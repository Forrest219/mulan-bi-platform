# Agentic Tableau MCP — 从"查数"到"控场"技术规格书

| 版本 | 日期 | 状态 | Owner |
|------|------|------|-------|
| v0.1 | 2026-04-19 | Draft |  |
| v0.2 | 2026-04-19 | Draft（补充 System Prompt + Phase 验收标准） |  |

---

## 目录

1. [概述](#1-概述)
2. [架构影响评估](#2-架构影响评估)
3. [技术可行性分析](#3-技术可行性分析)
4. [新增 MCP Tools 清单](#4-新增-mcp-tools-清单)
5. [System Prompt 设计框架](#5-system-prompt-设计框架)
6. [分阶段路线图](#6-分阶段路线图)
7. [风险评估](#7-风险评估)
8. [现有架构复用地图](#8-现有架构复用地图)
9. [Spec 变更记录](#9-spec-变更记录)

---

## 1. 概述

### 1.1 背景与战略定位

Mulan BI Platform 的 Tableau MCP 当前定位为"只读查询代理"——通过 REST API 读取 Tableau 元数据，返回给 Agent 做分析。这一模式在"查数"场景已跑通，但无法支撑**"控场"**场景：即通过自然语言指令直接操控 Tableau 实体（修改字段语义、变更看板过滤器、发布语义层更新）。

本 spec 定义了从"查数"到"控场"的完整升级路径，涵盖：
- 自动化字段映射（模糊字段名 → 精确 LUID）
- 意图驱动的看板更新（对话修改 Filter/Parameter）
- 面向 Tableau 动作生成的 System Prompt 工程

### 1.2 核心范式变化

> **结论先行**：这是一次范式跃迁，不是功能叠加。

| 维度 | 当前（只读） | 目标（读写） |
|------|------------|------------|
| Semantic Layer 角色 | 语义存储（查上下文） | 推理大脑（字段匹配 + 意图验证 + 操作回写） |
| MCP Server 角色 | 只读查询代理 | 读写执行器 |
| 前端交互模式 | 用户输入 → 展示结果 | 用户发指令 → 展示执行计划 → 确认 → 逐步执行 |
| 工具设计原则 | 查询优先 | 能用查询确认，不直接写；能用 URL 解决，不改数据库 |

### 1.3 与现有 spec 的关系

- **依赖 spec 07**（Tableau MCP V1）：现有 20 个 tools 的实现基础
- **依赖 spec 09**（Semantic Maintenance）：语义层服务是"推理大脑"的载体
- **依赖 spec 13**（Tableau MCP V2 Direct Connect）：MCP Server 传输层架构
- **前置条件 spec 26 Phase 1**：MCP Debugger 面板是所有新 tools 的调试基础设施

---

## 2. 架构影响评估

### 2.1 目标架构

```
当前 Mulan（只读模式）
─────────────────────────────────────────────────────
用户问题
  → NLQ Service（意图分类 + VizQL 生成）
  → MCP Client → Tableau REST API → 返回数据
  → 语义层（存储字段语义，辅助 LLM 上下文）

目标 Mulan（读写控制模式）
─────────────────────────────────────────────────────
用户指令
  → Agent Orchestrator（多步规划 + 工具选择）
       ↓ 读：语义层作为推理依据
       ↓ 写：MCP 工具调用 Tableau 写操作 API
  → [字段匹配] → [意图验证] → [执行确认] → [结果回写]
```

### 2.2 各模块影响分级

| 模块 | 现状 | 新方向影响 | 需要改动 |
|------|------|-----------|---------|
| `tableau_mcp.py`（20 tools） | 全只读 | 需新增 12 个读写 tools | 中等，仅扩展 |
| `nlq_service.py` | VizQL 查询意图 | 需扩展为通用动作意图解析 | 较大，增加意图类型 |
| `semantic_maintenance`（语义层） | 存储 + 工作流 | 升级为推理引擎：字段匹配、相似度搜索 | 较大，新增推理接口 |
| `mcp_client.py`（客户端） | 仅 query/list | 需支持写操作透传 | 小 |
| 前端 Chat / Analytics | 只显示结果 | 需增加"确认操作"交互模式 | 中等 |
| 前端 Semantic Maintenance | 手动语义管理 | 可接入 Agent 自动匹配建议 | 中等 |

### 2.3 Semantic Layer 角色重新定义

**从：** 存储人工维护的字段语义，辅助 NLQ 上下文拼接

**到：** Agentic 推理大脑，完成三类任务：

```
① 字段识别（Field Resolution）
   模糊名称 → 精确字段 LUID
   "那个 region 字段" → tableau_field_id: "Region [Tableau Superstore]"
   依赖：synonyms_json + semantic_name + embedding 向量搜索

② 意图验证（Intent Grounding）
   Agent 计划执行某操作前，先查语义层确认"这个字段是 dimension 还是 measure"
   防止在 measure 字段上设 category filter 这类语义错误

③ 操作回写（Write-back Integration）
   执行 Tableau 写操作后，自动更新语义层记录（如修改了字段 caption，语义层同步标记）
```

**需要新增的语义层 API：**
- `POST /api/semantic-maintenance/fields/resolve` — 模糊名称 → 候选字段列表（带置信度）
- `GET /api/semantic-maintenance/fields/similar?q=<name>` — embedding 相似度搜索

### 2.4 前端交互模式变化

```
现在（查结果模式）：
  用户输入 → LLM 生成查询 → 展示表格/图表

目标（发指令模式）：
  用户指令 → Agent 分解步骤 → 展示"执行计划" → 用户确认 → 逐步执行 → 显示执行结果

关键 UI 变化：
  1. "确认执行"弹窗（写操作必须有人工确认节点）
  2. 执行步骤进度展示（Agent 正在做什么）
  3. 回滚入口（Tableau 操作出错后的恢复路径）
```

---

## 3. 技术可行性分析

### 3.1 Tableau Metadata API（GraphQL）接入

**接入方式（已有基础）：**
- Endpoint：`{tableau_server}/api/metadata/graphql`
- 认证：`x-tableau-auth: {token}`（与 REST API 共用 PAT 登录）
- 版本要求：Tableau Server 2019.3+ / Tableau Cloud

**当前已读取的字段**（仅 name/isHidden/description）：
```graphql
# 现有 GQL（不足）
{ publishedDatasourcesConnection(filter: {luid: "xxx"}) {
    nodes { luid name fields { name isHidden description } } } }
```

**需要扩展的字段**（支持字段匹配和意图验证）：
```graphql
# 目标 GQL（完整字段 schema）
{ publishedDatasourcesConnection(filter: {luid: "xxx"}) {
    nodes {
      luid name
      fields {
        name
        fullyQualifiedName   # 带表名的完整路径
        description
        dataType             # STRING / INTEGER / REAL / BOOLEAN / DATE
        role                 # DIMENSION / MEASURE
        dataCategory         # NOMINAL / ORDINAL / QUANTITATIVE
        isHidden
        formula              # 计算字段公式
        defaultAggregation   # SUM / AVG / COUNT 等
      }
    }
  } }
```

**速率限制：**
- Tableau Server：无文档化速率限制，实测并发建议 ≤ 5 QPS
- Tableau Cloud：100 RPM per user token
- 应对：在 `_tableau_signin` 的 token 上加缓存（现有 `mcp_client.py` 已有 session 管理，可复用）

### 3.2 Tableau 写操作 API 可行性

| 写操作目标 | API 方案 | 可行性 | 版本要求 | 限制 |
|-----------|---------|--------|---------|------|
| 修改工作簿视图过滤器（持久化） | Custom View API | ✅ 高 | Server 3.x+ | 仅创建自定义视图，不修改原始视图 |
| 修改 Parameter 值（持久化） | ❌ REST API 无此接口 | ⚠️ 低 | — | Parameters 不能通过 REST 直接修改 |
| 修改 Parameter 值（会话级） | VizQL RunCommand API | ⚠️ 中 | Server 2023.1+（beta） | 需要独立的 VizQL session，复杂度高 |
| 更新字段描述/Caption | REST API：`PUT /datasources/{id}` | ✅ 高 | Server 3.x+ | 已有语义层发布实现，直接复用 |
| 修改视图 URL filter（URL 参数） | 构造 filter URL 返回给用户 | ✅ 高 | 所有版本 | 临时性，用户需在浏览器打开 |
| 创建/更新 Custom View（含 filter 状态） | Custom View API | ✅ 高 | Server 3.18+ | 保存为用户个人视图，非全局修改 |

**实战路径选择（任务 2 看板过滤器修改）：**

```
方案 A（推荐）：构造 Filter URL
  → 生成带过滤条件的视图 URL
  → 返回给用户在浏览器中打开
  → 场景：临时查看特定过滤视角
  → 实现难度：低

方案 B（推荐）：Custom View
  → 调用 Custom View API 保存带 filter 的视图状态
  → 可以分享、复用
  → 实现难度：中

方案 C（探索性）：VizQL RunCommand
  → 真正的动态 filter/parameter 修改
  → 需要 Server 2023.1+，接口仍为 beta
  → 实现难度：高
  → 建议 Phase 3 验证
```

### 3.3 与现有封装的复用分析

**可直接复用（零改动）：**
- `_tableau_signin()` — 所有新 tools 共用认证
- `_pulse_headers()` — REST/Metadata API headers
- `_process_mcp_body()` — 新 tools 只需添加 elif 分支
- `publish_service.py` — publish-field-semantic tool 直接调用
- `semantic_maintenance/service.py` — 版本控制 + 状态机
- `mcp_client.py` session 管理 — 写操作 client 复用同一会话机制

**需要扩展（有改动，但不破坏现有）：**
- `_get_datasource_metadata()` 的 GraphQL query — 扩展字段列表
- `nlq_service.py` 的 `classify_intent()` — 增加 Tableau 写操作意图类型
- `semantic_retriever.py` — 增加向量相似度接口

---

## 4. 新增 MCP Tools 清单

当前 20 个 tools 全部为只读或查询操作。"控场"需要新增以下 12 个工具，完成后总计 **32 个**。

### 4.1 字段智能匹配工具（P1）

| Tool Name | 功能 | API 映射 |
|-----------|------|---------|
| `get-field-schema` | 获取数据源字段完整 schema（含 role/dataType/formula） | GraphQL Metadata API（扩展查询） |
| `resolve-field-name` | 模糊字段名 → 精确字段匹配（调用语义层向量搜索） | Mulan 内部 API：`/semantic-maintenance/fields/resolve` |
| `get-datasource-fields-summary` | 返回数据源所有字段的 name + role + dataType 摘要（用于 LLM 字段选择） | GraphQL Metadata API |

### 4.2 视图控制工具（P1-P2）

| Tool Name | 功能 | API 映射 |
|-----------|------|---------|
| `get-view-filter-url` | 生成带 filter 参数的视图 URL（临时过滤视角） | 构造 `{view_url}?vf_{field}={value}` |
| `create-custom-view` | 创建带指定 filter 状态的 Custom View | `POST /api/3.18/sites/{siteId}/customviews` |
| `update-custom-view` | 更新已有 Custom View 的 filter 状态 | `PUT /api/3.18/sites/{siteId}/customviews/{id}` |
| `list-custom-views-for-view` | 列出某视图下的所有 Custom View | `GET /api/3.18/sites/{siteId}/customviews` |

### 4.3 语义回写工具（P1）

| Tool Name | 功能 | API 映射 |
|-----------|------|---------|
| `update-field-caption` | 修改 Tableau 字段的显示名称（Caption） | `PUT /api/3.20/sites/{siteId}/datasources/{id}` + 语义层同步 |
| `update-field-description` | 修改 Tableau 字段的描述 | 同上 |
| `publish-field-semantic` | 将 Mulan 语义层的字段语义发布到 Tableau | 调用 `publish_service.py` |

### 4.4 参数控制工具（P2-P3）

| Tool Name | 功能 | API 映射 |
|-----------|------|---------|
| `get-workbook-parameters` | 获取工作簿的所有 Parameter 定义 | GraphQL Metadata API |
| `set-parameter-via-url` | 构造带 Parameter 值的视图 URL | `{view_url}?{param_name}={value}` |
| `run-vizql-command` | 通过 VizQL RunCommand 执行参数修改 | `POST /api/v1/vizql-data-service/run-command`（Phase 3，Server 2023.1+ beta） |

---

## 5. System Prompt 设计框架

### 5.1 Mulan Tableau Agent 系统提示词结构

```
┌─────────────────────────────────────────────────────────────┐
│  SECTION 1: Agent 角色与边界定义                             │
│  "你是 Mulan BI 平台的 Tableau 操控 Agent。你的能力边界是…" │
├─────────────────────────────────────────────────────────────┤
│  SECTION 2: 工具目录（分组说明）                             │
│  [查询类] [字段类] [视图控制类] [写操作类]                   │
├─────────────────────────────────────────────────────────────┤
│  SECTION 3: 工具调用策略                                     │
│  "当用户说 X 时，优先用工具 A，然后 B，最后 C"              │
├─────────────────────────────────────────────────────────────┤
│  SECTION 4: 写操作安全规则                                   │
│  "所有写操作执行前必须先展示执行计划并等待确认"              │
├─────────────────────────────────────────────────────────────┤
│  SECTION 5: 错误处理协议                                     │
│  "遇到认证失败/API 超时/字段找不到时如何降级"               │
├─────────────────────────────────────────────────────────────┤
│  SECTION 6: 上下文管理规则                                   │
│  "datasource_luid/workbook_id 缓存策略"                     │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 工具调用策略（Decision Tree）

```
用户指令类型判断：

① "查/列出/显示" → 只读工具链
   "列出数据源" → list-datasources
   "查这个字段" → get-datasource-metadata → (如果字段名模糊) resolve-field-name

② "把 X 字段映射/匹配" → 字段匹配链
   resolve-field-name(模糊名)
   → get-field-schema(候选字段 luid)
   → [呈现候选列表，等用户确认]
   → update-field-caption / publish-field-semantic

③ "改过滤器/显示X区域" → 视图控制链
   识别 filter 字段名 → resolve-field-name 确认字段
   → get-view-filter-url(构造 URL) → 返回链接
   [如需持久化] → create-custom-view

④ "查某数据源的数据" → 数据查询链
   list-datasources → 用户选择 → get-datasource-fields-summary
   → 用户指定字段 → query-datasource

规则：能用查询确认，不直接写；能用 URL 解决，不改数据库。
```

### 5.3 字段名模糊匹配提示词技巧

```
1. 先抽取"字段指代词"：
   "把 region 过滤器" → 抽取 ["region"]
   "那个叫'区域'的维度" → 抽取 ["区域", "region", "dimension"]

2. 多候选排序策略（由高到低）：
   - exact match on semantic_name
   - exact match on synonyms_json
   - embedding cosine similarity > 0.85
   - fuzzy string match > 80%

3. 低置信度时强制确认：
   "我找到 3 个可能匹配的字段，请确认：
    (A) Region [Orders 数据源] — 维度，字符串
    (B) Sub-Region [Orders 数据源] — 维度，字符串
    (C) 区域代码 [Sales 数据源] — 维度，整数"

4. 上下文继承：
   一次对话中确认过 datasource_luid 后，后续工具调用自动带入，
   用户无需重复指定。
```

### 5.4 错误处理协议

```
错误类型 → 处理方式：

API 认证失败(-32002)
  → 提示用户检查 Tableau 连接配置：/system/mcp-configs

字段未找到
  → 调用 resolve-field-name 做模糊匹配，列出候选
  → 如候选为空：提示用户先同步字段（sync 功能）

写操作失败（权限不足）
  → 明确告知操作被拒绝，说明需要 Tableau Server 上的管理员权限
  → 不自动重试写操作

API 超时
  → 重试一次，超时后提示用户手动刷新
  → 不缓存失败结果

版本不支持（Pulse/VizQL RunCommand）
  → 明确提示版本要求，建议替代方案（如用 URL filter 替代 RunCommand）
```

---

## 6. 分阶段路线图

### Phase 1：字段智能化（2-3 周）

**里程碑**：Agent 能准确识别模糊字段描述，自动完成字段→语义层映射，无需用户手动指定 LUID。

| 任务 | 涉及模块 | 验收标准 |
|------|---------|---------|
| 扩展 `get-datasource-metadata` GraphQL 查询（增加 role/dataType/formula） | `tableau_mcp.py` | GraphQL 返回完整字段 schema，字段匹配准确率 ≥ 85% |
| 新增 `get-field-schema` + `get-datasource-fields-summary` tools | `tableau_mcp.py` | tools/list 返回新工具，参数校验通过 |
| 新增 `/semantic-maintenance/fields/resolve` API | `backend/app/api/semantic_maintenance/fields.py` | 模糊查询返回候选列表，含置信度分数 |
| 新增 `resolve-field-name` MCP tool | `tableau_mcp.py` | 模糊字段名调用后返回 ≤ 5 个候选 |
| 编写 Tableau Agent System Prompt v1 | `services/llm/prompts.py` | 人工测试：模糊字段指令 → 正确匹配率 ≥ 80% |
| 集成到 NLQ/Chat 流程 | `nlq_service.py` | 意图分类包含 `field_resolution` 新类型 |

### Phase 2：视图控制（2-3 周）

**里程碑**：Agent 能通过对话生成 filter URL、创建 Custom View，完成"发指令改看板"的基本闭环。

| 任务 | 涉及模块 | 验收标准 |
|------|---------|---------|
| 新增 `get-view-filter-url` tool | `tableau_mcp.py` | 生成 URL 在浏览器中打开，filter 生效 |
| 新增 `create-custom-view` + `update-custom-view` tools | `tableau_mcp.py` | Custom View 创建成功，可从 Tableau 界面看到 |
| 新增 `list-custom-views-for-view` tool | `tableau_mcp.py` | 列出指定视图下所有 Custom View |
| 新增 `publish-field-semantic` MCP tool | `tableau_mcp.py` | 发布后 Tableau Desktop/Server 字段描述更新 |
| 新增 `update-field-caption/description` tools | `tableau_mcp.py` | 字段 Caption/Description 在 Tableau 中正确更新 |
| 前端：Chat 页增加"执行计划确认"交互 | `frontend/src/pages/` | 写操作前弹窗显示执行计划，用户可取消 |
| P3 MCP Debugger Phase 1 | 见 spec 26 P3 | Debugger 面板上线，可调试 Phase 1-2 所有 tools |

### Phase 3：意图驱动 + 高级控制（4-6 周）

**里程碑**：多轮对话完成复杂 Tableau 操控任务，System Prompt 成熟可复用，支持 VizQL RunCommand（Server 2023.1+）。

| 任务 | 涉及模块 | 验收标准 |
|------|---------|---------|
| 意图解析升级（通用 Tableau 动作意图） | `nlq_service.py` | 支持 filter/parameter/publish 三类意图分类 |
| `get-workbook-parameters` tool | `tableau_mcp.py` | 返回工作簿所有 Parameter 定义 |
| `run-vizql-command` tool（VizQL RunCommand beta） | `tableau_mcp.py` | Server 2023.1+ 下参数修改成功，旧版本返回明确错误 |
| `update-custom-view` 的 filter/parameter 持久化 | `tableau_mcp.py` | Custom View 保存后，重新打开 filter/parameter 保持 |
| 审计日志体系 | `mcp_debug_logs` + `tableau_action_logs` | 操作记录可查询，支持按用户/时间/工具筛选 |
| System Prompt v2（含多轮对话策略） | Prompt 文档 | 多轮复杂任务测试：Agent 能记忆上下文，≥ 3 轮对话不丢状态 |
| 语义层向量搜索优化 | `semantic_retriever.py` | 字段匹配准确率 ≥ 90% |

### 与 P3（MCP Debugger）的协同

```
P3 Debugger 是 Phase 1-3 的"调试基础设施"：
  - Phase 1 期间用 Debugger 验证新 tools 是否正确调用 GraphQL
  - Phase 2 期间用 Debugger 测试写操作（Custom View 创建）
  - Phase 3 期间 Debugger 加入审计日志查询，形成完整运维闭环

建议并行推进：P3 Phase 1（Debugger 核心面板）与 Agentic Phase 1（字段智能化）同步进行。
```

---

## 7. 风险评估

### 7.1 Tableau API 写操作安全风险

| 风险 | 严重程度 | 发生概率 | 应对 |
|------|---------|---------|------|
| 误修改生产字段 Caption，影响依赖该字段的报表 | 高 | 中 | 写操作前展示 diff + 强制人工确认；语义层保存历史版本，支持一键回滚 |
| Custom View 创建过多污染站点 | 低 | 高 | 限制 Agent 创建 Custom View 时必须带标签 `mulan-agent-generated`，定期清理 |
| PAT Token 被 revoke 后 MCP 服务中断 | 高 | 低 | `revoke-access-token` 工具加二次确认弹窗 + 操作后自动通知管理员 |
| VizQL RunCommand（beta）在 Server 版本不匹配时静默失败 | 中 | 中 | 调用前先检查 Server 版本，不满足时返回明确错误而非静默降级 |

### 7.2 LLM 意图解析准确率

| 风险 | 应对 |
|------|------|
| 字段名歧义（多个数据源都有 "Region" 字段） | 先 `list-datasources` 确认数据源范围，再限定搜索 scope |
| LLM 幻觉：生成不存在的字段名 | `resolve-field-name` 强制走向量匹配，找不到时必须告知而非猜测 |
| 用户指令模糊（"把数据刷新一下"）| 意图分类时设置"无法识别"分支，要求用户澄清，不自动猜测写操作 |

### 7.3 与 Tableau 官方 MCP 的竞合分析

| 维度 | 官方 Tableau MCP | Mulan MCP |
|------|-----------------|-----------|
| 定位 | 通用 Tableau 数据访问 | Mulan 语义治理 + Tableau 操控 |
| 工具范围 | 20 个只读/查询工具 | 32 个（含写操作 + 语义匹配） |
| 语义层 | 无 | 核心差异化：字段语义 + 向量匹配 |
| 企业权限 | 无内置权限控制 | 原生集成 Mulan 权限体系 |
| 审计 | 无 | `mcp_debug_logs` 全量审计 |
| **核心竞争优势** | Salesforce 官方背书 | **语义推理 + 读写一体 + 企业合规** |

**结论**：两者互补，不竞争。官方 MCP 适合外部 Agent 接入；Mulan MCP 是内部治理 + 操控平台，差异化在"语义大脑"和"写操作能力"。

---

## 8. 现有架构复用地图

```
可直接复用（零改动）：
  ✅ _tableau_signin()               — 所有新 tools 共用
  ✅ _pulse_headers()               — API headers 工具函数
  ✅ _process_mcp_body()            — 新 tools 只需添加 elif 分支
  ✅ publish_service.py             — publish-field-semantic tool 直接调用
  ✅ semantic_maintenance/service.py — 版本控制 + 状态机
  ✅ mcp_client.py session 管理      — 写操作 client 复用同一会话

需要扩展（有改动，但不破坏现有）：
  ⚡ _get_datasource_metadata() 的 GraphQL query — 增加字段
  ⚡ nlq_service.classify_intent() — 增加意图类型
  ⚡ semantic_retriever.py — 增加向量相似度接口

需要新建（纯增量）：
  ➕ /semantic-maintenance/fields/resolve API
  ➕ 12 个新 MCP tools（字段匹配 + 视图控制 + 写操作）
  ➕ Tableau Agent System Prompt 文档
  ➕ 前端"执行计划确认"组件
```

---

## 9. Spec 变更记录

| 版本 | 日期 | 变更内容 | Author |
|------|------|---------|--------|
| v0.1 | 2026-04-19 | 初始版本：Phase 1-3 规划 + 新增工具清单 |  |
| v0.2 | 2026-04-19 | 补充 System Prompt + Phase 验收标准 |  |
| v0.3 | 2026-04-19 | 补充 Tableau Server 版本要求（2025.3.4+），确认所有版本依赖均已满足 |  |

---

## 10. Tableau Server 版本要求

**版本：2025.3.4 及以上**

| 依赖功能 | 最低版本要求 | 满足情况 |
|----------|-------------|---------|
| create-custom-view / update-custom-view | Server 3.18+ | ✅ 满足（2025.3.4 > 3.18） |
| run-vizql-command | Server 2023.1+ beta | ✅ 满足 |
| Tableau Metadata API (GraphQL) | Server 2021.1+ | ✅ 满足 |
| VizQL Data Service (query-datasource) | Server 2020.2+ | ✅ 满足 |
