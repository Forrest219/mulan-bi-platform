"""日志数据库模型"""
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, Integer, String, Text, DateTime
from app.core.database import Base, JSONB, sa_func, sa_text


class ScanLog(Base):
    """扫描日志表"""
    __tablename__ = "bi_scan_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_time = Column(DateTime, nullable=False, server_default=sa_func.now())
    database_name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)
    table_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    total_violations = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    error_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    warning_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    info_count = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
    duration_seconds = Column(Text, nullable=True)
    status = Column(String(32), default="completed", server_default=sa_text("'completed'"))
    error_message = Column(Text, nullable=True)
    # B13: 脱敏后的结果，仅存储 results_masked
    results_json_masked = Column(JSONB, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scan_time": self.scan_time.strftime("%Y-%m-%d %H:%M:%S") if self.scan_time else None,
            "database_name": self.database_name,
            "db_type": self.db_type,
            "table_count": self.table_count,
            "total_violations": self.total_violations,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error_message": self.error_message,
        }


class RuleChangeLog(Base):
    """规则变更日志表"""
    __tablename__ = "bi_rule_change_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    change_time = Column(DateTime, nullable=False, server_default=sa_func.now())
    operator = Column(String(128), default="system", server_default=sa_text("'system'"))
    operator_id = Column(Integer, nullable=True)
    rule_section = Column(String(64), nullable=False)
    change_type = Column(String(32), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "change_time": self.change_time.strftime("%Y-%m-%d %H:%M:%S") if self.change_time else None,
            "operator": self.operator,
            "operator_id": self.operator_id,
            "rule_section": self.rule_section,
            "change_type": self.change_type,
            "description": self.description,
        }


class OperationLog(Base):
    """操作日志表"""
    __tablename__ = "bi_operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    op_time = Column(DateTime, nullable=False, server_default=sa_func.now())
    operator = Column(String(128), default="anonymous", server_default=sa_text("'anonymous'"))
    operator_id = Column(Integer, nullable=True)
    operation_type = Column(String(64), nullable=False)
    target = Column(String(256), nullable=True)
    status = Column(String(32), default="success", server_default=sa_text("'success'"))
    details = Column(JSONB, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "op_time": self.op_time.strftime("%Y-%m-%d %H:%M:%S") if self.op_time else None,
            "operator": self.operator,
            "operator_id": self.operator_id,
            "operation_type": self.operation_type,
            "target": self.target,
            "status": self.status,
            "details": self.details,
        }


from app.core.database import SessionLocal
from sqlalchemy.orm import Session


class LogDatabase:
    """日志数据库管理"""

    def __init__(self, db_path: str = None):
        pass

    @property
    def session(self) -> Session:
        s = SessionLocal()
        s.expire_all()
        return s

    def add_scan_log(self, log: ScanLog):
        self.session.add(log)
        self.session.commit()

    def add_rule_change_log(self, log: RuleChangeLog):
        self.session.add(log)
        self.session.commit()

    def add_operation_log(self, log: OperationLog):
        self.session.add(log)
        self.session.commit()

    def get_scan_logs(self, limit: int = 100, database_name: str = None) -> List[ScanLog]:
        query = self.session.query(ScanLog)
        if database_name:
            query = query.filter(ScanLog.database_name == database_name)
        return query.order_by(ScanLog.scan_time.desc()).limit(limit).all()

    def get_rule_change_logs(self, limit: int = 100) -> List[RuleChangeLog]:
        return self.session.query(RuleChangeLog).order_by(
            RuleChangeLog.change_time.desc()
        ).limit(limit).all()

    def get_operation_logs(self, limit: int = 100, operation_type: str = None) -> List[OperationLog]:
        query = self.session.query(OperationLog)
        if operation_type:
            query = query.filter(OperationLog.operation_type == operation_type)
        return query.order_by(OperationLog.op_time.desc()).limit(limit).all()

    def get_statistics(self) -> Dict[str, Any]:
        from sqlalchemy import func
        total_scans = self.session.query(ScanLog).count()
        total_tables = self.session.query(func.sum(ScanLog.table_count)).scalar() or 0
        total_violations = self.session.query(func.sum(ScanLog.total_violations)).scalar() or 0
        return {
            "total_scans": total_scans,
            "total_tables": total_tables,
            "total_violations": total_violations,
        }
