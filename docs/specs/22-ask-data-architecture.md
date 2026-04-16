# Spec 22: 首页问数架构 -- 多站点 MCP + 多 LLM + 端到端链路

> 状态: Draft
> 作者: Forrest
> 日期: 2026-04-16
> 依赖: Spec 14 (NL-to-Query Pipeline), Spec 21 (首页重构), Spec 13 (MCP V2 直连), Spec 08 (LLM 能力层)

---

## 1. 架构现状总结

### 1.1 当前端到端链路

```
用户 (AskBar.tsx)
  |
  | POST /api/search/query {question, datasource_luid?, connection_id?}
  v
search.py (API 层)
  |-- 权限校验 (analyst+)
  |-- 速率限制 (Redis, 20/min)
  |-- 意图分类 classify_intent() [规则快速路径]
  |-- 数据源路由 route_datasource() [多数据源评分]
  |-- 字段准备: sanitize_fields_for_llm + ContextAssembler + recall_fields
  |-- 术语表增强: glossary_service.get_matching_terms()
  |-- One-Pass LLM: one_pass_llm() -> {intent, confidence, vizql_json}
  |-- 查询执行: execute_query() -> TableauMCPClient.query_datasource()
  |-- 结果格式化: format_response()
  |-- 审计日志: log_nlq_query()
  v
前端 (SearchResult.tsx) 渲染结果
```

### 1.2 当前模块关系

```
+--------------------+     +-------------------+     +--------------------+
|  search.py (API)   |---->| nlq_service.py    |---->| mcp_client.py      |
|  路由 + 编排        |     | NLQ 流水线        |     | Tableau MCP 客户端  |
+--------------------+     +-------------------+     +--------------------+
        |                         |                          |
        |                         v                          |
        |                  +-------------+                   |
        |                  | service.py  |                   |
        |                  | LLMService  |                   |
        |                  | (单例/单配置)|                   |
        |                  +-------------+                   |
        v                         |                          v
+--------------------+     +------+------+     +--------------------+
| glossary_service   |     | models.py   |     | _MCPSessionState   |
| 术语表             |     | LLMConfig   |     | (进程级共享/单站点) |
+--------------------+     | (单条记录)  |     +--------------------+
                           +-------------+
```

### 1.3 关键瓶颈

| 维度 | 现状 | 问题 |
|------|------|------|
| MCP Session | 进程级共享单例 `_MCPSessionState` | 只能连一个 Tableau Site；`get_tableau_mcp_server_url()` 是 `@lru_cache` 单值 |
| LLM 配置 | `ai_llm_configs` 表取 `.first()`（单条记录） | 只能配置一个全局 LLM；不同场景无法使用不同模型 |
| MCP Server URL | 环境变量 `TABLEAU_MCP_SERVER_URL` 固定一个地址 | 多站点需要多个 MCP server 实例，每个有不同 URL |
| 前端 | AskBar 直接调用 `/api/search/query`，无对话上下文 | Spec 21 对话式重构尚未实现 |

---

## 2. 多站点 Tableau MCP 改造方案

### 2.1 设计目标

从"所有 connection_id 共享同一个 MCP server 进程"改为"每个 Tableau Site 对应独立的 MCP session"。

### 2.2 核心变更：per-site session 映射

**现状**（单例）：

```python
_mcp_session_state = _MCPSessionState()  # 进程级唯一
```

**改造后**（site 映射）：

```python
_mcp_session_states: Dict[str, _MCPSessionState] = {}  # key = site_key
_mcp_session_states_lock = threading.Lock()

def _get_site_key(connection: _CachedTableauConnection) -> str:
    """生成 site 唯一标识（server_url + site 组合）"""
    return f"{connection.server_url}|{connection.site}"

def _get_or_create_session_state(site_key: str) -> _MCPSessionState:
    with _mcp_session_states_lock:
        if site_key not in _mcp_session_states:
            _mcp_session_states[site_key] = _MCPSessionState()
        return _mcp_session_states[site_key]
```

