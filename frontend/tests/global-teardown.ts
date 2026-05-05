import { request, type APIRequestContext } from '@playwright/test';

/**
 * 全局清理：跑完所有冒烟测试后，按命名前缀删除测试期间产生的资源。
 *
 * 命名约定：
 *   LLM 配置（display_name）：
 *     - 删除测试- / 删除回归测试- / 编辑测试-
 *     - MiniMax-Test-
 *     - API Key 测试 / API Key 空测试
 *     - Base URL 校验
 *   用户（username）：
 *     - smoke-user-
 *   用户组（name）：
 *     - smoke_test_group_
 *
 * 任何错误都不抛，避免影响主流程退出码。
 */
const LLM_CLEANUP_PATTERN =
  /^(删除测试-|删除回归测试-|编辑测试-|MiniMax-Test-|API Key (测试|空测试)|Base URL 校验)/;
const USER_CLEANUP_PATTERN = /^smoke-user-/;
const GROUP_CLEANUP_PATTERN = /^smoke_test_group_/;

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000';
const ADMIN_USERNAME = process.env.ADMIN_USERNAME || 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';

async function cleanupLLMConfigs(ctx: APIRequestContext): Promise<void> {
  const listResp = await ctx.get('/api/llm/configs');
  if (!listResp.ok()) {
    console.warn(`[teardown] list LLM configs failed: ${listResp.status()}`);
    return;
  }
  const data = await listResp.json();
  const configs: Array<{ id: number; display_name?: string }> =
    data?.configs ?? [];
  const targets = configs.filter(
    (c) => c.display_name && LLM_CLEANUP_PATTERN.test(c.display_name),
  );
  if (targets.length === 0) {
    console.log('[teardown] no LLM test data to cleanup');
    return;
  }
  let deleted = 0;
  for (const cfg of targets) {
    const resp = await ctx.delete(`/api/llm/configs/${cfg.id}`);
    if (resp.ok()) deleted += 1;
    else
      console.warn(
        `[teardown] delete LLM id=${cfg.id} (${cfg.display_name}) failed: ${resp.status()}`,
      );
  }
  console.log(`[teardown] cleaned ${deleted}/${targets.length} test LLM configs`);
}

async function cleanupUsers(ctx: APIRequestContext): Promise<void> {
  const listResp = await ctx.get('/api/users/');
  if (!listResp.ok()) {
    console.warn(`[teardown] list users failed: ${listResp.status()}`);
    return;
  }
  const data = await listResp.json();
  const users: Array<{ id: number; username?: string }> =
    Array.isArray(data) ? data : data?.users ?? [];
  const targets = users.filter(
    (u) => u.username && USER_CLEANUP_PATTERN.test(u.username),
  );
  if (targets.length === 0) {
    console.log('[teardown] no user test data to cleanup');
    return;
  }
  let deleted = 0;
  for (const u of targets) {
    const resp = await ctx.delete(`/api/users/${u.id}`);
    if (resp.ok()) deleted += 1;
    else
      console.warn(
        `[teardown] delete user id=${u.id} (${u.username}) failed: ${resp.status()}`,
      );
  }
  console.log(`[teardown] cleaned ${deleted}/${targets.length} test users`);
}

async function cleanupGroups(ctx: APIRequestContext): Promise<void> {
  const listResp = await ctx.get('/api/groups/');
  if (!listResp.ok()) {
    console.warn(`[teardown] list groups failed: ${listResp.status()}`);
    return;
  }
  const data = await listResp.json();
  const groups: Array<{ id: number; name?: string }> =
    Array.isArray(data) ? data : data?.groups ?? [];
  const targets = groups.filter(
    (g) => g.name && GROUP_CLEANUP_PATTERN.test(g.name),
  );
  if (targets.length === 0) {
    console.log('[teardown] no group test data to cleanup');
    return;
  }
  let deleted = 0;
  for (const g of targets) {
    const resp = await ctx.delete(`/api/groups/${g.id}`);
    if (resp.ok()) deleted += 1;
    else
      console.warn(
        `[teardown] delete group id=${g.id} (${g.name}) failed: ${resp.status()}`,
      );
  }
  console.log(`[teardown] cleaned ${deleted}/${targets.length} test groups`);
}

export default async function globalTeardown() {
  const ctx = await request.newContext({ baseURL: BACKEND });
  try {
    const login = await ctx.post('/api/auth/login', {
      data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
    });
    if (!login.ok()) {
      console.warn(`[teardown] login failed: ${login.status()}`);
      return;
    }
    await cleanupLLMConfigs(ctx);
    await cleanupUsers(ctx);
    await cleanupGroups(ctx);
  } catch (e) {
    console.warn('[teardown] error:', e);
  } finally {
    await ctx.dispose();
  }
}
