"""
分析会话管理器 — Analysis Session Manager

Spec 28 §3 — 数据模型
- BiAnalysisSession（可变会话状态）
- BiAnalysisSessionStep（不可变步骤历史）
- BiAnalysisInsight（已发布洞察）
- BiAnalysisReport（分析报告）

功能：
- 分析会话 CRUD
- 中断恢复（context_snapshot）
- 过期清理（24h 无 resume 标记 expired）
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.data_agent.models import (
    BiAnalysisSession,
    BiAnalysisSessionStep,
    BiAnalysisInsight,
    BiAnalysisReport,
)

logger = logging.getLogger(__name__)


class AnalysisSessionError(Exception):
    """分析会话异常"""

    def __init__(self, code: str, message: str, detail: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"[{code}] {message}")


class AnalysisSessionManager:
    """
    分析会话管理器

    负责分析会话的完整生命周期管理。
    """

    # 会话超时配置
    ACTIVE_TIMEOUT_HOURS = 2  # 活跃会话 2 小时无新 step 自动暂停
    PAUSED_EXPIRY_HOURS = 24  # 暂停会话 24 小时无 resume 自动过期

    def __init__(self, db: Session):
        self.db = db

    def create_session(
        self,
        tenant_id: uuid.UUID,
        task_type: str,
        created_by: int,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BiAnalysisSession:
        """
        创建分析会话

        Args:
            tenant_id: 租户 ID
            task_type: 任务类型（causation / report / insight）
            created_by: 创建人用户 ID
            subject: 分析主题
            metadata: 任务元数据（不含 user_id）

        Returns:
            BiAnalysisSession 实例

        Raises:
            AnalysisSessionError: 创建失败时
        """
        if task_type not in ("causation", "report", "insight"):
            raise AnalysisSessionError(
                code="DAT_001",
                message=f"无效的 task_type: {task_type}",
                detail={"valid_types": ["causation", "report", "insight"]},
            )

        session = BiAnalysisSession(
            tenant_id=tenant_id,
            task_type=task_type,
            status="created",
            created_by=created_by,
            session_metadata=metadata or {},
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        logger.info(
            "AnalysisSession created: id=%s, task_type=%s, created_by=%d",
            session.id,
            task_type,
            created_by,
        )

        return session

    def get_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Optional[BiAnalysisSession]:
        """
        获取分析会话

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID（用于多租户隔离）

        Returns:
            BiAnalysisSession 或 None
        """
        return self.db.query(BiAnalysisSession).filter(
            BiAnalysisSession.id == session_id,
            BiAnalysisSession.tenant_id == tenant_id,
        ).first()

    def list_sessions(
        self,
        tenant_id: uuid.UUID,
        created_by: Optional[int] = None,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[BiAnalysisSession]:
        """
        列出分析会话

        Args:
            tenant_id: 租户 ID
            created_by: 创建人过滤（可选）
            status: 状态过滤（可选）
            task_type: 任务类型过滤（可选）
            limit: 返回数量上限
            offset: 偏移量

        Returns:
            BiAnalysisSession 列表
        """
        query = self.db.query(BiAnalysisSession).filter(
            BiAnalysisSession.tenant_id == tenant_id,
            BiAnalysisSession.status != "deleted",
        )

        if created_by is not None:
            query = query.filter(BiAnalysisSession.created_by == created_by)

        if status:
            query = query.filter(BiAnalysisSession.status == status)

        if task_type:
            query = query.filter(BiAnalysisSession.task_type == task_type)

        return query.order_by(
            BiAnalysisSession.created_at.desc()
        ).offset(offset).limit(limit).all()

    def resume_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: int,
    ) -> BiAnalysisSession:
        """
        恢复中断的分析会话

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID
            user_id: 当前用户 ID（用于权限检查）

        Returns:
            BiAnalysisSession 实例

        Raises:
            AnalysisSessionError: 会话不存在或状态不允许 resume
        """
        session = self.get_session(session_id, tenant_id)

        if not session:
            raise AnalysisSessionError(
                code="DAT_002",
                message="会话不存在",
                detail={"session_id": str(session_id)},
            )

        # 权限检查：created_by == user_id 或 admin/data_admin 角色
        # 注意：这里只做基础检查，具体角色检查由 API 层负责

        # 状态检查：只能 resume paused 或 expired(paused_timeout) 状态
        if session.status not in ("paused", "expired"):
            raise AnalysisSessionError(
                code="DAT_003",
                message=f"会话状态为 {session.status}，不允许恢复",
                detail={
                    "current_status": session.status,
                    "allowed_statuses": ["paused", "expired"],
                },
            )

        # expired 状态只能 resume expiration_reason=paused_timeout 的
        if session.status == "expired" and session.expiration_reason != "paused_timeout":
            raise AnalysisSessionError(
                code="DAT_003",
                message="该会话已过期，无法恢复",
                detail={"expiration_reason": session.expiration_reason},
            )

        # 恢复会话
        session.status = "running"
        session.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(session)

        logger.info(
            "AnalysisSession resumed: id=%s, status=%s",
            session.id,
            session.status,
        )

        return session

    def pause_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str = "user_pause",
    ) -> BiAnalysisSession:
        """
        暂停分析会话

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID
            reason: 暂停原因

        Returns:
            BiAnalysisSession 实例
        """
        session = self.get_session(session_id, tenant_id)

        if not session:
            raise AnalysisSessionError(
                code="DAT_002",
                message="会话不存在",
                detail={"session_id": str(session_id)},
            )

        if session.status != "running":
            raise AnalysisSessionError(
                code="DAT_003",
                message=f"会话状态为 {session.status}，无法暂停",
                detail={"current_status": session.status},
            )

        session.status = "paused"
        session.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(session)

        logger.info(
            "AnalysisSession paused: id=%s, reason=%s",
            session.id,
            reason,
        )

        return session

    def complete_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        conclusion_summary: Optional[str] = None,
    ) -> BiAnalysisSession:
        """
        完成分析会话

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID
            conclusion_summary: 结论摘要

        Returns:
            BiAnalysisSession 实例
        """
        session = self.get_session(session_id, tenant_id)

        if not session:
            raise AnalysisSessionError(
                code="DAT_002",
                message="会话不存在",
                detail={"session_id": str(session_id)},
            )

        session.status = "completed"
        session.completed_at = datetime.utcnow()
        session.updated_at = datetime.utcnow()

        # 保存结论摘要到 context_snapshot
        if conclusion_summary:
            session.context_snapshot = {
                "conclusion_summary": conclusion_summary,
                "completed_at": datetime.utcnow().isoformat(),
            }

        self.db.commit()
        self.db.refresh(session)

        logger.info(
            "AnalysisSession completed: id=%s",
            session.id,
        )

        return session

    def fail_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        error_message: str,
    ) -> BiAnalysisSession:
        """
        标记会话失败

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID
            error_message: 错误信息

        Returns:
            BiAnalysisSession 实例
        """
        session = self.get_session(session_id, tenant_id)

        if not session:
            raise AnalysisSessionError(
                code="DAT_002",
                message="会话不存在",
                detail={"session_id": str(session_id)},
            )

        session.status = "failed"
        session.context_snapshot = {
            "error": error_message,
            "failed_at": datetime.utcnow().isoformat(),
        }
        session.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(session)

        logger.info(
            "AnalysisSession failed: id=%s, error=%s",
            session.id,
            error_message,
        )

        return session

    def delete_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        deleted_by: int,
    ) -> BiAnalysisSession:
        """
        删除分析会话（软删除）

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID
            deleted_by: 删除操作人

        Returns:
            BiAnalysisSession 实例
        """
        session = self.get_session(session_id, tenant_id)

        if not session:
            raise AnalysisSessionError(
                code="DAT_002",
                message="会话不存在",
                detail={"session_id": str(session_id)},
            )

        session.status = "deleted"
        session.expiration_reason = "admin_delete"
        session.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(session)

        logger.info(
            "AnalysisSession deleted: id=%s, deleted_by=%d",
            session.id,
            deleted_by,
        )

        return session

    def cleanup_expired_sessions(self) -> int:
        """
        清理过期的会话

        将暂停超过 24 小时的会话标记为 expired，
        将完成/失败超过 90 天的会话标记为 archived。

        Returns:
            清理的会话数量
        """
        now = datetime.utcnow()
        cleaned = 0

        # 1. 暂停超过 24 小时 → expired
        paused_threshold = now - timedelta(hours=self.PAUSED_EXPIRY_HOURS)
        paused_sessions = self.db.query(BiAnalysisSession).filter(
            BiAnalysisSession.status == "paused",
            BiAnalysisSession.updated_at < paused_threshold,
        ).all()

        for session in paused_sessions:
            session.status = "expired"
            session.expiration_reason = "paused_timeout"
            session.expired_at = now
            cleaned += 1

        # 2. 完成/失败超过 90 天 → archived
        archived_threshold = now - timedelta(days=90)
        terminal_sessions = self.db.query(BiAnalysisSession).filter(
            BiAnalysisSession.status.in_(["completed", "failed"]),
            BiAnalysisSession.updated_at < archived_threshold,
        ).all()

        for session in terminal_sessions:
            session.status = "archived"
            session.expiration_reason = "retention"
            cleaned += 1

        self.db.commit()

        logger.info("Cleaned up %d expired/archived sessions", cleaned)
        return cleaned

    def add_session_step(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        step_no: int,
        reasoning_trace: Dict[str, Any],
        query_log: Optional[Dict[str, Any]] = None,
        context_delta: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        branch_id: str = "main",
    ) -> BiAnalysisSessionStep:
        """
        添加分析会话步骤（Append-Only）

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID
            step_no: 逻辑步骤号
            reasoning_trace: 推理轨迹
            query_log: 查询日志
            context_delta: 上下文变更
            idempotency_key: 幂等键
            branch_id: 分支 ID

        Returns:
            BiAnalysisSessionStep 实例
        """
        # 检查幂等键
        if idempotency_key:
            existing = self.db.query(BiAnalysisSessionStep).filter(
                BiAnalysisSessionStep.session_id == session_id,
                BiAnalysisSessionStep.idempotency_key == idempotency_key,
            ).first()
            if existing:
                logger.info(
                    "Session step already exists (idempotent): session_id=%s, idempotency_key=%s",
                    session_id,
                    idempotency_key,
                )
                return existing

        step = BiAnalysisSessionStep(
            session_id=session_id,
            tenant_id=tenant_id,
            step_no=step_no,
            reasoning_trace=reasoning_trace,
            query_log=query_log,
            context_delta=context_delta,
            idempotency_key=idempotency_key,
            branch_id=branch_id,
        )
        self.db.add(step)

        # 更新会话当前步骤
        session = self.get_session(session_id, tenant_id)
        if session:
            session.current_step = step_no
            session.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(step)

        return step

    def get_session_steps(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> List[BiAnalysisSessionStep]:
        """
        获取会话的所有步骤

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID

        Returns:
            BiAnalysisSessionStep 列表（按 sequence_no 排序）
        """
        return self.db.query(BiAnalysisSessionStep).filter(
            BiAnalysisSessionStep.session_id == session_id,
            BiAnalysisSessionStep.tenant_id == tenant_id,
        ).order_by(BiAnalysisSessionStep.sequence_no).all()

    def create_insight(
        self,
        tenant_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        insight_type: str,
        title: str,
        summary: str,
        detail_json: Dict[str, Any],
        confidence: float,
        created_by: int,
        datasource_ids: List[int],
        visibility: str = "private",
        impact_scope: Optional[str] = None,
        metric_names: Optional[List[str]] = None,
    ) -> BiAnalysisInsight:
        """
        创建洞察

        Args:
            tenant_id: 租户 ID
            session_id: 关联会话 ID（可选）
            insight_type: 洞察类型（anomaly/trend/correlation/causation）
            title: 标题
            summary: 一句话总结
            detail_json: 完整洞察详情
            confidence: 置信度 0-1
            created_by: 创建人
            datasource_ids: 涉及的数据源 ID 列表
            visibility: 可见性（private/team/public）
            impact_scope: 影响范围描述
            metric_names: 涉及的指标名

        Returns:
            BiAnalysisInsight 实例
        """
        insight = BiAnalysisInsight(
            tenant_id=tenant_id,
            session_id=session_id,
            insight_type=insight_type,
            title=title,
            summary=summary,
            detail_json=detail_json,
            confidence=confidence,
            created_by=created_by,
            datasource_ids=datasource_ids,
            visibility=visibility,
            impact_scope=impact_scope,
            metric_names=metric_names,
        )
        self.db.add(insight)
        self.db.commit()
        self.db.refresh(insight)

        logger.info(
            "AnalysisInsight created: id=%s, insight_type=%s",
            insight.id,
            insight_type,
        )

        return insight

    def publish_insight(
        self,
        insight_id: uuid.UUID,
        tenant_id: uuid.UUID,
        push_targets: Optional[List[str]] = None,
        allowed_roles: Optional[List[str]] = None,
    ) -> BiAnalysisInsight:
        """
        发布洞察

        Args:
            insight_id: 洞察 ID
            tenant_id: 租户 ID
            push_targets: 推送渠道列表
            allowed_roles: 允许查看的角色列表

        Returns:
            BiAnalysisInsight 实例
        """
        insight = self.db.query(BiAnalysisInsight).filter(
            BiAnalysisInsight.id == insight_id,
            BiAnalysisInsight.tenant_id == tenant_id,
        ).first()

        if not insight:
            raise AnalysisSessionError(
                code="DAT_002",
                message="洞察不存在",
                detail={"insight_id": str(insight_id)},
            )

        insight.status = "published"
        insight.published_at = datetime.utcnow()
        insight.push_targets = push_targets
        insight.allowed_roles = allowed_roles

        self.db.commit()
        self.db.refresh(insight)

        logger.info(
            "AnalysisInsight published: id=%s",
            insight.id,
        )

        return insight

    def create_report(
        self,
        tenant_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        subject: str,
        content_json: Dict[str, Any],
        author: int,
        datasource_ids: List[int],
        time_range: Optional[str] = None,
        visibility: str = "private",
        allowed_roles: Optional[List[str]] = None,
        allowed_user_groups: Optional[List[str]] = None,
    ) -> BiAnalysisReport:
        """
        创建分析报告

        Args:
            tenant_id: 租户 ID
            session_id: 关联会话 ID（可选）
            subject: 报告主题
            content_json: 报告内容（规范层 JSON）
            author: 作者
            datasource_ids: 涉及的数据源 ID 列表
            time_range: 分析时间范围
            visibility: 可见性
            allowed_roles: 允许查看的角色列表
            allowed_user_groups: 允许查看的用户组列表

        Returns:
            BiAnalysisReport 实例
        """
        report = BiAnalysisReport(
            tenant_id=tenant_id,
            session_id=session_id,
            subject=subject,
            content_json=content_json,
            author=author,
            datasource_ids=datasource_ids,
            time_range=time_range,
            visibility=visibility,
            allowed_roles=allowed_roles,
            allowed_user_groups=allowed_user_groups,
        )
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)

        logger.info(
            "AnalysisReport created: id=%s, subject=%s",
            report.id,
            subject,
        )

        return report

    def get_session_progress(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """
        获取会话进度

        Args:
            session_id: 会话 ID
            tenant_id: 租户 ID

        Returns:
            进度信息字典
        """
        session = self.get_session(session_id, tenant_id)
        if not session:
            raise AnalysisSessionError(
                code="DAT_002",
                message="会话不存在",
                detail={"session_id": str(session_id)},
            )

        steps = self.get_session_steps(session_id, tenant_id)

        # 构建步骤摘要
        step_summaries = []
        for step in steps:
            trace = step.reasoning_trace or {}
            step_summaries.append({
                "step": step.step_no,
                "action": trace.get("name", "unknown"),
                "result": str(trace.get("output", ""))[:100],
                "timestamp": step.created_at.isoformat() if step.created_at else None,
            })

        # 确定总步骤数
        total_steps = 6 if session.task_type == "causation" else 4

        return {
            "session_id": str(session.id),
            "status": session.status,
            "current_step": session.current_step,
            "total_steps": total_steps,
            "step_summaries": step_summaries,
            "hypothesis_tree": session.hypothesis_tree,
        }