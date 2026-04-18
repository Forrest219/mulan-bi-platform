# 测试规范

> 适用于 Mulan BI Platform 所有功能提交。CI 分两层执行，覆盖率门槛仅在 merge-to-main 阶段强制。

---

## CI 分层

| CI 阶段 | 触发时机 | 内容 |
|---------|---------|------|
| PR 级 | coder PR 提交 | smoke test + lint + type-check |
| merge-to-main | fixer 完成后合并 | 全量测试 + 覆盖率门槛 ≥ 50% |

- coder PR 不要求立即满足覆盖率门槛
- fixer 负责补边界用例、错误路径，使覆盖率达到门槛后方可合并

---

## 后端测试

- **框架**：pytest + pytest-cov（已在 `backend/requirements.txt`）
- **覆盖率门槛**：merge-to-main 时 `services/` ≥ 50%，`app/` ≥ 50%
- **断言**：必须使用硬断言 `assert resp.status_code == 200`，禁止 `if resp.status_code == 200` 静默通过
- **测试文件**：`backend/tests/test_*.py`
- **运行命令**：

```bash
cd backend && pytest tests/ --cov=services --cov=app --cov-fail-under=50
```

- **必须覆盖的场景**：auth（密码哈希/JWT）、health scoring（7 因子算法）、encryption（Fernet）

---

## 前端测试

- **框架**：Vitest + React Testing Library（已在 `frontend/package.json`）
- **测试文件**：`frontend/tests/unit/*.test.{ts,tsx}`
- **运行命令**：

```bash
cd frontend && npm test
```

- **覆盖率**：merge-to-main 时达到 50%+

---

## CI 配置

- `.github/workflows/ci.yml` 中两个 job 均运行测试
- PostgreSQL service container 供后端集成测试使用
- 不跑的测试 = 不存在的测试

---

## tester 检查清单（阶段二验收）

每次 coder 完成实现后，tester 执行以下核查，通过后方可进入阶段三（fixer）：

| 检查项 | 标准 |
|--------|------|
| 核心 happy path | 主流程可跑通，无 500 / 报错 |
| 关键异常场景 | 至少 1 个错误输入有正确的错误响应 |
| SPEC 验收标准覆盖 | SPEC.md 中每条 AC 都有对应测试断言 |
| 类型检查 | `npm run type-check` 零错误 |
| lint | `eslint` / `flake8` 无新增警告 |
| 无遗留 EMERGENCY 注释 | 未经 ADR 登记的临时代码不得进入 PR |
