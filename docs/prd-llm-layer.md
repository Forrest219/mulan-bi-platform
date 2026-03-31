# Mulan BI Platform — LLM 能力层 PRD

> **版本：** v0.1（草案）
> **日期：** 2026-03-31
> **状态：** 待评审

---

## 1. 背景与目标

### 1.1 为什么需要 LLM 能力层

Mulan 当前已具备：
- 用户认证与权限体系 ✅
- 数据源管理与连接 ✅
- Tableau MCP 资产同步 ✅
- DDL 规范检查 ✅

**缺口：** 用户在浏览 Tableau 报表时，无法快速理解报表内容、指标口径、数据来源。传统方案是人工维护文档，成本高且易过时。

**机会：** 通过 LLM 对 Tableau 资产生成 AI 摘要，让用户在报表详情页直接获取解释，降低认知成本。

### 1.2 本阶段目标

让 Mulan 具备基础的 LLM 调用能力，并在 **Tableau 场景** 下落地 1~2 个可见 AI 功能。

三个核心原则：
| 原则 | 含义 |
|------|------|
| **能用** | 配置简单，接入即可用，不依赖复杂调优 |
| **可控** | 所有 LLM 调用经后端代理，敏感数据不外泄，支持审计 |
| **可演进** | 标准接口设计，后续可扩展 MCP / Agent / 自然语言检索 |

### 1.3 上线后应支持的功能

1. **统一 LLM Provider 配置** — 后台配置一个 LLM Provider（API Key + Base URL + Model）
2. **后端标准化 LLM 请求** — 通过统一服务发起 LLM 调用，支持流式响应
3. **Tableau 资产生成摘要** — 对 Workbooks / Views / DataSources 生成基础描述
4. **报表详情页 AI 解读** — 用户在报表详情页点击「AI 解读」获取 LLM 生成的内容解释
5. **标准扩展接口** — 为后续 NLP 搜索、MCP、Agent 扩展预留标准调用入口

---

## 2. 功能详细设计

### 2.1 LLM 配置管理（P0）

**目标：** 后台可配置 LLM Provider，支持 OpenAI API 兼容格式。

#### 配置项

| 字段 | 类型 | 说明 |
|------|------|------|
| `provider` | string | 提供商标识，`openai` / `anthropic`（后续扩展） |
| `base_url` | string | API Base URL，如 `https://api.openai.com/v1` |
| `api_key` | string | API Key（加密存储） |
| `model` | string | 模型名称，如 `gpt-4o-mini` |
| `temperature` | float | 采样温度，默认 `0.7` |
| `max_tokens` | int | 最大输出 token，默认 `1024` |
| `is_active` | bool | 是否启用 |

#### API 设计

```
GET    /api/llm/config          # 获取当前配置（不返回 api_key 明文）
POST   /api/llm/config           # 创建/更新配置
POST   /api/llm/config/test      # 测试连接（发送一个简单 prompt 验证）
DELETE /api/llm/config           # 删除配置（恢复默认状态）
```

#### 权限

- 仅 `admin` 可配置 LLM
- 配置变更记录操作日志

#### 加密存储

`api_key` 使用 Fernet 加密（复用 `DATASOURCE_ENCRYPTION_KEY`），解密仅在后端内存中使用，不暴露给前端。

### 2.2 标准化 LLM 调用服务（P0）

**目标：** 后端提供统一的 LLM 调用接口，支持同步和流式两种模式。

#### 服务接口

```python
class LLMService:
    def __init__(self):
        self._config = None  # 从数据库加载配置

    def complete(self, prompt: str, system: str = None, stream: bool = False) -> dict | Generator:
        """同步或流式生成"""

    def generate_asset_summary(self, asset: TableauAsset) -> str:
        """对 Tableau 资产生成摘要"""

    def explain_asset(self, asset: TableauAsset, context: str = None) -> str:
        """对报表/视图生成 AI 解读"""
```

#### Prompt 模板

**资产摘要模板：**
```
你是一个数据分析助手。请根据以下 Tableau 资产信息，生成一段简洁的中文摘要（100字以内）。

资产类型：{asset_type}
名称：{name}
项目：{project_name}
描述：{description}
所有者：{owner_name}

请直接输出摘要内容，无需额外说明。
```

**AI 解读模板：**
```
你是一个 BI 报表解读专家。请根据以下报表信息，用通俗易懂的语言向业务用户解释这个报表。

## 报表基本信息
名称：{name}
项目：{project_name}
描述：{description}

## 关联数据源
{datasources}

请用 2~3 句话解释这个报表的用途和关键指标，要求：
1. 面向非技术业务人员
2. 说明主要指标含义
3. 指出可能的数据关注点
```

### 2.3 Tableau 资产 AI 摘要（P0）

**目标：** 在资产详情页展示 AI 生成的摘要。

#### 数据流

```
用户点击「AI 解读」按钮
    → 前端调用 GET /api/llm/assets/{id}/summary
    → 后端从 DB 获取资产信息
    → 后端调用 LLMService.generate_asset_summary()
    → LLM 生成摘要（带 30 秒超时保护）
    → 前端展示摘要文本
```

