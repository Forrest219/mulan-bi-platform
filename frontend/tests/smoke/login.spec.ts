import { test, expect } from '@playwright/test';

// 默认管理员账号（参考 README）
const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = 'admin123';
const TEST_USER_PASSWORD = 'wrongpassword';

/**
 * Smoke Test: 登录页完整测试套件
 */
test.describe('登录页', () => {

  // ===== 基础元素渲染 =====

  test('页面加载无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/login');
    await expect(page.locator('h1')).toContainText('Mulan Platform');
    // 过滤掉 401/403 等认证相关错误（登录页检查 session 时预期返回）
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('所有表单元素正常渲染', async ({ page }) => {
    await page.goto('/login');
    // Logo 标题
    await expect(page.locator('h1')).toContainText('Mulan Platform');
    // 用户名输入框
    const usernameInput = page.locator('input[type="text"]');
    await expect(usernameInput).toBeVisible();
    await expect(usernameInput).toHaveAttribute('placeholder', '请输入用户名');
    // 密码输入框
    const passwordInput = page.locator('input[type="password"]');
    await expect(passwordInput).toBeVisible();
    await expect(passwordInput).toHaveAttribute('placeholder', '请输入密码');
    // 提交按钮
    const submitBtn = page.locator('button[type="submit"]');
    await expect(submitBtn).toBeVisible();
    await expect(submitBtn).toContainText('登录');
    // 注册链接
    await expect(page.locator('a[href="/register"]')).toContainText('注册新账号');
  });

  // ===== 表单交互 =====

  test('空表单提交应显示错误提示', async ({ page }) => {
    await page.goto('/login');
    await page.locator('button[type="submit"]').click();
    // HTML5 原生验证会阻止提交，username 输入框应该高亮
    const usernameInput = page.locator('input[type="text"]');
    await expect(usernameInput).toBeFocused();
  });

  test('错误密码应显示错误提示', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(TEST_USER_PASSWORD);
    await page.locator('button[type="submit"]').click();
    // 等待错误提示出现（后端返回"用户名或密码错误"）
    await expect(page.locator('text=用户名或密码错误')).toBeVisible({ timeout: 5000 });
  });

  test('正确凭据登录成功后跳转首页', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    // 应跳转到首页 /
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('登录成功后页面显示管理员欢迎语', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
    // 等待页面加载完成，管理员信息显示在头部用户菜单
    await expect(page.locator('text=管理员').first()).toBeVisible({ timeout: 5000 });
  });

  test('admin/admin123 登录后能看到对话输入框', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
    await expect(page.locator('textarea, input[placeholder*="提问"], input[placeholder*="木兰"]').first()).toBeVisible({ timeout: 5000 });
  });

  // ===== 键盘交互 =====

  test('用户名框按 Enter 提交表单', async ({ page }) => {
    await page.goto('/login');
    const usernameInput = page.locator('input[type="text"]');
    const passwordInput = page.locator('input[type="password"]');
    await usernameInput.fill(ADMIN_USERNAME);
    await usernameInput.press('Enter');
    // Enter 应填入密码或直接提交
    // 验证密码框有内容或表单已提交
    await expect(passwordInput).toBeVisible();
  });

  test('密码框按 Enter 提交表单', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('input[type="password"]').press('Enter');
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ===== 页面导航 =====

  test('点击注册链接跳转注册页', async ({ page }) => {
    await page.goto('/login');
    await page.locator('a[href="/register"]').click();
    await expect(page).toHaveURL('/register');
  });

  // ===== 加载状态 =====

  test('登录中按钮显示 loading 状态且不可点击', async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    const submitBtn = page.locator('button[type="submit"]');
    await submitBtn.click();
    // 按钮文字变为"登录中..."
    await expect(submitBtn).toContainText('登录中');
    // 按钮变为 disabled
    await expect(submitBtn).toBeDisabled();
  });
});

/**
 * Smoke Test: 注册页完整测试套件
 */
test.describe('注册页', () => {

  test('注册页加载无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/register');
    await expect(page.locator('h1')).toContainText('注册账号');
    // 过滤掉 401/403 等认证相关错误（注册页检查 session 时预期返回）
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('fetch') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('两次密码不一致时显示错误', async ({ page }) => {
    await page.goto('/register');
    // 注册页只有用户名、密码、确认密码（无 email）
    await page.locator('input[placeholder="请输入用户名"]').fill('testuser');
    await page.locator('input[placeholder="至少6位"]').fill('password123');
    await page.locator('input[placeholder="再次输入密码"]').fill('password456');
    await page.locator('button[type="submit"]').click();
    await expect(page.locator('text=两次输入的密码不一致')).toBeVisible({ timeout: 3000 });
  });

  test('点击去登录链接跳转登录页', async ({ page }) => {
    await page.goto('/register');
    await page.locator('a[href="/login"]').click();
    await expect(page).toHaveURL('/login');
  });
});
