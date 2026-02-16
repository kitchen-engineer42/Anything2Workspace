"""Parser for tabular data (xlsx, xls, csv) -> JSON."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import structlog

from ..config import settings
from ..schemas.result import ParseResult
from ..utils.file_utils import flatten_path
from .base import BaseParser

logger = structlog.get_logger(__name__)


class TabularParser(BaseParser):
    """
    Parser for tabular data (xlsx, xls, csv).
    Converts to JSON format instead of Markdown.
    """

    supported_extensions = [".xlsx", ".xls", ".csv"]
    parser_name = "tabular"

    def can_handle(self, file_path: Path) -> bool:
        """Check if file extension is supported."""
        return file_path.suffix.lower() in self.supported_extensions

    def parse(self, file_path: Path, output_dir: Path) -> ParseResult:
        """
        Convert tabular data to JSON.

        Args:
            file_path: Path to the input file
            output_dir: Directory to save output

        Returns:
            ParseResult with conversion details
        """
        started_at = datetime.now()

        logger.info("Tabular parsing", file=file_path.name)

        try:
            extension = file_path.suffix.lower()
            metadata = {}

            if extension == ".csv":
                # CSV: single sheet
                df = pd.read_csv(file_path)
                data = df.to_dict(orient="records")
                metadata["row_count"] = len(data)
                metadata["column_count"] = len(df.columns) if not df.empty else 0
            else:
                # Excel: may have multiple sheets
                xlsx = pd.ExcelFile(file_path)
                sheets_data = {}

                for sheet_name in xlsx.sheet_names:
                    df = pd.read_excel(xlsx, sheet_name=sheet_name)
                    sheets_data[sheet_name] = df.to_dict(orient="records")

                # Simplify structure for single sheet
                if len(sheets_data) == 1:
                    data = list(sheets_data.values())[0]
                    metadata["row_count"] = len(data)
                else:
                    data = sheets_data
                    metadata["sheet_count"] = len(sheets_data)
                    metadata["row_counts"] = {k: len(v) for k, v in sheets_data.items()}

            # Convert to JSON
            json_content = json.dumps(data, indent=2, ensure_ascii=False, default=str)

            # Generate flattened output filename
            output_name = flatten_path(file_path, settings.input_dir) + ".json"
            output_path = output_dir / output_name

            # Write output
            output_path.write_text(json_content, encoding="utf-8")

            completed_at = datetime.now()

            logger.info(
                "Tabular parsing success",
                file=file_path.name,
                output=output_path.name,
                chars=len(json_content),
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
                output_format="json",
                character_count=len(json_content),
                metadata=metadata,
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("Tabular parsing failed", file=file_path.name, error=str(e))

            return ParseResult(
                source_path=file_path,
                output_path=Path(""),
                source_type="file",
                parser_used=self.parser_name,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                output_format="json",
                error_message=str(e),
            )
