"""Front desk routing logic - determines which parser handles each file/URL."""

import re
from pathlib import Path

import structlog

from .config import settings
from .parsers import MarkItDownParser, MinerUParser, PaddleOCRVLParser, TabularParser
from .parsers.base import BaseParser
from .url_parsers import FireCrawlParser, RepomixParser, YouTubeParser
from .url_parsers.base import BaseURLParser
from .utils.file_utils import get_file_size_mb

logger = structlog.get_logger(__name__)


class Router:
    """
    Front desk script that routes files/URLs to appropriate parsers.
    Routing logic based on file extension, size, and URL patterns.
    """

    # File extension to parser mapping
    EXTENSION_MAP = {
        # MarkItDown handles these
        ".pdf": "markitdown",  # May fallback to MinerU
        ".ppt": "markitdown",
        ".pptx": "markitdown",
        ".doc": "markitdown",
        ".docx": "markitdown",
        ".html": "markitdown",
        ".htm": "markitdown",
        ".epub": "markitdown",
        ".md": "markitdown",
        ".txt": "markitdown",
        # Tabular data
        ".xlsx": "tabular",
        ".xls": "tabular",
        ".csv": "tabular",
    }

    # Extensions to silently skip (no useful text content)
    SKIP_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico", ".webp", ".tiff",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".flv", ".wmv",
        ".css", ".js", ".hhc", ".hhk",
    }

    # URL patterns for auto-detection
    YOUTUBE_PATTERNS = [
        r"youtube\.com/watch",
        r"youtu\.be/",
        r"youtube\.com/embed/",
    ]

    GITHUB_REPO_PATTERNS = [
        r"github\.com/[\w-]+/[\w-]+/?$",
        r"github\.com/[\w-]+/[\w-]+\.git$",
    ]

    def __init__(self):
        """Initialize all parsers."""
        # File parsers
        self.parsers: dict[str, BaseParser] = {
            "markitdown": MarkItDownParser(),
            "mineru": MinerUParser(),
            "paddleocr_vl": PaddleOCRVLParser(),
            "tabular": TabularParser(),
        }

        # URL parsers
        self.url_parsers: dict[str, BaseURLParser] = {
            "firecrawl": FireCrawlParser(),
            "youtube": YouTubeParser(),
            "repomix": RepomixParser(),
        }

    def route_file(self, file_path: Path) -> BaseParser:
        """
        Determine which parser to use for a file.

        Routing rules:
        1. Route by extension (MinerU disabled due to network issues)

        Args:
            file_path: Path to the file

        Returns:
            Appropriate parser instance

        Raises:
            ValueError: If file type is not supported
        """
        extension = file_path.suffix.lower()

        # Skip known non-text extensions silently
        if extension in self.SKIP_EXTENSIONS:
            logger.debug("Skipping non-text file", extension=extension, file=file_path.name)
            raise ValueError(f"Skipped non-text file: {extension}")

        # Get initial parser based on extension
        parser_key = self.EXTENSION_MAP.get(extension)

        if parser_key is None:
            logger.warning("No parser for extension", extension=extension, file=file_path.name)
            raise ValueError(f"Unsupported file type: {extension}")

        # NOTE: MinerU routing disabled due to network connectivity issues
        # to Alibaba Cloud Shanghai. Using MarkItDown for all PDFs.
        # To re-enable, uncomment the following:
        # if extension == ".pdf" and self._should_use_mineru_for_size(file_path):
        #     logger.info("Routing to MinerU (size threshold)", file=file_path.name)
        #     return self.parsers["mineru"]

        logger.debug("Routing file", file=file_path.name, parser=parser_key)
        return self.parsers[parser_key]

    def route_url(self, url: str) -> BaseURLParser:
        """
        Determine which URL parser to use based on URL pattern.

        Routing rules:
        1. YouTube URLs -> YouTubeParser
        2. GitHub repo URLs -> RepomixParser
        3. Other URLs -> FireCrawlParser

        Args:
            url: URL to parse

        Returns:
            Appropriate URL parser instance
        """
        url_lower = url.lower()

        # Check YouTube patterns
        for pattern in self.YOUTUBE_PATTERNS:
            if re.search(pattern, url_lower):
                logger.info("Routing URL to YouTube parser", url=url)
                return self.url_parsers["youtube"]

        # Check GitHub repo patterns
        for pattern in self.GITHUB_REPO_PATTERNS:
            if re.search(pattern, url_lower):
                # Make sure it's not a specific page (issues, PRs, etc.)
                excluded = ["/issues", "/pull", "/blob/", "/tree/", "/releases", "/actions"]
                if not any(ex in url_lower for ex in excluded):
                    logger.info("Routing URL to Repomix parser", url=url)
                    return self.url_parsers["repomix"]

        # Default to FireCrawl for general websites
        logger.info("Routing URL to FireCrawl parser", url=url)
        return self.url_parsers["firecrawl"]

    def _should_use_mineru_for_size(self, file_path: Path) -> bool:
        """
        Check if PDF should be routed to MinerU based on file size.

        Args:
            file_path: Path to the PDF file

        Returns:
            True if file exceeds size threshold
        """
        size_mb = get_file_size_mb(file_path)
        if size_mb > settings.max_pdf_size_mb:
            logger.info(
                "PDF exceeds size threshold",
                file=file_path.name,
                size_mb=f"{size_mb:.2f}",
                threshold_mb=settings.max_pdf_size_mb,
            )
            return True
        return False

    def should_fallback_to_ocr(self, text_content: str) -> bool:
        """
        Check if MarkItDown result should fallback to OCR.
        Called after MarkItDown parsing to check content quality.

        Args:
            text_content: Extracted text content from MarkItDown

        Returns:
            True if content quality is too low
        """
        # Count valid characters (alphanumeric + common punctuation)
        valid_chars = len(re.findall(r"[\w\s.,!?;:'\"-]", text_content))

        if valid_chars < settings.min_valid_chars:
            logger.info(
                "Low valid chars, fallback to OCR",
                valid_chars=valid_chars,
                threshold=settings.min_valid_chars,
            )
            return True

        return False

    def get_ocr_fallback_parser(self) -> BaseParser:
        """Get the PaddleOCR-VL parser for OCR fallback scenarios."""
        return self.parsers["paddleocr_vl"]
