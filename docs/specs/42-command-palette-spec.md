# Spec 42: Command Palette 搜索

> 版本：v0.2 | 状态：已完成 | 日期：2026-05-09

---

## 1. 概述

### 1.1 目的
将 Header 搜索框升级为全局命令面板（Spotlight 风格），支持功能页面快捷搜索、中文关键词匹配、结果带描述展示。

### 1.2 范围
- **包含**：Header 搜索入口、命令面板 UI、sitemap 搜索数据源、描述配置
- **不包含**：搜索结果排序优化、热门搜索、搜索历史

### 1.3 关联文档
| 文档 | 路径 | 关系 |
|------|------|------|
| 首页重构 | docs/specs/21-home-redesign-spec.md | 上游依赖 |
| Spec 23 修复 | docs/specs/23-homepage-login-fixes.md | 同步更新状态 |

---

## 2. UI 设计

### 2.1 入口

- Header 右侧第一个图标按钮（放大镜 `ri-search-line`）
- 点击后打开全屏命令面板，带半透明遮罩
- 支持 `ESC` 键关闭

### 2.2 面板布局

```
┌─────────────────────────────────────────────┐
│ [半透明遮罩 backdrop-blur-sm]               │
│                                             │
│         ┌───────────────────────┐           │
│         │ 🔍 输入框            ESC │           │
│         ├───────────────────────┤           │
│         │ 功能操作              │           │
│         │ 🔹 数据治理 / 数据质量      →    │
│         │    监控指标异常与告警           │  ← 描述
│         │ 🔹 数据质量 / 配置规则      →    │
│         │    监控指标异常与告警           │
│         └───────────────────────┘           │
└─────────────────────────────────────────────┘
```

### 2.3 样式规格

| 元素 | 规格 |
|------|------|
| 面板宽度 | max-w-[620px] |
| 输入框高度 | h-12 |
| 结果区最大高度 | max-h-80 (320px) |
| 遮罩 | bg-black/20 backdrop-blur-sm |
| 面板阴影 | shadow-2xl |
| 面板圆角 | rounded-2xl |
| 图标 | text-lg text-slate-400 |
| 标签 | text-sm text-slate-700 |
| 描述 | text-xs text-slate-400 line-clamp-1 |

---

## 3. 数据模型

### 3.1 搜索入口结构

```typescript
interface SitemapEntry {
  key: string;
  label: string;        // 菜单标签
  group: string;        // 所属分组
  path: string;         // 路由路径
  icon: string;         // Remix Icon 名称
  keywords: string[];   // 搜索关键词
  description?: string; // 功能描述（Command Palette 展示）
}
```

### 3.2 搜索匹配逻辑

- 匹配字段：label + group + keywords（全部 toLowerCase）
- 多词搜索：按空白符 split 后，每 term 必须全部命中（AND 逻辑）
- 返回条数上限：7 条
- 无匹配时显示"无匹配结果"

---

## 4. 配置文件

### 4.1 描述配置

路径：`src/config/sitemap-descriptions.json`

```json
{
  "tableau-assets": {
    "description": "查看和管理 Tableau 看板、工作簿与数据源"
  }
}
```

**维护方式**：直接编辑 JSON 文件，无需改动 TypeScript 代码。

### 4.2 sitemap.ts 职责

- `buildSearchEntries(role, hasPermission)` — 根据权限过滤，返回用户可访问的搜索入口
- `searchEntries(entries, query)` — 执行关键词匹配，返回最多 7 条结果

---

## 5. 实现详情

### 5.1 文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `src/components/layout/AppHeader.tsx` | 修改 | 搜索图标 → 命令面板 |
| `src/config/sitemap.ts` | 修改 | 动态导入 JSON 描述 |
| `src/config/sitemap-descriptions.json` | 新增 | 描述配置（独立维护） |

### 5.2 交互行为

| 操作 | 行为 |
|------|------|
| 点击搜索图标 | 打开命令面板，input autoFocus |
| ESC 键 | 清空搜索词 + 关闭面板 |
| 点击遮罩 | 清空搜索词 + 关闭面板 |
| 点击结果 | 跳转到对应路径 + 关闭面板 |
| 输入关键词 | 实时过滤，≤7 条结果 |

---

## 6. 验收标准

- [x] 点击放大镜图标打开命令面板
- [x] ESC 键关闭面板
- [x] ⌘K / Ctrl+K 快捷键打开面板
- [x] 输入关键词显示匹配结果（≤7 条）
- [x] 结果展示 label + group + description
- [x] 点击结果跳转对应页面
- [x] 无匹配时显示"无匹配结果"
- [x] 修改 `sitemap-descriptions.json` 可更新描述
- [x] 面板激活时背景不可滚动
- [x] 无障碍：role="dialog" + aria-modal

---

## 7. 交互增强

### 7.1 全局键盘监听

| 快捷键 | 行为 |
|--------|------|
| `ESC` | 关闭面板，清空搜索词 |
| `⌘K` / `Ctrl+K` | 打开面板 |

实现：组件 mount 时注册 `window.addEventListener('keydown')`，unmount 时移除。

### 7.2 无障碍

- 面板添加 `role="dialog"` + `aria-modal="true"` + `aria-label="搜索功能页面"`
- 遮罩添加 `aria-hidden="true"`
- 面板内部点击阻止冒泡（`onClick={e => e.stopPropagation()}`）

### 7.3 滚动锁定

弹框激活时 `document.body.style.overflow = 'hidden'`，关闭时恢复。

---

## 8. 非目标

- 不实现搜索历史
- 不实现热门搜索
- 不改变搜索排序算法
- 不修改 AppSidebar 搜索（独立功能）