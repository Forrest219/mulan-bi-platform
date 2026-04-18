# Spec 25 — UI/UX 重构：Open-WebUI 启发设计规范

> 状态: Draft
> 作者: architect
> 日期: 2026-04-18
> 依赖: Spec 21（首页重构）, Spec 22（Ask Data 架构）, Spec 24（OpenAI WebUI 架构升级）

---

## 1. 背景与目标

### 1.1 背景

Mulan BI Platform 当前 UI 存在以下问题：

- 登录页缺少"忘记密码"完整流程（路由注册缺失、后端无对应端点）
- 聊天输入框无文件上传/预览能力
- 无文件拖拽遮罩层
- 消息气泡不支持 Markdown 渲染和代码高亮
- 后端无流式输出支持，用户体验为"等待式"
- MFA 验证通过后 AuthContext 未刷新，导致需二次刷新页面
- `/system` 路径直接返回 404

本 Spec 以 open-webui（开源 WebUI 项目）的前端实现为参考基准，结合 Mulan 企业 BI 工具的定位，制定完整的 UI/UX 重构设计规范。

### 1.2 目标

1. 以 open-webui 源码侦察为依据，确立 Tailwind CSS 样式规范（颜色 DNA、毛玻璃、动画时序）
2. 明确四个核心组件（LoginPage、Sidebar、AskBar、DragDropOverlay）的完整实现代码
3. 定义九个 Gap 的验收标准（AC），每条 AC 可直接转化为 Playwright / pytest 测试
4. 为 coder 提供零歧义的实现参考，杜绝救急方案

### 1.3 非目标（Non-Goals）

详见第 10 节。

---

## 2. 参考基准（open-webui 侦察摘要）

以下数据来自对 open-webui 源码的结构性侦察，用于指导样式决策。Mulan 不直接复制，而是在风格对齐后调整为 BI 工具专业感（blue-700 替代 sky-500）。

### 2.1 Login 页面（`src/routes/auth/+page.svelte`）

| 元素 | open-webui 类名 |
|------|----------------|
| 页面容器 | `w-full h-screen max-h-[100dvh] text-white relative` |
| 背景 | `bg-white dark:bg-black` |
| 表单框 | `sm:max-w-md my-auto pb-10 w-full dark:text-gray-100` |
| 输入框 | `w-full text-sm outline-hidden bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-600` |
| 按钮 | `bg-gray-700/5 hover:bg-gray-700/10 ... rounded-full font-medium text-sm py-2.5` |
| 分割线 | `dark:bg-gray-100/10` |

**注意**：open-webui Login 无 `backdrop-blur`，无 `cubic-bezier`。Mulan 使用卡片式布局（`rounded-lg` 边框替代 `rounded-full` 按钮）。

### 2.2 Sidebar（`src/lib/components/layout/Sidebar.svelte`）

| 元素 | open-webui 实现 |
|------|----------------|
| 断点常量 | `BREAKPOINT = 768` |
| 宽度 | CSS 变量 `w-[var(--sidebar-width)]` |
| 背景 | `dark:bg-gray-950` |
| 文字 | `dark:text-gray-200 / dark:text-gray-400` |
| 边框 | `dark:border-gray-850/30 border-e-[0.5px]` |
| 导航项 | `rounded-2xl px-2.5 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition` |
| 展开动画 | `transition:slide={{ duration: 250, axis: 'x' }}`（Svelte 内置，无 cubic-bezier） |
| 移动端遮罩 | `fixed md:hidden z-40 bg-black/60` |

**Mulan 差异**：React 不能直接用 Svelte slide 指令，改用 `transition-[width]`（Desktop）+ `transition-transform`（Mobile）。

### 2.3 ChatInput（`src/lib/components/chat/MessageInput.svelte`）

| 元素 | open-webui 实现 |
|------|----------------|
| 容器 | `rounded-3xl border shadow-lg flex-1 flex flex-col relative w-full` |
| 毛玻璃 | `backdrop-blur-sm`（4px） |
| 背景 | `bg-white/5 dark:bg-gray-500/5` |
| 边框 | `border-gray-100/30 dark:border-gray-850/30 hover:border-gray-200` |
| 图片预览气泡 | `size-10 rounded-xl object-cover`（40x40px） |
| 气泡关闭按钮 | `absolute -top-1 -right-1 bg-white text-black rounded-full size-4 invisible group-hover:visible transition` |
| 工具栏按钮 | `rounded-full size-8 hover:bg-gray-100 dark:hover:bg-gray-800 transition` |
| Filter pills 过渡 | `transition-colors duration-300` |
| 激活 pill | `text-sky-500 dark:text-sky-300 bg-sky-50 dark:bg-sky-400/10 border border-sky-200/40` |

**Mulan 差异**：`sky-500` 替换为 `blue-700`；`bg-white/80`（替代 `bg-white/5`）以提升可读性。

---

## 3. 颜色 DNA 与设计 Token

### 3.1 背景三层

| 层级 | 用途 | 浅色模式 | 深色模式 |
|------|------|---------|---------|
| Layer 0（canvas） | 页面底色 | `bg-slate-50` | `dark:bg-slate-950` |
| Layer 1（卡片） | 卡片、面板 | `bg-white` | `dark:bg-slate-900` |
| Layer 2（内嵌） | 输入框内嵌、代码块 | `bg-slate-50 / bg-slate-100` | `dark:bg-slate-800` |

### 3.2 文字四级

| 级别 | 用途 | 浅色 | 深色 |
|------|------|------|------|
| Primary | 正文、标题 | `text-slate-900` | `dark:text-slate-50` |
| Secondary | 次要说明、元数据 | `text-slate-600` | `dark:text-slate-400` |
| Tertiary | 占位符 | `text-slate-400` | `dark:text-slate-500` |
| Disabled | 禁用态 | `text-slate-300` | `dark:text-slate-600` |

### 3.3 品牌强调色：`blue-700`

> 设计决策：open-webui 使用 `sky-500`，Mulan 改为 `blue-700` 以体现 BI 工具专业感。

| 用途 | Tailwind 类名 |
|------|--------------|
| 主按钮 | `bg-blue-700 hover:bg-blue-800 text-white` |
| 次要按钮 | `bg-white border border-slate-300 text-slate-700 hover:bg-slate-50` |
| Active 导航 | `bg-blue-50 text-blue-700 font-semibold` |
| Focus Ring | `ring-blue-500` |
| 链接 | `text-blue-600 hover:text-blue-700` |
| Active pill | `text-blue-700 bg-blue-50 border border-blue-200/40` |
| Selected 状态 | `bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300` |

### 3.4 交互状态

