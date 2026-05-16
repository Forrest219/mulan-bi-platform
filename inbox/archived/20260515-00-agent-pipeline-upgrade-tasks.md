# Agent Pipeline 升级任务（可并行）

> 创建日期：2026-05-15
> 关联背景：将 Agentic Workflow 建议整合进现有流水线，保留审计链路与门控严谨度
> 执行方式：Task A / B / C / D 可由四个 Coder 窗口同时执行，无强依赖

---

## 依赖关系图

```
Task A ──┐
Task B ──┤──► Task D（汇总更新 AGENT_PIPELINE.md）
Task C ──┘

Task A、B、C 完全并行，互不依赖
Task D 逻辑上最后，但修改内容已在本文件明确，可同步开工
```

---

## Task A — `agents/coder.md`

**执行者**：Coder 窗口 1
**读取文件**：`agents/coder.md`
**输出文件**：`agents/coder.md`（原地修改）

### 变更 A-1：赋予 Terminal 执行权限

在 `# Core Mindset` 末尾追加一条：

```markdown
- **工具闭环**：Coder 拥有 terminal 执行权限，可直接运行测试、lint、编译命令，在本地完成「写代码 → 运行 → 捕错 → 修改」内部循环，无需等待外部反馈。
```

### 变更 A-2：新增 Pre-handoff Checklist 节

在 `## 产出物` 表格之后、`# 权限边界` 之前，插入以下完整节：

```markdown
## Pre-handoff Checklist（交 Tester 前必须全绿）

以下命令必须全部通过，任意失败视为自愈循环继续（上限 3 次不变）：

```bash
# 后端（有 .py 改动时）
cd backend && python -m py_compile $(git diff --name-only | grep '\.py$')
cd backend && pytest tests/ -x -q

# 前端（有前端改动时）
cd frontend && npm run type-check
cd frontend && npm run lint
cd frontend && npm run build    # 改了路由/入口时必跑
```

全绿后方可产出 `IMPLEMENTATION_NOTES.md` 并移交 Tester。
若 3 次自愈后仍有失败项，产出 `IMPLEMENTATION_BLOCKER.md` 升级人工介入。
```

### 验收标准
- [ ] Core Mindset 包含 terminal 权限说明
- [ ] Pre-handoff Checklist 节存在且命令与 CLAUDE.md 验证命令一致
- [ ] 原有产出物表格、权限边界内容未被删改

---

## Task B — `agents/architect.md`

**执行者**：Coder 窗口 2
**读取文件**：`agents/architect.md`
**输出文件**：`agents/architect.md`（原地修改）

### 变更 B-1：Context_Summary 工具验证要求

在 `## Context_Summary.md 结构（5 字段）` 的代码块之后追加：

```markdown
**工具验证规则**：每条结论必须标注来源工具调用，例如：
- `Grep 'class DataSource'` → 发现 3 处引用（`services/datasource.py`、`app/api/datasources.py`、`tests/test_datasource.py`）

禁止仅凭预训练记忆描述受影响模块。未经工具验证的结论必须标注 `[UNVERIFIED]`，并在 `## 5. Potential Risks` 中说明原因。
```

### 变更 B-2：SPEC.md 第 6 节触发条件扩展

找到以下原文：

```
**第 6 节触发条件**：任务涉及并行角色（如 coder + tester 同步展开）时为必填，须包含接口契约、样本数据（正常值/边界值/空值）、Mock 桩声明。
```

替换为：

```markdown
**第 6 节触发条件**（满足任意一条即必填）：
1. 任务涉及并行角色（coder + tester 同步展开）
2. 流水线采用 TDD 模式（Tester 需提前写测试骨架）

必填内容：
- 接口函数签名（含参数类型与返回类型）
- 输入/输出样本数据（正常值 / 边界值 / 空值各至少一组）
- HTTP 状态码约定（API 场景）
- Mock 桩声明（并行场景）
```

### 验收标准
- [ ] Context_Summary 结构后有工具验证规则
- [ ] 第 6 节触发条件变为两条（并行角色 OR TDD 模式）
- [ ] 原有 5 字段结构、SPEC 6 节结构未被删改

---

## Task C — `agents/tester.md`

**执行者**：Coder 窗口 3
**读取文件**：`agents/tester.md`
**输出文件**：`agents/tester.md`（原地修改）

### 变更 C-1：新增 TDD 前置职责

在 `# Responsibilities` 的列表末尾追加：

```markdown
- **测试骨架前置**：当 SPEC.md 第 6 节存在时，在 Coder 开始实现之前，先产出测试骨架（断言结构已写、具体实现留空）。Coder 的交付标准是让这些骨架测试全部跑通。
```

