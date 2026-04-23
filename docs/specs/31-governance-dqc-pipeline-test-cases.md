# DQC MVP 测试用例文档

## 测试环境

- Python: 3.11.15
- pytest: 9.0.3
- sqlalchemy: 2.0.49
- psycopg2: 2.9.11
- celery: 5.6.3
- fastapi: 0.136.0
- pydantic: 2.13.1
- 数据库: PostgreSQL (测试环境)
- Redis: 用于 cycle 锁测试
- 测试命令: `pytest backend/tests/unit/dqc/ -v`

## 测试用例清单

### 模块: rule_engine（I7 - uniqueness NULL 处理）

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| RE-UNI-NULL-01 | 多列 uniqueness 含 NULL，(NULL,'a')与(NULL,'a')计为2个不同行 | distinct=3,total=4 | dup_rate=0.25, passed=False | PASS |
| RE-UNI-NULL-02 | 单列 uniqueness 含 NULL，NULL 被当独立值 | distinct=2,total=3 | dup_rate≈0.333, passed=False | PASS |
| RE-UNI-NULL-03 | 全 NULL 行只计一次 | distinct=1,total=3 | dup_rate≈0.667, passed=False | PASS |
| RE-UNI-NULL-04 | MySQL 方言用 ifnull（与 coalesce 等效） | distinct=4,total=5 | dup_rate=0.2, passed=False | PASS |
| RE-UNI-NULL-05 | coalesce 后 distinct count 正确 | distinct=2,total=4 | dup_rate=0.5, passed=False | PASS |

### 模块: rule_engine（I4 - scan_limit profile_json fastpath）

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| RE-SCAN-01 | profile_json 有 row_count=5000，跳过 COUNT(*) | row_count=5000, max_scan=1_000_000 | 仅发 null_rate 查询，不发 COUNT(*) | PASS |
| RE-SCAN-02 | profile_json row_count=200000 超 max_scan_rows=100000 | row_count=200000, max_scan=100000 | passed=False, error 含 max_scan_rows_exceeded | PASS |
| RE-SCAN-03 | profile_json=None 时 fallback 到 COUNT(*) | 无 profile_json, COUNT(*)=80000 | 发 COUNT(*) 查询 | PASS |
| RE-SCAN-04 | profile_json={}（空 dict）fallback 到 COUNT(*) | profile_json={} | 发 COUNT(*) 查询 | PASS |
| RE-SCAN-05 | profile_json.row_count=None fallback 到 COUNT(*) | row_count=None | 发 COUNT(*) 查询 | PASS |
| RE-SCAN-06 | max_scan_rows 配置覆盖默认值 | row_count=150000, max_scan_rows=200000 | 通过，无 COUNT(*) | PASS |

### 模块: orchestrator（I9 - cycles/run scope/asset_ids 互斥）

| 用例ID | 场景 | 期望行为 | 结果 |
|--------|------|---------|------|
| ORCH-MUTEX-01 | asset_ids + scope=hourly_light 同时传 | 抛 400 MulanError | PASS |
| ORCH-MUTEX-02 | asset_ids + scope=incremental 同时传 | 抛 400 MulanError | PASS |
| ORCH-MUTEX-03 | 仅传 asset_ids（scope=full） | 校验通过，无异常 | PASS |
| ORCH-MUTEX-04 | 仅传 scope=hourly_light | 校验通过，无异常 | PASS |
| ORCH-MUTEX-05 | scope=full + asset_ids | 校验通过，无异常 | PASS |
| ORCH-MUTEX-06 | asset_ids=[]（空列表） + scope=hourly_light | bool([])=False，校验通过 | PASS |

### 模块: notification_content（B3 - DQC 通知 builder）

| 用例ID | 事件类型 | title 非空 | content 非兜底 | 结果 |
|--------|---------|-----------|--------------|------|
| NC-01 | dqc.cycle.completed | 是 | 是 | PASS |
| NC-02 | dqc.asset.signal_changed | 是 | 是 | PASS |
| NC-03 | dqc.asset.p0_triggered | 是 | 是 | PASS |
| NC-04 | dqc.asset.p1_triggered | 是 | 是 | PASS |
| NC-05 | dqc.asset.recovered | 是 | 是 | PASS |
| NC-06 | 全部 5 个键注册于 CONTENT_BUILDERS | - | - | PASS |
| NC-07 | 每个 builder 返回 (str, str) 元组 | - | - | PASS |
| NC-08 | DQC 事件不走兜底 "收到事件" 文案 | - | 是 | PASS |
| NC-09 | 未知事件类型走兜底文案 | - | title="系统通知", content 含 "收到事件" | PASS |

