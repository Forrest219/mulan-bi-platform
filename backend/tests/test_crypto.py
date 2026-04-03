"""单元测试：CryptoHelper — Fernet 加解密"""
import pytest
from services.common.crypto import CryptoHelper


class TestCryptoHelper:
    """Fernet 加解密测试"""

    def test_encrypt_returns_non_empty_string(self):
        helper = CryptoHelper("test-key-32-bytes-abcdefgh!!")
        encrypted = helper.encrypt("hello world")
        assert encrypted
        assert isinstance(encrypted, str)
        assert encrypted != "hello world"

    def test_encrypt_produces_different_output_each_time(self):
        """每次加密结果不同（随机 salt）"""
        helper = CryptoHelper("test-key-32-bytes-abcdefgh!!")
        e1 = helper.encrypt("same plaintext")
        e2 = helper.encrypt("same plaintext")
        assert e1 != e2

    def test_decrypt_recovers_plaintext(self):
        """解密能正确还原明文"""
        helper = CryptoHelper("test-key-32-bytes-abcdefgh!!")
        original = "数据库密码: MyP@ssw0rd!2024"
        encrypted = helper.encrypt(original)
        decrypted = helper.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_various_texts(self):
        """测试各种文本内容"""
        helper = CryptoHelper("another-32-byte-key-for-test!!")
        texts = [
            "short",
            "中文字符",
            "空格 和 标点!?:,.",
            "a" * 1000,
            "new\nline\ttab",
        ]
        for text in texts:
            encrypted = helper.encrypt(text)
            decrypted = helper.decrypt(encrypted)
            assert decrypted == text

    def test_empty_key_raises(self):
        """空密钥抛出 ValueError"""
        with pytest.raises(ValueError):
            CryptoHelper("")

    def test_different_key_cannot_decrypt(self):
        """不同密钥无法解密"""
        helper1 = CryptoHelper("key-one-32-bytes-abcdefgh!!!")
        helper2 = CryptoHelper("key-two-32-bytes-abcdefgh!!!!")
        encrypted = helper1.encrypt("secret")
        with pytest.raises(Exception):  # Fernet 解密失败抛异常
            helper2.decrypt(encrypted)


class TestCryptoEncryptFactory:
    """加密工厂函数测试"""

    def test_get_datasource_crypto_requires_key(self, monkeypatch):
        """DATASOURCE_ENCRYPTION_KEY 未设置时抛出 RuntimeError"""
        monkeypatch.delenv("DATASOURCE_ENCRYPTION_KEY", raising=False)
        from app.core.crypto import get_datasource_crypto
        with pytest.raises(RuntimeError, match="DATASOURCE_ENCRYPTION_KEY"):
            get_datasource_crypto()

    def test_get_tableau_crypto_requires_key(self, monkeypatch):
        """TABLEAU_ENCRYPTION_KEY 未设置时抛出 RuntimeError"""
        monkeypatch.delenv("TABLEAU_ENCRYPTION_KEY", raising=False)
        from app.core.crypto import get_tableau_crypto
        with pytest.raises(RuntimeError, match="TABLEAU_ENCRYPTION_KEY"):
            get_tableau_crypto()

    def test_get_llm_crypto_falls_back_to_datasource(self, monkeypatch):
        """LLM_ENCRYPTION_KEY 未设置时回退到 DATASOURCE_ENCRYPTION_KEY"""
        monkeypatch.delenv("LLM_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("DATASOURCE_ENCRYPTION_KEY", "fallback-32-bytes-key-ok!!!!")
        from app.core.crypto import get_llm_crypto
        helper = get_llm_crypto()
        assert helper is not None
