"""数仓资产管理 API

路由前缀: /api/assets/dw
"""
import logging
import math
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, and_, distinct, text
from sqlalchemy.orm import Session

from app.core.crypto import get_datasource_crypto
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_roles
from services.audit.audit_service import log_action
from services.datasources.models import DataSource
from services.dw_assets.models import (
    DwAssetTable,
    DwAssetColumn,
    DwAssetPartition,
    DwAssetLineageEdge,
    DwAssetSyncRun,
    DwDomainTaxonomy,
    DwDomainTaxonomyDatabase,
)
from services.dw_assets.sync_service import MetadataSyncService, _SYSTEM_DATABASES
from services.dw_assets.preview_service import PreviewService
from services.dw_assets.lineage_service import LineageService

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# 角色常量
# ---------------------------------------------------------------------------
_ANALYST_PLUS = ["admin", "data_admin", "analyst"]
_DATA_ADMIN_PLUS = ["admin", "data_admin"]


# ---------------------------------------------------------------------------
# Pydantic 请求/响应模型
# ---------------------------------------------------------------------------

class UpdateTableRequest(BaseModel):
    """更新表治理字段"""
    business_name: Optional[str] = None
    description: Optional[str] = None
    domain: Optional[str] = None
    layer: Optional[str] = None
    tags: Optional[List[str]] = None


class UpdateColumnRequest(BaseModel):
    """更新单字段治理信息"""
    business_name: Optional[str] = None
    description: Optional[str] = None
    sensitivity_level: Optional[str] = None
    is_business_key: Optional[bool] = None


class BatchColumnItem(BaseModel):
    """批量更新字段条目"""
    column_id: int
    business_name: Optional[str] = None
    description: Optional[str] = None
    sensitivity_level: Optional[str] = None


class BatchUpdateColumnsRequest(BaseModel):
    """批量更新字段"""
    items: List[BatchColumnItem] = Field(..., max_length=50)


class CreateLineageRequest(BaseModel):
    """新增手工血缘"""
    lineage_type: str = "table"
    source_table_id: int
    target_table_id: Optional[int] = None
    source_column_id: Optional[int] = None
    target_column_id: Optional[int] = None
    relation_type: str = "manual"
    transformation_logic: Optional[str] = None


class TriggerSyncRequest(BaseModel):
    """触发同步"""
    mode: str = "incremental"
    include_partitions: bool = True


class AgentContextRequest(BaseModel):
    """生成 Agent 上下文"""
    intent: str = "ask_about_table"
    selected_columns: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# 权限辅助函数
# ---------------------------------------------------------------------------

def _get_authorized_table(db: Session, table_id: int, user: dict) -> DwAssetTable:
    """
    获取已授权的表对象。

    - admin: 可访问任何表
    - data_admin/analyst: 只能访问 bi_data_sources.owner_id == user.id 的表

    返回表对象或抛出 403/404。
    """
    if user["role"] == "admin":
        table = db.query(DwAssetTable).filter(
            DwAssetTable.id == table_id,
            DwAssetTable.is_deleted == False,
        ).first()
    else:
        table = (
            db.query(DwAssetTable)
            .join(DataSource, DwAssetTable.datasource_id == DataSource.id)
            .filter(
                DwAssetTable.id == table_id,
                DwAssetTable.is_deleted == False,
                DataSource.owner_id == user["id"],
            )
            .first()
        )

    if not table:
        # 区分不存在 vs 无权限
        exists = db.query(DwAssetTable.id).filter(
            DwAssetTable.id == table_id,
            DwAssetTable.is_deleted == False,
        ).first()
        if exists:
            raise HTTPException(status_code=403, detail={
                "error_code": "DWASSET_002",
                "message": "无权访问该数据源资产",
            })
        raise HTTPException(status_code=404, detail={
            "error_code": "DWASSET_001",
            "message": "数仓资产不存在",
        })

    return table


def _authorized_datasource_filter(query, user: dict):
    """为查询添加数据源权限过滤（非 admin 只看自有数据源）"""
    if user["role"] != "admin":
        query = query.join(DataSource, DwAssetTable.datasource_id == DataSource.id).filter(
            DataSource.owner_id == user["id"],
        )
    return query


# ---------------------------------------------------------------------------
# 1. GET /databases
# ---------------------------------------------------------------------------

