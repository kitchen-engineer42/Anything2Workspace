"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # I/O Paths
    input_dir: Path = Field(default=Path("./input"))
    output_dir: Path = Field(default=Path("./output"))
    log_dir: Path = Field(default=Path("./logs"))

    # API Keys
    siliconflow_api_key: str = Field(default="")
    mineru_api_key: str = Field(default="")
    firecrawl_api_key: str = Field(default="")

    # MinerU Configuration
    mineru_api_endpoint: str = Field(default="https://mineru.net/api/v4/extract/task")
    max_pdf_size_mb: int = Field(default=10)
    min_valid_chars: int = Field(default=500)

    # SiliconFlow API
    siliconflow_base_url: str = Field(default="https://api.siliconflow.cn/v1")

    # PaddleOCR-VL Configuration
    paddleocr_model: str = Field(default="PaddlePaddle/PaddleOCR-VL-1.5")
    ocr_dpi: int = Field(default=150)
    ocr_page_timeout: int = Field(default=60)
    ocr_base_url: str = Field(default="")  # Empty = use siliconflow_base_url; set to e.g. http://localhost:8080/v1 for local

    # Processing
    retry_count: int = Field(default=1)
    retry_delay_seconds: int = Field(default=2)

    # Language
    language: Literal["en", "zh"] = Field(default="en")

    # Logging
    log_level: str = Field(default="INFO")
    log_format: Literal["json", "text", "both"] = Field(default="both")


def get_settings() -> Settings:
    """Get settings instance. Creates new instance each time to pick up env changes."""
    return Settings()


# Default singleton for convenience
settings = Settings()
