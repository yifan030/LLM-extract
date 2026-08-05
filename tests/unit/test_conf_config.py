# -*- coding: utf-8 -*-
"""Tests for app.core.config.Settings."""
import pytest

from conf.config import Settings


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Isolate env overrides so tests are deterministic."""
    for var in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT",
        "HG_HOST",
        "HG_PORT",
        "HG_USER",
        "HG_PASSWD",
        "HG_GRAPHSPACE",
        "HG_GRAPH",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET",
        "MINIO_SECURE",
        "REDIS_URL",
        "DEBUG",
    ):
        monkeypatch.delenv(var, raising=False)


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.llm_api_key == ""
        assert s.llm_base_url == "https://api.openai.com/v1"
        assert s.llm_model == "gpt-4o"
        assert s.llm_temperature == 0.0
        assert s.llm_max_tokens == 8192
        assert s.llm_timeout == 120.0
        assert s.hg_host == "202.107.249.39"
        assert s.hg_port == 50045
        assert s.hg_user == "admin"
        assert s.hg_passwd == "admin"
        assert s.hg_graphspace == "DEFAULT"
        assert s.hg_graph == "edu"
        assert s.minio_endpoint == "localhost:9000"
        assert s.minio_access_key == ""
        assert s.minio_secret_key == ""
        assert s.minio_bucket == "exams"
        assert s.minio_secure is False
        assert s.redis_url == "redis://localhost:6379/0"
        assert s.debug is False

    def test_hg_base_url(self):
        s = Settings()
        assert (
            s.hg_base_url
            == "http://202.107.249.39:50045/graphspaces/DEFAULT/graphs/edu"
        )

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("HG_HOST", "localhost")
        monkeypatch.setenv("HG_PORT", "9999")
        monkeypatch.setenv("LLM_MODEL", "gpt-5")
        s = Settings()
        assert s.hg_host == "localhost"
        assert s.hg_port == 9999
        assert s.llm_model == "gpt-5"
        assert s.hg_base_url == "http://localhost:9999/graphspaces/DEFAULT/graphs/edu"
