"""DQC Port 接口（Hexagonal 架构）

v1 只定义 Protocol，不实现。v2 由 TableauAdapter / PowerBIAdapter 实现。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class TableRef:
    datasource_id: int
    schema: str
    table: str

    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"


@dataclass(frozen=True)
class BIAsset:
    adapter: str
    external_id: str
    name: str
    asset_type: str
    url: Optional[str]
    owner: Optional[str]


@dataclass(frozen=True)
class BIAssetMetadata:
    asset: BIAsset
    last_refresh_at: Optional[datetime]
    viewer_count_30d: Optional[int]
    referenced_fields: List[str]
    certified: Optional[bool]


@runtime_checkable
class BILineagePort(Protocol):
    """BI 血缘查询接口

    每个下游 BI 平台实现一个 adapter：
      - TableauBILineageAdapter
      - PowerBIBILineageAdapter
      - MetabaseBILineageAdapter
    """

    def find_assets_by_table(self, table_ref: TableRef) -> List[BIAsset]:
        ...

    def get_asset_metadata(self, external_id: str) -> Optional[BIAssetMetadata]:
        ...


BI_LINEAGE_ADAPTERS: Dict[str, BILineagePort] = {}


def register_bi_adapter(adapter_name: str, adapter: BILineagePort) -> None:
    BI_LINEAGE_ADAPTERS[adapter_name] = adapter


def get_bi_adapters() -> List[BILineagePort]:
    return list(BI_LINEAGE_ADAPTERS.values())
