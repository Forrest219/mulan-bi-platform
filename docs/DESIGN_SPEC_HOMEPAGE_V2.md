# 首页像素级对齐 open-webui 设计方案 v2

> 状态: Ready for Implementation
> 作者: ui-ux-designer
> 日期: 2026-04-18
> 依赖: Spec 25（§2 侦察摘要 / §3 颜色 DNA / §5 组件树 / §7 Tailwind 代码块）
> 目标读者: frontend coder
> 改动范围: 首页（`/`）idle 态视觉和结构；不改动 `/chat/:id` 有结果态核心逻辑；不改动后端。

---

## 0. 体验目标（为什么要做这一版）

- **idle 态干净**：首次进入首页，屏幕上只有"欢迎语 + 4 个建议卡片 + 底部输入框"三类元素，工具栏、运维快照等 BI 专属组件全部隐藏。
- **视觉重心下沉到输入框**：用户第一眼看到问候语居中、输入框在视线下方触手可及，而不是一堆选择器和数据面板。
- **侧边栏有品牌感**：顶部不再是一个孤零零的"新对话"按钮，而是"产品名 + 新建图标"的对称布局，贴近 open-webui。
- **回归修复**：删除上一轮 coder 误加的折叠按钮（上游已决定 sidebar 折叠由 Layout 层面控制，不属于 ConversationBar 自己）。
- **保留 BI 能力**：ScopePicker、OpsSnapshotPanel 不删除、不重命名、不改 API，仅调整 idle 态可见性；有结果态 / 有数据态再度可见。

---

## 1. 改动总览表

| 编号 | 文件 | 改动类型 | 预计影响范围 |
|------|------|---------|-------------|
| 1 | `ConversationBar.tsx` L121-L140 | 删除 + 重排 | 侧边栏顶部布局（回归修复） |
| 2 | `ConversationBar.tsx` L121-L140 | 重设计 | 侧边栏顶部加品牌区 |
| 3 | `page.tsx` L161-L164 | 条件渲染 | idle 态隐藏 ScopePicker |
| 4 | `page.tsx` L266-L273 | 条件渲染拆分 | idle 态隐藏 OpsSnapshotPanel |
| 5 | `WelcomeHero.tsx` 全文件 | 重设计 | 欢迎区样式、层级、字号 |
| 6 | `SuggestionGrid.tsx` 全文件 | 数据 + 样式 | 改为固定 4 条、极简样式 |
| 7 | `page.tsx` L159-L275 | 容器布局 | idle 态垂直居中 |
| 8 | `page.tsx` L247-L263 | 容器样式 | 底部固定区背景 |
| 9 | `page.tsx` L160 + `HomeLayout.tsx` L71 | 背景统一 | 主内容区底色清白 |

---

## 2. 各项改动详情

---

### 改动 1：删除 ConversationBar 折叠按钮（回归修复）

**改动目标**
去掉 `ConversationBar` 顶部由上一轮 coder 误加的 `ri-sidebar-fold-line` 折叠按钮，为改动 2 腾出位置。

**修改文件和位置**
- 文件：`frontend/src/pages/home/components/ConversationBar.tsx`
- 行号：L121-L140（整个"顶部：折叠 + 新建"区块）

**旧 className（原文引用，L121-L140）**
```tsx
{/* 顶部：折叠 + 新建 */}
<div className="flex items-center gap-2 px-3 pt-4 pb-2">
  <button
    onClick={onToggleCollapse}
    className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-lg
               text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
    aria-label="折叠侧边栏"
  >
    <i className="ri-sidebar-fold-line text-base" />
  </button>
  <button
    onClick={handleNew}
    className="flex-1 flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-600
               border border-slate-200 rounded-lg hover:bg-slate-50 hover:shadow-sm transition-all"
  >
    <i className="ri-add-line text-base" />
    新对话
    <span className="ml-auto text-[10px] text-slate-300 select-none">⌘N</span>
  </button>
</div>
```

**新 className（由改动 2 统一给出）**
见改动 2 的"新 className"。本改动本身就是"把折叠按钮那个 `<button>` 完整删除"。

**注意事项**
- `onToggleCollapse` prop 必须保留在 `ConversationBarProps` 中（由 `HomeLayout` 传入），后续若从 Header 或快捷键触发仍会用到。暂时未在 ConversationBar 内部使用的 prop，在 TS 层面会触发 `@typescript-eslint/no-unused-vars`；沿用现有 `collapsed: _collapsed` 的下划线命名惯例，把它改为 `onToggleCollapse: _onToggleCollapse` 即可静默 lint。
- 不要修改 `interface ConversationBarProps`（L26-L29），也不要改 `HomeLayout` 传 prop 的方式。这一保守选择的目的是：让此次改动的 diff 只落在一个文件内，不牵连 Layout。
- 快捷键 `Escape` 折叠 sidebar 的逻辑在 `HomeLayout.tsx` L53-L61，不受影响。

---

### 改动 2：ConversationBar 头部加品牌区（open-webui 风格顶部）

**改动目标**
顶部从"折叠按钮 + 大号新建按钮"改为"小 logo + 产品名 + 右侧新建图标按钮"的对称布局，贴近 open-webui 的侧边栏顶部模式，同时保留搜索框和 `⌘N` 快捷键提示。

**修改文件和位置**
- 文件：`frontend/src/pages/home/components/ConversationBar.tsx`
- 行号：L121-L140

**旧 className**
见改动 1 引用的代码块。

