---
title: P5 · 首页 AskBar 前端设计
aliases:
  - P5 Frontend Spec
  - AskBar
tags:
  - project/mulan-bi
  - type/design-spec
  - phase/v1-mvp
  - owner/frontend
status: ready-for-implementation
created: 2026-04-15
spec_version: v0.1
target_executor: MiniMax-M2.7 / Sonnet
related:
  - "[[Mulan - 首页问数 TODO 协作清单]]"
---

# P5 · 首页 AskBar 前端设计

> [!abstract] 目标
> 首页新增自然语言问数输入框,调用 `POST /api/search/query`,按响应 `type` 渲染为 `number | table | text | error | ambiguous` 卡片。

> [!warning] 前置
> 后端 `/api/search/query` 响应体以实际返回为准(v2 TODO 勘探已确认端点存在,400+ 行实现)。**执行者落地前必须先用 curl 打一次该接口拿到真实 schema**,不得照抄本 spec 的假设字段。

---

## 1. 项目约束(来自 `SPEC_DEVELOPER_PROMPT_TEMPLATE.md`)

- ❌ 不得硬编码 API URL(`http://localhost:8000/...`),走 Vite proxy `/api`
- ❌ 不得 `import` 新页面为同步组件,必须 `React.lazy + Suspense`
- ❌ API 路径不得改(`/api/search/query` 固定)
- ✅ 使用现有 axios/fetch client(若有)
- ✅ TypeScript strict 模式下通过

---

## 2. 技术栈(已确认)

React 19 + TypeScript + Vite + Tailwind(若项目已有) + React Query(可选)

---

## 3. 任务分解

### T1 · 探测后端真实响应(5 分钟,不写代码)

```bash
# 假设后端已跑起来 + admin 已配好 LLM
curl -sS -X POST http://localhost:8000/api/search/query \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<你手动 login 后拿到的 cookie>" \
  -d '{"question":"Q1 销售额是多少"}' | jq

# 记录:顶层字段名(answer / type / data / query / reason / detail ...)
# 若与本 spec §4 TypeScript 类型不一致,以真实为准,改 T2 的类型定义
```

若登录态拿不到 cookie,用 `curl -c cookie.txt -b cookie.txt` 先 `POST /api/auth/login`。

---

### T2 · `frontend/src/api/search.ts`

```typescript
import { apiClient } from './client';  // 若项目无 client,改 fetch + credentials: 'include'

export type SearchAnswerType = 'number' | 'table' | 'text' | 'error' | 'ambiguous';

export interface NumberData {
  value: number;
  unit?: string;
  formatted?: string;
}

export interface TableData {
  columns: string[];
  rows: Array<Record<string, unknown>>;
}

export interface SearchAnswer {
  answer: string;
  type: SearchAnswerType;
  data?: NumberData | TableData | { text?: string; candidates?: Array<{ id: number; name: string }> };
  datasource?: { id: number; name: string };
  query?: unknown;
  confidence?: number;
  reason?: string;           // error 时的 code
  detail?: string;           // error 时的详情
  trace_id?: string;         // 从 P4 新增的审计 trace_id,若后端回传
}

export interface AskQuestionRequest {
  question: string;
  datasource_luid?: string;
  connection_id?: number;
}

export async function askQuestion(req: AskQuestionRequest): Promise<SearchAnswer> {
  const resp = await fetch(`/api/search/query`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const code = err?.detail?.code || err?.code || 'UNKNOWN';
    const msg = err?.detail?.message || err?.message || `HTTP ${resp.status}`;
    throw new SearchError(code, msg);
  }
  return resp.json();
}

export class SearchError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
```

**自验证**:TypeScript 编译无 error(`npm run type-check`)。

---

### T3 · 组件树

