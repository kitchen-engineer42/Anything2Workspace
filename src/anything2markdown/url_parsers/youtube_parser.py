"""Parser for YouTube videos using transcript API."""

import re
from datetime import datetime
from pathlib import Path

import structlog
from youtube_transcript_api import YouTubeTranscriptApi

from ..schemas.result import ParseResult
from .base import BaseURLParser

logger = structlog.get_logger(__name__)


class YouTubeParser(BaseURLParser):
    """
    URL parser for YouTube videos.
    Extracts transcript and converts to Markdown.
    """

    parser_name = "youtube"

    # URL patterns for YouTube
    URL_PATTERNS = [
        r"youtube\.com/watch\?v=([^&]+)",
        r"youtu\.be/([^?]+)",
        r"youtube\.com/embed/([^?]+)",
    ]

    def can_handle(self, url: str) -> bool:
        """Check if URL is a YouTube video."""
        url_lower = url.lower()
        return any(
            [
                "youtube.com/watch" in url_lower,
                "youtu.be/" in url_lower,
                "youtube.com/embed/" in url_lower,
            ]
        )

    def parse(self, url: str, output_dir: Path) -> ParseResult:
        """
        Extract YouTube transcript and convert to Markdown.

        Args:
            url: YouTube video URL
            output_dir: Directory to save output

        Returns:
            ParseResult with transcript details
        """
        started_at = datetime.now()

        logger.info("YouTube parsing", url=url)

        try:
            # Extract video ID
            video_id = self._extract_video_id(url)

            # Fetch transcript
            transcript_data = self._fetch_transcript(video_id)

            # Format as Markdown
            content = self._format_as_markdown(url, video_id, transcript_data)

            # Generate output filename
            output_name = f"youtube_{video_id}.md"
            output_path = output_dir / output_name

            # Write output
            output_path.write_text(content, encoding="utf-8")

            completed_at = datetime.now()

            logger.info(
                "YouTube parsing success",
                video_id=video_id,
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
                    "video_id": video_id,
                    "transcript_segments": len(transcript_data),
                    "original_url": url,
                },
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("YouTube parsing failed", url=url, error=str(e))

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

    def _extract_video_id(self, url: str) -> str:
        """
        Extract video ID from YouTube URL.

        Args:
            url: YouTube URL

        Returns:
            Video ID string

        Raises:
            ValueError: If video ID cannot be extracted
        """
        for pattern in self.URL_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        raise ValueError(f"Could not extract video ID from: {url}")

    def _fetch_transcript(self, video_id: str) -> list[dict]:
        """
        Fetch transcript for a video.

        Tries manual transcripts first, then auto-generated.

        Args:
            video_id: YouTube video ID

        Returns:
            List of transcript segments
        """
        # Initialize API client
        api = YouTubeTranscriptApi()

        # Try to fetch with preferred languages first
        preferred_languages = ["en", "zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW"]

        try:
            # Use the fetch() shortcut which handles language fallback
            transcript = api.fetch(video_id, languages=preferred_languages)
            return list(transcript)
        except Exception:
            pass

        # Fall back to listing all transcripts
        try:
            transcript_list = api.list(video_id)

            # Try manually created first
            try:
                transcript = transcript_list.find_manually_created_transcript(preferred_languages)
                return list(transcript.fetch())
            except Exception:
                pass

            # Try auto-generated
            try:
                transcript = transcript_list.find_generated_transcript(preferred_languages)
                return list(transcript.fetch())
            except Exception:
                pass

            # Last resort: get any available transcript
            for transcript in transcript_list:
                return list(transcript.fetch())

        except Exception:
            pass

        raise ValueError(f"No transcript available for video: {video_id}")

    def _format_as_markdown(self, url: str, video_id: str, transcript: list) -> str:
        """
        Format transcript as readable Markdown.

        Args:
            url: Original video URL
            video_id: Video ID
            transcript: List of transcript segments (FetchedTranscriptSnippet objects)

        Returns:
            Formatted Markdown string
        """
        lines = [
            "# YouTube Video Transcript",
            "",
            f"**Video URL:** {url}",
            f"**Video ID:** {video_id}",
            "",
            "---",
            "",
            "## Transcript",
            "",
        ]

        # Group transcript into paragraphs
        current_paragraph = []
        for segment in transcript:
            # Handle both dict (old API) and object (new API) formats
            if hasattr(segment, "text"):
                text = segment.text.strip()
            else:
                text = segment.get("text", "").strip()

            if text:
                current_paragraph.append(text)
                # Start new paragraph after sentence endings
                if text.endswith((".", "!", "?", "...", "\u3002", "\uff01", "\uff1f")):
                    lines.append(" ".join(current_paragraph))
                    lines.append("")
                    current_paragraph = []

        # Add remaining text
        if current_paragraph:
            lines.append(" ".join(current_paragraph))

        return "\n".join(lines)
