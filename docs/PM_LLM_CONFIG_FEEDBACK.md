# LLM 配置管理页 用户反馈执行方案

> 页面路由：`/system/llm-configs`
> 主文件：`frontend/src/pages/admin/llm-configs/page.tsx`
> 分析日期：2026-04-18

---

## 反馈分析

### 反馈 1：列宽太窄——"优先级"和"运行状态"列内容展示不开

**根因**

表格容器限定了 `max-w-5xl`（约 1024px），但 7 列共用了这个宽度，且"运行状态"列同时承载了 RunStatusBadge（最宽时文字"检测中…"约 72px）和 Toggle Switch（约 40px），两个元素并排共需约 128px，而列本身没有显式 min-width，导致内容被压缩换行或截断。

- page.tsx 第 629 行：`max-w-5xl`（容器宽度上限）
- page.tsx 第 724 行：`优先级` 列无宽度声明，`text-center` 但内容窄
- page.tsx 第 725 行：`运行状态` 列无宽度声明
- page.tsx 第 758-782 行：RunStatusBadge + Toggle Switch 并排在同一列

"优先级"列仅显示一个数字，但因列未设 min-width，会被更宽的列挤压，数字"0"或"10"本身不会换行，但 th/td 内边距和字符宽度加在一起仍可能触发整列过窄。

**影响**

"运行状态"列里的 Badge 文字与 Toggle 并排后，在标准 1280px 屏幕上可能相互挤压，导致 Badge 文字被截断或 Toggle 跑到下方，信息密度过高、视觉混乱。"优先级"列表头宽度与内容不一致，体验粗糙。

**修复方案**

方案一（推荐）：将 Toggle Switch 从"运行状态"列中移出，单独拆为一列"启用"。这样每列职责单一，宽度更好控制。

| 列 | 修改后 |
|---|---|
| 运行状态 | 只放 RunStatusBadge，加 `min-w-[96px]` |
| 启用（新列） | 只放 Toggle Switch，加 `w-[56px] text-center` |
| 优先级 | 加 `w-[60px] text-center` 固定宽度 |

方案二（最小改动）：在现有"运行状态"列的 `<th>` 和 `<td>` 上增加 `style={{ minWidth: 148 }}`，防止被压缩。同时对"优先级"列加 `style={{ width: 72 }}`。

**建议采用方案一**，同时可以把容器 `max-w-5xl` 改为 `max-w-6xl`，给表格更多呼吸空间。

具体改动位置：

- `page.tsx` 第 629 行：`max-w-5xl` → `max-w-6xl`
- `page.tsx` 第 678 行：`max-w-5xl` → `max-w-6xl`
- `page.tsx` 第 719-727 行（`<thead>` 行）：新增"启用"列 `<th>`，对"优先级"列加 `style={{ width: 72 }}`，对"运行状态"列加 `style={{ minWidth: 96 }}`
- `page.tsx` 第 754-783 行（`<td>` 行）：RunStatusBadge 单独放"运行状态" `<td>`；Toggle Switch 移入新增的"启用" `<td>`

**优先级：P1**
**工作量：中（约 20-30 行）**

---

### 反馈 2：禁用开关无标题——Toggle Switch 含义不明

**根因**

page.tsx 第 761-781 行，`<label>` 元素中只包含一个 `<input type="checkbox" role="switch">` 和视觉样式的 `<div>`，没有任何可见文字说明，也没有 `aria-label` 或 `title` 属性：

```
第 761 行：<label className="relative inline-flex items-center cursor-pointer">
第 763 行：  <input type="checkbox" role="switch" className="sr-only peer" .../>
第 769 行：  <div className="w-8 h-4 rounded-full ...">  ← 纯视觉，无文字
```

Switch 没有独立列标题（混在"运行状态"列中），也没有 tooltip/title 提示，用户只能靠颜色猜测含义（绿色=启用、灰色=禁用）。

**影响**

用户不知道 Toggle 是"启用/禁用"开关，操作前无法预判后果，误操作风险高。屏幕阅读器也无法识别控件用途，无障碍体验不合格。

**修复方案**

最小改动（不拆列）：给 `<label>` 加 `title` 属性，给 `<input>` 加 `aria-label`：

