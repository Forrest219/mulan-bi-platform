"""Profiler 单元测试

由于真实 DB 采样需要连接，这里只覆盖纯 Python 的聚合/识别逻辑：
- sample_values 取样策略
- id 列识别
- timestamp 列识别
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.dqc.profiler import ColumnProfile, Profiler, _is_timestamp_type


class TestSampleValues:
    def test_pick_top_frequent(self):
        p = Profiler({"db_type": "postgresql"})
        vals = ["a"] * 30 + ["b"] * 20 + ["c"] * 5
        samples = p._pick_sample_values(vals, top_n=2, random_n=0)
        assert "a" in samples
        assert "b" in samples

    def test_empty_returns_empty(self):
        p = Profiler({"db_type": "postgresql"})
        assert p._pick_sample_values([]) == []


class TestIdColumnDetection:
    def test_high_distinct_is_id(self):
        p = Profiler({"db_type": "postgresql"})
        cols = [
            ColumnProfile(
                name="user_id",
                data_type="bigint",
                null_count=0,
                null_rate=0.0,
                distinct_count=1000,
            ),
        ]
        id_cols = p._detect_id_columns(cols, sampled=1000)
        assert id_cols == ["user_id"]

    def test_low_distinct_is_not_id(self):
        p = Profiler({"db_type": "postgresql"})
        cols = [
            ColumnProfile(
                name="status",
                data_type="varchar",
                null_count=0,
                null_rate=0.0,
                distinct_count=5,
            ),
        ]
        id_cols = p._detect_id_columns(cols, sampled=1000)
        assert id_cols == []

    def test_high_null_rate_not_id(self):
        p = Profiler({"db_type": "postgresql"})
        cols = [
            ColumnProfile(
                name="optional_key",
                data_type="bigint",
                null_count=500,
                null_rate=0.5,
                distinct_count=500,
            ),
        ]
        id_cols = p._detect_id_columns(cols, sampled=1000)
        assert id_cols == []


class TestTimestampDetection:
    def test_recognized_types(self):
        assert _is_timestamp_type("timestamp") is True
        assert _is_timestamp_type("datetime") is True
        assert _is_timestamp_type("date") is True
        assert _is_timestamp_type("TIMESTAMP(6)") is True

    def test_non_timestamp(self):
        assert _is_timestamp_type("varchar") is False
        assert _is_timestamp_type("bigint") is False
        assert _is_timestamp_type(None) is False


class TestColumnProfileSerialization:
    def test_to_dict_json_safe(self):
        col = ColumnProfile(
            name="c",
            data_type="bytes",
            null_count=0,
            null_rate=0.0,
            distinct_count=2,
            sample_values=[b"abc", 42, "ok"],
        )
        d = col.to_dict()
        assert isinstance(d["sample_values"], list)
        # bytes 应被转为 str
        assert "abc" in str(d["sample_values"])
