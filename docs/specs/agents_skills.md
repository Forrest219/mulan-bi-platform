# Agents Skills Center — 技能中心 Spec

**版本**: v1.2
**状态**: Approved — 进入实现阶段  
**作者**: Architect  
**创建日期**: 2026-05-08  
**最后修订**: 2026-05-13（AI Native 创建体验与防丢失约束纳入）
**关联模块**: `agents/` 域，智能体技能管理  

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [现状审计](#2-现状审计)
3. [数据模型](#3-数据模型)
4. [核心 API 定义](#4-核心-api-定义)
5. [版本管理逻辑](#5-版本管理逻辑)
6. [LLM 集成改造](#6-llm-集成改造)
7. [UI/UX 规范](#7-uiux-规范)
8. [菜单集成](#8-菜单集成)
9. [非功能性要求](#9-非功能性要求)
10. [验收标准](#10-验收标准)
11. [未纳入范围](#11-未纳入范围)

---

## 1. 背景与动机

### 1.1 现状问题

项目中 Agent 工具（Tools/Skills）当前以**硬编码**方式注册在两处：

| 位置 | 注册方式 | 工具数量 |
|------|---------|---------|
| `backend/services/data_agent/factory.py` | `create_engine()` 手动实例化 | 14 个 |
| `backend/services/data_agent/tools/registry.py` | `create_spec28_registry()` | 13 个 |

每次修改工具的 `description`（影响 LLM 选择准确率）、`parameters_schema`（影响入参解析），均需改代码、走 PR、重新部署，**无法在线调整，无法回滚**。

### 1.2 目标

- **集中管理**：所有对 LLM 可见的工具定义在数据库中有单一来源（Single Source of Truth）。
- **版本化**：每次改动生成新版本，保留完整变更历史，支持一键回滚。
- **动态加载**：ReAct 引擎在构建 System Prompt 时从 DB 读取 `is_active=true` 的版本，无需重启服务即可生效。
- **可观测**：每次 LLM 调用记录使用的版本 ID，方便追查调用行为。

### 1.3 不改变的内容

- 现有 14 个静态工具的**执行逻辑**（`execute()` 方法）保持不变；DB 版本只覆盖 `description / input_schema`（LLM 可见 meta）。
- `BaseTool / ToolRegistry / ToolContext` 框架层接口不变。
- v1.2 阶段技能中心不是“上传任意可执行代码”的入口，只允许配置已经在后端 ToolRegistry 注册的静态工具。
- 不得破坏或重置已经配置的 skill。所有同步、导入、模板应用和 AI 生成动作必须默认保留现有 `agent_skills` 与 `agent_skill_versions` 数据，只能在用户显式确认后发布新版本或修改启停状态。

---

## 2. 现状审计

### 2.1 工具注入流程（当前）

```
create_engine(db, settings)
  └─ ToolRegistry()
       ├─ register(TableSchemaFetchTool())        # 静态工具 × 14
       └─ register(ExecuteQueryTool())
             ↓
  ReActEngine(registry=registry)
       └─ _build_system_prompt()
            └─ registry.get_tool_descriptions()   # 生成 name/desc/schema 文本
                 → 注入 LLM System Prompt
```

**关键约束**：`registry.get_tool_descriptions()` 目前直接读取类属性 `name / description / parameters_schema`，均为硬编码字符串。

### 2.2 改造目标状态

```
应用启动时（或每次 create_engine 时）:
  SkillLoader.load_and_override(db)             # 新增
    └─ SELECT skill_key, description, input_schema, version_id
         WHERE is_active=true AND is_enabled=true
       → 对 registry 中已注册工具按 skill_key 覆盖 description + parameters_schema
       → 不存在于 registry 的 skill_key 静默跳过（见 §3.5 白名单约束）

  ReActEngine._build_system_prompt()
    └─ registry.get_tool_descriptions()          # 透明返回覆盖后的 meta
```

**核心约束**：
- 动态加载**只覆盖 meta**（`description / parameters_schema`），不替换 `execute()` 实现。
- DB 中无对应 `skill_key` 的活跃版本时，fallback 到静态类属性（向后兼容）。

---

## 3. 数据模型

### 3.1 表：`agent_skills`

存储技能的不可变基础标识信息。`description` 字段仅供管理界面展示，**不进入 LLM Prompt**（LLM 可见描述在版本表的 `description` 字段）。

```sql
CREATE TABLE agent_skills (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_key     VARCHAR(128) NOT NULL UNIQUE,   -- 对应 BaseTool.name（如 "execute_query"）
    name          VARCHAR(255) NOT NULL,           -- 显示名称（中文）
    description   TEXT,                           -- 管理界面简介，不进入 LLM Prompt
    category      VARCHAR(64) NOT NULL DEFAULT 'general',  -- query/analysis/visualization/reporting
    is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,   -- 全局禁用开关（优先于版本 is_active）
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    INTEGER REFERENCES auth_users(id) ON DELETE SET NULL
);

CREATE INDEX idx_agent_skills_skill_key ON agent_skills(skill_key);
CREATE INDEX idx_agent_skills_category  ON agent_skills(category);
```

**字段说明**：

| 字段 | 约束 | 说明 |
|------|------|------|
| `skill_key` | UNIQUE, NOT NULL | 与 `BaseTool.name` 一一对应；ReAct 引擎按此 key 匹配工具 |
| `description` | 可空 | 仅供管理后台展示，**不注入 LLM System Prompt** |
| `is_enabled` | NOT NULL DEFAULT TRUE | false 时该工具完全从 LLM 可见列表中移除 |
| `category` | NOT NULL | 仅用于 UI 分类筛选，不影响执行 |

---

### 3.2 表：`agent_skill_versions`

每个技能的变更历史。**DB 约束强制每个 skill 同时只有一个 `is_active=true` 的版本**（partial unique index）。

```sql
CREATE TABLE agent_skill_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id        UUID NOT NULL REFERENCES agent_skills(id) ON DELETE CASCADE,
    version_number  VARCHAR(16) NOT NULL,              -- "v1", "v2"... 自动生成
    description     TEXT NOT NULL,                    -- 注入 LLM System Prompt 的工具描述
    input_schema    JSONB NOT NULL,                    -- JSON Schema（OpenAI function calling 格式）
    endpoint_type   VARCHAR(32) NOT NULL DEFAULT 'static',  -- v1 仅允许 'static'
    code_ref        TEXT,                              -- 人读注释：对应的 Python class 名（不做机器校验）
    change_notes    TEXT,                              -- 本版本变更说明
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,    -- 当前生效标识
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      INTEGER REFERENCES auth_users(id) ON DELETE SET NULL,

    UNIQUE (skill_id, version_number)
);

CREATE INDEX idx_skill_versions_skill_id ON agent_skill_versions(skill_id);

-- 强约束：同一 skill 最多一个活跃版本，DB 层保证，无需依赖应用层
CREATE UNIQUE INDEX uq_skill_versions_one_active
    ON agent_skill_versions(skill_id)
    WHERE is_active = TRUE;
```

**字段说明**：

| 字段 | 约束 | 说明 |
|------|------|------|
| `description` | NOT NULL | **进入 LLM System Prompt** 的工具描述；与 `agent_skills.description`（管理简介）严格区分 |
| `version_number` | UNIQUE per skill | 由 Service 自动计算：当前最大序号 + 1，格式 `v{n}` |
| `input_schema` | JSONB NOT NULL | 标准 JSON Schema，供 LLM 解析入参；示例见 §3.3 |
| `endpoint_type` | NOT NULL DEFAULT 'static' | v1 仅允许 `'static'`；Service 层写入时校验，非 static 拒绝 `400 SKILLS_005` |
| `code_ref` | 可空文本 | 人读注释（如 `ExecuteQueryTool`），不做 Python import 反射校验 |
| `is_active` | NOT NULL | 由 `uq_skill_versions_one_active` 在 DB 层强制唯一 |

---

### 3.3 `input_schema` 格式约定

遵循 OpenAI function calling 的 `parameters` 格式，兼容 Anthropic tool_use。

```json
{
  "type": "object",
  "properties": {
    "sql": {
      "type": "string",
      "description": "要执行的 SQL 语句，不含分号"
    },
    "limit": {
      "type": "integer",
      "description": "最大返回行数",
      "default": 100
    }
  },
  "required": ["sql"]
}
```

写入前由 Service 层使用 `jsonschema.Draft7Validator.check_schema()` 验证；非法则拒绝 `400 SKILLS_003`。

---

### 3.4 ER 关系图

```
auth_users (id)
     │ created_by
     ▼
agent_skills (id, skill_key, name, description[管理], category, is_enabled)
     │ 1:N
     ▼
agent_skill_versions (id, skill_id, version_number,
                      description[LLM], input_schema,
                      endpoint_type, code_ref, is_active, change_notes)
```

---

### 3.5 skill_key 白名单约束（v1）

v1 阶段，`skill_key` 必须属于 **静态 ToolRegistry 已注册的工具**。创建技能（`POST /api/skills`）时 Service 层校验：

```python
STATIC_SKILL_KEYS = frozenset(registry.list_tool_names())  # 启动时从 ToolRegistry 读取

if skill_key not in STATIC_SKILL_KEYS:
    raise HTTPException(400, detail={"code": "SKILLS_006", "message": "skill_key 不在已注册工具列表中"})
```

**理由**：dispatch 返回的技能若无对应执行器，LLM 调用时必然失败。v2 引入 http/mcp 类型后，此约束仅对 `endpoint_type=static` 生效。

---

### 3.6 初始化 Seed 策略

Alembic 迁移执行后，需运行 **幂等 seed 脚本**将 14 个静态工具写入初始数据，否则系统启动后技能中心为空。

**脚本路径**：`backend/scripts/seed_skills.py`

**逻辑**（幂等）：

```python
STATIC_TOOLS = [
    {
        "skill_key": "execute_query",
        "name": "SQL 执行",
        "description": "在目标数据源执行 SQL 并返回结果集",   # 管理简介
        "category": "query",
        "initial_description": "执行 SQL 查询，返回结构化结果集。...",  # LLM prompt 描述
        "initial_input_schema": {...},
        "code_ref": "ExecuteQueryTool",
    },
    # ... 其余 13 个工具
]

async def seed(db: AsyncSession):
    for tool in STATIC_TOOLS:
        existing = await db.scalar(
            select(AgentSkill).where(AgentSkill.skill_key == tool["skill_key"])
        )
        if existing:
            continue  # 幂等跳过
        # INSERT agent_skills + agent_skill_versions(v1, is_active=True)
```

**触发方式**：`cd backend && python scripts/seed_skills.py`；CI 流水线在迁移后自动执行。

---

## 4. 核心 API 定义

所有接口遵循 `docs/specs/02-api-conventions.md` 错误格式。

### 4.0 `GET /api/skills/registered-tools`

**已注册工具元数据接口**

```
权限：admin / data_admin
```

**用途**：返回后端当前 ToolRegistry 已注册的静态工具元数据，作为新建/同步 skill 的唯一可信来源。

**Response 200**:
```json
{
  "tools": [
    {
      "skill_key": "schema",
      "name": "表结构查询",
      "description": "查询数据源的表结构、字段信息。",
      "input_schema": {"type": "object", "properties": {}},
      "category": "query",
      "code_ref": "SchemaTool",
      "configured": true,
      "skill_id": "uuid",
      "active_version_id": "uuid",
      "active_version_number": "v2"
    }
  ],
  "total": 14
}
```

**业务规则**：
- 返回值必须来自真实静态 ToolRegistry，不能返回前端 mock。
- `configured=true` 表示该工具已经存在于 `agent_skills`，前端必须引导用户进入详情页或发布新版本，禁止重复创建。
- 该接口只读，不改变现有 skill 数据。

---

### 4.1 `POST /api/skills`

**创建新技能**

```
权限：admin
```

**Request Body**:
```json
{
  "skill_key":   "execute_query",
  "name":        "SQL 执行",
  "description": "管理界面简介，不进入 LLM",
  "category":    "query",
  "initial_version": {
    "description":  "执行 SQL 查询，返回结构化结果集。参数 sql 为完整 SQL 语句，limit 控制最大行数。",
    "input_schema": { "type": "object", "properties": {"sql": {...}}, "required": ["sql"] },
    "endpoint_type": "static",
    "code_ref":      "ExecuteQueryTool",
    "change_notes":  "初始版本"
  }
}
```

**Response 201**:
```json
{
  "id": "uuid",
  "skill_key": "execute_query",
  "name": "SQL 执行",
  "category": "query",
  "is_enabled": true,
  "active_version": {
    "id": "uuid",
    "version_number": "v1",
    "is_active": true,
    "created_at": "2026-05-08T10:00:00Z"
  },
  "created_at": "2026-05-08T10:00:00Z"
}
```

**业务规则**：
- `skill_key` 全局唯一；冲突返回 `409 SKILLS_001`。
- `skill_key` 必须在静态 registry 白名单内；不在则返回 `400 SKILLS_006`。
- `initial_version` 必填；创建时自动将该版本设为 `is_active=true`，版本号为 `v1`。
- `initial_version.endpoint_type` v1 仅允许 `'static'`；其他值返回 `400 SKILLS_005`。
- 前端不得把该接口包装成“创建任意新工具”。v1.2 主链路必须是“从已注册工具添加/同步”，由 `GET /api/skills/registered-tools` 预填 `skill_key / description / input_schema / code_ref`。
- 如果 `skill_key` 已配置，前端必须阻断重复提交，并提供“查看详情”或“发布新版本”入口。

---

### 4.2 `POST /api/skills/{id}/versions`

**发布新版本**（自动将旧版本设为非活跃）

```
权限：admin（仅 admin，data_admin 只读）
```

**Request Body**:
```json
{
  "description":  "执行 SQL 查询，返回结构化结果集。新增 timeout 参数（秒），超时自动终止。",
  "input_schema": {
    "type": "object",
    "properties": {
      "sql":     {"type": "string"},
      "limit":   {"type": "integer", "default": 100},
      "timeout": {"type": "integer", "description": "执行超时秒数", "default": 30}
    },
    "required": ["sql"]
  },
  "endpoint_type": "static",
  "code_ref":      "ExecuteQueryTool",
  "change_notes":  "增加 timeout 参数，限制执行时长"
}
```

**Response 201**:
```json
{
  "id": "uuid",
  "skill_id": "uuid",
  "version_number": "v3",
  "is_active": true,
  "previous_active_version": "v2",
  "created_at": "2026-05-08T12:00:00Z"
}
```

**版本切换原子性**（伪代码）:
```python
async with db.begin():
    # 行级锁防并发双写
    skill = await db.get(AgentSkill, id, with_for_update=True)

    # 计算新版本号
    max_ver = await db.scalar(
        select(func.max(AgentSkillVersion.version_number))
        .where(AgentSkillVersion.skill_id == id)
    )
    new_ver = f"v{int(max_ver[1:]) + 1}" if max_ver else "v1"

    # 旧活跃版本 → 非活跃（0 或 1 行）
    await db.execute(
        update(AgentSkillVersion)
        .where(AgentSkillVersion.skill_id == id,
               AgentSkillVersion.is_active == True)
        .values(is_active=False)
    )

    # 插入新版本，is_active=True
    db.add(AgentSkillVersion(..., version_number=new_ver, is_active=True))
    # uq_skill_versions_one_active 在提交时强制唯一
```

---

### 4.3 `POST /api/skills/{id}/rollback/{version_id}`

**回滚到指定版本**

```
权限：admin
```

**Response 200**:
```json
{
  "skill_id": "uuid",
  "rolled_back_to": "v1",
  "previous_active": "v3",
  "activated_at": "2026-05-08T13:00:00Z"
}
```

**业务规则**：
- `version_id` 必须属于 `skill_id`，否则 `404 SKILLS_002`。
- 回滚与发布新版本共用同一原子切换逻辑（FOR UPDATE → 旧 false → 目标 true）。
- 回滚**不创建新版本行**，直接重新激活历史版本；版本号序列不重置。

---

### 4.4 `GET /api/skills/dispatch`

**供 LLM 调用时批量查询当前生效的技能定义**

```
权限：内部服务（需有效 session）
```

**Query Params**:
- `category`（可选）：按类别筛选（在全量结果上内存过滤）
- `skill_keys`（可选，逗号分隔）：只返回指定 key（在全量结果上内存过滤）

**Response 200**:
```json
{
  "tools": [
    {
      "skill_key":      "execute_query",
      "name":           "SQL 执行",
      "description":    "执行 SQL 查询，返回结构化结果集。...",
      "input_schema":   { "type": "object", "properties": {...} },
      "version_number": "v3",
      "version_id":     "uuid"
    }
  ],
  "total": 14,
  "fetched_at": "2026-05-08T14:00:00Z"
}
```

**缓存策略**：
- 仅缓存全量结果（key = `dispatch:all`），`TTLCache(maxsize=100, ttl=60)`。
- `category` / `skill_keys` 筛选在全量结果上内存过滤，不分 key 缓存。
- 版本切换（publish / rollback）时主动 `cache.pop("dispatch:all", None)` 失效。
- v1 不引入 Redis，`TTLCache` 单进程有效（多进程部署时 TTL 60s 内可能短暂不一致，可接受）。

**DB 查询**（利用 `uq_skill_versions_one_active` 部分唯一索引，P99 < 20ms）：
```sql
SELECT s.skill_key, s.name, v.description, v.input_schema, v.version_number, v.id
FROM agent_skills s
JOIN agent_skill_versions v ON v.skill_id = s.id AND v.is_active = TRUE
WHERE s.is_enabled = TRUE;
```

---

### 4.5 管理接口（CRUD 补全）

#### `GET /api/skills` — 技能列表

```
权限：admin / data_admin（只读）
```

**Query Params**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `category` | string | 按分类过滤 |
| `is_enabled` | bool | 过滤启用/禁用状态 |
| `q` | string | 按 `name` 或 `skill_key` 模糊搜索 |
| `page` | int, default=1 | 页码 |
| `page_size` | int, default=20, max=100 | 每页条数 |

**Response 200**:
```json
{
  "items": [
    {
      "id": "uuid",
      "skill_key": "execute_query",
      "name": "SQL 执行",
      "category": "query",
      "is_enabled": true,
      "active_version": { "version_number": "v3", "updated_at": "2026-05-08T12:00:00Z" },
      "updated_at": "2026-05-08T12:00:00Z"
    }
  ],
  "total": 14,
  "page": 1,
  "page_size": 20
}
```

---

#### `GET /api/skills/{id}` — 技能详情

**Response 200**:
```json
{
  "id": "uuid",
  "skill_key": "execute_query",
  "name": "SQL 执行",
  "description": "管理简介",
  "category": "query",
  "is_enabled": true,
  "versions": [
    {
      "id": "uuid",
      "version_number": "v3",
      "description": "执行 SQL 查询...",
      "endpoint_type": "static",
      "code_ref": "ExecuteQueryTool",
      "change_notes": "增加 timeout 参数",
      "is_active": true,
      "created_at": "2026-05-08T12:00:00Z",
      "created_by_name": "admin"
    }
  ],
  "created_at": "2026-05-08T10:00:00Z",
  "updated_at": "2026-05-08T12:00:00Z"
}
```

---

#### `PATCH /api/skills/{id}` — 更新技能基本信息

```
权限：admin
可更新字段：name, description（管理简介）, category, is_enabled
不可更新字段：skill_key（不可变标识）
```

**Request Body**（所有字段可选，只传需要修改的）:
```json
{
  "name":        "SQL 查询执行",
  "is_enabled":  false
}
```

**Response 200**：返回更新后的完整 skill 对象（同 GET detail，不含 versions）。

---

#### `GET /api/skills/{id}/versions/{v_id}/diff/{v_id2}` — Schema Diff

**Response 200**:
```json
{
  "from_version": "v2",
  "to_version":   "v3",
  "description_changed": true,
  "schema_patch": [
    { "op": "add", "path": "/properties/timeout", "value": {...} }
  ]
}
```

`schema_patch` 遵循 RFC 6902 JSON Patch 格式，前端据此渲染增删高亮。

---

### 4.6 错误码汇总

| 错误码 | HTTP | 说明 |
|--------|------|------|
| `SKILLS_001` | 409 | skill_key 已存在 |
| `SKILLS_002` | 404 | 版本不存在或不属于该技能 |
| `SKILLS_003` | 400 | input_schema 不合法（非有效 JSON Schema） |
| `SKILLS_004` | 404 | 技能不存在 |
| `SKILLS_005` | 400 | v1 不支持 endpoint_type 非 'static' |
| `SKILLS_006` | 400 | skill_key 不在静态 registry 白名单中 |

---

## 5. 版本管理逻辑

### 5.1 版本号规则

```
v1 → v2 → v3 → ... → vN
```

- 自动递增，不允许手动指定。
- 基于**当前 skill 下最大序号 + 1**，在 FOR UPDATE 事务内计算（不使用 DB sequence，避免跨 skill 序号污染）。
- 版本号不因回滚重置（回滚后序号仍为 `vN`，只改 `is_active`）。

### 5.2 状态机

```
skill.is_enabled = false
  └─ 所有版本对 LLM 不可见（dispatch 不返回该 skill）
  
skill.is_enabled = true
  └─ 版本状态：
       is_active=true  → LLM 当前使用此版本的 description + input_schema
       is_active=false → 历史版本，可回滚
```

### 5.3 并发安全

`SELECT FOR UPDATE` 锁定 `agent_skills` 行，配合 `uq_skill_versions_one_active` 唯一约束，**双重保障**防止并发双写产生多 active 版本：

- FOR UPDATE 在 Service 层序列化并发请求。
- 即使 FOR UPDATE 失效，`uq_skill_versions_one_active` 唯一索引也会在 COMMIT 时报 `UniqueViolation`，触发事务回滚。

---

## 6. LLM 集成改造

### 6.1 新增组件：`SkillLoader`

**文件**: `backend/services/data_agent/skill_loader.py`

```python
class SkillLoader:
    """从 DB 加载活跃版本，覆盖 ToolRegistry 的 description + parameters_schema。
    
    仅覆盖 meta，不替换 execute()。DB 无对应记录时保留静态类属性（fallback）。
    """

    async def load_and_override(
        self,
        registry: ToolRegistry,
        db: AsyncSession,
    ) -> dict[str, str]:
        """
        返回 {skill_key: version_id} 供 ReActEngine 写入步骤记录。
        """
        rows = await db.execute(
            select(AgentSkill.skill_key, AgentSkillVersion.description,
                   AgentSkillVersion.input_schema, AgentSkillVersion.id)
            .join(AgentSkillVersion,
                  (AgentSkillVersion.skill_id == AgentSkill.id) &
                  (AgentSkillVersion.is_active == True))
            .where(AgentSkill.is_enabled == True)
        )
        version_map = {}
        for skill_key, description, input_schema, version_id in rows:
            if registry.has(skill_key):
                registry.override_meta(skill_key, description, input_schema)
                version_map[skill_key] = str(version_id)
        return version_map
```

### 6.2 `ToolRegistry` 新增方法

```python
class ToolRegistry:
    def override_meta(self, name: str, description: str, parameters_schema: dict) -> None:
        """用 DB 版本覆盖工具的 description 和 parameters_schema（保留 execute()）"""
        tool = self._tools[name]
        tool.description = description
        tool.parameters_schema = parameters_schema

    def has(self, name: str) -> bool:
        return name in self._tools
```

### 6.3 `factory.py` 改造点

```python
# 原有代码（保留）
registry = ToolRegistry()
registry.register(ExecuteQueryTool())
# ... 其余 13 个工具

# 新增：DB 版本覆盖 meta
skill_loader = SkillLoader()
version_map = await skill_loader.load_and_override(registry, db)

engine = ReActEngine(registry=registry, active_skill_versions=version_map)
```

### 6.3.1 Tableau 查询技能字段口径

凡是技能描述、`input_schema` 或动态覆盖后的 LLM 可见 meta 涉及 Tableau 查询字段，必须固化以下口径：

- `metadata_fields` 是资产导入/API 同步得到的 Tableau 元数据层字段全集/字段快照，只能描述为治理、字段盘点、血缘/语义维护用途。
- `queryable_fields` 是当前 published datasource 通过 Tableau MCP/VizQL 实际可查询的字段子集，是首页问答、QueryTool、LLM 查询 prompt、direct VizQL 的唯一可信字段来源。
- 技能中心不得发布会诱导 LLM 把 `metadata_fields` 当成可查询字段的 `description` 或 `input_schema`。
- 当字段只存在于 `metadata_fields` 而不在 `queryable_fields` 时，工具描述应引导模型返回业务解释和替代字段建议，不得描述成工具执行失败。
- 字段元数据页未来可展示 `mcp_queryable` / `mcp_checked_at` / `mcp_status`，但本 spec 不要求本轮数据库或 UI 实现。

### 6.4 运行时版本追踪

`bi_agent_steps` 需扩展 `skill_version_id` 字段（独立迁移文件）：

```sql
-- backend/alembic/versions/20260508_add_skill_version_id_to_agent_steps.py
ALTER TABLE bi_agent_steps
    ADD COLUMN skill_version_id UUID
    REFERENCES agent_skill_versions(id) ON DELETE SET NULL;
```

`ReActEngine` 执行工具时，从 `active_skill_versions[tool_name]` 取 `version_id` 写入步骤记录。

### 6.5 Dispatch Cache 失效策略

```python
# cachetools.TTLCache，maxsize=100（预留未来分 key 场景），ttl=60s
_dispatch_cache: TTLCache = TTLCache(maxsize=100, ttl=60)
DISPATCH_CACHE_KEY = "dispatch:all"

class SkillService:
    async def _activate_version(self, ...):
        # ... 原子切换逻辑
        _dispatch_cache.pop(DISPATCH_CACHE_KEY, None)   # 主动失效
```

---

## 7. UI/UX 规范

### 7.1 整体布局

```
/agents/skills                     — 技能中心（列表页）
/agents/skills/{id}                — 技能详情 + 版本历史
/agents/skills/create              — 从已注册工具添加/同步 skill
```

遵循 Slate 风格：`bg-white border border-slate-200 rounded-xl`，与 DQC、资产管理等页面一致。页面容器 `max-w-6xl mx-auto`。

---

### 7.2 列表页（`/agents/skills`）

#### 页面头部

```
[ri-puzzle-2-line] 技能中心
  管理 Agent 可调用的技能定义与版本
                                          [从已注册工具添加] [导入/导出]
```

`[从已注册工具添加]` 仅 admin 可见，点击进入 `/agents/skills/create`。按钮文案禁止使用容易误解为“上传任意工具代码”的“新建技能”。

#### 筛选栏

```
[全部] [查询] [分析] [可视化] [报告]    搜索框（技能名/key）    [已启用 ▼]
```

#### 高密度列表（表格形式）

| 列 | 内容 | 宽度 |
|----|------|------|
| 技能名称 | `name`（粗体）+ `skill_key`（灰色小字 `text-[11px]`） | flex-1 |
| 分类 | badge（`category`）| 80px |
| 活跃版本 | `vN`（蓝色 badge）| 80px |
| 状态 | 已启用（绿）/ 已禁用（灰）| 80px |
| 最近更新 | `updated_at` 相对时间 | 120px |
| 操作 | [详情]；admin 额外显示 [发布版本] | 140px |

行点击进入详情页；admin 可通过 toggle 快捷切换 `is_enabled`。

**交互约束**：
- 列表页的 [发布版本] 必须直接打开发布新版本流程或跳转到详情页并自动打开发布面板，不能只是普通详情跳转。
- 导入/导出第一阶段只提供 JSON 预览与下载，不允许导入后直接发布。导入数据必须经过白名单校验、Diff 预览和用户确认。

---

### 7.2.1 从已注册工具添加/同步页（`/agents/skills/create`）

该页面替代原居中 Modal。页面采用沉浸式双栏布局，避免长 Prompt 与 JSON Schema 在小弹窗中编辑。

#### 布局

```
左侧 320px：工具选择与基础配置
  - 已注册工具选择器（必选，来源 GET /api/skills/registered-tools）
  - skill_key 只读
  - 技能名称
  - 分类
  - 管理简介
  - 当前配置状态：未配置 / 已配置 vN

右侧 flex：版本内容编辑
  - LLM 工具描述 textarea，大尺寸
  - Input Schema JSON 编辑区，大尺寸
  - 代码引用 code_ref 只读或可微调
  - 变更说明
  - 模板库 / 从静态工具恢复 / AI 帮我写（P1）
```

#### 主链路

1. 用户选择一个已注册工具。
2. 页面调用 `GET /api/skills/registered-tools` 的返回数据自动填充 `description / input_schema / code_ref`。
3. 如果该工具未配置，提交时调用 `POST /api/skills` 创建 v1。
4. 如果该工具已配置，页面默认不覆盖现有配置，只提供“查看详情”或“基于当前静态定义发布新版本”两个入口。
5. 所有提交前必须展示关键字段摘要，用户确认后才写库。

#### 防丢失

- 页面存在未保存内容时，路由离开、刷新、点击取消必须触发二次确认。
- 输入变化后以 debounce 写入 `localStorage`，key 格式为 `skill_draft_create:{skill_key || "unselected"}`。
- 再次进入页面时，如发现草稿，提示“发现未保存草稿，是否恢复？”。
- P0 不落库保存半成品草稿；数据库级草稿需要新增状态模型，见 §11 未纳入范围。

#### 模板与 AI 辅助

- P0 模板库至少提供：无参数模板、单字符串参数模板、枚举参数模板。
- P0 必须提供“从静态工具恢复”按钮，将当前工具的 registry 元数据重新填回编辑区。
- P1 增加“AI 帮我写”能力，生成结果只能回填编辑区，必须经过 JSON Schema 校验、Diff 展示和用户确认后才能发布。

---

### 7.3 详情页（`/agents/skills/{id}`）

#### 左侧：技能基本信息面板（width: 300px）

- 技能名称（admin 可编辑）、`skill_key`（只读 tag）
- 管理简介（admin 可编辑 textarea）
- 分类 select（admin 可编辑）
- is_enabled toggle（admin 即时 PATCH）

#### 右侧：版本历史 Timeline

```
─────────────────────────────────────
 ● v3  当前活跃        2026-05-08 12:00   [查看]
     增加 timeout 参数，限制执行时长
─────────────────────────────────────
 ○ v2  历史            2026-04-20 09:30   [查看] [回滚]
     修正 sql 字段描述
─────────────────────────────────────
 ○ v1  历史            2026-04-01 08:00   [查看] [回滚]
     初始版本
─────────────────────────────────────
                    [+ 发布新版本]（admin 可见）
```

Timeline 样式：
- 左侧竖线 `border-l-2 border-slate-200`
- 活跃版本节点：`w-3 h-3 rounded-full bg-blue-500`
- 历史版本节点：`w-3 h-3 rounded-full bg-slate-300`

[回滚] 按钮点击后弹出确认 Dialog（含版本号和变更说明），确认后调用 `POST /api/skills/{id}/rollback/{version_id}`，Timeline 刷新。

#### Schema 查看 Drawer（右侧抽屉，width: 500px）

点击 [查看] 打开，包含：
- **标题**：`vN — 变更说明`
- **LLM 描述**（`description`）：只读 textarea
- **Input Schema**：Monaco Editor（只读，`readOnly: true`）
- **与当前活跃版本 Diff**（非活跃版本时显示）：调用 `/diff` 接口，JSON Patch 渲染（新增行绿色背景，删除行红色背景，Monaco diff editor）
- 底部 [回滚到此版本] 按钮（活跃版本隐藏）

#### 发布新版本面板

```
发布新版本 v4
─────────────────────────────────────
LLM 工具描述（注入 System Prompt）
[textarea，行高 3，初始值复制自活跃版本]

Input Schema（JSON Schema）
┌────────────────────────────────────┐
│  Monaco Editor（可编辑）            │
│  初始值：复制自活跃版本的 input_schema │
└────────────────────────────────────┘
代码引用（可选）  [ExecuteQueryTool    ]
变更说明         [本次修改了什么...    ]

                    [取消]  [发布]
```

发布新版本不再使用小尺寸居中 Modal。允许采用详情页内联面板、右侧大 Drawer 或独立编辑页，但必须满足：
- 编辑区在 1366px 宽度下不出现内层嵌套滚动挤压。
- 关闭或离开前执行 dirty guard。
- 初始值复制自活跃版本，避免用户从空白开始。
- 发布前展示 Diff 摘要，用户确认后调用 `POST /api/skills/{id}/versions`。

Monaco Editor 配置：
- `language: 'json'`, `theme: 'vs'`, `minimap: { enabled: false }`
- `jsonDefaults.setDiagnosticsOptions({ validate: true, schemas: [...] })`
- 提交前前端 `JSON.parse()` 验证；后端 `Draft7Validator.check_schema()` 双重校验

---

## 8. 菜单集成

### 8.1 `frontend/src/config/menu.ts`

在 `agents` 域的 `items` 数组末尾追加：

```typescript
{ key: 'skills', label: '技能中心', path: '/agents/skills', icon: 'ri-puzzle-2-line' },
```

### 8.2 `frontend/src/router/config.tsx`

在 `/agents/*` 路由组内追加：

```typescript
{
  path: 'skills',
  element: (
    <Suspense fallback={<PageLoader />}>
      <SkillsPage />
    </Suspense>
  ),
},
{
  path: 'skills/create',
  element: (
    <Suspense fallback={<PageLoader />}>
      <SkillCreatePage />
    </Suspense>
  ),
},
{
  path: 'skills/:skillId',
  element: (
    <Suspense fallback={<PageLoader />}>
      <SkillDetailPage />
    </Suspense>
  ),
},
```

组件使用 `React.lazy` 懒加载（遵循 `dev-constraints.md` §8）。

---

## 9. 非功能性要求

### 9.1 性能

| 接口 | P50 目标 | P99 目标 |
|------|---------|---------|
| `GET /api/skills/dispatch`（命中缓存） | < 2ms | < 5ms |
| `GET /api/skills/dispatch`（冷启动） | < 10ms | < 20ms |
| `GET /api/skills` | < 50ms | < 200ms |
| `POST /api/skills/{id}/versions` | < 100ms | < 500ms |

### 9.2 安全与权限

| 操作 | 最低权限 |
|------|---------|
| 创建技能 | admin |
| 发布新版本 | admin |
| 回滚版本 | admin |
| PATCH 基本信息 | admin |
| 读取列表/详情/dispatch | admin / data_admin |

**data_admin 不可发布或回滚版本**（description 进入 LLM Prompt，操作权限收敛至 admin）。

`input_schema` 和 `description` 写入前由 Service 层校验；前端 Monaco Editor 提交前 JSON 解析验证。审计记录提供事后追溯（见 §9.3）。

### 9.3 审计

版本发布和回滚操作写入 `bi_events` 审计表（Append-Only）：

```python
event_type  = 'skill_version_activated'
extra_data  = {
    "skill_key":      "execute_query",
    "from_version":   "v2",          # 可为 null（首次激活）
    "to_version":     "v3",
    "action":         "publish" | "rollback",
}
```

同时，技能中心的关键写操作必须写入 `bi_operation_logs`，以便 `/system/activity` 可按用户操作追踪：

| 操作 | operation_type | target |
|------|----------------|--------|
| 从已注册工具创建 skill | `skill_create` | `skill:{skill_key}` |
| PATCH 基本信息或启停 | `skill_update` | `skill:{skill_key}` |
| 发布新版本 | `skill_version_publish` | `skill:{skill_key}:version:{version_number}` |
| 回滚版本 | `skill_version_rollback` | `skill:{skill_key}:version:{version_number}` |

日志写入失败不得影响主链路，但必须 warning 记录后端日志。

---

## 10. 验收标准

### AC-1 数据模型
- [ ] Alembic 迁移可正向执行（`upgrade head`）且可回滚（`downgrade -1`）
- [ ] `uq_skill_versions_one_active` 唯一索引生效：并发插入两条 `is_active=true` 时数据库报 UniqueViolation
- [ ] seed 脚本幂等：重复执行不报错，不产生重复行

### AC-2 版本原子性
- [ ] 并发发布两个版本，最终只有一个 `is_active=true`
- [ ] 回滚后 `bi_events` 有 `skill_version_activated` 记录，`action='rollback'`

### AC-3 白名单校验
- [ ] `POST /api/skills` 传入不在 registry 的 `skill_key` 返回 `400 SKILLS_006`
- [ ] `endpoint_type='http'` 发布新版本返回 `400 SKILLS_005`
- [ ] `GET /api/skills/registered-tools` 返回真实 ToolRegistry 元数据，且标记已配置工具，不修改现有 skill

### AC-4 LLM 集成
- [ ] `SkillLoader.load_and_override()` 单测：mock DB 返回 1 条 active 版本，验证 registry 中对应工具的 `description` 被覆盖
- [ ] 无 DB 记录时 registry 保留静态 class 属性（fallback）
- [ ] 版本切换后 `dispatch:all` 缓存失效，下次 dispatch 返回新版本

### AC-5 Dispatch API
- [ ] `GET /api/skills/dispatch` 仅返回 `is_enabled=true AND is_active=true` 的技能
- [ ] `is_enabled=false` 的技能不出现在 dispatch 结果中

### AC-6 前端
- [ ] 列表页展示技能名称、分类、活跃版本号、状态、最近更新时间
- [ ] 版本历史 Timeline 正确区分活跃/历史节点样式
- [ ] 非活跃版本的 Schema Drawer 展示与活跃版本的 Diff
- [ ] 从已注册工具添加页可以选择真实后端工具并自动回填 schema，不允许重复破坏已配置 skill
- [ ] 发布新版本编辑体验使用大编辑面板/Drawer/独立页，不再使用小尺寸居中 Modal
- [ ] 发布新版本编辑区可编辑、提交前展示 Diff，提交后列表刷新
- [ ] 创建和发布流程具备 dirty guard 与 localStorage 草稿恢复
- [ ] 模板库可回填无参数、单字符串参数、枚举参数 schema
- [ ] 回滚有确认弹窗，确认后 Timeline 更新
- [ ] data_admin 角色看不到 [发布版本] / [回滚] / [从已注册工具添加] 按钮
- [ ] 所有可见文案为中文

### AC-7 类型检查与 Lint
- [ ] `npm run type-check` 零错误
- [ ] `pytest tests/ -x -q` 覆盖 SkillService 的 happy path 及版本切换

### AC-8 操作日志
- [ ] 创建、PATCH、发布、回滚均写入 `bi_operation_logs`
- [ ] `/system/activity` 能筛选并看到 skill 相关 operation_type
- [ ] 审计失败不阻断技能配置主流程

### AC-9 现有数据保护
- [ ] 当前已配置的 `schema` skill 及其版本记录在迁移、同步、导入、创建页访问后保持不变
- [ ] 已配置工具在创建页显示为已配置，默认不允许再次创建
- [ ] 所有导入/模板/静态恢复动作只修改当前编辑草稿，未确认发布前不写库

---

## 11. 未纳入范围（Out of Scope）

| 功能 | 原因 |
|------|------|
| `endpoint_type=http`：实际 HTTP 转发执行 | v2 实现；v1 Service 层拒绝写入 |
| `endpoint_type=mcp`：MCP 工具委托 | 依赖 MCP 协议集成，独立 Spec |
| 技能 A/B 测试（多版本按权重路由） | 超出当前需求，版本表可预留 `weight` 列 |
| 技能市场 / 跨平台导入导出 | 留给后续迭代 |
| `bi_agent_steps.skill_version_id` 的聚合分析报表 | 数据积累后有意义，与本 Spec 解耦 |
| 多进程部署下的 dispatch 缓存强一致 | v1 单进程；多进程场景引入 Redis 时补充 |
| 上传任意 skill 代码包 / 安装第三方工具运行时 | v1.2 只配置已注册静态工具，避免制造不可执行 skill |
| 数据库级草稿（`status=draft/published` 或 `draft_skill_versions`） | P0 只做前端本地草稿；落库草稿需要新增状态机、权限、审计和 dispatch 排除规则 |
| AI 自动发布 | AI 只能生成候选内容，发布必须由 admin 显式确认 |

---

*v1.2 — AI Native 创建体验与现有数据保护约束已纳入，Approved，进入实现阶段*
