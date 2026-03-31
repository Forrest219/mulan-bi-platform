"""Tableau 资产同步服务"""
import json
import logging
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

    def sync_all_assets(self, db, connection_id: int) -> Dict[str, Any]:
        """同步所有资产类型到数据库"""
        import tableauserverclient as TSC

        if not self.server:
            raise Exception("未连接，请先调用 connect()")

        synced_ids = {"workbook": [], "dashboard": [], "view": [], "datasource": []}

        # Workbooks
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
                        "created_at": str(wb.created_at),
                        "updated_at": str(wb.updated_at)
                    }) if hasattr(wb, 'created_at') else None
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
        except Exception as e:
            logger.error("Workbook sync error: %s", e)

        # Views (including Dashboards)
        try:
            for view in TSC.Pager(self.server.views):
                content_url = f"/views/{view.id}"
                # Tableau views with sheetType='dashboard' are dashboards
                sheet_type = getattr(view, 'sheet_type', None) or getattr(view, 'sheetType', None)
                asset_type = "dashboard" if sheet_type == "dashboard" else "view"
                asset = db.upsert_asset(
                    connection_id=connection_id,
                    asset_type=asset_type,
                    tableau_id=view.id,
                    name=view.name,
                    project_name=getattr(view, 'project_name', None),
                    description=None,
                    owner_name=None,
                    thumbnail_url=None,
                    content_url=content_url,
                    raw_metadata=json.dumps({
                        "sheet_type": sheet_type
                    }) if sheet_type else None
                )
                synced_ids[asset_type].append(view.id)
        except Exception as e:
            logger.error("View sync error: %s", e)

        # Datasources
        try:
            for ds in TSC.Pager(self.server.datasources):
                content_url = f"/datasources/{ds.id}"
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
                    raw_metadata=None
                )
                synced_ids["datasource"].append(ds.id)
        except Exception as e:
            logger.error("Datasource sync error: %s", e)

        # 软删除：标记不再存在的资产
        all_ids = synced_ids["workbook"] + synced_ids["dashboard"] + synced_ids["view"] + synced_ids["datasource"]
        deleted_count = db.mark_assets_deleted(connection_id, all_ids)

        # 更新同步时间
        db.update_last_sync(connection_id)

        return {
            "synced": synced_ids,
            "deleted": deleted_count,
            "total": len(all_ids)
        }
