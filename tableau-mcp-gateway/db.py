"""
从 mulan 数据库读取 mcp_servers 表中首个 type='tableau' 且 is_active=true 的配置。
mcp_servers.credentials 中的 pat_value 为明文，直接使用。
"""
import logging
import os
import sys
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 把 mulan backend 加入 path，复用其 SQLAlchemy session
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, _BACKEND)


def get_active_tableau_config(config_id: Optional[int] = None) -> Optional[Dict[str, str]]:
    """返回 {'tableau_server', 'site_name', 'pat_name', 'pat_value'} 或 None。

    config_id: 指定加载哪条 mcp_servers 记录；None 时取 id 最小的活跃配置。
    """
    try:
        from dotenv import load_dotenv as _ld
        _ld(os.path.join(_BACKEND, ".env"))

        from app.core.database import SessionLocal
        from services.mcp.models import McpServer

        db = SessionLocal()
        try:
            q = db.query(McpServer).filter(
                McpServer.type == "tableau", McpServer.is_active.is_(True)
            )
            if config_id is not None:
                q = q.filter(McpServer.id == config_id)
            else:
                q = q.order_by(McpServer.id)
            row = q.first()
            if not row:
                logger.warning("mcp_servers: no active Tableau config found")
                return None

            creds = row.credentials or {}
            result = {
                "tableau_server": creds.get("tableau_server", ""),
                "site_name": creds.get("site_name", ""),
                "pat_name": creds.get("pat_name", ""),
                "pat_value": creds.get("pat_value", ""),
            }
            logger.info(
                "Loaded Tableau config: server=%s site=%s pat_name=%s",
                result["tableau_server"],
                result["site_name"],
                result["pat_name"],
            )
            return result
        finally:
            db.close()

    except Exception:
        logger.exception("Failed to load Tableau config from DB")
        return None
