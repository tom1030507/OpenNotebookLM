"""Adapters module for document processing."""
from app.adapters.pdf import PDFAdapter
from app.adapters.url import URLAdapter
from app.adapters.youtube import YouTubeAdapter

__all__ = ["PDFAdapter", "URLAdapter", "YouTubeAdapter"]