| 状态 | 类名 |
|------|------|
| Hover | `hover:bg-slate-50 dark:hover:bg-slate-800` |
| Focus | `focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500` |
| Active | `active:bg-slate-100 dark:active:bg-slate-700` |
| Error | `bg-red-50 border-red-200 text-red-600` |
| Warning | `bg-amber-50 border-amber-200 text-amber-700` |
| Success | `bg-emerald-50 border-emerald-200 text-emerald-700` |

### 3.5 z-index 层级表

```
Toast / 全局通知:  z-[100]
Modal:             z-50
Tooltip:           z-50
Dropdown:          z-50
Header:            z-40
Mobile Sidebar:    z-30
Mobile 遮罩:       z-20
Desktop Sidebar:   z-10
```

---

## 4. 毛玻璃（Glassmorphism）使用规范

**唯一允许的强度：`backdrop-blur-sm`（4px）**

### 4.1 适用场景

| 组件 | 背景透明度 | 说明 |
|------|-----------|------|
| AskBar 输入框 | `bg-white/80` | 主输入区，内容清晰优先 |
| 拖拽遮罩 | `bg-slate-50/90` | 遮挡内容但保留层次感 |
| 内容预览气泡 | `bg-white/90` | 附件预览浮层 |

### 4.2 禁止使用场景

- **Sidebar**：实色 `bg-white`，禁止毛玻璃（影响导航可读性）
- **Header**：实色，禁止毛玻璃
- **Dropdown**：实色 `bg-white border`，禁止毛玻璃

### 4.3 完整组合写法

```css
/* AskBar */
backdrop-blur-sm bg-white/80 border border-slate-200/60

/* DragDropOverlay */
backdrop-blur-sm bg-slate-50/90

/* AttachmentBubble */
backdrop-blur-sm bg-white/90 border border-slate-200/40 rounded-xl shadow-sm
```

---

## 5. 组件树结构

### 5.1 LoginPage

```
LoginPage
├── 背景层（bg-slate-50 全屏）
├── 居中卡片容器（max-w-md w-full mx-auto my-auto）
│   ├── Logo / 产品名
│   ├── 表单（逐步展示）
│   │   ├── 步骤 1：用户名 + 密码
│   │   │   ├── InputField（username）
│   │   │   ├── InputField（password）
│   │   │   ├── 忘记密码链接 → /forgot-password
│   │   │   └── 主按钮"登录"
│   │   └── 步骤 2：MFA 验证码（条件渲染）
│   │       ├── InputField（6位验证码）
│   │       └── 主按钮"验证"
│   └── 错误提示区（ErrorBanner）
```

### 5.2 Sidebar（4 态状态机）

```
AppLayout
├── Sidebar（状态: A/B/C/D）
│   ├── SidebarHeader
│   │   ├── Logo（展开态显示文字）
│   │   └── 折叠按钮（ChevronLeft/Right）
│   ├── SidebarNav
│   │   └── NavItem[] （图标 + 文字，折叠态只显示图标 + Tooltip）
│   └── SidebarFooter
│       └── 用户头像 / 设置入口
├── MobileOverlay（状态 C 专用，z-20）
└── MainContent
```

**状态说明：**

| 状态 | 触发条件 | 关键样式 |
|------|---------|---------|
| A Desktop 展开 | 屏幕 ≥ 768px + expanded=true | `w-60 transition-[width] duration-200 ease-in-out` |
| B Desktop 折叠 | 屏幕 ≥ 768px + expanded=false | `w-14 transition-[width] duration-200 ease-in-out` |
| C Mobile 覆层 | 屏幕 < 768px + mobileOpen=true | Sidebar `fixed left-0 top-0 h-screen w-60 z-30 translate-x-0 transition-transform duration-200 ease-out` + Overlay `fixed inset-0 bg-black/30 z-20` |
| D Mobile 隐藏 | 屏幕 < 768px + mobileOpen=false | `-translate-x-full transition-transform duration-200 ease-out` |

> **移动端设计决策（Overlay vs Push）**：Mobile 模式下 Sidebar 采用"覆层（Overlay）"模式而非"推移（Push）"模式。Sidebar 展开时以 `fixed` 定位叠于主内容之上，主内容区域宽度不变、不压缩。这与 open-webui 原实现一致（`fixed md:hidden z-40`），符合移动端用户对浮层导航的认知习惯，且避免在窄屏下主内容被压至不可读。
>
> **Push 模式禁止清单**：若将来切换为 Push 模式，须同步调整 `MainContent` 的 `margin-left` / `padding-left` 动画，并确保不与 Flex 布局产生冲突——两种模式不能混用。
>
> **汉堡菜单触发约束**：`mobileOpen` / `setMobileOpen` 必须提升至 `AppLayout`，由 Header 汉堡按钮持有控制权；Sidebar 组件本身不自持触发逻辑，只接收 `mobileOpen` prop（或通过 `useImperativeHandle` 暴露 toggle ref）。移动端点击遮罩（MobileOverlay）也必须调用同一 `setMobileOpen(false)`，确保状态单一来源。

### 5.3 ChatInput / AskBar

```
AskBar（rounded-2xl backdrop-blur-sm bg-white/80）
├── AttachmentRow（条件渲染，有附件时出现）
│   └── AttachmentBubble[]
│       ├── 图片类型：缩略图 64x64
│       └── 非图片类型：文件名 + 类型图标 + 大小
├── TextareaAutoResize（placeholder="向木兰提问..."）
├── FilterPillsRow（条件渲染）
│   └── FilterPill[]（transition-colors duration-150）
└── ToolbarRow
    ├── AttachButton（Paperclip icon，触发文件选择）
    ├── [其他工具按钮]
    └── SendButton（激活条件：有文字 OR 有附件）
```

### 5.4 DragDropOverlay

```
DragDropOverlay（fixed inset-0 z-50，条件渲染）
├── 毛玻璃背景层（bg-slate-50/90 backdrop-blur-sm）
└── 内容容器（flex items-center justify-center h-full）
    └── 虚线框提示区（border-2 border-dashed border-blue-300 rounded-2xl p-12）
        ├── 上传图标（CloudArrowUpIcon 或 SVG）
        ├── 主文字"释放文件以上传"
        └── 次要文字"支持图片、PDF、文档等格式"
```

---

## 6. 动画状态流转图

### 6.1 Sidebar 状态机

