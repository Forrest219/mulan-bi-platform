# 首页智能搜索 - 技术设计方案

> 文档版本：v1.0
> 日期：2026-04-01
> 状态：草案
> 适用范围：首页数据问答能力 V1 实现

---

## 一、能力目标

用户在首页搜索框输入自然语言问题，系统理解意图后自动路由到正确的数据源和字段，执行查询并返回结果。

**V1 范围**：
- 单轮问答（用户问，系统答，不支持多轮对话）
- 仅支持 SELECT 类查询（不执行写操作）
- 通过 Tableau MCP `query-datasource` 执行查询
- 前端渲染为数字卡片 / 简单表格

---

## 二、整体链路

```
用户问题
    ↓
[POST /api/search/ask]
    ↓
LLM 理解意图（读取语义元数据）
    ↓
确定数据源 + 目标字段 + 过滤条件
    ↓
构造 VizQL 查询
    ↓
调用 Tableau MCP query-datasource
    ↓
返回结构化结果 → 前端渲染
```

---

## 三、数据准备 — 语义元数据

### 3.1 语义元数据来源

V1 使用**语义维护**模块中已维护的字段级语义数据，作为 LLM 理解"用户问的是什么"的上下文。

**已有字段（元模型）**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `semantic_name` | 字段英文语义名 | `sales_amount` |
| `semantic_name_zh` | 字段中文名 | `销售额` |
| `metric_definition` | 指标口径说明 | `不含税的销售收入` |
| `dimension_definition` | 维度口径说明 | `按自然月统计` |
| `unit` | 单位 | `元`、`%`、`次` |
| `tags_json` | 同义词 | `["收入","营收"]` |

### 3.2 LLM 上下文构建

在执行 NL → VizQL 转换前，**不得**直接读取所有已维护字段元数据拼装为数据字典（会导致 Token 雪崩）。必须先通过 pgvector 向量检索召回最相关的字段元数据，再拼装为上下文传给 LLM。

**构建流程**：

1. **Embedding 召回**：将用户自然语言 Query 转化为 Embedding（调用 `text-embedding-3-small`），在数据库中以余弦相似度检索，召回 Top-10 最相关的表/字段元数据
2. **上下文拼装**：将召回结果拼装为结构化数据字典，**总 Token 严格控制在 3000 以内**
3. **LLM 理解**：LLM 根据召回的上下文理解用户意图并选择字段

**禁止**：读取所有已维护字段元数据并直接拼装——无论数据规模大小。

```
可用数据源和字段（向量检索召回 Top-10）：
[数据源A: sales_db]
  - sales_amount (销售额, 单位:元, 指标口径:不含税销售收入, 同义词:收入/营收) [相关性: 0.92]
  - order_date (订单日期, 维度, 按自然月统计) [相关性: 0.88]

[数据源B: inventory_db]
  - stock_qty (库存数量, 单位:件) [相关性: 0.75]
  ...
```

---

## 四、后端接口设计

### 4.1 新建路由文件

`backend/app/api/search.py`

### 4.2 接口定义

#### POST /api/search/ask

**请求体**：

```json
{
  "question": "Q1 销售额是多少"
}
```

**响应体**：

```json
{
  "answer": "Q1 销售额为 1,234,567 元",
  "type": "number",
  "data": {
    "value": 1234567,
    "unit": "元",
    "formatted": "1,234,567"
  },
  "datasource": {
    "id": 1,
    "name": "sales_db"
  },
  "query": {
    "fields": ["sales_amount"],
    "filters": [{"field": "order_date", "operator": "QUARTER", "value": "Q1"}]
  },
  "confidence": 0.92
}
```

**类型枚举**：
- `number`：单个数字结果（数字卡片渲染）
- `table`：多行表格结果
- `text`：无法结构化时返回文本回答
- `error`：查询失败

**错误响应**：

```json
{
  "answer": "无法回答该问题",
  "type": "error",
  "reason": "NO_MATCHING_FIELD",
  "detail": "语义库中未找到与'Q1'相关的时间字段"
}
```

### 4.3 错误码

| 错误码 | 说明 |
|--------|------|
| `NO_LLM_CONFIG` | 未配置 LLM |
| `NO_SEMANTIC_DATA` | 语义元数据为空 |
| `NO_MATCHING_FIELD` | 无法匹配到合适字段 |
| `QUERY_FAILED` | VizQL 执行失败 |
| `AMBIGUOUS` | 匹配到多个可能的数据源，需澄清 |

---

## 五、NL → VizQL 转换逻辑

### 5.1 System Prompt 设计

LLM 接收的 System Prompt 包含：
1. 数据字典（字段语义）
2. 查询构造规则（如何把自然语言转为 VizQL 字段+过滤条件）
3. 输出格式要求（必须 JSON）

### 5.2 LLM 输出格式

