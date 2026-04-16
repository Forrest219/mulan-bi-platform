# Spec 24 UI 落地实施细则（Designer 接管版）

> 文档目标：承接 Spec 24，给出首页（`/`、`/chat/:id`）与连接中心（`/assets/connection-center`）可直接执行的前端实施细则。  
> 关联规格：Spec 24 / Spec 21 / Spec 18  
> 范围约束：仅产出 UI 与前端实现规范，不改业务逻辑结论；保留 5 域导航体系。

---

## 0. 现状基线与落地方向

基于当前代码（`frontend/src`）确认：

1) 首页体系已初步具备
- 已有 `HomeLayout`、`ConversationBar`、`HomePage`、`ChatPage`
- 已支持 `/` 与 `/chat/:id`
- 已有会话 store（`conversationStore.tsx`）

2) 连接管理仍分裂
- DB 在 `pages/admin/datasources/page.tsx`
- Tableau 在 `pages/tableau/connections/page.tsx`
- 路由为 `/assets/datasources`、`/assets/tableau-connections`
- 尚无统一 `connection-center`

3) 设计 token 已有部分基础
- `tailwind.config.ts` 中已有 `text-primary`、`text-secondary`、`border-light`、`link-primary` 等
- 缺少可复用的 success/warning/danger 语义 token 命名层

落地策略：
- 首页：在现有实现上收敛为“状态机驱动 + 组件职责稳定”
- 连接中心：先统一 UI 壳与 ViewModel，再逐步替换到 `/api/connection-hub/*`

---

## 1. 首页（`/` 与 `/chat/:id`）组件树与状态机

## 1.1 路由与壳层关系

- `/` → `HomeLayout` + `HomePage`
- `/chat/:id` → `HomeLayout` + `ChatPage`
- HomeLayout 负责：
  - 左侧 Conversation Rail
  - 折叠状态持久化（`mulan-home-sidebar-collapsed`）
  - 全局快捷键入口（Cmd/Ctrl+N、Cmd/Ctrl+K）

## 1.2 组件树（执行版）

A. `/`（HomePage）
- `HomeLayout`
  - `ConversationBar`
    - `NewChatButton`
    - `ConversationSearch`
    - `ConversationList`
      - `ConversationItem`（rename/delete menu）
    - `QuickNavLinks`
  - `HomeWorkspace`
    - `ContextStrip`（环境/连接/治理徽章）
    - `WelcomeHero`（空态）
    - `SuggestionGrid`（空态）
    - `ResultTimeline`（结果态，P0 可继续复用 `SearchResult`）
    - `StickyComposer`（复用并改造 `AskBar`）

B. `/chat/:id`（ChatPage）
- `HomeLayout`
  - `ConversationBar`（同上）
  - `ChatWorkspace`
    - `ChatHeader`（标题、返回、导出）
    - `MessageTimeline`
      - `UserBubble`
      - `AssistantBubble`
        - `SearchResultCard`（结构化结果）
        - `DataUsedFooter`（连接、时间戳、权限、Show SQL/logic）
    - `StickyComposer`

## 1.3 状态机（`/`）

状态集合：
- `UNAUTHENTICATED`
- `HOME_IDLE`（欢迎 + 建议问题）
- `HOME_SUBMITTING`
- `HOME_RESULT`
- `HOME_ERROR`
- `HOME_OFFLINE`

关键事件：
- `LOGIN_SUCCESS`
- `SUBMIT_QUESTION`（Enter / 点击建议卡）
- `SUBMIT_SUCCESS`
- `SUBMIT_FAIL`
- `RETRY`
- `NETWORK_OFF`
- `NETWORK_ON`

状态迁移（摘要）：
- `UNAUTHENTICATED -> HOME_IDLE`（登录后）
- `HOME_IDLE -> HOME_SUBMITTING`（提交）
- `HOME_SUBMITTING -> HOME_RESULT`（成功）
- `HOME_SUBMITTING -> HOME_ERROR`（失败）
- `HOME_ERROR -> HOME_SUBMITTING`（重试）
- 任意已登录态 `-> HOME_OFFLINE`（断网）
- `HOME_OFFLINE -> HOME_IDLE|HOME_RESULT|HOME_ERROR`（恢复时回到断开前快照态）

