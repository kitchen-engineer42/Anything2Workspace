"""Schemas for postprocessing pipeline (bucketing, dedup, proofreading)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# --- Bucketing ---


class BucketEntry(BaseModel):
    """An SKU assigned to a bucket."""

    sku_id: str
    name: str
    description: str
    classification: str
    token_count: int
    label_path: list[str] = Field(default_factory=list)


class Bucket(BaseModel):
    """A group of similar SKUs within the token limit."""

    bucket_id: str
    total_tokens: int = 0
    sku_count: int = 0
    entries: list[BucketEntry] = Field(default_factory=list)


class BucketingResult(BaseModel):
    """Complete bucketing output."""

    created_at: datetime = Field(default_factory=datetime.now)
    total_skus: int = 0
    total_buckets: int = 0
    max_bucket_tokens: int = 100000
    similarity_weights: dict[str, float] = Field(default_factory=dict)
    factual_buckets: list[Bucket] = Field(default_factory=list)
    procedural_buckets: list[Bucket] = Field(default_factory=list)


# --- Dedup ---


class FlaggedPair(BaseModel):
    """A pair of SKUs flagged as potential duplicates/contradictions."""

    sku_a: str
    sku_b: str
    reason: str


class DedupAction(BaseModel):
    """Action taken on a flagged pair after deep read."""

    sku_a: str
    sku_b: str
    action: str  # "delete", "rewrite", "merge", "keep"
    detail: str = ""
    deleted_skus: list[str] = Field(default_factory=list)
    rewritten_skus: list[str] = Field(default_factory=list)


class DedupReport(BaseModel):
    """Complete dedup output."""

    created_at: datetime = Field(default_factory=datetime.now)
    buckets_scanned: int = 0
    pairs_flagged: int = 0
    pairs_resolved: int = 0
    total_deleted: int = 0
    total_rewritten: int = 0
    total_merged: int = 0
    total_kept: int = 0
    actions: list[DedupAction] = Field(default_factory=list)


# --- Proofreading ---


class ConfidenceEntry(BaseModel):
    """Confidence score for a single SKU."""

    sku_id: str
    name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = ""
    web_references: list[str] = Field(default_factory=list)
    source_chunk_available: bool = True
    web_search_available: bool = True


class ConfidenceReport(BaseModel):
    """Complete proofreading output."""

    created_at: datetime = Field(default_factory=datetime.now)
    total_scored: int = 0
    average_confidence: float = 0.0
    entries: list[ConfidenceEntry] = Field(default_factory=list)
