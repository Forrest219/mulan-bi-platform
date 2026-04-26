"""
Viz Agent API 路由 (Spec 26 附录 A)

注册：services/visualization/api.py 中的 router
本文件作为重导出层，保持与 app/api/ 目录结构一致。
"""
from services.visualization.api import router

__all__ = ["router"]
