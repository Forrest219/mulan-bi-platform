"""
Viz Agent API 路由 (Spec 26 附录 A §5)

POST /api/visualization/recommend — 图表推荐
POST /api/visualization/export — 触发输出（三路径：mcp/twb/card）
GET  /api/visualization/preview/{chart_spec_id} — 预览（ECharts 缩略图）

路由注册：backend/app/api/visualization.py
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visualization", tags=["visualization"])


# ── Request/Response Models ──────────────────────────────────────────────────


class QuerySchemaColumn(BaseModel):
    name: str
    dtype: str = "STRING"
    role: str = "dimension"
    sensitivity_level: Optional[str] = None


class QuerySchema(BaseModel):
    columns: list[QuerySchemaColumn] = Field(..., min_length=1, max_length=50)
    row_count_estimate: Optional[str] = None
    sample_values: Optional[Dict[str, list[Any]]] = None


class RecommendRequest(BaseModel):
    query_schema: QuerySchema
    user_intent: Optional[str] = ""
    datasource_luid: Optional[str] = None
    connection_id: Optional[int] = None


class RecommendResponse(BaseModel):
    recommendations: list[Dict[str, Any]]
    meta: Dict[str, Any]


class ExportRequest(BaseModel):
    recommendation: Dict[str, Any]
    mode: str = Field(..., pattern="^(mcp|twb|card)$")
    mcp_config: Optional[Dict[str, Any]] = None


class ExportResponse(BaseModel):
    mode: str
    # mode=card
    spec_card: Optional[Dict[str, Any]] = None
    # mode=twb
    download_url: Optional[str] = None
    expires_at: Optional[str] = None
    filename: Optional[str] = None
    # mode=mcp
    view_url: Optional[str] = None
    custom_view_id: Optional[str] = None
    message: Optional[str] = None


# ── Error Helpers ────────────────────────────────────────────────────────────


def viz_error(code: str, message: str, status_code: int = 400):
    return HTTPException(status_code=status_code, detail={"error_code": code, "message": message})


# ── Route Handlers ───────────────────────────────────────────────────────────


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_viz_charts(req: RecommendRequest):
    """
    图表推荐接口。

    输入查询 schema + 用户意图，返回最多 3 个推荐图表类型（按置信度降序）。
    """
    # Schema 空检查
    if not req.query_schema.columns:
        raise viz_error("VIZ_001", "query_schema.columns 不能为空")

    # 检查是否所有列均为高敏感
    all_high_sensitivity = all(
        col.sensitivity_level in ("high", "confidential")
        for col in req.query_schema.columns
    )
    if all_high_sensitivity:
        raise viz_error(
            "VIZ_008",
            "高敏感字段被全部过滤，schema 为空",
            status.HTTP_400_BAD_REQUEST,
        )

    # Schema 预处理
    schema_dict = {
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "role": c.role,
                "sensitivity_level": c.sensitivity_level,
            }
            for c in req.query_schema.columns
        ],
        "row_count_estimate": req.query_schema.row_count_estimate or "~1K",
        "sample_values": req.query_schema.sample_values or {},
    }

    # 调用 ChartRecommender（惰性导入避免循环）
    from services.visualization import ChartRecommender

    recommender = ChartRecommender()
    result = await recommender.recommend(
        schema=schema_dict,
        user_intent=req.user_intent or "",
        connection_id=req.connection_id,
        datasource_luid=req.datasource_luid,
    )

    if "error_code" in result:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result,
        )

    return result


@router.post("/export", response_model=ExportResponse)
async def export_viz_chart(req: ExportRequest):
    """
    图表输出接口（支持三路径）。

    - mode=card：返回规格卡片数据（含 ECharts 预览配置）
    - mode=twb：生成 TWB 骨架，返回下载 URL
    - mode=mcp：通过 MCP Bridge 在 Tableau 中创建 Custom View
    """
    recommendation = req.recommendation
    mode = req.mode

    if mode == "card":
        # 路径 3：规格卡片
        from services.visualization import SpecCardBuilder

        builder = SpecCardBuilder()
        spec_card = builder.build_spec_card(recommendation)

        return ExportResponse(
            mode="card",
            spec_card=spec_card,
        )

    elif mode == "twb":
        # 路径 2：TWB 骨架
        from services.visualization import TWBGenerator

        generator = TWBGenerator()
        twb_result = generator.generate_twb(recommendation)

        return ExportResponse(
            mode="twb",
            download_url=twb_result["download_url"],
            expires_at=twb_result["expires_at"],
            filename=twb_result["filename"],
        )

    elif mode == "mcp":
        # 路径 1：MCP Bridge
        if not req.mcp_config:
            raise viz_error("VIZ_005", "mode=mcp 时 mcp_config 不能为空")

        connection_id = req.mcp_config.get("connection_id")
        workbook_luid = req.mcp_config.get("workbook_luid")
        target_sheet = req.mcp_config.get("target_sheet", "Sheet 1")

        if not connection_id:
            raise viz_error("VIZ_005", "mcp_config.connection_id 不能为空")

        # 惰性导入 MCP 工具（避免循环依赖）
        try:
            from services.visualization.mcp_tools_viz import CreateVizCustomViewTool

            tool = CreateVizCustomViewTool(mcp_client=None, semantic_service=None)
            result = tool.execute(
                view_luid=workbook_luid or "",
                view_name=recommendation.get("suggested_title", "推荐图表"),
                field_mapping=recommendation.get("field_mapping", {}),
                chart_type=recommendation.get("chart_type", "bar"),
                tableau_mark_type=recommendation.get("tableau_mark_type", "Bar"),
                filters=[],
                connection_id=connection_id,
            )

            return ExportResponse(
                mode="mcp",
                view_url=result.get("view_url", ""),
                custom_view_id=result.get("custom_view_luid", ""),
                message=result.get("message", "已在 Tableau 中创建 Custom View"),
            )

        except Exception as e:
            logger.error("MCP Bridge 调用失败: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error_code": "VIZ_009",
                    "message": "Tableau MCP 连接不可用",
                    "detail": str(e),
                },
            )

    raise viz_error("VIZ_999", f"不支持的 mode: {mode}")


@router.get("/preview/{chart_spec_id}")
async def preview_chart(chart_spec_id: str):
    """
    ECharts 缩略图预览接口（占位）。

    chart_spec_id：对应之前 recommend 返回的 spec_id。
    当前返回 mock 预览数据，实际由前端 SpecCard 组件渲染。
    """
    return {
        "chart_spec_id": chart_spec_id,
        "preview_url": f"/api/visualization/preview/{chart_spec_id}/render",
        "status": "pending_implementation",
        "message": "ECharts 预览需配合前端 SpecCard 组件使用",
    }
