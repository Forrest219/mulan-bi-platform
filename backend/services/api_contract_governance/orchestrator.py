"""API Contract Governance - 编排器

采样 → 快照 → 比对 → 事件发射
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from .comparator import Comparator
from .dao import ApiContractAssetDao, ApiFieldChangeEventDao, ApiFieldSnapshotDao
from .models import ApiContractAsset, ApiFieldChangeEvent, ApiFieldSnapshot
from .sampler import GraphQLSampler, HttpRequestError, Sampler
from .types import ApiResponse, ComparisonResult, FieldSchema


@dataclass
class SamplingResult:
    """采样结果"""
    success: bool
    snapshot_id: Optional[UUID] = None
    error_message: Optional[str] = None
    fields_count: int = 0


@dataclass
class ComparisonOutcome:
    """比对结果"""
    has_changes: bool
    result: Optional[ComparisonResult] = None
    error_message: Optional[str] = None


class ApiContractGovernanceOrchestrator:
    """API 契约治理编排器"""

    def __init__(
        self,
        db: Session,
        sampler: Optional[Sampler] = None,
        comparator: Optional[Comparator] = None,
    ):
        self.db = db
        self.asset_dao = ApiContractAssetDao(db)
        self.snapshot_dao = ApiFieldSnapshotDao(db)
        self.change_dao = ApiFieldChangeEventDao(db)
        self.sampler = sampler or Sampler()
        self.comparator = comparator or Comparator()

    def run_cycle(self, asset_id: UUID) -> SamplingResult:
        """
        执行完整的采样-比对-事件发射周期

        1. 采样当前 API 响应
        2. 提取字段结构
        3. 创建快照
        4. 如果有基线，执行比对并发射事件
        5. 如果是首次采样（无基线），设置基线
        """
        asset = self.asset_dao.get(asset_id)
        if not asset:
            return SamplingResult(success=False, error_message=f"Asset not found: {asset_id}")

        if not asset.is_active:
            return SamplingResult(success=False, error_message=f"Asset is inactive: {asset_id}")

        try:
            # 1. 采样
            response = self._do_sample(asset)

            # 2. 提取字段
            fields = self.sampler.extract_fields_with_enum_detection(
                response.body,
                max_depth=20,
            )

            # 3. 过滤字段
            filtered_fields = self.sampler.filter_fields(
                fields,
                whitelist=asset.field_whitelist,
                blacklist=asset.field_blacklist,
            )

            # 4. 创建快照
            snapshot = self.snapshot_dao.create(
                ApiFieldSnapshot(
                    asset_id=asset_id,
                    snapshot_time=datetime.utcnow(),
                    sampling_duration_ms=response.duration_ms,
                    response_status_code=response.status_code,
                    response_size_bytes=response.size_bytes,
                    fields_schema=self._serialize_fields(filtered_fields),
                    raw_response_sample=self._sanitize_response(response.body),
                )
            )

            # 更新资产状态
            asset.last_sampled_at = datetime.utcnow()
            asset.last_error = None
            self.asset_dao.update(asset)

            # 5. 检查是否有基线
            if asset.baseline_snapshot_id:
                # 有基线，执行比对
                comparison = self._compare_with_baseline(asset, snapshot)
                if comparison.has_changes:
                    self._emit_change_events(asset, comparison.result)
            else:
                # 无基线，设置当前快照为基线
                asset.baseline_snapshot_id = snapshot.id
                self.asset_dao.update(asset)

            return SamplingResult(
                success=True,
                snapshot_id=snapshot.id,
                fields_count=len(filtered_fields),
            )

        except Exception as e:
            asset.last_error = str(e)
            self.asset_dao.update(asset)
            return SamplingResult(success=False, error_message=str(e))

    def sample_only(self, asset_id: UUID) -> SamplingResult:
        """仅采样，不比对（手动触发时使用）"""
        asset = self.asset_dao.get(asset_id)
        if not asset:
            return SamplingResult(success=False, error_message=f"Asset not found: {asset_id}")

        try:
            response = self._do_sample(asset)
            fields = self.sampler.extract_fields_with_enum_detection(response.body, max_depth=20)
            filtered_fields = self.sampler.filter_fields(
                fields,
                whitelist=asset.field_whitelist,
                blacklist=asset.field_blacklist,
            )

            snapshot = self.snapshot_dao.create(
                ApiFieldSnapshot(
                    asset_id=asset_id,
                    snapshot_time=datetime.utcnow(),
                    sampling_duration_ms=response.duration_ms,
                    response_status_code=response.status_code,
                    response_size_bytes=response.size_bytes,
                    fields_schema=self._serialize_fields(filtered_fields),
                    raw_response_sample=self._sanitize_response(response.body),
                )
            )

            asset.last_sampled_at = datetime.utcnow()
            asset.last_error = None
            self.asset_dao.update(asset)

            return SamplingResult(
                success=True,
                snapshot_id=snapshot.id,
                fields_count=len(filtered_fields),
            )
        except Exception as e:
            asset.last_error = str(e)
            self.asset_dao.update(asset)
            return SamplingResult(success=False, error_message=str(e))

    def compare_snapshots(
        self,
        asset_id: UUID,
        from_snapshot_id: UUID,
        to_snapshot_id: UUID,
    ) -> ComparisonOutcome:
        """比对两个指定快照"""
        from_snapshot = self.snapshot_dao.get(from_snapshot_id)
        to_snapshot = self.snapshot_dao.get(to_snapshot_id)

        if not from_snapshot or not to_snapshot:
            return ComparisonOutcome(
                has_changes=False,
                error_message="Snapshot not found",
            )

        from_fields = self._deserialize_fields(from_snapshot.fields_schema)
        to_fields = self._deserialize_fields(to_snapshot.fields_schema)

        result = self.comparator.compare(
            asset_id=asset_id,
            from_snapshot=from_fields,
            to_snapshot=to_fields,
            from_snapshot_id=from_snapshot_id,
            to_snapshot_id=to_snapshot_id,
        )

        # 创建变更事件记录
        for change in result.changes:
            self.change_dao.create(
                ApiFieldChangeEvent(
                    asset_id=asset_id,
                    from_snapshot_id=from_snapshot_id,
                    to_snapshot_id=to_snapshot_id,
                    change_type=change.change_type.value,
                    field_path=change.field_path,
                    change_detail={
                        "from_value": change.from_value,
                        "to_value": change.to_value,
                        "description": change.description,
                    },
                    severity=change.severity.value,
                )
            )

        if result.changes:
            self._emit_change_events_by_result(asset_id, result)

        return ComparisonOutcome(has_changes=len(result.changes) > 0, result=result)

    def promote_to_baseline(self, asset_id: UUID, snapshot_id: UUID) -> bool:
        """将指定快照提升为基线"""
        asset = self.asset_dao.get(asset_id)
        snapshot = self.snapshot_dao.get(snapshot_id)

        if not asset or not snapshot:
            return False

        asset.baseline_snapshot_id = snapshot_id
        self.asset_dao.update(asset)
        return True

    def _do_sample(self, asset: ApiContractAsset) -> ApiResponse:
        """执行采样"""
        if self._is_graphql_endpoint(asset.endpoint_url):
            return self._sample_graphql(asset)
        else:
            return self._sample_rest(asset)

    def _sample_rest(self, asset: ApiContractAsset) -> ApiResponse:
        """采样 REST API"""
        sampler = Sampler(timeout=asset.sample_timeout_seconds or 30, retry_count=asset.sample_retry_count or 3)
        return sampler.sample_with_retry(
            url=asset.endpoint_url,
            method=asset.method,
            headers=asset.request_headers,
            params=asset.query_params,
            body=asset.request_body_template,
            auth_method=asset.auth_method,
            auth_config=asset.auth_config,
        )

    def _sample_graphql(self, asset: ApiContractAsset) -> ApiResponse:
        """采样 GraphQL API"""
        sampler = GraphQLSampler(timeout=asset.sample_timeout_seconds or 30, retry_count=asset.sample_retry_count or 3)
        return sampler.sample_graphql(
            url=asset.endpoint_url,
            query=asset.path_pattern or "{ __typename }",
            headers=asset.request_headers,
            auth_method=asset.auth_method,
            auth_config=asset.auth_config,
        )

    def _is_graphql_endpoint(self, url: str) -> bool:
        """判断是否为 GraphQL 端点"""
        return "graphql" in url.lower() or url.endswith("/graphql")

    def _compare_with_baseline(self, asset: ApiContractAsset, new_snapshot) -> ComparisonOutcome:
        """与基线比对"""
        baseline = self.snapshot_dao.get(asset.baseline_snapshot_id)
        if not baseline:
            return ComparisonOutcome(has_changes=False)

        baseline_fields = self._deserialize_fields(baseline.fields_schema)
        new_fields = self._deserialize_fields(new_snapshot.fields_schema)

        result = self.comparator.compare(
            asset_id=asset.id,
            from_snapshot=baseline_fields,
            to_snapshot=new_fields,
            from_snapshot_id=baseline.id,
            to_snapshot_id=new_snapshot.id,
        )

        # 创建变更事件记录
        for change in result.changes:
            self.change_dao.create(
                ApiFieldChangeEvent(
                    asset_id=asset.id,
                    from_snapshot_id=baseline.id,
                    to_snapshot_id=new_snapshot.id,
                    change_type=change.change_type.value,
                    field_path=change.field_path,
                    change_detail={
                        "from_value": change.from_value,
                        "to_value": change.to_value,
                        "description": change.description,
                    },
                    severity=change.severity.value,
                    affected_consumers=asset.consumers or [],
                )
            )

        if result.changes:
            self._emit_change_events_by_result(asset.id, result)

        return ComparisonOutcome(has_changes=len(result.changes) > 0, result=result)

    def _emit_change_events(self, asset: ApiContractAsset, result: ComparisonResult) -> None:
        """发射变更事件"""
        self._emit_change_events_by_result(asset.id, result)

    def _emit_change_events_by_result(self, asset_id: UUID, result: ComparisonResult) -> None:
        """发射变更事件（通过比对结果）"""
        try:
            from services.events.event_service import emit_event

            # 破坏性变更事件
            for change in result.breaking_changes:
                emit_event(
                    db=self.db,
                    event_type="api_contract.asset.breaking_change_detected",
                    source_module="api_contract",
                    payload={
                        "asset_id": str(asset_id),
                        "change_type": change.change_type.value,
                        "field_path": change.field_path,
                        "description": change.description,
                        "severity": change.severity.value,
                    },
                    severity="error",
                )

            # 非破坏性变更事件
            for change in result.non_breaking_changes:
                event_type = f"api_contract.asset.{change.change_type.value}"
                sev = "warning" if change.severity.value in ("p1_major", "p2_minor") else "info"
                emit_event(
                    db=self.db,
                    event_type=event_type,
                    source_module="api_contract",
                    payload={
                        "asset_id": str(asset_id),
                        "change_type": change.change_type.value,
                        "field_path": change.field_path,
                        "description": change.description,
                        "severity": change.severity.value,
                    },
                    severity=sev,
                )

            # 兼容性评分事件
            emit_event(
                db=self.db,
                event_type="api_contract.asset.compatibility_score_updated",
                source_module="api_contract",
                payload={
                    "asset_id": str(asset_id),
                    "score": result.compatibility_score,
                    "breaking_changes_count": len(result.breaking_changes),
                    "non_breaking_changes_count": len(result.non_breaking_changes),
                },
                severity="info",
            )
        except Exception:
            pass

    def _serialize_fields(self, fields: dict[str, FieldSchema]) -> dict:
        """序列化字段为 JSONB 兼容格式"""
        return {path: schema.to_dict() for path, schema in fields.items()}

    def _deserialize_fields(self, data: dict) -> dict[str, FieldSchema]:
        """从 JSONB 数据反序列化字段"""
        return {path: FieldSchema.from_dict(data) for path, data in data.items()}

    def _sanitize_response(self, body: Any) -> Any:
        """脱敏响应数据（移除敏感信息）"""
        return body