### 2.3 MCP Server URL 路由策略

当前 `get_tableau_mcp_server_url()` 返回全局固定 URL。改造后需要按连接选择 MCP server URL：

**策略 A（推荐/P0）：使用 `tableau_connections.mcp_server_url` 字段**

该字段已存在于 `TableauConnection` 模型和 `_CachedTableauConnection` 中（Spec 13 预留）。当 `mcp_direct_enabled = True` 时，使用 `connection.mcp_server_url` 作为目标 MCP server 地址。

**改动点**：
- `_ensure_session()` 增加 `base_url` 参数（不再读全局 env）
- `_post_mcp()` 增加 `base_url` 参数
- `_build_headers()` 接收 `session_state` 参数（不再读全局 `_mcp_session_state`）
- 兜底逻辑：若 `connection.mcp_server_url` 为空，回退到全局 `TABLEAU_MCP_SERVER_URL`

**策略 B（P1 可选）：MCP server 进程管理器**

当管理员添加新 Tableau 连接时，自动为该 site 拉起独立 MCP server 进程。此方案复杂度高，P0 不实现。

### 2.4 改动文件清单

| 文件 | 变更类型 | 改动内容 | 复杂度 |
|------|---------|---------|--------|
| `backend/services/tableau/mcp_client.py` | 改造 | `_MCPSessionState` 改为 per-site 映射；`_ensure_session`/`_post_mcp`/`_build_headers` 接收 site 参数 | M |
| `backend/services/common/settings.py` | 改造 | `get_tableau_mcp_server_url()` 保留作为默认兜底 URL | S |
| `backend/services/tableau/models.py` | 不变 | `mcp_server_url` 字段已存在 | - |

### 2.5 session 生命周期变更

```
改造前:
  任何 connection_id → 全局 _mcp_session_state → 全局 MCP_SERVER_URL

改造后:
  connection_id → _CachedTableauConnection → site_key(server_url|site)
                → _mcp_session_states[site_key] → connection.mcp_server_url
```

### 2.6 并发安全

- 每个 `_MCPSessionState` 自带 `threading.Lock`（已有）
- `_mcp_session_states` 字典本身由 `_mcp_session_states_lock` 保护
- 同一 site 的多个 connection_id 共享同一 `_MCPSessionState`（正确行为：同 site 同 MCP server）

---

## 3. 多 LLM 供应商并存方案

### 3.1 设计目标

从"全局单 LLM 配置"改为"多配置并存，按场景/用途路由"。

### 3.2 数据库改造：`ai_llm_configs` 多记录支持

**现状**：表中只有 1 条记录，`LLMConfigDatabase.get_config()` 调用 `.first()`。

**改造后**：增加 `purpose` 字段区分用途，允许多条记录。

```sql
-- 新增列（DDL）
ALTER TABLE ai_llm_configs
  ADD COLUMN purpose VARCHAR(32) NOT NULL DEFAULT 'default',
  ADD COLUMN display_name VARCHAR(128),
  ADD COLUMN priority INTEGER DEFAULT 0;

-- 唯一约束：同一用途只能有一个 active 配置
-- (实际由应用层保证，不加 DB 约束以保持灵活性)
```

**purpose 枚举值**：

| purpose | 用途 | 典型模型 |
|---------|------|---------|
| `default` | 通用 LLM 调用（资产摘要、解读等） | MiniMax abab-7, GPT-4o-mini |
| `nlq` | NL-to-Query 流水线（One-Pass LLM） | GLM-4, GPT-4o |
| `embedding` | 向量生成 | MiniMax embo-01 |
| `semantic` | 语义生成（字段注释等） | GPT-4o-mini |

### 3.3 LLMConfig 模型改造

```python
# models.py 改造
class LLMConfig(Base):
    # 新增字段
    purpose = Column(String(32), default="default", server_default=sa_text("'default'"), nullable=False)
    display_name = Column(String(128), nullable=True)
    priority = Column(Integer, default=0, server_default=sa_func.cast(0, Integer()))
```

