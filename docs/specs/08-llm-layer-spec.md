# LLM 能力层技术规格书

| 属性 | 值 |
|------|-----|
| 版本 | v1.0 |
| 日期 | 2026-04-03 |
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

### 2.2 设计说明

- 当前为**单配置模式**：`get_config()` 取表中第一条记录，`save_config()` 采用 upsert 逻辑（有则更新，无则插入）
- `api_key_encrypted` 存储格式为 `base64(salt[16B] + fernet_ciphertext)`，解密需要环境变量中的主密钥
- `to_dict()` 方法**不返回** `api_key_encrypted`，仅返回 `has_api_key: bool` 标识

### 2.3 ORM 模型

```python
class LLMConfig(Base):
    __tablename__ = "ai_llm_configs"
    # ... 见 backend/services/llm/models.py
```

### 2.4 数据库访问层

`LLMConfigDatabase` 类封装所有数据库操作，使用中央 `SessionLocal` 获取连接：

| 方法 | 说明 |
|------|------|
| `get_config() -> Optional[LLMConfig]` | 获取当前配置（取第一条） |
| `save_config(provider, base_url, api_key_encrypted, model, temperature, max_tokens, is_active)` | upsert 配置 |
| `delete_config()` | 删除全部配置 |

---

## 3. API 设计

### 3.1 端点总览

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| `GET` | `/api/llm/config` | admin | 获取 LLM 配置 |
| `POST` | `/api/llm/config` | admin | 创建/更新 LLM 配置 |
| `DELETE` | `/api/llm/config` | admin | 删除 LLM 配置 |
| `POST` | `/api/llm/config/test` | admin | 测试 LLM 连接 |
| `GET` | `/api/llm/assets/{asset_id}/summary` | user+ | 获取资产 AI 摘要 |

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

### 3.4 DELETE /api/llm/config

删除全部 LLM 配置。

**响应 200**：
```json
{
  "message": "LLM 配置已删除"
}
```

### 3.5 POST /api/llm/config/test

使用当前已保存的配置测试 LLM 连接。

**请求体** `LLMTestRequest`：

| 字段 | 类型 | 必填 | 默认值 |
|------|------|------|--------|
| `prompt` | `string` | 否 | `"Hello, respond with 'OK'"` |

**响应 200**（成功）：
```json
{
  "success": true,
  "message": "OK"
}
```

**响应 200**（失败）：
```json
{
  "success": false,
  "message": "LLM 未配置，请联系管理员"
}
```

### 3.6 GET /api/llm/assets/{asset_id}/summary

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

客户端按 `{provider}:{base_url}` 为 key 进行缓存，避免重复创建连接：

| Provider | 缓存 Key 格式 | SDK 类 |
|----------|---------------|--------|
| `openai` | `openai:{base_url}` | `openai.AsyncOpenAI` |
| `anthropic` | `anthropic:{base_url}` | `anthropic.AsyncAnthropic` |

SDK 采用延迟导入（`from openai import AsyncOpenAI`），仅在首次调用对应供应商时加载。

### 4.3 complete() 核心调用流程

```
complete(prompt, system, timeout=15)
  │
  ├── 1. 加载配置 (_load_config)
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

| 消费者 | 调用方式 | 说明 |
|--------|---------|------|
| Tableau 资产管理 | `llm_service.generate_asset_summary(asset)` | 资产列表页 AI 摘要 |
| 报表解读（规划中） | `llm_service.complete(ASSET_EXPLAIN_TEMPLATE, ...)` | 5 维深度解读 |
| 自然语言查询（规划中） | `llm_service.complete(NL_TO_QUERY_TEMPLATE, ...)` | NL-to-VizQL |
| LLM 配置管理前端 | 通过 `/api/llm/config*` API | 管理员配置页面 |

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

---

## 11. 开放问题

| 编号 | 问题 | 优先级 | 状态 |
|------|------|--------|------|
| OI-01 | 当前为单配置模式，未来是否需要支持多供应商同时启用并按场景路由？ | P2 | 待讨论 |
| OI-02 | 客户端缓存（`_clients` 字典）无过期机制，配置变更后旧客户端不会失效，需考虑缓存刷新策略 | P1 | 待解决 |
| OI-03 | `ASSET_EXPLAIN_TEMPLATE` 和 `NL_TO_QUERY_TEMPLATE` 已定义但尚无对应 API 端点，需规划接入时机 | P2 | 待规划 |
| OI-04 | Anthropic system prompt 通过 `<system>` 标签嵌入 user message，非官方推荐方式，后续应改用 SDK 原生 system 参数 | P2 | 待优化 |
| OI-05 | `complete()` 返回错误时使用 `{"error": str}` 而非抛 HTTP 异常，上层需逐个判断，考虑统一为异常机制 | P2 | 待讨论 |
| OI-06 | 资产摘要缓存有效期硬编码为 3600 秒，是否需要可配置化？ | P3 | 待讨论 |
| OI-07 | NL-to-VizQL 场景的 Prompt 输出为 JSON，需增加 JSON 解析校验和 Schema 验证 | P1 | 待实现 |
| OI-08 | 操作日志记录失败时仅 warning 级别日志，不阻塞主流程，是否需要更强的保障？ | P3 | 待讨论 |
