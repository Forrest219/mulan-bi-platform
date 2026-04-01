"""
共享加密模块 - PBKDF2 + Fernet 对称加密

用于数据源密码、Tableau PAT Token、LLM API Key 等敏感字段的加密存储。
每次加密使用随机 salt（16B），salt 前置于密文以便解密时提取。
"""
import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class CryptoHelper:
    """基于 PBKDF2+Fernet 的加解密工具"""

    def __init__(self, key: str):
        if not key:
            raise ValueError("Encryption key must not be empty")
        self._key = key

    def _derive_fernet(self, salt: bytes) -> Fernet:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        derived = base64.urlsafe_b64encode(kdf.derive(self._key.encode()))
        return Fernet(derived)

    def encrypt(self, plaintext: str) -> str:
        """加密：随机 salt(16B) + Fernet(ciphertext)，base64 编码"""
        salt = os.urandom(16)
        cipher = self._derive_fernet(salt)
        encrypted = cipher.encrypt(plaintext.encode())
        return base64.urlsafe_b64encode(salt + encrypted).decode()

    def decrypt(self, token: str) -> str:
        """解密：提取前 16 字节 salt，派生密钥后解密"""
        data = base64.urlsafe_b64decode(token.encode())
        salt = data[:16]
        ciphertext = data[16:]
        cipher = self._derive_fernet(salt)
        return cipher.decrypt(ciphertext).decode()