- `page.tsx` 第 761 行：
  - 旧：`<label className="relative inline-flex items-center cursor-pointer">`
  - 新：`<label className="relative inline-flex items-center cursor-pointer" title={cfg.is_active ? '点击禁用' : '点击启用'}>`

- `page.tsx` 第 763-768 行，`<input>` 上增加：
  - `aria-label={cfg.is_active ? `禁用 ${cfg.display_name || cfg.provider}` : `启用 ${cfg.display_name || cfg.provider}`}`

若采用反馈 1 的"方案一"（拆出独立列），则在新"启用"列的 `<th>` 写明"启用"标题，就无需额外 tooltip，两条反馈可一并解决。

**优先级：P1**
**工作量：小（< 10 行）**

---

### 反馈 3：矛盾状态——API Key 显示"未配置"，测试却能成功

**根因**

这是一个**前端展示判断逻辑的 Bug**，分两层：

**第一层：`ApiKeyCell` 的判断条件过严**

page.tsx 第 199 行：

```ts
const hasKey = cfg.has_api_key && cfg.api_key_preview;
```

`&&` 要求两个条件同时为 truthy。但后端 `models.py` 第 56 行显示，当 `api_key_encrypted` 存在但解密失败时，`api_key_preview` 会被设为固定字符串 `"••••••••"`（8 个圆点），这是 truthy；然而如果解密成功但 `_build_api_key_preview` 返回的掩码字符串恰好是空字符串（极端情况），则 `api_key_preview` 为 `""` (falsy)，导致 `hasKey = false`，显示"未配置"——但实际 DB 中有加密 Key，`has_api_key = true`。

更常见的触发路径：后端 `models.py` 第 55-58 行：

```python
if self.api_key_encrypted:
    api_key_preview = self._build_api_key_preview(decrypted) if decrypted else "••••••••"
else:
    api_key_preview = None
```

当 Key 已加密存储但解密失败时，`api_key_preview = "••••••••"`，此时前端 `cfg.has_api_key = true` 且 `cfg.api_key_preview = "••••••••"` 均为 truthy，理论上不会显示"未配置"。

**真正的问题**：`api_key_preview` 字段在某些情况下可能为 `null` 或 `""`，而前端用 `&&` 同时判断了 `has_api_key` 和 `api_key_preview`。如果 `has_api_key = true` 但 `api_key_preview = null`（例如旧版数据迁移时 preview 未生成），前端就会错误显示"未配置"。

**修复方案**

前端仅依赖 `has_api_key` 作为"是否配置"的权威判断，`api_key_preview` 只用于展示指纹，不参与"是否配置"的逻辑判断：

- `page.tsx` 第 199 行：
  - 旧：`const hasKey = cfg.has_api_key && cfg.api_key_preview;`
  - 新：`const hasKey = cfg.has_api_key;`

- 同时，在展示 preview 时做防御性处理（第 221 行）：
  - 旧：`<code ...>{cfg.api_key_preview}</code>`
  - 新：`<code ...>{cfg.api_key_preview || '••••••••'}</code>`

另外建议在测试按钮上增加视觉提示，当 `!cfg.has_api_key` 时将"测试"按钮置灰并加 `title="API Key 未配置，无法测试"`，从入口上避免矛盾状态被触发（但这是附加改动，非核心 fix）。

**优先级：P0（数据显示错误，直接误导用户判断）**
**工作量：小（< 5 行）**

---

### 反馈 4："检测状态"按钮含义不明

**根因**

page.tsx 第 657-662 行，页头右上角有一个按钮，标签文字为"检测状态"：

```tsx
第 657 行：<button
第 658 行：  onClick={() => testAllActive(configs)}
第 659 行：  ...
第 662 行：>
第 663 行：  <i className="ri-refresh-line" />
第 664 行：  检测状态
第 665 行：</button>
```

该按钮实际触发 `testAllActive`，即对所有 `is_active=true` 的配置发起 `/api/llm/config/test` 请求，并将结果映射到"运行状态"列的 RunStatusBadge 4 态（running / checking / error / disabled）。

