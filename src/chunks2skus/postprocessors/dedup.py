"""Step 2: Dedup/Contradiction — Two-tier duplicate detection and resolution."""

import json
import shutil
from pathlib import Path
from typing import Any, Optional

import structlog

from chunks2skus.config import settings
from chunks2skus.postprocessors.base import BasePostprocessor
from chunks2skus.schemas.postprocessing import (
    BucketingResult,
    DedupAction,
    DedupReport,
    FlaggedPair,
)
from chunks2skus.utils.llm_client import call_llm, parse_json_response

logger = structlog.get_logger(__name__)


TIER1_SYSTEM_PROMPT = "You are a knowledge base quality assistant. Output ONLY valid JSON."

TIER1_SCAN_PROMPT = """Compare these SKU headers within the same topic bucket. Flag any pairs that look like potential duplicates or contradictions.

IMPORTANT:
- Only flag pairs that are CLEARLY similar or contradictory based on name and description
- It's OK to over-flag slightly — a second pass will verify
- Do NOT flag pairs that are merely related but distinct

SKU Headers:
{headers}

Return JSON:
{{"flagged_pairs": [{{"sku_a": "sku_id_1", "sku_b": "sku_id_2", "reason": "brief reason"}}]}}

If no duplicates or contradictions found, return: {{"flagged_pairs": []}}"""


TIER2_SYSTEM_PROMPT = "You are a knowledge base quality assistant. Output ONLY valid JSON."

TIER2_JUDGMENT_PROMPT = """Read these two SKUs carefully. Determine if they are truly duplicates or contradictory.

SKU A ({sku_a_id}):
Name: {sku_a_name}
Description: {sku_a_desc}
Content:
{sku_a_content}

---

SKU B ({sku_b_id}):
Name: {sku_b_name}
Description: {sku_b_desc}
Content:
{sku_b_content}

---

IMPORTANT: When in doubt, KEEP both. Only recommend deletion if they are near-identical.

Actions:
- "keep": Both are distinct enough to keep
- "delete": One is a clear duplicate (specify which to delete in "delete_sku")
- "rewrite": One needs revision to remove overlap (specify which in "rewrite_sku", provide "new_content")
- "merge": Combine into one (provide "merged_content", specify "delete_sku" for the one to remove)

Return JSON:
{{
    "action": "keep" | "delete" | "rewrite" | "merge",
    "reasoning": "brief explanation",
    "delete_sku": "sku_id or null",
    "rewrite_sku": "sku_id or null",
    "new_content": "rewritten content or null",
    "merged_content": "merged content or null"
}}"""