### 3.4 LLMConfigDatabase 改造

```python
class LLMConfigDatabase:
    def get_config(self, purpose: str = "default") -> Optional[LLMConfig]:
        """按用途获取 active 配置（优先级最高的）"""
        session = self.get_session()
        try:
            config = session.query(LLMConfig).filter(
                LLMConfig.purpose == purpose,
                LLMConfig.is_active == True,
            ).order_by(LLMConfig.priority.desc()).first()
            if config is None and purpose != "default":
                # fallback: 用途不存在时回退到 default
                config = session.query(LLMConfig).filter(
                    LLMConfig.purpose == "default",
                    LLMConfig.is_active == True,
                ).order_by(LLMConfig.priority.desc()).first()
            return config
        finally:
            session.close()
```

### 3.5 LLMService 改造

**最小改动方案**：`complete()` 系列方法增加 `purpose` 参数，默认 `"default"`。

```python
class LLMService:
    async def complete(self, prompt, system=None, timeout=15, purpose="default") -> dict:
        config = self._config_db.get_config(purpose=purpose)
        # ... 其余逻辑不变
```

**调用方适配**：

| 调用方 | 当前调用 | 改造后 |
|--------|---------|--------|
| `nlq_service.one_pass_llm()` | `llm_service.complete_for_semantic(...)` | `llm_service.complete_for_semantic(..., purpose="nlq")` |
| `service.py generate_asset_summary()` | `self.complete(...)` | `self.complete(..., purpose="default")` |
| `service.py generate_embedding_minimax()` | 固定走 MiniMax API | `purpose="embedding"`（或保持独立路径） |
| `semantic_llm_integration` | `llm_service.complete_for_semantic(...)` | `llm_service.complete_for_semantic(..., purpose="semantic")` |

### 3.6 Fallback 策略

```
请求 purpose="nlq"
  -> 查找 purpose="nlq" 且 is_active=True 的配置
  -> 未找到? fallback 到 purpose="default"
  -> 仍未找到? 返回 {"error": "LLM 未配置"}
```

### 3.7 改动文件清单

| 文件 | 变更类型 | 改动内容 | 复杂度 |
|------|---------|---------|--------|
| `backend/services/llm/models.py` | 改造 | `LLMConfig` 增加 `purpose`/`display_name`/`priority` 字段 | S |
| `backend/services/llm/models.py` | 改造 | `LLMConfigDatabase.get_config()` 增加 `purpose` 参数 + fallback | S |
| `backend/services/llm/service.py` | 改造 | `complete()`/`complete_with_temp()`/`complete_for_semantic()` 增加 `purpose` 参数 | M |
| `backend/services/llm/nlq_service.py` | 改造 | `one_pass_llm()` 调用时传 `purpose="nlq"` | S |
| `backend/app/api/llm.py` (LLM 管理 API) | 改造 | CRUD 接口支持多配置管理 | M |
| DB migration | 新增 | `alembic revision`: 添加 `purpose`/`display_name`/`priority` 列 | S |

### 3.8 向后兼容

- 现有单条 `ai_llm_configs` 记录自动被视为 `purpose="default"`
- 所有未传 `purpose` 的调用默认走 `"default"`
- 零停机迁移：先跑 migration 加列（带 default 值），再部署新代码

---

## 4. 首页问数端到端链路

### 4.1 与 Spec 21 首页重构的对接

Spec 21 定义了对话式 AI 助手界面。问数功能是首页的核心交互：

```
Spec 21 负责:                        Spec 22 负责:
+-----------------------+            +---------------------------+
| HomeLayout            |            | 问数后端链路               |
| ConversationBar       |            | 多站点 MCP                |
| WelcomeHero           |            | 多 LLM 配置               |
| SuggestionGrid        |            | NLQ Pipeline 增强          |
| AskBar (UI 改造)      |  -------> | POST /api/search/query    |
| ChatPage (对话流)     |            | 对话历史 API (新增)        |
+-----------------------+            +---------------------------+
```

