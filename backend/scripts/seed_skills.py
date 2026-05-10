#!/usr/bin/env python3
"""幂等 seed：将静态工具写入 agent_skills + agent_skill_versions(v1)。重复执行不报错。

用法：cd backend && python scripts/seed_skills.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os

# 设置 DATABASE_URL，若已有环境变量则优先使用
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://mulan:mulan@localhost:5432/mulan_bi"

from app.core.database import SessionLocal
from services.skills.models import AgentSkill, AgentSkillVersion

# ---------------------------------------------------------------------------
# 14 个静态工具的初始 seed 数据
# skill_key 对应 BaseTool.name
# ---------------------------------------------------------------------------

STATIC_TOOLS = [
    {
        "skill_key": "query",
        "name": "自然语言查询",
        "category": "query",
        "admin_description": "将用户自然语言问题转换为 Tableau VizQL 查询并执行，返回结构化数据结果。",
        "llm_description": (
            "执行自然语言数据查询。将用户问题转换为 Tableau VizQL 查询并返回结构化数据结果。"
            "适用于询问销售额、数量、统计数据等。"
            "若已有 vizql_json 和 datasource_luid，可直接传入跳过 NL→VizQL 转换（更快）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "用户的自然语言问题，如 'Q4销售额是多少'",
                },
                "connection_id": {
                    "type": "integer",
                    "description": "数据源连接 ID（可选，默认使用系统默认连接）",
                },
                "vizql_json": {
                    "type": "object",
                    "description": "已生成的 VizQL JSON 查询（可选）。若提供则直接执行，跳过 NL→VizQL 转换。须同时提供 datasource_luid。",
                },
                "datasource_luid": {
                    "type": "string",
                    "description": "数据源 LUID（与 vizql_json 配合使用）",
                },
                "datasource_name": {
                    "type": "string",
                    "description": "数据源名称（与 vizql_json 配合使用，用于结果展示）",
                },
            },
            "required": ["question"],
        },
        "code_ref": "QueryTool",
    },
    {
        "skill_key": "schema",
        "name": "表结构查询",
        "category": "query",
        "admin_description": "查询数据源的表结构、字段信息。",
        "llm_description": (
            "查询数据源的表结构、字段信息。"
            "当用户询问「有哪些表」「某表的字段是什么」「数据结构」时使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "integer",
                    "description": "数据源连接 ID（可选，默认使用 context.connection_id）",
                },
                "table_name": {
                    "type": "string",
                    "description": "指定表名，查询该表的字段结构（可选，不填则返回所有表）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回的表数量上限（默认 100）",
                    "default": 100,
                },
            },
            "required": [],
        },
        "code_ref": "SchemaTool",
    },
    {
        "skill_key": "metrics",
        "name": "指标查询",
        "category": "query",
        "admin_description": "查询指标定义和维度信息。",
        "llm_description": (
            "查询指标定义和维度信息。"
            "当用户询问「有哪些指标」「指标的计算方式」「某指标的维度」时使用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "integer",
                    "description": "数据源连接 ID（可选，用于过滤该数据源的指标）",
                },
                "keyword": {
                    "type": "string",
                    "description": "关键词过滤，匹配指标名称或描述（可选）",
                },
                "metric_type": {
                    "type": "string",
                    "description": "指标类型过滤，如 'gauge', 'counter', 'derived'（可选）",
                },
                "business_domain": {
                    "type": "string",
                    "description": "业务域过滤，如 'sales', 'finance'（可选）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回的指标数量上限（默认 50）",
                    "default": 50,
                },
            },
            "required": [],
        },
        "code_ref": "MetricsTool",
    },
    {
        "skill_key": "causation",
        "name": "归因分析",
        "category": "analysis",
        "admin_description": "六步因果推理，分析哪些维度贡献最大。",
        "llm_description": (
            "归因分析。当用户询问指标变动原因（如「为什么销售额下降了」「哪些因素导致增长」）时使用，"
            "分析哪些维度贡献最大，实现六步因果推理。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "指标名称",
                },
                "direction": {
                    "type": "string",
                    "enum": ["increase", "decrease"],
                    "description": "变动方向",
                },
                "connection_id": {
                    "type": "integer",
                    "description": "数据源 ID（可选）",
                },
                "time_range": {
                    "type": "string",
                    "description": "时间范围，如 last_7d, last_30d",
                },
            },
            "required": ["metric_name", "direction"],
        },
        "code_ref": "CausationTool",
    },
    {
        "skill_key": "chart",
        "name": "图表发布",
        "category": "visualization",
        "admin_description": "将查询结果发布为 Tableau Custom View 或 TWB 骨架。",
        "llm_description": (
            "【仅用于 Tableau 发布】将已有查询结果发布为 Tableau Custom View 或 TWB 骨架。"
            "注意：此工具不用于对话内图表渲染——若用户只是想「看图」「做个趋势图」，"
            "应直接用 query 工具获取数据，系统会自动渲染 Recharts 图表。"
            "仅在用户明确要求「发布到 Tableau」「生成 TWB」「推送到工作簿」时才调用本工具。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter", "area", "heatmap", "geo", "gantt", "histogram", "box"],
                    "description": "指定图表类型（可选，不指定则由 Viz Agent 自动推荐）",
                },
                "title": {
                    "type": "string",
                    "description": "图表标题（可选）",
                },
                "data": {
                    "type": "object",
                    "description": "数据（含 fields + rows，用于生成 schema）",
                },
                "schema": {
                    "type": "object",
                    "description": "查询结果 schema（columns/row_count_estimate/sample_values），优先级高于 data",
                },
                "user_intent": {
                    "type": "string",
                    "description": "用户自然语言意图，如「分析月度销售趋势」（可选）",
                },
                "x_field": {"type": "string", "description": "X 轴字段（可选）"},
                "y_field": {"type": "string", "description": "Y 轴字段（可选）"},
                "output_mode": {
                    "type": "string",
                    "enum": ["card", "twb", "mcp"],
                    "description": "输出路径：card=规格卡片（默认）, twb=TWB骨架, mcp=Tableau Custom View",
                },
                "connection_id": {
                    "type": "integer",
                    "description": "Tableau 连接 ID（mode=mcp 时需要）",
                },
                "workbook_luid": {
                    "type": "string",
                    "description": "Tableau 工作簿 LUID（mode=mcp 时需要）",
                },
            },
            "required": [],
        },
        "code_ref": "ChartTool",
    },
    {
        "skill_key": "report_generation",
        "name": "报告生成",
        "category": "reporting",
        "admin_description": "将分析结论生成为结构化报告（JSON规范层 + Markdown渲染层）。",
        "llm_description": (
            "自动生成分析报告。将归因分析、趋势分析等结论生成为结构化报告（JSON规范层 + Markdown渲染层）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "报告主题"},
                "analysis_type": {
                    "type": "string",
                    "enum": ["causation", "trend", "comparison", "correlation", "segmentation", "funnel", "cohort", "root_cause"],
                    "description": "分析类型",
                },
                "analysis_result": {
                    "type": "object",
                    "description": "分析结果数据（来自其他工具的输出）",
                },
                "time_range": {
                    "type": "object",
                    "description": "分析时间范围 {start, end}",
                },
                "include_sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "包含的报告章节，如 ['finding', 'evidence', 'recommendation']",
                },
                "output_format": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "输出格式 ['json', 'markdown']",
                    "default": ["json", "markdown"],
                },
            },
            "required": ["subject", "analysis_type", "analysis_result"],
        },
        "code_ref": "ReportGenerationTool",
    },
    {
        "skill_key": "proactive_insight",
        "name": "主动洞察",
        "category": "analysis",
        "admin_description": "扫描数据检测异常/趋势/维度集中度等，生成洞察并推送。",
        "llm_description": (
            "主动洞察发现。扫描数据检测异常/趋势/维度集中度等，生成洞察并推送。用于定时巡检和异常告警触发。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "scan_type": {
                    "type": "string",
                    "enum": ["full", "incremental", "triggered"],
                    "description": "扫描类型：full（全量）、incremental（增量）、triggered（触发式）",
                    "default": "incremental",
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要扫描的指标列表（为空则扫描所有活跃指标）",
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要扫描的维度列表",
                },
                "time_range": {
                    "type": "object",
                    "description": "扫描时间范围 {start, end}（可选）",
                },
                "sensitivity_threshold": {
                    "type": "number",
                    "description": "异常检测灵敏度阈值（默认 1.5σ）",
                    "default": 1.5,
                },
            },
            "required": [],
        },
        "code_ref": "ProactiveInsightTool",
    },
    {
        "skill_key": "data_comparison",
        "name": "数据对比",
        "category": "analysis",
        "admin_description": "对比两个数据集、指标或维度分类的差异。",
        "llm_description": (
            "跨数据集比较。对比两个数据集、指标或维度分类的差异，返回差异点、相似点和统计显著性。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "dataset_a": {
                    "type": "object",
                    "description": "数据集 A（包含 metric, dimensions, time_range）",
                },
                "dataset_b": {
                    "type": "object",
                    "description": "数据集 B（包含 metric, dimensions, time_range）",
                },
                "comparison_type": {
                    "type": "string",
                    "enum": ["temporal", "cross_sectional", "dimension_breakdown"],
                    "description": "比较类型：temporal（时间对比）、cross_sectional（横截面对比）、dimension_breakdown（维度分解对比）",
                    "default": "temporal",
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要比较的指标列表",
                },
            },
            "required": ["dataset_a", "dataset_b"],
        },
        "code_ref": "DataComparisonTool",
    },
    {
        "skill_key": "trend_analysis",
        "name": "趋势分析",
        "category": "analysis",
        "admin_description": "分析指标的时间序列趋势，识别上升/下降/平稳模式。",
        "llm_description": (
            "趋势分析（统计摘要）。注意：本工具返回统计摘要，不包含原始时间序列数据。"
            "如需逐年/逐月明细数据，请先用 query 工具获取，再用本工具做趋势判断。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "metric": {"type": "string", "description": "指标名称"},
                "time_range": {"type": "object", "description": "时间范围 {start, end}"},
                "granularity": {
                    "type": "string",
                    "enum": ["day", "week", "month", "quarter"],
                    "description": "时间粒度",
                    "default": "day",
                },
                "analysis_mode": {
                    "type": "string",
                    "enum": ["simple", "seasonal", "growth_rate", "moving_average"],
                    "description": "分析模式",
                    "default": "simple",
                },
                "window_size": {
                    "type": "integer",
                    "description": "移动平均窗口大小（用于 moving_average 模式）",
                    "default": 7,
                },
            },
            "required": ["metric", "time_range"],
        },
        "code_ref": "TrendAnalysisTool",
    },
    {
        "skill_key": "correlation_discovery",
        "name": "相关性发现",
        "category": "analysis",
        "admin_description": "计算两个或多个指标序列之间的相关性。",
        "llm_description": (
            "相关性发现。计算两个或多个指标序列之间的相关性（皮尔逊/斯皮尔曼），识别强相关、弱相关、正负相关。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要分析相关性的指标列表（至少2个）",
                },
                "time_range": {"type": "object", "description": "时间范围 {start, end}"},
                "method": {
                    "type": "string",
                    "enum": ["pearson", "spearman", "both"],
                    "description": "相关性计算方法",
                    "default": "both",
                },
                "lag_analysis": {
                    "type": "boolean",
                    "description": "是否进行时间滞后分析",
                    "default": False,
                },
                "min_correlation": {
                    "type": "number",
                    "description": "最小相关系数阈值（绝对值）",
                    "default": 0.5,
                },
            },
            "required": ["metrics", "time_range"],
        },
        "code_ref": "CorrelationDiscoveryTool",
    },
    {
        "skill_key": "segmentation_analysis",
        "name": "分群分析",
        "category": "analysis",
        "admin_description": "基于行为、属性等维度对用户或其他实体进行分群。",
        "llm_description": (
            "用户/实体分群分析。基于行为、属性等维度对用户或其他实体进行分群，识别不同群体特征和差异。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "entity_type": {
                    "type": "string",
                    "enum": ["user", "customer", "product", "region", "custom"],
                    "description": "实体类型",
                    "default": "user",
                },
                "segmentation_dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "分群维度列表",
                },
                "time_range": {"type": "object", "description": "分析时间范围 {start, end}"},
                "num_segments": {
                    "type": "integer",
                    "description": "分群数量",
                    "default": 4,
                },
                "segmentation_method": {
                    "type": "string",
                    "enum": ["kmeans", "hierarchical", "rule_based"],
                    "description": "分群方法",
                    "default": "kmeans",
                },
            },
            "required": ["entity_type", "segmentation_dimensions", "time_range"],
        },
        "code_ref": "SegmentationAnalysisTool",
    },
    {
        "skill_key": "funnel_analysis",
        "name": "漏斗分析",
        "category": "analysis",
        "admin_description": "分析用户行为漏斗，计算各步骤转化率、流失率。",
        "llm_description": (
            "漏斗分析。分析用户行为漏斗，计算各步骤转化率、流失率，识别漏斗中的关键瓶颈和优化点。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "funnel_name": {"type": "string", "description": "漏斗名称"},
                "funnel_steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_name": {"type": "string"},
                            "event_name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                    "description": "漏斗步骤列表（按顺序）",
                },
                "time_range": {"type": "object", "description": "分析时间范围 {start, end}"},
                "segmentation_dimension": {
                    "type": "string",
                    "description": "分维度分析（可选），如 'channel', 'region'",
                },
            },
            "required": ["funnel_steps", "time_range"],
        },
        "code_ref": "FunnelAnalysisTool",
    },
    {
        "skill_key": "cohort_analysis",
        "name": "队列分析",
        "category": "analysis",
        "admin_description": "基于时间或其他维度划分队列，分析不同队列的行为差异。",
        "llm_description": (
            "队列分析。基于时间或其他维度划分队列，分析不同队列的行为差异、留存曲线和生命周期价值。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "cohort_type": {
                    "type": "string",
                    "enum": ["time", "source", "channel", "acquisition", "custom"],
                    "description": "队列划分类型",
                    "default": "time",
                },
                "cohort_period": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "quarterly"],
                    "description": "队列时间粒度",
                    "default": "monthly",
                },
                "time_range": {"type": "object", "description": "分析时间范围 {start, end}"},
                "metric": {
                    "type": "string",
                    "description": "追踪指标（默认 retention_rate）",
                },
                "num_periods": {
                    "type": "integer",
                    "description": "追踪周期数",
                    "default": 6,
                },
            },
            "required": ["time_range"],
        },
        "code_ref": "CohortAnalysisTool",
    },
    {
        "skill_key": "root_cause_analysis",
        "name": "根因分析",
        "category": "analysis",
        "admin_description": "采用5-Why分析法和鱼骨图框架，深入挖掘问题的根本原因。",
        "llm_description": (
            "增强根因分析。采用5-Why分析法和鱼骨图框架，深入挖掘问题的根本原因，量化各影响因子。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "integer", "description": "数据源连接 ID"},
                "problem_statement": {"type": "string", "description": "问题描述"},
                "problem_metric": {"type": "string", "description": "问题相关指标"},
                "direction": {
                    "type": "string",
                    "enum": ["increase", "decrease"],
                    "description": "问题方向",
                },
                "time_range": {"type": "object", "description": "分析时间范围 {start, end}"},
                "analysis_depth": {
                    "type": "integer",
                    "description": "分析深度（Why 层数，默认 5）",
                    "default": 5,
                },
            },
            "required": ["problem_statement", "problem_metric", "direction", "time_range"],
        },
        "code_ref": "RootCauseAnalysisTool",
    },
]


def seed() -> None:
    """幂等写入：已存在的 skill_key 跳过，未存在的写入 agent_skills + agent_skill_versions(v1)。"""
    db = SessionLocal()
    try:
        created = 0
        skipped = 0
        for tool in STATIC_TOOLS:
            existing = db.query(AgentSkill).filter(
                AgentSkill.skill_key == tool["skill_key"]
            ).first()
            if existing:
                skipped += 1
                continue

            # 创建 skill
            skill = AgentSkill(
                skill_key=tool["skill_key"],
                name=tool["name"],
                description=tool["admin_description"],
                category=tool["category"],
                is_enabled=True,
            )
            db.add(skill)
            db.flush()

            # 创建 v1 版本（is_active=True）
            version = AgentSkillVersion(
                skill_id=skill.id,
                version_number="v1",
                description=tool["llm_description"],
                input_schema=tool["input_schema"],
                endpoint_type="static",
                code_ref=tool["code_ref"],
                change_notes="初始版本（seed 自动生成）",
                is_active=True,
            )
            db.add(version)
            created += 1

        db.commit()
        print(f"[seed_skills] 完成：创建 {created} 个技能，跳过 {skipped} 个（已存在）。")
    except Exception as e:
        db.rollback()
        print(f"[seed_skills] 错误：{e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
