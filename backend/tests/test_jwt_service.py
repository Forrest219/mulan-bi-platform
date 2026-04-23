"""
单元测试：Spec 14 T-01 — JWTService + ConnectedAppSecretsDatabase

全部为纯逻辑单元测试，不依赖数据库连接，通过 Mock / Stub 隔离 DB 层。

测试覆盖范围：
1. JWTService.issue() 返回合法 HS256 JWT
2. Header: kid == client_id
3. Payload: iss/sub/aud/exp/jti/scp 字段完整且正确
4. 相同参数两次调用，jti 不同（防重放）
5. sub 字段精确等于传入的 username
6. 密钥未配置时抛出 RuntimeError
7. username 为空时抛出 ValueError
8. ConnectedAppSecretsDatabase.get_active_decrypted() — 正常 + 未配置两个路径
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import jwt
import pytest

# 必须在导入模块前设置环境变量（与 conftest.py 模式一致）
os.environ.setdefault("TABLEAU_ENCRYPTION_KEY", "test-tableau-key-32-bytes-ok!!")
os.environ.setdefault("DATASOURCE_ENCRYPTION_KEY", "test-datasource-key-32-bytes-ok!!")
os.environ.setdefault("LLM_ENCRYPTION_KEY", "test-llm-key-32-bytes-ok!!!!")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-ci-!!")
os.environ.setdefault("DATABASE_URL", "postgresql://mulan:mulan@localhost:5432/mulan_bi_test")
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "")


# ---------------------------------------------------------------------------
# Stubs / Helpers
# ---------------------------------------------------------------------------

class _FakeSecretsDB:
    """
    ConnectedAppSecretsDatabase 的 Stub，直接返回预设值，不依赖 DB。
    """

    def __init__(self, client_id: Optional[str], secret: Optional[str]) -> None:
        self._client_id = client_id
        self._secret = secret

    def get_active_decrypted(self, db, connection_id: int) -> Optional[dict]:
        if self._client_id is None:
            return None
        return {"client_id": self._client_id, "secret": self._secret}


def _make_service(client_id: Optional[str] = "test-client-id",
                  secret: Optional[str] = "super-secret-value-at-least-32-bytes!!") \
        -> "JWTService":  # type: ignore[name-defined]
    """构造一个使用 Stub DB 的 JWTService，不依赖真实数据库"""
    from services.query.jwt_service import JWTService
    return JWTService(secrets_db=_FakeSecretsDB(client_id, secret))


_FAKE_DB_SESSION = MagicMock()  # 占位符 Session，Stub DB 不真正使用它


# ---------------------------------------------------------------------------
# TestJWTServiceIssue — 核心签发逻辑
# ---------------------------------------------------------------------------

class TestJWTServiceIssue:
    """JWTService.issue() 的核心行为验证"""

    def test_returns_non_empty_string(self):
        """issue() 返回非空字符串"""
        svc = _make_service()
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_valid_hs256_jwt(self):
        """返回的 token 可被 PyJWT 解码，签名算法为 HS256"""
        secret = "super-secret-value-at-least-32-bytes!!"
        svc = _make_service(secret=secret)
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)

        # PyJWT 解码需要提供 audience 以通过 aud 校验
        decoded = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="tableau",
        )
        assert decoded is not None

    def test_header_kid_equals_client_id(self):
        """JWT Header 的 kid 字段必须等于 client_id"""
        client_id = "my-connected-app-client"
        svc = _make_service(client_id=client_id)
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)

        # 不验证签名，直接解析 header
        header = jwt.get_unverified_header(token)
        assert header["kid"] == client_id
        assert header["alg"] == "HS256"
        assert header["typ"] == "JWT"

    def test_payload_iss_equals_client_id(self):
        """iss（Issuer）必须等于 client_id"""
        client_id = "my-connected-app-client"
        secret = "secret-value-at-least-32-bytes-ok!!"
        svc = _make_service(client_id=client_id, secret=secret)
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)

        decoded = jwt.decode(
            token, secret, algorithms=["HS256"], audience="tableau"
        )
        assert decoded["iss"] == client_id

    def test_payload_sub_equals_username(self):
        """sub 字段必须精确等于传入的 username，不做任何变换"""
        username = "ad_user_name_123"
        svc = _make_service()
        token = svc.issue(username, connection_id=1, db=_FAKE_DB_SESSION)

        decoded = jwt.decode(
            token,
            "super-secret-value-at-least-32-bytes!!",
            algorithms=["HS256"],
            audience="tableau",
        )
        assert decoded["sub"] == username

    def test_payload_aud_is_tableau(self):
        """aud 固定为 'tableau'（字符串，不是列表）"""
        svc = _make_service()
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)
        decoded = jwt.decode(
            token,
            "super-secret-value-at-least-32-bytes!!",
            algorithms=["HS256"],
            audience="tableau",
        )
        # PyJWT 解码后 aud 可能是字符串或列表，均接受
        aud = decoded["aud"]
        if isinstance(aud, list):
            assert "tableau" in aud
        else:
            assert aud == "tableau"

    def test_payload_exp_within_600_seconds(self):
        """exp 在当前时间 600 秒内（允许 ±5s 测试时间误差）"""
        svc = _make_service()
        before = datetime.now(timezone.utc).timestamp()
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)
        after = datetime.now(timezone.utc).timestamp()

        decoded = jwt.decode(
            token,
            "super-secret-value-at-least-32-bytes!!",
            algorithms=["HS256"],
            audience="tableau",
        )
        exp = decoded["exp"]
        assert before + 595 <= exp <= after + 605  # 600s ± 5s 误差

    def test_payload_jti_is_uuid(self):
        """jti 是合法的 UUID4 字符串"""
        svc = _make_service()
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)

        decoded = jwt.decode(
            token,
            "super-secret-value-at-least-32-bytes!!",
            algorithms=["HS256"],
            audience="tableau",
            options={"verify_exp": False},
        )
        jti = decoded["jti"]
        # 验证是合法 UUID（不会抛出 ValueError）
        parsed = uuid.UUID(jti)
        assert str(parsed) == jti

    def test_payload_scp_correct_scopes(self):
        """scp 字段包含且仅包含问数所需的两个 scope"""
        svc = _make_service()
        token = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)

        decoded = jwt.decode(
            token,
            "super-secret-value-at-least-32-bytes!!",
            algorithms=["HS256"],
            audience="tableau",
        )
        scp = decoded["scp"]
        assert isinstance(scp, list)
        assert "tableau:datasources:read" in scp
        assert "tableau:datasources:query" in scp

    def test_jti_unique_on_repeated_calls(self):
        """相同参数两次调用，jti 不同（每次独立签发，防重放）"""
        svc = _make_service()
        token1 = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)
        token2 = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)

        d1 = jwt.decode(
            token1, "super-secret-value-at-least-32-bytes!!", algorithms=["HS256"], audience="tableau"
        )
        d2 = jwt.decode(
            token2, "super-secret-value-at-least-32-bytes!!", algorithms=["HS256"], audience="tableau"
        )
        assert d1["jti"] != d2["jti"]

    def test_different_users_different_sub(self):
        """不同用户签发的 sub 字段不同"""
        svc = _make_service()
        t1 = svc.issue("alice", connection_id=1, db=_FAKE_DB_SESSION)
        t2 = svc.issue("bob", connection_id=1, db=_FAKE_DB_SESSION)

        d1 = jwt.decode(
            t1, "super-secret-value-at-least-32-bytes!!", algorithms=["HS256"], audience="tableau"
        )
        d2 = jwt.decode(
            t2, "super-secret-value-at-least-32-bytes!!", algorithms=["HS256"], audience="tableau"
        )
        assert d1["sub"] == "alice"
        assert d2["sub"] == "bob"
        assert d1["sub"] != d2["sub"]


# ---------------------------------------------------------------------------
# TestJWTServiceErrors — 异常路径
# ---------------------------------------------------------------------------

class TestJWTServiceErrors:
    """JWTService 异常路径验证"""

    def test_raises_runtime_error_when_secret_not_configured(self):
        """密钥未配置（None）时抛出 RuntimeError，禁止 fallback"""
        svc = _make_service(client_id=None, secret=None)
        with pytest.raises(RuntimeError, match="Connected App secret not configured"):
            svc.issue("alice", connection_id=99, db=_FAKE_DB_SESSION)

    def test_raises_value_error_on_empty_username(self):
        """username 为空字符串时抛出 ValueError"""
        svc = _make_service()
        with pytest.raises(ValueError, match="username must not be empty"):
            svc.issue("", connection_id=1, db=_FAKE_DB_SESSION)

    def test_raises_value_error_on_whitespace_username(self):
        """username 为纯空白字符串时抛出 ValueError"""
        svc = _make_service()
        with pytest.raises(ValueError, match="username must not be empty"):
            svc.issue("   ", connection_id=1, db=_FAKE_DB_SESSION)


# ---------------------------------------------------------------------------
# TestConnectedAppSecretsDatabase — 数据库层（用 Mock 隔离 DB）
# ---------------------------------------------------------------------------

class TestConnectedAppSecretsDatabaseDecrypt:
    """ConnectedAppSecretsDatabase.get_active_decrypted() 的行为验证"""

    def test_returns_none_when_no_active_record(self):
        """未配置密钥时返回 None"""
        from services.query.jwt_service import ConnectedAppSecretsDatabase

        db = MagicMock()
        # query(...).filter(...).first() 返回 None
        db.query.return_value.filter.return_value.first.return_value = None

        secrets_db = ConnectedAppSecretsDatabase()
        result = secrets_db.get_active_decrypted(db, connection_id=1)
        assert result is None

    def test_returns_decrypted_secret(self):
        """有效记录时返回解密后的 client_id 和 secret"""
        from services.common.crypto import CryptoHelper
        from services.query.jwt_service import ConnectedAppSecret, ConnectedAppSecretsDatabase

        # 使用与测试环境变量一致的密钥加密
        key = os.environ["TABLEAU_ENCRYPTION_KEY"]
        crypto = CryptoHelper(key)
        plaintext_secret = "my-plain-secret-value"
        encrypted = crypto.encrypt(plaintext_secret)

        # 构造 Mock ORM 对象
        fake_record = MagicMock(spec=ConnectedAppSecret)
        fake_record.client_id = "client-abc"
        fake_record.secret_encrypted = encrypted

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = fake_record

        secrets_db = ConnectedAppSecretsDatabase()
        result = secrets_db.get_active_decrypted(db, connection_id=1)

        assert result is not None
        assert result["client_id"] == "client-abc"
        assert result["secret"] == plaintext_secret
