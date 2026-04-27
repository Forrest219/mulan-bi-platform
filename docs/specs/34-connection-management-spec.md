# Spec 34：连接管理模块整合

- **状态**：待实施
- **创建**：2026-04-24
- **执行者**：coder
- **背景**：审计发现三套连接系统（bi_data_sources、tableau_connections、mcp_servers）各自独立，Connection Center 仅为只读看板，两个完整 CRUD 页面（数据源管理、Tableau 连接）被路由绕过成了死代码，冒烟测试大量空壳

---

## 非目标

- 不合并三张数据库表（保持独立，通过 UI 层整合体验）
- 不重写 Connection Center（保留为只读总览仪表盘）
- 不修改后端 API 契约（已有 CRUD 端点不变）
- 不实现 Spec 24 的 connection-hub 统一 API（P2 排期）

---

## 一、问题清单

| # | 问题 | 严重度 | 修复方式 |
|---|------|--------|---------|
| 1 | `pages/admin/datasources/page.tsx` 已实现 CRUD 但未注册路由，成死代码 | P0 | 恢复路由 |
| 2 | `pages/tableau/connections/page.tsx` 已实现 CRUD 但未注册路由，成死代码 | P0 | 恢复路由 |
| 3 | Connection Center 无增删改能力，"连接管理"名不副实 | P0 | 改为"连接总览" + 加跳转按钮 |
| 4 | Connection Center 大量英文占位文案 | P1 | 汉化 |
| 5 | `src/api/tableau.ts` 16 处英文错误消息 | P1 | 汉化 |
| 6 | Sync Logs 返回按钮导航到 404 | P1 | 修正路径 |
| 7 | Tableau 连接页 sync-logs 链接路径错误 | P1 | 修正路径 |
| 8 | 冒烟测试 `datasource-connections.spec.ts` 断言被 catch 吞掉 | P1 | 重写 |
| 9 | 冒烟测试 `tableau-connections.spec.ts` 查找不存在的英文文案 | P1 | 重写 |
| 10 | `mcp-config-add-tableau-real.spec.ts` 硬编码 PAT token | P0 安全 | 改环境变量 |
| 11 | Tableau 连接页用 `catch (e: any)` | P2 | 改 `(e: unknown)` |

---

## 二、菜单结构

### 修改前

```
资产
├── Tableau 资产         /assets/tableau
├── Tableau 健康         /assets/tableau-health
└── 连接管理             /assets/connection-center   ← 只读
```

### 修改后

```
资产
├── Tableau 资产         /assets/tableau
├── Tableau 健康         /assets/tableau-health
├── 连接总览             /assets/connection-center   ← 只读仪表盘
├── 数据源管理           /assets/datasources         ← CRUD（恢复）
└── Tableau 连接         /assets/tableau-connections  ← CRUD（恢复）
```

> MCP 配置保持在"设置"域下，不动。

### 实现文件

- **菜单配置**：`frontend/src/config/menu.ts` — `menuConfig` 数组，`MenuDomain > MenuItem` 两级结构
- **侧边栏组件**：`frontend/src/components/layout/AppSidebar.tsx` — 消费 `menuConfig`，通过 `isItemVisible()` 过滤权限
- 数据源管理、Tableau 连接菜单项已存在于 `menuConfig` 中，无需新增

### 权限规则

| 路由 | 菜单权限 | 路由权限（`router/config.tsx`） |
|------|---------|------|
| `/assets/datasources` | `requiredRole: 'data_admin'` | `<ProtectedRoute requiredPermission="database_monitor">` |
| `/assets/tableau-connections` | `requiredPermission: 'tableau'` | `<ProtectedRoute requiredPermission="tableau">` |
| `/assets/tableau-connections/:connId/sync-logs` | 继承父级 | `<ProtectedRoute requiredPermission="tableau">` |

---

## 三、路由变更

### `frontend/src/router/config.tsx`

**恢复路由**（去掉 redirect，改为加载真实页面组件）：

```tsx
// 示例：恢复 datasources 路由
// ❌ 当前（redirect）：
{
  path: 'datasources',
  element: <Navigate to="/assets/connection-center?type=db" replace />,
}

// ✅ 修改后（加载真实页面）：
{
  path: 'datasources',
  element: (
    <ProtectedRoute requiredPermission="database_monitor">
      <DatasourcesPage />
    </ProtectedRoute>
  ),
}
```

同理恢复 `tableau-connections` 路由。

**新增 lazy import**：

```tsx
const DatasourcesPage = lazy(() => import('../pages/admin/datasources/page'));
const TableauConnectionsPage = lazy(() => import('../pages/tableau/connections/page'));
```

---

## 四、Connection Center 汉化

### `pages/assets/connection-center/page.tsx` 汉化清单