### 4.2 完整端到端链路（改造后）

```
                         前端
                          |
    +---------------------+---------------------+
    |                     |                     |
 AskBar.tsx          SuggestionGrid        ConversationBar
 (改造: Spec 21)     (新增: Spec 21)       (新增: Spec 21)
    |                     |                     |
    +---------------------+                     |
              |                                 |
    POST /api/search/query              GET /api/conversations
    {question, connection_id?}          (P1, Spec 21 §12.1)
              |
              v
    search.py (API 层, 现有)
      |
      |-- 1. 权限校验 + 速率限制 (现有)
      |
      |-- 2. 意图分类 classify_intent() (现有)
      |
      |-- 3. 数据源路由 route_datasource()
      |       (改造: 支持跨 connection 路由)
      |
      |-- 4. 字段准备 + 术语增强 (现有)
      |
      |-- 5. One-Pass LLM
      |       (改造: purpose="nlq", 可用不同模型)
      |       llm_service.complete_for_semantic(purpose="nlq")
      |
      |-- 6. 查询执行 execute_query()
      |       |
      |       v
      |   TableauMCPClient.query_datasource()
      |       |
      |       v
      |   _ensure_session(site_key, base_url)  <-- 改造点
      |       |
      |       v
      |   MCP Server (per-site)
      |
      |-- 7. 结果格式化 format_response() (现有)
      |
      |-- 8. 审计日志 (现有)
      |
      v
    前端 SearchResult.tsx (现有)
    or ChatPage 对话流 (Spec 21 P1)
```

### 4.3 前端改动要点

| 组件 | 改动 | 归属 Spec |
|------|------|----------|
| `AskBar.tsx` | 样式改造 (rounded-full -> rounded-2xl)，增加 connection 选择器 | Spec 21 |
| `SearchResult.tsx` | 保留，在 ChatPage 中复用 | Spec 21 |
| `page.tsx (HomePage)` | 重写为 WelcomeHero + SuggestionGrid + AskBar | Spec 21 |
| `/api/search` API 调用 | 增加 `connection_id` 参数传递 | Spec 22 |

### 4.4 数据源选择器（新增交互）

当用户配置了多个 Tableau 连接时，AskBar 旁需要一个连接/数据源选择器：

- P0: 默认使用第一个 active 连接（不显示选择器）
- P1: AskBar 上方显示连接下拉框，用户可切换
- P2: 智能路由（跨连接搜索最佳数据源）

---

## 5. 模块依赖图

```
+------------------------------------------------------------------+
|                           前端                                    |
|                                                                  |
|  HomePage ──> AskBar ──> /api/search/query                       |
|       |                       |                                  |
|  SuggestionGrid              |                                  |
|       |                       |                                  |
|  ConversationBar ──> /api/conversations (P1)                     |
+------------------------------------------------------------------+
         |                      |
         v                      v
+------------------------------------------------------------------+
|                       后端 API 层                                 |
|                                                                  |
|  search.py ─────────────────────────────────────────────+        |
|    |          |            |           |                 |        |
|    v          v            v           v                 v        |
|  classify  route_ds    one_pass    execute_query    format_resp   |
|  _intent   (nlq_svc)  _llm        (nlq_svc)        (nlq_svc)    |
|  (nlq_svc)                                                       |
+------------------------------------------------------------------+
         |                      |
         v                      v
+-------------------+  +-------------------+  +-------------------+
|  LLMService       |  | TableauMCPClient  |  | 辅助服务           |
|  (service.py)     |  | (mcp_client.py)   |  | glossary_service  |
|                   |  |                   |  | ContextAssembler  |
|  .complete()      |  | .query_datasource |  | recall_fields     |
|  .complete_for_   |  |                   |  | redis_cache       |
|   semantic()      |  +-------------------+  +-------------------+
|  .generate_       |           |
|   embedding()     |           v
+-------------------+  +-------------------+
         |             | _MCPSessionState   |
         v             | {site_key -> state}|  <-- 改造点
+-------------------+  +-------------------+
| ai_llm_configs    |           |
| (多记录/purpose)  |           v
+-------------------+  +-------------------+
                       | MCP Server         |
                       | (per-site 实例)    |
                       | @tableau/mcp-server|
                       +-------------------+
```

