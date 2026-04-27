import { test, expect, type Page } from '@playwright/test';
import { auth } from '../fixtures/auth';

/**
 * Smoke Test: 权限重定向
 *
 * 验证所有受保护路由的权限检查行为：
 * 1. 未登录 → 跳转登录页
 * 2. 已登录但无权限 → 跳转 /403 或显示无权限
 * 3. 已登录且有权限 → 正常访问
 * 4. 公开页面 → 登录用户均可访问
 *
 * 路由权限参考：frontend/src/router/config.tsx
 *
 * 测试账号（由 seed 步骤在 CI 中创建）：
 *   smoke_analyst / analyst123 — 仅拥有 database_monitor 权限
 *   SMOKE_ADMIN_USERNAME / SMOKE_ADMIN_PASSWORD — admin 角色（所有权限）
 */
test.describe('权限重定向', () => {

  // ── 权限拒绝断言 ────────────────────────────────────────────
  /**
   * 检查 page 是否表现出"无权限"状态：
   * - URL 包含 /403，或
   * - 页面包含"无权限"/"访问被拒绝"/"Forbidden"文案
   */
  async function expectForbidden(page: Page) {
    const forbiddenText = page.getByText(/权限不足|无权限|访问被拒绝|Forbidden/).first();

    await Promise.race([
      page.waitForURL(/\/403(?:$|[?#])/, { timeout: 5000 }),
      forbiddenText.waitFor({ state: 'visible', timeout: 5000 }),
    ]).catch(() => {
      // Fall through to the explicit assertions below for a clearer failure.
    });

    if (/\/403(?:$|[?#])/.test(page.url())) {
      await expect(page).toHaveURL(/\/403(?:$|[?#])/);
      return;
    }

    await expect(forbiddenText).toBeVisible();
  }

  // ══════════════════════════════════════════════════════════════
  // 1. 未登录 → 跳转登录页（所有受保护路由）
  // ══════════════════════════════════════════════════════════════

  test.describe('未登录状态 — 应跳转到 /login', () => {

    const protectedPages = [
      // dev 前缀路由（router config 中在 /dev 下）
      { path: '/dev/ddl-validator',   name: 'DDL 检查',       permission: 'ddl_check' },
      { path: '/dev/rule-config',     name: '规则配置',       permission: 'rule_config' },
      { path: '/governance/health-center', name: '健康中心',       permission: 'database_monitor' },
      // tableau 语义层路由
      { path: '/governance/semantic/datasources', name: '语义数据源列表', permission: 'tableau' },
      // system admin 路由
      { path: '/system/users',         name: '用户管理',       permission: 'adminOnly' },
      { path: '/system/groups',         name: '用户组',         permission: 'adminOnly' },
      { path: '/system/permissions',    name: '权限总览',       permission: 'adminOnly' },
      { path: '/system/tasks',          name: '任务管理',       permission: 'adminOnly' },
      { path: '/system/activity',       name: '操作日志',       permission: 'adminOnly' },
    ];

    for (const { path, name } of protectedPages) {
      test(`${name} (${path}) 未登录时应跳转到 /login`, async ({ page }) => {
        await page.goto(path);
        await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
      });
    }
  });

  // ══════════════════════════════════════════════════════════════
  // 2. 已登录但无权限 → 应被拒绝（403 或无权限文案）
  // ══════════════════════════════════════════════════════════════

  test.describe('smoke_analyst 登录后 — 无权限路由应被拒绝', () => {

    test('访问 DDL 检查（需 ddl_check 权限）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);
      await page.goto('/dev/ddl-validator');
      await expectForbidden(page);
    });

    test('访问规则配置（需 rule_config 权限）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/dev/rule-config');
      await expectForbidden(page);
    });

    test('访问语义数据源（需 tableau 权限）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/governance/semantic/datasources');
      await expectForbidden(page);
    });

    test('访问用户管理（adminOnly）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/system/users');
      await expectForbidden(page);
    });

    test('访问用户组（adminOnly）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/system/groups');
      await expectForbidden(page);
    });

    test('访问权限总览（adminOnly）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/system/permissions');
      await expectForbidden(page);
    });

    test('访问任务管理（adminOnly）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/system/tasks');
      await expectForbidden(page);
    });

    test('访问操作日志（adminOnly）应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/system/activity');
      await expectForbidden(page);
    });
  });

  // ══════════════════════════════════════════════════════════════
  // 3. 已登录且有对应权限 → 正常访问
  // ══════════════════════════════════════════════════════════════

  test.describe('smoke_analyst 登录后 — 有权限路由应正常访问', () => {

    test('可访问健康中心（database_monitor 权限）', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/governance/health-center');

      await expect(page).toHaveURL(/\/governance\/health-center(?:$|[?#])/);
      await expect(page.locator('h1').first()).toBeVisible();
    });
  });

  test.describe('admin 登录后 — 所有受保护路由均应正常访问', () => {

    test('admin 可访问 DDL 检查', async ({ page }) => {
      await auth.asAdmin(page);

      await page.goto('/dev/ddl-validator');
      await expect(page).toHaveURL(/\/dev\/ddl-validator(?:$|[?#])/);
    });

    test('admin 可访问规则配置', async ({ page }) => {
      await auth.asAdmin(page);

      await page.goto('/dev/rule-config');
      await expect(page).toHaveURL(/\/dev\/rule-config(?:$|[?#])/);
    });

    test('admin 可访问语义数据源', async ({ page }) => {
      await auth.asAdmin(page);

      await page.goto('/governance/semantic/datasources');
      await expect(page).toHaveURL(/\/governance\/semantic\/datasources(?:$|[?#])/);
    });

    test('admin 可访问用户管理', async ({ page }) => {
      await auth.asAdmin(page);

      await page.goto('/system/users');
      await expect(page).toHaveURL(/\/system\/users(?:$|[?#])/);
    });

    test('admin 可访问用户组', async ({ page }) => {
      await auth.asAdmin(page);

      await page.goto('/system/groups');
      await expect(page).toHaveURL(/\/system\/groups(?:$|[?#])/);
    });
  });

  // ══════════════════════════════════════════════════════════════
  // 4. 公开页面（无需特定权限，登录用户均可访问）
  // ══════════════════════════════════════════════════════════════

  test.describe('公开页面 — 所有登录用户均可访问', () => {

    test('smoke_analyst 可正常访问首页', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/');
      await expect(page).toHaveURL(/\/(?:$|[?#])/);
    });

    test('smoke_analyst 可正常访问知识库', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/analytics/knowledge');
      await expect(page).toHaveURL(/\/(analytics\/)?knowledge(?:$|[?#])/);
    });

    test('admin 可正常访问首页', async ({ page }) => {
      await auth.asAdmin(page);

      await page.goto('/');
      await expect(page).toHaveURL(/\/(?:$|[?#])/);
    });
  });

  // ══════════════════════════════════════════════════════════════
  // 5. 登录页本身 — 已登录用户访问应跳转首页
  // ══════════════════════════════════════════════════════════════

  test.describe('已登录用户访问 /login — 应跳转首页', () => {

    test('smoke_analyst 访问 /login 应跳转到首页（而非停留在登录页）', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/login');
      // 已登录状态下访问 login 应重定向到首页，而非停留在 /login
      await expect(page).toHaveURL(/\/(?:$|[?#])/);
    });
  });

});