**新 className**
```tsx
{/* 顶部：品牌区 + 新建图标按钮 */}
<div className="flex items-center justify-between h-14 px-3 border-b border-slate-100 flex-shrink-0">
  <div className="flex items-center gap-2 min-w-0">
    <img
      src={LOGO_URL}
      alt=""
      aria-hidden="true"
      className="w-5 h-5 object-contain flex-shrink-0"
    />
    <span className="text-sm font-semibold text-slate-800 truncate">木兰平台</span>
  </div>
  <button
    onClick={handleNew}
    title="新对话  ⌘N"
    aria-label="新对话"
    className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg
               text-slate-400 hover:bg-slate-100 hover:text-slate-700
               transition-colors duration-150"
  >
    <i className="ri-edit-box-line text-base" />
  </button>
</div>
```

**注意事项**
- 需在文件顶部 import `LOGO_URL`：`import { LOGO_URL } from '../../../config';`（与 `WelcomeHero.tsx` 同模式）。
- "木兰平台"文案必须与 Spec 25 §7.2 Sidebar 示例保持一致（L586/L659），避免两处侧边栏产品名不一致。
- `⌘N` 快捷键提示从原先 inline 的 `<span>` 移到 `title` 属性中（浏览器原生 tooltip）。如果后续要保留可见的快捷键徽章，可改为：在 icon 按钮右下方用 `<kbd>` 标签做浮层，但不在本轮强求。
- icon 选择 `ri-edit-box-line`（编辑/新写），比 `ri-add-line`（加号）更贴近 open-webui "新对话 = 打开一个空白写作面板"的语义；若 remixicon 集里该 icon 不存在可替换为 `ri-quill-pen-line` 或 `ri-pencil-line`。
- 点击逻辑 `handleNew` 已存在（L72-L75），不需改。
- 搜索框（L142-L158）保持不动，它在品牌区下方依旧工作。
- `border-b border-slate-100` 让品牌区与搜索框之间有一条细分隔线，呼应 Spec 25 §7.2 L584 `border-b border-slate-100` 的做法。

---

### 改动 3：idle 态隐藏 ScopePicker

**改动目标**
ScopePicker（连接 + 项目筛选）是 BI 专属工具栏，open-webui 首页无对应物，idle 态不应出现。仅在"有流式消息 / 有 SearchResult / 有错误"时显示。

**修改文件和位置**
- 文件：`frontend/src/pages/home/page.tsx`
- 行号：L161-L164

**旧 className**
```tsx
{/* ScopePicker 工具栏（文档流顶部，全宽） */}
<div className="w-full px-6 pt-4 pb-2">
  <ScopePicker />
</div>
```

**新 className**
```tsx
{/* ScopePicker 工具栏 — 仅在非 idle 态展示（idle 态参考 open-webui 不显示工具栏） */}
{homeState !== 'HOME_IDLE' && homeState !== 'HOME_OFFLINE' && (
  <div className="w-full px-6 pt-4 pb-2 border-b border-slate-100">
    <div className="max-w-3xl mx-auto">
      <ScopePicker />
    </div>
  </div>
)}
```

**注意事项**
- 不要删除 `ScopePicker` 组件文件，也不要删除 `import { ScopePicker }`（L23）。
- 不要移除 `ScopeProvider`（L22/L291），因为 `AskBar` 的 `connectionId` prop 仍依赖 `useHomeUrlState` → URL 查询参数，URL 初始化逻辑必须保留。
- idle 态下用户仍可通过 URL 参数 `?connection=<id>` 显式指定连接（既有 `useHomeUrlState` 能力），所以隐藏 ScopePicker 不影响功能，只是在 idle 态不再暴露"切换连接"这个动作。若需在 idle 态让高阶用户切换连接，后续可把它移入 AskBar 的 inline 连接下拉（L113-L127 已存在此能力，会在"多连接"时自动出现）。
- `HOME_OFFLINE` 态下也不显示 ScopePicker（避免离线态误导用户以为可以切换连接）。
- 包一层 `max-w-3xl mx-auto` 让 ScopePicker 的宽度与主内容区对齐，避免它宽到撑满整个屏幕。

---

### 改动 4：idle 态隐藏 OpsSnapshotPanel

**改动目标**
OpsSnapshotPanel 是 BI 运维快照，信息密度高，与 open-webui 风格冲突。idle 态完全隐藏；保留组件本身，未来可迁移到独立的"运维概览"页面。

**修改文件和位置**
- 文件：`frontend/src/pages/home/page.tsx`
- 行号：L266-L273

**旧 className**
```tsx
{/* SuggestionGrid + OpsSnapshotPanel（idle 态展示） */}
{homeState === 'HOME_IDLE' && (
  <>
    <SuggestionGrid onPick={handleExamplePick} />
    <div className="mt-4">
      <OpsSnapshotPanel onOpenAsset={openAsset} />
    </div>
  </>
)}
```

**新 className**
```tsx
{/* SuggestionGrid（idle 态展示，open-webui 风格 4 张卡） */}
{homeState === 'HOME_IDLE' && (
  <SuggestionGrid onPick={handleExamplePick} />
)}
```

**注意事项**
- 不要删除 `OpsSnapshotPanel` 组件文件。
- 需同时删除未使用的 import（L19）：`import { OpsSnapshotPanel } from './components/OpsSnapshotPanel';`，否则触发 `@typescript-eslint/no-unused-vars`。
- `openAsset`（L41）当前仅被 `OpsSnapshotPanel` 消费；移除后 `openAsset` 仍被 `AssetInspectorDrawer` 间接依赖的 URL state 使用，不会成为死代码，**保留 `openAsset` 解构**。
- 保留 `AssetInspectorDrawer`（L278-L284）不动，用户通过消息内链接或未来其他入口仍可打开资产详情抽屉。

