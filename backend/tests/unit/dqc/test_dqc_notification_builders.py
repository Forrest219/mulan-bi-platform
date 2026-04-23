"""通知内容构建器 - 5 个 DQC builder 函数测试（B3 验证）

修复验证：notification_content.py 中 CONTENT_BUILDERS 包含 5 个 dqc 事件键，
每个 builder 返回 (title, str) 元组，content 不含兜底文案"收到事件"。
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")

import pytest

from services.events.notification_content import (
    CONTENT_BUILDERS,
    build_dqc_asset_p0_triggered_content,
    build_dqc_asset_p1_triggered_content,
    build_dqc_asset_recovered_content,
    build_dqc_asset_signal_changed_content,
    build_dqc_cycle_completed_content,
    build_notification_content,
)


class TestDqcNotificationBuilders:
    """B3 验证：5 个 DQC builder 注册正确且返回合规内容"""

    DQC_EVENT_KEYS = [
        "dqc.cycle.completed",
        "dqc.asset.signal_changed",
        "dqc.asset.p0_triggered",
        "dqc.asset.p1_triggered",
        "dqc.asset.recovered",
    ]

    def test_all_five_dqc_keys_registered(self):
        """CONTENT_BUILDERS 包含全部 5 个 dqc 事件键"""
        for key in self.DQC_EVENT_KEYS:
            assert key in CONTENT_BUILDERS, f"missing: {key}"

    def test_each_builder_returns_tuple_of_strings(self):
        """每个 builder 返回 (title: str, content: str)"""
        payload = {
            "display_name": "订单表",
            "schema_name": "dws",
            "table_name": "dws_order",
            "cycle_id": "123e4567-e89b-12d3-a456-426614174000",
            "scope": "full",
            "duration_sec": 42,
            "assets_processed": 10,
            "p0_count": 1,
            "p1_count": 2,
            "prev_signal": "GREEN",
            "current_signal": "P1",
            "prev_confidence_score": 90.0,
            "current_confidence_score": 76.0,
        }

        for key in self.DQC_EVENT_KEYS:
            builder = CONTENT_BUILDERS[key]
            title, content = builder(payload)
            assert isinstance(title, str), f"{key}: title 不是 str"
            assert isinstance(content, str), f"{key}: content 不是 str"
            assert len(title) > 0, f"{key}: title 为空"

    def test_dqc_cycle_completed_content(self):
        """dqc.cycle.completed builder 正确格式化"""
        payload = {
            "scope": "full",
            "duration_sec": 120,
            "assets_processed": 50,
            "p0_count": 2,
            "p1_count": 3,
        }
        title, content = build_dqc_cycle_completed_content(payload)
        assert "DQC" in title
        assert "full" in content
        assert "50" in content
        assert "P0=2" in content
        assert "P1=3" in content
        assert "120" in content

    def test_dqc_asset_p0_triggered_content(self):
        """dqc.asset.p0_triggered builder 生成 P0 告警"""
        payload = {
            "display_name": "销售明细表",
            "schema_name": "ods",
            "table_name": "ods_sales",
            "current_confidence_score": 55.0,
        }
        title, content = build_dqc_asset_p0_triggered_content(payload)
        assert "[P0]" in title
        assert "销售明细表" in title
        assert "55" in content
        assert "P0" in content

    def test_dqc_asset_p1_triggered_content(self):
        """dqc.asset.p1_triggered builder 生成 P1 告警"""
        payload = {
            "display_name": "库存表",
            "schema_name": "dwd",
            "table_name": "dwd_inventory",
            "current_confidence_score": 75.0,
        }
        title, content = build_dqc_asset_p1_triggered_content(payload)
        assert "[P1]" in title
        assert "库存表" in title
        assert "75" in content

    def test_dqc_asset_signal_changed_content(self):
        """dqc.asset.signal_changed builder 描述信号变化"""
        payload = {
            "display_name": "用户表",
            "schema_name": "dim",
            "table_name": "dim_user",
            "prev_signal": "GREEN",
            "current_signal": "P1",
            "prev_confidence_score": 92.0,
            "current_confidence_score": 78.0,
        }
        title, content = build_dqc_asset_signal_changed_content(payload)
        assert "用户表" in title
        assert "GREEN" in content
        assert "P1" in content

    def test_dqc_asset_recovered_content(self):
        """dqc.asset.recovered builder 描述恢复"""
        payload = {
            "display_name": "产品表",
            "schema_name": "dim",
            "table_name": "dim_product",
            "current_confidence_score": 95.0,
        }
        title, content = build_dqc_asset_recovered_content(payload)
        assert "产品表" in title
        assert "GREEN" in content
        assert "95" in content

    def test_build_notification_content_no_fallback_for_dqc(self):
        """DQC 事件走 CONTENT_BUILDERS，不走兜底 '收到事件' 文案"""
        payload = {
            "scope": "full",
            "duration_sec": 10,
            "assets_processed": 5,
            "p0_count": 0,
            "p1_count": 0,
        }
        for key in self.DQC_EVENT_KEYS:
            title, content = build_notification_content(key, payload)
            assert "收到事件" not in content, f"{key} 返回了兜底文案"
            assert "收到事件" not in title, f"{key} title 返回了兜底文案"

    def test_unknown_event_falls_back_to_default(self):
        """未知事件类型走兜底文案"""
        title, content = build_notification_content("unknown.event", {})
        assert title == "系统通知"
        assert "收到事件" in content
        assert "unknown.event" in content