```
                          窗口宽度
                    ┌─────────────────┐
                    │                 │
           ≥768px   │    <768px       │
                    │                 │
    ┌───────────────▼──┐          ┌───▼───────────────┐
    │  Desktop 模式     │          │  Mobile 模式       │
    │                  │          │                   │
    │  ┌─────────────┐ │          │  ┌─────────────┐  │
    │  │  A: 展开态   │ │          │  │  C: 覆层展开 │  │
    │  │  w-60       │ │          │  │  translate-x-0│ │
    │  └──────┬──────┘ │          │  └──────┬──────┘  │
    │         │折叠按钮  │          │         │关闭/点击遮罩│
    │         ▼        │          │         ▼         │
    │  ┌─────────────┐ │          │  ┌─────────────┐  │
    │  │  B: 折叠态   │ │          │  │ D: Mobile隐藏│  │
    │  │  w-14       │ │          │  │ -translate-x-full│
    │  └──────┬──────┘ │          │  └──────┬──────┘  │
    │         │展开按钮  │          │         │汉堡菜单   │
    │         └────────┘          │         └─────────┘
    └──────────────────┘          └───────────────────┘
              │                             │
              └──────── resize 事件 ─────────┘
                    (窗口变化时重新判断)
```

### 6.2 DragDropOverlay 状态机

```
正常态（无遮罩）
    │
    │ dragover 事件（150ms debounce 可选）
    ▼
遮罩出现（opacity: 0 → 1，150ms ease-out）
    │
    ├── dragleave / dragend
    │       │
    │       ▼
    │   遮罩消失（opacity: 1 → 0，100ms ease-in）
    │       │
    │       ▼
    │   正常态
    │
    └── drop 事件
            │
            ▼
        遮罩消失（100ms ease-in）+ 触发文件预览流程（Gap-02）
```

### 6.3 AttachmentBubble 出现/消失动画

```
选择文件 → opacity: 0, scale: 0.9 → opacity: 1, scale: 1（150ms ease-out）
删除文件 → opacity: 1, scale: 1 → opacity: 0, scale: 0.9（100ms ease-in）
```

### 6.4 动画参数汇总表

| 场景 | 属性 | 时长 | 曲线 | Tailwind 类名 |
|------|------|------|------|-------------|
| Sidebar 展开/折叠（Desktop） | width | 200ms | ease-in-out | `transition-[width] duration-200 ease-in-out` |
| Sidebar 滑入/滑出（Mobile） | transform | 200ms | ease-out | `transition-transform duration-200 ease-out` |
| 输入框 focus border | border-color, ring | 150ms | ease-in-out | `transition-colors duration-150` |
| 文件预览气泡出现 | opacity, scale | 150ms | ease-out | `transition-all duration-150 ease-out` |
| 文件预览气泡消失 | opacity, scale | 100ms | ease-in | `transition-all duration-100 ease-in` |
| 拖拽遮罩出现 | opacity | 150ms | ease-out | `transition-opacity duration-150` |
| 拖拽遮罩消失 | opacity | 100ms | ease-in | `transition-opacity duration-100 ease-in` |
| Toolbar pills 切换 | background-color, color | 150ms | ease-in-out | `transition-colors duration-150 ease-in-out` |
| Dropdown 出现 | opacity, transform | 120ms | ease-out | `transition-all duration-[120ms] ease-out` |

---

## 7. 完整 Tailwind 代码块

### 7.1 LoginPage

```tsx
// frontend/src/pages/LoginPage.tsx
import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

type LoginStep = 'credentials' | 'mfa';

export default function LoginPage() {
  const navigate = useNavigate();
  const { checkAuth } = useAuth();

  const [step, setStep] = useState<LoginStep>('credentials');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleCredentials = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setError(data.detail ?? '登录失败');
        return;
      }
      if (data.mfa_required) {
        setStep('mfa');
      } else {
        // 必须先 checkAuth() 刷新 AuthContext，再 navigate — 避免 Gap-06
        await checkAuth();
        navigate('/');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleMfa = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await fetch('/api/auth/mfa/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: mfaCode }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setError(data.detail ?? 'MFA 验证失败');
        return;
      }
      // Gap-06 修复：先 checkAuth() 再 navigate
      await checkAuth();
      navigate('/');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Logo 区 */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-slate-900">木兰 BI 平台</h1>
          <p className="mt-1 text-sm text-slate-500">数据建模与治理平台</p>
        </div>

        {/* 卡片 */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8">
          {/* 错误提示 */}
          {error && (
            <div className="mb-4 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-red-600 text-sm">
              {error}
            </div>
          )}

          {step === 'credentials' ? (
            <form onSubmit={handleCredentials} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  用户名
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                             text-slate-900 placeholder:text-slate-400 bg-white
                             focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                             transition-colors duration-150"
                  placeholder="请输入用户名"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  密码
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                             text-slate-900 placeholder:text-slate-400 bg-white
                             focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                             transition-colors duration-150"
                  placeholder="请输入密码"
                />
              </div>
              <div className="flex justify-end">
                {/* 忘记密码使用 Link 而非 <a href>，避免 SPA 路由陷阱（CLAUDE.md 陷阱 3） */}
                <a
                  href="/forgot-password"
                  className="text-sm text-blue-600 hover:text-blue-700"
                  onClick={(e) => { e.preventDefault(); navigate('/forgot-password'); }}
                >
                  忘记密码？
                </a>
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-blue-700 hover:bg-blue-800 text-white font-medium
                           text-sm py-2.5 rounded-md transition-colors duration-150
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? '登录中...' : '登录'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleMfa} className="space-y-4">
              <p className="text-sm text-slate-600 mb-2">
                请输入认证器 App 中的 6 位验证码
              </p>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  验证码
                </label>
                <input
                  type="text"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  maxLength={6}
                  required
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                             text-slate-900 placeholder:text-slate-400 bg-white text-center
                             tracking-widest font-mono
                             focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500
                             transition-colors duration-150"
                  placeholder="000000"
                />
              </div>
              <button
                type="submit"
                disabled={loading || mfaCode.length !== 6}
                className="w-full bg-blue-700 hover:bg-blue-800 text-white font-medium
                           text-sm py-2.5 rounded-md transition-colors duration-150
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? '验证中...' : '验证'}
              </button>
              <button
                type="button"
                onClick={() => { setStep('credentials'); setMfaCode(''); setError(null); }}
                className="w-full bg-white border border-slate-300 text-slate-700 hover:bg-slate-50
                           font-medium text-sm py-2.5 rounded-md transition-colors duration-150"
              >
                返回
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
```

### 7.2 Sidebar

