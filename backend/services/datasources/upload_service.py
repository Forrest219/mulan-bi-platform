"""
文件上传服务 - 处理 CSV/Excel 文件上传
"""
import io
import os
import uuid
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd


# 文件大小限制: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024

# 支持的文件类型
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
ALLOWED_MIME_TYPES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class UploadService:
    """文件上传服务"""

    def __init__(self, upload_dir: str = "/tmp/uploads"):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def validate_file(self, filename: str, file_size: int) -> Tuple[bool, str]:
        """验证文件大小和扩展名"""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"不支持的文件类型: {ext}，支持的类型: CSV, Excel (.xlsx, .xls)"
        if file_size > MAX_FILE_SIZE:
            return False, f"文件大小超过限制 (50MB)，当前大小: {file_size / (1024*1024):.1f}MB"
        return True, ""

    def save_file(self, content: bytes, filename: str) -> str:
        """保存文件到磁盘，返回文件ID"""
        file_id = uuid.uuid4().hex
        ext = Path(filename).suffix.lower()
        stored_path = self.upload_dir / f"{file_id}{ext}"
        stored_path.write_bytes(content)
        return file_id

    def parse_file(self, file_id: str, filename: str, content: bytes) -> Dict[str, Any]:
        """
        解析上传的文件，返回文件信息和数据结构
        
        Returns:
            {
                "file_id": str,
                "filename": str,
                "row_count": int,
                "columns": List[str],
                "column_types": Dict[str, str],
            }
        """
        ext = Path(filename).suffix.lower()
        try:
            if ext == ".csv":
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(io.BytesIO(content))
            else:
                raise ValueError(f"不支持的文件类型: {ext}")
        except Exception as e:
            raise ValueError(f"文件解析失败: {str(e)}")

        row_count = len(df)
        columns = df.columns.tolist()
        column_types = {col: str(dtype) for col, dtype in df.dtypes.items()}

        return {
            "file_id": file_id,
            "filename": filename,
            "row_count": row_count,
            "columns": columns,
            "column_types": column_types,
            "file_size": len(content),
        }

    def process_upload(self, filename: str, content: bytes) -> Dict[str, Any]:
        """
        处理完整的上传流程: 验证 -> 保存 -> 解析
        
        Returns:
            {
                "file_id": str,
                "filename": str,
                "row_count": int,
                "columns": List[str],
                "column_types": Dict[str, str],
                "preview_url": str,
            }
        """
        file_size = len(content)
        valid, err_msg = self.validate_file(filename, file_size)
        if not valid:
            raise ValueError(err_msg)

        file_id = self.save_file(content, filename)
        result = self.parse_file(file_id, filename, content)
        result["preview_url"] = f"/api/datasources/files/{file_id}/preview"
        return result
