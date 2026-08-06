# -*- coding: utf-8 -*-
"""Tests for app.core.exceptions exception hierarchy."""
import pytest

from core.exceptions import (
    AppError,
    MinioObjectNotFound,
    LlmApiCallError,
    HugeGraphError,
    KnowledgePointNotFound,
    ExtractionValidationError,
)


def test_app_error_default_status():
    err = AppError("something wrong")
    assert err.message == "something wrong"
    assert err.status_code == 500
    assert err.detail == {}


def test_app_error_with_detail():
    err = AppError("not found", status_code=404, detail={"key": "x"})
    assert err.status_code == 404
    assert err.detail == {"key": "x"}


@pytest.mark.parametrize("exc_cls,expected_status", [
    (MinioObjectNotFound, 404),
    (LlmApiCallError, 502),
    (HugeGraphError, 502),
    (KnowledgePointNotFound, 404),
    (ExtractionValidationError, 422),
])
def test_subclass_status_codes(exc_cls, expected_status):
    err = exc_cls("test")
    assert err.status_code == expected_status


from core.exceptions import (
    ExternalServiceError,
    HugeGraphTimeout,
    MilvusTimeout,
    MinioTimeout,
    OcrServiceError,
    RedisTimeout,
)


@pytest.mark.parametrize("exc_cls,service_name", [
    (HugeGraphTimeout, "hugegraph"),
    (MilvusTimeout, "milvus"),
    (MinioTimeout, "minio"),
    (OcrServiceError, "ocr"),
    (RedisTimeout, "redis"),
])
def test_external_service_error_detail(exc_cls, service_name):
    err = exc_cls("timeout")
    assert err.status_code == 502
    assert err.detail["service"] == service_name


def test_external_service_error_with_custom_detail():
    err = HugeGraphTimeout("timeout", detail={"endpoint": "/graph/edges"})
    assert err.detail["service"] == "hugegraph"
    assert err.detail["endpoint"] == "/graph/edges"
