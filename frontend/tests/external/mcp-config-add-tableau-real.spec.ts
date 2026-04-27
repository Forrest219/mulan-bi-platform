import { test, expect } from '@playwright/test';

// 使用真实 Tableau PAT 测试 MCP Tableau 配置创建
// 必须设置环境变量 TABLEAU_PAT（格式: token_name:token_secret）
const ADMIN_USER = 'admin';
const ADMIN_PASS = 'admin123';
const TABLEAU_PAT = process.env.TABLEAU_PAT;
const TABLEAU_SERVER_URL = process.env.TABLEAU_SERVER_URL;

test.describe('MCP 配置管理 - 使用真实 Tableau PAT @external @tableau @mcp', () => {
  test('使用真实 Tableau PAT 创建 MCP Tableau 配置并保存 @external @tableau @mcp', async ({ page }) => {
    // 跳过测试如果未配置 PAT
    test.skip(!TABLEAU_PAT, 'TABLEAU_PAT 环境变量未配置，跳过此测试');
    test.skip(!TABLEAU_SERVER_URL, 'TABLEAU_SERVER_URL 环境变量未配置，跳过此测试');
    // 1. 登录
    await page.goto(`${process.env.BASE_URL}/login`);
    await page.getByPlaceholder('用户名').fill(ADMIN_USER);
    await page.getByPlaceholder('密码').fill(ADMIN_PASS);
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL(`${process.env.BASE_URL}/**`, { timeout: 10000 });
    await page.waitForLoadState('networkidle');

    // 2. 导航到 MCP 配置页
    await page.goto(`${process.env.BASE_URL}/system/mcp-configs`);
    await page.waitForLoadState('networkidle');

    // 3. 点击新增配置
    await page.getByRole('button', { name: /新增配置/i }).click();

    // 4. 等待表单出现（heading 出现即表单渲染完毕）
    await expect(page.getByRole('heading', { name: '新增 MCP 配置' })).toBeVisible({ timeout: 5000 });

    // 5. 填写 MCP 表单
    // 解析 TABLEAU_PAT（格式: token_name:token_secret）
    const [patName, patSecret] = TABLEAU_PAT.split(':');
    const uniqueName = `Tableau-MCP-Test-${Date.now()}`;

    // 名称
    await page.getByPlaceholder('Tableau Dev').fill(uniqueName);

    // Server URL
    await page.getByPlaceholder('http://localhost:3927/tableau-mcp').fill(TABLEAU_SERVER_URL);

    // Tableau Server URL (认证区)
    await page.getByPlaceholder('https://online.tableau.com').fill(TABLEAU_SERVER_URL);

    // PAT 名称
    await page.getByPlaceholder('Personal Access Token 名称').fill(patName);

    // PAT 密钥
    await page.getByPlaceholder('Personal Access Token 密钥').fill(patSecret);

    // 6. 点击创建配置按钮
    await page.getByRole('button', { name: '创建配置' }).click();

    // 7. 等待保存完成，验证回到列表页
    await page.waitForTimeout(3000);
    await expect(page).toHaveURL(/\/system\/mcp-configs/, { timeout: 5000 });

    // 8. 验证新配置出现在列表中
    const pageContent = await page.content();
    const configExists = pageContent.includes('Tableau-MCP-Test-');
    expect(configExists).toBeTruthy();
  });
});
