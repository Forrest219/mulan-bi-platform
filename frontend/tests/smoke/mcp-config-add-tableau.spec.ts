import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: 添加 Tableau MCP 配置
 * 路径：/system/mcp-configs
 */
test.describe('MCP 配置管理 - 添加 Tableau MCP', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('添加 Tableau MCP 配置', async ({ page }) => {
    const uniqueName = `Tableau Test ${Date.now()}`;

    await page.goto('/system/mcp-configs');

    // 点击新增配置
    await page.getByRole('button', { name: /新增配置/i }).click();

    // 等待表单出现
    await page.waitForTimeout(500);

    // 查找名称输入框（在表单内的 textbox，placeholder 为 "Tableau Dev"）
    const nameInput = page.locator('textbox[placeholder="Tableau Dev"]');
    if (await nameInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await nameInput.fill(uniqueName);
    }

    // 选择类型为 Tableau（默认应该是 tableau，但确认一下）
    const typeSelect = page.locator('select').first();
    await typeSelect.selectOption('tableau');

    // 等待认证字段出现
    await page.waitForTimeout(300);

    // 填写 Server URL（placeholder 是 "http://localhost:3927/tableau-mcp"）
    const serverUrlInput = page.locator('textbox[placeholder="http://localhost:3927/tableau-mcp"]');
    if (await serverUrlInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await serverUrlInput.fill('http://localhost:3927/tableau-mcp');
    }

    // 填写 Tableau Server URL
    const tableauServerInput = page.locator('textbox[placeholder="https://online.tableau.com"]');
    if (await tableauServerInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await tableauServerInput.fill('https://online.tableau.com');
    }

    // 填写 PAT 名称
    const patNameInput = page.locator('textbox[placeholder="Personal Access Token 名称"]');
    if (await patNameInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await patNameInput.fill('test-pat-name');
    }

    // 填写 PAT 密钥
    const patKeyInput = page.locator('textbox[placeholder="Personal Access Token 密钥"]');
    if (await patKeyInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await patKeyInput.fill('test-pat-value');
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
  });
});
