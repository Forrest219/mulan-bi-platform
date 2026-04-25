import { test, expect } from '@playwright/test';

/**
 * 冒烟测试：Tableau 资产 → MCP 调试器 → 概览渲染
 *
 * 覆盖三种资产类型：
 *   - 数据源  → get-datasource-metadata（专属概览渲染器）
 *   - 视图    → get-view-data（通用渲染器）
 *   - 仪表板  → get-view-data + list-views（父工作簿 LUID）
 *
 * 全程使用 mock 数据，不依赖真实 Tableau 后端。
 */

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

// ── Mock 数据 ──────────────────────────────────────────────────────────────

const MOCK_DS_LUID = '07e71946-a34d-485d-a266-ec4d06e5524c';
const MOCK_VIEW_LUID = 'aabb1122-3344-5566-7788-99aabbccddee';
const MOCK_DASHBOARD_LUID = 'dd001122-3344-5566-7788-99aabbccddee';
const MOCK_WORKBOOK_LUID = '2e1b3c25-3164-4bcb-9dc3-6db186635dea';

const MOCK_CONNECTION = {
  id: 1, name: 'test_conn', server_url: 'https://tableau.test',
  is_active: true, last_test_success: true, connection_type: 'mcp',
};

const MOCK_DATASOURCE_ASSET = {
  id: 142, name: '月度指标汇总表', asset_type: 'datasource',
  tableau_id: MOCK_DS_LUID, project_name: '数据源',
  owner_name: 'test@example.com', view_count: 5, field_count: 24,
  health_score: null, tags: [], datasources: [],
  content_url: 'bidm_ai_metric_summary_mth-',
  server_url: 'https://prod-apsoutheast-b.online.tableau.com',
  parent_workbook_id: null, parent_workbook_name: null,
};

const MOCK_VIEW_ASSET = {
  id: 200, name: '销售趋势图', asset_type: 'view',
  tableau_id: MOCK_VIEW_LUID, project_name: '财务',
  owner_name: 'analyst@example.com', view_count: 120, field_count: null,
  health_score: 85, tags: [], datasources: [],
  content_url: 'SalesWorkbook/SalesTrend',
  server_url: 'https://prod-apsoutheast-b.online.tableau.com',
  parent_workbook_id: MOCK_WORKBOOK_LUID, parent_workbook_name: '销售分析工作簿',
};

const MOCK_DASHBOARD_ASSET = {
  id: 300, name: '经营总览仪表板', asset_type: 'dashboard',
  tableau_id: MOCK_DASHBOARD_LUID, project_name: '管理层',
  owner_name: 'manager@example.com', view_count: 88, field_count: null,
  health_score: 72, tags: [], datasources: [],
  content_url: 'BizWorkbook/BizDashboard',
  server_url: 'https://prod-apsoutheast-b.online.tableau.com',
  parent_workbook_id: MOCK_WORKBOOK_LUID, parent_workbook_name: '经营分析工作簿',
};

const MOCK_PARENT_WORKBOOK = {
  id: 100, name: '销售分析工作簿', asset_type: 'workbook',
  tableau_id: MOCK_WORKBOOK_LUID, project_name: '财务',
  owner_name: 'admin@example.com', view_count: null, field_count: null,
  health_score: null, tags: [], datasources: [],
  content_url: 'SalesWorkbook', server_url: 'https://prod-apsoutheast-b.online.tableau.com',
  parent_workbook_id: null, parent_workbook_name: null,
};

const MOCK_MCP_CONFIGS = [
  { id: 5, name: 'Tableau MCP', type: 'tableau', is_active: true },
];

const MOCK_MCP_TOOLS = {
  jsonrpc: '2.0', id: 1,
  result: {
    tools: [
      {
        name: 'get-datasource-metadata',
        description: '获取指定 Tableau 数据源的详情',
        inputSchema: {
          type: 'object',
          properties: { datasource_luid: { type: 'string', description: '数据源的 LUID（唯一标识）' } },
          required: ['datasource_luid'],
        },
      },
      {
        name: 'get-view-data',
        description: '获取视图数据',
        inputSchema: {
          type: 'object',
          properties: { view_id: { type: 'string', description: '视图的 LUID' } },
          required: ['view_id'],
        },
      },
      {
        name: 'list-views',
        description: '列出工作簿下的视图',
        inputSchema: {
          type: 'object',
          properties: {
            workbook_id: { type: 'string', description: '按工作簿 LUID 过滤' },
            limit: { type: 'integer', description: '最多返回条数', default: 100 },
          },
          required: [],
        },
      },
    ],
  },
};

