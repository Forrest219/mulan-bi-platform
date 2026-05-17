"""
从 mulan 数据库读取可用的 Tableau MCP 配置。

新入口下 mcp_servers 只保存 Agent 工具绑定，Tableau URL/Site/PAT
以 tableau_connections 为权威来源。为兼容历史数据，仍保留从
mcp_servers.credentials 读取旧字段的 fallback。
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
        from app.core.crypto import get_tableau_crypto
        from sqlalchemy import text

        db = SessionLocal()
        try:
            if config_id is not None:
                row = db.execute(
                    text(
                        """
                        SELECT id, credentials, tableau_connection_id
                        FROM mcp_servers
                        WHERE type = 'tableau'
                          AND is_active IS TRUE
                          AND id = :config_id
                        LIMIT 1
                        """
                    ),
                    {"config_id": config_id},
                ).mappings().first()
            else:
                row = db.execute(
                    text(
                        """
                        SELECT id, credentials, tableau_connection_id
                        FROM mcp_servers
                        WHERE type = 'tableau'
                          AND is_active IS TRUE
                        ORDER BY id
                        LIMIT 1
                        """
                    )
                ).mappings().first()
            if not row:
                logger.warning("mcp_servers: no active Tableau config found")
                return None

            creds = row["credentials"] or {}
            connection_id = row["tableau_connection_id"] or creds.get("tableau_connection_id")
            if connection_id:
                conn = db.execute(
                    text(
                        """
                        SELECT server_url, site, token_name, token_encrypted
                        FROM tableau_connections
                        WHERE id = :connection_id
                        LIMIT 1
                        """
                    ),
                    {"connection_id": int(connection_id)},
                ).mappings().first()
                if not conn:
                    logger.warning("mcp_servers[%s] references missing tableau_connection_id=%s", row["id"], connection_id)
                    return None
                result = {
                    "tableau_server": conn["server_url"],
                    "site_name": conn["site"],
                    "pat_name": conn["token_name"],
                    "pat_value": get_tableau_crypto().decrypt(conn["token_encrypted"]),
                }
            else:
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