#### API 设计

```
GET /api/llm/assets/{asset_id}/summary
Response: { "summary": "这是一个销售报表..." }
```

- 已登录用户可调用
- 同一资产 1 小时内不重复生成（缓存 `asset_summary` 字段，刷新由用户手动触发）
- LLM 调用失败返回 `{ "summary": null, "error": "LLM 服务暂不可用" }`

#### 字段变更

`TableauAsset` 模型新增字段：
| 字段 | 类型 | 说明 |
|------|------|------|
| `ai_summary` | TEXT | AI 生成的摘要 |
| `ai_summary_generated_at` | DATETIME | 生成时间 |
| `ai_summary_error` | TEXT | 最近一次生成错误信息 |

### 2.4 报表详情页 AI 解读按钮（P1）

**目标：** 在 Tableau 资产详情页增加「AI 解读」按钮，点击后加载 LLM 生成的内容解释。

#### 前端交互

1. 资产详情页新增「AI 解读」Tab 或按钮
2. 点击后：
   - 显示 loading 状态（"正在生成解读..."）
   - 调用 API 获取摘要/解读
   - 展示结果（支持 markdown 渲染）
3. 解读结果支持刷新

#### UI 示例

```
┌─ 资产详情 ──────────────────────────────┐
│  名称：月度销售看板                      │
│  项目：销售分析                          │
│  所有者：张三                           │
│                                        │
│  [基本信息] [关联数据源] [AI 解读]       │
│                                        │
│  ┌─ AI 解读 ──────────────────────┐    │
│  │ 📊 这是一个销售分析报表，主要展示    │    │
│  │    月度销售额、订单量和客单价等     │    │
│  │    核心指标。通过日期筛选器可以      │    │
│  │    查看不同时间维度的数据变化。     │    │
│  │                                │    │
│  │  [刷新解读]                      │    │
│  └────────────────────────────────┘    │
└────────────────────────────────────────┘
```

### 2.5 标准扩展接口预留（P2 规划）

为后续扩展预留标准接口：

```python
# 统一 LLM 调用接口
POST /api/llm/chat
Body: { "prompt": "...", "system": "...", "stream": false }
Response: { "content": "..." } | 流式 text/event-stream

# 自然语言检索（未来）
POST /api/llm/search
Body: { "query": "最近销售情况如何", "datasources": [1, 2] }
Response: { "sql": "SELECT ...", "explanation": "..." }
```

---

## 3. 技术架构

### 3.1 模块结构

```
src/
├── llm/
│   ├── __init__.py
│   ├── config.py           # LLM 配置读写
│   ├── models.py           # SQLAlchemy 模型（LLM 配置实体）
│   ├── service.py          # LLM 调用服务（同步/流式）
│   └── prompts.py          # Prompt 模板管理
│
backend/app/api/
│   ├── llm.py              # LLM 配置与调用 API（P0）
│   └── tableau.py           # 修改：/assets/{id}/summary 端点
│
frontend/src/
│   ├── api/llm.ts          # LLM 前端 API 调用
│   └── pages/tableau/asset-detail/page.tsx  # 修改：AI 解读 Tab
```

### 3.2 数据模型

```python
# src/llm/models.py
class LLMConfig(SQLAlchemyModel):
    __tablename__ = "llm_configs"

    id: int
    provider: str          # "openai"
    base_url: str
    api_key_encrypted: str
    model: str
    temperature: float
    max_tokens: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
```

### 3.3 LLM 调用流程

```
Frontend                    Backend                      LLM Provider
   │                           │                              │
   │  GET /llm/assets/{id}/summary   │                              │
   │──────────────────────────>│                              │
   │                           │  GET asset from DB            │
   │                           │──────────────────────────────>│
   │                           │<──────────────────────────────│
   │                           │                               │
   │                           │  Build prompt with template   │
   │                           │                               │
   │                           │  POST /chat/completions       │
   │                           │──────────────────────────────>│
   │                           │<──────────────────────────────│
   │                           │  (stream or full response)     │
   │                           │                               │
   │  { "summary": "..." }     │                               │
   │<──────────────────────────│                               │
```

### 3.4 错误处理与降级

| 场景 | 处理方式 |
|------|----------|
| LLM 配置未设置 | 返回 `{ "error": "LLM 未配置，请联系管理员" }` |
| API Key 无效 | 记录日志，返回 `{ "error": "LLM 认证失败" }` |
| LLM 调用超时（30s） | 记录日志，返回 `{ "error": "生成超时，请重试" }` |
| LLM 服务不可用 | 返回 `{ "error": "LLM 服务暂不可用" }` |
| 网络错误 | 返回 `{ "error": "网络错误，请检查配置" }` |

---

## 4. 前端设计

### 4.1 LLM 配置页（admin）

路径：`/admin/llm`

- 表单：Provider / Base URL / API Key / Model / Temperature / Max Tokens
- 测试按钮：输入测试 prompt，实时显示 LLM 返回
- 保存后显示成功提示

