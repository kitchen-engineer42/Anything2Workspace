"""Abstract base class for URL parsers."""

import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.result import ParseResult


class BaseURLParser(ABC):
    """
    Abstract base class for URL parsers.

    Subclasses must implement:
    - parser_name: unique identifier for this parser
    - parse(): main parsing logic
    - can_handle(): check if parser can handle a URL
    """

    parser_name: str = "base_url"

    @abstractmethod
    def parse(self, url: str, output_dir: Path) -> ParseResult:
        """
        Parse a URL and save output.

        Args:
            url: URL to parse
            output_dir: Directory to save output

        Returns:
            ParseResult with status and metadata
        """
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """
        Check if this parser can handle the given URL.

        Args:
            url: URL to check

        Returns:
            True if this parser can handle the URL
        """
        pass

    def url_to_filename(self, url: str, max_length: int = 100) -> str:
        """
        Convert URL to safe filename.

        Args:
            url: URL to convert
            max_length: Maximum filename length

        Returns:
            Safe filename string
        """
        # Remove protocol
        name = re.sub(r"^https?://", "", url)
        # Replace unsafe characters
        name = re.sub(r"[^\w\-.]", "_", name)
        # Remove consecutive underscores
        name = re.sub(r"_+", "_", name)
        # Truncate if too long
        return name[:max_length]