---

### 改动 5：WelcomeHero 重设计

**改动目标**
从"中等 logo + 大标题 + 小副标题"变为"问候语为主角 + 副标题弱化 + logo 极小或隐藏"。问候语可根据时段和用户名动态变化，贴近 open-webui "Hello, {name}" 的体验。

**修改文件和位置**
- 文件：`frontend/src/pages/home/components/WelcomeHero.tsx`
- 行号：整个文件（L1-L21）

**旧 className**
```tsx
export function WelcomeHero() {
  return (
    <div className="flex flex-col items-center text-center pt-16 pb-8">
      <img
        src={LOGO_URL}
        alt="Mulan Platform Logo"
        className="w-16 h-16 object-contain mb-5"
      />
      <h1 className="text-3xl font-bold text-slate-700 mb-2">Mulan Platform</h1>
      <p className="text-slate-400 text-sm">数据建模与治理平台 — 用自然语言探索你的数据</p>
    </div>
  );
}
```

**新 className**
```tsx
/**
 * WelcomeHero — 首页欢迎区（idle 态主视觉）
 *
 * 风格：贴近 open-webui，问候语为唯一主角；logo 作为 24px 徽标点缀。
 * 副本：根据当前时段和已登录用户名动态组装。
 */
import { LOGO_URL } from '../../../config';
import { useAuth } from '../../../context/AuthContext';

function greetingByHour(): string {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 12) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

export function WelcomeHero() {
  const { user } = useAuth();
  const name = user?.display_name ?? user?.username ?? '';
  const greeting = name ? `${greetingByHour()}，${name}` : greetingByHour();

  return (
    <div className="flex flex-col items-center text-center">
      <img
        src={LOGO_URL}
        alt=""
        aria-hidden="true"
        className="w-6 h-6 object-contain mb-3 opacity-80"
      />
      <h1 className="text-2xl font-semibold text-slate-800 tracking-tight">
        {greeting}
      </h1>
      <p className="mt-2 text-sm text-slate-500">
        用自然语言向木兰提问，开始探索你的数据
      </p>
    </div>
  );
}
```

**注意事项**
- 去掉原来的 `pt-16 pb-8`，垂直位置由改动 7 的父容器垂直居中控制；组件自身不再设置大块 padding。
- 字号从 `text-3xl font-bold` 降到 `text-2xl font-semibold`，与 Spec 25 §2.2 提到的 open-webui 文字层级一致（`text-sm font-semibold` 是侧边栏用的，主区欢迎语稍大一号用 `text-2xl`）。
- `text-slate-700` 改为 `text-slate-800` 用于主文案对比度更明确（接近 Spec 25 §3.2 Primary 文字）。
- 副标题 `text-slate-400` 升级到 `text-slate-500`：在白色底上 `text-slate-400` 偏灰、可读性不足。
- 不依赖 `AuthContext` 返回的字段变化（`display_name`/`username` 在 `page.tsx` L74 早已判空处理，进入本组件说明 user 已存在），但保险起见这里也做了 `?? ''` 降级。
- 时段问候不应每秒重算：`greetingByHour()` 在组件挂载时计算一次已足够（用户不会停留到跨时段）。不要加 `useEffect` + `setInterval`。
- `LOGO_URL` 已在 `config` 中定义，继续复用。logo 显示与否由 A/B 决策决定；此方案选择"保留 24px 徽标"作为产品辨识；若后期决定完全去 logo，直接删除 `<img>` 标签即可。

**界面文案**
- 主问候：`早上好，张三` / `下午好，李四`（带名字） 或 `早上好`（无名字降级）
- 时段边界文案：
  - 00:00–05:59 → `夜深了`
  - 06:00–11:59 → `早上好`
  - 12:00–13:59 → `中午好`
  - 14:00–17:59 → `下午好`
  - 18:00–23:59 → `晚上好`
- 副标题：`用自然语言向木兰提问，开始探索你的数据`

---

### 改动 6：SuggestionGrid 重设计（4 张 2×2）

**改动目标**
从 5 条建议变为严格 4 条；`grid-cols-1 sm:grid-cols-2` 改为固定 `grid-cols-2`；去掉 `hover:border-blue-400 hover:bg-blue-50` 的蓝色高亮，改为 open-webui 风格的 `hover:bg-slate-50` 中性反馈。

**修改文件和位置**
- 文件：`frontend/src/pages/home/components/SuggestionGrid.tsx`
- 行号：整个文件（L1-L33）

**旧 className**
```tsx
const SUGGESTIONS = [
  '帮我分析近30天订单金额的变化趋势',
  '对比本月和上月各区域销售额表现',
  '找出退款率最高的产品类别',
  '统计最近7天新增客户数及环比变化',
  '分析订单量下降的可能原因',
];

// ...

<div className="grid grid-cols-2 gap-3 w-full max-w-2xl mx-auto px-4">
  {SUGGESTIONS.map((q) => (
    <button
      key={q}
      onClick={() => onPick(q)}
      className="border border-slate-200 rounded-xl p-4 hover:border-blue-400 hover:bg-blue-50
                 cursor-pointer transition-all text-sm text-slate-600 text-left"
    >
      {q}
    </button>
  ))}
</div>
```

