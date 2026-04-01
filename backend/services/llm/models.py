"""LLM 配置数据模型"""
import threading
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()


class LLMConfig(Base):
    """LLM 配置"""
    __tablename__ = "llm_configs"

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), default="openai")
    base_url = Column(String(512), default="https://api.openai.com/v1")
    api_key_encrypted = Column(Text, nullable=False)
    model = Column(String(128), default="gpt-4o-mini")
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=1024)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

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


class LLMConfigDatabase:
    """LLM 配置数据库 — 线程安全单例"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_db(db_path)
        return cls._instance

    def _init_db(self, db_path: str = None):
        if db_path is None:
            import os
            db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "llm.db")
        self._engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def get_session(self):
        return self._Session()

    def get_config(self):
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
                config.updated_at = datetime.now()
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
