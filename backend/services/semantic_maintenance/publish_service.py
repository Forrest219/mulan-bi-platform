"""
语义维护模块 - 回写发布服务
将已审核通过的语义选择性回写到 Tableau REST API。
职责与 sync_service 完全对称（读取↔回写）。
"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import requests

from .database import SemanticMaintenanceDatabase
from .models import SemanticStatus, PublishStatus, SensitivityLevel

logger = logging.getLogger(__name__)

# 可回写到 Tableau 的字段白名单（文档 §7.2）
WRITABLE_FIELDS = {
    "datasource": ["description", "isCertified"],
    "field": ["caption", "description"],
}

# 禁止回写的高敏感级别
BLOCKED_SENSITIVITY = {SensitivityLevel.HIGH, SensitivityLevel.CONFIDENTIAL}


class PublishService:
    """回写发布服务"""

    def __init__(self, server_url: str, site_content_url: str,
                 token_name: str, token_value: str,
                 api_version: str = "3.21", db_path: str = None):
        self.server_url = server_url.rstrip("/")
        self.site_content_url = site_content_url
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
                logger.info("Publish REST auth success: site_id=%s", self._site_id)
                return True
            return False
        except Exception as e:
            logger.error("Publish REST auth error: %s", e, exc_info=True)
            return False

    def disconnect(self):
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

    def _build_diff(
        self, tableau_current: Dict[str, Any],
        mulan_pending: Dict[str, Any]
    ) -> Dict[str, Any]:
        """计算两个 dict 之间的差异"""
        diff = {}
        for key in set(mulan_pending.keys()):
            t_val = tableau_current.get(key)
            m_val = mulan_pending.get(key)
            if t_val != m_val:
                diff[key] = {"tableau": t_val, "mulan": m_val}
        return diff

    def preview_datasource_diff(
        self, connection_id: int, ds_id: int
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """预览数据源发布差异，返回 (diff_result, error)"""
        ds = self.db.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return {}, "记录不存在"
        if ds.connection_id != connection_id:
            return {}, "连接 ID 不匹配"

        # 权限检查：禁止回写高敏感
        if ds.sensitivity_level in BLOCKED_SENSITIVITY:
            return {}, f"敏感级别为 {ds.sensitivity_level} 的字段禁止自动回写"

        # 从 Tableau 获取当前值
        tableau_current = self._fetch_datasource_from_tableau(ds.tableau_datasource_id)
        mulan_pending = {
            "description": ds.semantic_description,
            "name_zh": ds.semantic_name_zh,
        }

        # 只展示白名单字段差异
        whitelist = WRITABLE_FIELDS["datasource"]
        filtered_pending = {k: v for k, v in mulan_pending.items() if k in whitelist}
        filtered_current = {k: v for k, v in tableau_current.items() if k in whitelist}
        diff = self._build_diff(filtered_current, filtered_pending)

        return {
            "object_type": "datasource",
            "object_id": ds_id,
            "tableau_id": ds.tableau_datasource_id,
            "tableau_current": filtered_current,
            "mulan_pending": filtered_pending,
            "diff": diff,
            "sensitivity_level": ds.sensitivity_level,
            "can_publish": len(diff) > 0 and ds.sensitivity_level not in BLOCKED_SENSITIVITY,
        }, None

    def preview_field_diff(
        self, connection_id: int, field_id: int
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """预览字段发布差异"""
        field = self.db.get_field_semantics_by_id(field_id)
        if not field:
            return {}, "记录不存在"
        if field.connection_id != connection_id:
            return {}, "连接 ID 不匹配"

        if field.sensitivity_level in BLOCKED_SENSITIVITY:
            return {}, f"敏感级别为 {field.sensitivity_level} 的字段禁止自动回写"

        # 从 Tableau 获取字段当前值（需 Metadata API）
        tableau_current = self._fetch_field_from_tableau(
            field.tableau_field_id,
            getattr(field, "datasource_luid", None)
        )
        mulan_pending = {
            "caption": field.semantic_name_zh,
            "description": field.semantic_definition,
        }

        whitelist = WRITABLE_FIELDS["field"]
        filtered_pending = {k: v for k, v in mulan_pending.items() if k in whitelist and v}
        filtered_current = {k: v for k, v in tableau_current.items() if k in whitelist}
        diff = self._build_diff(filtered_current, filtered_pending)

        return {
            "object_type": "field",
            "object_id": field_id,
            "tableau_id": field.tableau_field_id,
            "tableau_current": filtered_current,
            "mulan_pending": filtered_pending,
            "diff": diff,
            "sensitivity_level": field.sensitivity_level,
            "can_publish": len(diff) > 0 and field.sensitivity_level not in BLOCKED_SENSITIVITY,
        }, None

    def _fetch_datasource_from_tableau(self, tableau_datasource_id: str) -> Dict[str, Any]:
        """通过 REST API 获取 Tableau 数据源当前 metadata"""
        if not self._auth_token or not self._site_id:
            return {}
        try:
            url = (
                f"{self.server_url}/api/{self.api_version}"
                f"/sites/{self._site_id}/datasources/{tableau_datasource_id}"
            )
            resp = self._session.get(url, headers=self._headers(), timeout=15)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            # 提取 datasource 顶层字段
            for key in data:
                if isinstance(data[key], dict) and "datasource" in key.lower():
                    ds = data[key]
                    return {
                        "description": ds.get("description"),
                        "isCertified": ds.get("isCertified") or ds.get("certified"),
                    }
            return {}
        except Exception as e:
            logger.warning("Failed to fetch datasource %s from Tableau: %s", tableau_datasource_id, e)
            return {}

    def _fetch_field_from_tableau(self, tableau_field_id: str, datasource_luid: str = None) -> Dict[str, Any]:
        """通过 REST API 获取 Tableau 字段当前 caption/description"""
        if not self._auth_token or not self._site_id:
            return {}
        try:
            if datasource_luid:
                url = (
                    f"{self.server_url}/api/{self.api_version}"
                    f"/sites/{self._site_id}/datasources/{datasource_luid}/fields"
                )
                resp = self._session.get(url, headers=self._headers(), timeout=15)
                if resp.status_code != 200:
                    return {}
                data = resp.json()
                for key, val in data.items():
                    if isinstance(val, list):
                        for field in val:
                            fid = field.get("id", "") or field.get("name", "")
                            if fid == tableau_field_id:
                                return {
                                    "caption": field.get("caption") or field.get("alias"),
                                    "description": field.get("description"),
                                }
            return {}
        except Exception as e:
            logger.warning("Failed to fetch field %s from Tableau: %s", tableau_field_id, e)
            return {}

    def publish_datasource(
        self,
        connection_id: int,
        ds_id: int,
        operator: int = None,
        simulate: bool = False,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        发布数据源语义到 Tableau。

        Args:
            connection_id: Tableau 连接 ID
            ds_id: 数据源语义记录 ID
            operator: 操作人用户 ID
            simulate: True 则只返回 diff 不实际回写

        Returns: (result_dict, error_message)
        """
        if not self._auth_token:
            return {}, "未连接，请先调用 connect()"

        ds = self.db.get_datasource_semantics_by_id(ds_id)
        if not ds:
            return {}, "记录不存在"
        if ds.connection_id != connection_id:
            return {}, "连接 ID 不匹配"

        # 状态检查
        if ds.status != SemanticStatus.APPROVED:
            return {}, f"只有 approved 状态的语义才能发布，当前状态：{ds.status}"

        # 敏感级别检查
        if ds.sensitivity_level in BLOCKED_SENSITIVITY:
            return {}, f"敏感级别为 {ds.sensitivity_level} 的数据源禁止回写"

        # 构建 diff
        diff_result, err = self.preview_datasource_diff(connection_id, ds_id)
        if err:
            return {}, err

        if simulate:
            return {"simulated": True, **diff_result}, None

        # 构建发布 payload
        payload = {
            "datasource": {
                "id": ds.tableau_datasource_id,
                "description": ds.semantic_description or "",
            }
        }

        # 创建发布日志
        log = self.db.create_publish_log(
            connection_id=connection_id,
            object_type="datasource",
            object_id=ds_id,
            operator=operator,
            tableau_object_id=ds.tableau_datasource_id,
            diff_json=json.dumps(diff_result.get("diff", {}), ensure_ascii=False),
            payload_json=json.dumps(payload, ensure_ascii=False),
        )

        # 执行 REST API 回写
        url = (
            f"{self.server_url}/api/{self.api_version}"
            f"/sites/{self._site_id}/datasources/{ds.tableau_datasource_id}"
        )
        update_payload = {
            "datasource": {
                "description": ds.semantic_description or "",
            }
        }

        try:
            resp = self._session.put(
                url, json=update_payload,
                headers=self._headers(), timeout=20
            )
            if resp.status_code in (200, 201):
                self.db.update_publish_log_status(log.id, PublishStatus.SUCCESS, "回写成功")
                self.db.update_datasource_semantics(
                    ds_id, published_to_tableau=True, published_at=datetime.now()
                )
                return {
                    "log_id": log.id,
                    "status": "success",
                    "message": "数据源语义回写成功",
                    "diff": diff_result.get("diff", {}),
                }, None
            else:
                error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                self.db.update_publish_log_status(log.id, PublishStatus.FAILED, error_msg)
                return {}, error_msg
        except Exception as e:
            error_msg = str(e)
            self.db.update_publish_log_status(log.id, PublishStatus.FAILED, error_msg)
            return {}, f"回写异常: {error_msg}"

    def publish_fields(
        self,
        connection_id: int,
        field_ids: List[int],
        operator: int = None,
        simulate: bool = False,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """批量发布字段语义"""
        if not self._auth_token:
            return {}, "未连接"

        results = {"succeeded": [], "failed": [], "skipped": [], "not_supported": []}

        for field_id in field_ids:
            field = self.db.get_field_semantics_by_id(field_id)
            if not field:
                results["failed"].append({"field_id": field_id, "reason": "记录不存在"})
                continue
            if field.connection_id != connection_id:
                results["failed"].append({"field_id": field_id, "reason": "连接 ID 不匹配"})
                continue
            if field.status != SemanticStatus.APPROVED:
                results["skipped"].append({"field_id": field_id, "reason": f"状态为 {field.status}"})
                continue
            if field.sensitivity_level in BLOCKED_SENSITIVITY:
                results["skipped"].append({"field_id": field_id, "reason": f"敏感级别 {field.sensitivity_level} 禁止回写"})
                continue

            if simulate:
                results["succeeded"].append({"field_id": field_id, "simulated": True})
                continue

            # 单个字段回写（REST）
            success, err = self._publish_single_field(field, connection_id, operator)
            if success:
                results["succeeded"].append({"field_id": field_id})
            elif err and "暂不支持" in err:
                results["not_supported"].append({"field_id": field_id, "reason": err})
            else:
                results["failed"].append({"field_id": field_id, "reason": err})

        return results, None

    def _publish_single_field(
        self, field, connection_id: int, operator: int = None
    ) -> Tuple[bool, Optional[str]]:
        """发布单个字段到 Tableau — 当前 REST API 不支持字段级回写"""
        diff_result, err = self.preview_field_diff(connection_id, field.id)
        if err:
            return False, err

        if not diff_result.get("can_publish"):
            return False, "无有效差异或被敏感级别阻止"

        not_supported_message = (
            "Tableau REST API 暂不支持字段级 caption/description 回写，"
            "语义信息已保存在平台内，但未推送至 Tableau Server。"
        )

        # 创建发布日志
        log = self.db.create_publish_log(
            connection_id=connection_id,
            object_type="field",
            object_id=field.id,
            operator=operator,
            tableau_object_id=field.tableau_field_id,
            diff_json=json.dumps(diff_result.get("diff", {}), ensure_ascii=False),
        )

        # 标记为 NOT_SUPPORTED 而非虚假的 SUCCESS
        self.db.update_publish_log_status(
            log.id, PublishStatus.NOT_SUPPORTED, not_supported_message
        )

        # 不设置 published_to_tableau = True
        # 不设置 published_at

        return False, not_supported_message

    def retry_publish(self, log_id: int, operator: int = None) -> Tuple[Dict[str, Any], Optional[str]]:
        """重试失败的发布任务"""
        log = self.db.get_publish_log(log_id)
        if not log:
            return {}, "发布日志不存在"
        if log.status != PublishStatus.FAILED:
            return {}, f"只有 failed 状态的发布任务可以重试，当前状态：{log.status}"

        # 重试间隔：5s / 30s / 60s（最多 3 次）
        self.db.update_publish_log_status(log.id, PublishStatus.PENDING, "重试中...")

        for attempt in range(3):
            if attempt > 0:
                wait = [5, 30, 60][attempt - 1]
                logger.info("Retry attempt %d for log %d after %ds", attempt + 1, log_id, wait)
                time.sleep(wait)

            if log.object_type == "datasource":
                result, err = self.publish_datasource(
                    log.connection_id, log.object_id, operator=operator
                )
            elif log.object_type == "field":
                result, err = self._publish_single_field(
                    self.db.get_field_semantics_by_id(log.object_id),
                    log.connection_id, operator
                )
            else:
                return {}, f"未知对象类型: {log.object_type}"

            if not err and result.get("status") != "failed":
                return result, None

        self.db.update_publish_log_status(log.id, PublishStatus.FAILED, "重试 3 次后仍失败")
        return {}, "重试 3 次后仍失败"

    def rollback_publish(self, log_id: int, operator: int = None) -> Tuple[Dict[str, Any], Optional[str]]:
        """回滚已发布的语义（将 Tableau 字段恢复为发布前的值）"""
        log = self.db.get_publish_log(log_id)
        if not log:
            return {}, "发布日志不存在"
        if log.status != PublishStatus.SUCCESS:
            return {}, f"只能回滚 success 状态的发布，当前状态：{log.status}"

        # 从日志中恢复 diff
        if not log.diff_json:
            return {}, "无差异记录，无法回滚"

        try:
            diff = json.loads(log.diff_json)
        except json.JSONDecodeError:
            return {}, "差异数据损坏"

        # 逆向 diff：mulan → tableau_current（即把 Tableau 恢复为 diff[key]["tableau"]）
        rollback_payload = {}
        for key, vals in diff.items():
            if "tableau" in vals and vals["tableau"]:
                rollback_payload[key] = vals["tableau"]

        if not rollback_payload:
            return {}, "无有效回滚值"

        # 创建回滚发布日志
        rollback_log = self.db.create_publish_log(
            connection_id=log.connection_id,
            object_type=log.object_type,
            object_id=log.object_id,
            operator=operator,
            tableau_object_id=log.tableau_object_id,
            diff_json=json.dumps({"rollback": rollback_payload}, ensure_ascii=False),
            payload_json=json.dumps(rollback_payload, ensure_ascii=False),
        )

        # 实际回写（逆向操作）
        if log.object_type == "datasource":
            url = (
                f"{self.server_url}/api/{self.api_version}"
                f"/sites/{self._site_id}/datasources/{log.tableau_object_id}"
            )
            payload = {"datasource": rollback_payload}
        else:
            self.db.update_publish_log_status(rollback_log.id, PublishStatus.SUCCESS, "字段回滚已记录（REST 暂不支持）")
            return {"log_id": rollback_log.id, "status": "success", "message": "回滚已记录"}, None

        try:
            resp = self._session.put(url, json=payload, headers=self._headers(), timeout=20)
            if resp.status_code in (200, 201):
                self.db.update_publish_log_status(rollback_log.id, PublishStatus.SUCCESS, "回滚成功")
                self.db.update_publish_log_status(log.id, PublishStatus.ROLLED_BACK, f"已被 log_id={rollback_log.id} 回滚")
                return {"log_id": rollback_log.id, "status": "success", "message": "回滚成功"}, None
            else:
                self.db.update_publish_log_status(rollback_log.id, PublishStatus.FAILED, f"HTTP {resp.status_code}")
                return {}, f"回滚失败 HTTP {resp.status_code}"
        except Exception as e:
            self.db.update_publish_log_status(rollback_log.id, PublishStatus.FAILED, str(e))
            return {}, f"回滚异常: {e}"
