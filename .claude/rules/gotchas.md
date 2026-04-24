# 项目特有技术陷阱

遇到过的真实 Bug，改代码前必读。

## 陷阱 1：AuthContext useCallback 无限重渲染

**现象**：登录后页面持续发送 `/api/auth/me` 请求，CPU 飙升。

**根因**：将 token 过期时间存为 `useState`，导致 `checkAuth` 的 `useCallback` 依赖数组包含该 state，state 更新触发 `checkAuth` 重新创建，`useEffect` 重新触发，形成闭环。

**正确做法**：不需要触发重渲染的内部计时器值用 `useRef`，不要用 `useState`。

```ts
// ❌ 错误
const [tokenExpiresAt, setTokenExpiresAt] = useState<number | null>(null);

// ✅ 正确
const tokenExpiresAtRef = useRef<number | null>(null);
```

---

## 陷阱 2：React.lazy 不支持具名导出（named export）

**现象**：`lazy(() => import('./AssetInspector'))` 报错，组件 undefined。

**根因**：`React.lazy` 只接受 default export，具名导出需要手动转换。

**正确做法**：

```ts
// ❌ 错误
const AssetInspector = lazy(() => import('./AssetInspector'));

// ✅ 正确
const AssetInspector = lazy(() =>
  import('./AssetInspector').then(m => ({ default: m.AssetInspector }))
);
```

---

## 陷阱 3：react-router `<a href>` 触发全页刷新

**现象**：页面间跳转导致所有状态丢失，SPA 失效。

**根因**：在 React Router 应用中使用原生 `<a href>` 而非 `<Link to>`，会绕过客户端路由触发完整页面重载。

**正确做法**：项目内所有跳转一律使用 `<Link to>` 或 `useNavigate()`，只有外部链接使用 `<a href target="_blank">`。

---

## 陷阱 4：Alembic autogenerate 遗漏 `server_default`

**现象**：本地迁移成功，生产执行后新行的默认值为 NULL，导致应用报错。

**根因**：SQLAlchemy `Column(default=...)` 是 Python 层默认值，Alembic autogenerate 不会将其转换为数据库层 `server_default`，已有行不受影响，只有新行通过 Python 插入才有值。

**正确做法**：需要数据库级默认值时，明确写 `server_default`：

```python
# ❌ 只有 Python 插入时生效
is_active = Column(Boolean, default=True)

# ✅ 数据库层保证，迁移后存量行也有值
is_active = Column(Boolean, server_default=sa.true(), nullable=False)
```

---

## 陷阱 5：LLM 多配置 `purpose` 路由静默降级

**现象**：配置了专用 `embedding` 模型，但实际调用走了 `general` 模型，日志无报错。

**根因**：LLM 路由按 `purpose` 字段优先匹配，找不到时 fallback 到 `general`，整个过程静默进行，不抛出异常也不记录警告。

**正确做法**：任何 `purpose` 专用调用，若无匹配配置应显式抛错或告警，不允许静默 fallback 到 general——静默降级在生产中会导致向量维度不匹配等隐蔽故障。

---

## 陷阱 6：前端文案必须全中文，禁止英文占位

**现象**：页面上出现 "New Connection"、"Failed to fetch"、"No records found" 等英文文案，用户看不懂。

**根因**：开发时用英文占位或直接用英文错误消息，上线前忘记替换。尤其在以下场景高发：
- 按钮文案（"Submit"、"New Connection"）
- 空状态提示（"No data"、"No records found"）
- API 错误消息（`throw new Error('Failed to fetch')`）
- 表头（"Name"、"Status"、"Updated"）
- Tab 标签（"Overview"、"Database"）

**正确做法**：
- 所有用户可见文案一律用中文，包括按钮、提示、表头、错误消息、placeholder
- `src/api/*.ts` 中的 `throw new Error()` 消息用中文（如 `'获取连接列表失败'`）
- 冒烟测试中的文案断言也用中文匹配，防止回归
- 唯一允许英文的场景：技术标识符（如 "Tableau"、"StarRocks"）、代码级日志（`console.log`）
