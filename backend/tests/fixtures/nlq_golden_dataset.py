"""
NL-to-Query Golden Dataset（标准数据集）

用途：
  1. Stage 1（One-Pass LLM）：校验 LLM 输出的 JSON 是否符合 §5.5.2 格式
  2. Stage 3（MCP 通讯层）：校验 query-datasource 响应是否匹配 §5.5.3 格式
  3. Stage 4（结果格式化）：校验 number/table/text 推断逻辑是否正确

数据源假设：Superstore（Region/Category/Order Date/Sales/Profit/Quantity 等）
所有 vizql_json 严格遵循 §5.5.2 的 field/filters 结构。
"""

from typing import TypedDict


class ExpectedVizql(TypedDict):
    fields: list
    filters: list


class ExpectedMockResponse(TypedDict):
    fields: list
    rows: list


class GoldenCase(TypedDict):
    id: int
    question: str
    intent: str
    expected_vizql_json: ExpectedVizql
    expected_mock_response: ExpectedMockResponse
    expected_response_type: str
    notes: str


# ─────────────────────────────────────────────────────────────────────────────
# Golden Dataset（20 组）
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_DATASET: list[GoldenCase] = [
    # ── Aggregate ──────────────────────────────────────────────────────────────

    {
        "id": 1,
        "question": "总销售额是多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [{"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "总销售额"}],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [{"fieldCaption": "Sales", "dataType": "number"}],
            "rows": [[2098256.0]],
        },
        "expected_response_type": "number",
        "notes": "最基础的聚合查询，总销售额 → 单值 number",
    },
    {
        "id": 2,
        "question": "平均订单金额是多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [{"fieldCaption": "Sales", "function": "AVG", "fieldAlias": "平均订单金额"}],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [{"fieldCaption": "Sales", "dataType": "number"}],
            "rows": [[458.43]],
        },
        "expected_response_type": "number",
        "notes": "AVG 聚合，无分组",
    },
    {
        "id": 3,
        "question": "订单数量有多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [{"fieldCaption": "Order ID", "function": "COUNT", "fieldAlias": "订单数量"}],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [{"fieldCaption": "Order ID", "dataType": "number"}],
            "rows": [[4576]],
        },
        "expected_response_type": "number",
        "notes": "COUNT 计数，维度字段无需 function",
    },
    {
        "id": 4,
        "question": "有多少种产品类别",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [{"fieldCaption": "Category", "function": "COUNTD", "fieldAlias": "产品类别数"}],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [{"fieldCaption": "Category", "dataType": "number"}],
            "rows": [[3]],
        },
        "expected_response_type": "number",
        "notes": "COUNTD 去重",
    },
    {
        "id": 5,
        "question": "最高利润是多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [{"fieldCaption": "Profit", "function": "MAX", "fieldAlias": "最高利润"}],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [{"fieldCaption": "Profit", "dataType": "number"}],
            "rows": [[8399.98]],
        },
        "expected_response_type": "number",
        "notes": "MAX 聚合",
    },
    {
        "id": 6,
        "question": "各区域的销售额是多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Region", "fieldAlias": "区域"},
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "总销售额"},
            ],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Region", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["华东", 567234.5],
                ["华南", 489123.0],
                ["华北", 421876.2],
                ["西南", 320102.3],
                ["东北", 299920.0],
            ],
        },
        "expected_response_type": "table",
        "notes": "分组聚合，Region 维度 + SUM(Sales) 度量 → 表格",
    },
    {
        "id": 7,
        "question": "各产品类别的利润总额是多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Category", "fieldAlias": "产品类别"},
                {"fieldCaption": "Profit", "function": "SUM", "fieldAlias": "利润总额"},
            ],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Category", "dataType": "string"},
                {"fieldCaption": "Profit", "dataType": "number"},
            ],
            "rows": [
                ["家具", 286397.2],
                ["办公用品", 167568.5],
                ["技术", 121422.3],
            ],
        },
        "expected_response_type": "table",
        "notes": "按 Category 分组的利润聚合",
    },

    # ── Filter ─────────────────────────────────────────────────────────────────

    {
        "id": 8,
        "question": "华东区域的订单有哪些",
        "intent": "filter",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Order ID", "fieldAlias": "订单号"},
                {"fieldCaption": "Customer Name", "fieldAlias": "客户名"},
                {"fieldCaption": "Sales", "fieldAlias": "销售额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Region"},
                    "filterType": "SET",
                    "values": ["华东"],
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Order ID", "dataType": "string"},
                {"fieldCaption": "Customer Name", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["CA-2018-10234", "王磊", 458.0],
                ["CA-2018-10876", "李娜", 1234.5],
            ],
        },
        "expected_response_type": "table",
        "notes": "SET 过滤器，等值过滤",
    },
    {
        "id": 9,
        "question": "类别包含家具和办公用品的产品",
        "intent": "filter",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Product Name", "fieldAlias": "产品名称"},
                {"fieldCaption": "Category", "fieldAlias": "类别"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Category"},
                    "filterType": "SET",
                    "values": ["家具", "办公用品"],
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Product Name", "dataType": "string"},
                {"fieldCaption": "Category", "dataType": "string"},
            ],
            "rows": [
                ["书架", "家具"],
                ["铅笔盒", "办公用品"],
            ],
        },
        "expected_response_type": "table",
        "notes": "SET 过滤器，多值",
    },
    {
        "id": 10,
        "question": "退货订单有哪些",
        "intent": "filter",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Order ID", "fieldAlias": "订单号"},
                {"fieldCaption": "Sales", "fieldAlias": "销售额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Status"},
                    "filterType": "SET",
                    "values": ["已退货"],
                    "exclude": True,
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Order ID", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["CA-2018-10234", 458.0],
                ["CA-2018-10876", 1234.5],
            ],
        },
        "expected_response_type": "table",
        "notes": "exclude=true 排除退货订单",
    },
    {
        "id": 11,
        "question": "销售额大于1000的订单",
        "intent": "filter",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Order ID", "fieldAlias": "订单号"},
                {"fieldCaption": "Sales", "fieldAlias": "销售额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Sales"},
                    "filterType": "QUANTITATIVE_NUMERICAL",
                    "quantitativeFilterType": "MIN",
                    "min": 1000,
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Order ID", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["CA-2018-10876", 1234.5],
                ["CA-2018-11567", 1890.2],
            ],
        },
        "expected_response_type": "table",
        "notes": "QUANTITATIVE_NUMERICAL MIN 过滤器，数值下界",
    },
    {
        "id": 12,
        "question": "利润在100到500之间的订单",
        "intent": "filter",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Order ID", "fieldAlias": "订单号"},
                {"fieldCaption": "Profit", "fieldAlias": "利润"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Profit"},
                    "filterType": "QUANTITATIVE_NUMERICAL",
                    "quantitativeFilterType": "RANGE",
                    "min": 100,
                    "max": 500,
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Order ID", "dataType": "string"},
                {"fieldCaption": "Profit", "dataType": "number"},
            ],
            "rows": [
                ["CA-2018-10234", 234.5],
                ["CA-2018-10987", 456.7],
            ],
        },
        "expected_response_type": "table",
        "notes": "QUANTITATIVE_NUMERICAL RANGE 过滤器，数值范围",
    },
    {
        "id": 13,
        "question": "产品名包含'桌'的产品",
        "intent": "filter",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Product Name", "fieldAlias": "产品名称"},
                {"fieldCaption": "Category", "fieldAlias": "类别"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Product Name"},
                    "filterType": "MATCH",
                    "contains": "桌",
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Product Name", "dataType": "string"},
                {"fieldCaption": "Category", "dataType": "string"},
            ],
            "rows": [
                ["办公桌", "家具"],
                ["电脑桌", "家具"],
            ],
        },
        "expected_response_type": "table",
        "notes": "MATCH 过滤器，关键词包含",
    },

    # ── Ranking ────────────────────────────────────────────────────────────────

    {
        "id": 14,
        "question": "销售额前10的产品",
        "intent": "ranking",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Product Name", "fieldAlias": "产品名称"},
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "总销售额"},
            ],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Product Name", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["Apple Phone", 34567.0],
                ["Cisco IP Phone", 28900.0],
                ["Harbour Doll", 23456.0],
                ["Sony Wega TV", 21234.0],
                ["Epson HP Printer", 19876.0],
                ["Nike Golf Set", 18765.0],
                ["Sauder Coat Rack", 17654.0],
                ["Global Chat", 16543.0],
                ["Hon High Back Leather Chair", 15432.0],
                ["Howard Hamster Wheel", 14321.0],
            ],
        },
        "expected_response_type": "table",
        "notes": "TOP 10 排名，默认降序；实际由 query.limit=10 控制",
    },
    {
        "id": 15,
        "question": "利润最低的5个区域",
        "intent": "ranking",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Region", "fieldAlias": "区域"},
                {"fieldCaption": "Profit", "function": "SUM", "fieldAlias": "总利润"},
            ],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Region", "dataType": "string"},
                {"fieldCaption": "Profit", "dataType": "number"},
            ],
            "rows": [
                ["东北", 3456.2],
                ["华北", 12340.5],
                ["西南", 18765.3],
                ["华南", 45678.9],
                ["华东", 56789.1],
            ],
        },
        "expected_response_type": "table",
        "notes": "BOTTOM 5 排名；vizql_json 不含 direction，降序由 query.limit 和 direction 参数控制",
    },

    # ── Trend ─────────────────────────────────────────────────────────────────

    {
        "id": 16,
        "question": "过去6个月销售额趋势",
        "intent": "trend",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Order Date", "function": "MONTH", "fieldAlias": "月份"},
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "销售额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Order Date"},
                    "filterType": "DATE",
                    "periodType": "MONTHS",
                    "dateRangeType": "LASTN",
                    "rangeN": 6,
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Order Date", "dataType": "date"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["2024-10", 324567.0],
                ["2024-11", 356789.0],
                ["2024-12", 412345.0],
                ["2025-01", 298765.0],
                ["2025-02", 287654.0],
                ["2025-03", 345678.0],
            ],
        },
        "expected_response_type": "table",
        "notes": "时间粒度 MONTH + LASTN 过滤器 = 趋势折线图",
    },
    {
        "id": 17,
        "question": "本月的销售额是多少",
        "intent": "trend",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "本月销售额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Order Date"},
                    "filterType": "DATE",
                    "periodType": "MONTHS",
                    "dateRangeType": "CURRENT",
                }
            ],
        },
        "expected_mock_response": {
            "fields": [{"fieldCaption": "Sales", "dataType": "number"}],
            "rows": [[345678.0]],
        },
        "expected_response_type": "number",
        "notes": "DATE CURRENT → 单值，与 aggregate 类似但有日期过滤语义",
    },
    {
        "id": 18,
        "question": "按季度的年度销售额",
        "intent": "trend",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Order Date", "function": "QUARTER", "fieldAlias": "季度"},
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "季度销售额"},
            ],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Order Date", "dataType": "date"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["2024-Q1", 567890.0],
                ["2024-Q2", 623456.0],
                ["2024-Q3", 598234.0],
                ["2024-Q4", 712345.0],
            ],
        },
        "expected_response_type": "table",
        "notes": "QUARTER 粒度无过滤，等效于年度分组",
    },

    # ── Comparison ─────────────────────────────────────────────────────────────

    {
        "id": 19,
        "question": "各区域本月销售额与上月对比",
        "intent": "comparison",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Region", "fieldAlias": "区域"},
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "本月销售额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Order Date"},
                    "filterType": "DATE",
                    "periodType": "MONTHS",
                    "dateRangeType": "CURRENT",
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Region", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["华东", 98765.0],
                ["华南", 87654.0],
                ["华北", 76543.0],
            ],
        },
        "expected_response_type": "table",
        "notes": "对比查询需两次查询（本期+上期），当前 JSON 只含本期；对比计算由前端或 Stage 4 完成",
    },
    {
        "id": 20,
        "question": "家具和办公用品的利润对比",
        "intent": "comparison",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Category", "fieldAlias": "产品类别"},
                {"fieldCaption": "Profit", "function": "SUM", "fieldAlias": "利润总额"},
            ],
            "filters": [
                {
                    "field": {"fieldCaption": "Category"},
                    "filterType": "SET",
                    "values": ["家具", "办公用品"],
                }
            ],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Category", "dataType": "string"},
                {"fieldCaption": "Profit", "dataType": "number"},
            ],
            "rows": [
                ["家具", 286397.2],
                ["办公用品", 167568.5],
            ],
        },
        "expected_response_type": "table",
        "notes": "两类别横向对比；如需百分比计算由 Stage 4 或前端完成",
    },

    # ── Fuzzy Matching（跨 Stage 1↔Stage 2 桥接）───────────────────────────────

    {
        "id": 21,
        "question": "各区域的营收是多少",
        "intent": "aggregate",
        "expected_vizql_json": {
            "fields": [
                {"fieldCaption": "Region", "fieldAlias": "区域"},
                {"fieldCaption": "Sales", "function": "SUM", "fieldAlias": "营收总额"},
            ],
            "filters": [],
        },
        "expected_mock_response": {
            "fields": [
                {"fieldCaption": "Region", "dataType": "string"},
                {"fieldCaption": "Sales", "dataType": "number"},
            ],
            "rows": [
                ["华东", 567234.5],
                ["华南", 489123.0],
                ["华北", 421876.2],
            ],
        },
        "expected_response_type": "table",
        "notes": (
            "【模糊匹配】用户说'营收'，实际数据源只有'Sales'字段。"
            "Stage 1（One-Pass LLM）生成 VizQL 时应将'营收'映射到'Sales'；"
            "Stage 2（FieldResolver）通过同义词表（营收→Sales）确认映射正确；"
            "最终 VizQL JSON 中的 fieldCaption 必须与 mock_response 一致，均为'Sales'，不是'营收'。"
            "此 case 验证 Stage 1→Stage 2 的跨阶段字段一致性桥接。"
        ),
    },
]
