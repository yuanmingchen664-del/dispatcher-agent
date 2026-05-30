from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Dispatcher Assistant"
    app_env: str = "local"
    database_url: str = "postgresql+psycopg://dispatcher:dispatcher@127.0.0.1:5432/dispatcher"

    storage_provider: Literal["local", "s3"] = "local"
    local_storage_dir: str = ".data/uploads"

    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_region: str = "cn"

    embedding_provider: Literal["mock", "openai_compatible"] = "mock"
    embedding_base_url: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_model: str = "mock-embedding"
    embedding_dimensions: int = Field(default=384, ge=1)
    embedding_batch_size: int = Field(default=64, ge=1, le=256)

    llm_provider: Literal["mock", "openai_compatible"] = "mock"
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: str = "mock-llm"

    chunk_max_chars: int = Field(default=1200, ge=200)
    chunk_overlap_chars: int = Field(default=160, ge=0)
    top_k: int = Field(default=6, ge=1, le=20)

    ocr_provider: Literal["none", "openai_compatible_vision"] = "none"
    ocr_min_text_chars: int = Field(default=30, ge=0)
    ocr_dpi: int = Field(default=200, ge=72, le=400)
    ocr_base_url: Optional[str] = None
    ocr_api_key: Optional[str] = None
    ocr_model: str = "PaddlePaddle/PaddleOCR-VL-1.5"
    ocr_prompt: str = (
        "请对图片进行 OCR，只输出识别出的原始文字。"
        "尽量保持阅读顺序、章节标题、条款编号和换行。不要总结，不要解释。"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