```tsx
// frontend/src/components/layout/Sidebar.tsx
import { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';

// 注意：React.lazy 只支持 default export（CLAUDE.md 陷阱 2）
// 若需懒加载 Sidebar，须用 .then(m => ({ default: m.Sidebar })) 形式

const BREAKPOINT = 768;

interface NavItem {
  label: string;
  to: string;
  icon: React.ReactNode;
}

interface SidebarProps {
  navItems: NavItem[];
}

export default function Sidebar({ navItems }: SidebarProps) {
  const location = useLocation();
  const [expanded, setExpanded] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < BREAKPOINT);

  useEffect(() => {
    const handleResize = () => {
      const mobile = window.innerWidth < BREAKPOINT;
      setIsMobile(mobile);
      if (!mobile) setMobileOpen(false);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Desktop Sidebar
  if (!isMobile) {
    return (
      <aside
        className={[
          'h-screen bg-white border-r border-slate-200 flex flex-col flex-shrink-0 z-10',
          'transition-[width] duration-200 ease-in-out overflow-hidden',
          expanded ? 'w-60' : 'w-14',
        ].join(' ')}
      >
        {/* Header */}
        <div className="h-14 flex items-center justify-between px-3 border-b border-slate-100 flex-shrink-0">
          {expanded && (
            <span className="font-semibold text-slate-900 text-sm truncate">木兰平台</span>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100
                       transition-colors duration-150 ml-auto"
            aria-label={expanded ? '折叠侧边栏' : '展开侧边栏'}
          >
            {/* ChevronLeft / ChevronRight — 替换为实际 icon */}
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d={expanded ? 'M15 19l-7-7 7-7' : 'M9 5l7 7-7 7'} />
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
          {navItems.map((item) => {
            const isActive = location.pathname.startsWith(item.to);
            return (
              <div key={item.to} className="relative group">
                <Link
                  to={item.to}
                  className={[
                    'flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm font-medium',
                    'transition-colors duration-150',
                    isActive
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
                  ].join(' ')}
                >
                  <span className="flex-shrink-0 w-5 h-5">{item.icon}</span>
                  {expanded && <span className="truncate">{item.label}</span>}
                </Link>
                {/* 折叠态 Tooltip */}
                {!expanded && (
                  <div className="absolute left-full top-1/2 -translate-y-1/2 ml-2 px-2 py-1
                                  bg-slate-900 text-white text-xs rounded whitespace-nowrap
                                  opacity-0 group-hover:opacity-100 transition-opacity duration-120
                                  pointer-events-none z-50">
                    {item.label}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </aside>
    );
  }

  // Mobile Sidebar（状态 C / D）
  return (
    <>
      {/* Mobile 覆层遮罩（状态 C 专用） */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-20"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile Sidebar 主体 */}
      <aside
        className={[
          'fixed left-0 top-0 h-screen w-60 bg-white border-r border-slate-200 flex flex-col z-30',
          'transition-transform duration-200 ease-out',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
      >
        <div className="h-14 flex items-center justify-between px-3 border-b border-slate-100">
          <span className="font-semibold text-slate-900 text-sm">木兰平台</span>
          <button
            onClick={() => setMobileOpen(false)}
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100
                       transition-colors duration-150"
            aria-label="关闭侧边栏"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
          {navItems.map((item) => {
            const isActive = location.pathname.startsWith(item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => setMobileOpen(false)}
                className={[
                  'flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm font-medium',
                  'transition-colors duration-150',
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
                ].join(' ')}
              >
                <span className="flex-shrink-0 w-5 h-5">{item.icon}</span>
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* 汉堡按钮（由父组件 Header 提供，此处仅暴露控制函数） */}
    </>
  );
}

// 暴露 toggle 方法给父组件的方式：通过 ref 或状态提升
// 推荐：将 mobileOpen/setMobileOpen 提升至 AppLayout，由 Header 汉堡按钮控制
```

### 7.3 AskBar + AttachmentBubble

```tsx
// frontend/src/components/chat/AskBar.tsx
import { useState, useRef, useCallback, KeyboardEvent, DragEvent } from 'react';

interface AttachedFile {
  id: string;
  file: File;
  previewUrl?: string; // 图片类型才有
}

interface AskBarProps {
  onSend: (message: string, files: File[]) => void;
  onFileDrop?: (files: File[]) => void; // 由 DragDropOverlay 调用
  disabled?: boolean;
  placeholder?: string;
}

// AttachmentBubble 子组件
function AttachmentBubble({
  attached,
  onRemove,
}: {
  attached: AttachedFile;
  onRemove: (id: string) => void;
}) {
  const isImage = attached.file.type.startsWith('image/');
  const sizeLabel = attached.file.size < 1024 * 1024
    ? `${(attached.file.size / 1024).toFixed(1)} KB`
    : `${(attached.file.size / (1024 * 1024)).toFixed(1)} MB`;

  return (
    <div className="relative group flex-shrink-0 transition-all duration-150 ease-out">
      {isImage && attached.previewUrl ? (
        /* 图片预览 */
        <div className="w-16 h-16 rounded-xl overflow-hidden border border-slate-200/60
                        bg-white/90 backdrop-blur-sm shadow-sm">
          <img
            src={attached.previewUrl}
            alt={attached.file.name}
            className="w-full h-full object-cover"
          />
        </div>
      ) : (
        /* 非图片预览 */
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-200/60
                        bg-white/90 backdrop-blur-sm shadow-sm max-w-[160px]">
          <svg className="w-5 h-5 text-slate-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0121 9.414V19a2 2 0 01-2 2z" />
          </svg>
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-700 truncate">{attached.file.name}</p>
            <p className="text-xs text-slate-400">{sizeLabel}</p>
          </div>
        </div>
      )}

      {/* X 删除按钮（hover 显示） */}
      <button
        type="button"
        onClick={() => onRemove(attached.id)}
        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full
                   bg-white text-slate-500 border border-slate-200 shadow-sm
                   flex items-center justify-center
                   opacity-0 group-hover:opacity-100
                   transition-opacity duration-150
                   hover:bg-red-50 hover:text-red-500 hover:border-red-200"
        aria-label={`移除 ${attached.file.name}`}
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

// AskBar 主组件
export default function AskBar({ onSend, onFileDrop, disabled = false, placeholder }: AskBarProps) {
  const [message, setMessage] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback((files: File[]) => {
    const newAttached: AttachedFile[] = files.map((file) => {
      const id = `${Date.now()}-${Math.random()}`;
      const previewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined;
      return { id, file, previewUrl };
    });
    setAttachedFiles((prev) => [...prev, ...newAttached]);
  }, []);

  const removeFile = useCallback((id: string) => {
    setAttachedFiles((prev) => {
      const target = prev.find((f) => f.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((f) => f.id !== id);
    });
  }, []);

  const handleFileSelect = () => {
    fileInputRef.current?.click();
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length > 0) addFiles(files);
    // 重置 input 以允许重复选择同一文件
    e.target.value = '';
  };

  // 供 DragDropOverlay 调用（通过 onFileDrop prop 向上传递）
  const handleExternalFileDrop = useCallback((files: File[]) => {
    addFiles(files);
    onFileDrop?.(files);
  }, [addFiles, onFileDrop]);

  const canSend = (message.trim().length > 0 || attachedFiles.length > 0) && !disabled;

  const handleSend = () => {
    if (!canSend) return;
    onSend(message.trim(), attachedFiles.map((a) => a.file));
    setMessage('');
    // 清理 previewUrl 避免内存泄漏
    attachedFiles.forEach((f) => { if (f.previewUrl) URL.revokeObjectURL(f.previewUrl); });
    setAttachedFiles([]);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 自动调整 textarea 高度
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="relative w-full">
      {/* 隐藏文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileInputChange}
        accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"
      />

      {/* 主容器：毛玻璃 */}
      <div
        className={[
          'rounded-2xl border shadow-sm',
          'backdrop-blur-sm bg-white/80',
          'border-slate-200/60',
          'focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20',
          'transition-[border-color,box-shadow] duration-150',
          disabled ? 'opacity-50 cursor-not-allowed' : '',
        ].join(' ')}
      >
        {/* 附件预览行 */}
        {attachedFiles.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachedFiles.map((attached) => (
              <AttachmentBubble
                key={attached.id}
                attached={attached}
                onRemove={removeFile}
              />
            ))}
          </div>
        )}

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={message}
          onChange={handleTextareaChange}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder ?? '向木兰提问... （Enter 发送，Shift+Enter 换行）'}
          rows={1}
          className={[
            'w-full resize-none bg-transparent px-4 py-3',
            'text-sm text-slate-900 placeholder:text-slate-400',
            'focus:outline-none',
            'min-h-[48px] max-h-[200px]',
          ].join(' ')}
        />

        {/* 工具栏 */}
        <div className="flex items-center justify-between px-3 pb-2.5">
          <div className="flex items-center gap-1">
            {/* 附件按钮 */}
            <button
              type="button"
              onClick={handleFileSelect}
              disabled={disabled}
              className="w-8 h-8 rounded-full flex items-center justify-center
                         text-slate-400 hover:text-slate-600 hover:bg-slate-100
                         transition-colors duration-150 disabled:opacity-50"
              aria-label="上传文件"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </button>
          </div>

          {/* 发送按钮 */}
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            className={[
              'w-8 h-8 rounded-full flex items-center justify-center',
              'transition-colors duration-150',
              canSend
                ? 'bg-blue-700 hover:bg-blue-800 text-white'
                : 'bg-slate-100 text-slate-300 cursor-not-allowed',
            ].join(' ')}
            aria-label="发送"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
```

