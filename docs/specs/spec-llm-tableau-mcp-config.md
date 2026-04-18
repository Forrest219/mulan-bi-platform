# SPEC：LLM 接入 + Tableau MCP 状态管理

- **状态**：待实施
- **创建**：2026-04-17
- **执行者**：coder

---

## 改动范围总览

| 模块 | 改动性质 | 文件 |
|------|---------|------|
| LLM 接入 | **零后端改动**，仅通过现有 API 写入配置 | — |
| LLM 前端表单升级 | 表单 UI 优化 | `frontend/src/pages/admin/llm-configs/page.tsx` |
| Tableau MCP 状态 | 追加后端端点 | `backend/app/api/tableau.py` |
| Tableau MCP 前端 | 新增状态卡片 | `frontend/src/pages/admin/llm-configs/page.tsx`（或新建 integrations 页） |

---

## Task 1：写入 DeepSeek LLM 配置（curl，无代码改动）

架构确认：`POST /api/llm/configs` 接口已存在，字段完整覆盖，`ai_llm_configs` 表已有 `purpose`、`display_name`、`priority` 字段，**无需数据库迁移**。

### 1-A 写入配置

先登录获取 session cookie，再调用：

```bash
# Step 1：登录
curl -c /tmp/mulan-cookie.txt -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Step 2：写入 DeepSeek 配置
curl -b /tmp/mulan-cookie.txt -X POST http://localhost:8000/api/llm/configs \
  -H "Content-Type: application/json" \
  -d '{
    "display_name": "金山云 DeepSeek-R1",
    "provider": "openai",
    "base_url": "https://kspmas.ksyun.com/v1",
    "api_key": "b57c3bf5-xxxx-xxxx-xxxx-xxxxbd4d9e62",
    "model": "deepseek-r1-0528",
    "temperature": 0.7,
    "max_tokens": 4096,
    "purpose": "default",
    "priority": 10,
    "is_active": true
  }'
```

> `priority: 10` 高于默认值 0，确保多配置时优先选中此条。

### 1-B 验证连通

```bash
curl -b /tmp/mulan-cookie.txt -X POST http://localhost:8000/api/llm/config/test \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say OK in one word"}'
# 期望：{"success": true, "message": "..."}
```

---

## Task 2：后端新增 `GET /api/tableau/mcp-status`

**文件**：`backend/app/api/tableau.py` — 在文件**末尾**追加，不改动现有代码。

### 依赖确认

`httpx` 已在 `backend/services/llm/service.py` 中使用，无需新增依赖。

### 追加代码

```python
# ── Tableau MCP Server 状态检查 ─────────────────────────────────────────────

import time as _time

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore

from services.common.settings import get_tableau_mcp_server_url, get_tableau_mcp_timeout


@router.get("/mcp-status")
async def get_mcp_status():
    """探测 Tableau MCP Server 连通性（UI 状态指示器用）"""
    url = get_tableau_mcp_server_url()
    timeout = min(get_tableau_mcp_timeout(), 5)
    start = _time.monotonic()
    if _httpx is None:
        return {"status": "unknown", "url": url, "latency_ms": 0, "error": "httpx not installed"}
    try:
        async with _httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {
            "status": "online",
            "url": url,
            "latency_ms": latency_ms,
            "http_status": resp.status_code,
        }
    except (_httpx.ConnectError, _httpx.TimeoutException) as e:
        latency_ms = int((_time.monotonic() - start) * 1000)
        return {
            "status": "offline",
            "url": url,
            "latency_ms": latency_ms,
            "error": type(e).__name__,
        }
```

> 逻辑：任何 HTTP 响应（含 4xx/5xx）均视为 online，仅 TCP 连接失败视为 offline。

### 验收 curl

```bash
curl http://localhost:8000/api/tableau/mcp-status
# MCP 已启动：{"status":"online","url":"http://localhost:3927/tableau-mcp","latency_ms":xx}
# MCP 未启动：{"status":"offline","url":"http://localhost:3927/tableau-mcp","error":"ConnectError"}
```

---

## Task 3：前端 LLM 配置表单升级

**文件**：`frontend/src/pages/admin/llm-configs/page.tsx`

> 先完整读取该文件再实施，以下为精确改动规格。

### 3-A Modal 宽度扩大

```diff
- max-w-lg
+ max-w-xl
```

### 3-B 表单字段分 3 组

在字段区域增加分组结构，组间用分隔线：

```tsx
{/* 组分隔 */}
<div className="border-t border-slate-100 pt-4 mt-4">
  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
    {组标题}
  </p>
  {/* 字段 */}
</div>
```

三组：
- **组 A 身份识别**：`display_name`、`purpose`
- **组 B Provider 连接**：`provider`、`base_url`、`api_key`、`model`
- **组 C 调用参数**：`temperature`、`max_tokens`、`priority`、`is_active`

### 3-C purpose 改为 select

