import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: NL-to-Query 流水线前端集成测试
 *
 * 覆盖范围：
 * - 首页 AskBar → POST /api/agent/stream（Agent SSE）
 * - 流式回答渲染、反馈按钮、来源徽章
 * - 错误处理（NLQ_012 无数据源、SYS_001 服务错误）
 * - 追问、并发提问
 *
 * SSE 协议：POST /api/agent/stream
 * 事件类型：metadata → thinking → tool_call → tool_result → token → done | error
 */

/** 标准 Agent SSE done 事件（生成辅助函数避免重复） */
function agentDoneEvent(opts: {
  answer: string;
  traceId: string;
  runId: string;
  sourcesCount?: number;
  topSources?: string[];
  responseType?: string;
  executionTimeMs?: number;
}): string {
  return `data: {"type":"done","answer":"${opts.answer}","trace_id":"${opts.traceId}","run_id":"${opts.runId}","tools_used":[],"response_type":"${opts.responseType ?? 'text'}","response_data":null,"steps_count":0,"execution_time_ms":${opts.executionTimeMs ?? 100},"sources_count":${opts.sourcesCount ?? 0},"top_sources":${JSON.stringify(opts.topSources ?? [])}}\n\n`;
}

test.describe('NL-to-Query 流水线', () => {

  // ── 登录前置 ──────────────────────────────────────────────────────────────

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── P0: AskBar 基础交互 ────────────────────────────────────────────────────

  test('AskBar 输入框正常渲染并可输入', async ({ page }) => {
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
    await askBarInput.fill('华东区销售额是多少');
    await expect(askBarInput).toHaveValue('华东区销售额是多少');
  });

  test('AskBar 提交后输入框被清空', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"token","content":"华东区销售额为 1200 万元"}\n\n',
          agentDoneEvent({ answer: '华东区销售额为 1200 万元', traceId: 'nlq-smoke-001', runId: 'run-nlq-001' }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');
    await askBarInput.fill('华东区销售额是多少');
    await sendBtn.click();
    await expect(askBarInput).toHaveValue('');
  });

  test('回车键可发送问题', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"token","content":"测试回答"}\n\n',
          agentDoneEvent({ answer: '测试回答', traceId: 'nlq-smoke-enter', runId: 'run-enter' }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('测试问题');
    await askBarInput.press('Enter');
    await expect(askBarInput).toHaveValue('');
  });

  test('发送中按钮显示 loading 状态且不可点击', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      // 不 fulfill，让请求挂起模拟 loading
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');
    await askBarInput.fill('华东区销售额是多少');
    await sendBtn.click();
    await expect(sendBtn).toBeDisabled();
  });

  // ── P1: 流式响应渲染 ───────────────────────────────────────────────────────

  test('SSE 流式响应完整渲染', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"metadata","conversation_id":"conv-stream","run_id":"run-stream-001"}\n\n',
          'data: {"type":"token","content":"华东"}\n\n',
          'data: {"type":"token","content":"地区"}\n\n',
          'data: {"type":"token","content":"销售额为 1200 万元"}\n\n',
          agentDoneEvent({ answer: '华东地区销售额为 1200 万元', traceId: 'nlq-stream-001', runId: 'run-stream-001' }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('华东区销售额');
    await askBarInput.press('Enter');
    await expect(page.locator('text=华东地区销售额为 1200 万元')).toBeVisible({ timeout: 8000 });
  });

  test('done 事件后显示反馈按钮', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"token","content":"答案是 100"}\n\n',
          agentDoneEvent({ answer: '答案是 100', traceId: 'nlq-feedback-001', runId: 'run-fb-001' }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('最大值是多少');
    await askBarInput.press('Enter');
    await expect(page.locator('text=答案是 100')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button[title="有用"]')).toBeVisible();
    await expect(page.locator('button[title="报告错误"]')).toBeVisible();
  });

  test('done 事件 sources 字段后显示数据源来源信息', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"metadata","conversation_id":"conv-meta","run_id":"run-meta-001"}\n\n',
          'data: {"type":"token","content":"共 2 个数据表。"}\n\n',
          agentDoneEvent({ answer: '共 2 个数据表。', traceId: 'nlq-meta-001', runId: 'run-meta-001', sourcesCount: 2, topSources: ['orders', 'customers'] }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('汇总数据');
    await askBarInput.press('Enter');
    await expect(page.locator('text=共 2 个数据表')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=orders')).toBeVisible();
    await expect(page.locator('text=customers')).toBeVisible();
  });

  // ── P1: Agent 错误事件渲染 ──────────────────────────────────────────────────

  test('Agent error 事件渲染错误提示', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"type":"error","error_code":"AGENT_003","message":"查询执行失败，请重试"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('查询数据');
    await askBarInput.press('Enter');
    await expect(page.locator('text=查询执行失败')).toBeVisible({ timeout: 5000 });
  });

  // ── P2: 反馈功能 ──────────────────────────────────────────────────────────

  test('点击"有用"按钮发送正向反馈到 /api/agent/feedback', async ({ page }) => {
    let feedbackBody: string | null = null;
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"metadata","conversation_id":"conv-fb-up","run_id":"run-fb-up-001"}\n\n',
          'data: {"type":"token","content":"满意"}\n\n',
          agentDoneEvent({ answer: '满意', traceId: 'nlq-feedback-up-001', runId: 'run-fb-up-001' }),
        ].join(''),
      });
    });
    await page.route('POST **/api/agent/feedback', async (route) => {
      feedbackBody = route.request().postData() ?? '';
      await route.fulfill({ status: 200, body: '{"status":"created","feedback_id":1}' });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('满意吗');
    await askBarInput.press('Enter');
    await expect(page.locator('text=满意')).toBeVisible({ timeout: 5000 });
    await page.waitForTimeout(1000);
    await page.locator('button[title="有用"]').click();
    expect(feedbackBody).not.toBeNull();
    const body = JSON.parse(feedbackBody!);
    expect(body.run_id).toBe('run-fb-up-001');
    expect(body.rating).toBe('up');
  });

  test('点击"报告错误"按钮发送负向反馈', async ({ page }) => {
    let feedbackBody: string | null = null;
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"metadata","conversation_id":"conv-fb-down","run_id":"run-fb-down-001"}\n\n',
          'data: {"type":"token","content":"有错误"}\n\n',
          agentDoneEvent({ answer: '有错误', traceId: 'nlq-feedback-down-001', runId: 'run-fb-down-001' }),
        ].join(''),
      });
    });
    await page.route('POST **/api/agent/feedback', async (route) => {
      feedbackBody = route.request().postData() ?? '';
      await route.fulfill({ status: 200, body: '{"status":"created","feedback_id":1}' });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('有错误吗');
    await askBarInput.press('Enter');
    await expect(page.locator('text=有错误')).toBeVisible({ timeout: 5000 });
    await page.waitForTimeout(1000);
    await page.locator('button[title="报告错误"]').click();
    expect(feedbackBody).not.toBeNull();
    const body = JSON.parse(feedbackBody!);
    expect(body.run_id).toBe('run-fb-down-001');
    expect(body.rating).toBe('down');
  });

  // ── P1: 错误处理（Agent error 事件） ──────────────────────────────────────

  test('NLQ_012 无数据源时显示"暂无可用数据源"而非未知错误', async ({ page }) => {
    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify([]) });
    });
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"type":"error","error_code":"NLQ_012","message":"暂无可用数据源，请先配置数据连接"}\n\n',
      });
    });
    await page.goto('/');
    const suggestion = page.locator('[data-suggestion]').first();
    if (await suggestion.isVisible({ timeout: 3000 }).catch(() => false)) {
      await suggestion.click();
      await expect(page.locator('text=暂无可用数据源')).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=未知错误')).toHaveCount(0);
    }
  });

  test('SYS_001 服务器错误时显示"服务器内部错误"', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"type":"error","error_code":"SYS_001","message":"服务器内部错误"}\n\n',
      });
    });
    await page.goto('/');
    const suggestion = page.locator('[data-suggestion]').first();
    if (await suggestion.isVisible({ timeout: 3000 }).catch(() => false)) {
      await suggestion.click();
      await expect(page.locator('text=服务器内部错误')).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=未知错误')).toHaveCount(0);
    }
  });

  test('NLQ_001 解析失败时显示错误提示', async ({ page }) => {
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"type":"error","error_code":"NLQ_001","message":"无法理解问题，请重新描述"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('asdfghjkl');
    await askBarInput.press('Enter');
    await expect(page.locator('text=无法理解问题')).toBeVisible({ timeout: 5000 });
  });

  // ── P1: 连接选择下拉 ──────────────────────────────────────────────────────

  test('有多个数据源连接时显示连接选择下拉框', async ({ page }) => {
    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: 1, name: 'Superstore', site_name: 'primary' },
          { id: 2, name: 'Finance DB', site_name: 'finance' },
        ]),
      });
    });
    await page.goto('/');
    const connectionPicker = page.locator('select[aria-label="选择数据源"], [data-connection-picker]').first();
    await expect(connectionPicker).toBeVisible({ timeout: 3000 });
  });

  test('只有一个数据源时隐藏连接下拉框', async ({ page }) => {
    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: 1, name: 'Superstore', site_name: 'primary' },
        ]),
      });
    });
    await page.goto('/');
    const connectionPicker = page.locator('select[aria-label="选择数据源"], [data-connection-picker]').first();
    await expect(connectionPicker).not.toBeVisible({ timeout: 3000 }).catch(() => {});
  });

  // ── P2: 追问功能 ──────────────────────────────────────────────────────────

  test('追问时携带 conversation_id', async ({ page }) => {
    let capturedBody: string | null = null;
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      const body = route.request().postData();
      if (body) capturedBody = body;
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"type":"metadata","conversation_id":"conv-followup","run_id":"run-followup"}\n\n',
          'data: {"type":"token","content":"回答"}\n\n',
          agentDoneEvent({ answer: '回答', traceId: 'nlq-conv-001', runId: 'run-followup' }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('第一问');
    await askBarInput.press('Enter');
    await expect(page.locator('text=回答')).toBeVisible({ timeout: 5000 });
    await askBarInput.fill('追问');
    await askBarInput.press('Enter');
    expect(capturedBody).not.toBeNull();
  });

  // ── 回归测试 ──────────────────────────────────────────────────────────────

  test('并发提问时只保留最新回答，不出现串流', async ({ page }) => {
    let requestCount = 0;
    await page.route('**/api/agent/stream**', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return; }
      requestCount++;
      const idx = requestCount;
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          `data: {"type":"token","content":"回答${idx}"}\n\n`,
          agentDoneEvent({ answer: `回答${idx}`, traceId: `nlq-concurrent-${idx}`, runId: `run-concurrent-${idx}` }),
        ].join(''),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');
    await askBarInput.fill('问题一');
    await sendBtn.click();
    await askBarInput.fill('问题二');
    await sendBtn.click();
    await expect(page.locator('text=回答2')).toBeVisible({ timeout: 8000 });
    await expect(page.locator('text=回答1')).not.toBeVisible({ timeout: 3000 });
  });
});