function makeDatasourceCallResponse() {
  return {
    tool_name: 'get-datasource-metadata',
    result: {
      jsonrpc: '2.0', id: 1,
      result: {
        content: [{
          type: 'text',
          text: JSON.stringify({
            datasource: {
              id: MOCK_DS_LUID, name: '月度指标汇总表', type: 'mysql',
              createdAt: '2026-03-25T10:31:13Z', updatedAt: '2026-03-25T10:31:13Z',
              project: { id: 'proj-001', name: '数据源' },
              owner: { id: 'owner-001', name: 'test@example.com' },
              fields: [
                { name: '净额', description: null },
                { name: '品类名称', description: null },
                { name: '区域名称', description: '业务区域' },
              ],
            },
          }),
        }],
      },
    },
    status: 'success', duration_ms: 1200, log_id: 99,
  };
}

function makeViewDataCallResponse() {
  return {
    tool_name: 'get-view-data',
    result: {
      jsonrpc: '2.0', id: 1,
      result: {
        content: [{
          type: 'text',
          text: JSON.stringify({
            columns: ['区域', '销售额', '利润'],
            rows: [
              { '区域': '华东', '销售额': 128000, '利润': 32000 },
              { '区域': '华南', '销售额': 96000, '利润': 21000 },
            ],
          }),
        }],
      },
    },
    status: 'success', duration_ms: 800, log_id: 100,
  };
}

// ── 公共 helpers ────────────────────────────────────────────────────────────

/** 注册资产详情页所有公共 mock */
async function mockAssetDetailApis(page: import('@playwright/test').Page, asset: Record<string, unknown>, parent: Record<string, unknown> | null) {
  await page.route(`**/api/tableau/assets/${asset.id}`, route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(asset) })
  );
  await page.route(`**/api/tableau/assets/${asset.id}/parent`, route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ parent }) })
  );
  await page.route(`**/api/tableau/assets/${asset.id}/children`, route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ children: [] }) })
  );
  await page.route('**/api/llm/configs**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configs: [] }) })
  );
}

/** 注册 MCP 调试器所有公共 mock */
async function mockMcpDebuggerApis(page: import('@playwright/test').Page) {
  await page.route('**/api/mcp-configs/', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_MCP_CONFIGS) })
  );
  await page.route('**/tableau-mcp**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_MCP_TOOLS) })
  );
}

// ── 测试 ────────────────────────────────────────────────────────────────────

