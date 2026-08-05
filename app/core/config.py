# -*- coding: utf-8 -*-
"""应用配置中心，通过 pydantic-settings 从 .env / 环境变量加载。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192
    llm_timeout: float = 120.0

    # ── HugeGraph ──
    hg_host: str = "202.107.249.39"
    hg_port: int = 50045
    hg_user: str = "admin"
    hg_passwd: str = "admin"
    hg_graphspace: str = "DEFAULT"
    hg_graph: str = "edu"

    # ── MinIO ──
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "exams"
    minio_secure: bool = False

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── OCR 服务 ──
    ocr_service_url: str = "http://202.107.249.39:50108/api/v1/construct-question/ocr-parse"

    # ── App ──
    debug: bool = False
    output_dir: str = "tmp/extractions"

    @property
    def hg_base_url(self) -> str:
        return (
            f"http://{self.hg_host}:{self.hg_port}"
            f"/graphspaces/{self.hg_graphspace}/graphs/{self.hg_graph}"
        )
