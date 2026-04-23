"""
Spec 14 T-01 — Connected App 密钥存储 + JWT 签发服务

职责边界（严格遵守）：
- ConnectedAppSecretsDatabase : 密钥表 CRUD，读取时自动 Fernet 解密
- JWTService                  : 签发 Tableau Connected Apps 规范 JWT（HS256）
  - 不直接调用 MCP
  - 不持有全局单例（由 query_service 按需实例化）
  - 不持有 DB Session（调用方传入 db）

JWT 规范（Tableau Connected Apps HS256）：
  Header: alg=HS256, typ=JWT, kid=<client_id>
  Payload: iss, sub, aud="tableau", exp=now+600, jti=uuid4, scp=[两个 scope]
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Session

from app.core.crypto import get_tableau_crypto
from app.core.database import Base, sa_func, sa_text

# Tableau Connected Apps JWT 固定常量
_JWT_ALGORITHM = "HS256"
_JWT_AUDIENCE = "tableau"
_JWT_EXP_SECONDS = 600  # 10 分钟，Tableau 允许的最大值
_JWT_SCOPES = ["tableau:datasources:read", "tableau:datasources:query"]


class ConnectedAppSecret(Base):
    """query_connected_app_secrets — Tableau Connected App 密钥配置表"""

    __tablename__ = "query_connected_app_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    connection_id = Column(
        Integer,
        ForeignKey("tableau_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id = Column(String(256), nullable=False)
    secret_encrypted = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=sa_text("true"))
    created_by = Column(
        Integer,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=sa_func.now())
    updated_at = Column(DateTime, nullable=True)


class ConnectedAppSecretsDatabase:
    """
    Connected App 密钥 CRUD。

    读取时自动 Fernet 解密（复用 get_tableau_crypto()，与 PAT 存储机制一致）。
    写入时调用方负责加密（TABLEAU_ENCRYPTION_KEY 环境变量）。
    所有方法均接受 db: Session 参数，由调用方控制事务边界。
    """

    def upsert(
        self,
        db: Session,
        connection_id: int,
        client_id: str,
        secret_plaintext: str,
        created_by: Optional[int] = None,
    ) -> ConnectedAppSecret:
        """
        新增或替换指定连接的 Connected App 密钥。

        策略：先将该连接的旧记录标记为 is_active=False，再插入新记录。
        这样保留历史记录，同时 partial unique index 保证每个连接只有一条 active。
        """
        crypto = get_tableau_crypto()
        secret_encrypted = crypto.encrypt(secret_plaintext)

        # 停用旧记录
        db.query(ConnectedAppSecret).filter(
            ConnectedAppSecret.connection_id == connection_id,
            ConnectedAppSecret.is_active == True,  # noqa: E712
        ).update({"is_active": False, "updated_at": datetime.now(timezone.utc)})

        new_secret = ConnectedAppSecret(
            connection_id=connection_id,
            client_id=client_id,
            secret_encrypted=secret_encrypted,
            is_active=True,
            created_by=created_by,
        )
        db.add(new_secret)
        db.flush()
        return new_secret

    def get_active(
        self, db: Session, connection_id: int
    ) -> Optional[ConnectedAppSecret]:
        """获取指定连接当前激活的密钥记录（未解密）"""
        return (
            db.query(ConnectedAppSecret)
            .filter(
                ConnectedAppSecret.connection_id == connection_id,
                ConnectedAppSecret.is_active == True,  # noqa: E712
            )
            .first()
        )

    def get_active_decrypted(
        self, db: Session, connection_id: int
    ) -> Optional[dict]:
        """
        获取指定连接当前激活的密钥，并自动解密 secret。

        返回：
            {"client_id": str, "secret": str} 或 None（未配置时）
        """
        record = self.get_active(db, connection_id)
        if record is None:
            return None
        crypto = get_tableau_crypto()
        return {
            "client_id": record.client_id,
            "secret": crypto.decrypt(record.secret_encrypted),
        }

    def deactivate(self, db: Session, connection_id: int) -> int:
        """停用指定连接的所有密钥，返回受影响行数"""
        updated = (
            db.query(ConnectedAppSecret)
            .filter(
                ConnectedAppSecret.connection_id == connection_id,
                ConnectedAppSecret.is_active == True,  # noqa: E712
            )
            .update({"is_active": False, "updated_at": datetime.now(timezone.utc)})
        )
        return updated


class JWTService:
    """
    Tableau Connected Apps JWT 签发服务。

    设计要点：
    - 不持有全局单例，由 query_service 在每次请求时按需实例化
    - 不持有 DB Session，db 由调用方传入
    - 每次 issue() 生成唯一 jti，禁止跨请求复用 token
    - kid 字段与 client_id 一致（Tableau Server 用于查找验证密钥）
    """

    def __init__(self, secrets_db: Optional[ConnectedAppSecretsDatabase] = None) -> None:
        self._secrets_db = secrets_db or ConnectedAppSecretsDatabase()

    def issue(self, username: str, connection_id: int, db: Session) -> str:
        """
        签发符合 Tableau Connected Apps 规范的短效 JWT。

        Args:
            username      : 当前登录用户的 AD/Tableau 用户名（来自 auth_users.username）
            connection_id : Tableau 连接 ID（用于查找 Connected App 密钥）
            db            : SQLAlchemy Session（调用方传入，不由本方法管理生命周期）

        Returns:
            签名后的 JWT 字符串（HS256）

        Raises:
            RuntimeError : Connected App 密钥未配置时抛出（禁止 fallback 到 PAT）
            ValueError   : username 为空时抛出
        """
        if not username or not username.strip():
            raise ValueError("username must not be empty")

        creds = self._secrets_db.get_active_decrypted(db, connection_id)
        if creds is None:
            raise RuntimeError(
                f"Connected App secret not configured for connection_id={connection_id}. "
                "Please configure it via admin API before enabling query interface."
            )

        client_id: str = creds["client_id"]
        secret: str = creds["secret"]

        now = datetime.now(timezone.utc)
        payload = {
            "iss": client_id,
            "sub": username,
            "aud": _JWT_AUDIENCE,
            "exp": now + timedelta(seconds=_JWT_EXP_SECONDS),
            "jti": str(uuid.uuid4()),
            "scp": _JWT_SCOPES,
        }
        headers = {
            "kid": client_id,
        }

        token: str = jwt.encode(
            payload,
            secret,
            algorithm=_JWT_ALGORITHM,
            headers=headers,
        )
        return token