### 4.2 资产详情页 AI 解读 Tab

路径：`/tableau/assets/{id}`

- 「AI 解读」Tab 默认收起（点击加载）
- 加载中显示骨架屏或 spinner
- 成功后展示 Markdown 格式解读文本
- 支持刷新（有确认提示，避免误操作）

---

## 5. 安全考虑

| 风险 | 缓解措施 |
|------|----------|
| API Key 明文传输 | 全程 HTTPS，Key 加密存储在后端 |
| 敏感数据泄露给 LLM | 资产数据仅传名称/描述，不传具体数据值 |
| LLM 生成内容注入 | 对输出做基本 HTML 转义再渲染 |
| 未授权访问 LLM API | 所有端点需要登录态，admin 才能改配置 |
| LLM 调用耗尽配额 | 设置单次调用 max_tokens 上限，记录调用次数 |

---

## 6. 配置变更记录

所有 LLM 配置变更写入操作日志：

```json
{
  "operation_type": "llm_config_update",
  "operator": "admin",
  "detail": "更新 model: gpt-4o-mini → gpt-4o",
  "timestamp": "2026-04-01T10:00:00Z"
}
```

---

## 7. 测试计划

### 功能测试

| 用例 | 步骤 | 预期结果 |
|------|------|----------|
| LLM 配置-正常 | 配置有效 API Key，点击测试 | 返回测试成功 |
| LLM 配置-无效 Key | 配置错误 Key，点击测试 | 返回认证失败 |
| 资产摘要-已配置 | 有 LLM 配置，访问资产详情页 AI 解读 | 显示摘要 |
| 资产摘要-未配置 | 无 LLM 配置，访问 AI 解读 | 提示配置 LLM |
| 资产摘要-超时 | LLM 服务慢，30s 无响应 | 显示超时错误 |

### 回归测试

| 用例 | 步骤 | 预期结果 |
|------|------|----------|
| 登录状态 | 访问 LLM 配置页 | 未登录跳转登录页 |
| 权限控制 | 非 admin 访问 LLM 配置页 | 返回 403 |

---

## 8. 实施计划

### Phase 1：LLM 基础设施（P0）

1. 新建 `src/llm/` 模块（models, service, prompts）
2. 新建 `backend/app/api/llm.py`（配置管理 API）
3. 后端 LLM 调用服务实现（同步）
4. `GET /api/llm/config` 和 `POST /api/llm/config/test`

### Phase 2：Tableau AI 摘要（P0）

1. 修改 `TableauAsset` 模型，添加 `ai_summary` 等字段
2. 新建 `GET /api/llm/assets/{id}/summary` 端点
3. 前端资产详情页增加「AI 解读」Tab

### Phase 3：LLM 配置页 + 完善（P1）

1. 前端 `/admin/llm` 配置页
2. 流式响应支持（SSE）
3. Prompt 模板可配置化

### Phase 4：扩展接口预留（P2）

1. 统一 `POST /api/llm/chat` 接口
2. 自然语言检索接口（Text-to-SQL，远期）

---

## 9. 依赖关系

```
前置依赖：
- ✅ 用户认证与权限体系（Phase 1 完成）
- ✅ 数据源管理（Phase 2 完成）
- ✅ Tableau MCP 集成（Phase 1 完成）

本阶段新增依赖：
- ❌ 无（所有能力自包含）
```

---

## 10. 本期不做清单

以下功能在本阶段**明确不做**，避免范围蔓延：

| 不做项 | 说明 |
|--------|------|
| **多模型路由** | 暂不支持多个 provider 自动切换，本期只配置一个 LLM Provider |
| **智能体编排** | 不做多轮 Agent、工具链规划，本期仅做单次 LLM 调用 |
| **实时对话助手** | 不做 Chat UI，不做多轮会话，AI 解读是单向生成非对话 |
| **向量数据库/RAG** | 暂不接知识库检索系统，不做语义搜索 |
| **Prompt 管理平台** | 暂不做复杂 prompt 后台配置，Prompt 模板以内置为主 |
| **成本治理体系** | 暂不做细粒度 token 计费看板，不统计调用成本 |
| **Tableau 自动操作** | 不做"修改/发布/刷新"类 Tableau 动作，只做读取和解读 |
| **流式响应（Phase 1）** | Phase 1 仅实现同步返回，流式 SSE 放 Phase 3 |

---

## 11. 附录

### A. 参考资料

- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- [LangChain LCEL](https://python.langchain.com/docs/concepts/lcel/)（架构参考，非强制引入）

### B. 术语表

| 术语 | 说明 |
|------|------|
| LLM | Large Language Model，大语言模型 |
| Prompt | 给 LLM 的输入文本 |
| System Prompt | 系统级指令，定义 LLM 行为角色 |
| Streaming | 流式输出，边生成边返回 |
| AI 摘要 | LLM 根据资产元数据自动生成的描述 |
| AI 解读 | LLM 对报表内容的业务含义解释 |