@router.get("/databases")
async def list_databases(
    request: Request,
    db_type: Optional[str] = None,
    q: Optional[str] = None,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """获取可浏览的数据源/库列表（按数据源聚合，含表计数、存储和同步状态）"""
    # 聚合查询：按 datasource_id 分组统计（LEFT JOIN 保留未同步的数据源）
    table_filter = and_(
        DwAssetTable.datasource_id == DataSource.id,
        DwAssetTable.is_deleted == False,
        DwAssetTable.database_name.notin_(_SYSTEM_DATABASES),
    )
    agg_query = (
        db.query(
            DataSource.id.label("datasource_id"),
            DataSource.name,
            DataSource.db_type,
            DataSource.host,
            func.count(DwAssetTable.id).label("table_count"),
            func.coalesce(func.sum(DwAssetTable.storage_bytes), 0).label("total_storage_bytes"),
            func.count(distinct(DwAssetTable.database_name)).label("database_count"),
            func.array_agg(distinct(DwAssetTable.database_name)).label("databases"),
        )
        .outerjoin(DwAssetTable, table_filter)
        .filter(
            DataSource.is_active == True,
            DataSource.db_type.in_(["starrocks", "mysql"]),
        )
        .group_by(DataSource.id)
    )

    # 权限过滤
    if current_user["role"] != "admin":
        agg_query = agg_query.filter(DataSource.owner_id == current_user["id"])

    # db_type 过滤
    if db_type:
        agg_query = agg_query.filter(DataSource.db_type == db_type)

    # 搜索（按数据源名称或库名模糊匹配）
    if q:
        search_pattern = f"%{q}%"
        agg_query = agg_query.filter(
            or_(
                DataSource.name.ilike(search_pattern),
                DataSource.host.ilike(search_pattern),
            )
        )

    agg_rows = agg_query.all()

    # 收集所有命中的 datasource_id，批量查最新同步状态
    ds_ids = [row.datasource_id for row in agg_rows]

    sync_map: dict = {}
    if ds_ids:
        # 子查询：每个 datasource_id 最新的 started_at
        latest_subq = (
            db.query(
                DwAssetSyncRun.datasource_id,
                func.max(DwAssetSyncRun.started_at).label("max_started"),
            )
            .filter(DwAssetSyncRun.datasource_id.in_(ds_ids))
            .group_by(DwAssetSyncRun.datasource_id)
            .subquery()
        )
        sync_rows = (
            db.query(DwAssetSyncRun)
            .join(
                latest_subq,
                and_(
                    DwAssetSyncRun.datasource_id == latest_subq.c.datasource_id,
                    DwAssetSyncRun.started_at == latest_subq.c.max_started,
                ),
            )
            .all()
        )
        sync_map = {sr.datasource_id: sr for sr in sync_rows}

    items = []
    for row in agg_rows:
        latest_sync = sync_map.get(row.datasource_id)
        databases_list = sorted(d for d in (row.databases or []) if d is not None)
        items.append({
            "datasource_id": row.datasource_id,
            "name": row.name,
            "db_type": row.db_type,
            "host": row.host,
            "table_count": row.table_count,
            "total_storage_bytes": row.total_storage_bytes,
            "database_count": row.database_count,
            "databases": databases_list,
            "last_synced_at": (
                latest_sync.started_at.strftime("%Y-%m-%d %H:%M:%S")
                if latest_sync and latest_sync.started_at
                else None
            ),
            "sync_status": latest_sync.status if latest_sync else None,
        })

    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# 1b. GET /domain-values
# ---------------------------------------------------------------------------

@router.get("/domain-values")
async def list_domain_values(
    datasource_id: Optional[int] = None,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """返回当前库中所有已使用的 domain 值，并解析为 L1/L2 树结构，供前端级联选择器使用。"""
    query = db.query(DwAssetTable.domain).filter(
        DwAssetTable.is_deleted == False,
        DwAssetTable.domain.isnot(None),
    )
    if current_user["role"] != "admin":
        query = query.join(
            DataSource, DwAssetTable.datasource_id == DataSource.id
        ).filter(DataSource.owner_id == current_user["id"])
    if datasource_id:
        query = query.filter(DwAssetTable.datasource_id == datasource_id)

    raw_values = [row[0] for row in query.distinct().all() if row[0]]

    # 优先读 taxonomy 配置
    taxonomy_db = DwDomainTaxonomyDatabase()
    taxonomy_items = taxonomy_db.get_l1_l2_tree()
    if taxonomy_items:
        return {"items": taxonomy_items, "values": sorted(raw_values), "source": "taxonomy"}

    # Fallback：从已有数据派生
    tree: dict = {}
    for val in sorted(raw_values):
        parts = val.split("/", 1)
        l1 = parts[0].strip()
        l2 = parts[1].strip() if len(parts) == 2 else None
        if l1 not in tree:
            tree[l1] = []
        if l2 and l2 not in tree[l1]:
            tree[l1].append(l2)

    items = [
        {"l1": l1, "l2_list": sorted(l2s)}
        for l1, l2s in sorted(tree.items())
    ]
    return {"items": items, "values": sorted(raw_values), "source": "derived"}


# ---------------------------------------------------------------------------
# 1c. 主题域层级架构 CRUD（仅 admin / data_admin）
# ---------------------------------------------------------------------------

_ADMIN_ONLY = ["admin", "data_admin"]


class DomainTaxonomyCreate(BaseModel):
    l1: str = Field(..., min_length=1, max_length=64)
    l2: str | None = Field(None, max_length=64)  # None = 仅 L1


class DomainTaxonomyUpdate(BaseModel):
    display_order: int = 0


@router.get("/domain-taxonomy")
async def list_domain_taxonomy(
    current_user: dict = Depends(require_roles(_ADMIN_ONLY)),
):
    """列出所有主题域层级配置（仅 admin/data_admin）"""
    db = DwDomainTaxonomyDatabase()
    return {"items": [r.to_dict() for r in db.list_all()]}


@router.post("/domain-taxonomy")
async def create_domain_taxonomy(
    body: DomainTaxonomyCreate,
    current_user: dict = Depends(require_roles(_ADMIN_ONLY)),
):
    """新增一条主题域配置（l1 必填，l2 选填）"""
    db = DwDomainTaxonomyDatabase()
    row = db.upsert(body.l1, body.l2)
    log_action(
        current_user.get("id"),
        current_user.get("username", ""),
        "create",
        "domain_taxonomy",
        str(row.id),
        after_state=row.to_dict(),
    )
    return row.to_dict()


@router.patch("/domain-taxonomy/{taxonomy_id}")
async def update_domain_taxonomy(
    taxonomy_id: int,
    body: DomainTaxonomyUpdate,
    current_user: dict = Depends(require_roles(_ADMIN_ONLY)),
    db: Session = Depends(get_db),
):
    """更新排序"""
    row = db.query(DwDomainTaxonomy).filter(DwDomainTaxonomy.id == taxonomy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="不存在")
    row.display_order = body.display_order
    db.commit()
    return row.to_dict()


@router.delete("/domain-taxonomy/{taxonomy_id}")
async def delete_domain_taxonomy(
    taxonomy_id: int,
    current_user: dict = Depends(require_roles(_ADMIN_ONLY)),
):
    """删除一条主题域配置"""
    db = DwDomainTaxonomyDatabase()
    deleted = db.delete(taxonomy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="不存在")
    log_action(
        current_user.get("id"),
        current_user.get("username", ""),
        "delete",
        "domain_taxonomy",
        str(taxonomy_id),
    )
    return {"message": "已删除"}


# ---------------------------------------------------------------------------
# 2. GET /search
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_assets(
    request: Request,
    q: str,
    scope: str = "table",
    datasource_id: Optional[int] = None,
    limit: int = 10,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """跨表/字段搜索"""
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail="搜索词至少 2 个字符")

    if limit > 50:
        limit = 50

    items = []
    search_pattern = f"%{q}%"

    if scope in ("table", "all"):
        table_query = db.query(DwAssetTable).filter(
            DwAssetTable.is_deleted == False,
            or_(
                DwAssetTable.table_name.ilike(search_pattern),
                DwAssetTable.business_name.ilike(search_pattern),
                DwAssetTable.description.ilike(search_pattern),
            ),
        )
        # 权限过滤
        if current_user["role"] != "admin":
            table_query = table_query.join(
                DataSource, DwAssetTable.datasource_id == DataSource.id
            ).filter(DataSource.owner_id == current_user["id"])

        if datasource_id:
            table_query = table_query.filter(DwAssetTable.datasource_id == datasource_id)

        tables = table_query.limit(limit).all()
        for t in tables:
            items.append({
                "type": "table",
                "table_id": t.id,
                "column_id": None,
                "label": t.business_name or t.table_name,
                "matched_text": t.table_name,
                "datasource_id": t.datasource_id,
                "database_name": t.database_name,
                "table_name": t.table_name,
                "column_name": None,
                "score": 0.9,
            })

    if scope in ("column", "all"):
        remaining = limit - len(items)
        if remaining > 0:
            col_query = (
                db.query(DwAssetColumn, DwAssetTable)
                .join(DwAssetTable, DwAssetColumn.table_id == DwAssetTable.id)
                .filter(
                    DwAssetTable.is_deleted == False,
                    DwAssetColumn.sensitivity_level.notin_(["restricted"]),
                    or_(
                        DwAssetColumn.column_name.ilike(search_pattern),
                        DwAssetColumn.business_name.ilike(search_pattern),
                        DwAssetColumn.column_comment.ilike(search_pattern),
                    ),
                )
            )
            # 权限过滤
            if current_user["role"] != "admin":
                col_query = col_query.join(
                    DataSource, DwAssetTable.datasource_id == DataSource.id
                ).filter(DataSource.owner_id == current_user["id"])

            if datasource_id:
                col_query = col_query.filter(DwAssetTable.datasource_id == datasource_id)

            columns = col_query.limit(remaining).all()
            for col, tbl in columns:
                items.append({
                    "type": "column",
                    "table_id": tbl.id,
                    "column_id": col.id,
                    "label": col.business_name or col.column_name,
                    "matched_text": col.column_name,
                    "datasource_id": tbl.datasource_id,
                    "database_name": tbl.database_name,
                    "table_name": tbl.table_name,
                    "column_name": col.column_name,
                    "score": 0.8,
                })

    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# 3. GET /tables
# ---------------------------------------------------------------------------

@router.get("/tables")
async def list_tables(
    request: Request,
    datasource_id: Optional[int] = None,
    database_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    q: Optional[str] = None,
    domain: Optional[List[str]] = Query(None),
    layer: Optional[str] = None,
    table_type: Optional[str] = None,
    has_partition: Optional[bool] = None,
    sort: str = "heat_score",
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """获取表清单，分页过滤"""
    if page_size > 100:
        page_size = 100

    query = db.query(DwAssetTable).filter(DwAssetTable.is_deleted == False)

    # 权限过滤
    if current_user["role"] != "admin":
        query = query.join(
            DataSource, DwAssetTable.datasource_id == DataSource.id
        ).filter(DataSource.owner_id == current_user["id"])

    # 条件过滤
    if datasource_id:
        query = query.filter(DwAssetTable.datasource_id == datasource_id)
    if database_name:
        query = query.filter(DwAssetTable.database_name == database_name)
    if schema_name:
        query = query.filter(DwAssetTable.schema_name == schema_name)
    if q:
        search_pattern = f"%{q}%"
        query = query.filter(
            or_(
                DwAssetTable.table_name.ilike(search_pattern),
                DwAssetTable.business_name.ilike(search_pattern),
                DwAssetTable.description.ilike(search_pattern),
            )
        )
    if domain:
        conditions = []
        for d in domain:
            conditions.append(DwAssetTable.domain == d)
            conditions.append(DwAssetTable.domain.like(f"{d}/%"))
        query = query.filter(or_(*conditions))
    if layer:
        query = query.filter(DwAssetTable.layer == layer)
    if table_type:
        query = query.filter(DwAssetTable.table_type == table_type)
    if has_partition is not None:
        if has_partition:
            query = query.filter(DwAssetTable.partition_key.isnot(None))
        else:
            query = query.filter(DwAssetTable.partition_key.is_(None))

    # 排序
    sort_map = {
        "heat_score": DwAssetTable.heat_score.desc(),
        "updated_at": DwAssetTable.updated_at.desc(),
        "table_name": DwAssetTable.table_name.asc(),
    }
    order_clause = sort_map.get(sort, DwAssetTable.heat_score.desc())
    query = query.order_by(order_clause)

    # 总数
    total = query.count()
    pages = math.ceil(total / page_size) if total > 0 else 0

    # 分页
    offset = (page - 1) * page_size
    tables = query.offset(offset).limit(page_size).all()

    # 补充 field_count
    table_ids = [t.id for t in tables]
    field_counts = {}
    if table_ids:
        counts = (
            db.query(DwAssetColumn.table_id, func.count(DwAssetColumn.id))
            .filter(DwAssetColumn.table_id.in_(table_ids))
            .group_by(DwAssetColumn.table_id)
            .all()
        )
        field_counts = {tid: cnt for tid, cnt in counts}

    items = []
    for t in tables:
        item = t.to_list_dict()
        item["field_count"] = field_counts.get(t.id, 0)
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# 4. GET /tables/{table_id}
# ---------------------------------------------------------------------------

@router.get("/tables/{table_id}")
async def get_table_detail(
    table_id: int,
    request: Request,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """获取表详情"""
    table = _get_authorized_table(db, table_id, current_user)

    # 获取数据源信息
    ds = db.query(DataSource).filter(DataSource.id == table.datasource_id).first()

    # 血缘摘要
    upstream_count = db.query(func.count(DwAssetLineageEdge.id)).filter(
        DwAssetLineageEdge.target_table_id == table_id
    ).scalar() or 0
    downstream_count = db.query(func.count(DwAssetLineageEdge.id)).filter(
        DwAssetLineageEdge.source_table_id == table_id
    ).scalar() or 0

    result = table.to_dict()
    result["datasource"] = {
        "id": ds.id,
        "name": ds.name,
        "db_type": ds.db_type,
    } if ds else None
    result["lineage_summary"] = {
        "upstream_count": upstream_count,
        "downstream_count": downstream_count,
    }

    return result


# ---------------------------------------------------------------------------
# 5a. GET /tables/{table_id}/suggestions  (LLM 治理建议)
# ---------------------------------------------------------------------------

@router.get("/tables/{table_id}/suggestions")
async def get_table_suggestions(
    table_id: int,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """用 LLM 根据物理元数据生成 business_name / description 建议"""
    from services.llm.service import llm_service
    import json as _json

    table = _get_authorized_table(db, table_id, current_user)
    columns = (
        db.query(DwAssetColumn)
        .filter(DwAssetColumn.table_id == table_id)
        .order_by(DwAssetColumn.ordinal_position)
        .limit(20)
        .all()
    )
    col_lines = "\n".join(
        f"  - {c.column_name} ({c.data_type})" + (f"  # {c.column_comment}" if c.column_comment else "")
        for c in columns
    )

    prompt = (
        f"你是数仓治理专家。根据以下物理元数据，用中文输出该表的业务名称和业务描述。\n\n"
        f"表名: {table.table_name}\n"
        f"库名: {table.database_name}\n"
        f"现有注释: {table.table_comment or '（无）'}\n"
        f"字段列表（前20个）:\n{col_lines}\n\n"
        f"严格返回 JSON（不要 markdown 代码块，不要其他文字）:\n"
        f'{{"business_name": "中文业务名称（10字以内）", "description": "中文业务描述（50字以内）"}}'
    )

    result = await llm_service.complete(prompt, timeout=20, purpose="default")
    if "error" in result:
        raise HTTPException(status_code=503, detail={"error_code": "DWASSET_010", "message": "LLM 服务暂不可用"})

    content = result["content"].strip()
    # 去除可能的 markdown 代码块包裹
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        data = _json.loads(content)
        return {
            "business_name": data.get("business_name") or None,
            "description": data.get("description") or None,
        }
    except Exception:
        return {"business_name": None, "description": None, "raw": content}


# ---------------------------------------------------------------------------
# 5. PUT /tables/{table_id}
# ---------------------------------------------------------------------------

@router.put("/tables/{table_id}")
async def update_table(
    table_id: int,
    body: UpdateTableRequest,
    request: Request,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """更新治理字段（仅 business_name, description, domain, layer, tags）"""
    table = _get_authorized_table(db, table_id, current_user)

    before_state = table.to_dict()
    update_data = body.model_dump(exclude_unset=True)

    if "business_name" in update_data:
        table.business_name = update_data["business_name"]
    if "description" in update_data:
        table.description = update_data["description"]
    if "domain" in update_data:
        domain_val = update_data["domain"]
        if domain_val is not None:
            parts = domain_val.split("/")
            if len(parts) > 2 or any(not p.strip() for p in parts):
                raise HTTPException(
                    status_code=400,
                    detail={"error_code": "DWASSET_009", "message": "domain 格式错误，仅支持 'L1' 或 'L1/L2'"},
                )
        table.domain = domain_val
    if "layer" in update_data:
        table.layer = update_data["layer"]
    if "tags" in update_data:
        table.tags_json = update_data["tags"]

    table.updated_by = current_user["id"]
    db.commit()
    db.refresh(table)

    # 获取数据源信息（与 GET /tables/{table_id} 保持一致）
    ds = db.query(DataSource).filter(DataSource.id == table.datasource_id).first()
    upstream_count = db.query(func.count(DwAssetLineageEdge.id)).filter(
        DwAssetLineageEdge.target_table_id == table_id
    ).scalar() or 0
    downstream_count = db.query(func.count(DwAssetLineageEdge.id)).filter(
        DwAssetLineageEdge.source_table_id == table_id
    ).scalar() or 0

    result = table.to_dict()
    result["datasource"] = {
        "id": ds.id,
        "name": ds.name,
        "db_type": ds.db_type,
    } if ds else None
    result["lineage_summary"] = {
        "upstream_count": upstream_count,
        "downstream_count": downstream_count,
    }

    log_action(
        current_user["id"], current_user.get("username", ""),
        "update", "dw_asset_table", table_id,
        before_state=before_state, after_state=table.to_dict(),
    )

    return {"message": "数仓资产已更新", "table": result}


# ---------------------------------------------------------------------------
# 6. GET /tables/{table_id}/columns
# ---------------------------------------------------------------------------

@router.get("/tables/{table_id}/columns")
async def list_columns(
    table_id: int,
    request: Request,
    q: Optional[str] = None,
    sensitivity_level: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """获取字段元数据，分页"""
    if page_size > 200:
        page_size = 200

    # 权限校验
    _get_authorized_table(db, table_id, current_user)

    query = db.query(DwAssetColumn).filter(DwAssetColumn.table_id == table_id)

    if q:
        search_pattern = f"%{q}%"
        query = query.filter(
            or_(
                DwAssetColumn.column_name.ilike(search_pattern),
                DwAssetColumn.business_name.ilike(search_pattern),
                DwAssetColumn.column_comment.ilike(search_pattern),
            )
        )
    if sensitivity_level:
        query = query.filter(DwAssetColumn.sensitivity_level == sensitivity_level)

    query = query.order_by(DwAssetColumn.ordinal_position.asc())

    total = query.count()
    pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size
    columns = query.offset(offset).limit(page_size).all()

    return {
        "items": [c.to_dict() for c in columns],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# 7. PUT /tables/{table_id}/columns/{column_id}
# ---------------------------------------------------------------------------

@router.put("/tables/{table_id}/columns/{column_id}")
async def update_column(
    table_id: int,
    column_id: int,
    body: UpdateColumnRequest,
    request: Request,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """更新单字段治理信息"""
    _get_authorized_table(db, table_id, current_user)

    column = db.query(DwAssetColumn).filter(
        DwAssetColumn.id == column_id,
        DwAssetColumn.table_id == table_id,
    ).first()
    if not column:
        raise HTTPException(status_code=404, detail={
            "error_code": "DWASSET_001",
            "message": "字段不存在",
        })

    before_state = column.to_dict()
    update_data = body.model_dump(exclude_unset=True)

    if "business_name" in update_data:
        column.business_name = update_data["business_name"]
    if "description" in update_data:
        column.description = update_data["description"]
    if "sensitivity_level" in update_data:
        column.sensitivity_level = update_data["sensitivity_level"]
    if "is_business_key" in update_data:
        column.is_business_key = update_data["is_business_key"]

    db.commit()
    db.refresh(column)

    log_action(
        current_user["id"], current_user.get("username", ""),
        "update", "dw_asset_column", column_id,
        before_state=before_state, after_state=column.to_dict(),
    )

    return {"message": "字段元数据已更新", "column": column.to_dict()}


# ---------------------------------------------------------------------------
# 8. PATCH /tables/{table_id}/columns (batch update)
# ---------------------------------------------------------------------------

@router.patch("/tables/{table_id}/columns")
async def batch_update_columns(
    table_id: int,
    body: BatchUpdateColumnsRequest,
    request: Request,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """批量更新字段治理信息（最多 50 个）"""
    if len(body.items) > 50:
        raise HTTPException(status_code=400, detail="单次最多更新 50 个字段")

    _get_authorized_table(db, table_id, current_user)

    # 验证所有 column_id 属于该表
    column_ids = [item.column_id for item in body.items]
    existing_columns = (
        db.query(DwAssetColumn)
        .filter(
            DwAssetColumn.id.in_(column_ids),
            DwAssetColumn.table_id == table_id,
        )
        .all()
    )
    existing_map = {c.id: c for c in existing_columns}

    missing_ids = set(column_ids) - set(existing_map.keys())
    if missing_ids:
        raise HTTPException(status_code=400, detail={
            "error_code": "DWASSET_001",
            "message": f"以下字段 ID 不属于当前表: {list(missing_ids)}",
        })

    updated_columns = []
    for item in body.items:
        col = existing_map[item.column_id]
        if item.business_name is not None:
            col.business_name = item.business_name
        if item.description is not None:
            col.description = item.description
        if item.sensitivity_level is not None:
            col.sensitivity_level = item.sensitivity_level
        updated_columns.append(col)

    db.commit()

    log_action(
        current_user["id"], current_user.get("username", ""),
        "update", "dw_asset_columns_batch", table_id,
        after_state={"updated_count": len(updated_columns), "column_ids": column_ids},
    )

    return {
        "message": f"已更新 {len(updated_columns)} 个字段",
        "updated_count": len(updated_columns),
    }


# ---------------------------------------------------------------------------
# 9. GET /tables/{table_id}/partitions
# ---------------------------------------------------------------------------

@router.get("/tables/{table_id}/partitions")
async def list_partitions(
    table_id: int,
    request: Request,
    page: int = 1,
    page_size: int = 50,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """获取分区信息"""
    if page_size > 200:
        page_size = 200

    _get_authorized_table(db, table_id, current_user)

    query = db.query(DwAssetPartition).filter(
        DwAssetPartition.table_id == table_id
    ).order_by(DwAssetPartition.partition_name.desc())

    total = query.count()
    pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size
    partitions = query.offset(offset).limit(page_size).all()

    return {
        "items": [p.to_dict() for p in partitions],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# 10. GET /tables/{table_id}/lineage
# ---------------------------------------------------------------------------

@router.get("/tables/{table_id}/lineage")
async def get_lineage(
    table_id: int,
    request: Request,
    depth: int = 1,
    direction: str = "both",
    level: str = "table",
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """获取血缘拓扑"""
    if depth > 3:
        depth = 3

    table = _get_authorized_table(db, table_id, current_user)

    lineage_service = LineageService()
    graph = lineage_service.get_lineage(
        db=db,
        table_id=table_id,
        depth=depth,
        direction=direction,
        level=level,
    )

    return graph


# ---------------------------------------------------------------------------
# 11. POST /tables/{table_id}/lineage
# ---------------------------------------------------------------------------

@router.post("/tables/{table_id}/lineage")
async def create_lineage(
    table_id: int,
    body: CreateLineageRequest,
    request: Request,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """新增手工血缘"""
    table = _get_authorized_table(db, table_id, current_user)

    # 强制：path table_id 必须是 source 或 target
    effective_source = body.source_table_id
    effective_target = body.target_table_id or table_id
    if table_id != effective_source and table_id != effective_target:
        raise HTTPException(status_code=400, detail={
            "error_code": "DWASSET_008",
            "message": "路径中的表必须是血缘关系的源或目标",
        })

    if effective_source == effective_target:
        raise HTTPException(status_code=400, detail={
            "error_code": "DWASSET_008",
            "message": "血缘关系不能自环",
        })

    # 校验 source 和 target 都属于当前用户可访问的数据源（IDOR 防护）
    is_admin = current_user.get("role") == "admin"
    for check_table_id in (effective_source, effective_target):
        if check_table_id == table_id:
            continue  # 已通过 _get_authorized_table 校验
        asset = db.query(DwAssetTable).filter(
            DwAssetTable.id == check_table_id,
            DwAssetTable.is_deleted == False,
        ).first()
        if not asset:
            raise HTTPException(status_code=400, detail={
                "error_code": "DWASSET_008",
                "message": f"表 {check_table_id} 不存在",
            })
        if not is_admin:
            ds = db.query(DataSource).filter(
                DataSource.id == asset.datasource_id,
                DataSource.owner_id == current_user["id"],
            ).first()
            if not ds:
                raise HTTPException(status_code=403, detail={
                    "error_code": "DWASSET_002",
                    "message": "无权访问目标表所属数据源",
                })

    # 创建边
    edge = DwAssetLineageEdge(
        lineage_type=body.lineage_type,
        source_table_id=effective_source,
        source_column_id=body.source_column_id,
        target_table_id=effective_target,
        target_column_id=body.target_column_id,
        relation_type=body.relation_type,
        confidence=1.0,
        source_system="manual",
        transformation_logic=body.transformation_logic,
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)

    log_action(
        current_user["id"], current_user.get("username", ""),
        "create", "dw_asset_lineage", edge.id,
        after_state=edge.to_dict(),
    )

    return {"message": "血缘关系已创建", "edge": edge.to_dict()}


# ---------------------------------------------------------------------------
# 12. DELETE /tables/{table_id}/lineage/{edge_id}
# ---------------------------------------------------------------------------

@router.delete("/tables/{table_id}/lineage/{edge_id}")
async def delete_lineage(
    table_id: int,
    edge_id: int,
    request: Request,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """删除手工血缘（仅 source_system='manual'）"""
    _get_authorized_table(db, table_id, current_user)

    edge = db.query(DwAssetLineageEdge).filter(
        DwAssetLineageEdge.id == edge_id,
        or_(
            DwAssetLineageEdge.source_table_id == table_id,
            DwAssetLineageEdge.target_table_id == table_id,
        ),
    ).first()

    if not edge:
        raise HTTPException(status_code=404, detail={
            "error_code": "DWASSET_001",
            "message": "血缘关系不存在",
        })

    if edge.source_system != "manual":
        raise HTTPException(status_code=400, detail={
            "error_code": "DWASSET_008",
            "message": "仅允许删除手工维护的血缘关系",
        })

    before_state = edge.to_dict()
    db.delete(edge)
    db.commit()

    log_action(
        current_user["id"], current_user.get("username", ""),
        "delete", "dw_asset_lineage", edge_id,
        before_state=before_state,
    )

    return {"message": "血缘关系已删除", "success": True}


# ---------------------------------------------------------------------------
# 13. GET /tables/{table_id}/preview
# ---------------------------------------------------------------------------

@router.get("/tables/{table_id}/preview")
async def preview_table_data(
    table_id: int,
    request: Request,
    limit: int = 20,
    columns: Optional[str] = None,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """数据预览（实时查询外部数仓）"""
    table = _get_authorized_table(db, table_id, current_user)

    # analyst 最多 20 行，data_admin/admin 最多 100 行
    if current_user["role"] == "analyst":
        max_limit = 20
    else:
        max_limit = 100
    if limit > max_limit:
        limit = max_limit

    # 解析 columns 参数
    selected_columns = None
    if columns:
        selected_columns = [c.strip() for c in columns.split(",") if c.strip()]

    preview_service = PreviewService()
    try:
        result = preview_service.preview_table(
            db=db,
            table_id=table_id,
            limit=limit,
            columns=selected_columns,
            user_role=current_user["role"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={
            "error_code": "DWASSET_006",
            "message": str(e),
        })
    except TimeoutError:
        raise HTTPException(status_code=503, detail={
            "error_code": "DWASSET_007",
            "message": "数据预览超时，请稍后重试",
        })
    except Exception as e:
        logger.error("数据预览失败: table_id=%s, error=%s", table_id, str(e))
        raise HTTPException(status_code=500, detail={
            "error_code": "DWASSET_005",
            "message": "数据预览执行失败",
        })

    # 审计
    log_action(
        current_user["id"], current_user.get("username", ""),
        "preview", "dw_asset_table", table_id,
    )

    return result


# ---------------------------------------------------------------------------
# 14. POST /datasources/{datasource_id}/sync
# ---------------------------------------------------------------------------

@router.post("/datasources/{datasource_id}/sync")
async def trigger_sync(
    datasource_id: int,
    body: TriggerSyncRequest,
    request: Request,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """触发元数据同步"""
    # 权限校验：非 admin 必须是数据源 owner
    ds = db.query(DataSource).filter(
        DataSource.id == datasource_id,
        DataSource.is_active == True,
    ).first()
    if not ds:
        raise HTTPException(status_code=404, detail={
            "error_code": "DWASSET_001",
            "message": "数据源不存在",
        })

    if current_user["role"] != "admin" and ds.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail={
            "error_code": "DWASSET_002",
            "message": "无权访问该数据源资产",
        })

    # 检查数据源类型
    if ds.db_type not in ("starrocks", "mysql"):
        raise HTTPException(status_code=400, detail={
            "error_code": "DWASSET_003",
            "message": f"不支持的数据源类型: {ds.db_type}，仅支持 starrocks/mysql",
        })

    # 检查是否有正在运行的同步
    running = db.query(DwAssetSyncRun).filter(
        DwAssetSyncRun.datasource_id == datasource_id,
        DwAssetSyncRun.status == "running",
    ).first()
    if running:
        raise HTTPException(status_code=409, detail={
            "error_code": "DWASSET_004",
            "message": "该数据源已有同步任务在运行中",
        })

    # 创建同步
    sync_service = MetadataSyncService()
    result = sync_service.sync_datasource(
        db=db,
        datasource_id=datasource_id,
        mode=body.mode,
        include_partitions=body.include_partitions,
        operator_id=current_user["id"],
    )

    if result.get("error"):
        code = result.get("code", "DWASSET_005")
        status = 409 if code == "DWASSET_004" else 500
        raise HTTPException(status_code=status, detail={
            "error_code": code,
            "message": result.get("message", "同步失败"),
        })

    log_action(
        current_user["id"], current_user.get("username", ""),
        "create", "dw_asset_sync_run", result.get("id"),
        after_state=result,
    )

    return {
        "sync_run_id": result.get("id"),
        "status": result.get("status"),
        "message": "元数据同步已开始",
    }


# ---------------------------------------------------------------------------
# 15. GET /sync-runs
# ---------------------------------------------------------------------------

@router.get("/sync-runs")
async def list_sync_runs(
    request: Request,
    datasource_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(require_roles(_DATA_ADMIN_PLUS)),
    db: Session = Depends(get_db),
):
    """获取同步历史"""
    if page_size > 100:
        page_size = 100

    query = db.query(DwAssetSyncRun)

    # 权限过滤：非 admin 只看自有数据源的同步记录
    if current_user["role"] != "admin":
        query = query.join(
            DataSource, DwAssetSyncRun.datasource_id == DataSource.id
        ).filter(DataSource.owner_id == current_user["id"])

    if datasource_id:
        query = query.filter(DwAssetSyncRun.datasource_id == datasource_id)
    if status:
        query = query.filter(DwAssetSyncRun.status == status)

    query = query.order_by(DwAssetSyncRun.started_at.desc())

    total = query.count()
    pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size
    runs = query.offset(offset).limit(page_size).all()

    return {
        "items": [r.to_dict() for r in runs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# 16. POST /tables/{table_id}/agent-context
# ---------------------------------------------------------------------------

@router.post("/tables/{table_id}/agent-context")
async def generate_agent_context(
    table_id: int,
    body: AgentContextRequest,
    request: Request,
    current_user: dict = Depends(require_roles(_ANALYST_PLUS)),
    db: Session = Depends(get_db),
):
    """生成 Data Agent 上下文埋点"""
    table = _get_authorized_table(db, table_id, current_user)

    # 获取字段信息——无论是否指定 selected_columns，都必须排除 restricted/confidential
    user_role = current_user.get("role", "analyst")
    forbidden_levels = ["restricted"]
    if user_role == "analyst":
        forbidden_levels = ["restricted", "confidential"]

    col_query = db.query(DwAssetColumn).filter(
        DwAssetColumn.table_id == table_id,
        DwAssetColumn.sensitivity_level.notin_(forbidden_levels),
    )
    if body.selected_columns:
        col_query = col_query.filter(DwAssetColumn.column_name.in_(body.selected_columns))
    else:
        col_query = col_query.order_by(DwAssetColumn.ordinal_position.asc()).limit(20)

    columns = col_query.all()

    context = {
        "type": "dw_table",
        "asset_uid": table.asset_uid,
        "table_name": table.table_name,
        "business_name": table.business_name,
        "columns": [
            {
                "name": c.column_name,
                "type": c.data_type,
                "business_name": c.business_name,
            }
            for c in columns
        ],
    }

    event_id = str(uuid.uuid4())

    # 记录埋点
    log_action(
        current_user["id"], current_user.get("username", ""),
        "agent_context", "dw_asset_table", table_id,
        after_state={"intent": body.intent, "event_id": event_id},
    )

    return {"context": context, "event_id": event_id}
