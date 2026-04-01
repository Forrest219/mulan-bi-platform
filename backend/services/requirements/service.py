"""需求管理服务"""
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from .models import RequirementDatabase, Requirement


class RequirementService:
    """需求管理服务"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._db = RequirementDatabase()
        return cls._instance

    def create_requirement(
        self,
        title: str,
        what_to_do: str,
        requirement_type: str = "ddl_change",
        why_to_do: str = None,
        impact_scope: str = None,
        priority: str = "medium",
        related_tables: str = None,
        applicant: str = None,
        assignee: str = None
    ) -> int:
        """
        创建需求

        Args:
            title: 需求标题
            what_to_do: 做什么
            requirement_type: 需求类型 (ddl_change, quality_issue, exception_apply, other)
            why_to_do: 为什么做
            impact_scope: 影响范围
            priority: 优先级 (low, medium, high, urgent)
            related_tables: 涉及的表
            applicant: 申请人
            assignee: 负责人

        Returns:
            需求ID
        """
        req = Requirement(
            title=title,
            requirement_type=requirement_type,
            what_to_do=what_to_do,
            why_to_do=why_to_do,
            impact_scope=impact_scope,
            priority=priority,
            related_tables=related_tables,
            applicant=applicant,
            assignee=assignee,
            status="pending"
        )
        self._db.add_requirement(req)
        return req.id

    def update_requirement(
        self,
        req_id: int,
        title: str = None,
        what_to_do: str = None,
        why_to_do: str = None,
        impact_scope: str = None,
        priority: str = None,
        related_tables: str = None,
        assignee: str = None,
        status: str = None
    ) -> bool:
        """更新需求"""
        req = self._db.get_requirement(req_id)
        if not req:
            return False

        if title is not None:
            req.title = title
        if what_to_do is not None:
            req.what_to_do = what_to_do
        if why_to_do is not None:
            req.why_to_do = why_to_do
        if impact_scope is not None:
            req.impact_scope = impact_scope
        if priority is not None:
            req.priority = priority
        if related_tables is not None:
            req.related_tables = related_tables
        if assignee is not None:
            req.assignee = assignee
        if status is not None:
            req.status = status

        self._db.update_requirement(req)
        return True

    def approve_requirement(
        self,
        req_id: int,
        approver: str,
        comment: str = None,
        approved: bool = True
    ) -> bool:
        """审批需求"""
        req = self._db.get_requirement(req_id)
        if not req:
            return False

        req.approver = approver
        req.approve_comment = comment
        req.approve_time = datetime.now()
        req.status = "approved" if approved else "rejected"

        self._db.update_requirement(req)
        return True

    def mark_as_done(self, req_id: int) -> bool:
        """标记为完成"""
        req = self._db.get_requirement(req_id)
        if not req:
            return False

        req.status = "done"
        self._db.update_requirement(req)
        return True

    def delete_requirement(self, req_id: int) -> bool:
        """删除需求"""
        result = self._db.delete_requirement(req_id)
        return result is None or result == True

    def get_requirement(self, req_id: int) -> Optional[Dict[str, Any]]:
        """获取单个需求"""
        req = self._db.get_requirement(req_id)
        return req.to_dict() if req else None

    def get_requirements(
        self,
        limit: int = 100,
        status: str = None,
        requirement_type: str = None,
        priority: str = None
    ) -> List[Dict[str, Any]]:
        """获取需求列表"""
        reqs = self._db.get_requirements(
            limit=limit,
            status=status,
            requirement_type=requirement_type,
            priority=priority
        )
        return [req.to_dict() for req in reqs]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        return self._db.get_statistics()


# 全局服务实例
requirement_service = RequirementService()