```
pages/home/page.tsx
├── <AskBar />                    # 输入框 + 提交 + loading
├── <SearchResult result={...} /> # 根据 type 分发
│     ├── <NumberCard data={data} meta={datasource, confidence} />
│     ├── <TableResult data={data} />
│     ├── <TextAnswer answer={answer} />
│     ├── <ErrorCard code={reason} detail={detail} onRetry={...} />
│     └── <AmbiguousPicker candidates={data.candidates} onPick={...} />
└── <ExamplePrompts onPick={(q) => ask(q)} />
```

所有组件放 `frontend/src/pages/home/components/`,**禁止**放 `components/` 全局目录。

---

### T4 · 关键组件实现要点

#### T4.1 `AskBar.tsx`

```tsx
// 受控输入 + Enter 提交 + 防抖 + loading
// - 输入长度上限 500(后端 MAX_QUERY_LENGTH)
// - 空输入不触发
// - 提交中禁用输入框
// - 提交后清空 or 保留(由 props 控制,默认保留)
```

状态机:
```
idle --(submit)--> loading --(ok)-->  showing_result
                           --(err)-->  showing_error
                                       |
                                       v (new submit) → loading
```

#### T4.2 `NumberCard.tsx`

大字(48px+)+ 单位 + 语义副标题 + tooltip 显示 confidence 与数据源。
若 `confidence < 0.6`,加 ⚠️ "AI 不确定" 徽章。

#### T4.3 `TableResult.tsx`

最多渲染 10 行,超出显示 "共 N 行,已截断显示前 10 行"。
列名从 `data.columns` 来,行数据从 `data.rows`。

#### T4.4 `TextAnswer.tsx`

**XSS 防护必做**:**不得**用 `dangerouslySetInnerHTML` 直接渲染 LLM 输出。
建议:用 `react-markdown` + `rehype-sanitize`,或纯文本 `<pre>` 渲染。
若现仓已有 Markdown 组件,复用。

#### T4.5 `ErrorCard.tsx`

错误码 → 友好文案映射表:

```typescript
export const ERROR_MESSAGES: Record<string, { title: string; hint: string }> = {
  NLQ_001: { title: '问题不合法', hint: '请用完整的中文或英文描述你的问题' },
  NLQ_003: { title: 'LLM 服务暂不可用', hint: '请稍后重试,或联系管理员' },
  NLQ_005: { title: '参数缺失', hint: '请指定数据源后重试' },
  NLQ_006: { title: '查询执行失败', hint: 'Tableau MCP 调用出错,请联系管理员' },
  NLQ_007: { title: '查询超时', hint: '问题较复杂,请简化后重试' },
  NLQ_008: { title: '字段未识别', hint: '没找到与问题相关的数据字段,请换种说法' },
  NLQ_009: { title: '无权限', hint: '该数据源访问被拒绝' },
  NLQ_010: { title: '查询过于频繁', hint: '每分钟最多 20 次,请稍后再试' },
  NLQ_011: { title: '敏感数据不支持查询', hint: '该数据源为高敏级别,请联系管理员' },
  UNKNOWN: { title: '未知错误', hint: '请重试或联系管理员' },
};
```

#### T4.6 `AmbiguousPicker.tsx`(若后端返回 `type=ambiguous`)

- 列出候选数据源(≤ 5)
- 点击某个后,再次调 `askQuestion({question, datasource_luid})`
- 把首轮的 question 缓存在组件 state

---

### T5 · 示例问法

```tsx
// frontend/src/pages/home/components/ExamplePrompts.tsx
export const EXAMPLE_PROMPTS = [
  'Q1 销售额是多少',
  '3 月各区域订单数量',
  '销售额最高的前 5 个产品',
];
```

渲染成 chip,点击填入 AskBar 并自动提交。

---

### T6 · 懒加载 + Suspense

```tsx
// frontend/src/router.tsx(或等价文件)
const HomePage = lazy(() => import('./pages/home/page'));

// <Suspense fallback={<Skeleton />}> 包裹
```

---

### T7 · 单元测试(Vitest + React Testing Library)

