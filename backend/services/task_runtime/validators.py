"""Task Runtime - Validators（Spec 24 §4.2）

校验规则：
- intent 必须在白名单（config/taskrun_intents.yaml）
- timeout_seconds 范围 [5, 600]
- Agent 模式 conversation_id 必填且属于当前用户
- 单用户并发 running ≤ 5
"""
import logging
import os
from typing import List, Optional, Tuple

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import TRError
from services.auth.models import User
from services.task_runtime.models_db import BiTaskRun

logger = logging.getLogger(__name__)

# Intent 白名单路径
INTENT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "config", "taskrun_intents.yaml"
)


def _load_intent_whitelist() -> List[str]:
    """从 config/taskrun_intents.yaml 加载 intent 白名单"""
    try:
        with open(INTENT_CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f)
            return data.get("allowed", [])
    except FileNotFoundError:
        logger.warning("taskrun_intents.yaml not found at %s, using hardcoded fallback", INTENT_CONFIG_PATH)
        return ["agent_chat", "nlq_query", "bulk_action", "health_scan"]
    except Exception as e:
        logger.error("Failed to load taskrun_intents.yaml: %s", e)
        return ["agent_chat", "nlq_query", "bulk_action", "health_scan"]


# 缓存白名单
_ALLOWED_INTENTS: Optional[List[str]] = None


def get_allowed_intents() -> List[str]:
    global _ALLOWED_INTENTS
    if _ALLOWED_INTENTS is None:
        _ALLOWED_INTENTS = _load_intent_whitelist()
    return _ALLOWED_INTENTS


class TaskRunValidator:
    """TaskRun 创建校验器"""

    MAX_CONCURRENT_RUNNING = 5

    def __init__(self, db: Session, current_user: dict):
        self.db = db
        self.current_user = current_user

    def validate_create(
        self,
        intent: str,
        timeout_seconds: int,
        conversation_id: Optional[int],
    ) -> None:
        """校验 TaskRun 创建请求

        Raises:
            TRError: 对应错误码
        """
        # TR_001: intent 白名单校验
        allowed = get_allowed_intents()
        if intent not in allowed:
            logger.warning("Invalid intent '%s' not in whitelist %s", intent, allowed)
            raise TRError.invalid_intent()

        # TR_002: timeout 范围校验
        if not (5 <= timeout_seconds <= 600):
            logger.warning("timeout_seconds %d out of range [5, 600]", timeout_seconds)
            raise TRError.timeout_out_of_range()

        # TR_003: Agent 模式 conversation_id 必填且属于当前用户
        if intent == "agent_chat":
            if conversation_id is None:
                raise TRError.conversation_not_owned()
            # Defer conversation ownership check until Spec 21 conversation model is implemented
            # For now, we just validate conversation_id is provided
            pass

        # TR_008: 单用户并发 running ≤ 5
        running_count = self.db.query(func.count(BiTaskRun.id)).filter(
            BiTaskRun.user_id == self.current_user["id"],
            BiTaskRun.status == "running",
        ).scalar()
        if running_count >= self.MAX_CONCURRENT_RUNNING:
            logger.warning(
                "User %d has %d running TaskRuns, limit is %d",
                self.current_user["id"], running_count, self.MAX_CONCURRENT_RUNNING
            )
            raise TRError.concurrent_limit_exceeded()

    def validate_rbac(self, intent: str) -> None:
        """RBAC 校验（Spec 24 §6.1）

        仅 admin/data_admin 可创建 bulk_action / health_scan
        """
        role = self.current_user.get("role", "user")
        if intent in ("bulk_action", "health_scan"):
            if role not in ("admin", "data_admin"):
                from app.core.errors import AuthError
                raise AuthError.insufficient_permissions()
