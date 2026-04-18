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
    # B3 新增：purpose 路由、display_name、priority
    purpose = Column(String(50), default='default', server_default=sa_text("'default'"), nullable=False)
    display_name = Column(String(100), nullable=True)
    priority = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()), nullable=False)
    # 改造 1：api_key 最近更新时间（用于前端展示 Key 指纹更新时间）
    api_key_updated_at = Column(DateTime, nullable=True)

    def _build_api_key_preview(self, decrypted_key: Optional[str]) -> Optional[str]:
        """构建 api_key 掩码预览，保留前缀和后 4 位明文，中间全部替换为 •。

        示例：'sk-abc123xyz3f2a' → 'sk-•••••••••3f2a'
        """
        if not decrypted_key:
            return None
        if len(decrypted_key) <= 8:
            return "•" * len(decrypted_key)
        prefix = decrypted_key[:3] if decrypted_key.startswith("sk-") else decrypted_key[:2]
        suffix = decrypted_key[-4:]
        mask_len = len(decrypted_key) - len(prefix) - 4
        return f"{prefix}{'•' * mask_len}{suffix}"

    def to_dict(self):
        """返回配置，隐藏 api_key，附带掩码预览和更新时间"""
        # 解密仅用于生成 preview，不在返回体中暴露明文
        decrypted: Optional[str] = None
        if self.api_key_encrypted:
            try:
                from services.llm.service import _decrypt
                decrypted = _decrypt(self.api_key_encrypted)
            except Exception:
                # 密钥轮换等场景解密失败时，降级为固定掩码
                pass

        api_key_preview: Optional[str]
        if self.api_key_encrypted:
            api_key_preview = self._build_api_key_preview(decrypted) if decrypted else "••••••••"
        else:
            api_key_preview = None

        return {
            "id": self.id,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "is_active": self.is_active,
            "has_api_key": bool(self.api_key_encrypted),
            "api_key_preview": api_key_preview,
            "api_key_updated_at": self.api_key_updated_at.isoformat() if self.api_key_updated_at else None,
            "purpose": self.purpose,
            "display_name": self.display_name,
            "priority": self.priority,
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

    def get_config(self, purpose: str = "default") -> Optional[LLMConfig]:
        """
        获取 LLM 配置。

        路由规则（B3）：
        1. 先查 purpose=<purpose> AND is_active=True，按 priority DESC 取第一条
        2. 找不到则 fallback 查 purpose='default' AND is_active=True
        3. 仍找不到返回 None

        向后兼容：原调用方不传 purpose 时默认走 'default' 路由。
        """
        session = self.get_session()
        try:
            # Step 1: 查目标 purpose
            config = (
                session.query(LLMConfig)
                .filter(LLMConfig.purpose == purpose, LLMConfig.is_active == True)
                .order_by(LLMConfig.priority.desc())
                .first()
            )
            if config is not None:
                return config

            # Step 2: fallback 到 'default' purpose（仅当 purpose 本身不是 'default'）
            if purpose != "default":
                config = (
                    session.query(LLMConfig)
                    .filter(LLMConfig.purpose == "default", LLMConfig.is_active == True)
                    .order_by(LLMConfig.priority.desc())
                    .first()
                )
            return config
        finally:
            session.close()

    def save_config(
        self,
        provider,
        base_url,
        api_key_encrypted,
        model,
        temperature,
        max_tokens,
        is_active,
        purpose: str = "default",
        display_name: str | None = None,
        priority: int = 0,
    ):
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
                config.purpose = purpose
                if display_name is not None:
                    config.display_name = display_name
                config.priority = priority
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
                    purpose=purpose,
                    display_name=display_name,
                    priority=priority,
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

