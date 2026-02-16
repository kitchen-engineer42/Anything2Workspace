"""Step 3: Proofreading/Confidence — RAG-based verification with web search."""

import json
import re
from pathlib import Path
from typing import Any, Optional

import structlog

from chunks2skus.config import settings
from chunks2skus.postprocessors.base import BasePostprocessor
from chunks2skus.schemas.postprocessing import ConfidenceEntry, ConfidenceReport
from chunks2skus.schemas.sku import SKUType
from chunks2skus.utils.jina_client import search_web
from chunks2skus.utils.llm_client import call_llm, parse_json_response

logger = structlog.get_logger(__name__)


CONFIDENCE_SYSTEM_PROMPT = (
    "You are a fact-checking assistant that evaluates knowledge units. "
    "Output ONLY valid JSON."
)

CONFIDENCE_PROMPT = """You must evaluate this SKU in TWO separate steps. Both are required.

SKU ({sku_id}):
Name: {name}
Description: {description}
Content:
{content}

---

STEP 1 — Source Integrity Check (penalty only)

Original Source Chunk (the text this SKU was extracted from):
{source_chunk}

Compare the SKU against its source chunk. This check can only HURT confidence, never help it.
- If the SKU faithfully reflects the source → no penalty (extraction was correct, move on)
- If the SKU distorts, hallucinates, or contradicts the source → HARD penalty, set source_penalty to a value between 0.2 and 0.5
- If source is unavailable → no penalty, skip this step

---

STEP 2 — External Verification (the real confidence signal)

Web Search Results:
{web_results}

This is where the actual confidence comes from. Does the CLAIM in this SKU hold up against independent external sources?
- 0.8-1.0: Multiple web sources corroborate the core claims
- 0.6-0.8: Some corroboration, minor gaps or no direct confirmation
- 0.4-0.6: Ambiguous — web results neither confirm nor deny clearly
- 0.2-0.4: Weak — little external support, or topic too niche for web
- 0.0-0.2: Web sources actively contradict the SKU's claims

---

FINAL SCORE = web_confidence - source_penalty (clamped to 0.0-1.0)

Return JSON:
{{
    "web_confidence": 0.75,
    "source_penalty": 0.0,
    "confidence": 0.75,
    "reasoning": "brief explanation — what did web say? any source issues?",
    "web_references": ["url1", "url2"]
}}"""


