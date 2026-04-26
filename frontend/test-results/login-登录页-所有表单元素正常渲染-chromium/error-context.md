# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: login.spec.ts >> 登录页 >> 所有表单元素正常渲染
- Location: tests/smoke/login.spec.ts:33:3

# Error details

```
Error: expect(locator).toContainText(expected) failed

Locator: locator('h1')
Expected substring: "Mulan Platform"
Received string:    "木兰 BI 平台"
Timeout: 5000ms

Call log:
  - Expect "toContainText" with timeout 5000ms
  - waiting for locator('h1')
    9 × locator resolved to <h1 class="text-xl font-semibold text-slate-900 mb-1">木兰 BI 平台</h1>
      - unexpected value "木兰 BI 平台"

```

# Page snapshot

```yaml
- generic [ref=e4]:
  - generic [ref=e5]:
    - img "木兰 BI 平台 Logo" [ref=e6]
    - heading "木兰 BI 平台" [level=1] [ref=e7]
    - paragraph [ref=e8]: 数据建模与治理平台
  - generic [ref=e10]:
    - generic [ref=e11]:
      - generic [ref=e12]: 用户名
      - textbox "用户名" [ref=e13]:
        - /placeholder: 请输入用户名
    - generic [ref=e14]:
      - generic [ref=e15]: 密码
      - generic [ref=e16]:
        - textbox "密码" [ref=e17]:
          - /placeholder: 请输入密码
        - button "切换密码显示" [ref=e18] [cursor=pointer]:
          - img [ref=e19]
    - link "忘记密码？" [ref=e23] [cursor=pointer]:
      - /url: /forgot-password
    - button "登录" [ref=e24] [cursor=pointer]
    - link "注册新账号" [ref=e26] [cursor=pointer]:
      - /url: /register
```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test';
  2   | 
  3   | // 默认管理员账号（参考 README）
  4   | const ADMIN_USERNAME = 'admin';
  5   | const ADMIN_PASSWORD = 'admin123';
  6   | const TEST_USER_PASSWORD = 'wrongpassword';
  7   | 
  8   | /**
  9   |  * Smoke Test: 登录页完整测试套件
  10  |  */
  11  | test.describe('登录页', () => {
  12  | 
  13  |   // ===== 基础元素渲染 =====
  14  | 
  15  |   test('页面加载无 console.error', async ({ page }) => {
  16  |     const errors: string[] = [];
  17  |     page.on('console', (msg) => {
  18  |       if (msg.type() === 'error') errors.push(msg.text());
  19  |     });
  20  |     await page.goto('/login');
  21  |     await expect(page.locator('h1')).toContainText('Mulan Platform');
  22  |     // 过滤掉 401/403 等认证相关错误（登录页检查 session 时预期返回）
  23  |     const realErrors = errors.filter(e =>
  24  |       !e.includes('401') &&
  25  |       !e.includes('403') &&
  26  |       !e.includes('Unauthorized') &&
  27  |       !e.includes('fetch') &&
  28  |       !e.includes('favicon')
  29  |     );
  30  |     expect(realErrors).toHaveLength(0);
  31  |   });
  32  | 
  33  |   test('所有表单元素正常渲染', async ({ page }) => {
  34  |     await page.goto('/login');
  35  |     // Logo 标题
> 36  |     await expect(page.locator('h1')).toContainText('Mulan Platform');
      |                                      ^ Error: expect(locator).toContainText(expected) failed
  37  |     // 用户名输入框
  38  |     const usernameInput = page.locator('input[type="text"]');
  39  |     await expect(usernameInput).toBeVisible();
  40  |     await expect(usernameInput).toHaveAttribute('placeholder', '请输入用户名');
  41  |     // 密码输入框
  42  |     const passwordInput = page.locator('input[type="password"]');
  43  |     await expect(passwordInput).toBeVisible();
  44  |     await expect(passwordInput).toHaveAttribute('placeholder', '请输入密码');
  45  |     // 提交按钮
  46  |     const submitBtn = page.locator('button[type="submit"]');
  47  |     await expect(submitBtn).toBeVisible();
  48  |     await expect(submitBtn).toContainText('登录');
  49  |     // 注册链接
  50  |     await expect(page.locator('a[href="/register"]')).toContainText('注册新账号');
  51  |   });
  52  | 
  53  |   // ===== 表单交互 =====
  54  | 
  55  |   test('空表单提交应显示错误提示', async ({ page }) => {
  56  |     await page.goto('/login');
  57  |     await page.locator('button[type="submit"]').click();
  58  |     // HTML5 原生验证会阻止提交，username 输入框应该高亮
  59  |     const usernameInput = page.locator('input[type="text"]');
  60  |     await expect(usernameInput).toBeFocused();
  61  |   });
  62  | 
  63  |   test('错误密码应显示错误提示', async ({ page }) => {
  64  |     await page.goto('/login');
  65  |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  66  |     await page.locator('input[type="password"]').fill(TEST_USER_PASSWORD);
  67  |     await page.locator('button[type="submit"]').click();
  68  |     // 等待错误提示出现（后端返回"用户名或密码错误"）
  69  |     await expect(page.locator('text=用户名或密码错误')).toBeVisible({ timeout: 5000 });
  70  |   });
  71  | 
  72  |   test('登录失败的错误提示应为可读文本，不能显示原始对象', async ({ page }) => {
  73  |     await page.route('**/api/auth/login', async (route) => {
  74  |       await route.fulfill({
  75  |         status: 500,
  76  |         headers: { 'content-type': 'application/json' },
  77  |         body: JSON.stringify({
  78  |           error_code: 'SYS_001',
  79  |           message: '服务器内部错误',
  80  |           detail: {},
  81  |         }),
  82  |       });
  83  |     });
  84  |     await page.goto('/login');
  85  |     await page.locator('input[type="text"]').fill('admin');
  86  |     await page.locator('input[type="password"]').fill('any');
  87  |     await page.locator('button[type="submit"]').click();
  88  |     // 错误提示区域不能渲染原始对象 "{}" 或 "[object Object]"
  89  |     const errorArea = page.locator('.bg-red-50');
  90  |     await expect(errorArea).toBeVisible({ timeout: 5000 });
  91  |     const text = await errorArea.textContent();
  92  |     expect(text).not.toContain('{}');
  93  |     expect(text).not.toContain('[object Object]');
  94  |   });
  95  | 
  96  |   test('正确凭据登录成功后跳转首页', async ({ page }) => {
  97  |     await page.goto('/login');
  98  |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  99  |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  100 |     await page.locator('button[type="submit"]').click();
  101 |     // 应跳转到首页 /
  102 |     await expect(page).toHaveURL('/', { timeout: 5000 });
  103 |   });
  104 | 
  105 |   test('登录成功后页面显示管理员欢迎语', async ({ page }) => {
  106 |     await page.goto('/login');
  107 |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  108 |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  109 |     await page.locator('button[type="submit"]').click();
  110 |     await expect(page).toHaveURL('/', { timeout: 5000 });
  111 |     // 等待页面加载完成，管理员信息显示在头部用户菜单
  112 |     await expect(page.locator('text=管理员').first()).toBeVisible({ timeout: 5000 });
  113 |   });
  114 | 
  115 |   test('admin/admin123 登录后能看到对话输入框', async ({ page }) => {
  116 |     await page.goto('/login');
  117 |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  118 |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  119 |     await page.locator('button[type="submit"]').click();
  120 |     await expect(page).toHaveURL('/', { timeout: 5000 });
  121 |     await expect(page.locator('textarea, input[placeholder*="提问"], input[placeholder*="木兰"]').first()).toBeVisible({ timeout: 5000 });
  122 |   });
  123 | 
  124 |   // ===== 键盘交互 =====
  125 | 
  126 |   test('用户名框按 Enter 提交表单', async ({ page }) => {
  127 |     await page.goto('/login');
  128 |     const usernameInput = page.locator('input[type="text"]');
  129 |     const passwordInput = page.locator('input[type="password"]');
  130 |     await usernameInput.fill(ADMIN_USERNAME);
  131 |     await usernameInput.press('Enter');
  132 |     // Enter 应填入密码或直接提交
  133 |     // 验证密码框有内容或表单已提交
  134 |     await expect(passwordInput).toBeVisible();
  135 |   });
  136 | 
```