### 并发修改冲突矩阵

以下文件在本 Spec 中有改动，标注互斥约束：

| 文件 | 本 Spec 改动 | 与其他 Spec 冲突 | 互斥要求 |
|------|-------------|-----------------|---------|
| `mcp_client.py` | per-site session 映射 | Spec 13 (V2 直连) 也改此文件 | 串行合并，Spec 22 优先 |
| `service.py` (LLM) | 增加 purpose 参数 | 无其他 Spec 改动 | 无 |
| `models.py` (LLM) | 增加 purpose 列 | 无其他 Spec 改动 | 无 |
| `nlq_service.py` | 传 purpose 参数 | 无 | 无 |
| `search.py` | 无结构性改动 | Spec 21 可能改前端调用方式 | 低冲突 |

---

## 6. 分期 TODO List

### P0: 基础可用（使首页问数链路跑通）

| # | TODO | 影响文件 | 类型 | 复杂度 | 说明 |
|---|------|---------|------|--------|------|
| P0-1 | `ai_llm_configs` 增加 `purpose`/`display_name`/`priority` 列 | `models.py` (LLM), alembic migration | 改造 | S | DDL 变更，带 default 值零停机 |
| P0-2 | `LLMConfigDatabase.get_config()` 支持 `purpose` 参数 + fallback | `models.py` (LLM) | 改造 | S | 查询逻辑改为按 purpose 过滤 |
| P0-3 | `LLMService.complete()` 系列方法增加 `purpose` 参数 | `service.py` (LLM) | 改造 | M | 所有 complete 方法签名变更，`_load_config` 透传 purpose |
| P0-4 | `one_pass_llm()` 调用时传 `purpose="nlq"` | `nlq_service.py` | 改造 | S | 单行改动 |
| P0-5 | LLM 管理 API 支持多配置 CRUD | `backend/app/api/llm.py` | 改造 | M | 列表/创建/更新/删除接口适配多记录 |
| P0-6 | `_MCPSessionState` 改为 per-site 字典映射 | `mcp_client.py` | 改造 | M | 核心改造，需要仔细处理线程安全 |
| P0-7 | `_ensure_session()` 接收 `site_key` + `base_url` 参数 | `mcp_client.py` | 改造 | M | 与 P0-6 同一 PR |
| P0-8 | `_post_mcp()` / `_build_headers()` 接收 session_state 参数 | `mcp_client.py` | 改造 | S | 与 P0-6 同一 PR |
| P0-9 | `TableauMCPClient.query_datasource()` 内部获取 site_key 路由 session | `mcp_client.py` | 改造 | S | 利用已有 `_get_connection_by_luid()` 获取连接信息 |

### P1: 体验增强

