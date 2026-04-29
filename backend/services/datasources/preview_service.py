"""
数据预览服务 - 为上传的文件生成预览数据
"""
import io
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd


class PreviewService:
    """数据预览服务"""

    def __init__(self, upload_dir: str = "/tmp/uploads"):
        self.upload_dir = Path(upload_dir)
        # 默认预览前 100 行
        self.DEFAULT_PREVIEW_ROWS = 100

    def get_preview(self, file_id: str, filename: str, rows: int = 100) -> Dict[str, Any]:
        """
        获取文件预览数据

        Args:
            file_id: 文件ID
            filename: 原始文件名（用于确定格式）
            rows: 预览行数，默认100

        Returns:
            {
                "file_id": str,
                "filename": str,
                "columns": List[str],
                "column_types": Dict[str, str],
                "data": List[Dict],  # 预览数据
                "total_rows": int,
                "preview_rows": int,
            }
        """
        ext = Path(filename).suffix.lower()
        # 查找文件
        file_path = None
        for candidate_ext in [".csv", ".xlsx", ".xls"]:
            candidate = self.upload_dir / f"{file_id}{candidate_ext}"
            if candidate.exists():
                file_path = candidate
                break

        if not file_path or not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_id}")

        content = file_path.read_bytes()

        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise ValueError(f"不支持的文件类型: {ext}")

        total_rows = len(df)
        preview_df = df.head(rows)

        # 转换为字典列表，处理特殊类型
        data = preview_df.fillna("").astype(str).to_dict(orient="records")

        return {
            "file_id": file_id,
            "filename": filename,
            "columns": df.columns.tolist(),
            "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "data": data,
            "total_rows": total_rows,
            "preview_rows": len(preview_df),
        }
