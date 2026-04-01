"""Tableau 资产同步服务"""
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

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
            logger.error("Tableau connection failed: %s", e)
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
            logger.error("Workbook sync error: %s", e)
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
                    from src.tableau.models import TableauAsset
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
            logger.error("View sync error: %s", e)
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
            logger.error("Datasource sync error: %s", e)
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
