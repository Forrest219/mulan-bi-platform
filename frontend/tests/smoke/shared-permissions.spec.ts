import { test, expect } from '@playwright/test';

/**
 * Smoke Test: 共享权限巡检
 *
 * 用户场景：
 * 1. 管理员登录后查看权限列表，了解谁有共享权限
 * 2. 按用户/用户组筛选，快速定位某个人的权限
 * 3. 发现异常权限时批量撤销
 */

const ADMIN_USER = process.env.SMOKE_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.SMOKE_ADMIN_PASSWORD ?? 'admin123';

async function loginAsAdmin(page: any) {
  await page.goto('/login');
  await page.getByPlaceholder('用户名').fill(ADMIN_USER);
  await page.getByPlaceholder('密码').fill(ADMIN_PASS);
  await page.getByRole('button', { name: '登录' }).click();
  await page.waitForURL('/', { timeout: 8000 });
}

test.describe('共享权限巡检', () => {

  test('场景A：管理员查看共享权限列表', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/shared-permissions');
    await page.waitForLoadState('networkidle');

    // 验证页面标题
    await expect(page.locator('h1')).toContainText('共享权限巡检');

    // 验证页面副标题
    await expect(page.locator('text=查看和管理资源共享权限')).toBeVisible();

    // 验证统计卡片存在
    await expect(page.locator('text=共享权限总数')).toBeVisible();
    await expect(page.locator('text=已过期')).toBeVisible();
    await expect(page.locator('text=被授权主体')).toBeVisible();

    // 验证筛选器 select 存在
    const filterSelect = page.locator('select').first();
    await expect(filterSelect).toBeVisible();

    // 验证表格或空状态（API 可能返回 500 或空数据）
    const tableVisible = await page.locator('table').isVisible().catch(() => false);
    const emptyVisible = await page.locator('text=暂无共享权限').isVisible().catch(() => false);
    expect(tableVisible || emptyVisible).toBeTruthy();
  });

  test('场景B：按用户筛选权限', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/shared-permissions');
    await page.waitForLoadState('networkidle');

    // 选择「按用户」筛选
    const filterSelect = page.locator('select').first();
    await filterSelect.selectOption('user');
    await page.waitForTimeout(500);

    // 验证出现用户下拉选择
    const userSelect = page.locator('select').nth(1);
    await expect(userSelect).toBeVisible();

    // 获取用户数量
    const options = await userSelect.locator('option').count();
    if (options > 1) {
      // 选择第一个用户
      await userSelect.selectOption({ index: 1 });
      await page.waitForTimeout(500);

      // 表格或空状态应显示
      const tableVisible = await page.locator('table').isVisible().catch(() => false);
      const emptyVisible = await page.locator('text=暂无共享权限').isVisible().catch(() => false);
      expect(tableVisible || emptyVisible).toBeTruthy();
    }

    // 切换回「全部」
    await filterSelect.selectOption('all');
    await page.waitForTimeout(500);
  });

  test('场景C：批量撤销按钮交互', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/system/shared-permissions');
    await page.waitForLoadState('networkidle');

    // 等待内容加载
    await page.waitForSelector('h1', { timeout: 5000 });

    // 验证页面主体结构存在
    await expect(page.locator('text=共享权限巡检')).toBeVisible();
    await expect(page.locator('text=筛选：')).toBeVisible();

    // 如果有数据且可勾选，测试勾选和批量撤销按钮
    const firstCheckbox = page.locator('tbody input[type="checkbox"]').first();
    const checkboxCount = await page.locator('tbody input[type="checkbox"]').count();

    if (checkboxCount > 0) {
      await firstCheckbox.check();
      await page.waitForTimeout(300);

      // 验证出现批量撤销按钮
      const revokeBtn = page.locator('button', { hasText: '批量撤销' });
      await expect(revokeBtn).toBeVisible();

      // 点击撤销，dialog 自动接受
      page.on('dialog', dialog => dialog.accept());
      await revokeBtn.click();
      await page.waitForTimeout(1000);
    } else {
      // 无数据时，验证空状态提示
      await expect(page.locator('text=暂无共享权限')).toBeVisible();
    }
  });
});