**新 className**
```tsx
/**
 * SuggestionGrid — open-webui 风格 2×2 建议卡片
 *
 * 固定 4 条，每张卡 = 一行主问题 + 一行补充说明（可选）。
 * 移动端（<640px）仍保持 2 列，不塌陷为 1 列，避免首屏过高。
 */

interface Suggestion {
  title: string;
  hint?: string;
}

const SUGGESTIONS: Suggestion[] = [
  { title: '分析近 30 天订单金额趋势', hint: '按日聚合并识别拐点' },
  { title: '对比本月与上月各区域销售', hint: '找出同比增长最快的区域' },
  { title: '找出退款率最高的产品类别', hint: '定位需要优化的品类' },
  { title: '统计最近 7 天新增客户与环比', hint: '观察获客节奏' },
];

interface SuggestionGridProps {
  onPick: (question: string) => void;
}

export function SuggestionGrid({ onPick }: SuggestionGridProps) {
  return (
    <div className="grid grid-cols-2 gap-2.5 w-full max-w-2xl mx-auto">
      {SUGGESTIONS.map((s) => (
        <button
          key={s.title}
          onClick={() => onPick(s.title)}
          className="group flex flex-col items-start text-left
                     rounded-xl border border-slate-200 bg-white
                     px-4 py-3
                     hover:bg-slate-50 hover:border-slate-300
                     transition-colors duration-150
                     focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
        >
          <span className="text-sm font-medium text-slate-800">
            {s.title}
          </span>
          {s.hint && (
            <span className="mt-1 text-xs text-slate-500">
              {s.hint}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
```

**注意事项**
- 必须严格 4 条，不要 5 条也不要 6 条，2×2 网格布局的视觉对称是 open-webui 的关键特征之一。
- `grid-cols-2`（不加 `sm:` 断点）意味着移动端窄屏也是 2 列；卡片在窄屏下可能只能容纳 1-2 个字的一行，这由 `title`/`hint` 足够短保证（控制在 16 个汉字内）。如果后续担心 375px 屏挤压，再降级为 `grid-cols-1 sm:grid-cols-2`，**但默认方案是固定 2 列**。
- 去掉 `cursor-pointer`（Tailwind preflight 中 `button` 原本就有指针，多写一遍是冗余）。
- 去掉 `hover:border-blue-400 hover:bg-blue-50` 的蓝色反馈：open-webui 卡片 hover 是**中性灰**（`hover:bg-slate-50`），蓝色反馈留给"主操作"（比如发送按钮）；这样能降低 idle 态的视觉噪声。
- 保留 `focus:ring-blue-500/20` focus 环，满足键盘无障碍。
- 文案从"帮我分析近 30 天订单金额的变化趋势"精简为"分析近 30 天订单金额趋势"（去掉"帮我/的变化"等冗余词），符合 open-webui 建议卡简短直接的风格。

**界面文案（完整 4 条）**

| 主问题 | 补充说明 |
|---|---|
| 分析近 30 天订单金额趋势 | 按日聚合并识别拐点 |
| 对比本月与上月各区域销售 | 找出同比增长最快的区域 |
| 找出退款率最高的产品类别 | 定位需要优化的品类 |
| 统计最近 7 天新增客户与环比 | 观察获客节奏 |

---

### 改动 7：idle 态主内容区垂直居中

**改动目标**
idle 态下欢迎语和建议卡整体垂直居中于屏幕（扣掉底部固定输入框高度），而不是从顶部紧贴开始排列。有结果态仍保持顶部对齐（按消息流正常向下追加）。

**修改文件和位置**
- 文件：`frontend/src/pages/home/page.tsx`
- 行号：L159-L275（整个 `return` 结构需调整容器层级）

**旧 className**
```tsx
return (
  <div className="min-h-screen">
    {/* ScopePicker 工具栏（文档流顶部，全宽） */}
    <div className="w-full px-6 pt-4 pb-2">
      <ScopePicker />
    </div>

    <div className="max-w-3xl mx-auto px-6 pb-36">

      {/* WelcomeHero（始终展示） */}
      <WelcomeHero />
      ...
```

**新 className（骨架示意，具体内容不变，只改容器层级）**
```tsx
return (
  <div className="relative flex flex-col min-h-screen bg-white">
    {/* ScopePicker 工具栏（仅非 idle 态，见改动 3） */}
    {homeState !== 'HOME_IDLE' && homeState !== 'HOME_OFFLINE' && (
      <div className="w-full px-6 pt-4 pb-2 border-b border-slate-100">
        <div className="max-w-3xl mx-auto">
          <ScopePicker />
        </div>
      </div>
    )}

    {/* 主滚动区：idle 态垂直居中，其他态顶部对齐 */}
    <main
      className={[
        'flex-1 flex flex-col w-full',
        homeState === 'HOME_IDLE' ? 'items-center justify-center' : '',
        // 预留底部 AskBar 高度（约 132px）+ 安全边距
        'pb-40',
      ].join(' ')}
    >
      <div
        className={[
          'w-full max-w-3xl mx-auto px-6',
          homeState === 'HOME_IDLE' ? 'space-y-8' : 'pt-6 space-y-6',
        ].join(' ')}
      >
        {/* WelcomeHero：idle 态主视觉，有结果态后仍保留（或条件隐藏，见下方注意事项） */}
        {homeState === 'HOME_IDLE' && <WelcomeHero />}

        {/* 离线提示 */}
        {homeState === 'HOME_OFFLINE' && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            当前网络不可用，恢复后将继续显示上次状态。
          </div>
        )}

        {/* 流式消息 / SearchResult / Loading 指示器 等（保持原逻辑） */}
        {/* ... 略（沿用 L177-L244 的逻辑，去掉外层 mb-6 由 space-y-6 统一控制） */}

        {/* SuggestionGrid：仅 idle 态 */}
        {homeState === 'HOME_IDLE' && (
          <SuggestionGrid onPick={handleExamplePick} />
        )}
      </div>
    </main>

    {/* AskBar 固定底部（见改动 8） */}
    <div
      className="fixed bottom-0 right-0 z-20"
      style={{ left: 'var(--conv-bar-w)', transition: 'left 200ms' }}
    >
      {/* ... 见改动 8 */}
    </div>

    {/* 资产抽屉（不变） */}
    {hasPermission('tableau') && (
      <AssetInspectorDrawer assetId={assetId} tab={tab} onClose={closeAsset} />
    )}
  </div>
);
```

