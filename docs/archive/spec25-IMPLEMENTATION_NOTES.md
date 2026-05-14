# IMPLEMENTATION_NOTES.md — Spec 25 Gap-05: SSE流式输出（前后端集成）

## 任务
SSE流式输出 — 前后端集成

## 变更文件

| 文件 | 变更 |
|------|------|
| `frontend/src/components/chat/MessageBubble.tsx` | 修复 import 错误 |

## 实现状态：已完成

### Backend SSE Streaming (`backend/app/api/chat.py`)

POST `/api/chat/stream` 端点已实现：

- 使用 `StreamingResponse` + `text/event-stream`
- SSE 格式：
  - `data: {"token": "部分文字 "}\n\n` — 中间 token
  - `data: {"done": true}\n\n` — 流结束信号
  - `data: {"error": "..."}\n\n` — 错误信号
- 完整的 fallback 链：Agent 直接调用 → Agent 转发 → search query

```python
@router.post("/stream")
async def chat_stream_post(request: Request, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    body = await request.json()
    question = body.get("q", body.get("question", ""))
    return StreamingResponse(
        _chat_stream_with_fallback(question=question, ...),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### Frontend SSE Streaming Hook (`frontend/src/hooks/useStreamingChat.ts`)

`useStreamingChat` hook 已完整实现：

- 状态完全隔离于 AskBar（避免 re-render 污染）
- `useRef` buffer + `requestAnimationFrame` batch flush（每帧 ~16ms 批量合并 token）
- `fetch` + `ReadableStream` 消费 `text/event-stream`
- `AbortController` 支持 `stopStreaming()`

```typescript
export function useStreamingChat(): UseStreamingChatReturn {
  const [messages, setMessages] = useState<StreamingMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const bufferRef = useRef('');
  const rafRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const flushBuffer = useCallback(() => {
    const buffered = bufferRef.current;
    bufferRef.current = '';
    // ... batch flush to state
  }, []);

  // sendMessage uses streamAgent which consumes SSE
  // ...
}
```

### Frontend AskBar Integration

`frontend/src/pages/home/page.tsx` 中：

- `USE_MOCK = false`（使用真实 SSE 路径）
- `useStreamingChat` hook 与 `AskBar` 状态隔离
- `AskBar` 提交时调用 `sendMessage` 发起 SSE 流

### MessageBubble Streaming Cursor Animation

`frontend/src/components/chat/MessageBubble.tsx` 已实现：

```tsx
{isStreaming ? (
  <div className="prose prose-sm max-w-none prose-slate">
    <p className="whitespace-pre-wrap break-words leading-relaxed m-0">{content}</p>
    <span className="inline-block w-2 h-4 bg-slate-400 animate-pulse ml-0.5 align-middle rounded-sm" />
  </div>
) : ( ... )}
```

## 修复的问题

### Import 错误 (`components/chat/MessageBubble.tsx`)

**问题**：第 18 行错误地将 named export `MessageActions` 作为 default import 使用：

```tsx
// 错误（修复前）
import MessageActions from '../../pages/home/components/MessageActions';
```

`MessageActions` 在 `frontend/src/pages/home/components/MessageActions.tsx` 中定义为：
```tsx
export function MessageActions({ ... }) { ... }
```

**修复**：

```tsx
// 正确（修复后）
import { MessageActions } from '../../pages/home/components/MessageActions';
```

## 验证

- Backend: `python3 -m py_compile app/api/chat.py` ✅ 通过
- Frontend: `npm run type-check` ✅ 通过（零 TypeScript 错误）

## 数据流

```
用户提交问题
    ↓
AskBar.onSend → page.tsx handleLoading
    ↓
useStreamingChat.sendMessage()
    ↓
streamAgent() → POST /api/agent/stream
    ↓
ReadableStream 解析 SSE events
    ↓
token events → bufferRef.current += content
    ↓
requestAnimationFrame(flushBuffer)
    ↓
setMessages() 更新 MessageBubble
    ↓
