import { test, expect } from '@playwright/test';
import { auth } from '../fixtures/auth';

/**
 * Smoke Test: 知识库模块
 *
 * 覆盖范围：
 * - /analytics/knowledge 主页面渲染
 * - router redirect：/knowledge → /analytics/knowledge
 *
 * 对应后端：backend/services/knowledge_base/
 */
test.describe('知识库模块', () => {

  test('访问 /analytics/knowledge 正常渲染', async ({ page }) => {
    await auth.asAdmin(page);
    await page.goto('/analytics/knowledge');
    // 页面应展示知识库相关内容（h1 或主要内容区）
    const hasContent = await page.locator('body').textContent();
    expect(hasContent && hasContent.trim().length > 0).toBe(true);
  });

  test('访问 /knowledge redirect 到 /analytics/knowledge', async ({ page }) => {
    await auth.asAdmin(page);
    await page.goto('/knowledge');
    await page.waitForURL(/\/analytics\/knowledge/, { timeout: 5000 });
    expect(page.url()).toContain('/analytics/knowledge');
  });

  test('知识库页面无 console.error', async ({ page }) => {
    await auth.asAdmin(page);
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/analytics/knowledge');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

});
