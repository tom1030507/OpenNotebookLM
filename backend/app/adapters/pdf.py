"""PDF processing adapter."""
import io
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import structlog

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from pdfminer.high_level import extract_text, extract_pages
    from pdfminer.layout import LAParams, LTTextBox
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False

logger = structlog.get_logger()


class PDFAdapter:
    """Adapter for processing PDF files."""
    
    def __init__(self, use_pymupdf: bool = True):
        """Initialize PDF adapter.
        
        Args:
            use_pymupdf: Whether to use PyMuPDF (True) or pdfminer (False)
        """
        self.use_pymupdf = use_pymupdf and HAS_PYMUPDF
        
        if not HAS_PYMUPDF and not HAS_PDFMINER:
            raise ImportError("No PDF library available. Install PyMuPDF or pdfminer.six")
    
    def extract_text_from_file(self, file_path: str) -> Dict[str, any]:
        """Extract text from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        if self.use_pymupdf:
            return self._extract_with_pymupdf(file_path)
        else:
            return self._extract_with_pdfminer(file_path)
    
    def extract_text_from_bytes(self, pdf_bytes: bytes) -> Dict[str, any]:
        """Extract text from PDF bytes.
        
        Args:
            pdf_bytes: PDF file content as bytes
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        if self.use_pymupdf:
            return self._extract_bytes_with_pymupdf(pdf_bytes)
        else:
            return self._extract_bytes_with_pdfminer(pdf_bytes)
    
    def _extract_with_pymupdf(self, file_path: str) -> Dict[str, any]:
        """Extract text using PyMuPDF."""
        try:
            doc = fitz.open(file_path)
            pages = []
            full_text = []
            
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text()
                
                # Clean up text
                text = self._clean_text(text)
                
                pages.append({
                    "page_num": page_num,
                    "text": text,
                    "char_count": len(text),
                    "bbox": page.rect.irect  # Page bounding box
                })
                full_text.append(text)
            
            metadata = doc.metadata or {}
            doc.close()
            
            return {
                "text": "\n\n".join(full_text),
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {
                    "title": metadata.get("title", ""),
                    "author": metadata.get("author", ""),
                    "subject": metadata.get("subject", ""),
                    "keywords": metadata.get("keywords", ""),
                    "creator": metadata.get("creator", ""),
                    "producer": metadata.get("producer", ""),
                }
            }
        except Exception as e:
            logger.error("Failed to extract text with PyMuPDF", error=str(e))
            raise
    
    def _extract_bytes_with_pymupdf(self, pdf_bytes: bytes) -> Dict[str, any]:
        """Extract text from bytes using PyMuPDF."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages = []
            full_text = []
            
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text()
                text = self._clean_text(text)
                
                pages.append({
                    "page_num": page_num,
                    "text": text,
                    "char_count": len(text),
                })
                full_text.append(text)
            
            metadata = doc.metadata or {}
            doc.close()
            
            return {
                "text": "\n\n".join(full_text),
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {
                    "title": metadata.get("title", ""),
                    "author": metadata.get("author", ""),
                    "subject": metadata.get("subject", ""),
                }
            }
        except Exception as e:
            logger.error("Failed to extract text from bytes with PyMuPDF", error=str(e))
            raise
    
    def _extract_with_pdfminer(self, file_path: str) -> Dict[str, any]:
        """Extract text using pdfminer."""
        try:
            # Extract full text
            text = extract_text(file_path)
            text = self._clean_text(text)
            
            # Extract page-by-page
            pages = []
            laparams = LAParams()
            
            for page_num, page_layout in enumerate(extract_pages(file_path, laparams=laparams), start=1):
                page_text = []
                for element in page_layout:
                    if isinstance(element, LTTextBox):
                        page_text.append(element.get_text())
                
                page_content = "".join(page_text)
                page_content = self._clean_text(page_content)
                
                pages.append({
                    "page_num": page_num,
                    "text": page_content,
                    "char_count": len(page_content),
                })
            
            return {
                "text": text,
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {}  # pdfminer doesn't extract metadata easily
            }
        except Exception as e:
            logger.error("Failed to extract text with pdfminer", error=str(e))
            raise
    
    def _extract_bytes_with_pdfminer(self, pdf_bytes: bytes) -> Dict[str, any]:
        """Extract text from bytes using pdfminer."""
        try:
            # Create a file-like object from bytes
            pdf_file = io.BytesIO(pdf_bytes)
            
            # Extract full text
            text = extract_text(pdf_file)
            text = self._clean_text(text)
            
            # Reset file pointer for page extraction
            pdf_file.seek(0)
            
            # Extract page-by-page
            pages = []
            laparams = LAParams()
            
            for page_num, page_layout in enumerate(extract_pages(pdf_file, laparams=laparams), start=1):
                page_text = []
                for element in page_layout:
                    if isinstance(element, LTTextBox):
                        page_text.append(element.get_text())
                
                page_content = "".join(page_text)
                page_content = self._clean_text(page_content)
                
                pages.append({
                    "page_num": page_num,
                    "text": page_content,
                    "char_count": len(page_content),
                })
            
            return {
                "text": text,
                "pages": pages,
                "num_pages": len(pages),
                "metadata": {}
            }
        except Exception as e:
            logger.error("Failed to extract text from bytes with pdfminer", error=str(e))
            raise
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text.
        
        Args:
            text: Raw extracted text
            
        Returns:
            Cleaned text
        """
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove page headers/footers (common patterns)
        # This is a simple heuristic and may need adjustment
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Skip likely headers/footers (short lines with numbers)
            if len(line.strip()) < 5 and any(char.isdigit() for char in line):
                continue
            cleaned_lines.append(line)
        
        text = '\n'.join(cleaned_lines)
        
        # Remove multiple consecutive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    def extract_with_ocr(self, file_path: str) -> Dict[str, any]:
        """Extract text using OCR (placeholder for future implementation).
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        # This would use libraries like pytesseract or cloud OCR services
        raise NotImplementedError("OCR extraction not yet implemented")