执行约束：
- `AskBar` 在 `HOME_RESULT/HOME_ERROR` 必须保持可输入（不可因错误锁死）
- `SuggestionGrid` 仅在 `HOME_IDLE` 显示

## 1.4 状态机（`/chat/:id`）

状态集合：
- `CHAT_LOADING`
- `CHAT_READY`
- `CHAT_SENDING`
- `CHAT_APPEND_ERROR`
- `CHAT_NOT_FOUND`
- `CHAT_OFFLINE`

关键事件：
- `LOAD_OK` / `LOAD_404`
- `SEND_MESSAGE`
- `SEND_OK` / `SEND_FAIL`
- `RETRY_SEND`
- `NAVIGATE_OTHER_CHAT`

状态迁移（摘要）：
- `CHAT_LOADING -> CHAT_READY`（加载成功）
- `CHAT_LOADING -> CHAT_NOT_FOUND`（对话不存在）
- `CHAT_READY -> CHAT_SENDING`（发送追问）
- `CHAT_SENDING -> CHAT_READY`（返回成功并落消息）
- `CHAT_SENDING -> CHAT_APPEND_ERROR`（发送失败）
- `CHAT_APPEND_ERROR -> CHAT_SENDING`（重试）

执行约束：
- `CHAT_SENDING` 下仅禁用发送按钮，不禁用输入框滚动/历史浏览
- `CHAT_NOT_FOUND` 必须给“返回首页”主 CTA

---

## 2. 连接中心（`/assets/connection-center`）页面结构与交互状态

## 2.1 IA 与路由策略

新增统一入口：`/assets/connection-center`

兼容跳转：
- `/assets/datasources` → `/assets/connection-center?type=db`
- `/assets/tableau-connections` → `/assets/connection-center?type=tableau`

Tab 结构：
- `Overview`
- `DB`
- `Tableau`
- `Sync Logs`
- `Policies`（admin 可见）

## 2.2 页面结构（推荐分层）

- `ConnectionCenterPage`
  - `PageHeader`
    - 标题、副标题
    - `New Connection`
    - `Bulk Actions`
  - `KPIBar`
    - Total / Healthy / Warning / Failed / 24h Success Rate
  - `FilterBar`
    - 搜索、状态、Owner、环境、激活状态
  - `ConnectionTabs`
  - `ConnectionContent`
    - `ConnectionTableView`（默认）
    - `ConnectionCardView`（可切换）
  - `ConnectionDetailDrawer`
    - 基本配置
    - 健康与最近测试
    - 同步日志
    - 审计事件
    - 凭据策略（不回显 secret）

## 2.3 核心交互状态机（连接条目级）

A. Test Connection
- `IDLE -> RUNNING -> SUCCESS | FAIL`
- FAIL 后可 `RETRY`
- 行内反馈 + 全局 toast 双通道

B. Sync Now
- `IDLE -> QUEUED -> RUNNING -> COMPLETED | FAILED`
- `RUNNING` 禁止重复触发

C. Bulk Actions
- `SELECTING -> EXECUTING -> PARTIAL_SUCCESS | SUCCESS | FAIL`
- PARTIAL_SUCCESS 必须给明细（成功 N / 失败 M）

## 2.4 错误态规范

1) 页面级加载失败
- 文案：连接列表加载失败
- 行为：`重试`（主按钮）+ `查看诊断`（次按钮）

2) 操作级失败（test/sync/update）
- 不打断页面；行内红色状态 + toast
- 错误信息可展开查看原始 message（便于运维）

3) 权限错误
- 403 时显示 `无权限执行此操作`，并隐藏对应危险动作（删除/rotate-secret）

## 2.5 空态规范

1) 全局空态（无任何连接）
- 插画 + 文案 + `创建第一个连接`
- 次入口：导入模板（可后续）

2) 过滤空态（有连接但筛选后为空）
- 文案：未找到匹配连接
- 操作：清空筛选

3) Tab 空态（如 Sync Logs 暂无）
- 保留页骨架，只替换内容区为空态卡

---

## 3. Design Token → 现有 Tailwind/组件映射建议