MessageBubble 渲染 + streaming cursor 动画
```

---

## Batch 3: AskBar 样式打磨 (2026-04-29)

### 变更文件
- `frontend/src/components/chat/AskBar.tsx`

### 详细变更

#### 1. 容器圆角与阴影增强（第 176-185 行）

**改前:**
```tsx
className={[
  'rounded-2xl border shadow-sm',
  'backdrop-blur-sm bg-white/80',
  'border-slate-200/60',
  'focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20',
  'transition-[border-color,box-shadow] duration-150',
  disabled ? 'opacity-50 cursor-not-allowed' : '',
].join(' ')}
```

**改后:**
```tsx
className={[
  'rounded-3xl border shadow-md',
  'backdrop-blur-sm bg-white/80',
  'border-slate-200/60',
  'focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:shadow-lg',
  'transition-[border-color,box-shadow] duration-200',
  disabled ? 'opacity-50 cursor-not-allowed' : '',
].join(' ')}
```

变更摘要:
- `rounded-2xl` → `rounded-3xl`: 更大圆角提升视觉柔和度
- `shadow-sm` → `shadow-md`: 更明显的阴影层次
- 新增 `focus-within:shadow-lg`: 聚焦时阴影扩散效果
- `duration-150` → `duration-200`: 过渡动画稍慢更平滑

#### 2. 附件气泡阴影增强（第 41、49 行）

- 图片预览气泡: `shadow-sm` → `shadow-md`
- 文件气泡: `shadow-sm` → `shadow-md`

#### 3. 附件删除按钮 hover 效果增强（第 70-79 行）

变更摘要:
- `transition-opacity` → `transition-all`: 支持 transform 动画
- `ease-out`: 动画缓出曲线
- 新增 `hover:scale-110`: hover 时轻微放大
- 新增 `active:scale-95`: 点击时收缩反馈

#### 4. 筛选标签 hover 效果增强（第 221-234 行）

变更摘要:
- `transition-colors` → `transition-all`: 支持阴影动画
- `duration-150` → `duration-200`: 更平滑的过渡
- 新增 `ease-out`: 缓出曲线
- 激活态新增 `shadow-sm`: 选中态有轻微阴影
- 非激活态 hover 新增 `hover:shadow-sm` 和 `hover:border-slate-300`

#### 5. 附件按钮 hover 效果增强（第 243-260 行）

变更摘要:
- `transition-colors` → `transition-all`: 支持阴影动画
- 新增 `hover:shadow-sm`: hover 时有轻微阴影

#### 6. 发送按钮 hover 效果增强（第 263-285 行）

变更摘要:
- `w-8 h-8` → `w-9 h-9`: 按钮稍大
- `transition-colors` → `transition-all`: 支持 transform 动画
- `duration-150` → `duration-200`: 更平滑的过渡
- 新增 `ease-out`: 缓出曲线
- 新增 `hover:shadow-md`: hover 时阴影扩散
- 新增 `hover:scale-105`: hover 时轻微放大
- 新增 `active:scale-95`: 点击时收缩反馈

---

## Batch 4: LoadingSpinner 组件 (2026-04-29)

### 新增文件
- `frontend/src/components/chat/LoadingSpinner.tsx`

### 组件导出

| 导出名称 | 用途 | 使用场景 |
|---------|------|---------|
| `Spinner` | 通用旋转指示器 | 按钮内、卡片内加载状态 |
| `ChatLoadingDots` | 三点加载动画 | 聊天消息流式输出中 |
| `FullPageLoader` | 全屏加载遮罩 | 页面级加载状态 |
| `ButtonSpinner` | 按钮内置加载 | 表单提交按钮 |

### Spinner 变体

```tsx
// 小尺寸 (16px)
<Spinner size="sm" />

// 中尺寸 (20px，默认)
<Spinner size="md" />

// 大尺寸 (24px)
<Spinner size="lg" />
```

### ChatLoadingDots 用法

```tsx
// 替代内联三点动画
<ChatLoadingDots />

// 自定义样式
<ChatLoadingDots className="text-blue-400" />
```

### FullPageLoader 用法

```tsx
// 默认文案
<FullPageLoader />

// 自定义文案
<FullPageLoader message="正在加载数据..." />
```

### ButtonSpinner 用法

```tsx
// 纯加载
<ButtonSpinner />

