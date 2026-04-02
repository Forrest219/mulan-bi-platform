"""规则配置持久化模型"""
from typing import List, Dict, Any, Optional

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import Session
from app.core.database import Base, SessionLocal, JSONB, sa_func


class RuleConfig(Base):
    __tablename__ = "bi_rule_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    description = Column(String(1024), default="", nullable=False)
    level = Column(String(32), default="MEDIUM", nullable=False)
    category = Column(String(64), default="general", nullable=False)
    db_type = Column(String(32), default="MySQL", nullable=False)
    suggestion = Column(String(1024), default="", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    is_custom = Column(Boolean, default=False, nullable=False)
    config_json = Column(JSONB, default={}, nullable=False)
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now(), nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "category": self.category,
            "db_type": self.db_type,
            "suggestion": self.suggestion,
            "status": "enabled" if self.enabled else "disabled",
            "built_in": not self.is_custom,
            "config_json": self.config_json or {},
        }


class RuleConfigDatabase:
    """规则配置数据库操作"""

    def _get_db(self) -> Session:
        return SessionLocal()

    def get_all(self) -> List[RuleConfig]:
        db = self._get_db()
        try:
            return db.query(RuleConfig).order_by(RuleConfig.rule_id).all()
        finally:
            db.close()

    def get_by_rule_id(self, rule_id: str) -> Optional[RuleConfig]:
        db = self._get_db()
        try:
            return db.query(RuleConfig).filter(RuleConfig.rule_id == rule_id).first()
        finally:
            db.close()

    def toggle(self, rule_id: str, enabled: bool) -> Optional[RuleConfig]:
        db = self._get_db()
        try:
            rule = db.query(RuleConfig).filter(RuleConfig.rule_id == rule_id).first()
            if rule:
                rule.enabled = enabled
                db.commit()
                db.refresh(rule)
            return rule
        finally:
            db.close()

    def create_rule(self, **kwargs) -> RuleConfig:
        db = self._get_db()
        try:
            new_rule = RuleConfig(**kwargs)
            db.add(new_rule)
            db.commit()
            db.refresh(new_rule)
            return new_rule
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete(self, rule_id: str) -> bool:
        db = self._get_db()
        try:
            rule = db.query(RuleConfig).filter(RuleConfig.rule_id == rule_id).first()
            if rule and rule.is_custom:
                db.delete(rule)
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def seed_defaults(self, default_rules: List[Dict]) -> None:
        db = self._get_db()
        try:
            for rule_data in default_rules:
                existing = db.query(RuleConfig).filter(
                    RuleConfig.rule_id == rule_data["rule_id"]
                ).first()
                if not existing:
                    db.add(RuleConfig(**rule_data))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