**注意事项**
- 根容器从 `min-h-screen` 改为 `relative flex flex-col min-h-screen bg-white`：必须 `flex-col`，否则 `main` 的 `flex-1` 无法拉伸占满屏高。
- `items-center justify-center` 只在 `HOME_IDLE` 态生效：用条件类字符串，不要把它写死，否则有结果态消息流也会居中导致布局错乱。
- `pb-40`（约 160px）预留 AskBar 固定占位高度（AskBar 自身 + padding ≈ 132px，再留 28px 呼吸），避免最后一条消息被 AskBar 遮挡。
- `WelcomeHero` 是否在有结果态也展示是产品决策：当前方案"仅 idle 态展示"（上面写的 `homeState === 'HOME_IDLE' && <WelcomeHero />`），与 open-webui 一致（用户开始对话后欢迎语消失）。若产品要求"始终展示"可去掉条件。
- 有结果态下 `main` 不居中、`pt-6` 从顶部开始，符合消息流从上往下的阅读习惯。
- `space-y-8`（idle 态）比 `space-y-6`（有结果态）大一档，让欢迎语和建议卡之间有更大呼吸感。

---

### 改动 8：AskBar 底部固定容器视觉优化

**改动目标**
底部固定容器当前 `bg-white/95 backdrop-blur` 与 AskBar 内部的 `bg-white/80 backdrop-blur-sm` 毛玻璃叠加，产生"双层半透明"的视觉混乱。改为：外层实色淡底 + 上缘渐变过渡（让消息流内容在滚动到底部时有自然 fade-out，而不是被硬边截断）。

**修改文件和位置**
- 文件：`frontend/src/pages/home/page.tsx`
- 行号：L247-L263

**旧 className**
```tsx
{/* AskBar（始终可用，C1） */}
<div
  className="fixed bottom-0 right-0 border-t border-slate-200 bg-white/95 backdrop-blur z-20"
  style={{ left: 'var(--conv-bar-w)', transition: 'left 200ms' }}
>
  <div className="max-w-3xl mx-auto px-6 py-4">
    <AskBar
      onResult={handleAskBarResult}
      onError={handleError}
      onLoading={(loading) => {
        handleLoading(loading);
      }}
      onQuestionChange={(q) => setLastQuestion(q)}
      conversationId={currentConversationId ?? undefined}
      connectionId={connectionId}
    />
  </div>
</div>
```

**新 className**
```tsx
{/* AskBar 底部固定容器
    - 外层不使用 backdrop-blur（AskBar 内部已有 backdrop-blur-sm，避免叠加）
    - 上缘 12px 渐变，让消息流滚到底部时自然淡出
    - 背景使用 bg-white（实色），与主区 bg-white 统一 */}
<div
  className="fixed bottom-0 right-0 z-20 pointer-events-none"
  style={{ left: 'var(--conv-bar-w)', transition: 'left 200ms' }}
>
  {/* 上缘渐变过渡条（12px），纯装饰，不拦截事件 */}
  <div className="h-3 w-full bg-gradient-to-t from-white to-white/0" aria-hidden="true" />

  {/* AskBar 实际容器，开启 pointer-events */}
  <div className="bg-white pt-2 pb-5 pointer-events-auto">
    <div className="max-w-3xl mx-auto px-6">
      <AskBar
        onResult={handleAskBarResult}
        onError={handleError}
        onLoading={(loading) => { handleLoading(loading); }}
        onQuestionChange={(q) => setLastQuestion(q)}
        conversationId={currentConversationId ?? undefined}
        connectionId={connectionId}
      />
      <p className="mt-2 text-center text-[11px] text-slate-400">
        回答由 AI 生成，请核对关键数据后使用
      </p>
    </div>
  </div>
</div>
```

**注意事项**
- **关键**：外层 `pointer-events-none` + 内层 `pointer-events-auto` 的组合，让渐变条不拦截消息流的点击/选择（否则用户无法选中最后一条消息的末尾文字）。
- 去掉 `border-t border-slate-200`：Spec 25 §4.2 明确 "Header/Sidebar 以外禁止毛玻璃"的延伸原则是"实色面板不需要额外分隔线"。上缘渐变已经起到分隔作用。
- `bg-white` 是实色，与 `AskBar` 内部 `bg-white/80 backdrop-blur-sm`（L112）形成"外实内虚"的层次，反而比原来 `bg-white/95` 外层再叠一层 `backdrop-blur` 更干净。
- 新增一行 AI 免责提示 `回答由 AI 生成，请核对关键数据后使用`：这是 open-webui 和所有主流 LLM 产品的标配，对 BI 决策场景尤其重要（避免用户盲信 LLM 输出的数字）。文字 `text-[11px] text-slate-400` 保持极弱视觉存在。
- `--conv-bar-w` CSS 变量沿用 `HomeLayout.tsx` L72 的设置，不改。
- `pb-5`（原 `py-4` → `pt-2 pb-5`）：下方留更大空间应对 iOS Safari 底部 Home Indicator 安全区，若需要更严谨可用 `pb-[max(1.25rem,env(safe-area-inset-bottom))]`。
- 发送按钮颜色：AskBar 内部 L161 `bg-blue-700` 保持不变（Mulan 品牌色，与 Spec 25 §3.3 一致）。不要改为 open-webui 的黑色，那是 BI 工具专业感的让步线。

