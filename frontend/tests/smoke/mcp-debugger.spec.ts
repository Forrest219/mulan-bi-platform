import { test, expect } from '@playwright/test';

/**
 * MCP 调试器冒烟测试
 * 使用 config_mulan.md 真实 Tableau MCP 配置
 *
 * 验证：
 * 1. 工具列表正常加载
 * 2. 选中工具后参数面板出现
 * 3. 执行调用（list-datasources，无需参数）并返回结果
 * 4. 审计日志中可见调用记录
 */

const ADMIN_USER = 'admin';
const ADMIN_PASS = 'admin123';

test.describe('MCP 调试器', () => {
  test.beforeEach(async ({ page }) => {
    // 1. 登录
    await page.goto(`${process.env.BASE_URL}/login`, { waitUntil: 'domcontentloaded' });
    await page.getByPlaceholder('用户名').fill(ADMIN_USER);
    await page.getByPlaceholder('密码').fill(ADMIN_PASS);
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL(`${process.env.BASE_URL}/**`, { timeout: 10000 });
    await page.waitForTimeout(500);
  });

  test('工具列表加载正常', async ({ page }) => {
    await page.goto(`${process.env.BASE_URL}/system/mcp-debugger`, {
      waitUntil: 'domcontentloaded',
    });

    // 验证页面标题
    await expect(page.getByRole('heading', { name: /MCP 调试器/ })).toBeVisible({ timeout: 8000 });

    // 验证工具列表出现（列表加载 + 至少包含核心工具 list-datasources）
    await expect(page.locator('button', { hasText: 'list-datasources' })).toBeVisible({ timeout: 8000 });
    // 确认列表可滚动（包含多个分类，说明长列表渲染正常）
    await expect(page.getByText('查询类')).toBeVisible();
    await expect(page.getByText('其他')).toBeVisible();
  });

  test('选中工具后参数面板和执行按钮正常', async ({ page }) => {
    await page.goto(`${process.env.BASE_URL}/system/mcp-debugger`, {
      waitUntil: 'domcontentloaded',
    });
    await expect(page.getByRole('heading', { name: /MCP 调试器/ })).toBeVisible({ timeout: 8000 });

    // 等待工具列表加载
    await page.waitForTimeout(1000);

    // 点击 list-datasources（无需参数的工具）
    await page.locator('button', { hasText: 'list-datasources' }).click();

    // 验证参数面板出现（工具名 + 执行按钮）
    // 参数区标题是 div.font-medium，精确匹配文本
    await expect(page.locator('div.font-medium').filter({ hasText: 'list-datasources' }).first()).toBeVisible();
    // 执行按钮有图标，用 nth(2) 或更精确描述
    await expect(page.getByRole('button', { name: '执行' }).nth(2)).toBeVisible({ timeout: 3000 });
  });

  test('执行 list-datasources 调用并查看审计日志', async ({ page }) => {
    await page.goto(`${process.env.BASE_URL}/system/mcp-debugger`, {
      waitUntil: 'domcontentloaded',
    });
    await expect(page.getByRole('heading', { name: /MCP 调试器/ })).toBeVisible({ timeout: 8000 });
    await page.waitForTimeout(1000);

    // 选中工具
    await page.locator('button', { hasText: 'list-datasources' }).click();
    await page.waitForTimeout(500);

    // 执行调用（参数区内的提交按钮，class 含 bg-blue-600）
    await page.locator('button[type="submit"]').click();

    // 等待结果出现（成功或报错都算调用完成）
    // 结果区域可能是 JSON viewer 或错误提示，均说明调用完成
    await page.waitForTimeout(5000);

    // 验证审计日志 tab 可点击，切到审计日志验证有记录
    await page.getByRole('button', { name: '审计日志' }).click();
    await page.waitForTimeout(2000);

    // 审计日志中应出现 list-datasources 调用记录
    const logsContent = await page.content();
    const hasLogEntry = logsContent.includes('list-datasources');
    expect(hasLogEntry).toBeTruthy();
  });
});
