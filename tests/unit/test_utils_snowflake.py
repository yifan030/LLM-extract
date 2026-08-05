# -*- coding: utf-8 -*-
"""Tests for app.utils.snowflake.Snowflake."""
from utils.snowflake import Snowflake


def test_snowflake_generates_unique_increasing_ids():
    gen = Snowflake()
    ids = [gen.next_id() for _ in range(1000)]
    assert len(set(ids)) == 1000
    assert ids == sorted(ids)
