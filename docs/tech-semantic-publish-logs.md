# 语义发布记录 - 技术设计方案

> 文档版本：v1.0
> 日期：2026-04-01
> 状态：草案
> 适用范围：语义发布记录前后端实现

---

## 一、能力目标

展示语义发布（Publish）操作的历史记录，包含：
- 发布对象（数据源 / 字段）
- 发布状态（成功 / 失败 / 回滚）
- 操作人
- 发布时间
- 差异预览（Diff）

---

## 二、后端方案

### 2.1 补充缺失接口

`publish.py` 中 `list_publish_logs` 方法已存在，但缺少 HTTP 端点暴露。

**补充端点**：在 `backend/app/api/semantic_maintenance/publish.py` 中添加

```python
@router.get("/publish/logs")
async def list_publish_logs(
    request: Request,
    connection_id: int = Query(..., description="Tableau 连接 ID"),
    object_type: Optional[str] = Query(None, description="过滤：datasource / field"),
    status: Optional[str] = Query(None, description="过滤：pending / success / failed / rolled_back"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取发布日志列表"""
    user = get_current_user(request)
    _verify_connection_access(connection_id, user)

    sm = _sm_service()
    items, total = sm.db.list_publish_logs(
        connection_id=connection_id,
        object_type=object_type,
        status=status,
        page=page,
        page_size=page_size,
    )

    return {
        "items": [log.to_dict() for log in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }
```

### 2.2 日志记录触发点（已有）

| 发布操作 | 触发创建日志 | 代码位置 |
|---------|-------------|---------|
| 发布数据源 | `create_publish_log` | `publish_service.py` |
| 发布字段 | `create_publish_log` | `publish_service.py` |
| 重试发布 | `create_publish_log` | `publish_service.py` |
| 回滚发布 | `create_publish_log` | `publish_service.py` |

所有发布操作均已调用 `create_publish_log`，无需新增。

### 2.3 响应字段说明

`TableauPublishLog.to_dict()` 返回字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 日志 ID |
| `connection_id` | int | 连接 ID |
| `object_type` | string | `datasource` / `field` |
| `object_id` | int | 数据源语义 ID 或字段语义 ID |
| `tableau_object_id` | string | Tableau 侧对象 ID |
| `target_system` | string | 固定为 `tableau` |
| `publish_payload_json` | string | 发布内容 JSON |
| `diff_json` | string | 差异对比 JSON |
| `status` | string | `pending` / `success` / `failed` / `rolled_back` |
| `response_summary` | string | 发布结果摘要 |
| `operator` | int | 操作人用户 ID |
| `created_at` | string | 创建时间 |

---

## 三、前端方案

### 3.1 路由配置

**路由路径**：`/semantic-maintenance/publish-logs`

`frontend/src/router/config.tsx` 新增：

```tsx
import SemanticPublishLogsPage from "../pages/semantic-maintenance/publish-logs/page";

{
  path: "/semantic-maintenance/publish-logs",
  element: (
    <ProtectedRoute requiredPermission="tableau">
      <AdminLayout><SemanticPublishLogsPage /></AdminLayout>
    </ProtectedRoute>
  ),
},
```

### 3.2 API 模块

**文件**：`frontend/src/api/semantic-maintenance.ts` 追加

