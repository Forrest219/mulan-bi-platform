import { test, expect } from '@playwright/test';

// LLM 真实 Token 从环境变量读取（不得硬编码）
// 运行前需设置：export MINIMAX_API_TOKEN="sk-cp-..."
const MINIMAX_API_TOKEN = process.env.MINIMAX_API_TOKEN;
const ADMIN_USER = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';

// Token 未配置时跳过整个测试
test.skip(!MINIMAX_API_TOKEN, 'MINIMAX_API_TOKEN 环境变量未设置，跳过此测试');

test.describe('LLM 配置管理 - 使用真实 MiniMax Token', () => {
  test('使用真实 MiniMax Token 创建 LLM 配置并保存', async ({ page }) => {
    // 1. 登录
    await page.goto(`${process.env.BASE_URL}/login`, { waitUntil: 'domcontentloaded' });
    await page.getByPlaceholder('用户名').fill(ADMIN_USER);
    await page.getByPlaceholder('密码').fill(ADMIN_PASS);
    await page.getByRole('button', { name: '登录' }).click();
    await page.waitForURL(`${process.env.BASE_URL}/**`, { timeout: 10000 });
    await page.waitForTimeout(1000);

    // 2. 导航到 LLM 配置页
    await page.goto(`${process.env.BASE_URL}/system/llm-configs`, { waitUntil: 'domcontentloaded' });

    // 3. 点击新增配置
    await page.getByRole('button', { name: /新增配置/i }).click();

    // 4. 等待表单出现（heading 出现即表单渲染完毕）
    await expect(page.getByRole('heading', { name: '新增 LLM 配置' })).toBeVisible({ timeout: 5000 });

    // 5. 填写表单
    // 等待 form 渲染
    await page.waitForTimeout(1000);

    // 显示名称 (placeholder="GPT-4o Mini (General)")
    await page.getByPlaceholder('GPT-4o Mini (General)').fill(`MiniMax-Test-${Date.now()}`);

    // API Key（从环境变量注入，不得硬编码）
    await page.getByPlaceholder('sk-...').fill(MINIMAX_API_TOKEN);

    // 6. 点击创建配置按钮
    await page.getByRole('button', { name: '创建配置' }).click();

    // 7. 等待保存完成，验证回到列表页
    await page.waitForTimeout(3000);
    await expect(page).toHaveURL(/\/system\/llm-configs/, { timeout: 5000 });

    // 8. 验证新配置出现在列表中
    const pageContent = await page.content();
    const configExists = pageContent.includes('MiniMax-Test-');
    expect(configExists).toBeTruthy();
  });
});
