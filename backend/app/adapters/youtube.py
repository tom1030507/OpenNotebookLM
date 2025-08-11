"""YouTube transcript extraction adapter."""
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs
import structlog

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    HAS_YOUTUBE_API = True
except ImportError:
    HAS_YOUTUBE_API = False

logger = structlog.get_logger()


class YouTubeAdapter:
    """Adapter for extracting transcripts from YouTube videos."""
    
    def __init__(self, languages: List[str] = None):
        """Initialize YouTube adapter.
        
        Args:
            languages: Preferred languages for transcript (default: ['en'])
        """
        if not HAS_YOUTUBE_API:
            raise ImportError("youtube-transcript-api is not installed")
        
        self.languages = languages or ['en', 'zh-TW', 'zh-CN', 'zh']
    
    def extract_transcript(self, url: str) -> Dict[str, any]:
        """Extract transcript from a YouTube video.
        
        Args:
            url: YouTube video URL
            
        Returns:
            Dictionary containing transcript and metadata
        """
        try:
            # Extract video ID
            video_id = self._extract_video_id(url)
            if not video_id:
                raise ValueError(f"Could not extract video ID from URL: {url}")
            
            # Get transcript
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try to get transcript in preferred language
            transcript = None
            transcript_lang = None
            
            # First try manually created transcripts
            for lang in self.languages:
                try:
                    transcript = transcript_list.find_manually_created_transcript([lang])
                    transcript_lang = lang
                    break
                except:
                    continue
            
            # If no manual transcript, try generated ones
            if not transcript:
                for lang in self.languages:
                    try:
                        transcript = transcript_list.find_generated_transcript([lang])
                        transcript_lang = lang
                        break
                    except:
                        continue
            
            # If still no transcript, get any available
            if not transcript:
                try:
                    transcript = transcript_list.find_transcript(self.languages)
                    transcript_lang = transcript.language if hasattr(transcript, 'language') else 'unknown'
                except:
                    # Get first available transcript
                    for t in transcript_list:
                        transcript = t
                        transcript_lang = t.language if hasattr(t, 'language') else 'unknown'
                        break
            
            if not transcript:
                raise ValueError("No transcript available for this video")
            
            # Fetch the transcript
            transcript_data = transcript.fetch()
            
            # Process transcript
            processed = self._process_transcript(transcript_data)
            
            # Get video metadata (would need additional API for full metadata)
            metadata = {
                "video_id": video_id,
                "url": url,
                "language": transcript_lang,
                "is_generated": transcript.is_generated if hasattr(transcript, 'is_generated') else False,
                "duration": processed["duration"],
            }
            
            return {
                "video_id": video_id,
                "url": url,
                "text": processed["text"],
                "segments": processed["segments"],
                "duration": processed["duration"],
                "metadata": metadata,
                "language": transcript_lang,
            }
            
        except Exception as e:
            logger.error("Failed to extract YouTube transcript", url=url, error=str(e))
            raise
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL.
        
        Args:
            url: YouTube URL
            
        Returns:
            Video ID or None
        """
        # Handle different YouTube URL formats
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
            r'youtube\.com\/watch\?.*v=([^&\n?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # Try parsing with urlparse
        parsed = urlparse(url)
        if parsed.hostname in ['www.youtube.com', 'youtube.com']:
            query = parse_qs(parsed.query)
            if 'v' in query:
                return query['v'][0]
        elif parsed.hostname in ['youtu.be', 'www.youtu.be']:
            return parsed.path.lstrip('/')
        
        return None
    
    def _process_transcript(self, transcript_data: List[Dict]) -> Dict[str, any]:
        """Process raw transcript data.
        
        Args:
            transcript_data: Raw transcript from YouTube API
            
        Returns:
            Processed transcript with text and segments
        """
        segments = []
        full_text = []
        total_duration = 0
        
        for entry in transcript_data:
            start = entry.get('start', 0)
            duration = entry.get('duration', 0)
            text = entry.get('text', '').strip()
            
            # Clean text
            text = self._clean_transcript_text(text)
            
            if text:
                segments.append({
                    "start": start,
                    "end": start + duration,
                    "duration": duration,
                    "text": text,
                })
                full_text.append(text)
                total_duration = max(total_duration, start + duration)
        
        # Join text with proper spacing
        combined_text = ' '.join(full_text)
        
        # Add paragraph breaks at natural points (e.g., long pauses)
        paragraphs = self._create_paragraphs(segments)
        
        return {
            "text": combined_text,
            "paragraphs": paragraphs,
            "segments": segments,
            "duration": total_duration,
        }
    
    def _clean_transcript_text(self, text: str) -> str:
        """Clean transcript text.
        
        Args:
            text: Raw transcript text
            
        Returns:
            Cleaned text
        """
        # Remove music/sound effect annotations
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\(.*?\)', '', text)
        
        # Fix spacing
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters that might break processing
        text = text.replace('\n', ' ')
        text = text.replace('\r', '')
        
        return text.strip()
    
    def _create_paragraphs(self, segments: List[Dict]) -> str:
        """Create paragraphs from segments based on timing.
        
        Args:
            segments: List of transcript segments
            
        Returns:
            Text formatted with paragraphs
        """
        if not segments:
            return ""
        
        paragraphs = []
        current_paragraph = []
        last_end = 0
        
        for segment in segments:
            # If there's a gap > 2 seconds, start new paragraph
            if segment['start'] - last_end > 2.0 and current_paragraph:
                paragraphs.append(' '.join(current_paragraph))
                current_paragraph = []
            
            current_paragraph.append(segment['text'])
            last_end = segment['end']
        
        # Add remaining text
        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))
        
        return '\n\n'.join(paragraphs)
    
    def extract_video_info(self, url: str) -> Dict[str, any]:
        """Extract video information (placeholder for future implementation).
        
        This would require YouTube Data API for full metadata.
        
        Args:
            url: YouTube video URL
            
        Returns:
            Video metadata
        """
        video_id = self._extract_video_id(url)
        
        return {
            "video_id": video_id,
            "url": url,
            "title": f"YouTube Video {video_id}",  # Placeholder
            "description": "",  # Would need YouTube Data API
            "channel": "",  # Would need YouTube Data API
            "duration": 0,  # Would need YouTube Data API
            "views": 0,  # Would need YouTube Data API
            "likes": 0,  # Would need YouTube Data API
        }
