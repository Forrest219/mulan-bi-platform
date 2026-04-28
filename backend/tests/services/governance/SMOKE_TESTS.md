# Spec 15 冒烟测试用例

> 本文档定义 Spec 15 数据质量监控功能的冒烟测试用例。
> 运行方式：`cd backend && python3 -m pytest tests/api/governance/ tests/services/governance/ -v`

---

## 规则管理

- [ ] 1. 创建 null_rate 规则成功
- [ ] 2. 创建重复规则返回 GOV_006
- [ ] 3. analyst 角色创建规则返回 403
- [ ] 4. 更新规则字段（name, severity, threshold）
- [ ] 5. 启用/禁用规则切换（toggle）
- [ ] 6. 删除规则
- [ ] 7. 获取规则详情
- [ ] 8. 规则列表分页正确（page, page_size）
- [ ] 9. 规则列表按 datasource_id 筛选

## 检测执行

- [ ] 10. 手动触发检测（POST /execute）需要 admin/data_admin
- [ ] 11. 单条规则执行（POST /execute/rule/{rule_id}）
- [ ] 12. 大表规则熔断（max_scan_rows 生效）
- [ ] 13. execute 无参数返回 GOV_002
- [ ] 14. execute 针对不存在的数据源返回 GOV_010

## 评分

- [ ] 15. 全通过评分 = 100
- [ ] 16. 全失败评分 = 0
- [ ] 17. 混合场景评分正确
- [ ] 18. health_scan_score + ddl_compliance_score 整合正确

## 查询

- [ ] 19. /results 分页正确
- [ ] 20. /results/latest 返回最新结果
- [ ] 21. /results 按 passed 筛选正确
- [ ] 22. /scores/trend 趋势数据正确
- [ ] 23. /scores/trend 支持 days 参数
- [ ] 24. /dashboard 返回完整看板数据
- [ ] 25. /dashboard 包含 summary、datasource_scores、top_failures

## 清理

- [ ] 26. 90天历史数据清理任务注册（Celery Beat）

---

## 覆盖率目标

| 模块 | 目标覆盖率 | 已覆盖文件 |
|------|-----------|-----------|
| services/governance/scorer.py | ≥ 80% | scorer.py 本身 |
| services/governance/validators.py | ≥ 90% | test_rule_types.py |
| services/governance/sql_builder.py | ≥ 80% | test_sql_builder.py |
| services/governance/executor.py | ≥ 70% | executor.py 本身 |
| services/governance/database.py | ≥ 60% | API 集成测试覆盖 |
| services/governance/models.py | ≥ 70% | API 集成测试覆盖 |
| services/governance/cron_validator.py | ≥ 90% | test_rule_types.py |
| services/governance/rule_types.py | ≥ 80% | test_rule_types.py |
| services/governance/sql_security.py | ≥ 80% | test_sql_builder.py |

---

## 错误码验证清单

| 错误码 | 说明 | 验证场景 |
|--------|------|---------|
| GOV_001 | 质量规则不存在 | GET /rules/{id} 404, PUT /rules/{id} 404, DELETE /rules/{id} 404, /toggle /{id} 404 |
| GOV_002 | 质量检测结果不存在 | GET /results/{id} 404 |
| GOV_003 | 质量扫描任务进行中 | 扫描冲突时返回 409 |
| GOV_004 | 数据源连接失败 | execute 时数据源连接失败返回 400 |
| GOV_006 | 规则已存在 | 创建重复规则返回 409 |
| GOV_010 | 数据源不存在或未激活 | 创建规则时数据源无效返回 400 |

---

## 运行命令

### 单元测试（不依赖数据库）
```bash
cd backend && python3 -m pytest tests/services/governance/test_rule_service.py -v
```

### 集成测试（需要 PostgreSQL）
```bash
cd backend && python3 -m pytest tests/api/governance/test_quality_api.py -v
```

### 全部测试
```bash
cd backend && python3 -m pytest tests/services/governance/ tests/api/governance/ -v
```

### 带覆盖率
```bash
cd backend && python3 -m pytest tests/services/governance/ tests/api/governance/ --cov=services.governance --cov-report=term-missing
```

---

## 测试状态

### 前提条件
```bash
# 需要 PostgreSQL 运行
docker-compose up -d postgres

# 创建测试数据库
psql -h localhost -U mulan -c "CREATE DATABASE mulan_bi_test;" 2>/dev/null || true
```

### 当前状态 (2026-04-27)
- 核心校验逻辑（validators, cron_validator）：直接 Python 验证通过
- 语法检查：已通过 `python3 -m py_compile`
- 集成测试：需要 PostgreSQL 运行后方可执行

### 直接运行验证（不依赖 pytest）
```bash
cd backend && python3 -c "
from services.governance.validators import validate_threshold
from services.governance.cron_validator import validate_cron
validate_threshold('null_rate', {'max_rate': 0.05})
print('Validators work correctly!')
"
```
