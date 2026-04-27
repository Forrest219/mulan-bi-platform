# Mulan BI Platform -- Risk Register

> Last updated: 2026-04-27
> Scope: capability layer, agent tools, MCP tools, recent additions

## Risk Categories

- **SEC**: Security
- **REL**: Reliability
- **PERF**: Performance
- **DATA**: Data integrity
- **OPS**: Operations

## Risk Table

| ID | Category | Module | Risk | Likelihood | Impact | Mitigation | Status | Owner |
|----|----------|--------|------|------------|--------|------------|--------|-------|
| R-001 | SEC | `services/metrics_agent/consistency.py` L62-74 | **SQL injection via f-string interpolation.** `table_name` and `formula` are inserted into SQL via f-string (`f"SELECT {formula} AS val FROM {table_name}"`). Although column keys are checked with `isalnum()` and string values are single-quote-escaped, `table_name` and `formula` originate from metric definitions that could be manipulated. The post-hoc `SQLSecurityValidator` check mitigates DDL but not all injection vectors (e.g., `UNION SELECT`). | Medium | High | Replace f-string SQL with parameterized queries. Whitelist `table_name` against actual DB tables. Validate `formula` against an allowlist of aggregate expressions (SUM/COUNT/AVG). | Open | Backend |
| R-002 | SEC | `services/data_agent/engine.py` L313-351 | **LLM prompt injection leading to unauthorized tool calls.** The ReAct engine parses LLM JSON output to determine tool names and parameters. A crafted user question could manipulate the LLM into calling unintended tools or passing malicious parameters. The `_parse_text_response` regex fallback is especially fragile. | Medium | High | Add a tool-call allowlist filter in `_parse_llm_response`. Validate `tool_params` against the tool's `parameters_schema` before execution (partially done via jsonschema, but only when `_HAS_JSONSCHEMA` is True). Make jsonschema a hard dependency. | Open | Backend |
| R-003 | SEC | `services/capability/wrapper.py` L117-119 | **Role-based authz uses string comparison on dict.** Authorization checks `principal.get("role") not in cap_def.roles`. The `principal` dict is passed in from the API layer with no schema enforcement -- a missing or tampered `role` key defaults to `None`, which would deny access (fail-closed), but an empty string `""` could match a misconfigured capability. | Low | Medium | Enforce a strict `principal` schema (Pydantic model) at the API boundary. Validate `role` against a fixed enum before reaching the wrapper. | Open | Backend |
| R-004 | REL | `services/capability/rate_limiter.py` L79-82 | **PostgreSQL rate limit fallback is fail-open.** When PG fallback itself fails (L82), it returns `(999, True)` -- allowing the request through unconditionally. Under sustained Redis outage + PG issues, rate limiting is completely disabled. | Low | High | Change fail-open to fail-closed: return `(999, False)` or raise `CapabilityRateLimited` on PG fallback failure. Add alerting on repeated PG fallback failures. | Open | Backend |
| R-005 | REL | `services/capability/rate_limiter.py` L156-158 | **PG fallback path never enforces the rate limit.** When `self._redis is None`, `_pg_fallback_increment` is called but its return value is discarded -- the rate limit count is never compared against the threshold. Requests always pass through. | Medium | High | After calling `_pg_fallback_increment`, compare `current` against `rate` and raise `CapabilityRateLimited` if exceeded, matching the Redis path logic. | Open | Backend |
| R-006 | PERF | `services/capability/result_cache.py` L145-148 | **`KEYS` command used for cache invalidation.** `self._redis.keys(pattern)` with wildcard is O(N) across the entire Redis keyspace. In production with large key counts, this blocks Redis for other operations. | Low | Medium | Replace `KEYS` with `SCAN` iterator for pattern-based invalidation, or use Redis Hash/Set structures for per-capability cache management. | Open | Backend |
| R-007 | REL | `services/capability/circuit_breaker.py` L186-207, L209-241 | **DB session leak on exception in circuit breaker persistence.** `_load_from_db` and `_save_to_db` create `SessionLocal()` sessions in finally blocks, but if `SessionLocal()` itself throws or `db.execute` throws before reaching `finally`, the session could leak. Also, `__init__` calls `_load_from_db` which hits the database -- if many capabilities are registered simultaneously at startup, this creates a thundering herd of DB connections. | Low | Medium | Use context manager (`with SessionLocal() as db:`) for guaranteed cleanup. Add connection pooling awareness. Consider lazy-loading circuit state on first `allow()` call instead of in `__init__`. | Open | Backend |
| R-008 | SEC | `services/data_agent/tools/schema_tool.py` L157-165 | **Decrypted database password held in memory.** `SchemaTool` decrypts the datasource password and passes it through several function calls. The plaintext password lives in stack frames and could appear in crash dumps, tracebacks, or log messages. | Medium | Medium | Use a short-lived credential wrapper that zeroes memory after use. Ensure `password` is never logged (add redaction to the logger). Consider using SQLAlchemy `create_engine` with encrypted credential vaults instead of in-code decryption. | Open | Backend |
| R-009 | PERF | `services/data_agent/tools/schema_tool.py` L163 | **Ephemeral SQLAlchemy engine created per tool call.** Each `SchemaTool.execute()` call creates a new `create_engine()` + `connect()` + `dispose()` cycle. Under high concurrency, this causes connection storm on the target database and slow response times. | Medium | Medium | Implement a connection pool cache keyed by `(host, port, database)` with a bounded pool size and idle timeout. Reuse engines across calls to the same datasource. | Open | Backend |
| R-010 | SEC | `services/tableau/mcp_client.py` L581-652 | **MCP client instance cache uses `__new__` singleton pattern with mutable class-level dict.** `_instances` and `_last_access` are class-level dicts shared across all threads. While protected by `_instances_lock`, the LRU eviction logic in `__new__` is complex and could lead to stale references if an instance is evicted while another thread holds a reference to it. | Low | Medium | Replace the custom `__new__` singleton with an explicit factory + `threading.local` or `contextvars` storage. Document thread-safety invariants. | Open | Backend |
| R-011 | REL | `services/tableau/mcp_client.py` L370-516 | **MCP session rebuild has no backoff.** When `_SessionExpiredError` is caught, the session is immediately rebuilt and retried. If the MCP server is in a crash loop or returning repeated 400s, this creates a tight retry loop consuming resources. | Medium | Medium | Add exponential backoff with jitter to session rebuild attempts. Cap retries at 2 rebuilds per request. Log and circuit-break if rebuild failures exceed a threshold. | Open | Backend |
| R-012 | DATA | `services/data_agent/runner.py` L51-63, L155-161 | **Agent run DB writes not transactional.** `BiAgentRun` and `BiAgentStep` records are committed individually after each event (`db.commit()` after each step). If the process crashes mid-run, the run record shows `status=running` forever with orphaned steps. No cleanup mechanism exists for stale running records. | Medium | Medium | Add a periodic janitor that marks stale `running` records (older than `total_timeout * 2`) as `failed`. Consider batching step writes and committing less frequently. | Open | Backend |
| R-013 | PERF | `services/data_agent/engine.py` L143-147 | **Total timeout check only at loop start, not during tool execution.** The timeout check `time.time() - start_time >= self.total_timeout` only fires at the beginning of each step iteration. A single long-running tool could exceed `total_timeout` by up to `step_timeout` (30s) before being detected. | Low | Low | Wrap tool execution in `asyncio.wait_for(tool.execute(...), timeout=remaining_budget)` where `remaining_budget = total_timeout - elapsed`. | Open | Backend |
| R-014 | SEC | `services/mcp/concurrent_dispatcher.py` L182-188 | **Hardcoded MCP session ID in concurrent dispatcher.** `session_id = f"concurrent-{site.site_id[:8]}"` is deterministic and reused across requests. An attacker who knows the site_id can predict the session ID and potentially hijack or interfere with concurrent MCP sessions. | Low | Medium | Generate a unique session ID per request using `uuid4()` or similar. Store and manage session lifecycle properly per concurrent query. | Open | Backend |
| R-015 | OPS | `services/capability/cost_meter.py` L39-57, L59-76 | **CostMeter is a no-op.** `record()` only logs and does not write to any persistent store. `aggregate_daily()` returns an empty dict with a TODO comment. There is no actual cost tracking, making it impossible to monitor LLM spend or detect abuse. | High | Medium | Implement `aggregate_daily()` with the SQL query in the TODO comment. Wire `CostMeter.record()` to update token counts in the audit table or a dedicated cost table. | Open | Backend |
| R-016 | REL | `services/capability/wrapper.py` L240-254 | **Capability dispatch is a stub returning mock data.** `_dispatch_capability` returns `{"status": "ok", ...}` with a TODO comment. Any capability invoked through the wrapper will return fake data instead of calling the actual downstream service. | High | High | Implement the dispatcher to route to actual backends (Tableau MCP, SQL Agent, etc.) based on `cap_def.backend`. Add integration tests to verify downstream connectivity. | Open | Backend |
| R-017 | OPS | `services/mcp/site_health_monitor.py` L252-259 | **Health monitor re-query uses broken ORM pattern.** `_record_connection_failure` and `_record_connection_success` call `session.query(type(conn.__class__))` which evaluates to `type(TableauConnection)` = `DeclarativeMeta`, not the model class itself. This will raise an ORM error. | High | Medium | Replace `type(conn.__class__)` with the direct model import: `session.query(TableauConnection).filter(TableauConnection.id == conn.id)`. | Open | Backend |
| R-018 | SEC | `services/data_agent/engine.py` L284-300 | **Silent LLM purpose fallback masks configuration errors.** When `purpose="agent"` fails, the engine silently falls back to `purpose="general"`. Per gotchas.md陷阱 5, this can cause subtle quality degradation (wrong model, wrong temperature) without any alerting. | Medium | Medium | Log at WARNING level when falling back (already done). Add a metric counter for fallback events. Consider failing loud after N consecutive fallbacks instead of silently degrading. | Partial | Backend |
| R-019 | DATA | `services/capability/sensitivity.py` L37-39 | **Sensitivity check skipped when `datasource_id` is absent.** If a capability params dict does not contain `datasource_id`, the sensitivity gate is bypassed entirely. An attacker could omit this field to access sensitive datasources through capabilities that don't enforce the field. | Medium | High | For capabilities that access data (backend=`tableau_mcp`, `sql_agent`), require `datasource_id` in the params schema. Add a fallback that resolves the datasource from the query context if not explicitly provided. | Open | Backend |
| R-020 | PERF | `services/tableau/mcp_client.py` L718-723 | **Unbounded datasource connection cache growth.** `_ds_connection_cache` grows until it hits `_MAX_CACHE_SIZE=500`, then halves by deleting the oldest half. This saw-tooth pattern causes periodic CPU spikes from bulk deletion. The cache has no TTL, so stale connection data (e.g., a renamed site or rotated PAT) persists until eviction. | Low | Medium | Replace with an LRU cache with TTL (e.g., `cachetools.TTLCache`). Set TTL to match the PAT rotation interval. Add explicit invalidation on connection update events. | Open | Backend |
| R-021 | SEC | `services/mcp/concurrent_dispatcher.py` L192-204 | **MCP concurrent dispatcher sends `serverInfo` in initialize request.** The `initialize` payload includes `"serverInfo": {"name": "tableau-mcp", "version": "1.0"}` which is a client-side parameter. Per MCP protocol, `serverInfo` is returned by the server, not sent by the client. This may confuse some MCP server implementations. | Low | Low | Remove `serverInfo` from the client `initialize` request. Only send `clientInfo` and `protocolVersion` as per MCP spec. | Open | Backend |
| R-022 | REL | `services/data_agent/tools/query_tool.py` L106 | **`one_pass_llm` is called with `await` but may not be consistently async.** If `one_pass_llm` blocks synchronously internally (e.g., synchronous HTTP call to LLM), it will block the entire asyncio event loop, causing all concurrent agent sessions to stall. | Medium | High | Verify `one_pass_llm` is fully async (uses `httpx.AsyncClient` or `aiohttp`). If it uses synchronous `requests`, wrap it in `asyncio.to_thread()`. | Open | Backend |
| R-023 | OPS | `services/capability/audit.py` L50-89 | **Audit write failures are silently swallowed.** `write_audit` catches all exceptions and only logs them. If the `bi_capability_invocations` table is missing, full, or the DB connection is down, audit records are permanently lost with no retry or dead-letter queue. | Medium | Medium | Add a local file fallback (append to an audit log file) when DB writes fail. Implement a periodic reconciliation job that replays file-based audit records into the DB. Add alerting on audit write failure rate. | Open | Backend |
| R-024 | PERF | `services/mcp/site_selector.py` L152-208 | **SiteSelector queries DB on every round-robin call.** `_select_by_round_robin()` opens a `SessionLocal()`, queries all active connections and MCP servers, builds SiteInfo objects, and closes the session -- on every single request. No caching. | Medium | Medium | Cache the site list in Redis or in-memory with a 30-60s TTL. Invalidate on connection create/update/delete events. | Open | Backend |
| R-025 | SEC | `services/data_agent/tools/schema_tool.py` L159, L265, L349 | **Remote database connection URLs built with user-supplied credentials.** Database connection strings are constructed with `f"postgresql://{ds.username}:{password}@..."`. If `ds.username` or the decrypted `password` contains special URL characters (e.g., `@`, `/`, `%`), the URL parsing could break or be exploited. `urllib.parse.quote_plus` is used for the password but NOT for the username. | Medium | Medium | Apply `urllib.parse.quote_plus()` to both `ds.username` and `password` in all connection URL construction. Alternatively, use SQLAlchemy's `URL.create()` method which handles escaping automatically. | Open | Backend |

