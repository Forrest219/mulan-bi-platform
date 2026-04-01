"""日志数据库模型"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import json

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class ScanLog(Base):
    """扫描日志表"""
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_time = Column(DateTime, default=datetime.now, nullable=False)
    database_name = Column(String(128), nullable=False)
    db_type = Column(String(32), nullable=False)
    table_count = Column(Integer, default=0)
    total_violations = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    info_count = Column(Integer, default=0)
    duration_seconds = Column(Text, nullable=True)
    status = Column(String(32), default="completed")  # completed, failed
    error_message = Column(Text, nullable=True)
    results_json = Column(Text, nullable=True)  # JSON 格式存储违规详情

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
    __tablename__ = "rule_change_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    change_time = Column(DateTime, default=datetime.now, nullable=False)
    operator = Column(String(128), default="system")
    rule_section = Column(String(64), nullable=False)
    change_type = Column(String(32), nullable=False)  # created, updated, deleted
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "change_time": self.change_time.strftime("%Y-%m-%d %H:%M:%S") if self.change_time else None,
            "operator": self.operator,
            "rule_section": self.rule_section,
            "change_type": self.change_type,
            "description": self.description,
        }


class OperationLog(Base):
    """操作日志表"""
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    op_time = Column(DateTime, default=datetime.now, nullable=False)
    operator = Column(String(128), default="anonymous")
    operation_type = Column(String(64), nullable=False)  # login, scan, export, rule_change
    target = Column(String(256), nullable=True)  # 操作目标
    status = Column(String(32), default="success")  # success, failed
    details = Column(Text, nullable=True)  # JSON 格式存储详情

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "op_time": self.op_time.strftime("%Y-%m-%d %H:%M:%S") if self.op_time else None,
            "operator": self.operator,
            "operation_type": self.operation_type,
            "target": self.target,
            "status": self.status,
            "details": self.details,
        }


class LogDatabase:
    """日志数据库管理"""

    _instance = None

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if db_path is None:
                import os
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "logs.db")
            cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str):
        """初始化数据库"""
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def add_scan_log(self, log: ScanLog):
        """添加扫描日志"""
        self.session.add(log)
        self.session.commit()

    def add_rule_change_log(self, log: RuleChangeLog):
        """添加规则变更日志"""
        self.session.add(log)
        self.session.commit()

    def add_operation_log(self, log: OperationLog):
        """添加操作日志"""
        self.session.add(log)
        self.session.commit()

    def get_scan_logs(self, limit: int = 100, database_name: str = None) -> List[ScanLog]:
        """获取扫描日志"""
        query = self.session.query(ScanLog)
        if database_name:
            query = query.filter(ScanLog.database_name == database_name)
        return query.order_by(ScanLog.scan_time.desc()).limit(limit).all()

    def get_rule_change_logs(self, limit: int = 100) -> List[RuleChangeLog]:
        """获取规则变更日志"""
        return self.session.query(RuleChangeLog).order_by(
            RuleChangeLog.change_time.desc()
        ).limit(limit).all()

    def get_operation_logs(self, limit: int = 100, operation_type: str = None) -> List[OperationLog]:
        """获取操作日志"""
        query = self.session.query(OperationLog)
        if operation_type:
            query = query.filter(OperationLog.operation_type == operation_type)
        return query.order_by(OperationLog.op_time.desc()).limit(limit).all()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        from sqlalchemy import func

        total_scans = self.session.query(ScanLog).count()
        total_tables = self.session.query(
            func.sum(ScanLog.table_count)
        ).scalar() or 0
        total_violations = self.session.query(
            func.sum(ScanLog.total_violations)
        ).scalar() or 0

        return {
            "total_scans": total_scans,
            "total_tables": total_tables,
            "total_violations": total_violations,
        }

    def close(self):
        """关闭数据库连接"""
        self.session.close()
