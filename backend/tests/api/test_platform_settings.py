"""平台设置 API 冒烟测试

测试范围：
- GET /api/platform-settings/ — 任意登录用户可读
- PUT /api/platform-settings/ — 仅 admin 可写，字段校验

运行方式：
    cd backend && .venv/bin/python -m pytest tests/api/test_platform_settings.py -v

前置条件：
    conftest.py 会自动创建 admin 用户 (admin/admin123) 和 smoke_analyst 用户 (smoke_analyst/analyst123)
"""
import pytest
from starlette.testclient import TestClient


# -------------------------------------------------------------------
# GET — 任意登录用户可读
# -------------------------------------------------------------------

def test_get_platform_settings_as_admin(admin_client: TestClient):
    """Admin GET 返回 200，包含 platform_name、logo_url 等字段"""
    resp = admin_client.get("/api/platform-settings/")
    assert resp.status_code == 200
    data = resp.json()
    assert "platform_name" in data
    assert "logo_url" in data
    assert "platform_subtitle" in data
    assert "favicon_url" in data


def test_get_platform_settings_unauthenticated(client: TestClient):
    """未登录返回 401 或 403"""
    resp = client.get("/api/platform-settings/")
    assert resp.status_code in (401, 403)


# -------------------------------------------------------------------
# PUT — 仅 admin 可写
# -------------------------------------------------------------------

def test_put_platform_settings_as_admin(admin_client: TestClient):
    """Admin PUT 返回 200，新值入库"""
    payload = {
        "platform_name": "木兰 BI 平台 测试",
        "platform_subtitle": "数据建模与治理平台",
        "logo_url": "https://httpbin.org/image/png",
        "favicon_url": None,
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform_name"] == "木兰 BI 平台 测试"
    assert data["logo_url"] == "https://httpbin.org/image/png"


def test_put_platform_settings_as_non_admin(analyst_client: TestClient):
    """非 admin 用户 PUT 返回 403（analyst 登录后 session 为 user_session）"""
    payload = {
        "platform_name": "黑客平台",
        "logo_url": "https://evil.com/logo.png",
        "platform_subtitle": None,
        "favicon_url": None,
    }
    resp = analyst_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 403


# -------------------------------------------------------------------
# 端到端 — PUT 成功后再 GET 验证持久化
# -------------------------------------------------------------------

def test_put_and_get_platform_name_mulan(admin_client: TestClient):
    """PUT platform_name=mulan 后 GET 确认已持久化"""
    payload = {
        "platform_name": "mulan",
        "platform_subtitle": None,
        "logo_url": "https://httpbin.org/image/png",
        "favicon_url": None,
    }
    put_resp = admin_client.put("/api/platform-settings/", json=payload)
    assert put_resp.status_code == 200

    get_resp = admin_client.get("/api/platform-settings/")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["platform_name"] == "mulan"


# -------------------------------------------------------------------
# 字段校验 — logo_url
# -------------------------------------------------------------------

def test_put_platform_settings_invalid_url(admin_client: TestClient):
    """logo_url 无效返回 422"""
    payload = {
        "platform_name": "测试平台",
        "logo_url": "not-a-valid-url",
        "platform_subtitle": None,
        "favicon_url": None,
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 422


# -------------------------------------------------------------------
# 字段校验 — platform_name
# -------------------------------------------------------------------

def test_put_platform_settings_empty_name(admin_client: TestClient):
    """platform_name 为空返回 422"""
    payload = {
        "platform_name": "",
        "logo_url": "https://example.com/logo.png",
        "platform_subtitle": None,
        "favicon_url": None,
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 422


def test_put_platform_settings_name_too_long(admin_client: TestClient):
    """platform_name 超长（>128）返回 422"""
    payload = {
        "platform_name": "x" * 200,
        "logo_url": "https://example.com/logo.png",
        "platform_subtitle": None,
        "favicon_url": None,
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 422


# -------------------------------------------------------------------
# 字段校验 — favicon_url（Review 补充）
# -------------------------------------------------------------------

def test_put_platform_settings_invalid_favicon_url(admin_client: TestClient):
    """favicon_url 无效返回 422"""
    payload = {
        "platform_name": "测试平台",
        "logo_url": "https://example.com/logo.png",
        "platform_subtitle": None,
        "favicon_url": "not-a-valid-url",
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 422


def test_put_platform_settings_favicon_url_too_long(admin_client: TestClient):
    """favicon_url 超长（>512）返回 422"""
    payload = {
        "platform_name": "测试平台",
        "logo_url": "https://example.com/logo.png",
        "platform_subtitle": None,
        "favicon_url": "https://example.com/" + ("x" * 500),
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 422


# -------------------------------------------------------------------
# 字段校验 — platform_subtitle（Review 补充）
# -------------------------------------------------------------------

def test_put_platform_settings_subtitle_too_long(admin_client: TestClient):
    """platform_subtitle 超长（>256）返回 422"""
    payload = {
        "platform_name": "测试平台",
        "logo_url": "https://example.com/logo.png",
        "platform_subtitle": "x" * 300,
        "favicon_url": None,
    }
    resp = admin_client.put("/api/platform-settings/", json=payload)
    assert resp.status_code == 422


# -------------------------------------------------------------------
# 回归测试 — PUT 无 trailing slash 不应 307 重定向导致 Failed to fetch
# 根因：FastAPI 默认对无斜杠路径返回 307 重定向到有斜杠版本，
#       浏览器跟随 307 时把 PUT 变成 GET，导致 "Failed to fetch"
# 修复：router = APIRouter(redirect_slashes=False)
# -------------------------------------------------------------------

def test_put_without_trailing_slash_no_redirect(admin_client: TestClient):
    """PUT /api/platform-settings（无斜杠）应返回 307 而非成功，防止浏览器静默失败"""
    payload = {
        "platform_name": "回归测试",
        "logo_url": "https://httpbin.org/image/png",
        "platform_subtitle": None,
        "favicon_url": None,
    }
    resp = admin_client.put("/api/platform-settings", json=payload)
    # redirect_slashes=False 后，无斜杠路径不再被重定向
    # 期望：404（路径不存在）或 307（明确拒绝重定向），绝不应该是 200
    assert resp.status_code in (307, 404), (
        f"PUT 无 trailing slash 应拒绝重定向，实际返回 {resp.status_code}。"
        "若返回 200 说明修复失效，浏览器会因 307 变成 GET 而报 Failed to fetch"
    )
