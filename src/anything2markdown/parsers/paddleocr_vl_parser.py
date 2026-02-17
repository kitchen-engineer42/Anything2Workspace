"""Parser using PaddleOCR-VL via SiliconFlow API or local mlx-vlm for scanned PDF OCR."""

import base64
import re
from datetime import datetime
from pathlib import Path

import fitz
import httpx
import structlog
from openai import OpenAI

from ..config import settings
from ..schemas.result import ParseResult
from ..utils.file_utils import flatten_path
from .base import BaseParser

logger = structlog.get_logger(__name__)

OCR_PROMPT = "Convert this document page to markdown. Preserve all text content faithfully."

# PaddleOCR-VL emits bounding-box location tokens like <|LOC_401|> — strip them
_LOC_TOKEN_RE = re.compile(r"<\|LOC_\d+\|>")


class PaddleOCRVLParser(BaseParser):
    """
    Parser using PaddleOCR-VL vision-language model for scanned PDF OCR.
    Supports two backends:
    - SiliconFlow API (default): set SILICONFLOW_API_KEY
    - Local mlx-vlm server: set OCR_BASE_URL=http://localhost:8080
    """

    supported_extensions = [".pdf"]
    parser_name = "paddleocr_vl"

    def __init__(self):
        """Initialize the OpenAI client for OCR API."""
        self.client = None
        # Determine base URL: ocr_base_url overrides siliconflow_base_url (for local deployment)
        base_url = settings.ocr_base_url or settings.siliconflow_base_url
        api_key = settings.siliconflow_api_key or "local"
        if base_url:
            # For local servers, bypass system proxy to avoid connection issues
            http_client = None
            if "localhost" in base_url or "127.0.0.1" in base_url:
                http_client = httpx.Client(proxy=None)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=float(settings.ocr_page_timeout),
                max_retries=0,  # We handle retries ourselves to avoid stacking
                http_client=http_client,
            )

    def can_handle(self, file_path: Path) -> bool:
        """Check if file extension is supported."""
        return file_path.suffix.lower() in self.supported_extensions

    def parse(self, file_path: Path, output_dir: Path) -> ParseResult:
        """
        Parse a scanned PDF by rendering pages to images and running OCR.

        Args:
            file_path: Path to the input PDF
            output_dir: Directory to save output

        Returns:
            ParseResult with conversion details
        """
        started_at = datetime.now()

        if not self.client:
            completed_at = datetime.now()
            logger.error("PaddleOCR-VL: no OCR backend configured")
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
                error_message="No OCR backend configured (set SILICONFLOW_API_KEY or OCR_BASE_URL)",
            )

        logger.info("PaddleOCR-VL parsing", file=file_path.name)

        try:
            doc = fitz.open(file_path)
        except Exception as e:
            completed_at = datetime.now()
            logger.error("PaddleOCR-VL: failed to open PDF", error=str(e))
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
                error_message=f"Failed to open PDF: {e}",
            )

        page_count = len(doc)
        pages_failed = 0
        page_markdowns = []

        logger.info(
            "PaddleOCR-VL starting OCR",
            file=file_path.name,
            pages=page_count,
            dpi=settings.ocr_dpi,
            model=settings.paddleocr_model,
        )

        for page_num in range(page_count):
            page_md = self._ocr_page(doc[page_num], page_num + 1)
            if page_md is None:
                pages_failed += 1
                page_markdowns.append(f"<!-- OCR failed: page {page_num + 1} -->")
            else:
                page_markdowns.append(page_md)

            if (page_num + 1) % 10 == 0:
                logger.info(
                    "PaddleOCR-VL progress",
                    file=file_path.name,
                    page=page_num + 1,
                    total=page_count,
                    failed_so_far=pages_failed,
                )

        doc.close()

        content = "\n\n---\n\n".join(page_markdowns)

        output_name = flatten_path(file_path, settings.input_dir) + ".md"
        output_path = output_dir / output_name
        output_path.write_text(content, encoding="utf-8")

        completed_at = datetime.now()

        logger.info(
            "PaddleOCR-VL complete",
            file=file_path.name,
            pages=page_count,
            pages_failed=pages_failed,
            chars=len(content),
            duration=f"{(completed_at - started_at).total_seconds():.1f}s",
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
                "page_count": page_count,
                "pages_failed": pages_failed,
                "ocr_model": settings.paddleocr_model,
                "dpi": settings.ocr_dpi,
            },
        )

    def _ocr_page(self, page: fitz.Page, page_num: int) -> str | None:
        """
        OCR a single PDF page via the vision API.

        Args:
            page: PyMuPDF page object
            page_num: 1-based page number (for logging)

        Returns:
            Extracted markdown text, or None on failure
        """
        try:
            pix = page.get_pixmap(dpi=settings.ocr_dpi)
            png_bytes = pix.tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("ascii")
        except Exception as e:
            logger.warning("PaddleOCR-VL: failed to render page", page=page_num, error=str(e))
            return None

        # Try up to 2 attempts (initial + 1 retry)
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model=settings.paddleocr_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": OCR_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64}",
                                    },
                                },
                            ],
                        }
                    ],
                    max_tokens=4000,
                    temperature=0.1,
                )
                text = response.choices[0].message.content
                if text and text.strip():
                    # Strip <|LOC_xxx|> bounding-box tokens from PaddleOCR-VL output
                    clean = _LOC_TOKEN_RE.sub("", text).strip()
                    return clean if clean else None
                logger.warning("PaddleOCR-VL: empty response", page=page_num, attempt=attempt + 1)
            except Exception as e:
                logger.warning(
                    "PaddleOCR-VL: API call failed",
                    page=page_num,
                    attempt=attempt + 1,
                    error=str(e),
                )

        return None
