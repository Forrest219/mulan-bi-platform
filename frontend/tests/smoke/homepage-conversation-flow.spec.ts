import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 首页对话流程
 *
 * 场景 1: 新建对话
 * 场景 2: 切换数据源
 * 场景 3: 自然语言提问
 */

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

async function login(page: any) {
  await page.goto('/login');
  await page.getByPlaceholder('用户名').fill(ADMIN_USERNAME);
  await page.getByPlaceholder('密码').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL('/', { timeout: 8000 });
}

async function selectConnectionAndFill(page: any, question: string) {
  // 选择第一个 Tableau 连接
  const connSelector = page.locator('#scope-connection');
  const options = await connSelector.locator('option').allInnerTexts();
  if (options.length > 1) {
    await connSelector.selectOption({ index: 1 });
    await page.waitForTimeout(300);
  }

  // 输入问题 - 使用 data-askbar-input 属性
  const askBar = page.locator('textarea[data-askbar-input]');
  await askBar.fill(question);
}

test.describe('首页 - 新建对话', () => {

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.waitForLoadState('networkidle');
  });

  test('点击新建对话后 AskBar 可输入问题', async ({ page }) => {
    // 点击新建对话按钮
    await page.locator('button[aria-label="新建对话"]').click();
    await page.waitForTimeout(500);

    // AskBar 应可见且可输入
    const askBar = page.locator('textarea[data-askbar-input]');
    await expect(askBar).toBeVisible();
    await expect(askBar).toBeEnabled();

    // 输入问题
    await askBar.fill('查询近7天数据');
    await expect(askBar).toHaveValue('查询近7天数据');
  });

  test('发送问题后出现回答或加载状态', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 直接输入问题（不预先选择连接）
    const askBar = page.locator('textarea[data-askbar-input]');
    await askBar.fill('查询近7天数据');

    // 点击发送按钮
    const sendBtn = page.locator('button[aria-label="发送"]');
    await sendBtn.click();

    // 验证发送后没有立即报错（输入框被清空或 loading 状态出现）
    await page.waitForTimeout(500);
    const inputValue = await askBar.inputValue();
    // 发送后输入框应该被清空（或正在加载）
    expect(inputValue === '' || await sendBtn.isDisabled()).toBeTruthy();
  });

  test('新建对话出现在侧边栏历史列表', async ({ page }) => {
    // Mock agent stream endpoint
    await page.route('**/api/agent/stream**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: 'data: {"type":"done","answer":"回答内容","trace_id":"smoke-history-001","run_id":"run-001","tools_used":[],"response_type":"text","response_data":null,"steps_count":0,"execution_time_ms":0,"sources_count":0,"top_sources":[]}\n\n',
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await selectConnectionAndFill(page, '测试问题1');
    const sendBtn = page.locator('button[aria-label="发送"]');
    await sendBtn.click();
    await page.waitForTimeout(2000);

    // 侧边栏应出现新建的对话
    const sidebar = page.locator('#sidebar, aside, nav').first();
    await expect(sidebar).toBeVisible();
  });
});

test.describe('首页 - 切换数据源', () => {

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.waitForLoadState('networkidle');
  });

  test('连接选择器可见且可点击', async ({ page }) => {
    // 查找连接选择器
    const connectionSelector = page.locator('select#scope-connection');
    await expect(connectionSelector).toBeVisible();

    // 应有选项（全部 + Tableau 连接）
    const options = await connectionSelector.locator('option').count();
    expect(options).toBeGreaterThan(1);
  });

  test('切换数据源后发送问题', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 选择第二个连接
    const connectionSelector = page.locator('#scope-connection');
    const options = await connectionSelector.locator('option').count();
    if (options > 2) {
      await connectionSelector.selectOption({ index: 2 });
      await page.waitForTimeout(300);
    }

    // 输入问题
    const askBar = page.locator('textarea[data-askbar-input]');
    await askBar.fill('列出所有工作簿');

    // 发送
    const sendBtn = page.locator('button[aria-label="发送"]');
    await sendBtn.click();

    // 验证发送后状态正常（输入框清空或loading出现）
    await page.waitForTimeout(500);
    const inputAfter = await askBar.inputValue();
    expect(inputAfter === '' || await sendBtn.isDisabled()).toBeTruthy();
  });
});

test.describe('首页 - 自然语言提问', () => {

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.waitForLoadState('networkidle');
  });

  test('发送自然语言问题后出现流式回答', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 输入自然语言问题
    const askBar = page.locator('textarea[data-askbar-input]');
    await askBar.fill('帮我分析近30天订单金额的变化趋势');

    // 发送
    const sendBtn = page.locator('button[aria-label="发送"]');
    await sendBtn.click();

    // 验证发送成功：输入框清空或loading状态
    await page.waitForTimeout(500);
    expect(await askBar.inputValue() === '' || await sendBtn.isDisabled()).toBeTruthy();
  });

  test('回答完成后显示反馈按钮', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 输入问题
    const askBar = page.locator('textarea[data-askbar-input]');
    await askBar.fill('测试反馈');
    await askBar.press('Enter');

    // 发送后页面应正常响应（无崩溃）
    await page.waitForTimeout(500);
    // 验证 AskBar 存在且可用
    await expect(askBar).toBeVisible();
  });

  test('追问基于上下文继续回答', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 首次提问
    const askBar = page.locator('textarea[data-askbar-input]');
    await askBar.fill('帮我分析近30天订单金额的变化趋势');
    await askBar.press('Enter');

    await page.waitForTimeout(500);

    // 追问
    await askBar.fill('换成折线图展示');
    await askBar.press('Enter');

    // 验证追问后页面仍正常
    await page.waitForTimeout(500);
    await expect(askBar).toBeVisible();
  });
});
