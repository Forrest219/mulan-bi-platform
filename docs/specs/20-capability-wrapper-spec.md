# SPEC 20 — Capability Wrapper 能力封装层

> 版本:v0.1(骨架草稿)
> 日期:2026-04-15
> 状态:Draft — 仅 Phase 1(审计+敏感度)已落地([[tech-capability-audit-v1]]),Phase 1.5+ 待实施
> 类别:Tier 2 · 集成层
> 依赖:SPEC 04(Auth)· SPEC 07(Tableau v1)· SPEC 08(LLM)· SPEC 13(Tableau MCP v2)· SPEC 14(NL-to-Query)· SPEC 16(Events)

---

## §1 Overview

### 1.1 背景

当前首页问数链路是 LLM → MCP Client → Tableau 直通,缺失一层**企业级能力封装**。裸用 MCP 带来 5 个问题:

1. MCP 不感知 Mulan 用户,无法做 `user × datasource × field` 三元授权
2. 高敏/机密字段在查询路径无门禁(只在发布路径被拦)
3. 供应商锁定 —— Tableau MCP schema 变更穿透到 LLM Prompt
4. 可观测性割裂,无统一 `trace_id`、成本计量、限流维度
5. LLM 直接输出 VizQL JSON 稳定性差(OI-07)

### 1.2 目标

在 LLM 与 MCP/Tableau 之间插入 **Capability Wrapper** 层,统一提供:
- 业务语义工具注册表(LLM 看到的是 `query_metric`,不是 VizQL)
- 授权策略引擎(声明式 YAML 驱动)
- 敏感度门禁
- 限流 / 熔断 / 缓存
- 审计与 `trace_id` 贯穿
- 可插拔后端(Tableau MCP / 未来 Power BI MCP / 直连 SQL Engine)

### 1.3 非目标

- ❌ 完整 Agent 框架(规划、反思、多轮),属 SPEC 21+
- ❌ 多租户 MCP server 进程管理,属 [[tech-mcp-client-rewrite]] 延伸(T-R6)
- ❌ 替代现有 `services/tableau/`、`services/llm/` 核心服务,本层仅编排与治理

---

## §2 Scope / 分期实施

| 阶段 | 内容 | 状态 | 落地 spec |
|---|---|---|---|
| **Phase 1** | 审计 + trace_id + 敏感度门禁(复用 `nlq_service.is_datasource_sensitivity_blocked`)| ✅ Ready | [[tech-capability-audit-v1]] |
| **Phase 1.5** | Capability Registry + YAML 策略 + RateLimiter + ResultCache | 📋 设计中 | 本 spec §3~§7 |
| **Phase 2** | CircuitBreaker + CostMeter + Multi-capability(5 个业务工具) | 📋 规划 | 本 spec §8 |
| **Phase 3** | 多后端适配(Power BI MCP / SQL Engine)| 🗓 未来 | 独立 spec |

---

## §3 Data Model

### 3.1 已有(Phase 1)

`bi_capability_invocations`(Append-Only 审计表),定义见 [[tech-capability-audit-v1]] §T1。

### 3.2 新增(Phase 1.5)

#### 3.2.1 `bi_capability_rate_limits`(Redis 首选,PG 兜底)
用于按 `principal × capability` 维度限流。Redis key:`cap:rl:{capability}:{user_id}`,滑动窗口。

#### 3.2.2 `bi_capability_cache`(Redis)
结果缓存。Key:`cap:cache:{capability}:{hash(params + principal_role)}`,TTL 按 YAML 配置。

#### 3.2.3 `bi_capability_circuit_state`(内存 + 定期落 PG 快照)
熔断状态:`{capability: {state, failure_count, last_failure_at, opened_at}}`。

---

## §4 API / 模块结构

```
services/capability/
├── __init__.py
├── wrapper.py           # 统一入口 CapabilityWrapper.invoke(...)
├── registry.py          # YAML 加载 + get(name)
├── authz.py             # 策略引擎
├── sensitivity.py       # 敏感度门禁(Phase 1 已实现,迁移至此)
├── rate_limiter.py      # Phase 1.5
├── circuit_breaker.py   # Phase 2
├── result_cache.py      # Phase 1.5
├── audit.py             # Phase 1 已实现
├── cost_meter.py        # Phase 2
├── errors.py            # CAP_001~CAP_010 错误类
└── capabilities/
    ├── __init__.py
    ├── query_metric.py      # 业务参数 → VizQL 构造 → 调 MCP
    ├── search_asset.py      # Phase 2
    ├── list_datasources.py  # Phase 2
    ├── describe_datasource.py  # Phase 2
    └── explain_asset.py     # Phase 2

config/
└── capabilities.yaml        # 声明式策略
```

### 4.1 统一入口

