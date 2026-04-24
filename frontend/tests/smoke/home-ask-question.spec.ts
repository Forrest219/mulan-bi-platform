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

// ─── 回归测试：首页已修复 Bug ───────────────────────────────────────────────

test.describe('首页 - 回归测试', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('"前往添加"链接应指向 /system/mcp-configs 而非 /admin/llm-configs', async ({ page }) => {
    await page.route('**/api/tableau/connections**', async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify([]) });
    });
    await page.goto('/');
    const addLink = page.locator('a[href="/system/mcp-configs"]');
    const wrongLink = page.locator('a[href="/admin/llm-configs"]');
    await expect(wrongLink).toHaveCount(0);
    if (await addLink.isVisible()) {
      await addLink.click();
      await expect(page).not.toHaveURL(/404/, { timeout: 3000 });
    }
  });

  test('无数据源时点击默认问题应显示数据源缺失提示而非"未知错误"', async ({ page }) => {
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
      const errorCard = page.locator('text=暂无可用数据源');
      const unknownError = page.locator('text=未知错误');
      await expect(errorCard).toBeVisible({ timeout: 5000 });
      await expect(unknownError).toHaveCount(0);
    }
  });

  test('后端返回 SYS_001 时 ErrorCard 应显示"服务器内部错误"而非"未知错误"', async ({ page }) => {
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
    // 通过 suggestion card 触发 handleExamplePick（走 /api/search/query）
    const suggestion = page.locator('[data-suggestion]').first();
    if (await suggestion.isVisible({ timeout: 3000 }).catch(() => false)) {
      await suggestion.click();
      await expect(page.locator('text=服务器内部错误')).toBeVisible({ timeout: 5000 });
      await expect(page.locator('text=未知错误')).toHaveCount(0);
    }
  });
});
