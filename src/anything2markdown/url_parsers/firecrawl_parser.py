"""Parser for websites using FireCrawl API."""

from datetime import datetime
from pathlib import Path

import structlog
from firecrawl import FirecrawlApp

from ..config import settings
from ..schemas.result import ParseResult
from .base import BaseURLParser

logger = structlog.get_logger(__name__)


class FireCrawlParser(BaseURLParser):
    """
    URL parser using FireCrawl for multi-page websites.
    Crawls and combines all pages into a single Markdown file.
    """

    parser_name = "firecrawl"

    def __init__(self):
        """Initialize with API configuration."""
        self.api_key = settings.firecrawl_api_key
        self._client = None

    @property
    def client(self) -> FirecrawlApp:
        """Lazy-load FireCrawl client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("FIRECRAWL_API_KEY not set in environment")
            self._client = FirecrawlApp(api_key=self.api_key)
        return self._client

    def can_handle(self, url: str) -> bool:
        """Check if URL is a valid HTTP(S) URL."""
        return url.startswith(("http://", "https://"))

    def parse(self, url: str, output_dir: Path) -> ParseResult:
        """
        Crawl website and convert to Markdown.

        Args:
            url: Website URL to crawl
            output_dir: Directory to save output

        Returns:
            ParseResult with crawl details
        """
        started_at = datetime.now()

        logger.info("FireCrawl parsing", url=url)

        # Check API key
        if not self.api_key:
            logger.error("FireCrawl API key not configured")
            return ParseResult(
                source_path=Path(url),
                output_path=Path(""),
                source_type="url",
                parser_used=self.parser_name,
                status="failed",
                started_at=started_at,
                completed_at=datetime.now(),
                duration_seconds=0,
                output_format="markdown",
                error_message="FIRECRAWL_API_KEY not set in environment",
            )

        try:
            # Crawl the website using the new API
            result = self.client.crawl(
                url=url,
                limit=50,  # Max pages to crawl
                scrape_options={"formats": ["markdown"]},
            )

            # Combine all pages into single Markdown
            pages_content = []

            # Handle different result formats
            if hasattr(result, "data"):
                crawled_data = result.data
            elif isinstance(result, dict):
                crawled_data = result.get("data", [])
            elif isinstance(result, list):
                crawled_data = result
            else:
                crawled_data = []

            for page in crawled_data:
                # Handle both dict and object formats
                if hasattr(page, "url"):
                    page_url = page.url or getattr(page, "source_url", "")
                    page_md = getattr(page, "markdown", "") or getattr(page, "content", "")
                elif isinstance(page, dict):
                    page_url = page.get("url", page.get("sourceURL", ""))
                    page_md = page.get("markdown", page.get("content", ""))
                else:
                    continue

                if page_md:
                    pages_content.append(f"# {page_url}\n\n{page_md}")

            content = "\n\n---\n\n".join(pages_content) if pages_content else ""

            # Generate output filename
            output_name = f"website_{self.url_to_filename(url)}.md"
            output_path = output_dir / output_name

            # Write output
            output_path.write_text(content, encoding="utf-8")

            completed_at = datetime.now()

            logger.info(
                "FireCrawl success",
                url=url,
                output=output_path.name,
                pages=len(pages_content),
                chars=len(content),
            )

            return ParseResult(
                source_path=Path(url),
                output_path=output_path,
                source_type="url",
                parser_used=self.parser_name,
                status="success",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                output_format="markdown",
                character_count=len(content),
                metadata={
                    "pages_crawled": len(pages_content),
                    "original_url": url,
                },
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("FireCrawl failed", url=url, error=str(e))

            return ParseResult(
                source_path=Path(url),
                output_path=Path(""),
                source_type="url",
                parser_used=self.parser_name,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                output_format="markdown",
                error_message=str(e),
            )
