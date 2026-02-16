"""Main pipeline orchestration for Anything2Markdown."""

from datetime import datetime
from pathlib import Path

import structlog

from .config import settings
from .router import Router
from .schemas.result import ParseResult
from .utils.file_utils import ensure_directory, read_url_list, walk_directory
from .utils.retry import with_retry

logger = structlog.get_logger(__name__)


class Anything2MarkdownPipeline:
    """
    Main pipeline orchestrating the parsing of files and URLs.
    Processes sequentially as specified.
    """

    def __init__(self):
        """Initialize the pipeline."""
        self.router = Router()
        self.results: list[ParseResult] = []

        # Ensure output directory exists
        ensure_directory(settings.output_dir)

    def run(self) -> list[ParseResult]:
        """
        Execute the full pipeline.

        Processes:
        1. All files in input directory (recursively)
        2. All URLs from urls.txt

        Returns:
            List of ParseResult for all processed items
        """
        logger.info(
            "Starting Anything2Markdown pipeline",
            input_dir=str(settings.input_dir),
            output_dir=str(settings.output_dir),
        )

        start_time = datetime.now()
        self.results = []

        # Process files in input directory
        file_count = 0
        for file_path in walk_directory(settings.input_dir):
            result = self._process_file_with_retry(file_path)
            self.results.append(result)
            file_count += 1

        logger.info("File processing complete", files_processed=file_count)

        # Process URLs from urls.txt
        url_file = settings.input_dir / "urls.txt"
        url_count = 0
        if url_file.exists():
            urls = read_url_list(url_file)
            for url in urls:
                result = self._process_url_with_retry(url)
                self.results.append(result)
                url_count += 1

        logger.info("URL processing complete", urls_processed=url_count)

        # Log summary
        duration = (datetime.now() - start_time).total_seconds()
        self._log_summary(duration)

        return self.results

    def _process_file_with_retry(self, file_path: Path) -> ParseResult:
        """
        Process a single file with retry logic.

        Wraps _process_file with retry decorator behavior.
        """
        try:
            return self._process_file_impl(file_path)
        except Exception as e:
            # Retry once
            logger.warning("First attempt failed, retrying", file=file_path.name, error=str(e))
            try:
                return self._process_file_impl(file_path)
            except Exception as retry_error:
                logger.error(
                    "All attempts failed",
                    file=file_path.name,
                    error=str(retry_error),
                )
                return ParseResult(
                    source_path=file_path,
                    output_path=Path(""),
                    source_type="file",
                    parser_used="none",
                    status="failed",
                    started_at=datetime.now(),
                    completed_at=datetime.now(),
                    duration_seconds=0,
                    output_format="markdown",
                    error_message=str(retry_error),
                    retry_count=1,
                )

    def _process_file_impl(self, file_path: Path) -> ParseResult:
        """
        Process a single file.

        Handles:
        1. Route to appropriate parser
        2. Parse file
        3. Check for MinerU fallback (PDFs with low quality)

        Args:
            file_path: Path to the file

        Returns:
            ParseResult from parsing
        """
        logger.info("Processing file", file=file_path.name)

        try:
            # Route to appropriate parser
            parser = self.router.route_file(file_path)

            # Parse the file
            result = parser.parse(file_path, settings.output_dir)

            # Check for MinerU fallback (only for PDFs parsed by MarkItDown)
            if (
                file_path.suffix.lower() == ".pdf"
                and result.status == "success"
                and parser.parser_name == "markitdown"
                and result.output_path.exists()
            ):
                # Read output and check quality
                output_content = result.output_path.read_text(encoding="utf-8")
                if self.router.should_fallback_to_mineru(output_content):
                    logger.info("Falling back to MinerU", file=file_path.name)

                    # Remove low-quality output
                    result.output_path.unlink(missing_ok=True)

                    # Re-parse with MinerU
                    mineru_parser = self.router.get_mineru_parser()
                    result = mineru_parser.parse(file_path, settings.output_dir)

            return result

        except ValueError as e:
            # Unsupported file type
            logger.warning("Skipping unsupported file", file=file_path.name, error=str(e))
            return ParseResult(
                source_path=file_path,
                output_path=Path(""),
                source_type="file",
                parser_used="none",
                status="skipped",
                started_at=datetime.now(),
                completed_at=datetime.now(),
                duration_seconds=0,
                output_format="markdown",
                error_message=str(e),
            )

    def _process_url_with_retry(self, url: str) -> ParseResult:
        """
        Process a single URL with retry logic.

        Wraps _process_url_impl with retry behavior.
        """
        try:
            return self._process_url_impl(url)
        except Exception as e:
            # Retry once
            logger.warning("First attempt failed, retrying", url=url, error=str(e))
            try:
                return self._process_url_impl(url)
            except Exception as retry_error:
                logger.error("All attempts failed", url=url, error=str(retry_error))
                return ParseResult(
                    source_path=Path(url),
                    output_path=Path(""),
                    source_type="url",
                    parser_used="none",
                    status="failed",
                    started_at=datetime.now(),
                    completed_at=datetime.now(),
                    duration_seconds=0,
                    output_format="markdown",
                    error_message=str(retry_error),
                    retry_count=1,
                )

    def _process_url_impl(self, url: str) -> ParseResult:
        """
        Process a single URL.

        Args:
            url: URL to process

        Returns:
            ParseResult from parsing
        """
        logger.info("Processing URL", url=url)

        try:
            # Route to appropriate parser
            parser = self.router.route_url(url)

            # Parse the URL
            return parser.parse(url, settings.output_dir)

        except Exception as e:
            logger.error("URL processing failed", url=url, error=str(e))
            raise

    def _log_summary(self, duration: float):
        """
        Log pipeline execution summary.

        Args:
            duration: Total execution time in seconds
        """
        success = sum(1 for r in self.results if r.status == "success")
        failed = sum(1 for r in self.results if r.status == "failed")
        skipped = sum(1 for r in self.results if r.status == "skipped")

        logger.info(
            "Pipeline completed",
            duration_seconds=f"{duration:.2f}",
            total_processed=len(self.results),
            success=success,
            failed=failed,
            skipped=skipped,
        )

    def get_summary(self) -> dict:
        """
        Get pipeline execution summary as dict.

        Returns:
            Summary statistics
        """
        return {
            "total": len(self.results),
            "success": sum(1 for r in self.results if r.status == "success"),
            "failed": sum(1 for r in self.results if r.status == "failed"),
            "skipped": sum(1 for r in self.results if r.status == "skipped"),
            "results": self.results,
        }
