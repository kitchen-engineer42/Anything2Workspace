"""Parser for GitHub repositories using Repomix."""

import re
import subprocess
from datetime import datetime
from pathlib import Path

import structlog

from ..schemas.result import ParseResult
from .base import BaseURLParser

logger = structlog.get_logger(__name__)


class RepomixParser(BaseURLParser):
    """
    URL parser for GitHub repositories using Repomix.
    Converts entire repo to a single Markdown file.
    """

    parser_name = "repomix"

    def __init__(self):
        """Initialize and check if Repomix is installed."""
        self._repomix_available = self._check_repomix_installed()

    def _check_repomix_installed(self) -> bool:
        """
        Verify Repomix is installed.

        Returns:
            True if Repomix is available
        """
        try:
            result = subprocess.run(
                ["repomix", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.debug("Repomix found", version=result.stdout.strip())
                return True
            else:
                logger.warning("Repomix check failed. Install with: npm install -g repomix")
                return False
        except FileNotFoundError:
            logger.warning("Repomix not found. Install with: npm install -g repomix")
            return False
        except Exception as e:
            logger.warning("Repomix check error", error=str(e))
            return False

    def can_handle(self, url: str) -> bool:
        """
        Check if URL is a GitHub repository.

        Excludes specific pages like issues, PRs, blobs.
        """
        if "github.com" not in url.lower():
            return False

        # Exclude non-repo pages
        excluded_patterns = [
            "/issues",
            "/pull",
            "/blob/",
            "/tree/",
            "/releases",
            "/actions",
            "/wiki",
        ]

        return not any(pattern in url for pattern in excluded_patterns)

    def parse(self, url: str, output_dir: Path) -> ParseResult:
        """
        Clone repo and convert to Markdown using Repomix.

        Args:
            url: GitHub repository URL
            output_dir: Directory to save output

        Returns:
            ParseResult with repo details
        """
        started_at = datetime.now()

        logger.info("Repomix parsing", url=url)

        # Check if Repomix is available
        if not self._repomix_available:
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
                error_message="Repomix not installed. Run: npm install -g repomix",
            )

        try:
            # Extract repo name
            repo_name = self._extract_repo_name(url)

            # Generate output filename
            safe_name = repo_name.replace("/", "_")
            output_name = f"repo_{safe_name}.md"
            output_path = output_dir / output_name

            # Run Repomix on remote repo
            result = subprocess.run(
                [
                    "repomix",
                    "--remote",
                    url,
                    "--style",
                    "markdown",
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(f"Repomix failed: {error_msg}")

            # Read output to get character count
            content = output_path.read_text(encoding="utf-8") if output_path.exists() else ""

            completed_at = datetime.now()

            logger.info(
                "Repomix success",
                repo=repo_name,
                output=output_path.name,
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
                    "repo_name": repo_name,
                    "original_url": url,
                },
            )

        except subprocess.TimeoutExpired:
            completed_at = datetime.now()
            logger.error("Repomix timeout", url=url)

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
                error_message="Repomix timed out after 10 minutes",
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("Repomix failed", url=url, error=str(e))

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

    def _extract_repo_name(self, url: str) -> str:
        """
        Extract owner/repo from GitHub URL.

        Args:
            url: GitHub repository URL

        Returns:
            Repository name in "owner/repo" format
        """
        match = re.search(r"github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if match:
            return match.group(1)
        return "unknown_repo"
