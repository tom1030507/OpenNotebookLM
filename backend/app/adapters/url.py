"""URL content extraction adapter."""
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse
import structlog
import requests
from bs4 import BeautifulSoup

try:
    from readability import Readability
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

logger = structlog.get_logger()


class URLAdapter:
    """Adapter for extracting content from URLs."""
    
    def __init__(self, timeout: int = 30, use_readability: bool = True):
        """Initialize URL adapter.
        
        Args:
            timeout: Request timeout in seconds
            use_readability: Whether to use readability for content extraction
        """
        self.timeout = timeout
        self.use_readability = use_readability and HAS_READABILITY
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    def extract_content(self, url: str) -> Dict[str, any]:
        """Extract content from a URL.
        
        Args:
            url: URL to extract content from
            
        Returns:
            Dictionary containing extracted content and metadata
        """
        try:
            # Fetch the page
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract metadata
            metadata = self._extract_metadata(soup, url)
            
            # Extract main content
            if self.use_readability:
                content = self._extract_with_readability(response.text, url)
            else:
                content = self._extract_with_beautifulsoup(soup)
            
            # Extract headings structure
            headings = self._extract_headings(soup)
            
            return {
                "url": url,
                "title": metadata.get("title", ""),
                "text": content["text"],
                "html": content.get("html", ""),
                "metadata": metadata,
                "headings": headings,
                "links": self._extract_links(soup, url),
            }
            
        except requests.RequestException as e:
            logger.error("Failed to fetch URL", url=url, error=str(e))
            raise
        except Exception as e:
            logger.error("Failed to extract content from URL", url=url, error=str(e))
            raise
    
    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, str]:
        """Extract metadata from HTML."""
        metadata = {
            "url": url,
            "domain": urlparse(url).netloc,
        }
        
        # Title
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text().strip()
        
        # Meta tags
        meta_tags = soup.find_all("meta")
        for tag in meta_tags:
            # Description
            if tag.get("name") == "description":
                metadata["description"] = tag.get("content", "")
            # Keywords
            elif tag.get("name") == "keywords":
                metadata["keywords"] = tag.get("content", "")
            # Author
            elif tag.get("name") == "author":
                metadata["author"] = tag.get("content", "")
            # Open Graph
            elif tag.get("property") == "og:title":
                metadata["og_title"] = tag.get("content", "")
            elif tag.get("property") == "og:description":
                metadata["og_description"] = tag.get("content", "")
            elif tag.get("property") == "og:image":
                metadata["og_image"] = tag.get("content", "")
        
        return metadata
    
    def _extract_with_readability(self, html: str, url: str) -> Dict[str, str]:
        """Extract content using readability library."""
        try:
            doc = Readability(html, url)
            summary = doc.summary()
            
            # Parse the summary to extract text
            soup = BeautifulSoup(summary, 'html.parser')
            text = soup.get_text(separator='\n', strip=True)
            
            return {
                "text": self._clean_text(text),
                "html": summary,
                "title": doc.title(),
            }
        except Exception as e:
            logger.warning("Readability extraction failed, falling back", error=str(e))
            # Fall back to BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            return self._extract_with_beautifulsoup(soup)
    
    def _extract_with_beautifulsoup(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract content using BeautifulSoup."""
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        
        # Try to find main content areas
        main_content = None
        
        # Common content selectors
        content_selectors = [
            "main",
            "article",
            "[role='main']",
            ".main-content",
            "#main-content",
            ".content",
            "#content",
            ".post",
            ".entry-content",
        ]
        
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        # If no main content found, use body
        if not main_content:
            main_content = soup.body if soup.body else soup
        
        # Extract text
        text = main_content.get_text(separator='\n', strip=True)
        
        return {
            "text": self._clean_text(text),
            "html": str(main_content),
        }
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, any]]:
        """Extract heading structure from HTML."""
        headings = []
        
        for level in range(1, 7):
            for heading in soup.find_all(f'h{level}'):
                headings.append({
                    "level": level,
                    "text": heading.get_text(strip=True),
                    "tag": f"h{level}",
                })
        
        return headings
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract links from HTML."""
        links = []
        base_domain = urlparse(base_url).netloc
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)
            
            # Skip empty links
            if not href or href == '#':
                continue
            
            # Determine if internal or external
            parsed = urlparse(href)
            is_internal = not parsed.netloc or parsed.netloc == base_domain
            
            links.append({
                "href": href,
                "text": text[:100],  # Limit text length
                "is_internal": is_internal,
            })
        
        return links[:100]  # Limit to 100 links
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove multiple consecutive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove common noise patterns
        noise_patterns = [
            r'Cookie Policy',
            r'Privacy Policy',
            r'Terms of Service',
            r'Accept Cookies',
            r'We use cookies',
        ]
        
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        return text.strip()
