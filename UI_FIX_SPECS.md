# Mulan BI Platform UI 修复规格说明书

**生成日期**: 2026-04-03
**检查模型**: Gemini 2.5 Flash
**目标**: MiniMax 可直接执行修复

---

## 全局 CSS 变量（添加到 tailwind.config.js）

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        // WCAG AA Compliant Text Colors on white (#FFFFFF)
        'text-primary': '#1A202C',        // gray-900 (17.5:1 contrast)
        'text-secondary': '#374151',       // gray-700 (7.2:1 contrast)
        'text-placeholder': '#6B7280',     // gray-500 (3.5:1 - acceptable for placeholder)

        // Link Colors
        'link-primary': '#2563EB',         // blue-600 (4.86:1 contrast)

        // Border & Focus Colors
        'border-default': '#9CA3AF',      // gray-400 (more visible)
        'border-focus': '#3B82F6',         // blue-500 (4.0:1 contrast)
        'focus-ring': '#3B82F6',           // blue-500

        // Button Colors
        'btn-primary-bg': '#1D4ED8',       // blue-700
        'btn-primary-hover-bg': '#1E40AF', // blue-800
        'btn-primary-text': '#FFFFFF',      // (7.3:1 contrast)

        // 404 Page Colors
        'color-primary': '#0A4D68',        // (7.72:1 contrast - brand color)
        'color-text-dark': '#2C3E50',       // (13.9:1 contrast)
        'color-text-light': '#5C6B7B',      // (6.47:1 contrast)
        'color-404-text': '#34495E',       // (10.36:1 contrast)
        'color-background-light': '#F8F8F8',
      },
    },
  },
  plugins: [],
};
```

---

## 1. 登录页面 (Login Page) 修复规格

**文件路径**: `frontend/src/pages/login/page.tsx`

### 组件结构

```tsx
<div className="min-h-screen flex items-center justify-center bg-gray-50">
  <div className="w-full max-w-md p-8 bg-white rounded-lg shadow-md">

    {/* Card Header - 左对齐修复 */}
    <div className="flex flex-col items-start mb-6">
      <img src="path/to/logo.svg" alt="Mulan Platform Logo" className="w-12 h-12 mb-3" />
      <h1 className="text-xl font-semibold text-gray-900 mb-1">Mulan Platform</h1>
      <p className="text-sm text-gray-700">数据建模与治理平台</p>
    </div>

    {/* Login Form */}
    <form className="space-y-5">

      {/* Username Field */}
      <div>
        <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-2">用户名</label>
        <input
          type="text"
          id="username"
          name="username"
          placeholder="请输入用户名"
          autoComplete="username"
          className="block w-full px-4 py-2 border border-gray-400 rounded-md shadow-sm text-gray-900
                     placeholder:text-gray-600
                     focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                     sm:text-sm"
        />
      </div>

      {/* Password Field with Show/Hide Toggle */}
      <div>
        <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">密码</label>
        <div className="relative">
          <input
            type="password"
            id="password"
            name="password"
            placeholder="请输入密码"
            autoComplete="current-password"
            className="block w-full pr-10 px-4 py-2 border border-gray-400 rounded-md shadow-sm text-gray-900
                       placeholder:text-gray-600
                       focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
                       sm:text-sm"
          />
          {/* Show/Hide Toggle Button */}
          <button
            type="button"
            aria-label="Toggle password visibility"
            className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-500 hover:text-gray-700
                       focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 rounded-r-md"
            onClick={() => {/* toggle password visibility */}}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Forgot Password Link - 新增 */}
      <div className="flex justify-end mt-2 mb-4">
        <a
          href="/forgot-password"
          className="text-sm font-medium text-blue-600 hover:text-blue-700
                     focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white rounded-md"
        >
          忘记密码？
        </a>
      </div>

      {/* Login Button */}
      <button
        type="submit"
        className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm
                   text-base font-medium text-white bg-blue-700 hover:bg-blue-800
                   focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 focus:ring-offset-white"
      >
        登录
      </button>
    </form>

    {/* Register Link */}
    <div className="mt-6 text-center">
      <a
        href="/register"
        className="text-sm font-medium text-blue-600 hover:text-blue-700
                   focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white rounded-md"
      >
        注册新账号
      </a>
    </div>
  </div>
