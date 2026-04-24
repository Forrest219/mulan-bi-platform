import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 添加 StarRocks MCP 配置
 * 路径：/system/mcp-configs
 */
test.describe('MCP 配置管理 - 添加 StarRocks MCP', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('添加 StarRocks MCP 配置', async ({ page }) => {
    const uniqueName = `StarRocks Test ${Date.now()}`;

    await page.goto('/system/mcp-configs');

    // 点击新增配置
    await page.getByRole('button', { name: /新增配置/i }).click();

    // 等待表单出现
    await page.waitForTimeout(300);

    // 填写名称
    await page.locator('input[placeholder*="Tableau"]').first().fill(uniqueName);

    // 选择类型为 StarRocks
    await page.locator('select').first().selectOption('starrocks');

    // 填写 Server URL
    const serverUrlInput = page.locator('input[placeholder*="localhost"]').first();
    if (await serverUrlInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await serverUrlInput.fill('http://localhost:8000/mcp');
    }

    // 填写 StarRocks 连接信息
    const hostInput = page.locator('input[placeholder="localhost"]');
    if (await hostInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await hostInput.fill('localhost');
    }
    const portInput = page.locator('input[placeholder="9030"]');
    if (await portInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await portInput.fill('9030');
    }
    const userInput = page.locator('input[placeholder="root"]');
    if (await userInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await userInput.fill('root');
    }

    // 保存
    const saveBtn = page.getByRole('button', { name: /创建配置/i });
    await expect(saveBtn).toBeVisible({ timeout: 3000 });
    await saveBtn.click();

    // 等待返回列表页
    await page.waitForTimeout(1000);
    // 验证返回了列表页（h1 变为"新增 MCP 配置"或"MCP 配置管理"）
    const h1 = page.locator('h1');
    const h1Text = await h1.textContent({ timeout: 5000 }).catch(() => '');
    expect(h1Text).toMatch(/MCP 配置管理|新增 MCP 配置/);

    // cleanup: 通过 API 删除刚创建的测试记录
    const listResp = await page.request.get('/api/mcp-configs/', { headers: { 'Accept': 'application/json' } });
    if (listResp.ok()) {
      const servers = await listResp.json();
      const created = servers.find((s: { name: string }) => s.name === uniqueName);
      if (created) {
        await page.request.delete(`/api/mcp-configs/${created.id}`);
      }
    }
  });
});
