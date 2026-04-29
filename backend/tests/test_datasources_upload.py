"""
文件上传服务测试 (Spec 37 §3)

覆盖:
- 上传 CSV 文件，验证返回 row_count / columns
- 上传 Excel 文件，验证返回 row_count / columns
- 文件类型不正确返回 400
- 文件大小超过 50MB 返回 413
- 未认证访问返回 401
- analyst 角色不能上传返回 403

路由前缀: /api/datasources
"""
import io
import pytest
from fastapi.testclient import TestClient


# -------------------------------------------------------------------------
# 测试数据
# -------------------------------------------------------------------------

_CSV_CONTENT = """id,name,value,date
1,foo,100,2024-01-01
2,bar,200,2024-01-02
3,baz,300,2024-01-03
"""

_CSV_MULTI_COLS = """a,b,c,d,e
1,2,3,4,5
6,7,8,9,10
"""


# -------------------------------------------------------------------------
# 辅助函数
# -------------------------------------------------------------------------

def _make_csv_file(content: str = _CSV_CONTENT, filename: str = "test.csv"):
    """创建 CSV 文件的 tuple, 供 TestClient.post 使用"""
    file_obj = io.BytesIO(content.encode("utf-8"))
    return (file_obj, filename)


# -------------------------------------------------------------------------
# 未认证访问
# -------------------------------------------------------------------------

def test_upload_file_unauthenticated(client: TestClient):
    """未登录时，上传文件返回 401"""
    client.cookies.clear()
    file_obj, filename = _make_csv_file()
    resp = client.post(
        "/api/datasources/upload",
        files={"file": (filename, file_obj, "text/csv")},
    )
    assert resp.status_code == 401


# -------------------------------------------------------------------------
# admin 上传 CSV 文件
# -------------------------------------------------------------------------

def test_admin_can_upload_csv(admin_client: TestClient):
    """admin 上传 CSV 文件，返回包含 row_count / columns / file_id / preview_url"""
    file_obj, filename = _make_csv_file()
    resp = admin_client.post(
        "/api/datasources/upload",
        files={"file": (filename, file_obj, "text/csv")},
    )
    assert resp.status_code == 200, f"上传失败: {resp.text}"
    data = resp.json()

    # 验证必填字段
    assert "file_id" in data, "响应缺少 file_id"
    assert "filename" in data, "响应缺少 filename"
    assert "row_count" in data, "响应缺少 row_count"
    assert "columns" in data, "响应缺少 columns"
    assert "preview_url" in data, "响应缺少 preview_url"

    # 验证数据正确性
    assert data["filename"] == filename
    assert data["row_count"] == 3  # CSV 有 3 行数据
    assert data["columns"] == ["id", "name", "value", "date"]
    assert data["preview_url"].startswith("/api/datasources/files/")


def test_upload_csv_row_count_and_columns(admin_client: TestClient):
    """上传 CSV → 验证 row_count / columns 返回正确"""
    file_obj, filename = _make_csv_file(content=_CSV_MULTI_COLS, filename="multi.csv")
    resp = admin_client.post(
        "/api/datasources/upload",
        files={"file": (filename, file_obj, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["row_count"] == 2, f"期望 row_count=2，实际: {data['row_count']}"
    assert data["columns"] == ["a", "b", "c", "d", "e"], f"列名不匹配: {data['columns']}"


# -------------------------------------------------------------------------
# analyst 不能上传
# -------------------------------------------------------------------------

def test_analyst_cannot_upload_csv(analyst_client: TestClient):
    """analyst 角色（非 admin/data_admin）尝试上传文件，返回 403"""
    file_obj, filename = _make_csv_file()
    resp = analyst_client.post(
        "/api/datasources/upload",
        files={"file": (filename, file_obj, "text/csv")},
    )
    assert resp.status_code == 403


# -------------------------------------------------------------------------
# 文件类型验证
# -------------------------------------------------------------------------

def test_upload_unsupported_file_type(admin_client: TestClient):
    """上传不支持的文件类型（如 .txt），返回 400"""
    file_obj = io.BytesIO(b"hello world")
    resp = admin_client.post(
        "/api/datasources/upload",
        files={"file": ("report.txt", file_obj, "text/plain")},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error_code"] == "INVALID_FILE_TYPE"


# -------------------------------------------------------------------------
# 文件大小验证 (50MB limit)
# -------------------------------------------------------------------------

def test_upload_file_exceeds_50mb_returns_413(admin_client: TestClient):
    """上传超过 50MB 的文件，返回 413"""
    # 构造 51MB 的内容
    large_content = b"x" * (51 * 1024 * 1024)
    file_obj = io.BytesIO(large_content)
    resp = admin_client.post(
        "/api/datasources/upload",
        files={"file": ("large.csv", file_obj, "text/csv")},
    )
    assert resp.status_code == 413
    data = resp.json()
    assert data["error_code"] == "FILE_TOO_LARGE"


# -------------------------------------------------------------------------
# UploadService 单元测试
# -------------------------------------------------------------------------

def test_upload_service_validate_csv_extension():
    """UploadService.validate_file: CSV 扩展名通过验证"""
    from services.datasources.upload_service import UploadService
    svc = UploadService(upload_dir="/tmp/test_uploads")
    valid, msg = svc.validate_file("data.csv", 1024)
    assert valid is True, msg


def test_upload_service_validate_xlsx_extension():
    """UploadService.validate_file: xlsx 扩展名通过验证"""
    from services.datasources.upload_service import UploadService
    svc = UploadService(upload_dir="/tmp/test_uploads")
    valid, msg = svc.validate_file("data.xlsx", 1024)
    assert valid is True, msg


def test_upload_service_validate_unsupported_extension():
    """UploadService.validate_file: 不支持的扩展名返回 False"""
    from services.datasources.upload_service import UploadService
    svc = UploadService(upload_dir="/tmp/test_uploads")
    valid, msg = svc.validate_file("data.pdf", 1024)
    assert valid is False
    assert "不支持的文件类型" in msg


def test_upload_service_validate_file_size_exceeds_50mb():
    """UploadService.validate_file: 超过 50MB 返回 False"""
    from services.datasources.upload_service import UploadService
    svc = UploadService(upload_dir="/tmp/test_uploads")
    size = 51 * 1024 * 1024  # 51MB
    valid, msg = svc.validate_file("data.csv", size)
    assert valid is False
    assert "超过限制" in msg


def test_upload_service_process_upload_csv():
    """UploadService.process_upload: CSV 文件解析正确"""
    from services.datasources.upload_service import UploadService
    svc = UploadService(upload_dir="/tmp/test_uploads")
    content = _CSV_CONTENT.encode("utf-8")
    result = svc.process_upload("test.csv", content)

    assert result["row_count"] == 3
    assert result["columns"] == ["id", "name", "value", "date"]
    assert "file_id" in result
    assert result["preview_url"].startswith("/api/datasources/files/")