## 3.1 颜色映射

| 设计 token | 建议 Tailwind 映射 | 现状 | 建议 |
|---|---|---|---|
| `bg.canvas #F8FAFC` | `bg-slate-50` | 已可用 | 直接用 |
| `bg.surface #FFFFFF` | `bg-white` | 已可用 | 直接用 |
| `border.default #E2E8F0` | `border-slate-200` / `border-light` | 已可用 | 统一优先 `border-slate-200` |
| `text.primary #1A202C` | `text-text-primary` / `text-slate-900` | 已可用 | 首页主文本统一 `text-text-primary` |
| `text.tertiary #6B7280` | `text-text-placeholder` / `text-slate-500` | 已可用 | 辅助文案统一 `text-text-placeholder` |
| `accent.primary #2563EB` | `bg-blue-600 text-white` | 已可用 | 主 CTA 专用 |
| `accent.primary.hover #1D4ED8` | `hover:bg-blue-700` | 已可用 | 主 CTA hover |
| `success #059669` | `text-emerald-600 bg-emerald-50` | 类可用，语义 token 未命名 | 建议在 Tailwind extend 增加 `status-success` 别名 |
| `warning #D97706` | `text-amber-600 bg-amber-50` | 类可用，语义 token 未命名 | 同上 |
| `danger #DC2626` | `text-red-600 bg-red-50` | 类可用，语义 token 未命名 | 同上 |

## 3.2 排版/圆角/动效映射

- title 24/32/700 → `text-2xl font-bold leading-8`
- h2 18/28/600 → `text-lg font-semibold leading-7`
- body 14/22/400 → `text-sm leading-6`
- caption 12/18/400 → `text-xs leading-5`

- radius 8/10/12/16 → `rounded-lg` / `rounded-[10px]` / `rounded-xl` / `rounded-2xl`
- transition 150-220ms → `transition-all duration-150`、`duration-200`
- overlay shadow → `shadow-xl`（抽屉/模态）

## 3.3 组件复用优先级

1) 复用：`ConfirmModal`（删除/批量高风险动作）
2) 复用：`HomeLayout` / `AppShellLayout`（避免新增壳组件分叉）
3) 新增轻组件，避免引入大型 UI 库（保持现有 Tailwind + Remix Icon 体系）

---

## 4. 无障碍与键盘交互规范

## 4.1 首页与聊天页

- `AskBar textarea`：
  - `aria-label="输入你的数据问题"`
  - Enter 提交、Shift+Enter 换行
- `ConversationItem`：当前项加 `aria-current="true"`
- 折叠按钮：维护 `aria-expanded`
- 建议卡：`role="button"` + `tabIndex=0` + Enter/Space 触发
- 删除确认弹窗：
  - 打开后焦点进入弹窗
  - Esc 关闭
  - 关闭后焦点返回触发按钮

## 4.2 连接中心

- 表格视图：
  - 列头可聚焦并支持 Enter 排序（如后续支持排序）
  - 行操作按钮必须有 `aria-label`（包含连接名）
- Drawer：
  - `role="dialog"`、`aria-modal="true"`
  - 开启后焦点锁定，Esc 关闭，关闭后焦点回到来源行
- 批量选择：
  - 提供“已选择 N 项”的屏幕阅读器可读文本

## 4.3 全局键盘约定

- Cmd/Ctrl + K：聚焦输入框（首页/聊天）
- Cmd/Ctrl + N：新建对话
- Esc：
  - 若在输入框：清空（不关闭页面）
  - 若在 Drawer/Modal：关闭
- Tab 顺序：左栏 → 主区内容 → 输入区/操作区，不跳跃

---

## 5. 前端分迭代实施清单（文件路径级）

说明：以下为建议分期，按“先壳后能力、先兼容后替换”执行。

## Iteration A（首页状态机收敛，P0.5）

目标：统一 `/` 与 `/chat/:id` 的状态定义，减少逻辑散落。

涉及文件：
- `frontend/src/pages/home/page.tsx`（按状态机重排渲染分支）
- `frontend/src/pages/chat/page.tsx`（状态常量化）
- `frontend/src/pages/home/components/AskBar.tsx`（sticky composer 样式统一）
- `frontend/src/pages/home/components/ConversationBar.tsx`（可访问性细化）
- `frontend/src/store/conversationStore.tsx`（补充错误态字段可选）

