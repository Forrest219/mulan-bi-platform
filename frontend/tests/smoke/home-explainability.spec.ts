import { expect, test } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

async function loginAndGoHome(page: import('@playwright/test').Page) {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 8000 });
  await page.locator('textarea[data-askbar-input]').waitFor({ state: 'visible', timeout: 5000 });
}

function sse(events: Array<Record<string, unknown>>) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

test.describe('首页 Explainability UI', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndGoHome(page);
  });

  test('实时回答展示可折叠分析过程五段信息', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: sse([
          { type: 'metadata', conversation_id: 'conv-exp-001', run_id: 'run-exp-001', trace_id: 'trace-exp-001', mode: 'agent_only', contract_version: 'agent-stream.p0.1' },
          {
            type: 'explainability',
            phase: 'intent',
            status: 'completed',
            payload: {
              intent: 'analysis',
              confidence: 0.93,
              strategy: 'router_guardrail',
              guardrail: { decision: 'allow', reason_code: 'DATA_QUESTION', message: '识别为分析类问数。' },
            },
          },
          {
            type: 'explainability',
            phase: 'plan',
            status: 'completed',
            payload: {
              plan_id: 'plan-exp-001',
              datasource: { connection_id: 1, name: 'Superstore', type: 'tableau' },
              semantic_operators: [{ id: 'op-1', op: 'aggregate', label: '按年份聚合', metrics: ['profit'], fields: ['year'] }],
              pushdown: { enabled: true, target: 'tableau_vizql', reason: '聚合可下推', filters: ['year >= 2021'], aggregations: ['SUM(profit)'] },
              query_plan_context: { grain: 'year', metrics: ['利润'], dimensions: ['年份'], filters: ['近几年'], limit: 100 },
            },
          },
          { type: 'tool_call', tool: 'query', params: { query_kind: 'aggregate' } },
          { type: 'tool_result', tool: 'query', summary: '返回 5 行聚合结果' },
          { type: 'table_data', fields: ['年份', '利润'], rows: [[2021, 100], [2022, 130]], col_types: ['numeric', 'numeric'] },
          {
            type: 'explainability',
            phase: 'postprocess',
            status: 'completed',
            payload: { response_type: 'table', row_count: 2, displayed_row_count: 2, chart_generated: false, formatting: ['table_data'] },
          },
          { type: 'token', content: '利润近几年整体上升。' },
          {
            type: 'done',
            answer: '利润近几年整体上升。',
            trace_id: 'trace-exp-001',
            run_id: 'run-exp-001',
            tools_used: ['query'],
            response_type: 'table',
            response_data: { fields: ['年份', '利润'], rows: [[2021, 100], [2022, 130]] },
            steps_count: 2,
            execution_time_ms: 250,
            sources_count: 1,
            top_sources: ['Superstore'],
            explainability: {
              schema_version: 'p0.1',
              run_id: 'run-exp-001',
              trace_id: 'trace-exp-001',
              mode: 'agent_only',
              phases: {
                intent: { intent: 'analysis', confidence: 0.93, strategy: 'router_guardrail', guardrail: { decision: 'allow' } },
                plan: { plan_id: 'plan-exp-001', datasource: { name: 'Superstore' }, semantic_operators: [], pushdown: { enabled: true, target: 'tableau_vizql' }, query_plan_context: { metrics: ['利润'], dimensions: ['年份'], limit: 100 } },
                execution: { status: 'completed', steps: [{ step_id: 's1', step_number: 1, phase: 'execution', status: 'success', title: '执行 query', tool_name: 'query', result_preview: '返回 5 行聚合结果' }] },
                postprocess: { response_type: 'table', row_count: 2, displayed_row_count: 2, formatting: ['table_data'] },
                fallback: { occurred: false, chain: [], final_source: 'agent' },
              },
            },
          },
        ]),
      });
    });

    await page.locator('textarea[data-askbar-input]').fill('利润过去几年的趋势是什么');
    await page.locator('button[aria-label="发送"]').click();

    await expect(page.getByText('利润近几年整体上升')).toBeVisible({ timeout: 5000 });
    await expect(page.getByTestId('analysis-process-block')).toBeVisible();
    await page.getByTestId('analysis-process-toggle').click();
    await expect(page.getByTestId('analysis-phase-intent')).toContainText('意图');
    await expect(page.getByTestId('analysis-phase-plan')).toContainText('下推到 tableau_vizql');
    await expect(page.getByTestId('analysis-phase-execution')).toContainText('执行 query');
    await expect(page.getByTestId('analysis-phase-postprocess')).toContainText('结果 2 行');
    await expect(page.getByTestId('analysis-phase-fallback')).toContainText('未发生降级');
  });

  test('fallback explainability 显示降级徽标且不混淆为普通成功', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: sse([
          { type: 'metadata', conversation_id: 'conv-fallback-001', run_id: 'run-fallback-001', trace_id: 'trace-fallback-001', mode: 'agent_with_fallback' },
          {
            type: 'explainability',
            phase: 'fallback',
            status: 'completed',
            payload: {
              occurred: true,
              chain: [{ from: 'fast_mcp', to: 'react_agent', reason_code: 'FAST_MCP_QUERY_BUILDER_MISS', message: '直连查询构造失败，转入受控 Agent。' }],
              final_source: 'agent',
              user_visible_message: '已切换到受控 Agent 路径。',
            },
          },
          { type: 'token', content: '已通过受控 Agent 返回结果。' },
          {
            type: 'done',
            answer: '已通过受控 Agent 返回结果。',
            trace_id: 'trace-fallback-001',
            run_id: 'run-fallback-001',
            tools_used: ['query'],
            response_type: 'text',
            response_data: null,
            steps_count: 1,
            execution_time_ms: 320,
            sources_count: 0,
            top_sources: [],
            explainability: {
              schema_version: 'p0.1',
              run_id: 'run-fallback-001',
              trace_id: 'trace-fallback-001',
              mode: 'agent_with_fallback',
              phases: {
                fallback: {
                  occurred: true,
                  chain: [{ from: 'fast_mcp', to: 'react_agent', reason_code: 'FAST_MCP_QUERY_BUILDER_MISS', message: '直连查询构造失败，转入受控 Agent。' }],
                  final_source: 'agent',
                },
              },
            },
          },
        ]),
      });
    });

    await page.locator('textarea[data-askbar-input]').fill('Top 10 大客户是谁');
    await page.keyboard.press('Enter');

    await expect(page.getByText('已通过受控 Agent 返回结果')).toBeVisible({ timeout: 5000 });
    await expect(page.getByTestId('analysis-fallback-badge')).toBeVisible();
    await page.getByTestId('analysis-process-toggle').click();
    await expect(page.getByTestId('analysis-phase-fallback')).toContainText('FAST_MCP_QUERY_BUILDER_MISS');
  });

  test('旧 SSE contract 不返回 explainability 时页面不报错', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: sse([
          { type: 'metadata', conversation_id: 'conv-legacy-001', run_id: 'run-legacy-001' },
          { type: 'tool_call', tool: 'query', params: { metric: 'sales' } },
          { type: 'tool_result', tool: 'query', summary: '返回 1 行' },
          { type: 'token', content: '销售额为 100。' },
          { type: 'done', answer: '销售额为 100。', trace_id: 'trace-legacy-001', run_id: 'run-legacy-001', tools_used: ['query'], response_type: 'text', response_data: null, steps_count: 2, execution_time_ms: 100, sources_count: 0, top_sources: [] },
        ]),
      });
    });

    await page.locator('textarea[data-askbar-input]').fill('销售额是多少');
    await page.keyboard.press('Enter');
    await expect(page.getByText('销售额为 100')).toBeVisible({ timeout: 5000 });
  });
});
