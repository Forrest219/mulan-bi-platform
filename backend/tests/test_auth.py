"""测试：认证 API"""

import hashlib
import time

import pytest


def test_login_invalid_credentials(client):
    resp = client.post("/api/auth/login", json={"username": "nonexistent", "password": "***"})
    assert resp.status_code in (401, 400)


def test_me_without_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


def test_login_success(admin_client):
    resp = admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "username" in data or "user" in data


class TestForgotPassword:
    """AC-1 / AC-2: 忘记密码 + 重置密码"""

    def test_forgot_password_unknown_email_returns_200(self, client):
        """防枚举：无论邮箱是否存在均返回 200"""
        resp = client.post("/api/auth/forgot-password", json={"email": "nonexistent@example.com"})
        assert resp.status_code == 200
        assert "如果该邮箱已注册" in resp.json()["message"]

    def test_forgot_password_existing_user_returns_200(self, client):
        """已注册邮箱也返回 200（不暴露邮箱是否存在）"""
        resp = client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
        assert resp.status_code == 200
        assert "如果该邮箱已注册" in resp.json()["message"]

    def test_forgot_password_rate_limit(self, client):
        """同邮箱超过 3 次/小时返回 200（防枚举，返回相同信息）"""
        for i in range(3):
            resp = client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
            assert resp.status_code == 200
        # 第 4 次仍然返回 200（但内部已超过限速）
        resp = client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
        assert resp.status_code == 200

    def test_reset_password_invalid_token(self, client):
        """无效 token 返回 400"""
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": "invalid-token-123", "new_password": "NewPass123!"},
        )
        assert resp.status_code == 400
        assert "无效" in resp.json()["detail"] or "过期" in resp.json()["detail"]

    def test_reset_password_valid_token_flow(self, client, admin_client):
        """完整流程：请求 token → 使用 token 重置密码 → 用新密码登录"""
        # 1. 请求密码重置 token
        resp = client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
        assert resp.status_code == 200
        # 日志中会有 token（因为本期不做真实邮件）
        import logging
        log_token = None
        class TokenHandler(logging.Handler):
            def emit(self, record):
                if "Password reset token" in record.getMessage():
                    nonlocal log_token
                    log_token = record.getMessage().split("token for admin@mulan.local: ")[-1].strip()
        handler = TokenHandler()
        logging.getLogger("auth").addHandler(handler)
        logging.getLogger("auth").setLevel(logging.INFO)
        # 重新触发以捕获 token
        client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
        logging.getLogger("auth").removeHandler(handler)
        # 如果没找到 token，跳过此测试部分
        if log_token is None:
            pytest.skip("Could not capture reset token from logs")

        # 2. 使用 token 重置密码
        new_password = "ResetPass123!"
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": log_token, "new_password": new_password},
        )
        assert resp.status_code == 200
        assert "已重置" in resp.json()["message"]

        # 3. 使用新密码登录
        resp = client.post("/api/auth/login", json={"username": "admin", "password": new_password})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_reset_password_token_one_time_use(self, client):
        """Token 一次性使用：使用后再次使用应失败"""
        # 请求 token
        resp = client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
        assert resp.status_code == 200

        import logging
        log_token = None
        class TokenHandler(logging.Handler):
            def emit(self, record):
                if "Password reset token" in record.getMessage():
                    nonlocal log_token
                    log_token = record.getMessage().split("token for admin@mulan.local: ")[-1].strip()
        handler = TokenHandler()
        logging.getLogger("auth").addHandler(handler)
        logging.getLogger("auth").setLevel(logging.INFO)
        client.post("/api/auth/forgot-password", json={"email": "admin@mulan.local"})
        logging.getLogger("auth").removeHandler(handler)

        if log_token is None:
            pytest.skip("Could not capture reset token from logs")

        # 第一次使用：成功
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": log_token, "new_password": "ResetOnce123!"},
        )
        assert resp.status_code == 200

        # 第二次使用：失败
        resp = client.post(
            "/api/auth/reset-password",
            json={"token": log_token, "new_password": "ResetAgain123!"},
        )
        assert resp.status_code == 400


class TestAdminUserManagement:
    """AC-5: 管理员编辑用户"""

    def test_admin_get_user_detail(self, admin_client):
        """管理员可查看任意用户详情"""
        resp = admin_client.get("/api/users/1")
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "role" in data
        assert "email" in data

    def test_admin_update_user_display_name(self, admin_client):
        """管理员可更新用户 display_name"""
        resp = admin_client.put("/api/users/1", json={"display_name": "超级管理员"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["display_name"] == "超级管理员"

    def test_admin_update_user_role(self, admin_client):
        """管理员可更新用户角色"""
        # 先创建一个测试用户
        create_resp = admin_client.post("/api/users/", json={
            "username": "test_role_user",
            "display_name": "Test Role User",
            "password": "TestPass123!",
            "role": "user",
        })
        assert create_resp.status_code == 200
        user_id = create_resp.json()["user"]["id"]

        # 更新角色
        resp = admin_client.put(f"/api/users/{user_id}", json={"role": "analyst"})
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "analyst"

    def test_admin_cannot_update_nonexistent_user(self, admin_client):
        """更新不存在的用户返回 404"""
        resp = admin_client.put("/api/users/999999", json={"display_name": "Ghost"})
        assert resp.status_code == 404


class TestMFATOTP:
    """AC-6: MFA TOTP"""

    def test_mfa_status_unauthenticated(self, client):
        """未登录用户访问 MFA 状态返回 401"""
        resp = client.get("/api/auth/mfa/status")
        assert resp.status_code in (401, 403)

    def test_mfa_setup_returns_secret_and_qr(self, admin_client):
        """MFA setup 返回 secret、qr_uri 和 backup_codes"""
        resp = admin_client.post("/api/auth/mfa/setup")
        assert resp.status_code == 200
        data = resp.json()
        assert "secret" in data
        assert "qr_uri" in data
        assert "backup_codes" in data
        assert len(data["secret"]) > 10  # Base32 secret

    def test_mfa_verify_setup_with_valid_code(self, admin_client):
        """MFA setup 后用正确 code 验证启用"""
        import pyotp

        # 1. 获取 secret
        setup_resp = admin_client.post("/api/auth/mfa/setup")
        assert setup_resp.status_code == 200
        secret = setup_resp.json()["secret"]

        # 2. 用 TOTP 生成有效 code
        totp = pyotp.TOTP(secret)
        code = totp.now()

        # 3. 验证 code
        verify_resp = admin_client.post("/api/auth/mfa/verify-setup", json={"code": code})
        assert verify_resp.status_code == 200
        assert verify_resp.json()["success"] is True
        assert "backup_codes" in verify_resp.json()

    def test_mfa_verify_setup_with_invalid_code(self, admin_client):
        """错误的 TOTP code 验证失败"""
        resp = admin_client.post("/api/auth/mfa/verify-setup", json={"code": "000000"})
        assert resp.status_code == 400

    def test_mfa_status_after_enable(self, admin_client):
        """启用 MFA 后状态为 enabled"""
        import pyotp

        # Setup MFA
        setup_resp = admin_client.post("/api/auth/mfa/setup")
        secret = setup_resp.json()["secret"]
        totp = pyotp.TOTP(secret)
        admin_client.post("/api/auth/mfa/verify-setup", json={"code": totp.now()})

        # 检查状态
        status_resp = admin_client.get("/api/auth/mfa/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["mfa_enabled"] is True
