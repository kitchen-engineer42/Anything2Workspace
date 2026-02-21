"""Parser for Bilibili videos using yt-dlp subtitles and WhisperX fallback."""

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

import structlog

from ..config import settings
from ..schemas.result import ParseResult
from .base import BaseURLParser

logger = structlog.get_logger(__name__)


class BilibiliParser(BaseURLParser):
    """
    URL parser for Bilibili videos.
    Extracts subtitles via yt-dlp, falls back to WhisperX transcription.
    """

    parser_name = "bilibili"

    URL_PATTERNS = [
        r"bilibili\.com/video/",
        r"b23\.tv/",
        r"bilibili\.com/bangumi/",
    ]

    def __init__(self):
        """Initialize and check if WhisperX is installed."""
        self._whisperx_available: bool | None = None

    def _cookie_opts(self) -> dict:
        """
        Build yt-dlp cookie options.

        Prefers cookiefile if set, otherwise uses cookies_from_browser.
        Bilibili requires cookies to avoid HTTP 412.
        """
        if settings.bilibili_cookies_file:
            return {"cookiefile": settings.bilibili_cookies_file}
        if settings.bilibili_cookies_from_browser:
            return {"cookiesfrombrowser": (settings.bilibili_cookies_from_browser,)}
        return {}

    def can_handle(self, url: str) -> bool:
        """Check if URL is a Bilibili video."""
        url_lower = url.lower()
        return any(
            re.search(pattern, url_lower) for pattern in self.URL_PATTERNS
        )

    def parse(self, url: str, output_dir: Path) -> ParseResult:
        """
        Extract Bilibili video transcript and convert to Markdown.

        Tries CC subtitles first via yt-dlp. If unavailable, downloads audio
        and transcribes with WhisperX.

        Args:
            url: Bilibili video URL
            output_dir: Directory to save output

        Returns:
            ParseResult with transcript details
        """
        started_at = datetime.now()

        logger.info("Bilibili parsing", url=url)

        try:
            import yt_dlp

            # Extract video info (title, video ID)
            video_id, title = self._extract_info(url)

            # Strategy 1: Try CC subtitles
            segments = self._try_subtitles(url)

            # Strategy 2: WhisperX fallback
            if segments is None:
                logger.info("No subtitles found, trying WhisperX", video_id=video_id)
                if not self._check_whisperx():
                    raise RuntimeError(
                        "No subtitles available and faster-whisper not installed. "
                        "Install with: pip install faster-whisper"
                    )
                segments = self._download_and_transcribe(url)

            # Format as Markdown
            content = self._format_as_markdown(url, video_id, title, segments)

            # Write output
            output_name = f"bilibili_{video_id}.md"
            output_path = output_dir / output_name
            output_path.write_text(content, encoding="utf-8")

            completed_at = datetime.now()

            logger.info(
                "Bilibili parsing success",
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
                    "title": title,
                    "transcript_segments": len(segments),
                    "original_url": url,
                },
            )

        except Exception as e:
            completed_at = datetime.now()
            logger.error("Bilibili parsing failed", url=url, error=str(e))

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

    def _extract_info(self, url: str) -> tuple[str, str]:
        """
        Extract video ID and title from Bilibili URL.

        Args:
            url: Bilibili video URL

        Returns:
            Tuple of (video_id, title)

        Raises:
            ValueError: If video info cannot be extracted
        """
        import yt_dlp

        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            **self._cookie_opts(),
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise ValueError(f"Could not extract video info from: {url}")

            video_id = info.get("id", "")
            title = info.get("title", "Untitled")

            # Try to get BV ID from the URL or webpage_url
            bv_match = re.search(r"(BV[a-zA-Z0-9]+)", info.get("webpage_url", url))
            if bv_match:
                video_id = bv_match.group(1)

            if not video_id:
                raise ValueError(f"Could not extract video ID from: {url}")

            return video_id, title

    def _check_whisperx(self) -> bool:
        """
        Check if faster-whisper is available. Caches the result.

        Returns:
            True if faster-whisper is importable
        """
        if self._whisperx_available is not None:
            return self._whisperx_available

        try:
            import faster_whisper  # noqa: F401
            self._whisperx_available = True
        except ImportError:
            self._whisperx_available = False
            logger.warning(
                "faster-whisper not found. Install with: pip install faster-whisper"
            )

        return self._whisperx_available

    def _try_subtitles(self, url: str) -> list[dict] | None:
        """
        Try to extract CC subtitles via yt-dlp without downloading video.

        Args:
            url: Bilibili video URL

        Returns:
            List of {"text": ..., "start": ...} segments, or None if no subtitles
        """
        import yt_dlp

        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh", "zh-CN", "en", "ai-zh"],
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            **self._cookie_opts(),
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return None

            # Check for subtitles in requested_subtitles (what yt-dlp resolved)
            req_subs = info.get("requested_subtitles") or {}
            # Also check all available subtitles
            all_subs = info.get("subtitles") or {}
            auto_subs = info.get("automatic_captions") or {}

            # Preferred language order
            lang_priority = ["zh-Hans", "zh", "zh-CN", "en", "ai-zh"]

            # Try requested subtitles first
            for lang in lang_priority:
                sub_info = req_subs.get(lang)
                if sub_info:
                    segments = self._fetch_subtitle_data(ydl, sub_info, lang)
                    if segments:
                        logger.info("Found subtitles via requested_subtitles", lang=lang)
                        return segments

            # Try manual subtitles
            for lang in lang_priority:
                sub_info = all_subs.get(lang)
                if sub_info:
                    segments = self._parse_subtitle_formats(ydl, sub_info, lang)
                    if segments:
                        logger.info("Found manual subtitles", lang=lang)
                        return segments

            # Try automatic captions
            for lang in lang_priority:
                sub_info = auto_subs.get(lang)
                if sub_info:
                    segments = self._parse_subtitle_formats(ydl, sub_info, lang)
                    if segments:
                        logger.info("Found automatic captions", lang=lang)
                        return segments

        return None

    def _fetch_subtitle_data(
        self, ydl, sub_info: dict, lang: str
    ) -> list[dict] | None:
        """Fetch and parse a single subtitle entry from requested_subtitles."""
        # sub_info has 'url', 'ext', possibly 'data'
        if "data" in sub_info:
            return self._parse_subtitle_content(sub_info["data"], sub_info.get("ext", "json"))

        sub_url = sub_info.get("url")
        if not sub_url:
            return None

        try:
            data = ydl.urlopen(sub_url).read().decode("utf-8")
            return self._parse_subtitle_content(data, sub_info.get("ext", "json"))
        except Exception as e:
            logger.debug("Failed to fetch subtitle URL", lang=lang, error=str(e))
            return None

    def _parse_subtitle_formats(
        self, ydl, sub_formats: list, lang: str
    ) -> list[dict] | None:
        """Try each format variant for a subtitle language."""
        # Prefer json3, then srv3, then vtt, then any
        preferred_exts = ["json3", "srv3", "vtt", "srt", "json"]
        sorted_formats = sorted(
            sub_formats,
            key=lambda f: (
                preferred_exts.index(f.get("ext", ""))
                if f.get("ext", "") in preferred_exts
                else len(preferred_exts)
            ),
        )
        for fmt in sorted_formats:
            sub_url = fmt.get("url")
            if not sub_url:
                continue
            try:
                data = ydl.urlopen(sub_url).read().decode("utf-8")
                segments = self._parse_subtitle_content(data, fmt.get("ext", "json"))
                if segments:
                    return segments
            except Exception as e:
                logger.debug("Failed subtitle format", ext=fmt.get("ext"), error=str(e))
                continue
        return None

    def _parse_subtitle_content(self, data: str, ext: str) -> list[dict] | None:
        """
        Parse subtitle content into segments.

        Args:
            data: Raw subtitle content
            ext: Format extension (json3, srv3, vtt, srt, json)

        Returns:
            List of {"text": ..., "start": ...} or None
        """
        segments = []

        try:
            if ext in ("json3", "json"):
                parsed = json.loads(data)
                # json3 format: {"events": [{"segs": [{"utf8": "..."}], "tStartMs": ...}]}
                events = parsed.get("events") or parsed.get("body") or []
                if isinstance(events, list):
                    for event in events:
                        # json3 style
                        if "segs" in event:
                            text = "".join(
                                seg.get("utf8", "") for seg in event.get("segs", [])
                            ).strip()
                            if text and text != "\n":
                                segments.append({
                                    "text": text,
                                    "start": event.get("tStartMs", 0) / 1000,
                                })
                        # Bilibili API style: {"from": ..., "to": ..., "content": "..."}
                        elif "content" in event:
                            text = event["content"].strip()
                            if text:
                                segments.append({
                                    "text": text,
                                    "start": event.get("from", 0),
                                })
                        # Simple segment style
                        elif "text" in event:
                            text = event["text"].strip()
                            if text:
                                segments.append({
                                    "text": text,
                                    "start": event.get("start", 0),
                                })

            elif ext in ("srv3", "srv2", "srv1"):
                # XML-based format
                import xml.etree.ElementTree as ET
                root = ET.fromstring(data)
                for p in root.iter("p"):
                    text = (p.text or "").strip()
                    if text:
                        t = int(p.get("t", "0"))
                        segments.append({"text": text, "start": t / 1000})

            elif ext == "vtt":
                # WebVTT format
                lines = data.strip().split("\n")
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    # Look for timestamp lines
                    if "-->" in line:
                        # Next lines until blank are the text
                        text_parts = []
                        i += 1
                        while i < len(lines) and lines[i].strip():
                            text_parts.append(lines[i].strip())
                            i += 1
                        text = " ".join(text_parts)
                        # Remove VTT tags
                        text = re.sub(r"<[^>]+>", "", text).strip()
                        if text:
                            # Parse start time from "00:00:01.000 --> 00:00:02.000"
                            time_match = re.match(
                                r"(\d+):(\d+):(\d+)\.(\d+)", line
                            )
                            start = 0.0
                            if time_match:
                                h, m, s, ms = time_match.groups()
                                start = (
                                    int(h) * 3600
                                    + int(m) * 60
                                    + int(s)
                                    + int(ms) / 1000
                                )
                            segments.append({"text": text, "start": start})
                    i += 1

            elif ext == "srt":
                # SubRip format
                blocks = re.split(r"\n\n+", data.strip())
                for block in blocks:
                    block_lines = block.strip().split("\n")
                    if len(block_lines) >= 3:
                        time_line = block_lines[1]
                        text = " ".join(block_lines[2:]).strip()
                        text = re.sub(r"<[^>]+>", "", text)
                        if text:
                            time_match = re.match(
                                r"(\d+):(\d+):(\d+),(\d+)", time_line
                            )
                            start = 0.0
                            if time_match:
                                h, m, s, ms = time_match.groups()
                                start = (
                                    int(h) * 3600
                                    + int(m) * 60
                                    + int(s)
                                    + int(ms) / 1000
                                )
                            segments.append({"text": text, "start": start})

        except Exception as e:
            logger.debug("Failed to parse subtitle content", ext=ext, error=str(e))
            return None

        return segments if segments else None

    def _download_and_transcribe(self, url: str) -> list[dict]:
        """
        Download audio and transcribe with faster-whisper.

        Uses faster-whisper Python library directly (installed as a
        whisperx/faster-whisper dependency) for much better performance
        than shelling out to the whisperx CLI.

        Args:
            url: Bilibili video URL

        Returns:
            List of {"text": ..., "start": ...} segments

        Raises:
            RuntimeError: If download or transcription fails
        """
        import yt_dlp

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Download audio only
            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "wav"}
                ],
                "outtmpl": str(temp_path / "%(id)s.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                **self._cookie_opts(),
            }

            logger.info("Downloading audio for transcription")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise RuntimeError("Failed to download audio")

            # Find the downloaded wav file
            wav_files = list(temp_path.glob("*.wav"))
            if not wav_files:
                raise RuntimeError("Audio download produced no WAV file")

            audio_path = wav_files[0]
            logger.info("Audio downloaded", path=audio_path.name)

            # Transcribe with faster-whisper (Python library)
            from faster_whisper import WhisperModel

            model_size = settings.whisperx_model
            try:
                import torch
                if torch.cuda.is_available():
                    device, compute_type = "cuda", "float16"
                else:
                    device, compute_type = "cpu", "int8"
            except ImportError:
                device, compute_type = "cpu", "int8"

            logger.info(
                "Running faster-whisper",
                model=model_size,
                device=device,
                compute_type=compute_type,
            )

            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            raw_segments, transcribe_info = model.transcribe(
                str(audio_path), language="zh"
            )

            segments = []
            for seg in raw_segments:
                text = seg.text.strip()
                if text:
                    segments.append({
                        "text": text,
                        "start": seg.start,
                    })

            if not segments:
                raise RuntimeError("Transcription produced no segments")

            logger.info(
                "Transcription complete",
                segments=len(segments),
                language=transcribe_info.language,
            )
            return segments

    def _format_as_markdown(
        self, url: str, video_id: str, title: str, segments: list[dict]
    ) -> str:
        """
        Format transcript as readable Markdown.

        Args:
            url: Original video URL
            video_id: Bilibili video ID (BV...)
            title: Video title
            segments: List of transcript segments

        Returns:
            Formatted Markdown string
        """
        lines = [
            "# Bilibili Video Transcript",
            "",
            f"**Video URL:** {url}",
            f"**Video ID:** {video_id}",
            f"**Title:** {title}",
            "",
            "---",
            "",
            "## Transcript",
            "",
        ]

        # Group transcript into paragraphs
        current_paragraph = []
        for segment in segments:
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