---

### 改动 9：主内容区背景和整体间距统一

**改动目标**
`HomeLayout` 根容器背景从 `bg-slate-50`（浅灰）改为 `bg-white`（纯白），让侧边栏和主内容区共用一个底色，视觉上更贴近 open-webui 的"整体白色、仅靠边框分区"模式；侧边栏的 `bg-white` 和主区的 `bg-white` 之间只靠 `border-r border-slate-200` 分隔。

**修改文件和位置**
- 文件 1：`frontend/src/components/layout/HomeLayout.tsx` L71
- 文件 2：`frontend/src/pages/home/page.tsx` L160（已在改动 7 的新骨架中体现）

**旧 className（HomeLayout.tsx L69-L73）**
```tsx
return (
  <div
    className="flex min-h-screen bg-slate-50"
    style={{ '--conv-bar-w': collapsed ? '0px' : '260px' } as React.CSSProperties}
  >
```

**新 className（HomeLayout.tsx L69-L73）**
```tsx
return (
  <div
    className="flex min-h-screen bg-white"
    style={{ '--conv-bar-w': collapsed ? '0px' : '260px' } as React.CSSProperties}
  >
```

**旧 className（page.tsx L160）**
```tsx
<div className="min-h-screen">
```

**新 className（page.tsx L160，已在改动 7 的新骨架中）**
```tsx
<div className="relative flex flex-col min-h-screen bg-white">
```

**注意事项**
- `ConversationBar.tsx` L118 已经是 `bg-white border-r border-slate-200`，改动 9 后侧边栏和主区同为白底，靠 `border-r` 分隔即可；不要在主区加额外左边框，否则会出现"双线"。
- Spec 25 §3.1 把 "Layer 0 canvas" 定义为 `bg-slate-50`，这里我们选择"单层白色"是对 open-webui 的更彻底贴近。如果之后 UX 审视觉对比度过低（白底白卡分不清），可退回到 Spec 25 §3.1 的双层方案（canvas `bg-slate-50` + 卡片 `bg-white`）。**当前方案倾向单层白**，和 open-webui 首页一致。
- `page.tsx` 未登录态（L74-L96）仍用 `bg-slate-50`，本轮不动，避免登录前后色彩统一的大改。
- 其他页面（`/system/*`、`/chat/:id` 等）不在本轮范围。

---

## 3. 实现顺序建议

### 3.1 依赖关系图

```
改动 1 (删折叠按钮)
   └─► 改动 2 (品牌区重设计)   ← 共享 L121-L140 代码区

改动 3 (隐藏 ScopePicker) ─┐
改动 4 (隐藏 OpsPanel)    ─┼─► 改动 7 (垂直居中容器)   ← 共享 page.tsx return
改动 5 (WelcomeHero 重设计) ─┤
改动 6 (SuggestionGrid 重设计)┘

改动 8 (AskBar 底部容器) ─► 改动 7 (因同处 page.tsx return)

改动 9 (背景统一)  可独立提交，但建议与改动 7 同批
```

### 3.2 推荐批次

| 批次 | 改动编号 | 理由 |
|------|---------|------|
| Batch 1 | 1, 2 | 仅改 `ConversationBar.tsx`，最小单元闭环；与回归修复捆绑先上 |
| Batch 2 | 5, 6 | 独立组件文件（`WelcomeHero.tsx` / `SuggestionGrid.tsx`），彼此不依赖，可并行 |
| Batch 3 | 3, 4, 7, 8, 9 | 全部集中在 `page.tsx` + `HomeLayout.tsx`，必须作为一个整体提交，否则中间状态会出现布局破碎 |

Batch 3 不可拆分的原因：改动 3/4 让容器里元素变少，改动 7 让容器垂直居中，如果只做 3/4 不做 7，idle 态会变成"屏幕顶部孤零零的欢迎语 + 空白一大片 + 底部输入框"，视觉比现在还糟；必须同时生效。

### 3.3 自测清单

完成后至少覆盖以下场景：

- [ ] 未登录 → `/` 显示登录卡片（改动 9 不影响未登录态）。
- [ ] 登录后首次进入 `/`，屏幕中央显示"你好，{用户名}" + 4 张 2×2 建议卡 + 底部输入框；无 ScopePicker、无 OpsSnapshotPanel。
- [ ] 点击任一建议卡，进入 submitting → result 态，此时 ScopePicker 出现于顶部。
- [ ] 再次手动清空返回 idle 态（目前无直接入口，可通过点"新对话"）— ScopePicker 应再次隐藏。
- [ ] 侧边栏顶部显示 logo + "木兰平台" + 右侧铅笔图标；无折叠按钮；点击铅笔可创建新对话。
- [ ] 窗口宽度调至 375px（iPhone SE），建议卡仍为 2 列、欢迎语不溢出、AskBar 可正常输入。
- [ ] 流式消息追加时，最后一行文本不被底部输入框遮挡（验证 `pb-40`）。
- [ ] 键盘 Tab 聚焦能依次命中：新对话按钮 → 搜索框 → 第一张建议卡 → AskBar textarea → 发送按钮，focus ring 清晰可见。

