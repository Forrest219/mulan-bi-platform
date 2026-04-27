import { test, expect, type Page } from '@playwright/test';
import { auth } from '../fixtures/auth';

/**
 * Smoke Test: RBAC 权限隔离
 *
 * 验证非管理员用户无法访问受保护页面，
 * 防止权限配置退化。
 *
 * 路由权限参考：frontend/src/router/config.tsx
 *
 * 注意：使用 role=user + 仅分配 database_monitor 权限的账号，
 * 因为 role=analyst 默认包含 scan_logs + tableau 权限，
 * 与"analyst 无 tableau 权限"测试冲突。
 */
test.describe('RBAC 权限隔离', () => {
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

  // ── adminOnly 页面 ────────────────────────────────────────────
  // router/config.tsx 中 adminOnly 的页面（共 7 个）：
  // /system/users, /system/groups, /system/permissions,
  // /system/tasks, /system/activity,
  // /system/llm-configs, /system/mcp-configs

  test.describe('adminOnly 页面 — smoke_analyst 应被拒绝', () => {

    const adminOnlyPages = [
      { path: '/system/users',        name: '用户管理' },
      { path: '/system/groups',        name: '用户组' },
      { path: '/system/permissions',   name: '权限总览' },
      { path: '/system/tasks',        name: '任务管理' },
      { path: '/system/activity',     name: '操作日志' },
      { path: '/system/llm-configs',  name: 'LLM 配置' },
      { path: '/system/mcp-configs',   name: 'MCP 配置' },
    ];

    for (const { path, name } of adminOnlyPages) {
      test(`${name} (${path}) — 未登录应跳转登录页`, async ({ page }) => {
        await page.goto(path);
        await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
      });

      test(`${name} (${path}) — smoke_analyst 登录后应被拒绝访问（跳转 /403 或显示无权限）`, async ({ page }) => {
        await auth.asAnalyst(page);

        await page.goto(path);
        await expectForbidden(page);
      });
    }
  });

  // ── 特定权限路由（拒绝）───────────────────────────────────────
  // smoke_analyst 只有 database_monitor，无 ddl_check / rule_config / tableau 权限

  test.describe('特定权限路由 — 无权限用户应被拒绝', () => {

    test('smoke_analyst 无 ddl_check 权限，访问 DDL 检查应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/dev/ddl-validator');
      await expectForbidden(page);
    });

    test('smoke_analyst 无 tableau 权限，访问 Tableau 资产应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/assets/tableau');
      await expectForbidden(page);
    });

    test('smoke_analyst 无 rule_config 权限，访问规则配置应被拒绝', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/dev/rule-config');
      await expectForbidden(page);
    });
  });

  // ── 特定权限路由（正向：smoke_analyst 有 database_monitor）─────────
  // smoke_analyst 仅有 database_monitor 权限，可访问：
  // /governance/health-center, /assets/connections

  test.describe('smoke_analyst 权限正向验证 — database_monitor 权限有效', () => {

    test('smoke_analyst 可访问健康中心（database_monitor 权限）', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/governance/health-center');

      await expect(page).toHaveURL(/\/governance\/health-center(?:$|[?#])/);
      await expect(page.locator('h1').first()).toBeVisible();
    });

    test('smoke_analyst 可访问连接中心（无需特定权限）', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/assets/connections');

      await expect(page).toHaveURL(/\/assets\/connections(?:$|[?#])/);
    });
  });

  // ── 公开页面（无需权限，所有登录用户均可访问）────────────────

  test.describe('公开页面 — 所有登录用户均可访问', () => {

    test('smoke_analyst 可正常访问首页', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/');
      await expect(page).toHaveURL(/\/(?:$|[?#])/);
    });

    test('smoke_analyst 可正常访问知识库', async ({ page }) => {
      await auth.asAnalyst(page);

      await page.goto('/analytics/knowledge');
      // 允许重定向到 /knowledge
      await expect(page).toHaveURL(/\/(analytics\/)?knowledge(?:$|[?#])/);
    });
  });
});