class ProofreadingPostprocessor(BasePostprocessor):
    """Web-grounded confidence scoring for SKUs."""

    step_name = "proofreading"

    def __init__(self, skus_dir: Path | None = None, chunks_dir: Path | None = None):
        super().__init__(skus_dir=skus_dir)
        self.chunks_dir = chunks_dir or settings.chunks_dir

    def run(self, **kwargs: Any) -> ConfidenceReport:
        """
        Score confidence for all factual and procedural SKUs.

        Returns:
            ConfidenceReport with per-SKU scores.
        """
        index = self.load_index()
        skus = (
            index.get_skus_by_type(SKUType.FACTUAL)
            + index.get_skus_by_type(SKUType.PROCEDURAL)
        )

        logger.info("Starting proofreading", total_skus=len(skus))

        report = ConfidenceReport()

        for i, sku_entry in enumerate(skus):
            # Resumable: skip if already has confidence
            if sku_entry.confidence is not None:
                logger.debug("Skipping already scored SKU", sku_id=sku_entry.sku_id)
                continue

            logger.info(
                "Scoring SKU",
                progress=f"{i + 1}/{len(skus)}",
                sku_id=sku_entry.sku_id,
            )

            entry = self._score_sku(sku_entry)
            if entry is None:
                continue

            report.entries.append(entry)
            report.total_scored += 1

            # Update SKU header.md with confidence
            self._update_header(sku_entry, entry.confidence)

            # Update index entry
            sku_entry.confidence = entry.confidence
            index.updated_at = __import__("datetime").datetime.now()

            # Save periodically (every 10 SKUs)
            if report.total_scored % 10 == 0:
                self.save_index(index)

        # Final save
        self.save_index(index)

        # Compute average
        if report.entries:
            report.average_confidence = sum(
                e.confidence for e in report.entries
            ) / len(report.entries)

        # Save report
        report_path = self.postprocessing_dir / "confidence_report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        logger.info(
            "Proofreading complete",
            scored=report.total_scored,
            average_confidence=f"{report.average_confidence:.3f}",
        )

        return report

    def _score_sku(self, sku_entry) -> Optional[ConfidenceEntry]:
        """Score a single SKU's confidence."""
        # Load SKU content
        content = self._load_content(sku_entry)
        if not content:
            logger.warning("No content for SKU", sku_id=sku_entry.sku_id)
            return None

        # Build search query
        query = f"{sku_entry.name} {sku_entry.description}"

        # Web search
        web_results_raw = search_web(query)
        web_available = web_results_raw is not None
        web_text = self._format_web_results(web_results_raw) if web_available else "(Web search unavailable)"
        web_urls = [r["url"] for r in (web_results_raw or []) if r.get("url")]

        # Load original chunk
        source_chunk_text = self._load_source_chunk(sku_entry.source_chunk)
        source_available = source_chunk_text is not None
        if not source_available:
            source_chunk_text = "(Original source chunk not available)"

        # LLM assessment
        prompt = CONFIDENCE_PROMPT.format(
            sku_id=sku_entry.sku_id,
            name=sku_entry.name,
            description=sku_entry.description,
            content=content[:6000],
            source_chunk=source_chunk_text[:8000],
            web_results=web_text[:4000],
        )

        response = call_llm(
            prompt=prompt,
            system_prompt=CONFIDENCE_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=1000,
        )

        if not response:
            return None

        parsed = parse_json_response(response)
        if not parsed:
            return None

        # Parse bipolar scores
        web_conf = parsed.get("web_confidence", parsed.get("confidence", 0.5))
        if not isinstance(web_conf, (int, float)):
            web_conf = 0.5
        web_conf = max(0.0, min(1.0, float(web_conf)))

        source_penalty = parsed.get("source_penalty", 0.0)
        if not isinstance(source_penalty, (int, float)):
            source_penalty = 0.0
        source_penalty = max(0.0, min(0.5, float(source_penalty)))

        # Final score: web is the signal, source can only penalize
        confidence = max(0.0, min(1.0, web_conf - source_penalty))

        reasoning = parsed.get("reasoning", "")
        if source_penalty > 0:
            reasoning += f" [Source penalty: -{source_penalty:.2f}]"
        if not source_available:
            reasoning += " [Source chunk unavailable]"
        if not web_available:
            reasoning += " [Web search unavailable]"

        return ConfidenceEntry(
            sku_id=sku_entry.sku_id,
            name=sku_entry.name,
            confidence=confidence,
            reasoning=reasoning,
            web_references=web_urls,
            source_chunk_available=source_available,
            web_search_available=web_available,
        )

    def _load_content(self, sku_entry) -> Optional[str]:
        """Load SKU content text."""
        sku_path = Path(sku_entry.path)
        if sku_path.is_dir():
            for candidate in ["content.md", "content.json", "SKILL.md"]:
                p = sku_path / candidate
                if p.exists():
                    return p.read_text(encoding="utf-8")
        elif sku_path.exists():
            return sku_path.read_text(encoding="utf-8")
        return None

    def _load_source_chunk(self, source_chunk: str) -> Optional[str]:
        """Load the original chunk that this SKU was extracted from."""
        chunks_dir = self.chunks_dir
        # Try exact filename match
        chunk_path = chunks_dir / f"{source_chunk}.md"
        if chunk_path.exists():
            return chunk_path.read_text(encoding="utf-8")[:8000]

        # Try pattern matching
        for md_file in chunks_dir.glob("*.md"):
            if source_chunk in md_file.stem:
                return md_file.read_text(encoding="utf-8")[:8000]

        return None

    def _format_web_results(self, results: Optional[list[dict]]) -> str:
        """Format web search results for the LLM prompt."""
        if not results:
            return "(No web results found)"

        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(
                f"[{i}] {r.get('title', 'No title')}\n"
                f"    URL: {r.get('url', '')}\n"
                f"    {r.get('snippet', '')[:300]}"
            )
        return "\n\n".join(formatted)

    def _update_header(self, sku_entry, confidence: float) -> None:
        """Update an SKU's header.md with the confidence score."""
        sku_path = Path(sku_entry.path)
        header_path = None

        if sku_path.is_dir():
            header_path = sku_path / "header.md"
        else:
            return

        if not header_path or not header_path.exists():
            return

        content = header_path.read_text(encoding="utf-8")

        # Remove existing confidence line if present
        content = re.sub(r"- \*\*Confidence\*\*:.*\n?", "", content)

        # Insert confidence line after "Characters" line
        chars_pattern = r"(- \*\*Characters\*\*:.*)"
        if re.search(chars_pattern, content):
            content = re.sub(
                chars_pattern,
                rf"\1\n- **Confidence**: {confidence:.2f}",
                content,
            )
        else:
            # Fallback: add before description (after last bullet)
            content = content.rstrip() + f"\n- **Confidence**: {confidence:.2f}\n"

        header_path.write_text(content, encoding="utf-8")