| 行号(约) | 当前文案 | 改为 |
|----------|---------|------|
| 标题 | 连接管理 | **连接总览** |
| 副标题 | 统一管理数据库与 Tableau 连接 | 查看所有数据库与 Tableau 连接状态 |
| 264 | `"Open Logs"` | `"查看日志"` |
| 273 | `"No records found"` | `"暂无记录"` |
| 254 | status 显示 `healthy`/`warning`/`failed` | `正常`/`警告`/`失败` |
| 290 | `"Connection Detail"` | `"连接详情"` |
| 296-301 | `Name:`/`Type:`/`Endpoint:`/`Owner:`/`Status:`/`Updated:` | `名称：`/`类型：`/`地址：`/`负责人：`/`状态：`/`更新时间：` |
| 302 | `"Detail drawer placeholder (option C shell)."` | **删除此行** |

### 新增"管理"跳转按钮

在数据库 tab 和 Tableau tab 的表格上方各加一个按钮：

```tsx
// 示例（DB tab）：
<Link
  to="/assets/datasources"
  className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50"
>
  管理数据源
</Link>

// 示例（Tableau tab）：
<Link
  to="/assets/tableau-connections"
  className="px-3 py-1.5 text-sm border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50"
>
  管理 Tableau 连接
</Link>
```

按钮位置：放在搜索栏右侧，与状态筛选并排。

---

## 五、导航修复

### 5.1 Sync Logs 返回按钮

**文件**：`pages/tableau/sync-logs/page.tsx`

```tsx
// ❌ 当前：
navigate('/tableau/connections')  // 404

// ✅ 修改后：
navigate('/assets/tableau-connections')
```

### 5.2 Tableau 连接页 sync-logs 链接

**文件**：`pages/tableau/connections/page.tsx`

```tsx
// ❌ 当前：
navigate(`/tableau/connections/${conn.id}/sync-logs`)  // 404

// ✅ 修改后：
navigate(`/assets/tableau-connections/${conn.id}/sync-logs`)
```

---

## 六、`src/api/tableau.ts` 错误消息汉化

所有 `throw new Error('Failed to ...')` 改为中文。对照表：

| 当前 | 改为 |
|------|------|
| `'Failed to fetch connections'` | `'获取连接列表失败'` |
| `'Failed to create connection'` | `'创建连接失败'` |
| `'Failed to update connection'` | `'更新连接失败'` |
| `'Failed to delete connection'` | `'删除连接失败'` |
| `'Failed to test connection'` | `'测试连接失败'` |
| `'Failed to sync connection'` | `'同步连接失败'` |
| `'Failed to fetch assets'` | `'获取资产列表失败'` |
| `'Failed to fetch asset'` | `'获取资产详情失败'` |
| `'Failed to search assets'` | `'搜索资产失败'` |
| `'Failed to fetch projects'` | `'获取项目列表失败'` |
| `'Failed to fetch sync logs'` | `'获取同步日志失败'` |
| `'Failed to fetch sync log'` | `'获取同步日志详情失败'` |
| `'Failed to fetch sync status'` | `'获取同步状态失败'` |
| `'Failed to fetch children'` | `'获取子资产失败'` |
| `'Failed to fetch parent'` | `'获取父资产失败'` |
| `'Failed to explain asset'` | `'资产解读失败'` |
| `'Failed to fetch health'` | `'获取健康评分失败'` |
| `'Failed to fetch health overview'` | `'获取健康概览失败'` |

> **约束**：只改错误消息字符串，不改函数签名、参数、返回值类型。

---

## 七、代码质量修复

### `pages/tableau/connections/page.tsx`

4 处 `catch (e: any)` 改为 `catch (e: unknown)`，取错误消息用 `e instanceof Error ? e.message : String(e)`。

**示例**：

```tsx
// ❌ 当前：
} catch (e: any) {
  setError(e.message || '操作失败');
}

// ✅ 修改后：
} catch (e: unknown) {
  setError(e instanceof Error ? e.message : '操作失败');
}
```

---

## 八、冒烟测试用例

### 8.1 `datasource-connections.spec.ts` — 重写

```typescript
test.describe('数据源管理', () => {
  // beforeEach: 登录 admin

  test('数据源管理页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/datasources');
    // 必须断言：页面 h1 包含"数据源"
    await expect(page.locator('h1')).toContainText('数据源');
    // 必须断言：不是 404 页面
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有"新建"按钮', async ({ page }) => {
    await page.goto('/assets/datasources');
    // 必须断言：按钮可见（用中文文案匹配）
    const addBtn = page.locator('button').filter({ hasText: /新增|添加|创建/ });
    await expect(addBtn.first()).toBeVisible({ timeout: 5000 });
  });

  test('空状态显示提示文案', async ({ page }) => {
    await page.goto('/assets/datasources');
    // 断言之一必须通过：表格或空状态提示
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无').isVisible().catch(() => false);
    expect(hasTable || hasEmpty).toBe(true);
  });
});
```

> **约束**：
> - 禁止用 `.catch(() => {})` 吞掉断言失败
> - 所有 `expect` 必须是硬断言，失败则测试失败
> - 文案匹配用中文，不用英文

### 8.2 `tableau-connections.spec.ts` — 重写

