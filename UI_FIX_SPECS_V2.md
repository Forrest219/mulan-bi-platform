# Mulan BI Platform UI 修复规格说明书 V2

**生成日期**: 2026-04-03
**检查模型**: Gemini 2.5 Flash
**目标**: MiniMax 可直接执行修复

---

## 全局配置修复

### [tailwind.config.ts]

- **问题类型**：对比度/颜色
- **修复方案**：

  在 `theme.extend.colors` 中添加缺失的语义化颜色：

  ```ts
  theme: {
    extend: {
      colors: {
        // 添加缺失的语义化颜色
        'nav-active': '#1890FF',      // 导航选中态
        'text-secondary-light': '#64748B', // 次要文本（侧边栏分类标题等）
        'border-light': '#E2E8F0',   // 浅色边框
        'bg-slate-100': '#F1F5F9',   // 浅灰背景
      },
    },
  },
  ```

- **影响范围**：全局配置

---

## 登录/注册页面修复（已完成 V1）

### [frontend/src/pages/login/page.tsx]

已在 V1 中完成以下修复：
- ✅ 占位符对比度 (`placeholder:text-gray-600`)
- ✅ 输入框边框 (`border-gray-400`)
- ✅ 密码显示/隐藏 Toggle
- ✅ 忘记密码链接
- ✅ 焦点状态 (`focus:ring-2`)
- ✅ 卡片标题左对齐

### [frontend/src/pages/register/page.tsx]

已在 V1 中完成以下修复：
- ✅ 占位符对比度 (`placeholder-gray-600`)
- ✅ 两个密码框 Toggle
- ✅ 登录链接下划线 (`underline`)
- ✅ 焦点状态 (`focus:ring-2`)

---

## 404 页面修复（已完成 V1）

### [frontend/src/pages/NotFound.tsx]

已在 V1 中完成以下修复：
- ✅ "404" 对比度 (`#34495E`)
- ✅ 导航栏 Header
- ✅ Footer
- ✅ "返回首页" / "报告问题" 按钮
- ✅ 统一错误信息

---

## 业务页面 UI 修复

### [frontend/src/pages/ddl-validator/page.tsx]

- **问题类型**：对比度/布局
- **修复方案**：

  1. **文本占位符对比度不足**
     - **Find**:
       ```tsx
       <Input
         placeholder="--- 粘贴你的 CREATE TABLE 语句 ---"
         className="font-mono text-sm placeholder:text-slate-400"
       ```
     - **Replace**:
       ```tsx
       <Input
         placeholder="--- 粘贴你的 CREATE TABLE 语句 ---"
         className="font-mono text-sm placeholder:text-gray-500"
       ```

  2. **顶部标签和辅助文本对比度不足**
     - **Find**:
       ```tsx
       <span className="text-xs text-slate-400">PREVIEW</span>
       <p className="text-xs text-slate-400">预览工具，仅供参考</p>
       ```
     - **Replace**:
       ```tsx
       <span className="text-xs text-gray-500 font-medium">PREVIEW</span>
       <p className="text-xs text-gray-500">预览工具，仅供参考</p>
       ```

  3. **DDL 输入区域下方辅助文本对比度**
     - **Find**:
       ```tsx
       <span className="text-xs text-slate-400">
         支持多个 CREATE TABLE 语句
       </span>
       <span className="text-xs text-slate-400">0 chars</span>
       ```
     - **Replace**:
       ```tsx
       <span className="text-xs text-gray-500">
         支持多个 CREATE TABLE 语句
       </span>
       <span className="text-xs text-gray-500">0 chars</span>
       ```

  4. **"加载示例 SQL" 链接对齐**
     - **Find**:
       ```tsx
       <button className="text-sm text-blue-600 hover:text-blue-700">
         加载示例 SQL
       </button>
       ```
     - **Replace**:
       ```tsx
       <button className="text-sm text-blue-600 hover:text-blue-700 underline">
         加载示例 SQL
       </button>
       ```