```python
# services/capability/wrapper.py
from dataclasses import dataclass
from typing import Any

@dataclass
class CapabilityResult:
    data: Any
    meta: dict   # {audit_id, latency_ms, cost_tokens, cached, trace_id, ...}

class CapabilityWrapper:
    async def invoke(
        self,
        principal: dict,      # {id, role}
        capability: str,      # "query_metric" ...
        params: dict,
        trace_id: str | None = None,
    ) -> CapabilityResult:
        """
        执行顺序:
          1. trace_id 生成/继承
          2. Registry.get(capability) 找能力定义
          3. Authz.check(principal, capability)
          4. Params JSON Schema 校验(能力定义里的 schema)
          5. Sensitivity.check(principal, capability, params)
          6. RateLimiter.acquire(principal, capability)
          7. CircuitBreaker.allow(capability)
          8. ResultCache.get(key) → hit return
          9. capabilities.{name}.run(params) → downstream(MCP / SQL / ...)
         10. ResultCache.set(key, result)
         11. CostMeter.record(...)
         12. Audit.write(...)  ← Phase 1 已实现
        """
```

---

## §5 Business Logic

### 5.1 Capability Registry(YAML 驱动)

```yaml
# config/capabilities.yaml
version: 1
capabilities:
  - name: query_metric
    description: "按业务字段 + 过滤 + 聚合查询指标"
    roles: [analyst, data_admin, admin]
    params_schema:
      $schema: http://json-schema.org/draft-07/schema#
      type: object
      required: [datasource_id, metric]
      properties:
        datasource_id: { type: integer }
        metric: { type: string }
        dims: { type: array, items: { type: string }, default: [] }
        filters: { type: array, default: [] }
        aggregation: { type: string, enum: [SUM, AVG, COUNT, MIN, MAX], default: SUM }
        limit: { type: integer, minimum: 1, maximum: 10000, default: 1000 }
    guards:
      sensitivity_block: [high, confidential]
      max_rows: 10000
      forbid_raw_pii: true
    rate_limit: "30/min/user"
    timeout_seconds: 30
    cache:
      ttl_seconds: 300
      key_fields: [principal_role, datasource_id, metric, dims, filters, aggregation]
    circuit_breaker:
      failure_threshold: 5
      recovery_seconds: 60
    audit: always
    backend: tableau_mcp

  # Phase 2 追加 ...
```

### 5.2 授权策略

粗粒度:`roles` 字段。细粒度(按资源 owner_id)由 capability 内部实现查 DB 决定。

### 5.3 敏感度门禁

迁移 `services/llm/nlq_service.is_datasource_sensitivity_blocked` 到 `services/capability/sensitivity.py`,保留接口:
```python
def check(principal: dict, capability: str, params: dict) -> None:
    """违规 raise CapabilityDenied(code='CAP_003')"""
```

### 5.4 限流

- 后端:Redis `INCR + EXPIRE` 滑动窗口
- 粒度:`{capability, user_id}` 组合
- 配置:YAML `rate_limit: "30/min/user"` 解析为 `{rate: 30, window: 60, scope: user}`

### 5.5 熔断

经典三态机:`closed → open → half_open`。
- `closed`:正常放行;失败计数
- 达到 `failure_threshold` → `open`:拒所有请求,返回 `CAP_006`
- `recovery_seconds` 后 → `half_open`:放 1 个请求试探
- 成功 → `closed`;失败 → `open` 重置计时

### 5.6 结果缓存

key 计算:`sha256(f"{capability}:{canonical_json(cache_key_fields)}")`。
命中:响应 `meta.cached = true`,跳过下游调用。
失效:写入时 `SETEX(ttl)`;手动清除走 admin API。

---

## §6 Error Codes(加入 SPEC 01)

| 代码 | HTTP | 含义 |
|---|---|---|
| CAP_001 | 403 | Authz 拒绝(角色/身份不够) |
| CAP_002 | 400 | params 不符 Schema |
| CAP_003 | 403 | 敏感度门禁拒绝 |
| CAP_004 | 429 | 限流触发 |
| CAP_005 | 502 | 下游调用失败(Tableau/LLM) |
| CAP_006 | 503 | 熔断打开 |
| CAP_007 | 504 | 超时 |
| CAP_008 | 400 | Capability 不存在 |
| CAP_009 | 500 | Capability 实现内部错误 |
| CAP_010 | 500 | Registry 加载失败(启动时) |

---

## §7 Security

- Phase 1 已落:审计 Append-Only,参数脱敏存 JSONB
- Phase 1.5 要做:
  - Rate limit 防滥用(与 DDoS 场景隔离,跨用户限流留给网关)
  - Sensitivity block 不得被 capability 内部逻辑绕过(统一在 wrapper 调用)
  - Cache key 必须含 `principal_role`,避免低权用户命中高权用户缓存
- Phase 2:
  - Cost meter 接入 LLM token 计费,防止恶意 prompt 刷 token
  - Circuit breaker 在 Tableau 抖动时保护下游
- 红线:
  - ❌ Capability 实现 **禁止**直接访问 `os.environ`
  - ❌ Capability 结果**禁止**携带原始 PII(需在 ResultShaper 内脱敏)
  - ❌ YAML 里的 `params_schema` 变更必须通过 PR,禁止运行时热改

---

## §8 Integration

### 8.1 现有模块对接