| # | TODO | 影响文件 | 类型 | 复杂度 | 说明 |
|---|------|---------|------|--------|------|
| P1-1 | 首页 UI 重构（Spec 21 P0 部分） | `frontend/src/pages/home/*`, `frontend/src/components/layout/HomeLayout.tsx` | 新增+改造 | L | Spec 21 交付，本 Spec 不负责 |
| P1-2 | AskBar 增加连接选择器下拉框 | `frontend/src/pages/home/components/AskBar.tsx` | 改造 | M | 多连接场景下用户选择 Site |
| P1-3 | 前端 `/api/search/query` 调用增加 `connection_id` | `frontend/src/api/search.ts` | 改造 | S | 透传选择器的值 |
| P1-4 | 数据源路由支持跨 connection 自动匹配 | `nlq_service.py` `route_datasource()` | 改造 | M | 当不指定 connection_id 时遍历所有 active 连接 |
| P1-5 | LLM 配置管理前端页面支持多配置 | `frontend/src/pages/system/llm/` | 改造 | M | 列表展示多配置，按 purpose 分组 |
| P1-6 | 对话历史 API（Spec 21 §12.1） | `backend/app/api/conversations.py` (新增) | 新增 | L | 对话 CRUD，本 Spec 定义接口契约但不实现 |
| P1-7 | MCP session 池上限 + 自动回收 | `mcp_client.py` | 改造 | S | 防止 site 数量无限增长导致内存泄漏 |

### P2: 高级能力

| # | TODO | 影响文件 | 类型 | 复杂度 | 说明 |
|---|------|---------|------|--------|------|
| P2-1 | 多轮对话上下文传递（Spec 14 OI-02） | `nlq_service.py`, `search.py` | 改造 | L | 追问时继承数据源/字段/时间范围上下文 |
| P2-2 | LLM fallback 链（主 LLM 失败自动切备用） | `service.py` (LLM) | 新增 | M | 同 purpose 多条配置按 priority 排序，失败切下一个 |
| P2-3 | MCP Server 进程管理器（自动拉起/停止） | `backend/services/tableau/mcp_manager.py` (新增) | 新增 | L | 每个 site 独立 MCP server 进程生命周期管理 |
| P2-4 | 查询结果缓存（Spec 14 OI-03） | `nlq_service.py`, Redis | 新增 | M | 相同问题+数据源的结果缓存 |
| P2-5 | 智能模型路由（按问题复杂度选模型） | `service.py` (LLM) | 新增 | M | 简单问题用小模型，复杂问题用大模型 |

---

## 7. 风险点与缓解措施

### 7.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| per-site session 映射引入内存泄漏 | 高（每个 site 持有 session 对象） | 中 | P1-7 增加 session 池上限（默认 50）+ idle 超时回收（复用已有 `_IDLE_TIMEOUT = 300s`） |
| 多 LLM 配置 fallback 逻辑复杂化 | 中（调用链路变长） | 低 | P0 阶段不实现 fallback，仅做 purpose 路由 + default 兜底 |
| DB migration 阻塞（`ai_llm_configs` 加列） | 低（小表，通常 <10 行） | 极低 | `ADD COLUMN ... DEFAULT` 是 online DDL，不锁表 |
| MCP Server per-site 实例资源消耗 | 高（每实例约 200MB 内存） | 中 | P0 阶段仅做 session 隔离（共享 MCP server 进程），per-site 进程推迟到 P2 |

### 7.2 迁移风险

| 风险 | 缓解措施 |
|------|---------|
| 现有单条 `ai_llm_configs` 记录迁移 | 新增列 `purpose` 默认值 `'default'`，现有记录自动归为 default，零数据迁移 |
| `LLMService.complete()` 签名变更影响所有调用方 | `purpose` 参数带默认值 `"default"`，所有未改的调用方行为不变 |
| `_MCPSessionState` 全局单例被移除 | 保留 `_mcp_session_state` 变量名作为兼容别名（指向 default site 的 state），但标记 `@deprecated` |

### 7.3 回滚方案

| 阶段 | 回滚策略 |
|------|---------|
| P0-1~P0-5 (LLM 多配置) | 回滚代码即可，DB 新增列不影响旧代码（`purpose` 列有 default 值） |
| P0-6~P0-9 (MCP per-site) | 回滚代码后自动退化为全局单 session（`_mcp_session_states` 字典为空时 fallback） |

---

## 8. 验收标准

### P0 验收