用户看到"检测状态"时，无法理解：
1. "检测"的对象是什么（所有配置？当前选中的？）
2. "检测"的结果会反映在哪里（"运行状态"列？还是会弹出对话框？）
3. 与每行的"测试"按钮有何区别

此外 `title` 属性（第 659-661 行）虽然有提示文字"重新检测所有配置连接状态"，但 tooltip 默认需要 hover 才能看到，初次使用时用户几乎不会发现。

**影响**

用户不敢随意点击，或点击后不知道发生了什么（页面无明显 loading 反馈在按钮自身上），造成困惑。

**修复方案**

1. **改按钮文案**：将"检测状态"改为"重新检测连接"，更直接说明动作对象和目的。

2. **增加点击后的视觉反馈**：点击后按钮文字临时变为"检测中…"并显示 spinner，检测完成后恢复。需要增加一个 `isCheckingAll` state。

3. **"运行状态"列增加列说明**：将表头"运行状态"改为"连接状态"，并在旁边加一个 `(i)` 图标，hover 时展示 tooltip："每次加载页面或点击「重新检测连接」时自动更新"。

具体改动位置：

- `page.tsx` 第 664 行：
  - 旧：`检测状态`
  - 新：`重新检测连接`

- `page.tsx` 第 725 行（"运行状态"列 `<th>`）：
  - 旧：`运行状态`
  - 新：`连接状态` + `<span title="每次加载或点击「重新检测连接」时自动更新" className="ml-1 text-slate-400 cursor-help text-xs">(?)</span>`

- `page.tsx` 新增 state（约第 332 行 `togglingId` 附近）：
  - 新增：`const [checkingAll, setCheckingAll] = useState(false);`

- `page.tsx` `testAllActive` 函数调用处（第 657-665 行按钮）：
  - 将 `onClick` 改为异步包装，前后设置 `checkingAll` 状态
  - 按钮文字改为：`{checkingAll ? '检测中…' : '重新检测连接'}`
  - 图标改为：`{checkingAll ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'}`

**优先级：P2**
**工作量：中（约 15-20 行）**

---

## 优先级排序

| 优先级 | 反馈编号 | 标题 | 工作量 | 可并行 |
|--------|---------|------|--------|--------|
| P0 | 反馈 3 | API Key 显示"未配置"但实际已配置（数据错误） | 小（< 5 行） | 是 |
| P1 | 反馈 1 | 列宽太窄，优先级/运行状态列展示不开 | 中（20-30 行） | 是 |
| P1 | 反馈 2 | Toggle Switch 无标题，含义不明 | 小（< 10 行） | 是，建议与反馈 1 合并处理 |
| P2 | 反馈 4 | "检测状态"按钮含义不明 | 中（15-20 行） | 是 |

**注意：反馈 1 和反馈 2 高度相关**——若采用"拆出独立启用列"的方案，两条反馈的改动可以合并在一次 PR 中完成，避免重复改动表格结构。建议 coder 将 P1-反馈1 和 P1-反馈2 作为同一个 task 交付。

---

## 交付清单

> 给 coder 的精确改动列表，按文件和行号排列。
> 所有改动仅在 `frontend/src/pages/admin/llm-configs/page.tsx` 中，无需改动后端。

### Task A（P0）——修复 API Key 展示逻辑（反馈 3）

**文件**：`frontend/src/pages/admin/llm-configs/page.tsx`

| # | 行号 | 旧内容 | 新内容 | 说明 |
|---|------|--------|--------|------|
| A1 | 199 | `const hasKey = cfg.has_api_key && cfg.api_key_preview;` | `const hasKey = cfg.has_api_key;` | 仅以 `has_api_key` 作为权威判断 |
| A2 | 221 | `<code ...>{cfg.api_key_preview}</code>` | `<code ...>{cfg.api_key_preview \|\| '••••••••'}</code>` | 防御 preview 为 null 的边界情况 |
| A3 | 788-795（"测试"按钮） | `disabled={evidence?.status === 'testing'}` | 增加：`disabled={evidence?.status === 'testing' \|\| !cfg.has_api_key}` 并加 `title={!cfg.has_api_key ? 'API Key 未配置，无法测试' : undefined}` | 避免无 Key 时仍可点测试 |