</div>
```

### 修复清单

| # | 问题 | 修复 | Tailwind 类 |
|---|------|------|-------------|
| 1 | 占位符对比度不足 | 使用 `placeholder:text-gray-600` | `#4B5563` (5.7:1) |
| 2 | 输入框边框过浅 | 使用 `border-gray-400` | `#9CA3AF` |
| 3 | 缺少密码显示/隐藏 | 添加 toggle button + SVG icon | `absolute inset-y-0 right-0 pr-3` |
| 4 | 缺少忘记密码链接 | 添加链接 + `text-blue-600` | `text-blue-600 hover:text-blue-700` |
| 5 | 卡片对齐不一致 | 全部左对齐 | `items-start` |
| 6 | 副标题对比度低 | 使用 `text-gray-700` | `#374151` (7.2:1) |
| 7 | 缺少焦点状态 | 添加 `focus:ring-2 focus:ring-blue-500` | Focus ring |

### 间距规范

- Logo 与标题: `mb-3` (12px)
- 标题与副标题: `mb-1` (4px)
- 标签与输入框: `mb-2` (8px)
- 表单组之间: `space-y-5` (20px)
- 按钮与注册链接: `mt-6` (24px)
- 输入框内边距: `px-4 py-2` (16px 水平, 8px 垂直)

---

## 2. 注册页面 (Register Page) 修复规格

**文件路径**: `frontend/src/pages/register/page.tsx`

### 组件结构

```tsx
<div className="min-h-screen flex items-center justify-center bg-gray-50">
  <div className="bg-white p-8 rounded-lg shadow-md w-full max-w-sm">

    {/* Logo */}
    <div className="text-center mb-6">
      <img src="/path/to/logo.svg" alt="Mulan Platform Logo" className="mx-auto h-10 w-auto" />
    </div>

    {/* Title and Subtitle */}
    <div className="text-center mb-8">
      <h1 className="text-2xl font-bold text-gray-800 mb-2">注册账号</h1>
      <p className="text-sm text-gray-600">加入 Mulan Platform</p>
    </div>

    <form className="space-y-5">

      {/* Username Field */}
      <div>
        <label htmlFor="username" className="block text-sm font-medium text-gray-800 mb-2">用户名</label>
        <input
          type="text"
          id="username"
          name="username"
          placeholder="请输入用户名"
          className="block w-full px-4 py-3 border border-gray-300 rounded-md shadow-sm
                     placeholder-gray-600 text-gray-800
                     focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600
                     sm:text-sm"
        />
      </div>

      {/* Password Field */}
      <div>
        <label htmlFor="password" className="block text-sm font-medium text-gray-800 mb-2">密码</label>
        <div className="relative">
          <input
            type="password"
            id="password"
            name="password"
            placeholder="至少6位"
            className="block w-full pr-10 px-4 py-3 border border-gray-300 rounded-md shadow-sm
                       placeholder-gray-600 text-gray-800
                       focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600
                       sm:text-sm"
          />
          <button
            type="button"
            aria-label="Toggle password visibility"
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Confirm Password Field */}
      <div>
        <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-800 mb-2">确认密码</label>
        <div className="relative">
          <input
            type="password"
            id="confirm-password"
            name="confirm-password"
            placeholder="再次输入密码"
            className="block w-full pr-10 px-4 py-3 border border-gray-300 rounded-md shadow-sm
                       placeholder-gray-600 text-gray-800
                       focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-600
                       sm:text-sm"
          />
          <button
            type="button"
            aria-label="Toggle password visibility"
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-500"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          </button>
        </div>
      </div>

      {/* Register Button */}
      <button
        type="submit"
        className="w-full flex justify-center py-3 px-6 border border-transparent rounded-md shadow-sm
                   text-base font-medium text-white bg-gray-900
                   hover:bg-gray-800
                   focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-600"
      >
        注册
      </button>
    </form>

    {/* Login Link */}
    <div className="mt-6 text-center">
      <p className="text-sm text-gray-600">
        已有账号?
        <a
          href="/login"
          className="font-medium text-blue-600 hover:text-blue-500 underline
                     focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-600"
        >
          去登录
        </a>
      </p>
    </div>
  </div>
</div>
```