```typescript
test.describe('Tableau 连接管理', () => {
  // beforeEach: 登录 admin

  test('Tableau 连接页可访问且显示中文标题', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    await expect(page.locator('h1')).toContainText('Tableau');
    await expect(page.locator('text=Page Not Found')).toHaveCount(0);
  });

  test('页面有"新建"按钮', async ({ page }) => {
    await page.goto('/assets/tableau-connections');
    const addBtn = page.locator('button').filter({ hasText: /新增|添加|创建/ });
    await expect(addBtn.first()).toBeVisible({ timeout: 5000 });
  });

  test('已有连接显示在列表中', async ({ page }) => {
    // Mock API 返回一条连接
    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          connections: [{
            id: 1, name: 'Test Tableau', server_url: 'https://example.com',
            site: 'test', connection_type: 'mcp', is_active: true,
            sync_status: 'idle', created_at: '2026-04-24', updated_at: '2026-04-24'
          }],
          total: 1
        }),
      });
    });
    await page.goto('/assets/tableau-connections');
    // mock 数据必须渲染到 DOM
    await expect(page.locator('text=Test Tableau')).toBeVisible({ timeout: 5000 });
  });
});
```

> **约束**：
> - mock 数据中的 `name` 值必须在 DOM 断言中精确匹配
> - 禁止只断言"页面没报错"——必须断言具体内容

### 8.3 `connection-center.spec.ts` — 新增

```typescript
test.describe('连接总览', () => {
  // beforeEach: 登录 admin

  test('连接总览页可访问', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await expect(page.locator('h1')).toContainText('连接总览');
  });

  test('KPI 卡片显示中文标签', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await expect(page.locator('text=总计')).toBeVisible();
    await expect(page.locator('text=正常')).toBeVisible();
    await expect(page.locator('text=警告')).toBeVisible();
    await expect(page.locator('text=失败')).toBeVisible();
  });

  test('Tab 标签为中文', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await expect(page.locator('button', { hasText: '总览' })).toBeVisible();
    await expect(page.locator('button', { hasText: '数据库' })).toBeVisible();
    await expect(page.locator('button', { hasText: 'Tableau' })).toBeVisible();
  });

  test('DB tab 有"管理数据源"跳转按钮', async ({ page }) => {
    await page.goto('/assets/connection-center?type=db');
    const manageBtn = page.locator('a[href="/assets/datasources"]');
    await expect(manageBtn).toBeVisible({ timeout: 3000 });
  });

  test('Tableau tab 有"管理 Tableau 连接"跳转按钮', async ({ page }) => {
    await page.goto('/assets/connection-center?type=tableau');
    const manageBtn = page.locator('a[href="/assets/tableau-connections"]');
    await expect(manageBtn).toBeVisible({ timeout: 3000 });
  });

  test('页面无英文占位文案残留', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await page.waitForTimeout(1000);
    const body = await page.locator('body').textContent();
    // 不允许出现已知的英文占位符
    expect(body).not.toContain('Import Placeholder');
    expect(body).not.toContain('New Connection (CTA)');
    expect(body).not.toContain('Owner placeholder');
    expect(body).not.toContain('option C shell');
  });
});
```

### 8.4 `mcp-config-toggle.spec.ts` — 补充断言

```typescript
// 示例：toggle 后必须验证状态变化
await toggleBtn.click();
await page.waitForTimeout(500);
// 必须断言：按钮文案或颜色发生了变化
const newText = await toggleBtn.textContent();
expect(newText).not.toBe(originalText);
```

### 8.5 `mcp-config-add-tableau-real.spec.ts` — 安全修复

```typescript
// ❌ 当前（硬编码 PAT token）：
const PAT_VALUE = 'UaN/B5UUSF+dw/+WGwrD6w==:LrWI0YnhZfFavND6rEcPi...';

// ✅ 修改后（环境变量）：
const PAT_VALUE = process.env.TABLEAU_PAT_VALUE ?? '';
test.skip(!PAT_VALUE, 'TABLEAU_PAT_VALUE 环境变量未设置，跳过真实连接测试');
```

---

## 九、验收标准

| # | 验收项 | 验证方法 |
|---|--------|---------|
| 1 | 侧栏菜单显示：连接总览、数据源管理、Tableau 连接（3 项独立） | 目视 |
| 2 | 数据源管理页能增删改测试 | 手动操作 |
| 3 | Tableau 连接页能增删改测试同步 | 手动操作 |
| 4 | 连接总览页全中文，无英文占位 | 冒烟测试 |
| 5 | 连接总览 DB/Tableau tab 各有"管理"跳转按钮 | 冒烟测试 |
| 6 | Sync Logs 返回按钮不 404 | 手动点击 |
| 7 | `npx tsc --noEmit` 零错误 | CI |
| 8 | 全量冒烟测试通过 | `npx playwright test tests/smoke/ --reporter=list` |
| 9 | 无硬编码 PAT token 在测试文件中 | `grep -r "UaN/B5UUSF" tests/` 无结果 |