- [ ] 管理员可在 LLM 配置页创建多条配置（不同 purpose）
- [ ] NL-to-Query 流水线使用 `purpose="nlq"` 的 LLM 配置（若存在），否则 fallback 到 default
- [ ] 多个 Tableau 连接（不同 Site）可各自独立执行 MCP 查询，互不干扰
- [ ] 同一 Site 的多个 connection_id 共享同一 MCP session
- [ ] 单站点场景（现有环境）行为完全不变（向后兼容）

### P1 验收

- [ ] 前端 AskBar 可选择 Tableau 连接
- [ ] 跨连接数据源路由正确工作
- [ ] MCP session 池不超过上限，idle session 自动回收

---

## 9. 测试计划

### 单元测试

| 测试目标 | 测试文件 | 内容 |
|---------|---------|------|
| `LLMConfigDatabase.get_config(purpose)` | `tests/unit/test_llm_models.py` | 测试 purpose 过滤、fallback 到 default、无配置时返回 None |
| `_get_or_create_session_state(site_key)` | `tests/unit/test_mcp_client.py` | 测试 site 映射创建、复用、线程安全 |
| `_ensure_session(site_key, base_url)` | `tests/unit/test_mcp_client.py` | 测试不同 site 创建独立 session |

### 集成测试

| 测试目标 | 内容 |
|---------|------|
| 多站点 MCP 查询 | 配置 2 个 Tableau 连接（不同 site），分别执行 NLQ 查询，验证 session 隔离 |
| LLM 多配置路由 | 配置 nlq + default 两组 LLM，验证 NLQ 流水线走 nlq 配置 |
| 向后兼容 | 不创建新配置，验证现有单配置环境行为不变 |

### 回归测试

- Spec 14 的所有 Golden Case 必须通过
- LLM 配置 CRUD API 的现有测试用例必须通过

---

## 10. 设计共识记录（2026-04-16）

以下 7 点经 Human 确认，作为后续开发的准则，优先级高于原 Spec 描述。

### C1：P0 结果原地展示，不跳转（影响：前端）

P0 阶段结果在 HomePage 原地展示，不跳转 `/chat/:id`。后端 Search API 无需关联 conversation_id，P0 与现有 `POST /api/search/query` 接口兼容。

### C2：localStorage Schema 与后端 API 对齐（影响：前端 + 后端 P1）

P0 localStorage 的对话/消息结构与 P1 后端 API 响应结构一致（详见 Spec 21 §14 C2），P1 后端设计 `GET /api/conversations` 和 `GET /api/conversations/:id/messages` 时必须遵守该 schema。

### C3：MCP Session 字典 P0 不限上限（影响：mcp_client.py）

`_get_or_create_session_state(site_key)` 预留 `_max_sites: int = 0`（0 = 不限制）参数占位，P0 不实现驱逐逻辑。P1 在该函数内实现 LRU，上限默认 50。

### C4：P0 前端不传 connection_id（影响：前端 + search.py）

`POST /api/search/query` 的 `connection_id` 字段在 P0 为可选（已是 `Optional[int]`）。后端 `route_datasource()` 当 connection_id 为 None 时，自动选第一个 is_active=True 的连接。该逻辑检查是否已存在，若不存在需补充。

### C5：时间分组使用浏览器本地时区（影响：前端）

后端所有时间字段统一返回 UTC ISO 8601 字符串，不做时区转换。前端负责本地时区转换，该约定适用于全项目时间字段。

### C6：LLM 多配置 admin-only，前端入口 /system/llm-configs（影响：后端 API + 前端 P1）

`/api/llm/configs` CRUD 接口添加 `require_role("admin")` 依赖注入检查。前端管理页路径：`frontend/src/pages/admin/llm-configs/page.tsx`，P1 实现，挂载到现有系统管理路由。

### C7：conversation_messages 表预留 query_context JSONB（影响：alembic 迁移 P1）

P1 的 `xxxx_create_conversations.py` 迁移脚本必须包含 `query_context JSONB NULL` 列。P1 应用层写入 NULL，P2 实现追问时直接读取，无需再次迁移。结构见 Spec 21 §14 C2。
