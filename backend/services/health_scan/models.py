"""数仓健康检查 - 数据模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, DateTime,
    Float, Text, ForeignKey, Index
)
from app.core.database import Base, sa_func, sa_text # 导入中央配置的 Base, func, text

class HealthScanRecord(Base):
    """健康扫描记录"""
    __tablename__ = "bi_health_scan_records" # 表名前缀规范化

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(Integer, nullable=False, index=True)
    datasource_name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)
    database_name = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default=sa_text("'pending'"))  # pending/running/success/failed
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    total_tables = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    total_issues = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    high_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    medium_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    low_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    health_score = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "datasource_id": self.datasource_id,
            "datasource_name": self.datasource_name,
            "db_type": self.db_type,
            "database_name": self.database_name,
            "status": self.status,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "total_tables": self.total_tables,
            "total_issues": self.total_issues,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "health_score": self.health_score,
            "error_message": self.error_message,
            "triggered_by": self.triggered_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class HealthScanIssue(Base):
    """扫描发现的问题"""
    __tablename__ = "bi_health_scan_issues" # 表名前缀规范化
    __table_args__ = (
        Index("ix_issue_scan_severity", "scan_id", "severity"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("bi_health_scan_records.id", ondelete="CASCADE"), nullable=False)
    severity = Column(String(16), nullable=False)  # high/medium/low
    object_type = Column(String(16), nullable=False)  # table/field
    object_name = Column(String(256), nullable=False)
    database_name = Column(String(128), nullable=True)
    issue_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    suggestion = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now()) # DateTime 默认值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scan_id": self.scan_id,
            "severity": self.severity,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "database_name": self.database_name,
            "issue_type": self.issue_type,
            "description": self.description,
            "suggestion": self.suggestion,
        }


# 从中央配置导入 SessionLocal
from app.core.database import SessionLocal
from sqlalchemy.orm import Session
from sqlalchemy import func

class HealthScanDatabase:
    """健康检查数据库管理 - 不再是单例，直接使用中央 SessionLocal"""

    def __init__(self, db_path: str = None):
        """db_path 参数不再使用，保留签名以兼容旧代码"""
        pass

    @property
    def session(self) -> Session:
        """每次访问获取当前线程的 session，并刷新缓存避免脏读"""
        s = SessionLocal()
        s.expire_all()
        return s

    # close_session 方法不再需要
    # def close_session(self):
    #     self.session.remove()

    # --- Scan Record CRUD ---

    def create_scan(self, datasource_id: int, datasource_name: str, db_type: str,
                    database_name: str, triggered_by: int = None) -> HealthScanRecord:
        s = self.session
        try:
            record = HealthScanRecord(
                datasource_id=datasource_id,
                datasource_name=datasource_name,
                db_type=db_type,
                database_name=database_name,
                status="running",
                started_at=sa_func.now(), # 使用 server_default
                triggered_by=triggered_by,
            )
            s.add(record)
            s.commit()
            return record
        except Exception:
            s.rollback()
            raise
        finally:
            s.close() # 确保会话关闭

    def finish_scan(self, scan_id: int, status: str, total_tables: int = 0,
                    total_issues: int = 0, high_count: int = 0, medium_count: int = 0,
                    low_count: int = 0, health_score: float = None,
                    error_message: str = None):
        s = self.session
        try:
            record = s.query(HealthScanRecord).get(scan_id)
            if not record:
                return
            record.status = status
            record.finished_at = sa_func.now() # 使用 server_default
            record.total_tables = total_tables
            record.total_issues = total_issues
            record.high_count = high_count
            record.medium_count = medium_count
            record.low_count = low_count
            record.health_score = health_score
            record.error_message = error_message
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close() # 确保会话关闭

    def get_scan(self, scan_id: int) -> Optional[HealthScanRecord]:
        s = self.session
        try:
            return s.query(HealthScanRecord).get(scan_id)
        finally:
            s.close() # 确保会话关闭

    def list_scans(self, datasource_id: int = None, page: int = 1,
                   page_size: int = 20) -> Dict[str, Any]:
        s = self.session
        try:
            q = s.query(HealthScanRecord)
            if datasource_id:
                q = q.filter(HealthScanRecord.datasource_id == datasource_id)
            total = q.count()
            items = q.order_by(HealthScanRecord.id.desc()) \
                     .offset((page - 1) * page_size).limit(page_size).all()
            return {"scans": [r.to_dict() for r in items], "total": total, "page": page, "page_size": page_size}
        finally:
            s.close() # 确保会话关闭

    def get_latest_scans(self) -> List[HealthScanRecord]:
        """每个数据源的最新一次扫描"""
        s = self.session
        try:
            subq = s.query(
                HealthScanRecord.datasource_id,
                func.max(HealthScanRecord.id).label("max_id")
            ).group_by(HealthScanRecord.datasource_id).subquery()

            records = s.query(HealthScanRecord).join(
                subq, HealthScanRecord.id == subq.c.max_id
            ).all()
            return records
        finally:
            s.close() # 确保会话关闭

    # --- Issues CRUD ---

    def batch_create_issues(self, scan_id: int, issues: List[Dict[str, Any]]) -> int:
        s = self.session
        try:
            objs = []
            for iss in issues:
                objs.append(HealthScanIssue(
                    scan_id=scan_id,
                    severity=iss["severity"],
                    object_type=iss["object_type"],
                    object_name=iss["object_name"],
                    database_name=iss.get("database_name"),
                    issue_type=iss["issue_type"],
                    description=iss["description"],
                    suggestion=iss.get("suggestion", ""),
                ))
            s.bulk_save_objects(objs)
            s.commit()
            return len(objs)
        except Exception:
            s.rollback()
            raise
        finally:
            s.close() # 确保会话关闭

    def get_scan_issues(self, scan_id: int, severity: str = None,
                        page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        s = self.session
        try:
            q = s.query(HealthScanIssue).filter(HealthScanIssue.scan_id == scan_id)
            if severity:
                q = q.filter(HealthScanIssue.severity == severity)
            total = q.count()
            items = q.order_by(HealthScanIssue.id).offset((page - 1) * page_size).limit(page_size).all()
            return {"issues": [i.to_dict() for i in items], "total": total, "page": page, "page_size": page_size}
        finally:
            s.close() # 确保会话关闭

