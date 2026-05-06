/**
 * Smoke Test: 查数日志写入验证
 *
 * 验证链路：首页发送问题 → /api/agent/stream SSE → 后端写入 nlq_query_logs
 * → GET /api/admin/query/logs 可查到该条记录
 *
 * 不 mock /api/agent/stream，走真实后端，确保 log_nlq_query 被调用。
 */
import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';
const API_BASE = process.env.API_BASE ?? 'http://localhost:8000';

// 唯一标识本次测试的问题文本（避免与已有记录混淆）
const TEST_QUESTION = `冒烟测试-查数日志-${Date.now()}`;

test.describe('查数日志写入', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 8000 });
  });

  test('首页问数后 nlq_query_logs 出现对应记录', async ({ page, request }) => {
    await page.goto('/');

    // 等待输入框出现
    const askBar = page.locator('textarea[data-askbar-input]');
    await expect(askBar).toBeVisible({ timeout: 5000 });

    // 记录发送前的时间（用于后续日志过滤）
    const beforeSend = new Date();

    // 输入并发送问题（回车触发）
    await askBar.fill(TEST_QUESTION);
    await askBar.press('Enter');

    // 等待 SSE 流结束标志：done 事件渲染的任意内容出现，
    // 或者等待 /api/agent/stream 请求完成（最多 30s）
    await page.waitForResponse(
      (resp) => resp.url().includes('/api/agent/stream') && resp.status() === 200,
      { timeout: 30000 },
    );

    // SSE 是流式响应，waitForResponse 在收到 headers 即返回，
    // 需要额外等待 done 事件被前端处理完毕（字符流动画最长约 3s）
    await page.waitForTimeout(4000);

    // 查询后端日志 API，验证写入
    const cookies = await page.context().cookies();
    const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join('; ');

    const logsResp = await request.get(`${API_BASE}/api/admin/query/logs`, {
      headers: { Cookie: cookieHeader },
      params: {
        page: '1',
        page_size: '20',
        start_time: beforeSend.toISOString().slice(0, 16),
      },
    });

    expect(logsResp.ok()).toBeTruthy();
    const logsData = await logsResp.json();

    const match = (logsData.items as Array<{ question: string }>).find(
      (item) => item.question === TEST_QUESTION,
    );

    expect(
      match,
      `nlq_query_logs 中未找到问题 "${TEST_QUESTION}"，实际返回条目数：${logsData.total}`,
    ).toBeTruthy();

    // 同时验证查数日志页面也能展示该条记录（DOM 闭环）
    await page.goto('/system/query-alerts');
    await expect(page.locator('h1')).toContainText('查数日志');

    const row = page.locator(`text=${TEST_QUESTION}`);
    // 页面默认时间范围是过去 24h，测试记录刚写入，应能看到
    await expect(row).toBeVisible({ timeout: 5000 });
  });
});
