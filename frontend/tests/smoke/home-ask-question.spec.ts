import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 首页问答功能
 * 路径：/
 */
test.describe('首页 - 问答功能', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('首页显示问答输入框', async ({ page }) => {
    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await expect(askBarInput).toBeVisible();
  });

  test('发送问题后出现加载或回答状态', async ({ page }) => {
    // Mock SSE 确保有稳定回答，避免依赖真实后端
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"销售额最高的区域是华东区。","trace_id":"smoke-001"}\n\n',
      });
    });

    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');

    await askBarInput.fill('查询销售额最高的产品');
    await sendBtn.click();

    // 回答出现即表示 UI 正确渲染了流式响应
    await expect(page.locator('text=销售额最高的区域是华东区')).toBeVisible({ timeout: 5000 });
  });

  test('回车键可以发送问题', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('查询本月收入');
    await askBarInput.press('Enter');

    // 输入框应被清空
    await expect(askBarInput).toHaveValue('');
  });

  test('发送后输入框被清空', async ({ page }) => {
    await page.goto('/');

    const askBarInput = page.locator('textarea[data-askbar-input]');
    const sendBtn = page.locator('button[aria-label="发送"]');

    await askBarInput.fill('测试问题');
    await sendBtn.click();

    // 无论结果如何，输入框都应清空
    await expect(askBarInput).toHaveValue('');
  });

  // ─── P2: 网络层契约验证 ────────────────────────────────────────────────

  test('Ask Data 调用正确 endpoint 并渲染 token 流', async ({ page }) => {
    let capturedUrl = '';
    await page.route('**/api/chat/stream**', async (route) => {
      capturedUrl = route.request().url();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"token":"根","done":false}\n\n',
          'data: {"token":"据","done":false}\n\n',
          'data: {"done":true,"answer":"根据分析，销售额最高的产品是 A 产品。","trace_id":"test-trace-001"}\n\n',
        ].join(''),
      });
    });

    await page.goto('/');
    const askBarInput = page.locator('textarea[data-askbar-input]');
    await askBarInput.fill('销售额最高的产品是什么');
    await askBarInput.press('Enter');

    expect(capturedUrl).toContain('/api/chat/stream');
    await expect(page.locator('text=根据分析，销售额最高的产品是 A 产品')).toBeVisible({ timeout: 5000 });
  });

  test('done 事件后显示回答并渲染反馈按钮', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"答案是 42","trace_id":"trace-042"}\n\n',
      });
    });

    await page.goto('/');
    await page.locator('textarea[data-askbar-input]').fill('人生的意义是什么');
    await page.keyboard.press('Enter');

    await expect(page.locator('text=答案是 42')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('button[title="有用"]')).toBeVisible();
    await expect(page.locator('button[title="报告错误"]')).toBeVisible();
  });

  test('点击反馈按钮发送 /api/ask-data/feedback', async ({ page }) => {
    let feedbackBody: string | null = null;

    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"done":true,"answer":"满意","trace_id":"trace-abc123"}\n\n',
      });
    });

    await page.route('POST **/api/ask-data/feedback', async (route) => {
      feedbackBody = route.request().postData() ?? '';
      await route.fulfill({ status: 200, body: '{"ok":true}' });
    });

    await page.goto('/');
    await page.locator('textarea[data-askbar-input]').fill('满意吗');
    await page.keyboard.press('Enter');

    await expect(page.locator('text=满意')).toBeVisible({ timeout: 5000 });
    await page.locator('button[title="有用"]').click();

    expect(feedbackBody).not.toBeNull();
    const body = JSON.parse(feedbackBody!);
    expect(body.trace_id).toBe('trace-abc123');
    expect(body.rating).toBe('up');
  });

  test('metadata 事件后显示来源徽章', async ({ page }) => {
    await page.route('**/api/chat/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'data: {"token":"根","done":false}\n\n',
          'data: {"type":"metadata","sources_count":3,"top_sources":["产品表","销售表","客户表"]}\n\n',
          'data: {"done":true,"answer":"共 3 个数据源。","trace_id":"trace-meta-001"}\n\n',
        ].join(''),
      });
    });

    await page.goto('/');
    await page.locator('textarea[data-askbar-input]').fill('有哪些数据');
    await page.keyboard.press('Enter');

    await expect(page.locator('text=共 3 个数据源')).toBeVisible({ timeout: 5000 });
    // 来源徽章：显示数据源总数
    await expect(page.locator('text=基于 3 个数据源生成')).toBeVisible();
    // 来源徽章：显示具体表名
    await expect(page.locator('text=产品表')).toBeVisible();
    await expect(page.locator('text=销售表')).toBeVisible();
  });
});