- **影响范围**：局部页面

---

### [frontend/src/pages/database-monitor/page.tsx]

- **问题类型**：可访问性/布局/一致性
- **修复方案**：

  1. **导航选中项对比度不足**
     - **Find**:
       ```tsx
       <NavLink
         to="/health"
         icon={<Heart className="w-5 h-5" />}
         className={({ isActive }) =>
           isActive ? 'flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg bg-blue-50 text-blue-600' : '...'
         }
       >
         数据仓库体检
       </NavLink>
       ```
     - **Replace**:
       ```tsx
       <NavLink
         to="/health"
         icon={<Heart className="w-5 h-5" />}
         className={({ isActive }) =>
           isActive ? 'flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg bg-blue-50 text-blue-700' : '...'
         }
       >
         数据仓库体检
       </NavLink>
       ```

  2. **空状态"发起扫描"链接样式不明确**
     - **Find**:
       ```tsx
       <p className="text-sm text-gray-500">
         暂无扫描记录，点击"发起扫描"开始
       </p>
       ```
     - **Replace**:
       ```tsx
       <p className="text-sm text-gray-600">
         暂无扫描记录，
         <button className="text-blue-600 hover:text-blue-700 underline font-medium">
           发起扫描
         </button>
         开始
       </p>
       ```

  3. **侧边栏分类标题层级不清**
     - **Find**:
       ```tsx
       <span className="text-xs text-gray-500">数据治理</span>
       ```
     - **Replace**:
       ```tsx
       <span className="text-xs text-gray-400 font-semibold uppercase tracking-wide">
         数据治理
       </span>
       ```

  4. **侧边栏底部的"管理员 admin"区域优化**
     - **Find**:
       ```tsx
       <div className="flex items-center gap-2 px-3 py-2 border-t border-gray-200">
         <div className="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center">
           <User className="w-4 h-4 text-slate-500" />
         </div>
         <div>
           <p className="text-sm font-medium text-slate-700">admin</p>
           <p className="text-xs text-slate-400">管理员</p>
         </div>
       </div>
       ```
     - **Replace**:
       ```tsx
       <div className="flex items-center gap-2 px-3 py-3 border-t border-gray-200 bg-slate-50">
         <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center">
           <User className="w-4 h-4 text-slate-600" />
         </div>
         <div>
           <p className="text-sm font-semibold text-gray-700">admin</p>
           <p className="text-xs text-gray-500">管理员</p>
         </div>
       </div>
       ```

- **影响范围**：局部页面

---

### [frontend/src/pages/tableau/assets/page.tsx]

