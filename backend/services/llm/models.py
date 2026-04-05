"""LLM 配置数据模型"""
from typing import Optional

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON, Index
from app.core.database import Base, JSONB, sa_func, sa_text # 导入中央配置的 Base, JSONB, func, text

class LLMConfig(Base):
    """LLM 配置"""
    __tablename__ = "ai_llm_configs" # 表名前缀规范化

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), default="openai", server_default=sa_text("'openai'"))
    base_url = Column(String(512), default="https://api.openai.com/v1", server_default=sa_text("'https://api.openai.com/v1'"))
    api_key_encrypted = Column(String(512), nullable=False) # 密码加密后长度可能变长，使用 String(512)
    model = Column(String(128), default="gpt-4o-mini", server_default=sa_text("'gpt-4o-mini'"))
    temperature = Column(Float, default=0.7, server_default=sa_func.cast(0.7, Float()))
    max_tokens = Column(Integer, default=1024, server_default=sa_func.cast(1024, Integer()))
    is_active = Column(Boolean, default=False, server_default=sa_text('false')) # Boolean 默认值
    created_at = Column(DateTime, server_default=sa_func.now()) # DateTime 默认值
    updated_at = Column(DateTime, server_default=sa_func.now(), onupdate=sa_func.now()) # DateTime 默认值和更新

    def to_dict(self):
        """返回配置，隐藏 api_key"""
        return {
            "id": self.id,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "is_active": self.is_active,
            "has_api_key": bool(self.api_key_encrypted),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# 从中央配置导入 SessionLocal
from app.core.database import SessionLocal
from sqlalchemy.orm import Session

class LLMConfigDatabase:
    """LLM 配置数据库 - 不再是单例，直接使用中央 SessionLocal"""

    def __init__(self, db_path: str = None):
        """db_path 参数不再使用，保留签名以兼容旧代码"""
        pass

    def get_session(self) -> Session:
        """获取当前线程的 session"""
        s = SessionLocal()
        s.expire_all()
        return s

    def get_config(self) -> Optional[LLMConfig]:
        session = self.get_session()
        try:
            return session.query(LLMConfig).first()
        finally:
            session.close()

    def save_config(self, provider, base_url, api_key_encrypted, model, temperature, max_tokens, is_active):
        session = self.get_session()
        try:
            config = session.query(LLMConfig).first()
            if config:
                config.provider = provider
                config.base_url = base_url
                config.api_key_encrypted = api_key_encrypted
                config.model = model
                config.temperature = temperature
                config.max_tokens = max_tokens
                config.is_active = is_active
                # updated_at 会由 onupdate 自动更新
            else:
                config = LLMConfig(
                    provider=provider,
                    base_url=base_url,
                    api_key_encrypted=api_key_encrypted,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    is_active=is_active,
                )
                session.add(config)
            session.commit()
        finally:
            session.close()

    def delete_config(self):
        session = self.get_session()
        try:
            session.query(LLMConfig).delete()
            session.commit()
        finally:
            session.close()


# ─────────────────────────────────────────────────────────────────────────────
# NL-to-Query 查询审计日志（PRD §10.1）
# ─────────────────────────────────────────────────────────────────────────────

class NlqQueryLog(Base):
    """
    NL-to-Query 查询审计日志表。

    每次 NL-to-Query 请求（成功或失败）均记录一条。
    注意：VizQL JSON 会记录，但查询结果数据不记录（PRD §10.4 数据隔离）。
    """
    __tablename__ = "nlq_query_logs"
    __table_args__ = (
        Index("ix_nlq_log_user_created", "user_id", "created_at"),
        Index("ix_nlq_log_datasource", "datasource_luid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    question = Column(Text, nullable=False)
    intent = Column(String(32), nullable=True)
    datasource_luid = Column(String(256), nullable=True)
    vizql_json = Column(JSONB, nullable=True)  # 仅记录查询结构，不记录结果
    response_type = Column(String(16), nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    error_code = Column(String(16), nullable=True)  # 成功时为 NULL
    created_at = Column(DateTime, server_default=sa_func.now(), nullable=False)


def log_nlq_query(
    user_id: int,
    question: str,
    intent: str = None,
    datasource_luid: str = None,
    vizql_json: dict = None,
    response_type: str = None,
    execution_time_ms: int = None,
    error_code: str = None,
) -> None:
    """
    写入一条 NL-to-Query 审计日志（PRD §10.1）。

    在 search.py 的 /api/search/query 返回前调用（无论成功或失败）。
    注意：此函数为 fire-and-forget，异常不向上抛出以避免干扰主流程。
    """
    try:
        from app.core.database import SessionLocal
        session = SessionLocal()
        try:
            log = NlqQueryLog(
                user_id=user_id,
                question=question,
                intent=intent,
                datasource_luid=datasource_luid,
                vizql_json=vizql_json,
                response_type=response_type,
                execution_time_ms=execution_time_ms,
                error_code=error_code,
            )
            session.add(log)
            session.commit()
        finally:
            session.close()
    except Exception:
        # fire-and-forget，审计失败不干扰主流程
        pass

