"""Parser using MinerU API for complex/scanned PDFs."""

import io
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
import structlog

from ..config import settings
from ..schemas.result import ParseResult
from ..utils.file_utils import flatten_path, get_file_size_mb
from .base import BaseParser

logger = structlog.get_logger(__name__)

# MinerU API configuration
MINERU_BASE_URL = "https://mineru.net/api/v4"
PAGES_PER_SPLIT = 400  # MinerU's recommended limit
MAX_FILE_SIZE_MB = 2  # Split files larger than this (network reliability to Alibaba Cloud)


class MinerUParser(BaseParser):
    """
    Parser using MinerU API for complex/scanned PDFs.

    For large PDFs:
    1. Split into chunks of 400 pages
    2. Upload each chunk via presigned URL
    3. Wait for extraction
    4. Download and combine results
    """

    supported_extensions = [".pdf"]
    parser_name = "mineru"

    def __init__(self, language: str = "ch"):
        """
        Initialize with API configuration.

        Args:
            language: OCR language - "ch" for Chinese, "en" for English
        """
        self.api_key = settings.mineru_api_key
        self.language = language
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def can_handle(self, file_path: Path) -> bool:
        """Check if file is a PDF."""
        return file_path.suffix.lower() in self.supported_extensions

    def parse(self, file_path: Path, output_dir: Path) -> ParseResult:
        """
        Parse PDF using MinerU API.

        For large PDFs, splits into chunks, processes each, then combines.

        Args:
            file_path: Path to the input PDF
            output_dir: Directory to save output

        Returns:
            ParseResult with conversion details
        """
        started_at = datetime.now()

        logger.info("MinerU parsing", file=file_path.name)

        # Check API key
        if not self.api_key:
            logger.error("MinerU API key not configured")
            return ParseResult(
                source_path=file_path,
                output_path=Path(""),
                source_type="file",
                parser_used=self.parser_name,
                status="failed",
                started_at=started_at,
                completed_at=datetime.now(),
                duration_seconds=0,
                output_format="markdown",
                error_message="MINERU_API_KEY not set in environment",
            )

        try:
            # Check if we need to split the PDF
            page_count = self._get_page_count(file_path)
            file_size_mb = get_file_size_mb(file_path)
            logger.info(
                "PDF info",
                file=file_path.name,
                pages=page_count,
                size_mb=f"{file_size_mb:.1f}",
            )

            # Split if too many pages OR file too large
            needs_split = page_count > PAGES_PER_SPLIT or file_size_mb > MAX_FILE_SIZE_MB

            if needs_split:
                # Calculate pages per split based on file size
                if file_size_mb > MAX_FILE_SIZE_MB:
                    # Estimate pages per 15MB
                    pages_per_mb = page_count / file_size_mb
                    pages_per_split = int(pages_per_mb * MAX_FILE_SIZE_MB * 0.8)  # 80% safety margin
                    pages_per_split = max(50, min(pages_per_split, PAGES_PER_SPLIT))
                else:
                    pages_per_split = PAGES_PER_SPLIT

                logger.info(
                    "Splitting PDF",
                    reason="large file" if file_size_mb > MAX_FILE_SIZE_MB else "many pages",
                    pages_per_split=pages_per_split,
                )
                content = self._process_large_pdf(file_path, page_count, pages_per_split)
            else:
                # Process directly
                content = self._process_single_pdf(file_path)

            # Generate flattened output filename
            output_name = flatten_path(file_path, settings.input_dir) + ".md"
            output_path = output_dir / output_name

            # Write output
            output_path.write_text(content, encoding="utf-8")

            completed_at = datetime.now()

            logger.info(
                "MinerU success",
                file=file_path.name,
                output=output_path.name,
                chars=len(content),
                pages=page_count,
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
                    "file_size_mb": get_file_size_mb(file_path),
                    "page_count": page_count,
                    "api_used": True,
                },
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("MinerU failed", file=file_path.name, error=str(e))

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

    def _get_page_count(self, file_path: Path) -> int:
        """Get the number of pages in a PDF."""
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(file_path)
            return len(reader.pages)
        except ImportError:
            logger.warning("PyPDF2 not installed, assuming large PDF")
            # If PyPDF2 not available, estimate based on file size
            # Rough estimate: 100KB per page
            size_kb = file_path.stat().st_size / 1024
            return max(1, int(size_kb / 100))

    def _split_pdf(self, file_path: Path, pages_per_split: int = PAGES_PER_SPLIT) -> list[Path]:
        """
        Split a PDF into smaller chunks.

        Args:
            file_path: Path to PDF file
            pages_per_split: Number of pages per split

        Returns:
            List of split PDF paths (in temp directory)
        """
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(file_path)
        total_pages = len(reader.pages)

        logger.info(
            "Splitting PDF",
            file=file_path.name,
            total_pages=total_pages,
            pages_per_split=pages_per_split,
        )

        split_files = []
        num_splits = (total_pages + pages_per_split - 1) // pages_per_split

        # Create temp directory for splits
        temp_dir = Path(tempfile.mkdtemp(prefix="mineru_splits_"))

        for i in range(num_splits):
            start_page = i * pages_per_split
            end_page = min((i + 1) * pages_per_split, total_pages)

            writer = PdfWriter()
            for page_num in range(start_page, end_page):
                writer.add_page(reader.pages[page_num])

            split_filename = f"{file_path.stem}_part{i + 1:02d}.pdf"
            split_path = temp_dir / split_filename

            with open(split_path, "wb") as output_file:
                writer.write(output_file)

            split_files.append(split_path)
            logger.info(
                "Created split",
                part=i + 1,
                pages=f"{start_page + 1}-{end_page}",
                file=split_filename,
            )

        return split_files

    def _process_large_pdf(
        self, file_path: Path, page_count: int, pages_per_split: int = PAGES_PER_SPLIT
    ) -> str:
        """
        Process a large PDF by splitting, converting each part, and combining.

        Args:
            file_path: Path to the large PDF
            page_count: Total page count
            pages_per_split: Number of pages per split

        Returns:
            Combined markdown content
        """
        # Split the PDF
        split_files = self._split_pdf(file_path, pages_per_split)

        try:
            # Process each split
            markdown_parts = []
            for i, split_path in enumerate(split_files, 1):
                logger.info(
                    "Processing split",
                    part=i,
                    total=len(split_files),
                    file=split_path.name,
                )
                content = self._process_single_pdf(split_path)
                markdown_parts.append(content)

            # Combine with separators
            combined = []
            for i, content in enumerate(markdown_parts, 1):
                if i > 1:
                    combined.append("\n\n---\n\n")
                    combined.append(f"# Part {i}\n\n")
                combined.append(content)

            return "".join(combined)

        finally:
            # Clean up temp files
            for split_path in split_files:
                try:
                    split_path.unlink()
                except Exception:
                    pass
            try:
                split_files[0].parent.rmdir()
            except Exception:
                pass

    def _process_single_pdf(self, file_path: Path) -> str:
        """
        Process a single PDF (or split) through MinerU API.

        Steps:
        1. Request presigned upload URL
        2. Upload file via PUT
        3. Poll for completion
        4. Download and extract results

        Args:
            file_path: Path to the PDF file

        Returns:
            Extracted markdown content
        """
        with httpx.Client(timeout=300) as client:
            # Step 1: Request upload URL
            upload_data = self._request_upload_url(client, file_path.name)
            batch_id = upload_data["batch_id"]
            upload_url = upload_data["upload_url"]

            logger.info("Got upload URL", batch_id=batch_id)

            # Step 2: Upload file
            self._upload_file(client, upload_url, file_path)

            # Step 3: Wait for extraction
            result = self._wait_for_completion(client, batch_id)

            # Step 4: Download results
            zip_url = result.get("full_zip_url")
            if not zip_url:
                raise RuntimeError("No download URL in results")

            content = self._download_and_extract(client, zip_url)

            return content

    def _request_upload_url(self, client: httpx.Client, filename: str) -> dict:
        """Request a presigned upload URL for a file."""
        url = f"{MINERU_BASE_URL}/file-urls/batch"

        payload = {
            "files": [
                {
                    "name": filename,
                    "is_ocr": True,
                    "enable_formula": True,
                    "enable_table": True,
                    "language": self.language,
                }
            ]
        }

        response = client.post(url, headers=self.headers, json=payload)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"API error: {data.get('msg', 'Unknown error')}")

        result = data["data"]
        return {
            "batch_id": result["batch_id"],
            "upload_url": result["file_urls"][0],
        }

    def _upload_file(self, client: httpx.Client, upload_url: str, file_path: Path) -> None:
        """Upload file to the presigned URL using PUT."""
        import requests  # Use requests for streaming upload (more reliable for large files)

        file_size = file_path.stat().st_size / (1024 * 1024)
        logger.info("Uploading file", file=file_path.name, size_mb=f"{file_size:.1f}")

        # Use requests for streaming upload (httpx has issues with large file uploads)
        with open(file_path, "rb") as f:
            response = requests.put(upload_url, data=f, timeout=600)

        response.raise_for_status()
        logger.info("Upload complete", file=file_path.name)

    def _wait_for_completion(
        self, client: httpx.Client, batch_id: str, poll_interval: int = 5, timeout: int = 1800
    ) -> dict:
        """Poll batch results until completion."""
        url = f"{MINERU_BASE_URL}/extract-results/batch/{batch_id}"
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Extraction timed out after {timeout} seconds")

            response = client.get(url, headers=self.headers)
            response.raise_for_status()

            data = response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"API error: {data.get('msg', 'Unknown error')}")

            results = data.get("data", {})
            extract_results = results.get("extract_result", [])

            if not extract_results:
                logger.debug("Waiting for task to start", elapsed=f"{elapsed:.0f}s")
                time.sleep(poll_interval)
                continue

            file_result = extract_results[0]
            state = file_result.get("state", "unknown")

            if state == "done":
                logger.info("Extraction complete", elapsed=f"{elapsed:.0f}s")
                return file_result
            elif state == "failed":
                raise RuntimeError(
                    f"Extraction failed: {file_result.get('err_msg', 'Unknown error')}"
                )
            else:
                progress = file_result.get("extract_progress", {})
                extracted = progress.get("extracted_pages", 0)
                total = progress.get("total_pages", "?")
                logger.info(
                    "Extraction in progress",
                    state=state,
                    pages=f"{extracted}/{total}",
                    elapsed=f"{elapsed:.0f}s",
                )
                time.sleep(poll_interval)

    def _download_and_extract(self, client: httpx.Client, zip_url: str) -> str:
        """Download results ZIP and extract markdown content."""
        logger.info("Downloading results")

        response = client.get(zip_url)
        response.raise_for_status()

        # Extract markdown from ZIP
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            # Look for full.md or any .md file
            md_files = [f for f in zf.namelist() if f.endswith(".md")]

            if not md_files:
                raise RuntimeError("No markdown file found in results")

            # Prefer full.md
            if "full.md" in md_files:
                md_file = "full.md"
            else:
                md_file = md_files[0]

            content = zf.read(md_file).decode("utf-8")

        logger.info("Downloaded markdown", chars=len(content))
        return content
