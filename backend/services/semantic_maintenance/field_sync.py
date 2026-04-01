"""
语义维护模块 - 字段级同步服务
通过 Tableau REST API 获取数据源字段元数据，写入 tableau_datasource_fields 表。
"""
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests

from .database import SemanticMaintenanceDatabase
from .models import SemanticStatus

logger = logging.getLogger(__name__)


class FieldSyncService:
    """字段级元数据同步服务（REST API 模式）"""

    def __init__(self, server_url: str, site_content_url: str,
                 token_name: str, token_value: str,
                 api_version: str = "3.21", db_path: str = None):
        self.server_url = server_url.rstrip("/")
        self.site_content_url = site_content_url  # REST signin 返回的 contentUrl
        self.token_name = token_name
        self.token_value = token_value
        self.api_version = api_version
        self.db = SemanticMaintenanceDatabase(db_path=db_path)
        self._auth_token: Optional[str] = None
        self._site_id: Optional[str] = None
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._auth_token:
            headers["X-Tableau-Auth"] = self._auth_token
        return headers

    def connect(self) -> bool:
        """REST API 认证"""
        try:
            resp = self._session.post(
                f"{self.server_url}/api/{self.api_version}/auth/signin",
                json={
                    "credentials": {
                        "personalAccessTokenName": self.token_name,
                        "personalAccessTokenSecret": self.token_value,
                        "site": {"contentUrl": self.site_content_url}
                    }
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._auth_token = data.get("credentials", {}).get("token", "")
                site_creds = data.get("credentials", {}).get("site", {})
                self._site_id = site_creds.get("id", "")
                logger.info("FieldSync REST auth success: site_id=%s", self._site_id)
                return True
            logger.warning("FieldSync REST auth failed: HTTP %s", resp.status_code)
            return False
        except Exception as e:
            logger.error("FieldSync REST auth error: %s", e, exc_info=True)
            return False

    def disconnect(self):
        """登出清理"""
        if self._auth_token:
            try:
                self._session.post(
                    f"{self.server_url}/api/{self.api_version}/auth/signout",
                    headers={"X-Tableau-Auth": self._auth_token},
                    timeout=5,
                )
            except Exception:
                pass
            self._auth_token = None
            self._site_id = None

    def _get_field_hash(self, field: Dict) -> str:
        """计算字段语义哈希，用于变更检测"""
        raw = (
            field.get("name", "") +
            field.get("type", "") +
            field.get("formula", "") +
            str(field.get("description", ""))
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _parse_datetime(self, value) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def sync_datasource_fields(
        self,
        connection_id: int,
        tableau_datasource_id: str,
        asset_id: int,  # tableau_assets.id
        datasource_luid: str,  # Tableau 数据源 LUID
    ) -> Dict[str, Any]:
        """同步数据源的所有字段，返回同步结果"""
        if not self._auth_token:
            raise Exception("未连接，请先调用 connect()")

        errors = []
        synced_count = 0
        skipped_count = 0

        # 通过 REST API 获取字段元数据
        url = (
            f"{self.server_url}/api/{self.api_version}"
            f"/sites/{self._site_id}/datasources/{datasource_luid}/fields"
        )

        try:
            resp = self._session.get(url, headers=self._headers(), timeout=30)
            if resp.status_code != 200:
                logger.warning("Fields API returned %s: %s", resp.status_code, resp.text[:300])
                errors.append(f"Fields API HTTP {resp.status_code}: {resp.text[:100]}")
                return {
                    "synced": synced_count,
                    "skipped": skipped_count,
                    "errors": errors,
                    "status": "failed",
                }

            data = resp.json()
            # 尝试提取字段列表
            raw_fields = []
            for key, val in data.items():
                if isinstance(val, list):
                    raw_fields = val
                    break
                elif isinstance(val, dict):
                    for inner_key in ("column", "field", "columns"):
                        inner = val.get(inner_key, [])
                        if isinstance(inner, list) and inner:
                            raw_fields = inner
                            break

            logger.info("Fetched %d raw fields for datasource %s", len(raw_fields), datasource_luid)

        except Exception as e:
            logger.error("Failed to fetch fields for datasource %s: %s", datasource_luid, e, exc_info=True)
            errors.append(f"获取字段列表失败: {e}")
            return {"synced": 0, "skipped": 0, "errors": errors, "status": "failed"}

        # 获取已有的字段记录（用于变更检测）
        existing_fields = {}
        for f in self.db.get_datasource_fields(asset_id):
            existing_fields[f.datasource_luid] = f  # key by luid

        now = datetime.now()
        synced_fields = []

        for raw in raw_fields:
            # 提取字段信息（兼容多种格式）
            field_name = raw.get("name", "") or raw.get("fieldName", "") or raw.get("id", "")
            field_caption = raw.get("caption", "") or raw.get("alias", "") or raw.get("name", "")
            data_type = raw.get("type", "") or raw.get("dataType", "") or raw.get("data_type", "")
            role = raw.get("role", "") or raw.get("fieldRole", "")
            description = raw.get("description", "") or raw.get("desc", "")
            formula = raw.get("formula", "") or raw.get("calculation", "") or raw.get("expression", "")
            is_hidden = raw.get("isHidden", False) or raw.get("hidden", False)
            aggregation = raw.get("aggregation", "") or raw.get("agg", "")

            if not field_name:
                continue

            # 构建字段 LUID（用于关联 tableau_datasource_fields）
            field_luid = f"{datasource_luid}.{field_name}"

            # 计算语义哈希
            semantic_hash = self._get_field_hash(raw)

            # 变更检测：跳过无变化的字段
            existing = existing_fields.get(field_luid)
            if existing:
                existing_hash = getattr(existing, "metadata_json", None)
                if existing_hash:
                    try:
                        existing_meta = json.loads(existing_hash)
                        if existing_meta.get("semantic_hash") == semantic_hash:
                            skipped_count += 1
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass

            # 构键字段数据
            field_data = {
                "field_name": field_name,
                "field_caption": field_caption,
                "data_type": data_type,
                "role": role if role in ("dimension", "measure", "") else None,
                "description": description or None,
                "formula": formula or None,
                "aggregation": aggregation or None,
                "is_calculated": bool(formula),
                "metadata_json": json.dumps({
                    "semantic_hash": semantic_hash,
                    "is_hidden": is_hidden,
                    "fetched_at": now.isoformat(),
                }, ensure_ascii=False),
            }

            try:
                self.db.upsert_datasource_fields(
                    asset_id=asset_id,
                    datasource_luid=field_luid,
                    fields=[field_data]
                )
                synced_count += 1
                synced_fields.append(field_data)
            except Exception as e:
                logger.warning("Upsert field %s failed: %s", field_name, e)
                errors.append(f"字段 {field_name} 写入失败: {e}")

        return {
            "synced": synced_count,
            "skipped": skipped_count,
            "errors": errors,
            "status": "success" if synced_count > 0 else ("partial" if errors else "no_change"),
        }


class FieldSyncJob:
    """字段同步任务（支持异步调度）"""

    def __init__(self, connection_id: int, tableau_datasource_id: str,
                 asset_id: int, datasource_luid: str,
                 server_url: str, site_content_url: str,
                 token_name: str, token_value: str,
                 api_version: str = "3.21", db_path: str = None):
        self.connection_id = connection_id
        self.tableau_datasource_id = tableau_datasource_id
        self.asset_id = asset_id
        self.datasource_luid = datasource_luid
        self.server_url = server_url
        self.site_content_url = site_content_url
        self.token_name = token_name
        self.token_value = token_value
        self.api_version = api_version
        self.db_path = db_path

    def run(self) -> Dict[str, Any]:
        """同步任务的实际执行逻辑"""
        service = FieldSyncService(
            server_url=self.server_url,
            site_content_url=self.site_content_url,
            token_name=self.token_name,
            token_value=self.token_value,
            api_version=self.api_version,
            db_path=self.db_path,
        )
        try:
            if not service.connect():
                return {"status": "failed", "error": "Tableau REST API 认证失败"}
            result = service.sync_datasource_fields(
                connection_id=self.connection_id,
                tableau_datasource_id=self.tableau_datasource_id,
                asset_id=self.asset_id,
                datasource_luid=self.datasource_luid,
            )
            return result
        finally:
            service.disconnect()