// 带文案
<ButtonSpinner label="提交中..." />
```

---

## 约束遵守

- [x] 不改动 SSE 接入点
- [x] 不改动 AskBar 提交逻辑
- [x] 不改动 streaming 相关逻辑
- [x] 所有类名在 Tailwind v3 范围内
- [x] TypeScript 严格模式，无 any

---

## 验证

```bash
cd frontend && npm run type-check
```

注意: `npm run type-check` 报告的 MessageBubble.tsx 错误是预存在问题，与本次 Batch 3-4 变更无关。

---

## 后续建议

1. **Batch 5 可选**: 将 AskBar.tsx 迁移至 `frontend/src/pages/home/components/AskBar.tsx`（如 spec 中指定的路径）
2. **LoadingSpinner 推广**: 逐步替换分散在各处的内联 `animate-spin` 样式，统一使用 LoadingSpinner 组件
3. **深色模式适配**: LoadingSpinner 的颜色基于浅色模式设计，深色模式适配待后续完成

---

## Phase 2 Batch 1-2: MessageBubble UI 优化 (2026-04-29)

### 变更文件

| 文件 | 变更 |
|------|------|
| `frontend/src/components/chat/MessageBubble.tsx` | Batch 1 + Batch 2 |
| `frontend/src/pages/home/components/MessageActions.tsx` | Batch 2（新增 edit/delete 按钮） |

---

### Batch 1: 用户消息右对齐微调

**文件:** `frontend/src/components/chat/MessageBubble.tsx`

**改前:**
```tsx
<div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
```

**改后:**
```tsx
<div className={`flex ${isUser ? 'flex-row-reverse' : 'justify-start'} mb-4 group`}>
```

**说明:**
- 将 `justify-end` 替换为 `flex-row-reverse`，实现用户消息右对齐
- 添加 `group` class 支持 hover 交互（供 MessageActions 使用）

---

### Batch 2: MessageActions 组件集成

#### 2.1 MessageActions 新增 edit/delete 按钮

**文件:** `frontend/src/pages/home/components/MessageActions.tsx`

**新增 Props:**
```typescript
interface MessageActionsProps {
  // ... existing props
  /** Callback when user clicks edit */
  onEdit?: (content: string) => void;
  /** Callback when user clicks delete */
  onDelete?: () => void;
}
```

**新增按钮:**
- **编辑按钮** (when `onEdit` provided): `ri-edit-line` icon
- **删除按钮** (when `onDelete` provided): `ri-delete-bin-line` icon，hover 时变红色

#### 2.2 MessageBubble Props 扩展

```typescript
export interface MessageBubbleProps {
  // ... existing props
  /** Conversation ID for feedback/rating */
  conversationId?: string | null;
  /** Message index in the conversation for feedback */
  messageIndex?: number;
  /** The user question this message responds to */
  question?: string;
  /** Callback when user clicks edit */
  onEdit?: (content: string) => void;
  /** Callback when user clicks delete */
  onDelete?: () => void;
}
```

#### 2.3 MessageBubble 集成位置

**文件:** `frontend/src/components/chat/MessageBubble.tsx`

```tsx
<div className={`flex ${isUser ? 'flex-row-reverse' : 'justify-start'} mb-4 group`}>
  <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm ...`}>
    {/* 气泡内容 */}
  </div>
  {/* MessageActions: hover 时显示在气泡下方 */}
  {!isUser && !isStreaming && (
    <MessageActions
      content={content}
      conversationId={conversationId ?? null}
      messageIndex={messageIndex ?? 0}
      question={question ?? ''}
      traceId={traceId}
      onEdit={onEdit}
      onDelete={onDelete}
    />
  )}
</div>
```

---

### SSE/Streaming 相关逻辑

**未修改。** `isStreaming` prop 继续控制:
- 流式输出末尾的光标动画
- 流式输出期间 MessageActions 不显示

---

### 验证

```bash
cd frontend && npm run type-check
# No errors ✅
```

---

### 向后兼容

所有新增 props 都是可选的，使用 `??` 提供默认值：
- `conversationId ?? null`
- `messageIndex ?? 0`
- `question ?? ''`

现有 MessageBubble 调用方式不受影响。
