import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';

/**
 * Smoke Test: LLM 配置表单校验
 * 路径：/system/llm-configs
 */
test.describe('LLM 配置管理 - 表单校验', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('Provider 切换自动填充对应的 base_url 和 model', async ({ page }) => {
    await page.goto('/system/llm-configs');
    await page.getByRole('button', { name: /新增配置/i }).click();
    await expect(page.getByRole('heading', { name: '新增 LLM 配置' })).toBeVisible({ timeout: 5000 });

    // Provider select 是表单中第二个 select（第1个是 purpose select）
    const providerSelect = page.locator('select').nth(1);

    // 默认选中 minimax，检查其默认 base_url 和 model
    const defaultBaseUrl = await page.locator('input[placeholder="https://api.openai.com/v1"]').inputValue();
    const defaultModel = await page.locator('input[placeholder="gpt-4o-mini"]').inputValue();
    expect(defaultBaseUrl).toContain('minimaxi');
    expect(defaultModel).toBe('MiniMax-2.7');

    // 切换到 OpenAI，检查 base_url 和 model 自动变化
    await providerSelect.selectOption('openai');
    const openaiBaseUrl = await page.locator('input[placeholder="https://api.openai.com/v1"]').inputValue();
    const openaiModel = await page.locator('input[placeholder="gpt-4o-mini"]').inputValue();
    expect(openaiBaseUrl).toBe('https://api.openai.com/v1');
    expect(openaiModel).toBe('gpt-4o-mini');

    // 切换到 Anthropic，检查 base_url 和 model 自动变化
    await providerSelect.selectOption('anthropic');
    const anthropicBaseUrl = await page.locator('input[placeholder="https://api.openai.com/v1"]').inputValue();
    const anthropicModel = await page.locator('input[placeholder="gpt-4o-mini"]').inputValue();
    expect(anthropicBaseUrl).toBe('https://api.anthropic.com');
    expect(anthropicModel).toBe('claude-3-5-sonnet-20241022');
  });

  test('新建配置时 API Key 为空拦截创建', async ({ page }) => {
    await page.goto('/system/llm-configs');
    await page.getByRole('button', { name: /新增配置/i }).click();
    await expect(page.getByRole('heading', { name: '新增 LLM 配置' })).toBeVisible({ timeout: 5000 });

    // 填写显示名称，但故意不填 API Key
    await page.locator('input[placeholder="GPT-4o Mini (General)"]').fill('API Key 测试配置');
    // API Key 输入框保留为空

    // 点击"创建配置"
    await page.getByRole('button', { name: /创建配置/i }).click();

    // 验证出现"API Key 不能为空"错误提示
    const errorMsg = page.locator('text=API Key 不能为空');
    await expect(errorMsg).toBeVisible({ timeout: 3000 });
  });

  test('新建配置时 Base URL 不以 http 开头拦截创建', async ({ page }) => {
    await page.goto('/system/llm-configs');
    await page.getByRole('button', { name: /新增配置/i }).click();
    await expect(page.getByRole('heading', { name: '新增 LLM 配置' })).toBeVisible({ timeout: 5000 });

    // 填写显示名称和 API Key，但 Base URL 写错（故意不加 http）
    await page.locator('input[placeholder="GPT-4o Mini (General)"]').fill('Base URL 校验测试');
    await page.locator('input[placeholder="sk-..."]').fill('sk-test-base-url-key');

    // 找到 Base URL 输入框（placeholder="https://api.openai.com/v1"），清空后填入无效值
    const baseUrlInput = page.locator('input[placeholder="https://api.openai.com/v1"]');
    await baseUrlInput.clear();
    await baseUrlInput.fill('ftp://invalid-url.com');

    // 点击"创建配置"
    await page.getByRole('button', { name: /创建配置/i }).click();

    // 验证出现"Base URL 必须以 http:// 或 https:// 开头"错误提示
    const errorMsg = page.locator('text=Base URL 必须以 http');
    await expect(errorMsg).toBeVisible({ timeout: 3000 });
  });

  test('新建配置时 display_name 重复，前端显示"显示名称已存在"提示', async ({ page }) => {
    await page.goto('/system/llm-configs');
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });

    // 从列表中取一个真实存在的 display_name（找首个非 "-" 的"名称"列）
    const nameCells = page.locator('tbody tr td:nth-child(2)');
    const total = await nameCells.count();
    let duplicateName = '';
    for (let i = 0; i < total; i++) {
      const txt = (await nameCells.nth(i).textContent() ?? '').trim();
      if (txt && txt !== '-') { duplicateName = txt; break; }
    }
    if (!duplicateName) { test.skip(); return; }

    // 新建配置时填入重复 display_name
    await page.getByRole('button', { name: /新增配置/i }).click();
    await expect(page.getByRole('heading', { name: '新增 LLM 配置' })).toBeVisible({ timeout: 5000 });
    await page.locator('input[placeholder="GPT-4o Mini (General)"]').fill(duplicateName);
    await page.locator('input[placeholder="sk-..."]').fill('sk-test-duplicate-key');
    // 滚动到底部确保"创建配置"按钮可见并点击
    const createBtn = page.getByRole('button', { name: /创建配置/i });
    await createBtn.scrollIntoViewIfNeeded();

    // 监听创建配置请求的响应
    const respPromise = page.waitForResponse(r => r.url().includes('/api/llm/configs') && r.request().method() === 'POST', { timeout: 8000 });
    await createBtn.click();
    const resp = await respPromise;
    expect(resp.status()).toBe(409);

    // 验证前端显示"显示名称已存在"错误提示
    await expect(page.locator('text=/显示名称已存在/')).toBeVisible({ timeout: 5000 });
  });
});
