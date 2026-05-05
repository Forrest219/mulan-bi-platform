# Spec 20 Bug Fix Patch: ScopeProvider 双实例问题

> 日期：2026-04-30 | 类型：Bug Fix Clarification | 影响范围：Phase 2 组件树 + home/page.tsx

---

## 问题描述

### 现象
登录后访问首页，`ScopePicker` 下拉框显示"全部"和"mcp_test_0419"两个连接项，切换后 `OpsSnapshotPanel` 能正确刷新。但 `AskBar` 仍然显示"请先添加连接，再开始提问"，说明 `AskBar` 内部的 `noConnection` 判断基于空白的 connections 列表。

### 根因
`pages/home/page.tsx` 和 `features/ops-workbench/OpsWorkbench.tsx` 各有一个 `ScopeProvider`。

| 层级 | 组件 | ScopeProvider 来自 | 影响 |
|------|------|--------------------|------|
| 外层 | `HomePage` → `ScopeProvider` | `pages/home/context/ScopeContext.tsx` | `AskBar` 的 `noConnection` 判断 |
| 内层 | `OpsWorkbench` → `ScopeProvider` | `features/ops-workbench/ScopeContext.tsx` | `ScopePicker`、`OpsSnapshotPanel` |

两个 `ScopeProvider` 各自独立调用 `listConnections()` API，导致 `AskBar` 和 `ScopePicker` 看到不同的 connections 状态。

---

## Spec 修复内容

### 3.1 组件树（修正）

**Phase 2 完成后的组件树应为：**

```
HomePage /
└── OpsWorkbench          (features/ops-workbench/OpsWorkbench.tsx)
    └── ScopeProvider     (features/ops-workbench/ScopeContext.tsx) ← 唯一
        └── OpsWorkbenchInner
            ├── ScopePicker
            ├── [idle 态]
            │   ├── WelcomeHero
            │   ├── SuggestionGrid
            │   └── OpsSnapshotPanel
            ├── [result 态]
            │   ├── AskBar
            │   ├── SearchResult
            │   └── DataUsedFooter
            └── AssetInspectorDrawer
```

**关键约束：**
- `ScopeProvider` **只能有一个**，位于 `OpsWorkbench` 内部
- `pages/home/page.tsx` **不得**再包 `ScopeProvider`
- `pages/home/context/ScopeContext.tsx` 应**删除或废弃**，由 `features/ops-workbench/ScopeContext.tsx` 替代

### 3.2 状态驱动方式（确认）

> 原 Spec Section 3.2 补充说明：
>
> **ScopeContext 是单一实例**：整个首页（含 `ScopePicker`、`AskBar`、`OpsSnapshotPanel`）共享同一个 `ScopeContext` 实例，由 `OpsWorkbench` 根组件提供。不得在 `OpsWorkbench` 外部再包 `ScopeProvider`。

### Phase 2 修改条目（补充）

**删除：**
- `pages/home/context/ScopeContext.tsx` — 功能已被 `features/ops-workbench/ScopeContext.tsx` 取代
- `pages/home/page.tsx` 中的 `<ScopeProvider>` 包裹 — 应直接使用 `OpsWorkbench` 提供的内容，不再自行提供 Context

**修改：**
- `pages/home/page.tsx` — 移除 `ScopeProvider`，改为：
  ```tsx
  export default function HomePage() {
    return (
      <OpsWorkbench
        homeState={homeState}
        idleContent={idleContent}
        resultContent={resultContent}
        submittingContent={submittingContent}
      />
    );
  }
  ```

### 文件变更汇总

| 文件 | 操作 | 原因 |
|------|------|------|
| `pages/home/context/ScopeContext.tsx` | **删除** | 被 `features/ops-workbench/ScopeContext.tsx` 取代 |
| `pages/home/page.tsx` | **修改** | 移除 `ScopeProvider`，不再自行提供 Context |
| `features/ops-workbench/ScopeContext.tsx` | 不变 | 已是唯一 ScopeProvider，无需修改 |
| `features/ops-workbench/OpsWorkbench.tsx` | 不变 | 已是 ScopeProvider 所在位置 |
| `features/ops-workbench/ScopePicker.tsx` | 不变 | 从 Context 消费 connections，无冲突 |
| `pages/home/components/AskBar.tsx` | 不变 | 从 Context 消费 connections，无冲突 |

---

## 验收标准（补充）

- [ ] `ScopeProvider` 在整个首页组件树中只有一个实例
- [ ] `ScopePicker` 切换连接后，`AskBar` 的 `noConnection` 同步更新（不再各自独立）
- [ ] `OpsSnapshotPanel` 和 `AskBar` 响应同一个 `scopeConnections` 状态
- [ ] `npm run type-check` 通过
- [ ] 冒烟测试 `admin/admin123 登录后能看到对话输入框` 通过