```ts
// 追加到 semantic-maintenance.ts

export interface PublishLog {
  id: number;
  connection_id: number;
  object_type: 'datasource' | 'field';
  object_id: number;
  tableau_object_id: string | null;
  target_system: string;
  publish_payload_json: string | null;
  diff_json: string | null;
  status: 'pending' | 'success' | 'failed' | 'rolled_back';
  response_summary: string | null;
  operator: number | null;
  created_at: string;
}

export interface PublishLogsResponse {
  items: PublishLog[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export async function listPublishLogs(params: {
  connection_id: number;
  object_type?: 'datasource' | 'field';
  status?: 'pending' | 'success' | 'failed' | 'rolled_back';
  page?: number;
  page_size?: number;
}): Promise<PublishLogsResponse> {
  const sp = new URLSearchParams({
    connection_id: String(params.connection_id),
    ...(params.object_type && { object_type: params.object_type }),
    ...(params.status && { status: params.status }),
    ...(params.page && { page: String(params.page) }),
    ...(params.page_size && { page_size: String(params.page_size) }),
  });
  const res = await fetch(`${API_BASE}/api/semantic-maintenance/publish/logs?${sp}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('获取发布日志失败');
  return res.json();
}
```

### 3.3 页面组件

**文件**：`frontend/src/pages/semantic-maintenance/publish-logs/page.tsx`

**页面布局**：

```
语义发布记录
├── 连接选择器（下拉，选中的连接决定日志范围）
├── 筛选栏
│     ├── 对象类型：全部 / 数据源 / 字段
│     └── 状态：全部 / 成功 / 失败 / 回滚
├── 统计卡片（总发布次数 / 成功次数 / 失败次数）
└── 日志列表（Table）
      ├── 时间
      ├── 操作类型（发布 / 重试 / 回滚）
      ├── 对象类型（数据源 / 字段）
      ├── 对象名称
      ├── 状态（badge）
      ├── 操作人
      └── 操作（查看 Diff / 查看详情）
```

### 3.4 组件状态设计

```tsx
const [logs, setLogs] = useState<PublishLog[]>([]);
const [loading, setLoading] = useState(false);
const [total, setTotal] = useState(0);
const [filters, setFilters] = useState({
  object_type: '' as '' | 'datasource' | 'field',
  status: '' as '' | 'pending' | 'success' | 'failed' | 'rolled_back',
});
const [selectedConnId, setSelectedConnId] = useState<number | null>(null);
```

### 3.5 Diff 弹窗

点击"查看 Diff"时，调用 `GET /api/semantic-maintenance/publish/diff` 预览发布差异：

```tsx
// Diff 弹窗
<DiffModal
  visible={diffModalVisible}
  connectionId={selectedConnId}
  objectType={log.object_type}
  objectId={log.object_id}
  onClose={() => setDiffModalVisible(false)}
/>
```

`diff_json` 字段结构示例：

```json
{
  "changes": [
    {
      "field": "semantic_name_zh",
      "before": "销售额",
      "after": "含税销售额"
    }
  ]
}
```

### 3.6 状态 Badge 样式

| status | 颜色 | 样式 |
|--------|------|------|
| `pending` | 蓝 | `bg-blue-50 text-blue-600` |
| `success` | 绿 | `bg-emerald-50 text-emerald-600` |
| `failed` | 红 | `bg-red-50 text-red-600` |
| `rolled_back` | 灰 | `bg-slate-100 text-slate-500` |

### 3.7 与现有菜单的关系

根据 PRD 菜单结构，语义发布记录归属 `BI语义 → 语义发布记录`。

当前菜单中**没有这个入口**，需要新增。AdminLayout 的 sidebar 应新增入口：

```tsx
// AdminLayout.tsx 的 adminMenuItems 追加
{
  path: '/semantic-maintenance/publish-logs',
  label: '发布记录',
  icon: 'ri-file-history-line',
},
```

---

## 四、路由注册

### 4.1 后端

无需修改 `main.py`（接口加在已有 `semantic_maintenance` router 下）。

### 4.2 前端路由

`frontend/src/router/config.tsx` 新增路由。

---

## 五、已确认事项

1. **对象名称显示**：不显示，列表中仅展示 ID
2. **操作人显示**：直接显示 `operator`（用户 ID），不 JOIN 用户表
3. **Diff 存储**：已确认 `publish_service.py` 中 `diff_json` 在以下场景均正确写入：
   - `publish_datasource`（L293）
   - `_publish_single_field`（L392）
   - `rollback_publish`（L480）

   Diff 结构：
   - 发布：`{ field: { tableau: value, mulan: value } }`
   - 回滚：`{ rollback: { field: value } }`

   前端只需 `JSON.parse(log.diff_json)` 渲染即可。