验收：
- 首页/聊天状态切换清晰，无重复 loading/error 逻辑
- 断网与重试行为可预测

## Iteration B（连接中心路由与页面骨架，P1）

目标：建立 `/assets/connection-center`，先跑通统一视图与兼容跳转。

新增文件：
- `frontend/src/pages/assets/connection-center/page.tsx`
- `frontend/src/pages/assets/connection-center/components/ConnectionKPIBar.tsx`
- `frontend/src/pages/assets/connection-center/components/ConnectionFilterBar.tsx`
- `frontend/src/pages/assets/connection-center/components/ConnectionTableView.tsx`
- `frontend/src/pages/assets/connection-center/components/ConnectionCardView.tsx`
- `frontend/src/pages/assets/connection-center/components/ConnectionDetailDrawer.tsx`
- `frontend/src/pages/assets/connection-center/model.ts`

修改文件：
- `frontend/src/router/config.tsx`（新增 route + 旧路由 redirect）
- `frontend/src/config/menu.ts`（资产域菜单新增“连接中心”）

验收：
- 可从菜单进入连接中心
- `/assets/datasources` 与 `/assets/tableau-connections` 可正确跳转

## Iteration C（统一 ViewModel 与操作状态，P1.5）

目标：把 DB/Tableau 两类连接映射到同一前端模型，支持 Test/Sync/Bulk 状态。

新增文件：
- `frontend/src/api/connection-center.ts`（前端聚合层，先适配现有 `datasources.ts` + `tableau.ts`）
- `frontend/src/pages/assets/connection-center/adapters/fromDatasources.ts`
- `frontend/src/pages/assets/connection-center/adapters/fromTableau.ts`

修改文件：
- `frontend/src/pages/admin/datasources/page.tsx`（入口按钮引导到 connection-center，可保留原页）
- `frontend/src/pages/tableau/connections/page.tsx`（同上）

验收：
- 单页可展示两类连接，状态徽章统一
- Test/Sync 支持行级 loading 与结果反馈

## Iteration D（接入 `/api/connection-hub/*`，P2）

目标：从前端聚合层切到后端统一 API。

修改文件：
- `frontend/src/api/connection-center.ts`（请求切换到 `/api/connection-hub/*`）
- `frontend/src/pages/assets/connection-center/*`（字段映射与错误处理）

可选新增：
- `frontend/src/api/audit.ts`（抽屉审计事件）
- `frontend/src/api/governance.ts`（Policies tab）

验收：
- 新 API 下连接中心行为一致
- 错误态、空态、权限态齐全

## Iteration E（无障碍与交互完善，P2.5）

目标：完成键盘与可访问性闭环。

涉及文件：
- `frontend/src/pages/home/components/*.tsx`
- `frontend/src/pages/chat/page.tsx`
- `frontend/src/pages/assets/connection-center/components/*.tsx`
- `frontend/src/components/ConfirmModal.tsx`

验收：
- 键盘可完成核心流程（新建对话、发送、切换连接、执行 test/sync）
- Modal/Drawer 焦点管理完整

---

## 6. 设计落地红线（防偏移）

1) 不回退为“菜单先于任务”的首页心智；首页必须是工作台，不是图标导航页。  
2) 连接中心必须保留“统一视图 + 类型筛选”，不能回到 DB/Tableau 双孤岛。  
3) 治理信号色（绿黄红）只用于健康/风险，不用于主导航与主 CTA。  
4) 所有 destructive 操作必须二次确认（复用 `ConfirmModal`）。

---

## 7. 完成定义（DoD）

- 首页 `/` 与 `/chat/:id`：组件边界明确、状态机可落图并可测试。
- 连接中心 `/assets/connection-center`：结构、交互态、错误态、空态完整。
- Design token 与 Tailwind 映射已形成统一约定，团队可按约定编码。
- 无障碍与键盘规范可执行、可验收。
- 分迭代清单具备文件路径粒度，可直接拆任务进入开发。