class DedupPostprocessor(BasePostprocessor):
    """Two-tier dedup: quick scan headers, then deep read flagged pairs."""

    step_name = "dedup"

    def run(self, **kwargs: Any) -> DedupReport:
        """
        Run dedup on all buckets from bucketing_result.json.

        Returns:
            DedupReport with actions taken.
        """
        bucketing_path = self.postprocessing_dir / "bucketing_result.json"
        if not bucketing_path.exists():
            raise FileNotFoundError(
                f"Bucketing result not found: {bucketing_path}. Run bucketing first."
            )

        data = json.loads(bucketing_path.read_text(encoding="utf-8"))
        bucketing = BucketingResult.model_validate(data)

        all_buckets = bucketing.factual_buckets + bucketing.procedural_buckets
        logger.info("Starting dedup", total_buckets=len(all_buckets))

        report = DedupReport()
        index = self.load_index()

        for bucket in all_buckets:
            if bucket.sku_count <= 1:
                logger.debug("Skipping single-SKU bucket", bucket_id=bucket.bucket_id)
                continue

            report.buckets_scanned += 1

            # Tier 1: Quick scan headers
            flagged = self._tier1_scan(bucket)
            if not flagged:
                logger.debug("No flags in bucket", bucket_id=bucket.bucket_id)
                continue

            report.pairs_flagged += len(flagged)
            logger.info(
                "Flagged pairs",
                bucket_id=bucket.bucket_id,
                count=len(flagged),
            )

            # Validate flagged SKU IDs against actual bucket entries
            valid_ids = {e.sku_id for e in bucket.entries}
            flagged = [
                fp for fp in flagged
                if fp.sku_a in valid_ids and fp.sku_b in valid_ids
            ]

            # Tier 2: Deep read flagged pairs
            for pair in flagged:
                action = self._tier2_judge(pair)
                if action is None:
                    continue

                report.pairs_resolved += 1
                report.actions.append(action)

                # Apply action and update counters
                self._apply_action(action, index)
                if action.action == "keep":
                    report.total_kept += 1
                elif action.action == "delete":
                    report.total_deleted += len(action.deleted_skus)
                elif action.action == "rewrite":
                    report.total_rewritten += len(action.rewritten_skus)
                elif action.action == "merge":
                    report.total_merged += 1
                    report.total_deleted += len(action.deleted_skus)

        # Save updated index
        self.save_index(index)

        # Update mapping.md to remove references to deleted SKUs
        if report.total_deleted > 0:
            self._clean_mapping(report)

        # Save report
        report_path = self.postprocessing_dir / "dedup_report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        logger.info(
            "Dedup complete",
            buckets_scanned=report.buckets_scanned,
            pairs_flagged=report.pairs_flagged,
            deleted=report.total_deleted,
            rewritten=report.total_rewritten,
            merged=report.total_merged,
            kept=report.total_kept,
        )

        return report

    # Max headers per Tier 1 scan call to avoid token overflow
    _TIER1_BATCH_SIZE = 80

    def _tier1_scan(self, bucket) -> list[FlaggedPair]:
        """Tier 1: Quick scan of headers to flag potential duplicates."""
        entries = bucket.entries

        # For large buckets, scan in overlapping sub-batches
        if len(entries) <= self._TIER1_BATCH_SIZE:
            return self._tier1_scan_batch(entries, bucket.bucket_id)

        all_flagged = []
        for i in range(0, len(entries), self._TIER1_BATCH_SIZE):
            batch = entries[i : i + self._TIER1_BATCH_SIZE]
            logger.debug(
                "Tier 1 sub-batch",
                bucket_id=bucket.bucket_id,
                batch=f"{i // self._TIER1_BATCH_SIZE + 1}",
                size=len(batch),
            )
            flagged = self._tier1_scan_batch(batch, bucket.bucket_id)
            all_flagged.extend(flagged)

        return all_flagged

    def _tier1_scan_batch(self, entries: list, bucket_id: str) -> list[FlaggedPair]:
        """Scan a batch of SKU headers for duplicates."""
        headers_text = "\n".join(
            f"- {e.sku_id}: name=\"{e.name}\", desc=\"{e.description}\""
            for e in entries
        )

        prompt = TIER1_SCAN_PROMPT.format(headers=headers_text)
        response = call_llm(
            prompt=prompt,
            system_prompt=TIER1_SYSTEM_PROMPT,
            model=settings.dedup_scan_model,
            temperature=0.2,
            max_tokens=4000,
        )

        if not response:
            logger.warning("Tier 1 scan returned no response", bucket_id=bucket_id)
            return []

        parsed = parse_json_response(response)
        if not parsed or "flagged_pairs" not in parsed:
            return []

        flagged = []
        for pair_data in parsed["flagged_pairs"]:
            try:
                flagged.append(FlaggedPair(
                    sku_a=pair_data["sku_a"],
                    sku_b=pair_data["sku_b"],
                    reason=pair_data.get("reason", ""),
                ))
            except (KeyError, TypeError):
                continue

        return flagged

    def _tier2_judge(self, pair: FlaggedPair) -> Optional[DedupAction]:
        """Tier 2: Deep read of flagged pair, full content comparison."""
        # Load full content
        content_a = self._load_sku_content(pair.sku_a)
        content_b = self._load_sku_content(pair.sku_b)
        meta_a = self._load_sku_meta(pair.sku_a)
        meta_b = self._load_sku_meta(pair.sku_b)

        if content_a is None or content_b is None:
            logger.warning("Could not load content for pair", a=pair.sku_a, b=pair.sku_b)
            return None

        prompt = TIER2_JUDGMENT_PROMPT.format(
            sku_a_id=pair.sku_a,
            sku_a_name=meta_a.get("name", pair.sku_a),
            sku_a_desc=meta_a.get("description", ""),
            sku_a_content=content_a[:8000],
            sku_b_id=pair.sku_b,
            sku_b_name=meta_b.get("name", pair.sku_b),
            sku_b_desc=meta_b.get("description", ""),
            sku_b_content=content_b[:8000],
        )

        response = call_llm(
            prompt=prompt,
            system_prompt=TIER2_SYSTEM_PROMPT,
            model=settings.extraction_model,
            temperature=0.3,
            max_tokens=4000,
        )

        if not response:
            return None

        parsed = parse_json_response(response)
        if not parsed:
            return None

        action_str = parsed.get("action", "keep")
        if action_str not in ("keep", "delete", "rewrite", "merge"):
            action_str = "keep"

        return DedupAction(
            sku_a=pair.sku_a,
            sku_b=pair.sku_b,
            action=action_str,
            detail=parsed.get("reasoning", ""),
            deleted_skus=[parsed["delete_sku"]] if parsed.get("delete_sku") else [],
            rewritten_skus=[parsed["rewrite_sku"]] if parsed.get("rewrite_sku") else [],
        )

    def _apply_action(self, action: DedupAction, index) -> None:
        """Apply a dedup action: delete, rewrite, merge, or keep."""
        if action.action == "keep":
            logger.debug("Keeping both", a=action.sku_a, b=action.sku_b)
            return

        if action.action == "delete":
            for sku_id in action.deleted_skus:
                if self._validate_sku_id(sku_id, action):
                    self._delete_sku(sku_id, index)

        elif action.action == "rewrite":
            # Rewrite is a future enhancement — for now just log
            for sku_id in action.rewritten_skus:
                logger.info("Rewrite flagged (manual review)", sku_id=sku_id, detail=action.detail)

        elif action.action == "merge":
            # Delete the secondary SKU
            for sku_id in action.deleted_skus:
                if self._validate_sku_id(sku_id, action):
                    self._delete_sku(sku_id, index)

    def _validate_sku_id(self, sku_id: str, action: DedupAction) -> bool:
        """Validate that an SKU ID from LLM response is one of the pair's IDs."""
        if sku_id not in (action.sku_a, action.sku_b):
            logger.warning(
                "LLM returned invalid SKU ID for action",
                returned=sku_id,
                expected=[action.sku_a, action.sku_b],
            )
            return False
        return True

    def _delete_sku(self, sku_id: str, index) -> None:
        """Delete an SKU folder from disk and remove from index."""
        # Find the entry in index to get path
        entry = None
        for s in index.skus:
            if s.sku_id == sku_id:
                entry = s
                break

        if entry is None:
            logger.warning("SKU not found in index for deletion", sku_id=sku_id)
            return

        # Delete folder from disk
        sku_path = Path(entry.path)
        if sku_path.exists() and sku_path.is_dir():
            shutil.rmtree(sku_path)
            logger.info("Deleted SKU folder", sku_id=sku_id, path=str(sku_path))
        elif sku_path.exists():
            sku_path.unlink()
            logger.info("Deleted SKU file", sku_id=sku_id, path=str(sku_path))

        # Remove from index
        index.remove_sku(sku_id)

    def _load_sku_content(self, sku_id: str) -> Optional[str]:
        """Load full content of an SKU."""
        index = self.load_index()
        for entry in index.skus:
            if entry.sku_id == sku_id:
                sku_path = Path(entry.path)
                if sku_path.is_dir():
                    for candidate in ["content.md", "content.json", "SKILL.md"]:
                        p = sku_path / candidate
                        if p.exists():
                            return p.read_text(encoding="utf-8")
                elif sku_path.exists():
                    return sku_path.read_text(encoding="utf-8")
        return None

    def _load_sku_meta(self, sku_id: str) -> dict:
        """Load SKU header metadata."""
        index = self.load_index()
        for entry in index.skus:
            if entry.sku_id == sku_id:
                return {
                    "name": entry.name,
                    "description": entry.description,
                    "classification": entry.classification.value,
                }
        return {}

    def _clean_mapping(self, report: DedupReport) -> None:
        """Remove references to deleted SKUs from mapping.md."""
        mapping_path = self.skus_dir / "meta" / "mapping.md"
        if not mapping_path.exists():
            return

        deleted_ids = set()
        for action in report.actions:
            deleted_ids.update(action.deleted_skus)

        if not deleted_ids:
            return

        content = mapping_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        cleaned = []
        for line in lines:
            if any(sku_id in line for sku_id in deleted_ids):
                continue
            cleaned.append(line)

        mapping_path.write_text("\n".join(cleaned), encoding="utf-8")
        logger.info("Cleaned mapping.md", removed_references=len(lines) - len(cleaned))
