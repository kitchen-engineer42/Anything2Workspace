"""Configuration management for knowledge extraction module."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Knowledge extraction configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # I/O Paths (shared with upstream modules)
    input_dir: Path = Field(default=Path("./input"))
    output_dir: Path = Field(default=Path("./output"))
    log_dir: Path = Field(default=Path("./logs"))

    # Module 3: SKU output directory
    skus_output_dir: Path = Field(default=Path("./output/skus"))

    # LLM Configuration (SiliconFlow)
    siliconflow_api_key: str = Field(default="")
    siliconflow_base_url: str = Field(default="https://api.siliconflow.cn/v1")
    extraction_model: str = Field(
        default="Pro/zai-org/GLM-5",
        description="Model for knowledge extraction (complex tasks)",
    )

    # Postprocessing
    max_bucket_tokens: int = Field(default=100000)
    embedding_model: str = Field(default="Pro/BAAI/bge-m3")
    jina_api_key: str = Field(default="")
    similarity_weight_literal: float = Field(default=0.2)
    similarity_weight_label: float = Field(default=0.3)
    similarity_weight_vector: float = Field(default=0.5)
    dedup_scan_model: str = Field(
        default="Qwen/Qwen3-VL-235B-A22B-Instruct",
        description="Fast model for dedup header scanning",
    )

    # Language
    language: Literal["en", "zh"] = Field(default="en")

    # Logging
    log_level: str = Field(default="INFO")
    log_format: Literal["json", "text", "both"] = Field(default="both")

    @property
    def chunks_dir(self) -> Path:
        """Directory containing chunks from Module 2."""
        return self.output_dir / "chunks"

    @property
    def chunks_index_path(self) -> Path:
        """Path to chunks_index.json from Module 2."""
        return self.chunks_dir / "chunks_index.json"

    @property
    def factual_dir(self) -> Path:
        """Directory for factual SKUs."""
        return self.skus_output_dir / "factual"

    @property
    def relational_dir(self) -> Path:
        """Directory for relational knowledge."""
        return self.skus_output_dir / "relational"

    @property
    def procedural_dir(self) -> Path:
        """Directory for procedural SKUs (skills)."""
        return self.skus_output_dir / "procedural"

    @property
    def meta_dir(self) -> Path:
        """Directory for meta knowledge."""
        return self.skus_output_dir / "meta"

    @property
    def postprocessing_dir(self) -> Path:
        """Directory for postprocessing outputs."""
        return self.skus_output_dir / "postprocessing"


def get_settings() -> Settings:
    """Get settings instance."""
    return Settings()


# Default singleton
settings = Settings()
