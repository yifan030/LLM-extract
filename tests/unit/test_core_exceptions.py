# -*- coding: utf-8 -*-
"""Tests for app.core.exceptions exception hierarchy."""
import pytest

from app.core.exceptions import (
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
