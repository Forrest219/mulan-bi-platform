# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: login.spec.ts >> 登录页 >> 页面加载无 console.error
- Location: tests/smoke/login.spec.ts:16:3

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
  4   | const ADMIN_USERNAME = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
  5   | const ADMIN_PASSWORD = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';
  6   | // 用于测试错误密码
  7   | const WRONG_PASSWORD = 'wrong_password_123';
  8   | 
  9   | /**
  10  |  * Smoke Test: 登录页完整测试套件
  11  |  */
  12  | test.describe('登录页', () => {
  13  | 
  14  |   // ===== 基础元素渲染 =====
  15  | 
  16  |   test('页面加载无 console.error', async ({ page }) => {
  17  |     const errors: string[] = [];
  18  |     page.on('console', (msg) => {
  19  |       if (msg.type() === 'error') errors.push(msg.text());
  20  |     });
  21  |     await page.goto('/login');
> 22  |     await expect(page.locator('h1')).toContainText('Mulan Platform');
      |                                      ^ Error: expect(locator).toContainText(expected) failed
  23  |     // 过滤掉 401/403 等认证相关错误（登录页检查 session 时预期返回）
  24  |     const realErrors = errors.filter(e =>
  25  |       !e.includes('401') &&
  26  |       !e.includes('403') &&
  27  |       !e.includes('Unauthorized') &&
  28  |       !e.includes('fetch') &&
  29  |       !e.includes('favicon')
  30  |     );
  31  |     expect(realErrors).toHaveLength(0);
  32  |   });
  33  | 
  34  |   test('所有表单元素正常渲染', async ({ page }) => {
  35  |     await page.goto('/login');
  36  |     // Logo 标题
  37  |     await expect(page.locator('h1')).toContainText('Mulan Platform');
  38  |     // 用户名输入框
  39  |     const usernameInput = page.locator('input[type="text"]');
  40  |     await expect(usernameInput).toBeVisible();
  41  |     await expect(usernameInput).toHaveAttribute('placeholder', '请输入用户名');
  42  |     // 密码输入框
  43  |     const passwordInput = page.locator('input[type="password"]');
  44  |     await expect(passwordInput).toBeVisible();
  45  |     await expect(passwordInput).toHaveAttribute('placeholder', '请输入密码');
  46  |     // 提交按钮
  47  |     const submitBtn = page.locator('button[type="submit"]');
  48  |     await expect(submitBtn).toBeVisible();
  49  |     await expect(submitBtn).toContainText('登录');
  50  |     // 注册链接
  51  |     await expect(page.locator('a[href="/register"]')).toContainText('注册新账号');
  52  |   });
  53  | 
  54  |   // ===== 表单交互 =====
  55  | 
  56  |   test('空表单提交应显示错误提示', async ({ page }) => {
  57  |     await page.goto('/login');
  58  |     await page.locator('button[type="submit"]').click();
  59  |     // HTML5 原生验证会阻止提交，username 输入框应该高亮
  60  |     const usernameInput = page.locator('input[type="text"]');
  61  |     await expect(usernameInput).toBeFocused();
  62  |   });
  63  | 
  64  |   test('错误密码应显示错误提示', async ({ page }) => {
  65  |     await page.goto('/login');
  66  |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  67  |     await page.locator('input[type="password"]').fill(WRONG_PASSWORD);
  68  |     await page.locator('button[type="submit"]').click();
  69  |     // 等待错误提示出现（后端返回"用户名或密码错误"）
  70  |     await expect(page.locator('text=用户名或密码错误')).toBeVisible();
  71  |   });
  72  | 
  73  |   test('登录失败的错误提示应为可读文本，不能显示原始对象', async ({ page }) => {
  74  |     await page.route('**/api/auth/login', async (route) => {
  75  |       await route.fulfill({
  76  |         status: 500,
  77  |         headers: { 'content-type': 'application/json' },
  78  |         body: JSON.stringify({
  79  |           error_code: 'SYS_001',
  80  |           message: '服务器内部错误',
  81  |           detail: {},
  82  |         }),
  83  |       });
  84  |     });
  85  |     await page.goto('/login');
  86  |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  87  |     await page.locator('input[type="password"]').fill(WRONG_PASSWORD);
  88  |     await page.locator('button[type="submit"]').click();
  89  |     // 错误提示区域不能渲染原始对象 "{}" 或 "[object Object]"
  90  |     const errorArea = page.locator('.bg-red-50');
  91  |     await expect(errorArea).toBeVisible();
  92  |     await expect(errorArea).not.toContainText('{}');
  93  |     await expect(errorArea).not.toContainText('[object Object]');
  94  |   });
  95  | 
  96  |   test('正确凭据登录成功后跳转首页', async ({ page }) => {
  97  |     await page.goto('/login');
  98  |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  99  |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  100 |     await page.locator('button[type="submit"]').click();
  101 |     // 应跳转到首页 /
  102 |     await expect(page).toHaveURL('/');
  103 |   });
  104 | 
  105 |   test('登录成功后页面显示管理员欢迎语', async ({ page }) => {
  106 |     await page.goto('/login');
  107 |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  108 |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  109 |     await page.locator('button[type="submit"]').click();
  110 |     await expect(page).toHaveURL('/');
  111 |     // 等待页面加载完成，管理员信息显示在头部用户菜单
  112 |     await expect(page.locator('text=管理员').first()).toBeVisible();
  113 |   });
  114 | 
  115 |   test('admin/admin123 登录后能看到对话输入框', async ({ page }) => {
  116 |     await page.goto('/login');
  117 |     await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
  118 |     await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  119 |     await page.locator('button[type="submit"]').click();
  120 |     await expect(page).toHaveURL('/');
  121 |     await expect(page.locator('textarea, input[placeholder*="提问"], input[placeholder*="木兰"]').first()).toBeVisible();
  122 |   });
```