---

## 4. 风险提示（coder 需要小心的地方）

### 4.1 不可回归的功能点

- **ScopeProvider 必须保留**：改动 3 只隐藏 UI，不删 Context。AskBar 的 `connectionId` prop 来源链是 `ScopeProvider → useHomeUrlState → AskBar`，断链会导致无法通过 URL 参数固定连接。
- **`AssetInspectorDrawer` 必须保留**：改动 4 隐藏的是首页入口，但抽屉可通过 URL `?asset=<id>` 直接打开，是既有深链能力。
- **`useStreamingChat` 的消息不因容器变动而丢失**：改动 7 只改容器层级，不要动 `streamingMessages` 的渲染逻辑（L178-L207）。
- **`onToggleCollapse` prop**：改动 1 删掉了内部的折叠按钮，但 prop 类型和 `HomeLayout` 传参必须保留，后续新位置（比如 Header）要接管这个 toggle。

### 4.2 可能的视觉回归

- **Dark mode**：当前方案的类名未带 `dark:` 前缀，与 Spec 25 §10 Non-Goals 一致（本轮不做暗色）。但如果项目的 Tailwind config 开启了 `darkMode: 'class'` 且用户 OS 处于暗色，`bg-white`/`text-slate-800` 会在暗色下刺眼。coder 在实施时需确认 Spec 25 项目当前是否强制 light，否则需补 `dark:` 前缀。
- **`text-[11px]` / `pb-40`**：这类任意值类需确保 Tailwind JIT 开启（`content` 配置正确），否则不生效。
- **Logo 尺寸变化**：`WelcomeHero` logo 从 64px → 24px 的变化幅度大，QA 如果做截图对比回归需要更新基线。

### 4.3 不要顺手做的事

- **不要改 AskBar 内部实现**：改动 8 只改 AskBar 的外包容器，不要动 `AskBar.tsx` 自身（L112 的 `bg-white/80 backdrop-blur-sm` 故意保留）。若同时改 AskBar 会让这次 diff 变大、回归风险翻倍。
- **不要把 OpsSnapshotPanel 迁到新页面**：改动 4 只是从首页隐藏，单独的"运维概览"页是未来另立 spec 的事情。本轮保留文件即可。
- **不要改 remixicon 引入方式**：`ri-edit-box-line` 等依赖全局 remixicon CSS，不要顺手换成 lucide-react 或 heroicons，那是另一次技术决策。
- **不要改 `LOGO_URL` 来源**：继续从 `config` 读，不要内联 SVG。

### 4.4 回滚策略

本设计的每一项改动都是**纯视觉层**，不涉及 state 形状、API 形态、路由变化。若上线后用户反馈不佳，回滚成本 = 还原相关 Tailwind class + 恢复 `SUGGESTIONS` 数组。建议 PR 粒度以 3.2 节的 Batch 为单位，每个 Batch 独立可回滚。

---

## 5. 未在本轮解决的事项（记录以便后续处理）

1. **idle 态切换连接**：ScopePicker 隐藏后，idle 态用户若想切换数据源需依赖 URL 参数或先发一条问题进入有结果态。若产品认为这是障碍，下一轮可考虑：
   - 方案 A：将连接选择作为 AskBar 左下角的 chip/pill（open-webui 的 filter pills 风格）
   - 方案 B：在侧边栏底部用户区上方新增"当前连接"徽标，点击打开下拉
2. **OpsSnapshotPanel 的新家**：建议另立 spec 设计 `/ops` 或 `/system/overview` 页面承载。
3. **Sidebar 折叠控件的新位置**：`onToggleCollapse` 目前只能通过 `Esc` 键或 `HomeLayout` 层快捷键触发，视觉上无控件。未来可在主内容区顶部左上角加一个汉堡/展开图标。
4. **WelcomeHero 时段问候的 i18n**：当前硬编码中文，若 Mulan 未来要做英文版，需抽到 i18n 资源文件。

---

## 变更记录

| 日期 | 版本 | 作者 | 变更内容 |
|------|------|------|---------|
| 2026-04-18 | v2.0 | ui-ux-designer | 初版：9 项改动的精确 Tailwind 级方案，供 coder 执行 |
| 2026-04-19 | v2.1 | pm | ScopePicker 交互改进：idle 态显示、无连接引导、AskBar 感知、项目字段隐藏 |

---

## ScopePicker 交互改进（v2.1 — 2026-04-19）

### 改进背景

v2.0 将 ScopePicker 在 idle 态完全隐藏，但这导致首次进入首页时用户无法感知当前连接状态，也没有添加连接的引导入口。v2.1 对 ScopePicker 的显示逻辑和无连接态体验进行针对性改进，兼顾"视觉干净"与"功能可发现性"两个目标。

---

### 方向 A（P0）— idle 态也显示 ScopePicker

**目标状态**

ScopePicker 在 idle 态始终可见，但采用轻量样式；进入有结果态后，切换为带边框分割线的工具栏样式。

**交互细节**

- idle 态：`ScopePicker` 接收 `variant="idle"` prop，背景透明（`bg-transparent`）、无 border（`border-none`）、无分割线，视觉融入欢迎区，不喧宾夺主。
- 有结果态：保持 v2.0 的原样式（`bg-white border-b border-slate-100`，带工具栏分割线）。