## Summary

| Category | Count | High Impact | Open |
|----------|-------|-------------|------|
| SEC | 9 | 4 | 9 |
| REL | 6 | 2 | 6 |
| PERF | 4 | 0 | 4 |
| DATA | 2 | 1 | 2 |
| OPS | 4 | 1 | 4 |
| **Total** | **25** | **8** | **25** |

## Priority Matrix

### P0 -- Fix Immediately (High Likelihood + High Impact)

- **R-016**: Capability dispatch stub -- production traffic gets mock data
- **R-005**: PG rate limit fallback never enforces limits
- **R-001**: SQL injection in metrics consistency checker

### P1 -- Fix This Sprint (Medium Likelihood + High Impact)

- **R-002**: LLM prompt injection leading to unauthorized tool calls
- **R-019**: Sensitivity check bypass when datasource_id omitted
- **R-022**: Blocking sync call in async agent loop
- **R-004**: Rate limiter fail-open on PG fallback failure
- **R-015**: CostMeter is a no-op (no spend visibility)

### P2 -- Fix Next Sprint

- **R-008**: Decrypted password in memory
- **R-011**: MCP session rebuild with no backoff
- **R-012**: Stale agent run records
- **R-017**: Broken ORM pattern in health monitor
- **R-025**: Username not URL-escaped in connection strings
- **R-018**: Silent LLM fallback masking config errors
- **R-023**: Audit write failures silently swallowed

### P3 -- Track / Low Priority

- **R-003**: Role authz string comparison
- **R-006**: Redis KEYS command in cache invalidation
- **R-007**: DB session leak in circuit breaker
- **R-009**: Ephemeral engine per schema tool call
- **R-010**: MCP client singleton complexity
- **R-013**: Timeout check gap in agent loop
- **R-014**: Predictable MCP session ID
- **R-020**: Unbounded connection cache
- **R-021**: Wrong MCP protocol field
- **R-024**: SiteSelector DB query on every call