验收：配置了 API Key 的记录显示指纹掩码（如 `sk-•••••3f2a`）和"已配置"状态，不再显示"未配置"。

---

### Task B（P1）——拆分列 + Switch 增加语义（反馈 1 + 反馈 2 合并）

**文件**：`frontend/src/pages/admin/llm-configs/page.tsx`

| # | 行号 | 旧内容 | 新内容 | 说明 |
|---|------|--------|--------|------|
| B1 | 629 | `max-w-5xl` | `max-w-6xl` | 扩大页面最大宽度 |
| B2 | 678 | `max-w-5xl` | `max-w-6xl` | 同上（Content 区域） |
| B3 | 724 | `<th ... >优先级</th>` | `<th ... style={{ width: 72 }}>优先级</th>` | 固定优先级列宽 |
| B4 | 725 | `<th ... >运行状态</th>` | `<th ... style={{ minWidth: 112 }}>连接状态</th>` | 改名，固定最小宽度 |
| B5 | 725 后（新增） | —— | `<th className="px-4 py-3 text-center font-medium text-slate-600" style={{ width: 64 }}>启用</th>` | 新增"启用"列表头 |
| B6 | 756-783（`<td>` 运行状态区域） | RunStatusBadge + Toggle 并排在一个 `<td>` | 将 `<td>` 内 flex 容器拆分：RunStatusBadge 留在该 `<td>`，Toggle Switch 移入紧随其后的新 `<td>` | 职责分离 |
| B7 | 新增 `<td>`（Toggle 专属） | —— | `<td className="px-4 py-3 text-center"><label ... title={cfg.is_active ? '点击禁用' : '点击启用'}><input ... aria-label={cfg.is_active ? \`禁用 ${cfg.display_name}\` : \`启用 ${cfg.display_name}\`} /></label></td>` | 独立列 + 语义标注 |
| B8 | 244（`TestEvidenceRow`，`colSpan={8}`） | `colSpan={8}` | `colSpan={9}` | 新增一列后 colSpan 需同步更新 |
| B9 | 274（同上） | `colSpan={8}` | `colSpan={9}` | 同上 |

验收：在 1280px 屏幕下，优先级列、连接状态列、启用列均能完整展示内容，不换行；Toggle Switch 下方有"启用"列标题；Toggle 有 title tooltip 说明操作含义。

---

### Task C（P2）——"检测状态"按钮文案与反馈优化（反馈 4）

**文件**：`frontend/src/pages/admin/llm-configs/page.tsx`

| # | 行号 | 旧内容 | 新内容 | 说明 |
|---|------|--------|--------|------|
| C1 | 约 332 行（state 声明区） | —— | `const [checkingAll, setCheckingAll] = useState(false);` | 新增 loading state |
| C2 | 657-665（按钮） | `onClick={() => testAllActive(configs)}` | 改为异步 handler：`onClick={async () => { setCheckingAll(true); await testAllActive(configs); setCheckingAll(false); }}` | 按钮自身有 loading 反馈 |
| C3 | 663（图标） | `<i className="ri-refresh-line" />` | `<i className={checkingAll ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'} />` | 图标随检测状态变化 |
| C4 | 664（文字） | `检测状态` | `{checkingAll ? '检测中…' : '重新检测连接'}` | 文案更直白 |
| C5 | 725（"连接状态"列表头，与 B4 合并） | `连接状态` | `连接状态 <span title="每次加载或点击「重新检测连接」时自动更新" className="ml-1 text-slate-400 cursor-help">(?)</span>` | 帮助提示说明列含义 |

验收：点击按钮后按钮立即显示"检测中…"并转圈，完成后恢复；表头"连接状态"有 `(?)` hover 说明；列名"连接状态"而非模糊的"检测状态"。

---

## 附注

1. Task A（P0）可以独立上线，无依赖，建议最先合并。
2. Task B 和 Task C 可并行开发，但 Task C 的 C5 步骤与 Task B 的 B4 步骤涉及同一列表头，合并 PR 时需要 coder 协调，避免 git 冲突。
3. 以上所有改动均在前端，无需联调后端接口。
4. `TestEvidenceRow` 组件（第 240 行）的 `colSpan` 如有进一步列数变动需同步更新，否则证据副行展示会错位。