**状态对照表**

| homeState | ScopePicker 可见 | 样式 variant |
|-----------|-----------------|-------------|
| HOME_IDLE | 是 | `"idle"`（透明、无分割线） |
| HOME_SUBMITTING | 是 | `"default"`（带分割线工具栏） |
| HOME_STREAMING | 是 | `"default"` |
| HOME_RESULT | 是 | `"default"` |
| HOME_ERROR | 是 | `"default"` |
| HOME_OFFLINE | 否 | — |

**改动范围**

- 文件：`frontend/src/pages/home/page.tsx`
- 移除 `homeState !== 'HOME_IDLE'` 条件；保留 `homeState !== 'HOME_OFFLINE'` 条件。
- idle 态向 `ScopePicker` 传入差异化 className 或 `variant` prop。
- 文件：`frontend/src/pages/home/components/ScopePicker.tsx`
- 接收 `variant?: 'idle' | 'default'` prop，idle 时切换为轻量 className。

---

### 方向 B（P0）— 无连接时替换为引导入口

**目标状态**

当系统无任何 Tableau 连接时，ScopePicker 的 select 组件替换为引导文字链接，帮助用户找到添加连接的入口。

**交互细节**

- 触发条件：`connections.length === 0 && !connectionsLoading`
- 主链接：`<Link to="/admin/llm-configs">添加数据连接 →</Link>`
  - 样式：`text-sm text-blue-600 hover:text-blue-800 hover:underline`
  - 跳转目标：`/admin/llm-configs`（LLM 配置页，该页管理 Tableau 连接）
- 副文案：`连接后即可开始提问`
  - 样式：`text-xs text-slate-400`，位于主链接右侧或下方
- 有连接时（`connections.length > 0`）：正常渲染原 select 组件，行为不变。
- loading 中：保持现有 loading skeleton 或 disabled 态，不替换为引导链接（避免闪烁）。

**改动范围**

- 文件：`frontend/src/pages/home/components/ScopePicker.tsx`
- 在连接 select 渲染处增加条件分支；引入 `Link`（来自 `react-router-dom`）。

---

### 方向 C 轻版（P1）— AskBar 无连接感知

**目标状态**

当无连接时，AskBar 的 placeholder 给出提示，用户强行提交时显示 inline 错误提示，而不是弹窗或静默失败。

**交互细节**

- placeholder 变更：`connections.length === 0 && !connectionsLoading` 时，placeholder 从默认文案改为 `请先添加连接，再开始提问`。
- 提交拦截：用户强行点击发送/按 Enter 时，不发起请求，在 AskBar 下方（或内部底部）显示 inline 提示文字：`尚未配置数据连接，请先前往添加。`
  - 样式：`text-xs text-amber-600`
  - 不弹 toast、不 disabled AskBar 输入框（保留用户输入内容）。
- 有连接时：行为恢复正常，inline 提示不显示。

**改动范围**

- 文件：`frontend/src/pages/home/components/AskBar.tsx`（或由父组件 `page.tsx` 下传 `hasNoConnection` prop，由 AskBar 内部渲染提示）
- 前置条件：AskBar 须在 `ScopeProvider` 内，方可通过 `useScope()` 获取 `connections`；现有架构已满足此条件。
- 注意：不要 disabled AskBar，保持用户可以输入（可降低挫败感，并允许在有连接后直接发送）。

---

### 方向 D（P1）— 项目字段无数据时隐藏

**目标状态**

ScopePicker 中的"项目"输入框，在功能未启用或数据为空时直接隐藏，避免显示空下拉造成困惑。

**交互细节**

- 隐藏条件：`scopeProject` 列表为空，或相关功能 flag 未启用。
- 隐藏方式：条件渲染（`false` 或 `null`），不用 `visibility: hidden`（避免占位）。
- 本轮以"隐藏"为默认态；待项目功能正式上线后，由 coder 移除隐藏条件。

**改动范围**

- 文件：`frontend/src/pages/home/components/ScopePicker.tsx`
- 在项目输入框渲染处加条件：`{scopeProjectList.length > 0 && <ProjectSelect ... />}`，或暂时注释标注 `// TODO: 项目功能上线后启用`。

---

### 非目标范围（v2.1 不处理）

- 不改动 `/admin/llm-configs` 页面本身的任何逻辑或样式。
- 不改动 `ScopeProvider` 的数据获取逻辑。
- 不改动有结果态下 ScopePicker 的任何已有行为。
- 不新增连接管理的 modal 或 drawer（用户点击引导链接直接跳转页面）。

---

### 验收标准（v2.1）

| 场景 | 预期结果 |
|------|---------|
| 无连接 + idle 态 | ScopePicker 区域显示"添加数据连接 →"链接 + "连接后即可开始提问"副文案；点击链接跳转 `/admin/llm-configs` |
| 无连接 + 强行提交 | AskBar 不发请求，下方出现 `text-xs text-amber-600` inline 提示；AskBar 输入框仍可编辑 |
| 有连接 + idle 态 | ScopePicker 以透明/无分割线轻量样式显示连接 select |
| 有连接 + 有结果态 | ScopePicker 以带分割线工具栏样式显示，行为与 v2.0 一致 |
| HOME_OFFLINE 态 | ScopePicker 不显示（行为不变） |
| 项目字段 | ScopePicker 中无项目下拉框（字段已隐藏） |
| 首页提问功能 | 输入"你有几个数据源"，能得到正确回复（数据源列表，预期 3～5 条） |
