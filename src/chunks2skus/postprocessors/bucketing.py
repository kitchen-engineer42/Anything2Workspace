"""Step 1: Bucketing — Group SKUs by similarity into token-limited buckets."""

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import structlog
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from chunks2skus.config import settings
from chunks2skus.postprocessors.base import BasePostprocessor
from chunks2skus.schemas.index import SKUEntry
from chunks2skus.schemas.postprocessing import Bucket, BucketEntry, BucketingResult
from chunks2skus.schemas.sku import LabelTree, SKUType
from chunks2skus.utils.embedding_client import get_embeddings
from chunks2skus.utils.token_utils import estimate_tokens

logger = structlog.get_logger(__name__)


class BucketingPostprocessor(BasePostprocessor):
    """Group factual and procedural SKUs by similarity into buckets."""

    step_name = "bucketing"

    def run(self, **kwargs: Any) -> BucketingResult:
        """
        Run bucketing on all factual and procedural SKUs.

        Returns:
            BucketingResult with bucket assignments.
        """
        index = self.load_index()
        label_tree = self._load_label_tree()

        factual_skus = index.get_skus_by_type(SKUType.FACTUAL)
        procedural_skus = index.get_skus_by_type(SKUType.PROCEDURAL)

        logger.info(
            "Starting bucketing",
            factual=len(factual_skus),
            procedural=len(procedural_skus),
        )

        # Determine effective weights based on available resources
        weights = self._resolve_weights(label_tree)

        factual_buckets = self._bucket_skus(factual_skus, label_tree, weights, "factual")
        procedural_buckets = self._bucket_skus(procedural_skus, label_tree, weights, "procedural")

        result = BucketingResult(
            total_skus=len(factual_skus) + len(procedural_skus),
            total_buckets=len(factual_buckets) + len(procedural_buckets),
            max_bucket_tokens=settings.max_bucket_tokens,
            similarity_weights=weights,
            factual_buckets=factual_buckets,
            procedural_buckets=procedural_buckets,
        )

        # Save result
        out_path = self.postprocessing_dir / "bucketing_result.json"
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        logger.info(
            "Bucketing complete",
            factual_buckets=len(factual_buckets),
            procedural_buckets=len(procedural_buckets),
            output=str(out_path),
        )

        return result

    def _resolve_weights(self, label_tree: Optional[LabelTree]) -> dict[str, float]:
        """Determine effective similarity weights based on available resources."""
        w_literal = settings.similarity_weight_literal
        w_label = settings.similarity_weight_label
        w_vector = settings.similarity_weight_vector

        # Test embedding availability
        test_embed = get_embeddings(["test"])
        embed_available = test_embed is not None

        if not embed_available and label_tree is None:
            # Only literal available
            return {"literal": 1.0, "label": 0.0, "vector": 0.0}
        elif not embed_available:
            # Reweight: literal + label only
            total = w_literal + w_label
            return {"literal": w_literal / total, "label": w_label / total, "vector": 0.0}
        elif label_tree is None:
            # Reweight: literal + vector only
            total = w_literal + w_vector
            return {"literal": w_literal / total, "label": 0.0, "vector": w_vector / total}
        else:
            return {"literal": w_literal, "label": w_label, "vector": w_vector}

    def _load_label_tree(self) -> Optional[LabelTree]:
        """Load the label tree from relational output."""
        label_tree_path = self.skus_dir / "relational" / "label_tree.json"
        if not label_tree_path.exists():
            logger.warning("Label tree not found, label similarity disabled")
            return None
        try:
            data = json.loads(label_tree_path.read_text(encoding="utf-8"))
            return LabelTree.model_validate(data)
        except Exception as e:
            logger.warning("Failed to load label tree", error=str(e))
            return None

    def _bucket_skus(
        self,
        skus: list[SKUEntry],
        label_tree: Optional[LabelTree],
        weights: dict[str, float],
        prefix: str,
    ) -> list[Bucket]:
        """Bucket a list of SKUs using similarity-based clustering."""
        if not skus:
            return []
        if len(skus) == 1:
            entry = self._sku_to_bucket_entry(skus[0])
            return [Bucket(
                bucket_id=f"{prefix}_bucket_001",
                total_tokens=entry.token_count,
                sku_count=1,
                entries=[entry],
            )]

        # Prepare data
        entries = [self._sku_to_bucket_entry(sku) for sku in skus]
        descriptions = [e.description if len(e.description) >= 10 else e.name for e in entries]

        # Compute similarity matrix
        sim_matrix = self._compute_similarity(entries, descriptions, label_tree, weights)

        # Recursive splitting
        buckets = self._recursive_split(entries, sim_matrix, prefix)

        logger.info(f"Bucketed {len(entries)} {prefix} SKUs into {len(buckets)} buckets")
        return buckets

    def _sku_to_bucket_entry(self, sku: SKUEntry) -> BucketEntry:
        """Convert an SKUEntry to a BucketEntry with token count."""
        # Estimate tokens from character count (rough: ~4 chars per token)
        # For more accuracy, load content — but character_count is a good proxy
        token_count = max(1, sku.character_count // 4)

        # Try to load actual content for better estimate
        sku_path = Path(sku.path)
        content_path = None
        if sku_path.is_dir():
            for candidate in ["content.md", "content.json", "SKILL.md"]:
                p = sku_path / candidate
                if p.exists():
                    content_path = p
                    break
        if content_path and content_path.exists():
            try:
                text = content_path.read_text(encoding="utf-8")
                token_count = estimate_tokens(text)
            except Exception:
                pass

        return BucketEntry(
            sku_id=sku.sku_id,
            name=sku.name,
            description=sku.description,
            classification=sku.classification.value,
            token_count=token_count,
        )

    def _compute_similarity(
        self,
        entries: list[BucketEntry],
        descriptions: list[str],
        label_tree: Optional[LabelTree],
        weights: dict[str, float],
    ) -> np.ndarray:
        """Compute weighted similarity matrix from multiple aspects."""
        n = len(entries)
        sim_matrix = np.zeros((n, n))

        # Literal similarity (TF-IDF)
        if weights["literal"] > 0:
            literal_sim = self._compute_tfidf_similarity(descriptions)
            sim_matrix += weights["literal"] * literal_sim

        # Label similarity (Jaccard on label paths)
        if weights["label"] > 0 and label_tree is not None:
            label_paths = self._assign_labels(entries, label_tree)
            label_sim = self._compute_label_similarity(label_paths)
            sim_matrix += weights["label"] * label_sim

        # Vector similarity (embeddings)
        if weights["vector"] > 0:
            # Use content text for short descriptions
            embed_texts = []
            for i, entry in enumerate(entries):
                if len(descriptions[i]) < 10:
                    embed_texts.append(self._load_sku_content_snippet(entry))
                else:
                    embed_texts.append(descriptions[i])

            vector_sim = self._compute_vector_similarity(embed_texts)
            if vector_sim is not None:
                sim_matrix += weights["vector"] * vector_sim
            else:
                # Fallback: redistribute vector weight to literal
                logger.warning("Vector similarity failed, falling back to literal")
                literal_sim = self._compute_tfidf_similarity(descriptions)
                sim_matrix += weights["vector"] * literal_sim

        return sim_matrix

    def _compute_tfidf_similarity(self, texts: list[str]) -> np.ndarray:
        """Compute cosine similarity from TF-IDF vectors."""
        if not texts or all(not t.strip() for t in texts):
            return np.zeros((len(texts), len(texts)))

        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        try:
            tfidf_matrix = vectorizer.fit_transform(texts)
            return cosine_similarity(tfidf_matrix).astype(np.float64)
        except ValueError:
            return np.zeros((len(texts), len(texts)))

    def _assign_labels(
        self,
        entries: list[BucketEntry],
        label_tree: LabelTree,
    ) -> list[list[str]]:
        """
        Assign label paths to each SKU by matching against the label tree.

        Peeling onion: match root → child → grandchild layer by layer.
        """
        all_paths = label_tree.get_all_paths()
        if not all_paths:
            return [[] for _ in entries]

        # Build flat list of all label names at each level
        result = []
        for entry in entries:
            text = f"{entry.name} {entry.description}".lower()
            best_path: list[str] = []
            best_score = 0

            for path in all_paths:
                score = sum(1 for label in path if label.lower() in text)
                if score > best_score:
                    best_score = score
                    best_path = path

            result.append(best_path)

        return result

    def _compute_label_similarity(self, label_paths: list[list[str]]) -> np.ndarray:
        """Compute Jaccard similarity on label paths."""
        n = len(label_paths)
        sim = np.zeros((n, n))

        for i in range(n):
            set_i = set(label_paths[i])
            if not set_i:
                continue
            for j in range(i, n):
                set_j = set(label_paths[j])
                if not set_j:
                    continue
                intersection = len(set_i & set_j)
                union = len(set_i | set_j)
                jaccard = intersection / union if union > 0 else 0.0
                sim[i, j] = jaccard
                sim[j, i] = jaccard

        return sim

    def _compute_vector_similarity(self, texts: list[str]) -> Optional[np.ndarray]:
        """Compute cosine similarity from embedding vectors."""
        embeddings = get_embeddings(texts)
        if embeddings is None:
            return None

        emb_array = np.array(embeddings)
        # Normalize for cosine similarity
        norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        emb_normalized = emb_array / norms

        return (emb_normalized @ emb_normalized.T).astype(np.float64)

    def _load_sku_content_snippet(self, entry: BucketEntry, max_chars: int = 500) -> str:
        """Load first max_chars of SKU content as fallback for short descriptions."""
        sku_path = self.skus_dir / entry.classification / entry.sku_id
        for candidate in ["content.md", "content.json", "SKILL.md"]:
            p = sku_path / candidate
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8")[:max_chars]
                except Exception:
                    pass
        return entry.name

    def _recursive_split(
        self,
        entries: list[BucketEntry],
        sim_matrix: np.ndarray,
        prefix: str,
        bucket_counter: list[int] | None = None,
    ) -> list[Bucket]:
        """Recursively split until all buckets fit within token limit."""
        if bucket_counter is None:
            bucket_counter = [0]

        total_tokens = sum(e.token_count for e in entries)

        # Base case: fits in one bucket
        if total_tokens <= settings.max_bucket_tokens or len(entries) <= 1:
            bucket_counter[0] += 1
            bucket_id = f"{prefix}_bucket_{bucket_counter[0]:03d}"
            return [Bucket(
                bucket_id=bucket_id,
                total_tokens=total_tokens,
                sku_count=len(entries),
                entries=entries,
            )]

        # Convert similarity to distance
        distance_matrix = 1.0 - np.clip(sim_matrix, 0, 1)
        np.fill_diagonal(distance_matrix, 0)

        # Extract condensed distance matrix for scipy
        n = len(entries)
        condensed = []
        for i in range(n):
            for j in range(i + 1, n):
                condensed.append(distance_matrix[i, j])
        condensed = np.array(condensed)

        # Agglomerative clustering with average linkage, cut into 2
        try:
            Z = linkage(condensed, method="average")
            labels = fcluster(Z, t=2, criterion="maxclust")
        except Exception as e:
            logger.warning("Clustering failed, splitting by index", error=str(e))
            mid = len(entries) // 2
            labels = np.array([1] * mid + [2] * (len(entries) - mid))

        # Split into two groups
        group_0 = [entries[i] for i in range(n) if labels[i] == 1]
        group_1 = [entries[i] for i in range(n) if labels[i] == 2]
        idx_0 = [i for i in range(n) if labels[i] == 1]
        idx_1 = [i for i in range(n) if labels[i] == 2]

        # Handle edge case where one group is empty
        if not group_0 or not group_1:
            mid = len(entries) // 2
            group_0, group_1 = entries[:mid], entries[mid:]
            idx_0, idx_1 = list(range(mid)), list(range(mid, n))

        # Sub-matrices for recursion
        sim_0 = sim_matrix[np.ix_(idx_0, idx_0)]
        sim_1 = sim_matrix[np.ix_(idx_1, idx_1)]

        # Recurse
        buckets_0 = self._recursive_split(group_0, sim_0, prefix, bucket_counter)
        buckets_1 = self._recursive_split(group_1, sim_1, prefix, bucket_counter)

        return buckets_0 + buckets_1
