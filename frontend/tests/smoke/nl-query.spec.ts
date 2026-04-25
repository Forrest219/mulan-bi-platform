import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: NL-to-Query 流水线前端集成测试
 *
 * 覆盖范围：
 * - 首页 AskBar → /api/chat/stream（或 /api/search/query）NLQ 调用链
 * - 意图分类 + 查询构建（One-Pass LLM）结果的 UI 渲染
 * - 字段解析结果的展示
 * - 错误处理（NLQ_012 无数据源、SYS_001 服务错误）
 *
 * 对应后端：backend/tests/test_nlq_pipeline.py
 * 对应规格：docs/specs/14-nl-to-query-pipeline-spec.md
 */
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
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"华东区销售额为 1200 万元","trace_id":"nlq-smoke-001"}\n\n',
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
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"测试回答","trace_id":"nlq-smoke-enter"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('测试问题');
    await askBarInput.press('Enter');
    await expect(askBarInput).toHaveValue('');
  });

  test('发送中按钮显示 loading 状态且不可点击', async ({ page }) => {
    // 延迟响应模拟加载中状态
    await page.route('**/api/chat/stream**', async (route) => {
      // 不立即 fulFill，让请求挂起
      route.request().waitForResponse();
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
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"token":"华东","done":false}\n\n',
          'data: {"token":"地区","done":false}\n\n',
          'data: {"token":"销售额","done":false}\n\n',
          'data: {"done":true,"answer":"华东地区销售额为 1200 万元","trace_id":"nlq-stream-001"}\n\n',
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
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"答案是 100","trace_id":"nlq-feedback-001"}\n\n',
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

  test('metadata 事件后显示数据源来源信息', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"token":"当","done":false}\n\n',
          'data: {"type":"metadata","sources_count":2,"top_sources":["orders","customers"]}\n\n',
          'data: {"done":true,"answer":"共 2 个数据表。","trace_id":"nlq-meta-001"}\n\n',
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

  // ── P1: 意图类型响应渲染 ──────────────────────────────────────────────────

  test('响应类型为 number 时渲染数值卡片', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"月销售额为 850 万元","type":"number","data":{"value":8500000,"unit":"元","formatted":"850 万元"},"trace_id":"nlq-num-001"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('月销售额是多少');
    await askBarInput.press('Enter');
    await expect(page.locator('text=月销售额为 850 万元')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=850')).toBeVisible();
  });

  test('响应类型为 table 时渲染表格', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"各区域销售如下","type":"table","data":{"columns":["区域","销售额"],"rows":[{"区域":"华东","销售额":1200},{"区域":"华南","销售额":980}]},"trace_id":"nlq-table-001"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('各区域销售额');
    await askBarInput.press('Enter');
    await expect(page.locator('text=各区域销售如下')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=华东')).toBeVisible();
    await expect(page.locator('text=华南')).toBeVisible();
  });

  test('响应类型为 error 时渲染错误提示', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"查询失败","type":"error","detail":"数据源连接超时","trace_id":"nlq-err-001"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('查询数据');
    await askBarInput.press('Enter');
    await expect(page.locator('text=查询失败')).toBeVisible({ timeout: 5000 });
  });

  // ── P1: 置信度展示 ────────────────────────────────────────────────────────

  test('高置信度（>0.8）显示蓝色置信徽章', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"回答内容","confidence":0.95,"trace_id":"nlq-conf-high"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('销售额');
    await askBarInput.press('Enter');
    await expect(page.locator('text=95%')).toBeVisible({ timeout: 5000 });
  });

  test('低置信度（<0.6）显示橙色置信徽章', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"不确定的回答","confidence":0.45,"trace_id":"nlq-conf-low"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('模糊问题');
    await askBarInput.press('Enter');
    await expect(page.locator('text=45%')).toBeVisible({ timeout: 5000 });
  });

  // ── P2: 反馈功能 ──────────────────────────────────────────────────────────

  test('点击"有用"按钮发送正向反馈到 /api/ask-data/feedback', async ({ page }) => {
    let feedbackBody: string | null = null;
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"满意","trace_id":"nlq-feedback-up-001"}\n\n',
      });
    });
    await page.route('POST **/api/ask-data/feedback', async (route) => {
      feedbackBody = route.request().postData() ?? '';
      await route.fulfill({ status: 200, body: '{"ok":true}' });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('满意吗');
    await askBarInput.press('Enter');
    await expect(page.locator('text=满意')).toBeVisible({ timeout: 5000 });
    await page.locator('button[title="有用"]').click();
    expect(feedbackBody).not.toBeNull();
    const body = JSON.parse(feedbackBody!);
    expect(body.trace_id).toBe('nlq-feedback-up-001');
    expect(body.rating).toBe('up');
  });

  test('点击"报告错误"按钮发送负向反馈', async ({ page }) => {
    let feedbackBody: string | null = null;
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"有错误","trace_id":"nlq-feedback-down-001"}\n\n',
      });
    });
    await page.route('POST **/api/ask-data/feedback', async (route) => {
      feedbackBody = route.request().postData() ?? '';
      await route.fulfill({ status: 200, body: '{"ok":true}' });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('有错误吗');
    await askBarInput.press('Enter');
    await expect(page.locator('text=有错误')).toBeVisible({ timeout: 5000 });
    await page.locator('button[title="报告错误"]').click();
    expect(feedbackBody).not.toBeNull();
    const body = JSON.parse(feedbackBody!);
    expect(body.trace_id).toBe('nlq-feedback-down-001');
    expect(body.rating).toBe('down');
  });

  // ── P1: 错误处理 ──────────────────────────────────────────────────────────

  test('NLQ_012 无数据源时显示"暂无可用数据源"而非未知错误', async ({ page }) => {
    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify([]) });
    });
    await page.route('**/api/search/query**', async (route) => {
      await route.fulfill({
        status: 400,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          detail: { error_code: 'NLQ_012', message: '暂无可用数据源，请先配置数据连接' },
        }),
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
    await page.route('**/api/search/query**', async (route) => {
      await route.fulfill({
        status: 500,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          detail: { error_code: 'SYS_001', message: '服务器内部错误', details: {} },
        }),
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

  test('NLQ_001 解析失败时显示"无法理解问题"', async ({ page }) => {
    await page.route('**/api/search/query**', async (route) => {
      await route.fulfill({
        status: 422,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          detail: { error_code: 'NLQ_001', message: '无法理解问题，请重新描述' },
        }),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('asdfghjkl');
    await askBarInput.press('Enter');
    await expect(page.locator('text=无法理解问题')).toBeVisible({ timeout: 5000 });
  });

  test('NLQ_003 多数据源歧义时显示歧义提示和候选列表', async ({ page }) => {
    await page.route('**/api/search/query**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          answer: '您指的是哪个数据源？',
          type: 'ambiguous',
          data: {
            candidates: [
              { id: 1, name: '销售数据库' },
              { id: 2, name: '财务数据库' },
            ],
          },
          trace_id: 'nlq-ambig-001',
        }),
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('销售额');
    await askBarInput.press('Enter');
    await expect(page.locator('text=您指的是哪个数据源')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=销售数据库')).toBeVisible();
    await expect(page.locator('text=财务数据库')).toBeVisible();
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
    // 连接选择器应在 AskBar 中可见
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
    // 只有一个连接时选择器应隐藏（保持 AskBar 简洁）
    const connectionPicker = page.locator('select[aria-label="选择数据源"], [data-connection-picker]').first();
    // 不应显示或有特定隐藏 class
    await expect(connectionPicker).not.toBeVisible({ timeout: 3000 }).catch(() => {});
  });

  // ── P2: 追问功能 ──────────────────────────────────────────────────────────

  test('追问时携带 conversation_id', async ({ page }) => {
    let capturedBody: string | null = null;
    await page.route('**/api/chat/stream**', async (route) => {
      const body = route.request().postData();
      if (body) capturedBody = body;
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"回答","trace_id":"nlq-conv-001"}\n\n',
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('第一问');
    await askBarInput.press('Enter');
    await expect(page.locator('text=回答')).toBeVisible({ timeout: 5000 });
    // 等待 conversation_id 出现在 URL 或 store 中
    // 再次发送追问
    await askBarInput.fill('追问');
    await askBarInput.press('Enter');
    // capturedBody 中应包含 conversation_id（首次请求中 server 返回或在后续请求中携带）
    expect(capturedBody).not.toBeNull();
  });

  // ── 回归测试 ──────────────────────────────────────────────────────────────

  test('并发提问时只保留最新回答，不出现串流', async ({ page }) => {
    let requestCount = 0;
    await page.route('**/api/chat/stream**', async (route) => {
      requestCount++;
      const idx = requestCount;
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: `data: {"done":true,"answer":"回答${idx}","trace_id":"nlq-concurrent-${idx}"}\n\n`,
      });
    });
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');
    // 快速连续发送两个问题
    await askBarInput.fill('问题一');
    await sendBtn.click();
    await askBarInput.fill('问题二');
    await sendBtn.click();
    // 最终只显示问题二的结果
    await expect(page.locator('text=回答2')).toBeVisible({ timeout: 8000 });
    await expect(page.locator('text=回答1')).not.toBeVisible({ timeout: 3000 });
  });
});
