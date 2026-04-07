"""Tableau 资产同步服务"""
import json
import logging
import time
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional, Iterator

logger = logging.getLogger(__name__)


class TableauSyncService:
    """Tableau 同步服务"""

    def __init__(self, server_url: str, site: str, token_name: str,
                 token_value: str, api_version: str = "3.21"):
        self.server_url = server_url.rstrip("/")
        self.site = site
        self.token_name = token_name
        self.token_value = token_value
        self.api_version = api_version
        self.server = None

    def connect(self) -> bool:
        """使用 PAT 认证连接 Tableau Server"""
        try:
            import tableauserverclient as TSC
            tableau_auth = TSC.PersonalAccessTokenAuth(
                token_name=self.token_name,
                personal_access_token=self.token_value,
                site_id=self.site
            )
            server = TSC.Server(self.server_url, use_server_version=True)
            server.version = self.api_version
            server.sign_in(tableau_auth)
            self.server = server
            return True
        except Exception as e:
            logger.error("Tableau connection failed: %s", e, exc_info=True)
            return False

    def disconnect(self):
        """登出并关闭连接"""
        if self.server:
            try:
                self.server.sign_out()
            except Exception:
                pass

    def test_connection(self) -> Dict[str, Any]:
        """测试连接是否可用"""
        try:
            if self.connect():
                endpoint = self.server.server_info.get()
                version = endpoint.server_info.version
                self.disconnect()
                return {
                    "success": True,
                    "message": f"连接成功，Server Version: {version}"
                }
            else:
                return {"success": False, "message": "连接失败，请检查 URL、Site 和 PAT 凭证"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    def _parse_server_datetime(self, value) -> Optional[datetime]:
        """安全解析 Tableau Server 返回的时间字段"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def sync_all_assets(self, db, connection_id: int,
                        trigger_type: str = "manual") -> Dict[str, Any]:
        """同步所有资产类型到数据库，带日志记录"""
        import tableauserverclient as TSC

        if not self.server:
            raise Exception("未连接，请先调用 connect()")

        # 开始同步：记录日志 + 更新连接状态
        sync_log = db.create_sync_log(connection_id, trigger_type)
        db.set_sync_status(connection_id, "running")
        start_time = time.time()

        synced_ids = {"workbook": [], "dashboard": [], "view": [], "datasource": []}
        errors = []

        # --- Workbooks ---
        try:
            for wb in TSC.Pager(self.server.workbooks):
                content_url = f"/workbooks/{wb.id}"
                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type="workbook",
                    tableau_id=wb.id,
                    name=wb.name,
                    project_name=getattr(wb, 'project_name', None),
                    description=getattr(wb, 'description', None) or None,
                    owner_name=getattr(wb, 'owner_name', None),
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=json.dumps({
                        "created_at": str(wb.created_at) if hasattr(wb, 'created_at') else None,
                        "updated_at": str(wb.updated_at) if hasattr(wb, 'updated_at') else None,
                    }),
                    created_on_server=self._parse_server_datetime(getattr(wb, 'created_at', None)),
                    updated_on_server=self._parse_server_datetime(getattr(wb, 'updated_at', None)),
                    view_count=getattr(wb, 'usage', {}).get('total_views', None) if hasattr(wb, 'usage') else None,
                    tags=json.dumps([t.name for t in wb.tags]) if hasattr(wb, 'tags') and wb.tags else None,
                )
                synced_ids["workbook"].append(wb.id)

                # 同步关联数据源
                try:
                    self.server.workbooks.populate_datasources(wb)
                    for ds in wb.datasources:
                        db.add_asset_datasource(
                            asset_id=asset.id,
                            datasource_name=ds.name,
                            datasource_type=getattr(ds, 'datasource_type', None) or getattr(ds, 'type_', None)
                        )
                except Exception as ds_err:
                    logger.warning("Datasource sync for workbook %s error: %s", wb.id, ds_err)
                    errors.append(f"Workbook {wb.name} datasource: {ds_err}")
        except Exception as e:
            logger.error("Workbook sync error: %s", e, exc_info=True)
            errors.append(f"Workbook sync: {e}")

        # --- Views (including Dashboards) ---
        try:
            for view in TSC.Pager(self.server.views):
                content_url = f"/views/{view.id}"
                sheet_type = getattr(view, 'sheet_type', None) or getattr(view, 'sheetType', None)
                asset_type = "dashboard" if sheet_type == "dashboard" else "view"

                # view → workbook 关联
                workbook_id = getattr(view, 'workbook_id', None)
                workbook_name = None
                if workbook_id:
                    from services.tableau.models import TableauAsset
                    parent = db.session.query(TableauAsset).filter(
                        TableauAsset.connection_id == connection_id,
                        TableauAsset.tableau_id == workbook_id,
                    ).first()
                    if parent:
                        workbook_name = parent.name

                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type=asset_type,
                    tableau_id=view.id,
                    name=view.name,
                    project_name=getattr(view, 'project_name', None),
                    description=None,
                    owner_name=getattr(view, 'owner_name', None),
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=json.dumps({
                        "sheet_type": sheet_type,
                        "workbook_id": workbook_id,
                    }) if sheet_type or workbook_id else None,
                    sheet_type=sheet_type,
                    parent_workbook_id=workbook_id,
                    parent_workbook_name=workbook_name,
                    created_on_server=self._parse_server_datetime(getattr(view, 'created_at', None)),
                    updated_on_server=self._parse_server_datetime(getattr(view, 'updated_at', None)),
                )
                synced_ids[asset_type].append(view.id)
        except Exception as e:
            logger.error("View sync error: %s", e, exc_info=True)
            errors.append(f"View sync: {e}")

        # --- Datasources ---
        try:
            for ds in TSC.Pager(self.server.datasources):
                content_url = f"/datasources/{ds.id}"
                is_certified = getattr(ds, 'certified', None) or getattr(ds, 'is_certified', None)
                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type="datasource",
                    tableau_id=ds.id,
                    name=ds.name,
                    project_name=getattr(ds, 'project_name', None),
                    description=getattr(ds, 'description', None) or None,
                    owner_name=getattr(ds, 'owner_name', None),
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=None,
                    created_on_server=self._parse_server_datetime(getattr(ds, 'created_at', None)),
                    updated_on_server=self._parse_server_datetime(getattr(ds, 'updated_at', None)),
                    is_certified=bool(is_certified) if is_certified is not None else None,
                    tags=json.dumps([t.name for t in ds.tags]) if hasattr(ds, 'tags') and ds.tags else None,
                )
                synced_ids["datasource"].append(ds.id)
        except Exception as e:
            logger.error("Datasource sync error: %s", e, exc_info=True)
            errors.append(f"Datasource sync: {e}")

        # 软删除：标记不再存在的资产
        all_ids = synced_ids["workbook"] + synced_ids["dashboard"] + synced_ids["view"] + synced_ids["datasource"]
        deleted_count = db.mark_assets_deleted(connection_id, all_ids)

        # 计算同步耗时和状态
        duration_sec = int(time.time() - start_time)
        total = len(all_ids)
        status = "success" if not errors else ("partial" if total > 0 else "failed")
        error_msg = "\n".join(errors) if errors else None

        # 更新同步日志
        db.finish_sync_log(
            sync_log.id,
            status=status,
            workbooks_synced=len(synced_ids["workbook"]),
            views_synced=len(synced_ids["view"]),
            dashboards_synced=len(synced_ids["dashboard"]),
            datasources_synced=len(synced_ids["datasource"]),
            assets_deleted=deleted_count,
            error_message=error_msg,
        )

        # 更新连接状态
        db.update_last_sync(connection_id)
        db.set_sync_status(connection_id, "idle" if status != "failed" else "failed", duration_sec)

        return {
            "synced": synced_ids,
            "deleted": deleted_count,
            "total": total,
            "duration_sec": duration_sec,
            "status": status,
            "errors": errors,
            "sync_log_id": sync_log.id,
        }


# --- REST API 同步服务（MCP 模式，不依赖 TSC 库）---

class TableauRestSyncService:
    """通过原生 REST API 同步 Tableau 资产（MCP 模式）"""

    def __init__(self, server_url: str, site: str, token_name: str,
                 token_value: str, api_version: str = "3.21"):
        self.server_url = server_url.rstrip("/")
        self.site = site
        self.token_name = token_name
        self.token_value = token_value
        self.api_version = api_version
        self._auth_token: Optional[str] = None
        self._site_id: Optional[str] = None      # 数字 ID
        self._site_content_url: Optional[str] = None  # URL 中使用的 contentUrl
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        """带认证头的请求 headers"""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._auth_token:
            headers["X-Tableau-Auth"] = self._auth_token
        return headers

    def connect(self) -> bool:
        """通过 REST API 认证"""
        try:
            resp = self._session.post(
                f"{self.server_url}/api/{self.api_version}/auth/signin",
                json={
                    "credentials": {
                        "personalAccessTokenName": self.token_name,
                        "personalAccessTokenSecret": self.token_value,
                        "site": {"contentUrl": self.site}
                    }
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._auth_token = data.get("credentials", {}).get("token", "")
                creds_site = data.get("credentials", {}).get("site", {})
                self._site_id = creds_site.get("id", "")   # 数字 ID（用于日志）
                self._site_content_url = creds_site.get("contentUrl", "")  # URL 中使用的 contentUrl
                logger.info("REST auth success: token=%s, site_id=%s, site_content_url=%s",
                    self._auth_token[:20] + "..." if self._auth_token else "EMPTY",
                    self._site_id, self._site_content_url)
                return True
            return False
        except Exception as e:
            logger.error("REST auth failed: %s", e, exc_info=True)
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
            self._site_content_url = None

    def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        try:
            if not self.connect():
                return {"success": False, "message": "REST API 认证失败，请检查 URL、Site 和 PAT 凭证"}
            self.disconnect()
            return {"success": True, "message": "REST API 连接成功"}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {e}"}

    def _get_all_items(self, endpoint: str, page_size: int = 100) -> Iterator[Dict]:
        """REST 分页拉取，自动翻页"""
        url = f"{self.server_url}/api/{self.api_version}/{endpoint}"
        params = {"pageSize": page_size}
        page = 1
        while True:
            resp = self._session.get(url, headers=self._headers(), params={**params, "pageNumber": page}, timeout=30)
            if resp.status_code != 200:
                logger.warning("REST %s returned %s: %s", endpoint, resp.status_code, resp.text[:300])
                break
            # resp.json() 只能调用一次，避免重复消费响应流
            try:
                data = resp.json()
            except Exception as e:
                logger.error("REST %s JSON 解析失败（响应可能是 XML）: %s", endpoint, e)
                break
            logger.info("REST %s HTTP %s data_keys=%s", endpoint, resp.status_code, list(data.keys()))

            # 尝试提取 items（支持多种返回格式）
            items_extracted = False
            for key in data:
                val = data[key]
                if isinstance(val, dict):
                    # {"workbooks": {"workbook": [...]}} 或 {"views": {"view": [...]}}
                    for item_key in ("workbook", "view", "datasource"):
                        items = val.get(item_key, [])
                        if items:
                            for item in items:
                                yield item
                            items_extracted = True
                            logger.info("REST %s: extracted %d %s(s)", endpoint, len(items), item_key)
                elif isinstance(val, list):
                    # 直接是数组
                    for item in val:
                        yield item
                    items_extracted = True
                    logger.info("REST %s: extracted %d items from list", endpoint, len(val))

            if not items_extracted:
                logger.warning("REST %s: no items found in response keys=%s", endpoint, list(data.keys()))

            # Tableau REST API 分页：pagination.pageNumber / pagination.totalPages
            pagination = data.get("pagination", {})
            if isinstance(pagination, dict):
                current_page = int(pagination.get("pageNumber", 1))
                total_pages = int(pagination.get("totalPages", 1))
                logger.info("REST %s: page %s/%s", endpoint, current_page, total_pages)
                if current_page >= total_pages:
                    break
                page = current_page + 1
            else:
                break

    def _get_workbooks(self) -> List[Dict]:
        # Tableau REST API /sites/{site-id}/workbooks 需要数字 site ID
        return list(self._get_all_items(f"sites/{self._site_id}/workbooks", page_size=100))

    def _get_views(self) -> List[Dict]:
        return list(self._get_all_items(f"sites/{self._site_id}/views", page_size=100))

    def _get_datasources(self) -> List[Dict]:
        return list(self._get_all_items(f"sites/{self._site_id}/datasources", page_size=100))

    def _get_datasource_fields(self, datasource_luid: str) -> List[Dict]:
        """通过 REST API 获取数据源的字段级元数据（Spec 07 §4.1.2 Step 5）"""
        try:
            url = f"{self.server_url}/api/{self.api_version}/sites/{self._site_id}/datasources/{datasource_luid}/fields"
            resp = self._session.get(url, headers=self._headers(), timeout=30)
            if resp.status_code != 200:
                logger.warning("REST _get_datasource_fields %s returned %s", datasource_luid, resp.status_code)
                return []
            data = resp.json()
            # Tableau REST API 返回格式: { "fields": { "field": [...] } } 或直接 { "field": [...] }
            fields_data = data.get("fields", {}) if isinstance(data, dict) else {}
            if isinstance(fields_data, dict):
                return fields_data.get("field", []) or []
            elif isinstance(fields_data, list):
                return fields_data
            return []
        except Exception as e:
            logger.warning("REST _get_datasource_fields %s error: %s", datasource_luid, e)
            return []

    def _parse_field_metadata(self, field: Dict) -> Dict[str, Any]:
        """解析单个字段元数据，返回标准字段字典"""
        return {
            "field_name": field.get("name", "") or field.get("field-name", "") or "",
            "field_caption": field.get("caption") or field.get("alias") or "",
            "data_type": field.get("type") or field.get("dataType") or field.get("data_type") or "",
            "role": field.get("role") or "",  # dimension / measure
            "description": field.get("description") or "",
            "formula": field.get("formula") or field.get("expression") or "",
            "aggregation": field.get("aggregation") or "",
            "is_calculated": bool(field.get("formula") or field.get("expression")),
            "metadata_json": field,
        }

    def _build_url(self, base: str = None) -> str:
        if base:
            return f"{self.server_url}/api/{self.api_version}/{base.replace('{site_id}', self._site_id or '')}"
        return f"{self.server_url}/api/{self.api_version}"

    def _parse_iso_datetime(self, value) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def _extract_id(self, item: Dict, field: str = "id") -> str:
        """安全提取 ID，支持 'id' 是直接字符串或嵌套 dict {'id': '...'} 的情况"""
        val = item.get(field)
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            return val.get("id", "") or ""
        return str(val) if val else ""

    def _get_workbook_datasources(self, workbook_id: str) -> List[Dict]:
        """获取工作簿关联的数据源"""
        try:
            url = f"{self.server_url}/api/{self.api_version}/sites/{self._site_id}/workbooks/{workbook_id}/datasources"
            resp = self._session.get(url, headers=self._headers(), timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            ds_list = data.get("datasources", {}).get("datasource", []) or data.get("datasources", []) or []
            return ds_list
        except Exception:
            return []

    def sync_all_assets(self, db, connection_id: int,
                        trigger_type: str = "manual") -> Dict[str, Any]:
        """同步所有资产类型到数据库（MCP REST 模式）"""
        if not self._auth_token:
            raise Exception("未连接，请先调用 connect()")

        sync_log = db.create_sync_log(connection_id, trigger_type)
        db.set_sync_status(connection_id, "running")
        start_time = time.time()

        synced_ids = {"workbook": [], "dashboard": [], "view": [], "datasource": []}
        errors = []

        # --- Workbooks ---
        try:
            workbooks = self._get_workbooks()
            logger.info("REST MCP sync: fetched %d workbooks (site_id=%s)", len(workbooks), self._site_id)
            workbook_name_map: Dict[str, str] = {}
            for wb in workbooks:
                wb_id = self._extract_id(wb) or wb.get("_id", "") or str(wb.get("id", ""))
                wb_name = wb.get("name", "Unknown")
                workbook_name_map[wb_id] = wb_name

                content_url = f"/workbooks/{wb_id}"
                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type="workbook",
                    tableau_id=wb_id,
                    name=wb_name,
                    project_name=wb.get("project", {}).get("name") if isinstance(wb.get("project"), dict) else wb.get("projectName"),
                    description=wb.get("description"),
                    owner_name=wb.get("owner", {}).get("name") if isinstance(wb.get("owner"), dict) else wb.get("ownerName"),
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=json.dumps({"created_at": wb.get("createdAt"), "updated_at": wb.get("updatedAt")}),
                    created_on_server=self._parse_iso_datetime(wb.get("createdAt")),
                    updated_on_server=self._parse_iso_datetime(wb.get("updatedAt")),
                    tags=json.dumps([t.get("label", t) for t in wb.get("tags", [])]) if wb.get("tags") else None,
                )
                synced_ids["workbook"].append(wb_id)

                # 同步工作簿关联数据源
                for ds in self._get_workbook_datasources(wb_id):
                    ds_name = ds.get("name", "")
                    ds_type = ds.get("datasourceType") or ds.get("type")
                    if ds_name:
                        db.add_asset_datasource(asset_id=asset.id, datasource_name=ds_name, datasource_type=ds_type)
        except Exception as e:
            logger.error("REST workbook sync error: %s", e, exc_info=True)
            errors.append(f"Workbook sync: {e}")

        # --- Views (including Dashboards) ---
        try:
            views = self._get_views()
            logger.info("REST MCP sync: fetched %d views", len(views))
            for view in views:
                view_id = self._extract_id(view) or view.get("_id", "") or str(view.get("id", ""))
                sheet_type = view.get("sheetType") or view.get("sheet_type") or ""
                asset_type = "dashboard" if sheet_type.lower() == "dashboard" else "view"

                workbook_id = view.get("workbook", {}).get("id", "") if isinstance(view.get("workbook"), dict) else (view.get("workbookId", "") or view.get("workbook_id", ""))
                workbook_name = workbook_name_map.get(workbook_id)

                content_url = f"/views/{view_id}"
                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type=asset_type,
                    tableau_id=view_id,
                    name=view.get("name", "Unknown"),
                    project_name=view.get("project", {}).get("name") if isinstance(view.get("project"), dict) else view.get("projectName"),
                    description=None,
                    owner_name=view.get("owner", {}).get("name") if isinstance(view.get("owner"), dict) else view.get("ownerName"),
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=json.dumps({"sheet_type": sheet_type, "workbook_id": workbook_id}),
                    sheet_type=sheet_type or None,
                    parent_workbook_id=workbook_id or None,
                    parent_workbook_name=workbook_name,
                    created_on_server=self._parse_iso_datetime(view.get("createdAt")),
                    updated_on_server=self._parse_iso_datetime(view.get("updatedAt")),
                )
                synced_ids[asset_type].append(view_id)
        except Exception as e:
            logger.error("REST view sync error: %s", e, exc_info=True)
            errors.append(f"View sync: {e}")

        # --- Datasources ---
        try:
            datasources = self._get_datasources()
            for ds in datasources:
                ds_id = self._extract_id(ds) or ds.get("_id", "") or str(ds.get("id", ""))
                content_url = f"/datasources/{ds_id}"
                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type="datasource",
                    tableau_id=ds_id,
                    name=ds.get("name", "Unknown"),
                    project_name=ds.get("project", {}).get("name") if isinstance(ds.get("project"), dict) else ds.get("projectName"),
                    description=ds.get("description"),
                    owner_name=ds.get("owner", {}).get("name") if isinstance(ds.get("owner"), dict) else ds.get("ownerName"),
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=None,
                    created_on_server=self._parse_iso_datetime(ds.get("createdAt")),
                    updated_on_server=self._parse_iso_datetime(ds.get("updatedAt")),
                    is_certified=bool(ds.get("isCertified") or ds.get("certified")) if ds.get("isCertified") is not None or ds.get("certified") is not None else None,
                    tags=json.dumps([t.get("label", t) for t in ds.get("tags", [])]) if ds.get("tags") else None,
                )
                synced_ids["datasource"].append(ds_id)

                # Step 5: 拉取字段级元数据（Spec 07 §4.1.2 P0 修复）
                try:
                    raw_fields = self._get_datasource_fields(ds_id)
                    if raw_fields:
                        parsed_fields = [self._parse_field_metadata(f) for f in raw_fields]
                        if parsed_fields:
                            db.upsert_datasource_fields(asset.id, ds_id, parsed_fields)
                            logger.info("REST sync: upserted %d fields for datasource %s", len(parsed_fields), ds_id)
                except Exception as field_err:
                    logger.warning("REST datasource fields sync error for %s: %s", ds_id, field_err)
                    errors.append(f"Datasource {ds_id} fields: {field_err}")

        except Exception as e:
            logger.error("REST datasource sync error: %s", e, exc_info=True)
            errors.append(f"Datasource sync: {e}")

        # 软删除
        all_ids = synced_ids["workbook"] + synced_ids["dashboard"] + synced_ids["view"] + synced_ids["datasource"]
        deleted_count = db.mark_assets_deleted(connection_id, all_ids)

        duration_sec = int(time.time() - start_time)
        total = len(all_ids)
        status = "success" if not errors else ("partial" if total > 0 else "failed")
        error_msg = "\n".join(errors) if errors else None

        db.finish_sync_log(
            sync_log.id,
            status=status,
            workbooks_synced=len(synced_ids["workbook"]),
            views_synced=len(synced_ids["view"]),
            dashboards_synced=len(synced_ids["dashboard"]),
            datasources_synced=len(synced_ids["datasource"]),
            assets_deleted=deleted_count,
            error_message=error_msg,
        )
        db.update_last_sync(connection_id)
        db.set_sync_status(connection_id, "idle" if status != "failed" else "failed", duration_sec)

        return {
            "synced": synced_ids,
            "deleted": deleted_count,
            "total": total,
            "duration_sec": duration_sec,
            "status": status,
            "errors": errors,
            "sync_log_id": sync_log.id,
        }