### 7.4 DragDropOverlay

```tsx
// frontend/src/components/chat/DragDropOverlay.tsx
// 用法：挂载于聊天页面根容器，监听 window 级别 drag 事件

import { useState, useEffect, useCallback, useRef } from 'react';

interface DragDropOverlayProps {
  onFilesDropped: (files: File[]) => void;
  disabled?: boolean;
}

export default function DragDropOverlay({ onFilesDropped, disabled = false }: DragDropOverlayProps) {
  const [isDragging, setIsDragging] = useState(false);
  // 使用 ref 而非 state 计数器避免 useCallback 无限重建（CLAUDE.md 陷阱 1 同理）
  const dragCounterRef = useRef(0);

  const handleDragEnter = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) return;
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) {
      setIsDragging(true);
    }
  }, [disabled]);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragging(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length > 0) {
      onFilesDropped(files);
    }
  }, [disabled, onFilesDropped]);

  useEffect(() => {
    window.addEventListener('dragenter', handleDragEnter);
    window.addEventListener('dragleave', handleDragLeave);
    window.addEventListener('dragover', handleDragOver);
    window.addEventListener('drop', handleDrop);
    return () => {
      window.removeEventListener('dragenter', handleDragEnter);
      window.removeEventListener('dragleave', handleDragLeave);
      window.removeEventListener('dragover', handleDragOver);
      window.removeEventListener('drop', handleDrop);
    };
  }, [handleDragEnter, handleDragLeave, handleDragOver, handleDrop]);

  if (!isDragging) return null;

  return (
    /* 全屏遮罩，z-50 确保覆盖 Header(z-40) 和 Sidebar(z-10)
       注意：遮罩出现时 pointer-events-auto 阻断下层点击（AC-03-02） */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-8
                 bg-slate-50/90 backdrop-blur-sm
                 animate-in fade-in duration-150"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* 虚线高亮边框容器 */}
      <div className="w-full h-full max-w-2xl max-h-96 flex flex-col items-center justify-center
                      border-2 border-dashed border-blue-300 rounded-2xl
                      bg-white/60 gap-4">
        {/* 上传图标 */}
        <div className="w-16 h-16 rounded-full bg-blue-50 flex items-center justify-center">
          <svg className="w-8 h-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
        </div>
        <div className="text-center">
          <p className="text-base font-semibold text-slate-700">释放文件以上传</p>
          <p className="text-sm text-slate-400 mt-1">支持图片、PDF、文档等格式</p>
        </div>
      </div>
    </div>
  );
}

/*
 * 使用方式（ChatPage.tsx）：
 *
 * import DragDropOverlay from '../components/chat/DragDropOverlay';
 * import AskBar from '../components/chat/AskBar';
 *
 * function ChatPage() {
 *   const askBarRef = useRef<{ addFiles: (files: File[]) => void }>(null);
 *
 *   const handleFilesDropped = (files: File[]) => {
 *     askBarRef.current?.addFiles(files);
 *   };
 *
 *   return (
 *     <div className="relative flex flex-col h-screen">
 *       <DragDropOverlay onFilesDropped={handleFilesDropped} />
 *       <MessageList />
 *       <AskBar onSend={handleSend} />
 *     </div>
 *   );
 * }
 */
```

---

## 8. Gap 清单与验收标准（AC）

> AC 编号格式：`AC-{GapNo}-{序号}`。每条 AC 可直接转化为一条 Playwright 或 pytest 测试用例。

### 8.1 Gap-01 忘记密码路由

**现状**：`/forgot-password` 链接存在于 LoginPage，但前端路由未注册，后端无对应端点，点击后返回 404。

**实现路径（轻量方案）**：前端新增路由页面 + 弹窗流程，管理员在后台重置密码；暂不依赖 SMTP 邮件（避免引入新基础设施依赖）。若需要邮件验证码，须先完成 SMTP 基础设施配置（此为 Non-Goal）。

**需新增文件**：
- `frontend/src/pages/ForgotPasswordPage.tsx`
- `backend/app/api/auth.py`（新增两个端点）