test.describe('Tableau 资产 → MCP 调试器', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 数据源 ──────────────────────────────────────────────────────────────

  test('数据源：详情 → 调试 get-datasource-metadata → 概览渲染字段列表', async ({ page }) => {
    await mockAssetDetailApis(page, MOCK_DATASOURCE_ASSET, null);
    await page.goto(`/assets/tableau/${MOCK_DATASOURCE_ASSET.id}`);
    await expect(page.locator('h1').filter({ hasText: '月度指标汇总表' })).toBeVisible({ timeout: 5000 });

    // MCP 调试按钮正确显示 get-datasource-metadata
    const mcpBtn = page.locator('button', { hasText: '调试 get-datasource-metadata' });
    await expect(mcpBtn).toBeVisible({ timeout: 3000 });

    // 跳转 MCP 调试器
    await mockMcpDebuggerApis(page);
    await mcpBtn.click();
    await expect(page).toHaveURL(/tool=get-datasource-metadata/, { timeout: 5000 });
    await expect(page).toHaveURL(new RegExp(`arg_datasource_luid=${MOCK_DS_LUID}`));

    // 参数自动填充
    await expect(
      page.locator('div.font-medium').filter({ hasText: 'get-datasource-metadata' }).first()
    ).toBeVisible({ timeout: 8000 });
    const luidInput = page.locator('input[type="text"]').first();
    await expect(luidInput).toHaveValue(MOCK_DS_LUID, { timeout: 3000 });

    // 执行
    await page.route('**/api/mcp-debug/call', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(makeDatasourceCallResponse()) })
    );
    await page.locator('button[type="submit"]').click();
    await expect(page.locator('text=成功').first()).toBeVisible({ timeout: 8000 });

    // 概览：专属渲染器
    await expect(page.locator('text=数据源信息')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('text=月度指标汇总表').first()).toBeVisible();
    await expect(page.locator(`text=${MOCK_DS_LUID}`).first()).toBeVisible();
    await expect(page.locator('text=mysql').first()).toBeVisible();
    await expect(page.locator('text=test@example.com').first()).toBeVisible();
    await expect(page.locator('text=字段列表')).toBeVisible();
    await expect(page.locator('td').filter({ hasText: '净额' })).toBeVisible();
    await expect(page.locator('td').filter({ hasText: '区域名称' })).toBeVisible();
    await expect(page.locator('td').filter({ hasText: '业务区域' })).toBeVisible();
  });

  // ── 视图 ────────────────────────────────────────────────────────────────

  test('视图：详情 → 调试 get-view-data → 参数填充 view_id → 概览渲染数据行', async ({ page }) => {
    await mockAssetDetailApis(page, MOCK_VIEW_ASSET, MOCK_PARENT_WORKBOOK);
    await page.goto(`/assets/tableau/${MOCK_VIEW_ASSET.id}`);
    await expect(page.locator('h1').filter({ hasText: '销售趋势图' })).toBeVisible({ timeout: 5000 });

    // 视图应显示 get-view-data 按钮
    const viewDataBtn = page.locator('button', { hasText: '调试 get-view-data' });
    await expect(viewDataBtn).toBeVisible({ timeout: 3000 });

    // 有父工作簿时，list-views 按钮也应存在
    await expect(page.locator('button', { hasText: '调试 list-views' })).toBeVisible();

    // 跳转 MCP 调试器（get-view-data）
    await mockMcpDebuggerApis(page);
    await viewDataBtn.click();
    await expect(page).toHaveURL(/tool=get-view-data/, { timeout: 5000 });
    await expect(page).toHaveURL(new RegExp(`arg_view_id=${MOCK_VIEW_LUID}`));

    // 参数自动填充
    await expect(
      page.locator('div.font-medium').filter({ hasText: 'get-view-data' }).first()
    ).toBeVisible({ timeout: 8000 });
    const viewIdInput = page.locator('input[type="text"]').first();
    await expect(viewIdInput).toHaveValue(MOCK_VIEW_LUID, { timeout: 3000 });

    // 执行
    await page.route('**/api/mcp-debug/call', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(makeViewDataCallResponse()) })
    );
    await page.locator('button[type="submit"]').click();
    await expect(page.locator('text=成功').first()).toBeVisible({ timeout: 8000 });

    // 概览：通用渲染器应显示 mock 数据行
    await expect(page.locator('text=华东').first()).toBeVisible({ timeout: 3000 });
    await expect(page.locator('text=华南').first()).toBeVisible();
  });

  // ── 仪表板 ──────────────────────────────────────────────────────────────

  test('仪表板：详情 → 调试 get-view-data → 参数填充 view_id + list-views 传父工作簿 LUID', async ({ page }) => {
    await mockAssetDetailApis(page, MOCK_DASHBOARD_ASSET, MOCK_PARENT_WORKBOOK);
    await page.goto(`/assets/tableau/${MOCK_DASHBOARD_ASSET.id}`);
    await expect(page.locator('h1').filter({ hasText: '经营总览仪表板' })).toBeVisible({ timeout: 5000 });

    // 仪表板应显示 get-view-data 按钮
    const viewDataBtn = page.locator('button', { hasText: '调试 get-view-data' });
    await expect(viewDataBtn).toBeVisible({ timeout: 3000 });

    // list-views 按钮存在（因为有父工作簿）
    const listViewsBtn = page.locator('button', { hasText: '调试 list-views' });
    await expect(listViewsBtn).toBeVisible();

    // 验证 get-view-data 跳转传视图自身 LUID
    await mockMcpDebuggerApis(page);
    await viewDataBtn.click();
    await expect(page).toHaveURL(/tool=get-view-data/, { timeout: 5000 });
    await expect(page).toHaveURL(new RegExp(`arg_view_id=${MOCK_DASHBOARD_LUID}`));

    // 返回资产详情
    await page.goBack();
    await expect(page.locator('h1').filter({ hasText: '经营总览仪表板' })).toBeVisible({ timeout: 5000 });

    // 验证 list-views 跳转传父工作簿 LUID（不是仪表板自身 LUID）
    await listViewsBtn.click();
    await expect(page).toHaveURL(/tool=list-views/, { timeout: 5000 });
    await expect(page).toHaveURL(new RegExp(`arg_workbook_id=${MOCK_WORKBOOK_LUID}`));
    // 绝不应该包含仪表板自身 LUID
    const url = page.url();
    expect(url).not.toContain(MOCK_DASHBOARD_LUID);
  });
});
