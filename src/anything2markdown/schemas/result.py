"""ParseResult schema - the output of all parsers."""

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ParseResult(BaseModel):
    """
    Schema for parser output.

    Design: Agile with fixed + JIT parts.
    - Fixed parts: Standard fields that all results must have
    - JIT parts: metadata dict for parser-specific info
    """

    # Fixed schema: Source information
    source_path: Path
    source_type: Literal["file", "url"]

    # Fixed schema: Output information
    output_path: Path
    output_format: Literal["markdown", "json"]

    # Fixed schema: Processing information
    parser_used: str
    status: Literal["success", "failed", "skipped"]

    # Fixed schema: Timing
    started_at: datetime
    completed_at: datetime
    duration_seconds: float

    # Fixed schema: Content metrics
    character_count: int = 0

    # Fixed schema: Error handling
    error_message: Optional[str] = None
    retry_count: int = 0

    # JIT schema: Flexible metadata for parser-specific info
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        """Pydantic config."""

        json_encoders = {
            Path: str,
            datetime: lambda v: v.isoformat(),
        }