```tsx
// 改动前：<input type="text" placeholder="general / nl_query / summary ..." />
// 改动后：
<select ...>
  <option value="default">default — 通用默认</option>
  <option value="nl_query">nl_query — 自然语言查询</option>
  <option value="summary">summary — 数据摘要</option>
</select>
```

### 3-D provider 扩充选项

```tsx
<select ...>
  <option value="openai">OpenAI</option>
  <option value="openai-compatible">OpenAI Compatible（第三方）</option>
  <option value="anthropic">Anthropic</option>
</select>
```

### 3-E api_key 改为 password 类型

```diff
- <input type="text" ...>
+ <input type="password" autoComplete="new-password" ...>
```

编辑态 label 右侧保留现有灰字：`（留空则不更新）`

编辑态且 `config.has_api_key` 为 true 时，input 下方补一行：
```tsx
<p className="mt-1 text-xs text-slate-400">
  <i className="ri-shield-check-line mr-1" />已配置 API Key
</p>
```

### 3-F is_active 改为 toggle switch

```tsx
// 改动前：<input type="checkbox" />
// 改动后：
<label className="flex items-center justify-between py-1 cursor-pointer">
  <span className="text-sm text-slate-700">启用此配置</span>
  <div
    className={`relative w-10 h-6 rounded-full transition-colors ${
      form.is_active ? 'bg-emerald-500' : 'bg-slate-200'
    }`}
    onClick={() => setForm(f => ({ ...f, is_active: !f.is_active }))}
  >
    <div className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-sm transition-transform ${
      form.is_active ? 'translate-x-4' : ''
    }`} />
  </div>
</label>
```

### 3-G temperature 和 max_tokens 两列布局

```tsx
<div className="grid grid-cols-2 gap-3">
  <div>/* temperature input */</div>
  <div>/* max_tokens input */</div>
</div>
```

### 3-H "测试连接"按钮

**仅在编辑模式**（`editingId !== null`）下渲染，新建态不显示。

位置：Modal footer，左端（`flex justify-between`，按钮分两侧）：

```tsx
<div className="flex items-center justify-between pt-4 border-t border-slate-100 mt-4">
  {/* 左端：测试连接（仅编辑态） */}
  {editingId && (
    <div className="flex flex-col items-start gap-2">
      <button
        onClick={handleTestConnection}
        disabled={testing}
        className={`px-3 py-1.5 text-xs border rounded-lg transition-colors flex items-center gap-1.5 ${
          testResult?.success
            ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
            : testResult?.success === false
              ? 'border-red-200 bg-red-50 text-red-600'
              : 'border-slate-200 text-slate-500 hover:bg-slate-50'
        }`}
      >
        <i className={`text-xs ${
          testing ? 'ri-loader-4-line animate-spin' :
          testResult?.success ? 'ri-check-line' :
          testResult?.success === false ? 'ri-close-circle-line' :
          'ri-signal-wifi-line'
        }`} />
        {testing ? '测试中...' : testResult?.success ? '连接正常' : testResult?.success === false ? '连接失败' : '测试连接'}
      </button>
      {/* 测试结果详情 */}
      {testResult && (
        <p className={`text-xs px-2 py-1 rounded ${
          testResult.success ? 'text-emerald-700 bg-emerald-50' : 'text-red-600 bg-red-50'
        }`}>
          {testResult.message}
        </p>
      )}
    </div>
  )}
  {/* 右端：取消 + 保存 */}
  <div className={`flex gap-2 ${!editingId ? 'ml-auto' : ''}`}>
    <button onClick={handleClose}>取消</button>
    <button onClick={handleSave}>{editingId ? '保存修改' : '创建配置'}</button>
  </div>
