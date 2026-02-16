"""PostprocessingPipeline — orchestrates bucketing, dedup, and proofreading."""

from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from chunks2skus.config import settings
from chunks2skus.postprocessors.bucketing import BucketingPostprocessor
from chunks2skus.postprocessors.dedup import DedupPostprocessor
from chunks2skus.postprocessors.proofreading import ProofreadingPostprocessor

logger = structlog.get_logger(__name__)


class PostprocessingPipeline:
    """Orchestrates the 3-step postprocessing pipeline."""

    def __init__(self, skus_dir: Path | None = None, chunks_dir: Path | None = None):
        """
        Initialize the pipeline.

        Args:
            skus_dir: SKUs directory (default: settings.skus_output_dir)
            chunks_dir: Chunks directory for source chunk lookup (default: settings.chunks_dir)
        """
        self.skus_dir = skus_dir or settings.skus_output_dir
        self.chunks_dir = chunks_dir or settings.chunks_dir

    def run_all(self) -> dict[str, Any]:
        """Run all 3 postprocessing steps sequentially."""
        start_time = datetime.now()
        logger.info("Starting postprocessing pipeline", skus_dir=str(self.skus_dir))

        results = {}

        # Step 1: Bucketing
        logger.info("Step 1/3: Bucketing")
        bucketing = BucketingPostprocessor(skus_dir=self.skus_dir)
        results["bucketing"] = bucketing.run()

        # Step 2: Dedup
        logger.info("Step 2/3: Dedup")
        dedup = DedupPostprocessor(skus_dir=self.skus_dir)
        results["dedup"] = dedup.run()

        # Step 3: Proofreading
        logger.info("Step 3/3: Proofreading")
        proofreading = ProofreadingPostprocessor(skus_dir=self.skus_dir, chunks_dir=self.chunks_dir)
        results["proofreading"] = proofreading.run()

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Postprocessing pipeline complete",
            duration_seconds=f"{duration:.1f}",
            buckets=results["bucketing"].total_buckets,
            dedup_deleted=results["dedup"].total_deleted,
            confidence_avg=f"{results['proofreading'].average_confidence:.3f}",
        )

        return results

    def run_bucket(self) -> Any:
        """Run bucketing step only."""
        bucketing = BucketingPostprocessor(skus_dir=self.skus_dir)
        return bucketing.run()

    def run_dedup(self) -> Any:
        """Run dedup step only (requires bucketing_result.json)."""
        dedup = DedupPostprocessor(skus_dir=self.skus_dir)
        return dedup.run()

    def run_proof(self) -> Any:
        """Run proofreading step only."""
        proofreading = ProofreadingPostprocessor(skus_dir=self.skus_dir, chunks_dir=self.chunks_dir)
        return proofreading.run()
