"""需求管理数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, Integer, String, Text, DateTime
from app.core.database import Base, JSONB, sa_func # 导入中央配置的 Base, JSONB, func

class Requirement(Base):
    """需求表"""
    __tablename__ = "bi_requirements" # 表名前缀规范化

    id = Column(Integer, primary_key=True, autoincrement=True)
    create_time = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值
    update_time = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now()) # DateTime 默认值和更新

    # 需求基本信息
    title = Column(String(256), nullable=False)  # 需求标题
    requirement_type = Column(String(64), nullable=False)  # ddl_change, quality_issue, exception_apply, other

    # 轻量级三要素
    what_to_do = Column(Text, nullable=False)  # 做什么
    why_to_do = Column(Text, nullable=True)  # 为什么做
    impact_scope = Column(Text, nullable=True)  # 影响范围

    # 状态和优先级
    status = Column(String(32), default="pending", server_default=sa_text("'pending'"))  # pending, approved, rejected, done
    priority = Column(String(32), default="medium", server_default=sa_text("'medium'"))  # low, medium, high, urgent

    # 关联信息
    related_tables = Column(Text, nullable=True)  # 涉及的表，多个用逗号分隔
    applicant = Column(String(128), nullable=True)  # 申请人
    assignee = Column(String(128), nullable=True)  # 负责人

    # 审批信息
    approver = Column(String(128), nullable=True)  # 审批人
    approve_comment = Column(Text, nullable=True)  # 审批意见
    approve_time = Column(DateTime, nullable=True)  # 审批时间

    # 额外信息
    extra_data = Column(JSONB, nullable=True)  # JSON 格式存储额外信息, 改为 JSONB

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "create_time": self.create_time.strftime("%Y-%m-%d %H:%M:%S") if self.create_time else None,
            "update_time": self.update_time.strftime("%Y-%m-%d %H:%M:%S") if self.update_time else None,
            "title": self.title,
            "requirement_type": self.requirement_type,
            "what_to_do": self.what_to_do,
            "why_to_do": self.why_to_do,
            "impact_scope": self.impact_scope,
            "status": self.status,
            "priority": self.priority,
            "related_tables": self.related_tables,
            "applicant": self.applicant,
            "assignee": self.assignee,
            "approver": self.approver,
            "approve_comment": self.approve_comment,
            "approve_time": self.approve_time.strftime("%Y-%m-%d %H:%M:%S") if self.approve_time else None,
        }


# 从中央配置导入 SessionLocal
from app.core.database import SessionLocal
from sqlalchemy.orm import Session

class RequirementDatabase:
    """需求数据库管理 - 不再是单例，直接使用中央 SessionLocal"""

    def __init__(self, db_path: str = None):
        """db_path 参数不再使用，保留签名以兼容旧代码"""
        pass

    @property
    def session(self) -> Session:
        """每次访问获取当前线程的 session，并刷新缓存避免脏读"""
        s = SessionLocal()
        s.expire_all()
        return s

    def add_requirement(self, req: Requirement):
        """添加需求"""
        self.session.add(req)
        self.session.commit()

    def update_requirement(self, req: Requirement):
        """更新需求"""
        # update_time 会由 onupdate 自动更新，无需手动设置
        self.session.commit()

    def delete_requirement(self, req_id: int):
        """删除需求"""
        req = self.session.query(Requirement).filter(Requirement.id == req_id).first()
        if req:
            self.session.delete(req)
            self.session.commit()

    def get_requirement(self, req_id: int) -> Optional[Requirement]:
        """获取单个需求"""
        return self.session.query(Requirement).filter(Requirement.id == req_id).first()

    def get_requirements(
        self,
        limit: int = 100,
        status: str = None,
        requirement_type: str = None,
        priority: str = None
    ) -> List[Requirement]:
        """获取需求列表"""
        query = self.session.query(Requirement)

        if status:
            query = query.filter(Requirement.status == status)
        if requirement_type:
            query = query.filter(Requirement.requirement_type == requirement_type)
        if priority:
            query = query.filter(Requirement.priority == priority)

        return query.order_by(Requirement.create_time.desc()).limit(limit).all()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        total = self.session.query(Requirement).count()
        pending = self.session.query(Requirement).filter(Requirement.status == "pending").count()
        approved = self.session.query(Requirement).filter(Requirement.status == "approved").count()
        rejected = self.session.query(Requirement).filter(Requirement.status == "rejected").count()
        done = self.session.query(Requirement).filter(Requirement.status == "done").count()

        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "done": done
        }

    # close 方法不再需要
    # def close(self):
    #     self.session.close()