LLM 输出一个结构化的**查询意图对象**，由后端解析：

```json
{
  "datasource_id": 1,
  "datasource_name": "sales_db",
  "fields": [
    { "name": "sales_amount", "aggregation": "SUM", "alias": "销售额" }
  ],
  "filters": [
    { "field": "order_date", "operator": "QUARTER", "value": "Q1" }
  ],
  "order_by": [],
  "limit": 100,
  "reasoning": "用户问Q1销售额，选择sales_amount字段，filter用QUARTER操作符取Q1"
}
```

### 5.3 Operator 映射

LLM 输出的 operator 为抽象操作符，后端转为 VizQL filter 格式：

| LLM Operator | VizQL FilterType |
|---------------|-----------------|
| `EQ` | `SET` |
| `GT`, `GTE`, `LT`, `LTE` | `QUANTITATIVE_NUMERICAL` |
| `CONTAINS` | `MATCH` |
| `YEAR`, `QUARTER`, `MONTH` | `DATE` |
| `TOP_N` | `TOP` |

---

## 六、Tableau MCP 调用

### 6.1 调用工具

使用 `mcp__tableau-bi-ksyun__query-datasource`

### 6.2 调用参数构造

VizQL 查询意图对象 → `query-datasource` 参数：

```
datasourceLuid: Tableau 数据源 ID（从 semantic_maintenance 表中关联）
query:
  fields:
    - fieldCaption: "sales_amount"
      function: "SUM"
      fieldAlias: "销售额"
  filters:
    - field: { fieldCaption: "order_date" }
      filterType: "DATE"
      dateRangeType: "TODATE"  (或按 QUARTER 解析)
      periodType: "QUARTERS"
  parameters: []
```

### 6.3 多数据源路由

当语义元数据中同一字段名出现在多个数据源时（如 `sales_amount` 同时存在于 `sales_db` 和 `finance_db`），LLM 输出所有候选，后端按预设优先级（如连接活跃时间、字段完整度）选择一个执行。

---

## 七、前端交互设计

### 7.1 组件结构

```
HomePage
  ├── SearchBox        # 搜索输入框（复用现有）
  ├── SearchResult      # 结果展示区
  │     ├── NumberCard  # type=number 时
  │     ├── TableResult # type=table 时
  │     └── TextAnswer  # type=text 时
  └── ErrorCard         # type=error 时
```

### 7.2 状态流转

```
idle → loading → success / error
```

### 7.3 结果渲染

**type=number**：大字数字 + 单位 + 标签说明

```
┌─────────────────────┐
│    1,234,567        │  ← 大字
│    元               │  ← 单位
│  Q1 销售额          │  ← 语义说明
└─────────────────────┘
```

**type=table**：简单表格，最多显示 10 行

**type=text**：AI 自然语言回答直接展示

### 7.4 示例问题更新

首页示例问题改为贴合数据问答场景：

```tsx
const examplePrompts = [
  'Q1 销售额是多少',
  '3月各区域订单数量',
  '销售额最高的前5个产品',
];
```

---

## 八.API 前端对接

### 8.1 新建 API 模块

`frontend/src/api/search.ts`

```ts
export async function askQuestion(question: string): Promise<SearchAnswer> {
  const res = await fetch(`${API_BASE}/api/search/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '查询失败');
  }
  return res.json();
}
```

### 8.2 类型定义

```ts
export interface SearchAnswer {
  answer: string;
  type: 'number' | 'table' | 'text' | 'error';
  data?: {
    value?: number;
    unit?: string;
    formatted?: string;
    rows?: Record<string, unknown>[];
    columns?: string[];
  };
  datasource?: { id: number; name: string };
  query?: QueryIntent;
  confidence?: number;
  reason?: string;
  detail?: string;
}
```

---

## 九、路由注册

`backend/app/main.py` 新增：

```python
from app.api import search
app.include_router(search.router, prefix="/api/search", tags=["首页搜索"])
```

---

## 十、安全考虑

1. **只读查询**：后端仅调用 `query-datasource`（SELECT），不暴露写操作
2. **权限校验**：用户需有 `tableau` 权限才能使用搜索功能
3. **结果校验**：LLM 构造的 filter 由后端校验合法性后再执行
4. **查询超时**：MCP 调用设置 30s 超时

---

## 十一、已确认事项

1. **多数据源冲突** → 让用户从候选数据源中选择（返回 `AMBIGUOUS` 类型，前端展示选择器）
2. **VizQL filter 类型** → V1 支持全部类型：`SET`、`QUANTITATIVE_NUMERICAL`、`MATCH`、`DATE`、`QUANTITATIVE_DATE`、`TOP`、`LASTN`、`NEXTN`
3. **结果缓存** → V1 不加
4. **LLM model** → 复用后台已有的 LLM 配置（`/api/llm/config`）
