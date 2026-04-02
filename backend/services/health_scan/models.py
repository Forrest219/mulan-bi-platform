"""数仓健康检查 - 数据模型"""
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime,
    Float, Text, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

Base = declarative_base()


class HealthScanRecord(Base):
    """健康扫描记录"""
    __tablename__ = "health_scan_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    datasource_id = Column(Integer, nullable=False, index=True)
    datasource_name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)
    database_name = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="pending")  # pending/running/success/failed
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    total_tables = Column(Integer, default=0)
    total_issues = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    medium_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    health_score = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

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
    __tablename__ = "health_scan_issues"
    __table_args__ = (
        Index("ix_issue_scan_severity", "scan_id", "severity"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("health_scan_records.id", ondelete="CASCADE"), nullable=False)
    severity = Column(String(16), nullable=False)  # high/medium/low
    object_type = Column(String(16), nullable=False)  # table/field
    object_name = Column(String(256), nullable=False)
    database_name = Column(String(128), nullable=True)
    issue_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    suggestion = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

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


class HealthScanDatabase:
    """健康检查数据库管理 - 单例模式（线程安全）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    if db_path is None:
                        import os
                        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "health_scan.db")
                    cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str):
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._scoped_session = scoped_session(Session)

    @property
    def session(self):
        return self._scoped_session()

    def close_session(self):
        self._scoped_session.remove()

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
                started_at=datetime.now(),
                triggered_by=triggered_by,
            )
            s.add(record)
            s.commit()
            return record
        except Exception:
            s.rollback()
            raise
        finally:
            self.close_session()

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
            record.finished_at = datetime.now()
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
            self.close_session()

    def get_scan(self, scan_id: int) -> Optional[HealthScanRecord]:
        s = self.session
        try:
            return s.query(HealthScanRecord).get(scan_id)
        finally:
            self.close_session()

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
            self.close_session()

    def get_latest_scans(self) -> List[HealthScanRecord]:
        """每个数据源的最新一次扫描"""
        s = self.session
        try:
            from sqlalchemy import func
            subq = s.query(
                HealthScanRecord.datasource_id,
                func.max(HealthScanRecord.id).label("max_id")
            ).group_by(HealthScanRecord.datasource_id).subquery()

            records = s.query(HealthScanRecord).join(
                subq, HealthScanRecord.id == subq.c.max_id
            ).all()
            return records
        finally:
            self.close_session()

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
            self.close_session()

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
            self.close_session()
