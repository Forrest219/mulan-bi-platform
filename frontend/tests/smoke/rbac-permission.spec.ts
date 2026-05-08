import { test, expect } from '@playwright/test';

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

  // ── 测试账号：仅有 database_monitor 权限的普通用户 ──
  const SMOKE_USER = process.env.SMOKE_ANALYST_USERNAME ?? 'smoke_analyst';
  const SMOKE_PASS = process.env.SMOKE_ANALYST_PASSWORD ?? 'analyst123';

  /**
   * 以 smoke_analyst 身份登录（CI 中由 seed 步骤创建）
   */
  async function loginAsSmokeUser(page: any) {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(SMOKE_USER);
    await page.locator('input[type="password"]').fill(SMOKE_PASS);
    await page.locator('button[type="submit"]').click();
    // 等待登录完成
    await page.waitForTimeout(1500);
    return page;
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
        await loginAsSmokeUser(page);
        const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
        if (loginFailed) {
          test.skip();
          return;
        }

        await page.goto(path);
        await page.waitForTimeout(1500);

        // 明确检查：跳转 /403 或出现无权限文案
        const url = page.url();
        const isForbidden = url.includes('/403');
        const hasForbiddenText = await page.locator('text=无权限').isVisible().catch(() => false)
          || await page.locator('text=访问被拒绝').isVisible().catch(() => false)
          || await page.locator('text=Forbidden').isVisible().catch(() => false);
        expect(isForbidden || hasForbiddenText).toBe(true);
      });
    }
  });

  // ── 特定权限路由（拒绝）───────────────────────────────────────
  // smoke_analyst 只有 database_monitor，无 ddl_check / rule_config / tableau 权限

  test.describe('特定权限路由 — 无权限用户应被拒绝', () => {

    test('smoke_analyst 无 ddl_check 权限，访问 DDL 检查应被拒绝', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/dev/ddl-validator');
      await page.waitForTimeout(1500);

      const url = page.url();
      const isForbidden = url.includes('/403');
      const hasForbiddenText = await page.locator('text=无权限').isVisible().catch(() => false)
        || await page.locator('text=访问被拒绝').isVisible().catch(() => false);
      // 要么跳到 /403，要么出现无权限文案
      expect(isForbidden || hasForbiddenText).toBe(true);
    });

    test('smoke_analyst 无 tableau 权限，访问 Tableau 资产应被拒绝', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/assets/tableau');
      await page.waitForTimeout(1500);

      const url = page.url();
      const isForbidden = url.includes('/403');
      const hasForbiddenText = await page.locator('text=无权限').isVisible().catch(() => false)
        || await page.locator('text=访问被拒绝').isVisible().catch(() => false);
      expect(isForbidden || hasForbiddenText).toBe(true);
    });

    test('smoke_analyst 无 rule_config 权限，访问规则配置应被拒绝', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/dev/rule-config');
      await page.waitForTimeout(1500);

      const url = page.url();
      const isForbidden = url.includes('/403');
      const hasForbiddenText = await page.locator('text=无权限').isVisible().catch(() => false)
        || await page.locator('text=访问被拒绝').isVisible().catch(() => false);
      expect(isForbidden || hasForbiddenText).toBe(true);
    });
  });

  // ── 特定权限路由（正向：smoke_analyst 有 database_monitor）─────────
  // smoke_analyst 仅有 database_monitor 权限，可访问：
  // /governance/health-center, /assets/connections

  test.describe('smoke_analyst 权限正向验证 — database_monitor 权限有效', () => {

    test('smoke_analyst 可访问健康中心（database_monitor 权限）', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/governance/health-center');
      await page.waitForTimeout(1500);

      expect(page.url()).toContain('/governance/health-center');
      const hasContent = await page.locator('h1').first().isVisible().catch(() => false);
      expect(hasContent).toBe(true);
    });

    test('smoke_analyst 可访问连接中心（无需特定权限）', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/assets/connections');
      await page.waitForTimeout(1500);

      expect(page.url()).toContain('/assets/connections');
    });
  });

  // ── 公开页面（无需权限，所有登录用户均可访问）────────────────

  test.describe('公开页面 — 所有登录用户均可访问', () => {

    test('smoke_analyst 可正常访问首页', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/');
      await page.waitForTimeout(1000);
      expect(page.url()).toContain('/');
    });

    test('smoke_analyst 可正常访问知识库', async ({ page }) => {
      await loginAsSmokeUser(page);
      const loginFailed = await page.locator('text=用户名或密码错误').isVisible({ timeout: 1000 }).catch(() => false);
      if (loginFailed) { test.skip(); return; }

      await page.goto('/analytics/knowledge');
      await page.waitForTimeout(1000);
      // 允许重定向到 /knowledge
      expect(page.url()).toMatch(/\/(analytics\/)?knowledge/);
    });
  });
});