### 变更 C-2：在检查清单最前面插入前置门控

在 `# 检查清单` 表格的第一行（Happy path 之前）插入：

```markdown
| **[前置门控]** Pre-handoff checklist | 收到实现后先验证 `type-check` + `lint` 均无新增错误；有则立即 FAIL 退回 Coder，不进行功能测试 |
```

### 变更 C-3：TESTER_PASS.md 输出格式补充

找到：
```
- 若测试通过，产出 `TESTER_PASS.md`（含每项检查结果）。
```

替换为：
```markdown
- 若测试通过，产出 `TESTER_PASS.md`（含每项检查结果 + CI 命令输出摘要或运行日志链接，确保结果可追溯）。
```

### 变更 C-4：补充缺失的检查项

在检查清单表格末尾追加两行：

```markdown
| IDOR 负例 | 属主资源写入/删除/动作接口覆盖跨用户资源 403/404 场景 |
| Mock 闭环 | 所有 `page.route()`/`route.fulfill()` 的 mock 数据均有 DOM 或后续请求体断言 |
```

### 验收标准
- [ ] Responsibilities 包含"测试骨架前置"
- [ ] 检查清单第一行是前置门控（Pre-handoff checklist）
- [ ] TESTER_PASS.md 输出要求包含 CI 摘要
- [ ] 检查清单包含 IDOR 负例和 Mock 闭环两项
- [ ] `# 边界` 中"不补充测试用例"保留（骨架前置 ≠ 补用例，不冲突）

---

## Task D — `AGENT_PIPELINE.md`

**执行者**：Coder 窗口 4
**读取文件**：`AGENT_PIPELINE.md`
**输出文件**：`AGENT_PIPELINE.md`（原地修改）

> Task D 与 A/B/C 并行时，依据本文件描述执行即可，无需等待 A/B/C 完成。

### 变更 D-1：流水线阶段图插入 TDD 节点

找到流水线图中：
```
[阶段一] architect + coder 澄清对齐
    ↓
[阶段二] coder → 实现 + IMPLEMENTATION_NOTES.md
```

替换为：
```
[阶段一] architect + coder 澄清对齐
    ↓
[阶段一后] tester → 测试骨架（SPEC.md 第 6 节存在时，Coder 开工前完成）
    ↓
[阶段二] coder → 实现（目标：让测试骨架跑通）→ Pre-handoff Checklist 全绿
    ↓
[阶段二] coder → 产出 IMPLEMENTATION_NOTES.md → 移交 Tester
```

### 变更 D-2：Coder 角色行追加 terminal 注释

找到参与角色表格中：
```
| **coder** | 按 SPEC 填空式开发 | [docs/roles/coder.md](docs/roles/coder.md) |
```

替换为：
```markdown
| **coder** | 按 SPEC 填空式开发（含 terminal 执行权限，内部自愈 ≤ 3 次） | [agents/coder.md](agents/coder.md) |
```

### 变更 D-3：所有角色链接从 docs/roles/ 改指 agents/

将参与角色表格中所有 `docs/roles/XXX.md` 链接替换为 `agents/XXX.md`，共 7 处（pm / designer / architect / coder / tester / fixer / reviewer / shipper）。

顶部说明行同步修改：
```
> 角色详情：[`agents/`](agents/)
```

### 变更 D-4：制品清单新增测试骨架行

在制品清单表格中，`| 一 | coder | Clarification_Questions.md | 如有 |` 之前插入：

```markdown
| 一后 | tester | 测试骨架文件（`tests/` 下，命名与功能对应） | SPEC 第 6 节存在时 |
```

### 验收标准
- [ ] 流水线图包含 `[阶段一后] tester → 测试骨架` 节点
- [ ] 阶段二 coder 行注明 Pre-handoff Checklist 全绿
- [ ] 参与角色表所有链接指向 `agents/` 而非 `docs/roles/`
- [ ] 顶部 `角色详情` 指向 `agents/`
- [ ] 制品清单包含测试骨架行
- [ ] 铁规则编号未变动，内容未删减

---

## 合并提交建议

四个 Task 完成后各自验收，统一 commit：

```bash
git add agents/coder.md agents/architect.md agents/tester.md AGENT_PIPELINE.md
git commit -m "feat(agents): agentic workflow upgrade

- coder: add terminal permission + pre-handoff checklist gate
- architect: require tool-verified Context_Summary + expand SPEC sec.6 trigger
- tester: TDD pre-skeleton responsibility + pre-handoff guard + IDOR/mock checks
- AGENT_PIPELINE: insert TDD node, update role links to agents/, add skeleton artifact"
```