```tsx
// frontend/src/pages/home/__tests__/AskBar.test.tsx
describe('AskBar', () => {
  it('空输入不触发提交', () => { /* ... */ });
  it('Enter 键触发提交', () => { /* ... */ });
  it('提交中禁用输入', () => { /* ... */ });
  it('超长输入被截断在 500 字符', () => { /* ... */ });
});

// frontend/src/pages/home/__tests__/SearchResult.test.tsx
describe('SearchResult', () => {
  it('type=number 渲染 NumberCard', () => { /* ... */ });
  it('type=table 渲染 TableResult,超过 10 行显示截断提示', () => { /* ... */ });
  it('type=error 渲染 ErrorCard,未知 code fallback UNKNOWN', () => { /* ... */ });
  it('confidence<0.6 显示警告徽章', () => { /* ... */ });
});

// Mock fetch 测 api/search
describe('askQuestion', () => {
  it('正常返回 parse 正确', async () => { /* ... */ });
  it('HTTP 500 抛 SearchError 含 code', async () => { /* ... */ });
});
```

---

## 4. 响应体(**按真实接口为准,本节为兜底假设**)

### 成功
```json
{
  "answer": "Q1 销售额为 1,234,567 元",
  "type": "number",
  "data": { "value": 1234567, "unit": "元", "formatted": "1,234,567" },
  "datasource": { "id": 1, "name": "sales_db" },
  "confidence": 0.92,
  "trace_id": "a1b2c3d4"
}
```

### 错误
```
HTTP 400/502
{ "detail": { "code": "NLQ_008", "message": "无法匹配到合适字段", "details": {...} } }
```

### Ambiguous(若后端支持)
```json
{
  "answer": "请选择数据源",
  "type": "ambiguous",
  "data": { "candidates": [{"id":1,"name":"sales_db"}, {"id":2,"name":"finance_db"}] }
}
```

---

## 5. DoD(MiniMax 自查)

- [ ] `npm run type-check` 零 error
- [ ] `npm run lint` 零 warning
- [ ] `npm run test` 覆盖本 spec §T7 的全部用例,全绿
- [ ] 本地 `npm run dev` 起服务,首页可见 AskBar + 3 个示例问法
- [ ] 示例问法点击 → 自动提交 → 看到 loading → 看到结果卡片(至少 `error` 或 `text` 其一)
- [ ] ErrorCard 对未知 code 正确 fallback "UNKNOWN"
- [ ] 没有新引入硬编码 `http://localhost:8000`
- [ ] 新页面用 `React.lazy + Suspense` 加载(`grep -R "lazy.*home" frontend/src` 能找到)
- [ ] XSS 检查:`grep -R "dangerouslySetInnerHTML" frontend/src/pages/home` 空结果

---

## 6. 碰到以下情况停下来

| 情况 | 为什么 |
|---|---|
| 后端 `/api/search/query` 实际响应字段与本 spec §4 相差 3+ | 需要对齐,避免类型错配 |
| 项目现有 API client 样式与本 spec `fetch` 不同 | 要遵循既有风格 |
| 项目没有 Tailwind / 已有 UI 组件库(Ant Design 等) | 视觉风格要一致,先问 Forrest |
| 现有 `pages/home/page.tsx` 已有复杂内容 | 不确定 AskBar 怎么嵌入,问 Forrest |
| 需要 MathJax / 复杂图表渲染(非 MVP) | V2 再做 |

---

## 7. 未来延伸

- P5.1 · 历史问答侧栏(localStorage 或后端日志驱动)
- P5.2 · 流式响应(SSE)
- P5.3 · 多轮对话
- P5.4 · 图表自动渲染(数值超过 20 行时)
- P5.5 · 复制 / 分享 结果 URL

---

> [!success] 交付标志
> 首页刷新 → 见 AskBar + 3 个示例 → 点击示例 → 1~5s 内看到数值或错误卡 → 错误卡按错误码显示对应友好文案。