**验收标准**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-01-01 | 在 `/login` 点击"忘记密码"链接，浏览器 URL 变为 `/forgot-password`，不出现 404 | Playwright |
| AC-01-02 | `/forgot-password` 页面包含邮箱输入框和"提交"按钮 | Playwright |
| AC-01-03 | 提交有效邮箱后，页面显示"我们已向您的邮箱发送重置说明"提示（不暴露账号是否存在） | Playwright |
| AC-01-04 | 提交无效邮箱格式（非 `@` 格式），"提交"按钮保持禁用状态 | Playwright |
| AC-01-05 | `POST /api/auth/forgot-password` 对任意邮箱（存在或不存在）均返回 200（安全考量） | pytest |
| AC-01-06 | 关闭忘记密码页面（点击返回登录）后，登录页用户名/密码输入框内容保持不变 | Playwright |

### 8.2 Gap-02 多模态预览气泡

**现状**：AskBar 无文件上传入口，无 AttachmentBubble 组件。

**需新增/修改文件**：
- `frontend/src/components/chat/AskBar.tsx`（新增附件能力）
- `frontend/src/components/chat/AttachmentBubble.tsx`（可内联或独立文件）
- `frontend/src/components/chat/MessageBubble.tsx`（发送后只读展示）

**验收标准**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-02-01 | 点击附件按钮（paperclip），弹出系统文件选择对话框 | Playwright |
| AC-02-02 | 选择图片文件后，AskBar 上方出现 64x64 缩略图气泡，图片比例保持（object-cover） | Playwright |
| AC-02-03 | 选择非图片文件（PDF/Excel），气泡显示文件名、文件大小（KB 或 MB） | Playwright |
| AC-02-04 | hover 附件气泡，右上角出现 X 删除按钮；点击 X，气泡从预览区消失 | Playwright |
| AC-02-05 | 仅有附件（无文字）时，发送按钮处于可点击状态（非 disabled） | Playwright |
| AC-02-06 | 发送后，消息气泡区域包含附件的只读展示（图片/文件名）；AskBar 附件预览区清空 | Playwright |
| AC-02-07 | 图片缩略图宽高均不超过 80px | Playwright（截图断言） |

### 8.3 Gap-03 文件拖拽遮罩层

**现状**：无 dragover/dragleave/drop 事件监听，无遮罩层组件。

**依赖**：Gap-02 已完成（drop 后触发 Gap-02 预览流程）。

**需新增文件**：
- `frontend/src/components/chat/DragDropOverlay.tsx`

**验收标准**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-03-01 | 将文件拖入浏览器窗口，150ms 内全屏遮罩出现（含蓝色虚线边框和上传提示文字） | Playwright |
| AC-03-02 | 遮罩出现期间，遮罩下层的按钮和输入框不可点击（pointer-events 被遮罩阻断） | Playwright |
| AC-03-03 | 将文件拖出浏览器窗口（dragleave），100ms 内遮罩消失 | Playwright |
| AC-03-04 | 在遮罩上 drop 文件，遮罩消失且 AskBar 出现对应附件预览气泡（触发 Gap-02 流程） | Playwright |
| AC-03-05 | Sidebar 和 Header 在拖拽遮罩出现期间，自身不出现额外高亮或样式变化 | Playwright（视觉回归） |
| AC-03-06 | 同时拖入多个文件（3 个），全部文件均出现在 AskBar 预览区 | Playwright |

### 8.4 Gap-04 Markdown 渲染

**现状**：消息气泡以纯文本显示，不渲染 Markdown 语法。

**技术选型**：
- `react-markdown`（渲染引擎）
- `remark-gfm`（GitHub Flavored Markdown，支持表格/删除线/任务列表）
- `react-syntax-highlighter`（代码块高亮）

**需修改文件**：
- `frontend/src/components/chat/MessageBubble.tsx`
- `frontend/package.json`（新增依赖）

