# LLM 能力层技术规格书

| 属性 | 值 |
|------|-----|
| 版本 | v1.2 |
| 日期 | 2026-04-27 |
| 状态 | 草稿 |
| 作者 | Mulan BI Platform Team |
| 模块路径 | `backend/services/llm/` |
| API 前缀 | `/api/llm` |

---

## 目录

1. [概述](#1-概述)
2. [数据模型](#2-数据模型)
3. [API 设计](#3-api-设计)
4. [业务逻辑](#4-业务逻辑)
5. [Prompt 模板](#5-prompt-模板)
6. [错误码](#6-错误码)
7. [安全](#7-安全)
8. [集成点](#8-集成点)
9. [时序图](#9-时序图)
10. [测试策略](#10-测试策略)
11. [开放问题](#11-开放问题)
12. [开发交付约束](#12-开发交付约束)

---

## 1. 概述

LLM 能力层为 Mulan BI Platform 提供大语言模型调用基础设施，支持 OpenAI 兼容接口和 Anthropic 接口两种供应商协议。该层的核心职责包括：

- **配置管理**：管理员通过 API 配置 LLM 供应商、模型、密钥等参数，API Key 加密存储
- **统一调用**：通过单例服务对上层业务屏蔽供应商差异，提供统一的 `complete()` 异步接口
- **业务能力**：基于 Prompt 模板实现资产摘要生成、报表深度解读、自然语言转查询等场景

### 架构定位

```
┌─────────────────────────────────────────────┐
│              前端 (React)                     │
├─────────────────────────────────────────────┤
│          API 路由层 (FastAPI)                 │
│   app/api/llm.py    app/api/tableau.py       │
├─────────────────────────────────────────────┤
│            LLM 能力层 (本规格书)               │
│   services/llm/service.py                    │
│   services/llm/models.py                     │
│   services/llm/prompts.py                    │
├─────────────────────────────────────────────┤
│          基础设施层                            │
│   CryptoHelper (Fernet)    PostgreSQL 16      │
│   AsyncOpenAI / AsyncAnthropic SDK           │
└─────────────────────────────────────────────┘
```

### 1.3 关联文档

| 文档 | 路径 | 关系 |
|------|------|------|
| 统一错误码标准 | docs/specs/01-error-codes-standard.md | 上游：LLM_001~005 错误码定义 |
| 数据源管理 | docs/specs/05-datasource-management-spec.md | 上游：加密基础设施（CryptoHelper） |
| 语义 LLM 集成 | docs/specs/12-semantic-llm-spec.md | 下游：`complete_for_semantic()` 消费者 |
| 自然语言查询 | docs/specs/14-nl-to-query-spec.md | 下游：`one_pass_llm()` + `purpose="nlq"` |
| 知识库 & RAG | docs/specs/17-knowledge-base-spec.md | 下游：`generate_embedding()` 消费者 |

---

## 2. 数据模型

### 2.1 表定义：`ai_llm_configs`

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|------|------|------|--------|------|
| `id` | `INTEGER` | PK, 自增 | — | 主键 |
| `provider` | `VARCHAR(32)` | NOT NULL | `'openai'` | 供应商标识：`openai` / `anthropic` |
| `base_url` | `VARCHAR(512)` | NOT NULL | `'https://api.openai.com/v1'` | API 端点地址 |
| `api_key_encrypted` | `VARCHAR(512)` | NOT NULL | — | 加密后的 API Key（PBKDF2+Fernet） |
| `model` | `VARCHAR(128)` | NOT NULL | `'gpt-4o-mini'` | 模型名称 |
| `temperature` | `FLOAT` | — | `0.7` | 生成温度 |
| `max_tokens` | `INTEGER` | — | `1024` | 最大生成 token 数 |
| `is_active` | `BOOLEAN` | — | `false` | 是否启用 |
| `created_at` | `DATETIME` | — | `now()` | 创建时间 |
| `updated_at` | `DATETIME` | — | `now()` (onupdate) | 更新时间 |
| `api_key_updated_at` | `DATETIME` | NULL | — | API Key 最近更新时间（仅 key 变更时更新） |
| `purpose` | `VARCHAR(50)` | NOT NULL | `'default'` | **[P1 新增]** 用途标识，见下方 Purpose 枚举 |
| `display_name` | `VARCHAR(100)` | NULL | — | **[P1 新增]** 配置的展示名称（管理页面用） |
| `priority` | `INTEGER` | NOT NULL | `0` | **[P1 新增]** 同一 purpose 内的优先级，越大越优先 |

### 2.1.1 Purpose 枚举（P1 新增）

| purpose 值 | 含义 | 典型场景 |
|-----------|------|---------|
| `default` | 通用配置，其他 purpose 的兜底 | 资产摘要、报表解读等一般性 LLM 调用 |
| `nlq` | 自然语言转查询专用 | NL-to-Query One-Pass LLM（`one_pass_llm()` 使用） |
| `semantic` | 语义生成专用 | 字段语义 AI 生成（`complete_for_semantic()` 使用） |
| `embedding` | 向量化专用 | 文本 embedding 生成 |

### 2.2 设计说明

- **[P1 改造] 多配置模式**：表中可存放多条记录，每条有独立的 `purpose`。原"单配置全局"模式（`get_config()` 取第一条、`save_config()` 做 upsert）已被下方 Purpose 路由机制替代，旧接口仅用于向后兼容。
- **Purpose 路由规则**：`get_config(purpose)` 先查 `purpose=<purpose> AND is_active=True`，按 `priority DESC` 取第一条；找不到则 fallback 到 `purpose='default' AND is_active=True`；仍找不到返回 `None`。
- `api_key_encrypted` 存储格式为 `base64(salt[16B] + fernet_ciphertext)`，解密需要环境变量中的主密钥
- `to_dict()` 方法**不返回** `api_key_encrypted`，仅返回 `has_api_key: bool` 标识；同时返回 `purpose`、`display_name`、`priority`、`api_key_preview`（脱敏后的 key 片段，如 `sk-*******3f2a`）、`api_key_updated_at` 字段
- `display_name` 唯一性在应用层强制（创建/更新时查重，409 冲突），非数据库约束

### 2.3 ORM 模型

```python
class LLMConfig(Base):
    __tablename__ = "ai_llm_configs"
    # ... 见 backend/services/llm/models.py
```

### 2.4 表定义：`nlq_query_logs`

NL-to-Query 查询审计日志表，fire-and-forget 写入（失败不阻塞主流程）。

| 列名 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `INTEGER` | PK, 自增 | 主键 |
| `user_id` | `INTEGER` | NOT NULL | 发起查询的用户 ID |
| `question` | `TEXT` | NOT NULL | 用户自然语言问题 |
| `intent` | `VARCHAR(50)` | NULL | 识别的意图类型 |
| `datasource_luid` | `VARCHAR(100)` | NULL | 目标数据源 LUID |
| `vizql_json` | `JSONB` | NULL | 生成的 VizQL 查询 JSON |
| `response_type` | `VARCHAR(50)` | NULL | 响应类型 |
| `execution_time_ms` | `INTEGER` | NULL | 执行耗时（毫秒） |
| `error_code` | `VARCHAR(50)` | NULL | 错误码（成功时为空） |
| `created_at` | `DATETIME` | NOT NULL | 创建时间 |

**索引**：`(user_id, created_at)` 复合索引、`datasource_luid` 单列索引。

**辅助函数**：`log_nlq_query()` 封装 fire-and-forget 写入逻辑。

### 2.5 数据库访问层

`LLMConfigDatabase` 类封装所有数据库操作，使用中央 `SessionLocal` 获取连接：

| 方法 | 说明 |
|------|------|
| `get_config(purpose="default") -> Optional[LLMConfig]` | **[P1 改造]** 按 purpose 路由获取配置（先查目标 purpose，fallback 到 `default`） |
| `save_config(provider, base_url, api_key_encrypted, model, temperature, max_tokens, is_active)` | upsert 兼容接口（向后兼容，写入 `purpose='default'` 的记录） |
| `delete_config()` | 删除全部配置 |

---

## 3. API 设计

### 3.1 端点总览

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| `GET` | `/api/llm/config` | admin | 获取 LLM 配置（兼容旧接口，取第一条 default） |
| `POST` | `/api/llm/config` | admin | 创建/更新 LLM 配置（兼容旧接口，upsert default） |
| `DELETE` | `/api/llm/config` | admin | ~~删除全部 LLM 配置~~ **已废弃，返回 410 Gone** |
| `POST` | `/api/llm/config/test` | admin | 测试 LLM 连接（支持 ad-hoc 和已保存配置两种模式） |
| `GET` | `/api/llm/assets/{asset_id}/summary` | user+ | 获取资产 AI 摘要 |
| `GET` | `/api/llm/assets/{asset_id}/explain` | user+ | 获取资产深度解读（5 维分析） |
| `GET` | `/api/llm/configs` | admin | **[P1 新增]** 列出所有 LLM 配置 |
| `POST` | `/api/llm/configs` | admin | **[P1 新增]** 创建新 LLM 配置（含 purpose/display_name/priority） |
| `PUT` | `/api/llm/configs/{id}` | admin | **[P1 新增]** 更新指定 LLM 配置 |
| `DELETE` | `/api/llm/configs/{id}` | admin | **[P1 新增]** 删除指定 LLM 配置（HTTP 204） |
| `PATCH` | `/api/llm/configs/{id}/active` | admin | **[P1 新增]** 切换指定配置启用状态（保护最后一条 default 活跃配置） |

### 3.2 GET /api/llm/config

获取当前 LLM 配置（不含 API Key 明文）。

**请求**：无参数

**响应 200**（已配置）：
```json
{
  "config": {
    "id": 1,
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 1024,
    "is_active": true,
    "has_api_key": true,
    "created_at": "2026-04-01T10:00:00",
    "updated_at": "2026-04-01T12:00:00"
  }
}
```

**响应 200**（未配置）：
```json
{
  "config": null,
  "message": "未配置 LLM"
}
```

### 3.3 POST /api/llm/config

创建或更新 LLM 配置。API Key 在写入前加密。

**请求体** `LLMConfigRequest`：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `provider` | `string` | 否 | `"openai"` | 供应商 |
| `base_url` | `string` | 否 | `"https://api.openai.com/v1"` | API 端点 |
| `api_key` | `string` | 是 | — | API Key（明文，传输后立即加密） |
| `model` | `string` | 否 | `"gpt-4o-mini"` | 模型名称 |
| `temperature` | `float` | 否 | `0.7` | 温度 |
| `max_tokens` | `int` | 否 | `1024` | 最大 token |
| `is_active` | `bool` | 否 | `true` | 是否启用 |

**响应 200**：
```json
{
  "message": "LLM 配置保存成功"
}
```

**副作用**：记录操作日志（`llm_config_update`），包含操作人、provider、model。

### 3.4 DELETE /api/llm/config（已废弃）

此端点已废弃，调用返回 HTTP 410 Gone。功能性删除请使用 `DELETE /api/llm/configs/{id}`。

**响应 410**：
```json
{
  "error_code": "LLM_001",
  "message": "此接口已废弃，请使用 DELETE /api/llm/configs/{id}"
}
```

### 3.5 POST /api/llm/config/test

测试 LLM 连接。支持两种模式：

- **Ad-hoc 模式**：请求体中同时提供 `base_url`、`api_key`、`model`，直接使用内联参数测试，不读取数据库
- **已保存配置模式**：请求体仅含 `prompt`（或 `config_id`），从数据库加载配置后测试

**请求体** `LLMTestRequest`：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `prompt` | `string` | 否 | `"Hello, respond with 'OK'"` | 测试 prompt |
| `base_url` | `string` | 否 | — | Ad-hoc 模式：API 端点 |
| `api_key` | `string` | 否 | — | Ad-hoc 模式：API Key 明文 |
| `model` | `string` | 否 | — | Ad-hoc 模式：模型名称 |
| `provider` | `string` | 否 | `"openai"` | Ad-hoc 模式：供应商 |
| `config_id` | `int` | 否 | — | 指定配置 ID（已保存配置模式） |

**响应 200**（成功）：
```json
{
  "success": true,
  "message": "OK",
  "response_model": "gpt-4o-mini",
  "latency_ms": 850,
  "tokens_used": 12
}
```

**响应 200**（失败）：
```json
{
  "success": false,
  "message": "LLM 未配置，请联系管理员",
  "error_code": "HTTP_401"
}
```

### 3.6 多配置 CRUD 接口（P1 新增）

#### GET /api/llm/configs

列出所有 LLM 配置（按 `priority DESC, id` 排序），不含 API Key 明文。

**响应 200**：
```json
{
  "configs": [
    {
      "id": 1,
      "provider": "openai",
      "model": "gpt-4o-mini",
      "purpose": "default",
      "display_name": "通用配置",
      "priority": 0,
      "is_active": true,
      "has_api_key": true
    }
  ]
}
```

#### POST /api/llm/configs（创建，HTTP 201）

**请求体** `LLMConfigCreateRequest`：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `provider` | `string` | 否 | `"openai"` | 供应商 |
| `base_url` | `string` | 否 | `"https://api.openai.com/v1"` | API 端点 |
| `api_key` | `string` | 是 | — | API Key 明文 |
| `model` | `string` | 否 | `"gpt-4o-mini"` | 模型名 |
| `temperature` | `float` | 否 | `0.7` | 温度 |
| `max_tokens` | `int` | 否 | `1024` | 最大 token |
| `is_active` | `bool` | 否 | `true` | 是否启用 |
| `purpose` | `string` | 否 | `"default"` | 用途：`default`/`nlq`/`semantic`/`embedding` |
| `display_name` | `string` | 否 | `null` | 展示名称 |
| `priority` | `int` | 否 | `0` | 优先级（越大越优先） |

**响应 201**：`{"config": {...}}`（包含新建配置的完整字段）

#### PUT /api/llm/configs/{id}（更新）

字段同上，所有字段可选，`api_key` 为空字符串时不更新已有密钥。

**响应 200**：`{"config": {...}}`

#### DELETE /api/llm/configs/{id}（删除，HTTP 204）

**保护规则**：若目标配置是 `purpose=default` 且 `is_active=True`，且已无其他同 purpose 活跃配置，则拒绝删除（400）。

#### PATCH /api/llm/configs/{id}/active（启停切换）

切换指定配置的 `is_active` 状态。

**请求体** `ActiveToggleRequest`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `is_active` | `bool` | 是 | 目标状态 |

**保护规则**：不可禁用最后一条 `purpose=default` 的活跃配置。

**响应 200**：`{"config": {...}}`

### 3.7 GET /api/llm/assets/{asset_id}/summary

获取指定 Tableau 资产的 AI 摘要。支持缓存（1 小时），可强制刷新。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `asset_id` | `int` | 资产 ID |

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `refresh` | `bool` | `false` | 是否强制重新生成 |

**权限校验**：
- 需登录用户（`get_current_user`）
- IDOR 防护：非 admin 用户只能访问自己连接下的资产

**响应 200**（命中缓存）：
```json
{
  "summary": "该报表展示了...",
  "cached": true
}
```

**响应 200**（新生成）：
```json
{
  "summary": "该报表展示了...",
  "cached": false
}
```

**响应 200**（生成失败）：
```json
{
  "summary": null,
  "error": "LLM 未配置，请联系管理员"
}
```

**响应 404**：资产不存在或已删除

**响应 403**：无权访问该资产

### 3.8 GET /api/llm/assets/{asset_id}/explain

获取指定 Tableau 资产的深度解读（5 维分析）。支持缓存（1 小时），可强制刷新。

**路径参数**：同 3.7

**查询参数**：同 3.7（`refresh` 参数）

**权限校验**：同 3.7（IDOR 防护）

**响应 200**：
```json
{
  "explanation": "## 报表概述\n该报表展示了...\n\n## 关键指标\n...",
  "cached": true
}
```

**Prompt**：使用 `ASSET_EXPLAIN_TEMPLATE`（见 Section 5.2），输出 5 维结构化分析。

---

## 4. 业务逻辑

### 4.1 LLMService 单例模式

```python
class LLMService:
    _instance = None    # 类级单例引用
    _clients: dict = {} # 客户端缓存池
```

- 使用 `__new__` 实现单例，首次创建时初始化 `LLMConfigDatabase` 实例和客户端缓存
- 模块级导出 `llm_service = LLMService()` 供其他模块直接引用

### 4.2 客户端缓存策略

客户端通过 `_TimedClientCache` 类管理，TTL 为 5 分钟（300 秒），按复合 key 缓存，避免重复创建连接：

**缓存 Key 格式**：`{provider}:{base_url}:{model}:{hash(api_key)}`

| Provider | 缓存 Key 示例 | SDK 类 |
|----------|---------------|--------|
| `openai` | `openai:https://api.openai.com/v1:gpt-4o-mini:hash` | `openai.AsyncOpenAI` |
| `anthropic` | `anthropic:https://api.minimaxi.com/anthropic:claude-3:hash` | `anthropic.AsyncAnthropic` |

- TTL 过期后自动驱逐，下次调用重建客户端
- 配置变更（api_key/model 等）会产生新 key，旧客户端在 TTL 后自动清理

SDK 采用延迟导入（`from openai import AsyncOpenAI`），仅在首次调用对应供应商时加载。

### 4.3 complete() 系列核心调用流程

`LLMService` 提供三个主要调用接口，均支持 `purpose` 参数路由到对应配置：

| 方法 | purpose 默认值 | 特殊约束 | 用途 |
|------|--------------|---------|------|
| `complete(prompt, system, timeout, purpose)` | `"default"` | 继承配置的 temperature | 通用 LLM 调用 |
| `complete_with_temp(prompt, system, timeout, temperature, purpose)` | `"default"` | temperature 硬编码，不继承配置 | NL-to-Query One-Pass |
| `complete_for_semantic(prompt, system, timeout, purpose)` | `"default"` | temperature=0.1，OpenAI 额外开启 `response_format=json_object` | 语义生成、One-Pass LLM |

`one_pass_llm()` 调用 `complete_for_semantic(..., purpose="nlq")`，路由到 `purpose=nlq` 的 LLM 配置。

**`complete()` 流程**：

```
complete(prompt, system, timeout=15, purpose="default")
  │
  ├── 1. 加载配置 (_load_config(purpose))
  │     └── purpose 路由：先查目标 purpose，fallback 到 default
  │     └── 校验 config 存在 / is_active / api_key_encrypted 非空
  │
  ├── 2. 解密 API Key (_decrypt)
  │     └── 失败则返回 {"error": "LLM 认证配置错误"}
  │
  └── 3. 路由到供应商
        ├── provider == "anthropic" → _anthropic_complete()
        └── 其他 → _openai_complete()
```

### 4.4 OpenAI 调用逻辑

- 构造 `messages` 数组：可选 system message + user message
- 调用 `client.chat.completions.create()`，传入 model / temperature / max_tokens
- 从 `response.choices[0].message.content` 提取文本

### 4.5 Anthropic 调用逻辑

- `base_url` 为空时回退到 `https://api.minimaxi.com/anthropic`（MiniMax 代理）
- system prompt 嵌入 user message 中：`<system>{system}</system>\n\n{prompt}`
- 调用 `client.messages.create()`
- 响应处理需兼容 MiniMax 的 ThinkingBlock：过滤出 `TextBlock` 类型，取第一个

### 4.6 资产摘要生成流程

```
generate_asset_summary(asset)
  │
  ├── 1. 用 ASSET_SUMMARY_TEMPLATE 填充资产元数据
  │     (asset_type, name, project_name, description, owner_name)
  │
  ├── 2. 调用 complete(prompt, system="你是一个数据分析助手。", timeout=15)
  │
  └── 3. 返回 {"summary": content} 或 {"error": msg}
```

### 4.7 缓存策略（资产摘要）

- 缓存存储在 `tableau_assets` 表的 `ai_summary` 和 `ai_summary_generated_at` 字段
- 缓存有效期：**1 小时**（3600 秒）
- `refresh=true` 查询参数可强制跳过缓存
- 生成失败时将错误信息写入 `ai_summary_error` 字段

### 4.8 Embedding 生成

`LLMService` 提供文本向量化能力，通过 MiniMax `embo-01` 模型实现：

| 方法 | 说明 |
|------|------|
| `generate_embedding_minimax(texts: List[str])` | 批量 embedding，调用 `https://api.minimaxi.com/v1/embeddings`，返回 `List[List[float]]` |
| `generate_embedding(text: str)` | 单文本便捷封装，内部调用 `generate_embedding_minimax([text])`，返回 `{"embedding": List[float]}` |

- 需要 `purpose="embedding"` 的 LLM 配置（从中获取 API Key）
- 未配置时返回 `{"error": "..."}` 而非抛异常

---

## 5. Prompt 模板

### 5.1 ASSET_SUMMARY_TEMPLATE -- 资产摘要

**用途**：为 Tableau 资产生成 100 字以内的中文摘要

**变量**：

| 变量 | 来源 | 说明 |
|------|------|------|
| `{asset_type}` | `TableauAsset.asset_type` | 资产类型（workbook/view/datasource） |
| `{name}` | `TableauAsset.name` | 资产名称 |
| `{project_name}` | `TableauAsset.project_name` | 所属项目 |
| `{description}` | `TableauAsset.description` | 资产描述 |
| `{owner_name}` | `TableauAsset.owner_name` | 所有者 |

**System Prompt**：`"你是一个数据分析助手。"`

**输出要求**：直接输出摘要文本，无额外说明，100 字以内。

### 5.2 ASSET_EXPLAIN_TEMPLATE -- 报表深度解读

**用途**：面向业务用户的 5 维报表解读

**变量**：

| 变量 | 说明 |
|------|------|
| `{name}` | 报表名称 |
| `{asset_type}` | 资产类型 |
| `{project_name}` | 所属项目 |
| `{description}` | 描述 |
| `{owner_name}` | 所有者 |
| `{parent_workbook_info}` | 所属工作簿信息 |
| `{datasources}` | 关联数据源列表 |
| `{field_metadata}` | 数据源字段元数据（含计算字段公式） |

**输出结构**（5 个维度）：

1. **报表概述** -- 2-3 句话说明核心用途
2. **关键指标** -- 主要指标及其业务含义
3. **维度说明** -- 主要分析维度
4. **数据关注点** -- 使用时的注意要点
5. **适用场景** -- 推荐使用场景

**约束**：面向非技术人员，使用中文，解释业务含义而非技术实现。

### 5.3 NL_TO_QUERY_TEMPLATE -- 自然语言转 VizQL 查询

**用途**：将用户自然语言问题转换为 Tableau VizQL 查询 JSON

**变量**：

| 变量 | 说明 |
|------|------|
| `{datasource_luid}` | 数据源 LUID |
| `{datasource_name}` | 数据源名称 |
| `{fields_with_types}` | 字段列表及类型信息 |
| `{term_mappings}` | 业务术语到字段的映射关系 |
| `{question}` | 用户自然语言问题 |

**输出格式**：
```json
{
  "fields": [
    {"fieldCaption": "字段显示名", "function": "SUM"},
    {"fieldCaption": "维度字段"}
  ],
  "filters": []
}
```

**规则**：
- 度量字段必须指定 `function`（SUM/AVG/COUNT/COUNTD/MIN/MAX 等）
- 维度字段不需要 `function`
- 排序使用 `sortDirection`（ASC/DESC）和 `sortPriority`
- 限制条数使用 TOP 类型 filter
- 仅输出 JSON，不要其他内容

---

## 6. 错误码

| 错误码 | HTTP 状态码 | 触发条件 | 错误消息 |
|--------|------------|----------|----------|
| `LLM_001` | 404 | `get_config()` 返回空 / `is_active=false` / `api_key_encrypted` 为空 | 无可用 LLM 配置 |
| `LLM_002` | 400 | API Key 解密失败（密钥不匹配或数据损坏） | API Key 无效 |
| `LLM_003` | 502 | LLM 供应商请求超时（默认 15 秒） | LLM 供应商超时 |
| `LLM_004` | 502 | LLM 供应商 API 返回错误（鉴权失败、余额不足等） | LLM 供应商不可用 |
| `LLM_005` | 502 | Anthropic 响应中无 TextBlock（MiniMax ThinkingBlock 兼容问题） | LLM 响应解析失败 |

### 当前实现映射

| 场景 | 代码位置 | 返回值 |
|------|---------|--------|
| 无配置 | `complete()` L60-61 | `{"error": "LLM 未配置，请联系管理员"}` |
| 解密失败 | `complete()` L65-67 | `{"error": "LLM 认证配置错误"}` |
| Anthropic 调用异常 | `_anthropic_complete()` L110-114 | `{"error": "Anthropic API 错误: {msg}"}` |
| 无 TextBlock | `_anthropic_complete()` L119-121 | `{"error": "MiniMax 响应格式异常：未找到文本内容"}` |
| 通用异常 | `complete()` L74-76 | `{"error": "{exception_str}"}` |

---

## 7. 安全

### 7.1 API Key 加密存储

- **算法**：PBKDF2-SHA256 密钥派生 + Fernet 对称加密
- **实现**：`CryptoHelper`（`services/common/crypto.py`）
- **流程**：
  1. 生成 16 字节随机 salt
  2. 使用 PBKDF2（100,000 次迭代）从主密钥 + salt 派生 32 字节密钥
  3. 用派生密钥创建 Fernet 实例加密明文
  4. 存储格式：`base64(salt[16B] + fernet_ciphertext)`
- **主密钥**：从环境变量 `LLM_ENCRYPTION_KEY` 读取，回退到 `DATASOURCE_ENCRYPTION_KEY`
- **启动校验**：两个环境变量均未设置时，服务启动直接抛 `RuntimeError`

### 7.2 访问控制

| 操作 | 权限要求 | 校验函数 |
|------|---------|---------|
| 配置管理（CRUD + 测试） | `admin` | `get_current_admin(request)` |
| 资产摘要查询 | 已登录用户 | `get_current_user(request)` |
| 资产摘要 IDOR 防护 | 非 admin 用户只能访问自己连接下的资产 | `conn.owner_id != user["id"]` |

### 7.3 数据隔离

- LLM 调用**仅发送元数据**（资产名称、描述、字段名等），**不发送实际数据值**
- Prompt 模板中的变量均来自 Tableau 资产的元信息字段，不包含行级数据

### 7.4 XSS 防护

- LLM 返回的文本内容在前端渲染前**必须进行 HTML 转义**
- 后端 `complete()` 返回原始文本，转义责任在前端展示层

### 7.5 API Key 传输

- API Key 明文仅在 `POST /api/llm/config` 请求体中传输一次
- `GET /api/llm/config` 响应中**不包含** API Key，仅返回 `has_api_key: true/false`

---

## 8. 集成点

### 8.1 上游依赖

| 依赖 | 说明 | 文件 |
|------|------|------|
| `CryptoHelper` | API Key 加密/解密 | `services/common/crypto.py` |
| `SessionLocal` / `Base` | 数据库连接与 ORM 基类 | `app/core/database.py` |
| `get_current_admin` / `get_current_user` | 权限校验 | `app/core/dependencies.py` |
| `openai` SDK | OpenAI 兼容接口调用 | PyPI: `openai` |
| `anthropic` SDK | Anthropic 接口调用 | PyPI: `anthropic` |

### 8.2 下游消费者

| 消费者 | 调用方式 | purpose 参数 | 说明 |
|--------|---------|------------|------|
| Tableau 资产管理 | `llm_service.generate_asset_summary(asset)` | `"default"` | 资产列表页 AI 摘要 |
| 报表解读 | `llm_service.generate_asset_explanation(asset)` | `"default"` | 5 维深度解读 |
| 自然语言查询（One-Pass） | `llm_service.complete_for_semantic(..., purpose="nlq")` | `"nlq"` | NL-to-VizQL，使用 nlq 专用配置 |
| 语义 AI 生成 | `llm_service.complete_for_semantic(...)` | `"default"` | 字段语义批量生成 |
| 知识库 Embedding | `llm_service.generate_embedding(text)` | `"embedding"` | 文本向量化（MiniMax embo-01） |
| LLM 配置管理前端 | 通过 `/api/llm/configs` 系列 API | — | 管理员多配置管理页面 |

### 8.3 操作日志

配置更新操作写入操作日志，日志字段：

| 字段 | 值 |
|------|-----|
| `operation_type` | `llm_config_update` |
| `target` | `llm_config` |
| `status` | `success` |
| `operator` | 当前 admin 用户名 |
| `detail` | `更新 LLM 配置: provider={}, model={}` |

---

## 9. 时序图

### 9.1 资产摘要生成流程

```
用户           前端            API 路由           LLMService         LLM 供应商
 │              │                │                  │                   │
 │─查看资产────>│                │                  │                   │
 │              │─GET summary──>│                  │                   │
 │              │               │─权限校验────────>│                   │
 │              │               │─检查缓存         │                   │
 │              │               │  (< 1h 命中)     │                   │
 │              │               │  ──返回缓存──>   │                   │
 │              │               │                  │                   │
 │              │               │  (缓存过期)       │                   │
 │              │               │─generate_asset──>│                   │
 │              │               │                  │─加载配置           │
 │              │               │                  │─解密 API Key       │
 │              │               │                  │─填充 Prompt        │
 │              │               │                  │─complete()────────>│
 │              │               │                  │<─────响应──────────│
 │              │               │<─{"summary":...}─│                   │
 │              │               │─更新缓存          │                   │
 │              │<──JSON 响应───│                  │                   │
 │<──渲染摘要───│               │                  │                   │
```

### 9.2 LLM 配置保存流程

```
管理员          前端            API 路由           CryptoHelper       数据库
 │              │                │                  │                  │
 │─填写配置────>│                │                  │                  │
 │              │─POST config──>│                  │                  │
 │              │               │─admin 权限校验    │                  │
 │              │               │─_encrypt(key)───>│                  │
 │              │               │<─encrypted_key───│                  │
 │              │               │─save_config()────────────────────>  │
 │              │               │<──────────commit──────────────────  │
 │              │               │─记录操作日志       │                  │
 │              │<──200 OK──────│                  │                  │
 │<──保存成功───│               │                  │                  │
```

---

## 10. 测试策略

### 10.1 单元测试

| 测试项 | 测试内容 | Mock 对象 |
|--------|---------|-----------|
| 加密/解密往返 | `_encrypt(key)` 后 `_decrypt` 恢复原文 | 无 |
| 配置 CRUD | `save_config` / `get_config` / `delete_config` | 测试数据库 |
| `to_dict()` 安全性 | 返回值不包含 `api_key_encrypted` | 无 |
| `complete()` 无配置 | 返回 `{"error": "LLM 未配置..."}` | `LLMConfigDatabase` |
| `complete()` 解密失败 | 返回 `{"error": "LLM 认证配置错误"}` | `_decrypt` 抛异常 |
| OpenAI 调用路径 | 正确构造 messages 并返回 content | `AsyncOpenAI` |
| Anthropic 调用路径 | system prompt 嵌入方式、TextBlock 提取 | `AsyncAnthropic` |
| Anthropic 无 TextBlock | 返回解析失败错误 | `AsyncAnthropic` 返回非 TextBlock |

### 10.2 集成测试

| 测试项 | 说明 |
|--------|------|
| API 权限校验 | 非 admin 调用配置接口返回 403 |
| IDOR 防护 | 用户 A 无法访问用户 B 连接下的资产摘要 |
| 缓存机制 | 1 小时内重复请求命中缓存，`refresh=true` 跳过缓存 |
| 端到端连接测试 | `POST /config/test` 使用真实 LLM 端点验证连通性 |

### 10.3 安全测试

| 测试项 | 说明 |
|--------|------|
| API Key 不泄露 | GET 响应中无 `api_key_encrypted`，日志中无明文密钥 |
| 环境变量缺失 | 两个加密密钥均未设置时，服务启动失败（RuntimeError） |
| XSS 注入 | LLM 返回含 HTML/JS 的内容时，前端正确转义 |

### 10.4 验收标准

- [ ] `LLMService` 单例模式正常工作，`_TimedClientCache` TTL 5 分钟
- [ ] `get_config(purpose)` 实现两级路由（目标 purpose → default fallback）
- [ ] `complete()` / `complete_for_semantic()` / `complete_with_temp()` 三个入口均支持 `purpose` 参数
- [ ] `generate_embedding()` / `generate_embedding_minimax()` 调用 MiniMax embedding API
- [ ] `DELETE /api/llm/config` 返回 410 Gone
- [ ] `PATCH /configs/{id}/active` 保护最后一条 default 活跃配置
- [ ] `GET /assets/{id}/explain` 返回 5 维深度解读
- [ ] `to_dict()` 包含 `api_key_preview`、`api_key_updated_at`，不包含 `api_key_encrypted`
- [ ] `display_name` 重复时返回 409
- [ ] `nlq_query_logs` 表 fire-and-forget 写入，失败不阻塞主流程
- [ ] `cd backend && pytest tests/ -x -q` 全通过

### 10.5 Mock 与测试约束

- **`LLMService` 单例**：测试中需要 `patch('services.llm.service.LLMService._instance', None)` 重置单例，否则跨测试污染。或用 `patch.object(llm_service, '_load_config')` 绕过单例直接 mock 配置加载
- **`_TimedClientCache`**：测试客户端缓存过期时，mock `time.time()` 推进 300+ 秒，不要用 `sleep()`
- **Async SDK Mock**：`AsyncOpenAI` / `AsyncAnthropic` 的 mock 必须返回 `asyncio.coroutine` 或使用 `AsyncMock`；直接 `MagicMock` 会导致 `await` 失败
- **Fire-and-forget 审计**：`log_nlq_query()` 在独立 session 中写入；测试时 mock `SessionLocal` 避免写入测试数据库，或验证 `warning` 级别日志在写入失败时触发
- **CryptoHelper**：加密/解密测试需设置 `LLM_ENCRYPTION_KEY` 环境变量；测试用固定值 `test-key-32-chars-long-enough!!!` 即可

---

## 11. 开放问题

| 编号 | 问题 | 优先级 | 状态 |
|------|------|--------|------|
| OI-01 | ~~当前为单配置模式，未来是否需要支持多供应商同时启用并按场景路由？~~ | P2 | **已解决（P1 改造：多配置 purpose 路由）** |
| OI-02 | ~~客户端缓存（`_clients` 字典）无过期机制，配置变更后旧客户端不会失效~~ | P1 | **已解决（`_TimedClientCache` 5 分钟 TTL，key 含 model+hash(api_key)）** |
| OI-03 | ~~`ASSET_EXPLAIN_TEMPLATE` 和 `NL_TO_QUERY_TEMPLATE` 已定义但尚无对应 API 端点~~ | P2 | **已解决（`GET /assets/{id}/explain` 已实现；NL-to-Query 在 `nlq_service.py` 中消费）** |
| OI-04 | Anthropic system prompt 通过 `<system>` 标签嵌入 user message，非官方推荐方式，后续应改用 SDK 原生 system 参数 | P2 | 待优化 |
| OI-05 | `complete()` 返回错误时使用 `{"error": str}` 而非抛 HTTP 异常，上层需逐个判断，考虑统一为异常机制 | P2 | 待讨论 |
| OI-06 | 资产摘要缓存有效期硬编码为 3600 秒，是否需要可配置化？ | P3 | 待讨论 |
| OI-07 | ~~NL-to-VizQL 场景的 Prompt 输出为 JSON，需增加 JSON 解析校验和 Schema 验证~~ | P1 | **已解决（`nlq_service.py` 实现了 Schema 校验 + 重试机制）** |
| OI-08 | 操作日志记录失败时仅 warning 级别日志，不阻塞主流程，是否需要更强的保障？ | P3 | 待讨论 |

---

## 12. 开发交付约束

### 架构红线（违反 = PR 拒绝）

1. **services/ 层无 Web 框架依赖** — `services/llm/service.py` 不得 import FastAPI/Request
2. **SQL 安全性** — 所有数据库查询使用 SQLAlchemy ORM 或 `text()` + 参数绑定
3. **禁止 `os.environ`** — 配置通过 `get_settings` 或 `CryptoHelper` 获取
4. **API Key 不可泄露** — `to_dict()` 禁止返回 `api_key_encrypted`，日志禁止打印明文 key
5. **单例线程安全** — `LLMService.__new__` 的单例模式不得被破坏，`_TimedClientCache` 必须模块级实例化

### SPEC 08 强制检查清单

- [ ] `_TimedClientCache` key 格式为 `{provider}:{base_url}:{model}:{hash(api_key)}`，不是旧的 `{provider}:{base_url}`
- [ ] `DELETE /api/llm/config` 返回 410 Gone，不是 200/204
- [ ] `PATCH /configs/{id}/active` 存在且保护最后一条 default 配置
- [ ] `GET /assets/{id}/explain` 存在且使用 `ASSET_EXPLAIN_TEMPLATE`
- [ ] `generate_embedding_minimax()` 调用 MiniMax `embo-01`，使用 `purpose="embedding"` 配置
- [ ] `NlqQueryLog` 表存在，`log_nlq_query()` fire-and-forget
- [ ] `to_dict()` 返回 `api_key_preview` 和 `api_key_updated_at`
- [ ] `display_name` 查重在 API 层实现（409 冲突），非数据库 UNIQUE 约束

### 验证命令

```bash
# 后端
cd backend && python3 -m py_compile services/llm/service.py
cd backend && python3 -m py_compile services/llm/models.py
cd backend && python3 -m py_compile app/api/llm.py
cd backend && pytest tests/ -x -q

# 检查 services 层无 Web 框架依赖
grep -r "from fastapi\|from starlette" backend/services/llm/ && echo "FAIL" || echo "PASS"

# 检查 API Key 不泄露
grep -r "api_key_encrypted" backend/services/llm/service.py | grep -v "_decrypt\|_encrypt\|encrypted" && echo "FAIL: key leakage" || echo "PASS"
```

### 正确 / 错误示范

```python
# ❌ 错误：旧的缓存 key 格式
cache_key = f"{provider}:{base_url}"

# ✅ 正确：包含 model 和 api_key hash
cache_key = f"{provider}:{base_url}:{model}:{hash(api_key)}"

# ❌ 错误：to_dict() 返回加密密钥
def to_dict(self):
    return {"api_key_encrypted": self.api_key_encrypted, ...}

# ✅ 正确：返回脱敏预览
def to_dict(self):
    return {"has_api_key": bool(self.api_key_encrypted),
            "api_key_preview": self._build_api_key_preview(), ...}

# ❌ 错误：DELETE /config 返回 200
@router.delete("/config")
async def delete_config():
    db.delete_config()
    return {"message": "已删除"}

# ✅ 正确：返回 410 Gone 表示废弃
@router.delete("/config")
async def delete_config():
    raise HTTPException(status_code=410, detail="此接口已废弃")
```

---

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-04-27 | v1.2 | Spec 合规补齐：新增 Section 1.3 关联文档、Section 12 开发交付约束；补入 `PATCH /configs/{id}/active`、`GET /assets/{id}/explain`、`generate_embedding()`/`generate_embedding_minimax()` 接口；新增 `NlqQueryLog` 表定义、`api_key_updated_at`/`api_key_preview` 字段；`DELETE /config` 标记为 410 Gone 废弃；更新客户端缓存为 `_TimedClientCache`（5 分钟 TTL + 复合 key）；新增 10.4 验收标准、10.5 Mock 约束；关闭 OI-02/OI-03。 |
| 2026-04-16 | v1.1 | P1 改造：支持多配置 purpose 路由。`ai_llm_configs` 表新增 `purpose`、`display_name`、`priority` 字段；`get_config(purpose)` 实现 purpose → default 两级路由；新增 `GET/POST /api/llm/configs`、`PUT/DELETE /api/llm/configs/{id}` 四个 admin-only CRUD 端点；`complete_for_semantic()` NLQ 调用传 `purpose="nlq"`；客户端缓存改为带 TTL 的 `_TimedClientCache`（5 分钟过期）。 |
| 2026-04-03 | v1.0 | 初始版本，单配置全局模式 |