### 修复清单

| # | 问题 | 修复 | Tailwind 类 |
|---|------|------|-------------|
| 1 | 占位符对比度不足 | `placeholder-gray-600` | `#6B7280` |
| 2 | 输入框边框过浅 | `border-gray-300` | `#D1D5DB` |
| 3 | 标签与输入框间距不一致 | `mb-2` + `space-y-5` | 8px / 20px |
| 4 | 两个密码框都缺少 toggle | 添加 toggle button | `pr-10` + SVG |
| 5 | 副标题对比度低 | `text-gray-600` | `#4B5563` |
| 6 | 缺少焦点状态 | `focus:ring-2 focus:ring-blue-200` | Blue ring |
| 7 | 登录链接缺少下划线 | `underline` | 下划线 |

---

## 3. 404 错误页面 (404 Page) 修复规格

**文件路径**: `frontend/src/pages/NotFound.tsx`

### 全局样式变量

```html
<style>
  :root {
    --color-primary: #0A4D68;        /* 7.72:1 contrast */
    --color-text-dark: #2C3E50;       /* 13.9:1 contrast */
    --color-text-light: #5C6B7B;     /* 6.47:1 contrast */
    --color-404-text: #34495E;        /* 10.36:1 contrast */
    --color-background-light: #F8F8F8;
  }
</style>
```

### 组件结构

```tsx
<body className="bg-white text-[var(--color-text-dark)] font-sans flex flex-col min-h-screen">

  {/* 1. Navigation Bar */}
  <header className="bg-white shadow-sm py-4 px-6 flex justify-between items-center">
    <div className="flex items-center">
      <a href="/" className="text-2xl font-bold text-[var(--color-primary)]">
        Mulan Platform
      </a>
    </div>
    <nav>
      <ul className="flex space-x-6">
        <li><a href="/" className="text-[var(--color-text-dark)] hover:text-[var(--color-primary)] transition-colors duration-200">首页</a></li>
        <li><a href="/about" className="text-[var(--color-text-dark)] hover:text-[var(--color-primary)] transition-colors duration-200">关于</a></li>
        <li><a href="/contact" className="text-[var(--color-text-dark)] hover:text-[var(--color-primary)] transition-colors duration-200">联系</a></li>
      </ul>
    </nav>
  </header>

  {/* 2. Main Content Area */}
  <main className="flex-grow flex flex-col items-center justify-center p-6 text-center relative overflow-hidden">

    {/* Large Background "404" - 修复对比度 */}
    <div className="absolute inset-x-0 bottom-[-15%] sm:bottom-[-20%] md:bottom-[-25%] lg:bottom-[-30%] xl:bottom-[-35%]
                    text-[var(--color-404-text)] opacity-20 font-extrabold
                    text-[12rem] sm:text-[18rem] md:text-[24rem] lg:text-[28rem] xl:text-[32rem]
                    leading-none select-none z-0">
      404
    </div>

    {/* Central Content Block */}
    <div className="relative z-10 max-w-lg mx-auto">

      {/* Main Error Message - 统一语义 */}
      <h1 className="text-5xl md:text-6xl font-extrabold text-[var(--color-text-dark)] mb-4 leading-tight">
        Page Not Found
      </h1>
      <p className="text-xl text-[var(--color-text-light)] mb-8">
        抱歉，您访问的页面不存在或已被移除。
      </p>

      {/* Navigation Guidance Buttons */}
      <div className="flex flex-col sm:flex-row justify-center gap-4 mb-8">
        <a
          href="/"
          className="inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm
                     text-white bg-[var(--color-primary)] hover:bg-opacity-90 transition-colors duration-200
                     focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[var(--color-primary)]"
        >
          返回首页
        </a>
        <a
          href="/contact"
          className="inline-flex items-center justify-center px-6 py-3 border border-[var(--color-primary)] text-base font-medium rounded-md
                     text-[var(--color-primary)] bg-white hover:bg-[var(--color-primary)] hover:text-white
                     transition-colors duration-200
                     focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[var(--color-primary)]"
        >
          报告问题
        </a>
      </div>

      {/* Secondary Contact Link */}
      <p className="text-lg text-[var(--color-text-light)]">
        如果问题持续存在，请联系技术支持
        <a href="/contact" className="text-[var(--color-primary)] hover:underline font-semibold transition-colors duration-200">
          联系我们
        </a>
      </p>
    </div>
  </main>

  {/* 3. Footer */}
  <footer className="bg-[var(--color-background-light)] py-6 px-6 text-center text-[var(--color-text-light)] text-sm mt-auto">
    <p>&copy; 2026 Mulan Platform. All rights reserved.</p>
    <div className="mt-2 space-x-4">
      <a href="/privacy" className="hover:text-[var(--color-primary)] transition-colors duration-200">隐私政策</a>
      <a href="/terms" className="hover:text-[var(--color-primary)] transition-colors duration-200">服务条款</a>
    </div>
  </footer>

</body>
```