**验收标准**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-04-01 | 消息中 `**粗体**` 渲染为 `<strong>` 标签，页面显示粗体文字 | Vitest（快照） |
| AC-04-02 | 消息中含代码块（三个反引号 python），渲染为带语法高亮的代码块 | Vitest（快照） |
| AC-04-03 | 代码块右上角有复制按钮，点击后代码内容写入剪贴板 | Playwright |
| AC-04-04 | Markdown 表格（GFM）正确渲染为 HTML `<table>`，有边框分隔 | Vitest（快照） |
| AC-04-05 | 消息中的外部链接（`[text](https://...)）渲染为 `<a target="_blank">` | Vitest（快照） |

### 8.5 Gap-05 流式输出

**现状**：后端 LLM 响应为一次性 JSON 返回，前端等待响应再渲染，用户体验为"等待式"。

**实现方案**：
- 后端：FastAPI `StreamingResponse`，Content-Type: `text/event-stream`（SSE）
- 前端：`fetch` + `ReadableStream` 逐 token 读取，实时追加到消息气泡
- 打字机效果：直接追加字符（无需 CSS animation，避免性能问题）

**需修改文件**：
- `backend/app/api/chat.py`（改为 StreamingResponse）
- `backend/services/llm/`（LLM 调用层支持 stream=True）
- `frontend/src/hooks/useChat.ts`（流式读取逻辑）
- `frontend/src/components/chat/MessageBubble.tsx`（支持 isStreaming 状态）

**验收标准**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-05-01 | 发送消息后，助手气泡在 LLM 响应完成前即开始出现内容（非等待全量响应） | Playwright |
| AC-05-02 | 流式输出期间，消息气泡末尾显示光标/加载指示符 | Playwright |
| AC-05-03 | 流式输出完成后，光标/加载指示符消失，消息内容完整显示 | Playwright |
| AC-05-04 | `GET /api/chat/stream` 返回 Content-Type: `text/event-stream` | pytest |
| AC-05-05 | 流式响应中断（网络错误），前端显示错误提示而非卡死 | Playwright（模拟网络中断） |

### 8.6 其他 Gap（Gap-06～09）

#### Gap-06：MFA 登录后 AuthContext 未刷新

**现状**：`/api/auth/mfa/verify` 成功后直接 `navigate('/')`，AuthContext 未更新，导致首页仍显示未登录状态（需手动刷新）。

**修复方案**：verify 成功后先 `await checkAuth()`，再 `navigate('/')`。代码见 7.1 LoginPage 实现。

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-06-01 | 完成 MFA 验证后，自动跳转到首页，且首页立即显示已登录用户名（无需手动刷新） | Playwright |

#### Gap-07：权限矩阵页面仅只读（P2，本次暂不实现）

**现状**：`/system/permissions` 页面仅展示权限矩阵，无编辑能力。

**范围说明**：P2 优先级，不在本次实现范围内。需另立 Spec。

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-07-01 | （占位）权限矩阵页面具备行内编辑能力，修改后保存 | Playwright |

#### Gap-08：/system 路径 404

**现状**：访问 `/system` 直接返回 404，正确行为应重定向到 `/system/users`。

**修复**：在 React Router 配置中添加 `<Route path="/system" element={<Navigate to="/system/users" replace />} />`。

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-08-01 | 访问 `/system`，浏览器 URL 自动变为 `/system/users`，页面正常显示 | Playwright |
| AC-08-02 | 直接访问 `/system`，HTTP 状态码不为 404（前端 SPA 重定向） | Playwright |

#### Gap-09：403 权限不足页面缺失

**现状**：无权限操作返回 403，前端无对应展示页面，显示空白。

**修复**：新增 `frontend/src/pages/ForbiddenPage.tsx`，在路由层全局 ErrorBoundary 或 `403` 拦截器中渲染。

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-09-01 | 以低权限账号访问高权限页面，渲染 403 提示页（包含"权限不足"文字和返回按钮） | Playwright |
| AC-09-02 | 403 页面的"返回"按钮使用 `useNavigate(-1)` 或跳转首页，不触发全页刷新 | Playwright |

---

## 9. 优先级矩阵与交付顺序

| 批次 | Gap | 优先级 | 用户影响 | 复杂度 | 依赖 |
|------|-----|--------|---------|--------|------|
| 批次 1（P0） | Gap-04 Markdown 渲染 | P0 | 极高 | 低 | 无 |
| 批次 1（P0） | Gap-05 流式输出 | P0 | 极高 | 中 | 无 |
| 批次 2（P1） | Gap-08 /system 404 | P1 | 中 | 极低 | 无 |
| 批次 2（P1） | Gap-06 MFA 刷新 | P1 | 中 | 低 | 无 |
| 批次 2（P1） | Gap-01 忘记密码 | P1 | 高 | 低/中 | 无 |
| 批次 3（P1） | Gap-02 文件预览气泡 | P1 | 中 | 中 | 无 |
| 批次 3（P1） | Gap-03 拖拽遮罩 | P1 | 中 | 低 | Gap-02 |
| 批次 4（P2） | Gap-09 403 页面 | P2 | 中 | 低 | 无 |
| 批次 4（P2） | Gap-07 权限矩阵编辑 | P2 | 中 | 低 | 另立 Spec |

**推荐实现顺序**：批次 1 → 批次 2 → 批次 3 → 批次 4（批次 2 内部可并行，Gap-08 和 Gap-06 各自独立）。

---

## 10. 非目标（Non-Goals）

1. **SMTP 邮件服务集成**：忘记密码流程仅实现管理员重置路径，不引入 SMTP 基础设施
2. **深色模式全量适配**：设计 Token 已预留 `dark:` 前缀，但本次实现以浅色模式为主，深色模式不作为验收标准
3. **open-webui 功能完整复制**：只借鉴交互范式和样式系统，不复制其 Svelte 组件或功能集
4. **ETL 数据集成**：不在本次范围内（参考 CLAUDE.md 产品定位 Non-Goals）
5. **BI 可视化本身**：不在本次范围内
6. **多租户 SaaS**：不在本次范围内
7. **权限矩阵编辑（Gap-07）**：P2 优先级，需另立 Spec 设计后端接口
8. **`react-markdown` 沙箱安全**：XSS 防御依赖 `react-markdown` 默认行为，不额外实现 HTML sanitizer（当前场景为内部系统，LLM 输出可信）

---

## 11. 技术实现注意事项（陷阱与约束）

本节引用 `CLAUDE.md` 中记录的真实 Bug，说明本次重构中哪些环节需要主动规避。

### 陷阱 1：AuthContext useCallback 无限重渲染

**原始描述（CLAUDE.md 陷阱 1）**：将 token 过期时间存为 `useState`，导致 `checkAuth` 的 `useCallback` 依赖数组包含该 state，state 更新触发 `checkAuth` 重新创建，`useEffect` 重新触发，形成闭环。

**本次重构的风险点**：

1. **LoginPage 调用 `checkAuth()`（Gap-06 修复）**：`checkAuth` 函数从 `AuthContext` 中解构，若 AuthContext 内部使用 `useState` 存储计时器值，`checkAuth` 每次渲染都会变化，导致 LoginPage useEffect 重复调用。

   **规避措施**：coder 实现 Gap-06 修复时，确认 `AuthContext` 中计时器/过期时间使用 `useRef` 而非 `useState`（参考 CLAUDE.md 正确做法）。若 AuthContext 已有问题，须一并修复，不得绕过。

2. **DragDropOverlay 的 useCallback 依赖链**：`handleDragEnter / handleDragLeave / handleDrop` 依赖 `disabled` prop 和 `onFilesDropped`。若调用方在每次渲染创建新的 `onFilesDropped` 函数（如内联箭头函数），会导致 DragDropOverlay 频繁重新绑定 window 事件监听器。

   **规避措施**：调用方（ChatPage）使用 `useCallback` 包裹 `onFilesDropped`，DragDropOverlay 内部的 `dragCounterRef` 使用 `useRef` 而非 `useState`（见 7.4 实现代码注释）。

### 陷阱 2：React.lazy 不支持具名导出（named export）

**原始描述（CLAUDE.md 陷阱 2）**：`React.lazy` 只接受 default export，具名导出需手动转换。

**本次重构的风险点**：

本次新增四个组件文件：
- `LoginPage.tsx` — 使用 `export default`，无风险
- `Sidebar.tsx` — 使用 `export default`，无风险
- `AskBar.tsx` — 使用 `export default`，无风险（`AttachmentBubble` 为内部组件，不懒加载）
- `DragDropOverlay.tsx` — 使用 `export default`，无风险
- `ForgotPasswordPage.tsx` — 使用 `export default`，无风险

若未来路由层需要对这些页面做懒加载（`React.lazy`），必须确保：

```ts
// 正确写法（若组件是 default export，直接使用）
const LoginPage = lazy(() => import('./pages/LoginPage'));

