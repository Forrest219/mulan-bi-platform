import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

test.describe('连接总览', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  test('连接总览页可访问', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await expect(page.locator('h1')).toContainText('连接总览');
  });

  test('KPI 卡片显示中文标签', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await expect(page.locator('text=总计')).toBeVisible();
    await expect(page.locator('.text-emerald-700', { hasText: '正常' })).toBeVisible();
    await expect(page.locator('.text-amber-700', { hasText: '警告' })).toBeVisible();
    await expect(page.locator('.text-red-700', { hasText: '失败' })).toBeVisible();
  });

  test('Tab 标签为中文', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await expect(page.locator('button', { hasText: '总览' })).toBeVisible();
    await expect(page.locator('button', { hasText: '数据库' })).toBeVisible();
    await expect(page.locator('button', { hasText: 'Tableau' })).toBeVisible();
  });

  test('数据库和 Tableau tab 可切换', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await page.locator('button', { hasText: 'Tableau' }).click();
    await expect(page).toHaveURL(/type=tableau/);
    await page.locator('button', { hasText: '数据库' }).click();
    await expect(page).toHaveURL(/type=db/);
  });

  test('数据库 tab 有"管理数据源"跳转链接', async ({ page }) => {
    await page.goto('/assets/connection-center?type=db');
    await expect(page.locator('a[href="/assets/datasources"]').last()).toBeVisible({ timeout: 3000 });
  });

  test('Tableau tab 有"管理 Tableau 连接"跳转链接', async ({ page }) => {
    await page.goto('/assets/connection-center?type=tableau');
    await expect(page.locator('a[href="/assets/tableau-connections"]').last()).toBeVisible({ timeout: 3000 });
  });

  test('页面无英文占位文案残留', async ({ page }) => {
    await page.goto('/assets/connection-center');
    await page.waitForTimeout(1000);
    const body = await page.locator('body').textContent();
    expect(body).not.toContain('Import Placeholder');
    expect(body).not.toContain('New Connection (CTA)');
    expect(body).not.toContain('Owner placeholder');
    expect(body).not.toContain('option C shell');
  });

  test('页面无控制台 JS 错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/assets/connection-center');
    await page.waitForTimeout(1000);
    const realErrors = errors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('fetch') &&
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('net::ERR')
    );
    expect(realErrors).toHaveLength(0);
  });
});