### 模块: scorer（12 条边界用例）

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| SC-01 | 全绿得满分 | 全 PASS | CS=100, GREEN | PASS |
| SC-02 | P0 严格边界 | 混合含 P0 | CS<60 → P0 | PASS |
| SC-03 | 60 分是 P1 | CS=60 | P1 | PASS |
| SC-04 | 80 分是 GREEN | CS=80 | GREEN | PASS |
| SC-05 | 79.99 是 P1 | CS=79.99 | P1 | PASS |
| SC-06 | drift=-20 精确值 P0 | drift=-20 | P0 | PASS |
| SC-07 | drift=-19.99 P1 | drift=-19.99 | P1 | PASS |
| SC-08 | drift=-10 精确值 P1 | drift=-10 | P1 | PASS |
| SC-09 | drift=-9.99 GREEN | drift=-9.99 | GREEN | PASS |
| SC-10 | 无 prev 无 drift | prev=None | GREEN, drift=0 | PASS |
| SC-11 | 全绿但 CS 低是 P0 | 全绿 CS=55 | P0 | PASS |
| SC-12 | 全绿 CS=79 是 P1 | 全绿 CS=79 | P1 | PASS |
| SC-13 | 混合含一个 P1 是 P1 | 含 P1 其余绿 | P1 | PASS |
| SC-14 | 混合含一个 P0 是 P0 | 含 P0 其余绿 | P0 | PASS |

### 模块: orchestrator 锁

| 用例ID | 场景 | 期望行为 | 结果 |
|--------|------|---------|------|
| ORCH-LOCK-01 | Redis 锁获取/释放往返 | 锁成功，store 有 key，release 后无 | PASS |
| ORCH-LOCK-02 | 重复获取锁失败 | 第二把锁 try_acquire 返回 False | PASS |
| ORCH-LOCK-03 | 释放需要匹配 token | 错误 token release 不删除 key | PASS |
| ORCH-LOCK-04 | Redis 不可用时 fail-open | 锁成功获取，不抛异常 | PASS |
| ORCH-LOCK-05 | Redis 锁命中时 run_full_cycle | 抛 CycleLockedError(DQC_030) | PASS |

### 模块: signal_events

| 用例ID | 场景 | 期望事件 | 结果 |
|--------|------|---------|------|
| EVT-01 | GREEN→P1 | signal_changed + p1_triggered | PASS |
| EVT-02 | GREEN→P0 | signal_changed + p0_triggered | PASS |
| EVT-03 | P1→GREEN 恢复 | recovered + signal_changed | PASS |
| EVT-04 | 无信号变化 | 无事件 | PASS |
| EVT-05 | 首次运行 GREEN | 无事件 | PASS |
| EVT-06 | 首次运行 P1 | p1_triggered（无 signal_changed） | PASS |

### 模块: rule_engine - null_rate

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| RE-NR-01 | 空列（100% NULL）| actual=1.0 | passed=False | PASS |
| RE-NR-02 | 低于阈值 | null=1,total=100,rate=0.01,阈值=0.05 | passed=True | PASS |
| RE-NR-03 | 高于阈值 | null=10,total=100,rate=0.1,阈值=0.05 | passed=False | PASS |
| RE-NR-04 | 全非 NULL | null=0,total=100 | passed=True | PASS |
| RE-NR-05 | 空表（0 行）| total=0 | passed=True, actual=0.0 | PASS |
| RE-NR-06 | 扫描行数超限 | row_count > max_scan_rows | passed=False, error 含 max_scan_rows | PASS |
| RE-NR-07 | 缺少配置 | 缺 column 或 max_rate | passed=False, error 含 invalid_rule_config | PASS |

### 模块: rule_engine - range_check

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| RE-RC-01 | min_max_all 无违规 | val 在 [min,max] 内 | passed=True | PASS |
| RE-RC-02 | min_max_all 有违规 | val 超出 [min,max] | passed=False | PASS |
| RE-RC-03 | 全 NULL 时忽略 | col 全 NULL | passed=True | PASS |
| RE-RC-04 | avg 在范围内 | avg=50, min=0, max=100 | passed=True | PASS |
| RE-RC-05 | avg 低于 min | avg=50, min=60 | passed=False | PASS |
| RE-RC-06 | avg 高于 max | avg=110, max=100 | passed=False | PASS |
| RE-RC-07 | 缺少 column | 无 column 配置 | passed=False, invalid_rule_config | PASS |