// 若历史文件使用具名导出，必须转换
const SomePage = lazy(() =>
  import('./pages/SomePage').then(m => ({ default: m.SomePage }))
);
```

**规避措施**：本次新建的所有页面和组件一律使用 `export default`，不使用具名导出，从源头规避此陷阱。

### 陷阱 3：react-router `<a href>` 触发全页刷新

**原始描述（CLAUDE.md 陷阱 3）**：在 React Router 应用中使用原生 `<a href>` 跳转，会绕过客户端路由触发完整页面重载。

**本次重构的风险点**：

LoginPage 的"忘记密码"链接和 Gap-09 的 403 页面"返回"按钮，若使用 `<a href>` 实现，会触发全页刷新，丢失 AuthContext 等全局状态。

**规避措施**：见 7.1 LoginPage 代码，"忘记密码"使用 `onClick + navigate('/forgot-password')` 实现；ForbiddenPage 返回按钮使用 `useNavigate(-1)`。

### 陷阱 4：Alembic autogenerate 遗漏 server_default

**本次重构的风险点**：

Gap-01 忘记密码流程若需要数据库层存储验证码（如 `auth_password_reset_tokens` 表），Model 中的 `expires_at`、`used` 字段必须使用 `server_default` 而非 Python 层 `default`，确保存量数据安全。

**规避措施**：

```python
# 正确写法
used = Column(Boolean, server_default=sa.false(), nullable=False)
expires_at = Column(DateTime(timezone=True), nullable=False)  # 由应用层计算并显式传入，不依赖 default
```

### 陷阱 5（本次特有）：DragDropOverlay 拖拽计数器必须用 useRef

### 陷阱 6（本次特有）：AskBar 频繁状态更新与 React 19 Concurrent Mode

**场景**：Gap-05 流式输出期间，LLM 每秒可能追加 30–50 个 token，若每个 token 都触发 `setMessage()` 并导致 AskBar 所在的父组件重渲染，AskBar 内部的 textarea 高度计算（`handleTextareaChange`）以及附件预览区也会同步重渲染，可能造成每帧多次重绘、输入框掉帧。

**React 19 Concurrent Mode 的缓解作用**：React 18+ 的 Concurrent Mode 对高频 `setState` 有自动批处理（Automatic Batching）和时间分片（Time Slicing），能在一定程度上合并更新、避免阻塞主线程。但这不能完全免疫：
- 若流式内容 state 与 AskBar 的 `message` state 在同一组件树且未做隔离，两者会互相触发重渲染。
- `useDeferredValue` 能将低优先级渲染推迟，但它本身不减少 state 更新次数，只影响渲染时机。

**风险缓解方案（coder 实现 Gap-05 时必须执行）**：

1. **状态隔离**：流式输出的消息内容 state（`streamingContent`）必须放在独立的 `MessageBubble` 或专用 hook 内，**不得**与 AskBar 的 `message` / `attachedFiles` state 共存于同一组件。

2. **AskBar 使用 `React.memo` 包裹**：

   ```tsx
   // ✅ 正确：AskBar 只在 props 变化时重渲染
   export default React.memo(AskBar);
   ```

3. **消息列表使用 `useDeferredValue`（可选优化）**：

   ```tsx
   // 在父组件中，流式消息可用 useDeferredValue 降低渲染优先级
   const deferredMessages = useDeferredValue(messages);
   return <MessageList messages={deferredMessages} />;
   ```

4. **流式追加策略**：后端 SSE chunk 到达后，使用 `useRef` 缓存临时文本，每 16ms（一帧）批量 flush 一次 `setState`，避免每个 chunk 都触发渲染：

   ```tsx
   // 伪代码示意
   const bufferRef = useRef('');
   const rafRef = useRef<number | null>(null);

   const flushBuffer = useCallback(() => {
     setStreamingContent((prev) => prev + bufferRef.current);
     bufferRef.current = '';
     rafRef.current = null;
   }, []);

   const onChunk = useCallback((chunk: string) => {
     bufferRef.current += chunk;
     if (!rafRef.current) {
       rafRef.current = requestAnimationFrame(flushBuffer);
     }
   }, [flushBuffer]);
   ```

**验收补充（在 AC-05 基础上追加）**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-05-06 | 流式输出期间（模拟 30 token/s），AskBar 输入框仍可正常输入文字、无卡顿（Chrome DevTools Performance 无超过 16ms 的 Long Task） | 手动验证 |

---

### 陷阱 7（本次特有）：AutoGrowingTextarea 极端输入导致布局撑破

**场景**：用户粘贴几千行日志到 AskBar 输入框，`scrollHeight` 可能达到 10000px+。若 `handleTextareaChange` 逻辑不完整，textarea 会无限撑高，突破 AskBar 容器，导致整个页面布局错位。

**当前 SPEC 方案**（见 7.3 `handleTextareaChange`）：

```tsx
el.style.height = 'auto';
el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
```

配合 Tailwind 类 `max-h-[200px]`，将最大高度限制为 200px。

**潜在遗漏项与修复要求（coder 实现时必须核查）**：

1. **缺少 `overflow-y-auto`**：当 inline style 将 height 固定为 200px 时，textarea 内部内容仍超出，若无 overflow 声明，部分浏览器会让内容溢出而不显示滚动条。**必须**在 textarea className 中加入 `overflow-y-auto`：

   ```tsx
   // ✅ 正确
   className={[
     'w-full resize-none bg-transparent px-4 py-3',
     'text-sm text-slate-900 placeholder:text-slate-400',
     'focus:outline-none',
     'min-h-[48px] max-h-[200px] overflow-y-auto',  // ← overflow-y-auto 不可省略
   ].join(' ')}
   ```

2. **AskBar 外层容器不得使用 `overflow-hidden`**：若外层容器截断内容，200px 高的 textarea 内部滚动条会被裁切，导致用户无法滚动查看粘贴内容。外层容器保持 `overflow-visible`（默认值）或不设置 overflow。

3. **200px 上限的依据**：等同于约 8–10 行文本（14px 行高 × 1.5 行距），足以展示多行问题描述；超出后用户可在框内滚动。这是 open-webui 同类场景的惯用上限，也是本平台的正式约定，**不得**在未更新本 SPEC 的情况下擅自调大或去掉此限制。

**验收补充（在 Gap-02 / AskBar 基础上追加）**：

| AC 编号 | 验收内容 | 测试类型 |
|---------|---------|---------|
| AC-02-08 | 向 AskBar 输入框粘贴 500 行文字，输入框高度不超过 200px，页面整体布局不发生偏移 | Playwright |
| AC-02-09 | 粘贴极长内容后，AskBar 输入框内部出现纵向滚动条，可正常滚动查看内容 | Playwright |

**现象**：使用 `useState` 计数器追踪 dragenter/dragleave 嵌套层级时，React 批量更新导致计数不准确，遮罩频繁闪烁。

**正确做法**：使用 `useRef` 存储计数器（见 7.4 `dragCounterRef`），只在需要触发渲染时调用 `setIsDragging`。

---

## 变更记录

| 日期 | 版本 | 作者 | 变更内容 |
|------|------|------|---------|
| 2026-04-18 | v1.0 | architect | 初稿：汇编 open-webui 侦察报告、Gap 清单、设计规范，输出完整 Spec 25 |
| 2026-04-18 | v1.1 | architect | 风险补充：移动端 Sidebar Overlay 模式设计决策说明（5.2）；新增陷阱 6（React 19 AskBar 高频更新 + memo/RAF 批处理方案）；新增陷阱 7（AutoGrowingTextarea 极端输入 overflow-y-auto 修复要求 + AC-02-08/09）|