| 现有模块 | 本 spec 对接方式 |
|---|---|
| `app/api/search.py` | 入口改为调 `CapabilityWrapper.invoke("query_metric", ...)`(Phase 1.5) |
| `services/llm/nlq_service.py` | 敏感度/限流逻辑迁到 Wrapper,本模块聚焦 NL 编排 |
| `services/tableau/mcp_client.py` | Wrapper 的 `query_metric` capability 作为其 downstream |
| `services/llm/service.py` | LLM 调用成本接入 `CostMeter` |
| SPEC 16(Events) | Wrapper 可发 `capability.invoked` / `capability.denied` 事件到事件总线 |

### 8.2 LLM Prompt 契约变更(Phase 1.5)

LLM 不再输出 VizQL JSON,改为输出 capability 调用:
```json
{
  "capability": "query_metric",
  "params": {
    "datasource_id": 17,
    "metric": "sales_amount",
    "dims": ["region"],
    "filters": [{"field":"order_date","op":"QUARTER","value":"Q1"}],
    "aggregation": "SUM"
  },
  "reasoning": "用户问 Q1 各区域销售额,选 sales_amount 聚合,region 分组"
}
```

**收益**:LLM 输出 schema 收窄 80%,OI-07 JSON 稳定性问题自然消解。

---

## §9 Diagrams

### 9.1 分层图

```
┌─ LLM (NL 理解) ────────────────────────────┐
│ 仅看到业务 capability 定义,不接触 VizQL      │
└──────────────────┬─────────────────────────┘
                   ▼
┌─ Capability Wrapper ───────────────────────┐
│  Registry │ Authz │ Sensitivity │ RateLim   │
│  Cache    │ CircuitBreaker │ CostMeter     │
│  Audit(trace_id)                           │
└──────────────────┬─────────────────────────┘
                   ▼
┌─ capability 实现(business params → VizQL) ┐
│  query_metric / search_asset / ...         │
└──────────────────┬─────────────────────────┘
                   ▼
┌─ MCP Client / SQL Engine / REST Adapter ──┐
│  per-connection 隔离                        │
└────────────────────────────────────────────┘
```

### 9.2 调用时序

```mermaid
sequenceDiagram
  participant API as /api/search/query
  participant W as CapabilityWrapper
  participant R as Registry
  participant G as Guards (authz/sens/rate)
  participant Cap as query_metric.run
  participant MCP as TableauMCPClient
  participant A as Audit

  API->>W: invoke(principal, "query_metric", params, trace)
  W->>R: get("query_metric")
  R-->>W: definition
  W->>G: check all guards
  G-->>W: ok | raise CAP_00X
  W->>Cap: run(params)
  Cap->>MCP: query_datasource(vizql)
  MCP-->>Cap: rows
  Cap-->>W: CapabilityResult
  W->>A: write(record)
  W-->>API: CapabilityResult
```

---

## §10 Tests

### 10.1 单元

- [ ] Registry 加载不合法 YAML → 启动失败 + CAP_010
- [ ] Authz 不足 → CAP_001,审计记 `status=denied`
- [ ] params 不符 Schema → CAP_002
- [ ] 敏感度拦截 → CAP_003,审计 `redacted_fields` 非空
- [ ] 限流触发 → CAP_004,`Retry-After` 头
- [ ] 缓存命中 → 下游不调用,`meta.cached=true`
- [ ] 熔断 open → CAP_006;half_open 放 1 试探
- [ ] Capability 实现抛异常 → CAP_009,审计含堆栈摘要

### 10.2 集成

- [ ] LLM 输出 `{capability, params}` → Wrapper 跑通 E2E
- [ ] 并发 30 req/user 触发限流
- [ ] Tableau 连续 5 失败触发熔断
- [ ] Cache 跨用户角色不串(analyst/admin 不共享 key)

---

## §11 Open Issues

| # | 问题 | 级别 | 候选方案 |
|---|---|---|---|
| OI-A | Capability YAML 热加载 vs. 重启加载 | P2 | 重启为主,admin API 支持软 reload |
| OI-B | Rate limit 跨实例一致性 | P1 | Redis Lua 原子脚本 |
| OI-C | Circuit breaker 状态跨实例同步 | P2 | 单实例本地即可,或 Redis pub/sub |
| OI-D | LLM token 成本归因(多租户) | P2 | CostMeter 存 `bi_capability_invocations.llm_tokens_*` |
| OI-E | Capability 版本化(schema 演进) | P3 | YAML 加 `version` 字段,兼容性矩阵 |
| OI-F | 多后端(Power BI)时 capability 是否统一 | P3 | capability 抽象,backend 可选 |

---

## §12 References

- [[tech-capability-audit-v1]] — Phase 1 审计骨架(已 ready)
- [[tech-mcp-client-rewrite]] — 下游 MCP 接入层
- [[tech-embedding-retrieval]] — 召回层(与本 spec 平行)
- [[tech-homepage-askbar]] — 前端入口
- SPEC 14 NL-to-Query Pipeline — LLM 输出 schema 变更的上游
- `SPEC_DEVELOPER_PROMPT_TEMPLATE.md` §通用约束 + 交付纪律