### 模块: rule_engine - freshness

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| RE-FR-01 | PG 新鲜数据通过 | age=5h, max_age=24h | passed=True | PASS |
| RE-FR-02 | PG 陈旧数据失败 | age=30h, max_age=24h | passed=False | PASS |
| RE-FR-03 | 无时间戳数据 | age=None | passed=False, no_timestamp_available | PASS |
| RE-FR-04 | MySQL 方言 | age=5h, max_age=24h | passed=True | PASS |
| RE-FR-05 | 缺少 column | 无 column 配置 | passed=False, invalid_rule_config | PASS |
| RE-FR-06 | 缺少 max_age_hours | 无 max_age_hours | passed=False, invalid_rule_config | PASS |

### 模块: rule_engine - uniqueness

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| RE-UNI-01 | 零重复 | distinct=100,total=100 | dup_rate=0, passed=True | PASS |
| RE-UNI-02 | 全重复 | distinct=1,total=100 | dup_rate=0.99, passed=False | PASS |
| RE-UNI-03 | 多列组合唯一 | distinct=50,total=50 | dup_rate=0, passed=True | PASS |
| RE-UNI-04 | 空表 | distinct=0,total=0 | passed=True, actual=0.0 | PASS |
| RE-UNI-05 | 缺少 columns | config={} | passed=False, invalid_rule_config | PASS |
| RE-UNI-06 | 允许最大重复率 | distinct=99,total=100,rate=0.01,阈值=0.05 | passed=True | PASS |

### 模块: drift_detector

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| DRIFT-01 | prev=None 返回 None | prev=None | drift=None | PASS |
| DRIFT-02 | 相等 prev 无 drift | prev=80,current=80 | drift=0 | PASS |
| DRIFT-03 | prev 更高负 drift | prev=80,current=60 | drift=-25 | PASS |
| DRIFT-04 | prev 更低正 drift | prev=60,current=80 | drift=+25 | PASS |
| DRIFT-05 | 单调递减序列 | 递减序列 | drift 负数 | PASS |

### 模块: profiler

| 用例ID | 描述 | 输入 | 期望 | 结果 |
|--------|------|------|------|------|
| PROF-01 | 取高频值 | 分布 [a:5次,b:3次,c:2次] | top=[a,b,c] | PASS |
| PROF-02 | 空返回空 | 无数据 | [] | PASS |
| PROF-03 | 高 distinct 是 id 列 | distinct_ratio=1.0 | is_id=True | PASS |
| PROF-04 | 低 distinct 不是 id | distinct_ratio=0.1 | is_id=False | PASS |
| PROF-05 | 高 NULL 率不是 id | null_rate=0.8 | is_id=False | PASS |
| PROF-06 | 识别时间戳类型 | col 类型含 timestamp | is_timestamp=True | PASS |
| PROF-07 | 非时间戳 | col 类型不含 timestamp | is_timestamp=False | PASS |
| PROF-08 | to_dict JSON 安全 | 含 datetime | serializable | PASS |

## 回归测试清单（已有测试，确认无回归）

| 测试文件 | 用例数 | 状态 |
|---------|-------|------|
| test_scorer.py | 14 | PASS |
| test_signal_events.py | 6 | PASS |
| test_orchestrator_lock.py | 5 | PASS |
| test_rule_engine_null_rate.py | 7 | PASS |
| test_rule_engine_range_check.py | 7 | PASS |
| test_rule_engine_freshness.py | 6 | PASS |
| test_rule_engine_uniqueness.py | 6 | PASS |
| test_drift_detector.py | 5 | PASS |
| test_profiler.py | 8 | PASS |
| **原有合计** | **64** | **PASS** |

## 新增测试用例清单

| 测试文件 | 新增用例数 | 状态 |
|---------|----------|------|
| test_rule_engine_uniqueness_null_handling.py | 5 | PASS |
| test_scan_limit_profile_json_fastpath.py | 6 | PASS |
| test_cycles_run_scope_assetids_mutex.py | 6 | PASS |
| test_dqc_notification_builders.py | 9 | PASS |
| **新增合计** | **26** | **PASS** |

## 已知限制

- 集成测试在 MVP 中全部 pytest.skip，需 CI 环境完整 E2E
- LLM 分析 V1 范围，MVP 不测试
- BILineagePort V2 范围，MVP 不测试
- `DqcRuleEngine._check_scan_limit` 优先读 `profile_json["row_count"]`，需 `profile_and_suggest_task` 成功写入 profile_json 后才生效；未写入时 fallback 到 COUNT(*)
- 互斥校验测试（I9）直接测试 `RunCycleRequest` 模型和校验逻辑，未启动 FastAPI 测试服务器
