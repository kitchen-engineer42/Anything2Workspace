"""Parser using Microsoft's MarkItDown library."""

from datetime import datetime
from pathlib import Path

import structlog
from markitdown import MarkItDown

from ..config import settings
from ..schemas.result import ParseResult
from ..utils.file_utils import flatten_path
from .base import BaseParser

logger = structlog.get_logger(__name__)


class MarkItDownParser(BaseParser):
    """
    Parser using Microsoft's MarkItDown library.
    Handles: PDF, PPT, PPTX, DOC, DOCX, MP3, MP4, images, HTML.
    """

    supported_extensions = [
        ".pdf",
        ".ppt",
        ".pptx",
        ".doc",
        ".docx",
        ".html",
        ".htm",
        ".epub",
        ".md",
        ".txt",
    ]
    parser_name = "markitdown"

    def __init__(self):
        """Initialize the MarkItDown converter."""
        self.converter = MarkItDown()

    def can_handle(self, file_path: Path) -> bool:
        """Check if file extension is supported."""
        return file_path.suffix.lower() in self.supported_extensions

    def parse(self, file_path: Path, output_dir: Path) -> ParseResult:
        """
        Convert file to Markdown using MarkItDown.

        Args:
            file_path: Path to the input file
            output_dir: Directory to save output

        Returns:
            ParseResult with conversion details
        """
        started_at = datetime.now()

        logger.info("MarkItDown parsing", file=file_path.name)

        try:
            # Convert file
            result = self.converter.convert(str(file_path))
            content = result.text_content

            # Generate flattened output filename
            output_name = flatten_path(file_path, settings.input_dir) + ".md"
            output_path = output_dir / output_name

            # Ensure parent directory exists (for grouped outputs)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Write output
            output_path.write_text(content, encoding="utf-8")

            completed_at = datetime.now()

            logger.info(
                "MarkItDown success",
                file=file_path.name,
                output=output_path.name,
                chars=len(content),
            )

            return ParseResult(
                source_path=file_path,
                output_path=output_path,
                source_type="file",
                parser_used=self.parser_name,
                status="success",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                output_format="markdown",
                character_count=len(content),
                metadata={
                    "original_extension": file_path.suffix,
                },
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("MarkItDown failed", file=file_path.name, error=str(e))

            return ParseResult(
                source_path=file_path,
                output_path=Path(""),
                source_type="file",
                parser_used=self.parser_name,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                output_format="markdown",
                error_message=str(e),
            )