</div>
```

**测试连接调用**：`POST /api/llm/config/test`，复用现有 `testLLMConnection` 函数（如已存在）或新增：

```ts
const handleTestConnection = async () => {
  setTesting(true);
  setTestResult(null);
  try {
    const res = await fetch('/api/llm/config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: 'Say OK in one word' }),
    });
    const data = await res.json();
    setTestResult({ success: data.success, message: data.message ?? (data.success ? '连接正常' : '连接失败') });
  } catch {
    setTestResult({ success: false, message: '请求异常，请检查网络' });
  } finally {
    setTesting(false);
  }
};
```

新增 state：
```ts
const [testing, setTesting] = useState(false);
const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
```

---

## Task 4：前端 Tableau MCP 状态卡片

**位置决策**：在现有 `llm-configs/page.tsx` 页面底部新增分节，不新建路由。与 LLM 配置主题相关（均为 AI 能力基础设施配置），无需独立页面。

在页面末尾（LLM 列表下方）追加以下结构：

```tsx
{/* ── Tableau MCP 集成 ──────────────────────────────── */}
<section className="mt-10">
  <div className="flex items-center gap-2 mb-4">
    <i className="ri-puzzle-line text-slate-400" />
    <h2 className="text-sm font-semibold text-slate-700">Tableau MCP 集成</h2>
  </div>

  <div className="bg-white border border-slate-200 rounded-xl p-5">
    {/* 顶部：图标 + 信息 + badge */}
    <div className="flex items-start justify-between">
      <div className="flex items-start gap-3">
        <i className="ri-server-line text-xl text-slate-300 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-slate-700">MCP 服务器</p>
          <p className="text-xs text-slate-400 font-mono mt-0.5">{mcpStatus?.url ?? 'http://localhost:3927/tableau-mcp'}</p>
          <p className="text-xs text-slate-400 mt-1">由环境变量 TABLEAU_MCP_SERVER_URL 配置</p>
        </div>
      </div>
      {/* 状态 badge */}
      <StatusBadge status={mcpStatus?.status ?? 'unknown'} />
    </div>

    {/* 分隔线 + 操作区 */}
    <div className="border-t border-slate-100 mt-4 pt-4 flex items-start justify-between gap-4">
      {/* 测试结果 */}
      {mcpTestResult && (
        <div className={`flex-1 px-3 py-2 rounded-lg text-xs border ${
          mcpTestResult.status === 'online'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-red-50 border-red-200 text-red-700'
        }`}>
          {mcpTestResult.status === 'online'
            ? `连接正常 · 响应 ${mcpTestResult.latency_ms}ms`
            : `无法连接：${mcpTestResult.error ?? '连接失败'}`}
        </div>
      )}
      {/* 测试按钮 */}
      <button
        onClick={handleTestMcp}
        disabled={mcpTesting}
        className="shrink-0 px-3 py-1.5 text-xs border border-slate-200 rounded-lg text-slate-500 hover:bg-slate-50 flex items-center gap-1.5 transition-colors"
      >
        <i className={`text-xs ${mcpTesting ? 'ri-loader-4-line animate-spin' : 'ri-refresh-line'}`} />
        {mcpTesting ? '检测中...' : '测试连接'}
      </button>
    </div>
  </div>
</section>
```

**StatusBadge 内联组件**（在同文件定义，不新建文件）：

```tsx
function StatusBadge({ status }: { status: 'online' | 'offline' | 'unknown' }) {
  const map = {
    online: { dot: 'bg-emerald-500', text: 'text-emerald-700 bg-emerald-100', label: '在线' },
    offline: { dot: 'bg-red-500', text: 'text-red-600 bg-red-100', label: '离线' },
    unknown: { dot: 'bg-slate-300', text: 'text-slate-400 bg-slate-100', label: '未检测' },
  };
  const s = map[status] ?? map.unknown;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
```

**新增 state 和逻辑**：

```ts
const [mcpStatus, setMcpStatus] = useState<{ status: 'online' | 'offline' | 'unknown'; url: string; latency_ms?: number } | null>(null);
const [mcpTesting, setMcpTesting] = useState(false);
const [mcpTestResult, setMcpTestResult] = useState<{ status: string; latency_ms?: number; error?: string } | null>(null);

// 页面挂载时自动检测一次（只更新 badge，不展示结果详情）
useEffect(() => {
  fetch('/api/tableau/mcp-status')
    .then(r => r.json())
    .then(data => setMcpStatus(data))
    .catch(() => setMcpStatus({ status: 'unknown', url: '' }));
}, []);

const handleTestMcp = async () => {
  setMcpTesting(true);
  try {
    const r = await fetch('/api/tableau/mcp-status');
    const data = await r.json();
    setMcpStatus(data);
    setMcpTestResult(data);
  } catch {
    setMcpTestResult({ status: 'offline', error: 'fetch 异常' });
  } finally {
    setMcpTesting(false);
  }
};
```

---

## 验收清单

### Task 1（LLM 配置写入）
- [ ] `GET /api/llm/configs` 返回列表中包含 `model: deepseek-r1-0528` 的条目
- [ ] `POST /api/llm/config/test` 返回 `success: true`（网络可达时）
- [ ] 前端管理后台 LLM 配置列表展示新条目，`is_active` 为启用态

### Task 2（MCP 状态端点）
- [ ] `curl http://localhost:8000/api/tableau/mcp-status` 有响应（无 500）
- [ ] MCP 未启动时返回 `status: offline`
- [ ] 无 Python ImportError

### Task 3（前端表单升级）
- [ ] Modal 宽度扩大，字段无截断
- [ ] `purpose` 渲染为 select，有三个选项
- [ ] `api_key` input 类型为 password，内容遮蔽
- [ ] `is_active` 为 toggle switch，点击切换
- [ ] 编辑态底部显示"测试连接"按钮，新建态不显示
- [ ] 测试连接成功/失败后按钮颜色正确变化

### Task 4（MCP 状态卡片）
- [ ] 页面加载后自动发起检测，badge 状态更新
- [ ] 点击"测试连接"后 badge 和结果详情更新
- [ ] URL 显示为环境变量实际值（从 API 返回）
- [ ] TypeScript 编译无报错

---

## 约束

- Task 2 仅追加代码到 `tableau.py` 末尾，不修改现有路由或函数
- Task 3 不改动 LLM 配置的 API 调用逻辑，仅改 UI
- 不新建路由页面
- 不引入新的 npm 或 pip 依赖