- **问题类型**：可访问性/布局/一致性
- **修复方案**：

  1. **导航选中项蓝色与背景对比度不足**
     - **Find**:
       ```tsx
       className={({ isActive }) =>
         isActive
           ? 'flex items-center gap-3 px-3 py-2 rounded-lg bg-blue-50 text-blue-600'
           : 'flex items-center gap-3 px-3 py-2 text-slate-600 hover:bg-slate-50'
       }
       ```
     - **Replace**:
       ```tsx
       className={({ isActive }) =>
         isActive
           ? 'flex items-center gap-3 px-3 py-2 rounded-lg bg-blue-50 text-blue-700 font-medium'
           : 'flex items-center gap-3 px-3 py-2 text-slate-600 hover:bg-slate-50'
       }
       ```

  2. **"加载中..." 动画未居中对齐**
     - **Find**:
       ```tsx
       <div className="flex items-center justify-center py-12">
         <Loader className="w-8 h-8 text-blue-600 animate-spin" />
         <span className="ml-3 text-sm text-slate-500">加载中...</span>
       </div>
       ```
     - **Replace**:
       ```tsx
       <div className="flex flex-col items-center justify-center py-12">
         <Loader className="w-8 h-8 text-blue-600 animate-spin" />
         <span className="mt-3 text-sm text-gray-500">加载中...</span>
       </div>
       ```

  3. **筛选标签对比度和样式加强**
     - **Find**:
       ```tsx
       <button className="px-3 py-1 text-xs border border-slate-200 rounded-full text-slate-600">
         工作簿
       </button>
       ```
     - **Replace**:
       ```tsx
       <button className="px-3 py-1 text-xs border border-gray-300 rounded-full text-gray-700 hover:border-blue-400 hover:text-blue-600 transition-colors">
         工作簿
       </button>
       ```

  4. **搜索框与筛选标签间距优化**
     - **Find**:
       ```tsx
       <Input
         placeholder="搜索资产..."
         className="w-64"
       />
       <div className="flex items-center gap-2 mt-6">
     ```
     - **Replace**:
       ```tsx
       <Input
         placeholder="搜索资产..."
         className="w-64"
       />
       <div className="flex items-center gap-2 mt-4">
       ```

  5. **分类标题样式加强**
     - **Find**:
       ```tsx
       <span className="text-xs text-gray-500">数据治理</span>
       ```
     - **Replace**:
       ```tsx
       <span className="text-xs text-gray-400 font-semibold uppercase tracking-wide">
         数据治理
       </span>
       ```

- **影响范围**：局部页面

---

### [frontend/src/components/Sidebar.tsx] (如存在)

- **问题类型**：可访问性/一致性
- **修复方案**：

  1. **统一侧边栏分类标题样式**
     ```tsx
     // 添加全局样式类
     sidebarTitle: 'text-xs text-gray-400 font-semibold uppercase tracking-wide'
     ```

  2. **统一导航图标风格**
     - 选中态: 填充图标 + 蓝色
     - 非选中态: 线框图标 + 灰色

  3. **添加分隔线样式**
     ```tsx
     <div className="border-t border-gray-200 my-2" />
     ```

- **影响范围**：全局组件

---

### [frontend/src/index.css]

- **问题类型**：全局样式/一致性
- **修复方案**：

  ```css
  @layer base {
    html {
      scrollbar-width: thin;
      scrollbar-color: #CBD5E1 transparent;
    }

    ::-webkit-scrollbar {
      width: 8px;
      height: 8px;
    }

    ::-webkit-scrollbar-track {
      background: transparent;
    }

    ::-webkit-scrollbar-thumb {
      background-color: #CBD5E1;
      border-radius: 4px;
    }

    ::-webkit-scrollbar-thumb:hover {
      background-color: #94A3B8;
    }
  }

  /* 全局链接样式增强 */
  @layer components {
    .link-primary {
      @apply text-blue-600 hover:text-blue-700 underline-offset-2 hover:underline;
    }

    .link-secondary {
      @apply text-gray-600 hover:text-gray-700;
    }
  }
  ```

- **影响范围**：全局配置

---

## 修复优先级汇总

| 优先级 | 页面/组件 | 问题数 | 预计工时 |
|--------|----------|--------|----------|
| P0 | ddl-validator | 占位符对比度、SQL注释冲突 | 15min |
| P0 | database-monitor | 导航选中对比度、空状态可点击性 | 20min |
| P0 | tableau/assets | 加载动画对齐、选中态对比度 | 20min |
| P1 | 全局 Sidebar | 分类标题层级、图标风格统一 | 30min |
| P1 | 全局 CSS | 滚动条样式、链接样式 | 15min |
| P2 | 各页面 | 间距微调、辅助文本优化 | 45min |

---

## 执行顺序

1. **tailwind.config.ts** - 添加语义化颜色
2. **index.css** - 全局样式增强
3. **ddl-validator/page.tsx** - 对比度修复
4. **database-monitor/page.tsx** - 可访问性修复
5. **tableau/assets/page.tsx** - UI bug 修复
6. **Sidebar 组件** - 统一样式规范