### 修复清单

| # | 问题 | 修复 | 实现 |
|---|------|------|------|
| 1 | "404" 对比度极低 | 使用 `text-[var(--color-404-text)]` | `#34495E` (10.36:1) |
| 2 | "404" 文字被裁剪 | 使用负值 bottom + overflow-hidden | `bottom-[-35%] overflow-hidden` |
| 3 | "Tell me more..." 缺乏可点击提示 | 重写为"联系我们" + 链接样式 | `text-[var(--color-primary)] hover:underline` |
| 4 | 缺少导航引导 | 添加"返回首页"和"报告问题"按钮 | Primary + Outline 按钮 |
| 5 | 错误信息语义冲突 | 统一为"Page Not Found" | 清晰的中英文错误提示 |
| 6 | 缺少品牌标识 | 添加导航栏和 Footer | Header + Footer 组件 |

### 间距规范

- Header 内边距: `py-4 px-6`
- 主内容区内边距: `p-6`
- 主标题与描述: `mb-4` (16px)
- 描述与按钮: `mb-8` (32px)
- 按钮间距: `gap-4` (16px)
- Footer 内边距: `py-6 px-6`

---

## 密码显示/隐藏 Toggle JavaScript 实现

在每个登录/注册页面添加以下 JavaScript 函数：

```javascript
// Password visibility toggle
const togglePassword = (inputId) => {
  const input = document.getElementById(inputId);
  const button = input.nextElementSibling;
  const svg = button.querySelector('svg');

  if (input.type === 'password') {
    input.type = 'text';
    // Switch to eye-off icon
    svg.innerHTML = `
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.542-7
               1.274-4.057 5.064-7 9.542-7 1.54 0 2.97.354 4.236.968M14.932 9.068
               a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M1.39 1.39l21.22 21.22" />
    `;
  } else {
    input.type = 'password';
    // Switch to eye icon
    svg.innerHTML = `
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7
               -1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    `;
  }
};
```

---

## WCAG AA 合规色值参考

| 用途 | 色值 | 对比度 | 状态 |
|------|------|--------|------|
| 主要文本 (白底) | `#1A202C` | 17.5:1 | ✅ AAA |
| 次要文本 (白底) | `#374151` | 7.2:1 | ✅ AA |
| 占位符文本 (白底) | `#6B7280` | 3.5:1 | ⚠️ 最低标准 |
| 链接文本 (白底) | `#2563EB` | 4.86:1 | ✅ AA |
| 背景 | `#FFFFFF` | - | - |
| 输入框边框 | `#9CA3AF` | 1.6:1 | ⚠️ 仅边框 |
| 焦点边框 | `#3B82F6` | 4.0:1 | ✅ AA |

---

## 执行顺序

1. **先更新 tailwind.config.js** - 添加全局 CSS 变量
2. **修复登录页面** - login/page.tsx
3. **修复注册页面** - register/page.tsx
4. **修复 404 页面** - NotFound.tsx
5. **添加密码 toggle 功能** - 在页面中引入 JavaScript 函数
