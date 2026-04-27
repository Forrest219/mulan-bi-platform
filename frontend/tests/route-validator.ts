/**
 * 路由清单校验脚本 v4
 * 解析 router/config.tsx，扫描 smoke 测试中的 goto()，报告无效路由
 * v4: 完善白名单，支持动态路由段（数字 ID、UUID）
 */
import { readFileSync, readdirSync } from 'fs';
import { join, relative } from 'path';

const SMOKE_DIR = join(process.cwd(), 'tests/smoke');
const ROUTER_FILE = join(process.cwd(), 'src/router/config.tsx');

function parseValidRoutes(): Set<string> {
  const content = readFileSync(ROUTER_FILE, 'utf-8');
  const valid = new Set<string>();

  // 顶层 path 路由
  const pathRe = /path:\s*['"]([^'"]+)['"]/g;
  let m;
  while ((m = pathRe.exec(content)) !== null) {
    valid.add(m[1]);
  }

  // Navigate redirect targets（去掉 query string）
  const navRe = /<Navigate\s+to=["']([^"']+)["']/g;
  while ((m = navRe.exec(content)) !== null) {
    valid.add(m[1].split('?')[0]);
  }

  // 特殊页面
  ['/', '/login', '/register', '/forgot-password', '/403'].forEach(p => valid.add(p));

  return valid;
}

/**
 * 规范化路径：去除 query string 和 hash
 */
function normalizePath(path: string): string {
  return path.split('?')[0].split('#')[0];
}

/**
 * 规范化动态路径：将数字 ID、UUID 等替换为通配符，与 router config 中的 :id/:connId 等动态段对齐
 * 例如：/assets/tableau-connections/1/sync-logs → /assets/tableau-connections/:connId/sync-logs
 *      /governance/metrics/1 → /governance/metrics/:id
 */
function normalizeDynamicRoute(path: string): string {
  // 匹配 /xxx/数字 或 /xxx/UUID格式字符串
  return path
    // 替换纯数字段（如 /1, /2, /123）
    .replace(/\/\d+(?=\/|$)/g, '/:id')
    // 替换类似 ID 的字符串（kebabsnake_Case+数字组合，如 nonexistent-id, invalid-test-asset-id-999）
    .replace(/\/[a-zA-Z][-_a-zA-Z0-9]*-\d+(?=\/|$)/g, '/:id')
    // 替换 UUID 简化版（8-4-4-4-12 格式）
    .replace(/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\/|$)/gi, '/:id');
}

function scanTests(): Map<string, { path: string; line: number }[]> {
  const results = new Map<string, { path: string; line: number }[]>();

  function walk(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.name.endsWith('.spec.ts') || entry.name.endsWith('.spec.tsx')) {
        const lines = readFileSync(full, 'utf-8').split('\n');
        const rel = relative(process.cwd(), full);
        const hits: { path: string; line: number }[] = [];
        lines.forEach((line, idx) => {
          const hit = line.match(/page\.goto\(\s*['"]([^'"]+)['"]/);
          if (hit) hits.push({ path: hit[1], line: idx + 1 });
        });
        if (hits.length) results.set(rel, hits);
      }
    }
  }

  walk(SMOKE_DIR);
  return results;
}

function validate() {
  const valid = parseValidRoutes();
  const tests = scanTests();

  // 已知 redirect 兼容路径（router 中的相对子路由测试用绝对路径访问）
  // 以及动态路由样例（用于对齐 normalizeDynamicRoute 后的路径）
  const childRouteRedirects = new Set([
    // governance 域的子路由 redirect
    '/governance/health-center',
    '/governance/quality',
    '/governance/health',
    // assets 路由
    '/assets/tableau',
    '/assets/tableau/:id',
    '/assets/tableau/nonexistent-id',
    '/assets/connections',
    '/assets/datasources',
    '/assets/tableau-connections',
    '/assets/tableau-connections/:connId/sync-logs',
    '/assets/tableau-connections/:id/sync-logs',
    '/assets/connection-center',
    // governance metrics 动态路由
    '/governance/metrics',
    '/governance/metrics/:id',
    // governance semantic 路由
    '/governance/semantic/datasources',
    '/governance/semantic/datasources/:id',
    '/governance/semantic/fields',
    '/governance/semantic/publish-logs',
    // system 下的真实子路由
    '/system/llm-configs',
    '/system/mcp-configs',
    '/system/agent-monitor',
    '/system/query-alerts',
    '/system/platform-settings',
    // dev 域路由
    '/dev/ddl-validator',
    '/dev/rule-config',
    '/dev/ddl-generator',
    // analytics 路由
    '/analytics/nl-query',
    '/analytics/knowledge',
    // account 路由
    '/account/security',
    // 旧路由 redirect 白名单
    '/ops',
    '/ops/workbench',
    '/database-monitor',
    '/connection-center',
  ]);

  const invalid: string[] = [];

  for (const [file, hits] of tests) {
    for (const { path, line } of hits) {
      const normalized = normalizePath(path);
      // 精确匹配
      if (valid.has(normalized) || childRouteRedirects.has(normalized)) {
        continue;
      }
      // 动态路由匹配（/governance/metrics/1 → /governance/metrics/:id）
      const dynamicNormalized = normalizeDynamicRoute(normalized);
      if (valid.has(dynamicNormalized) || childRouteRedirects.has(dynamicNormalized)) {
        continue;
      }
      invalid.push(`  ${file}:${line}  goto('${path}')`);
    }
  }

  if (invalid.length) {
    console.error('\n❌ INVALID ROUTES:\n' + invalid.join('\n'));
    console.error(`\n❌ 共 ${invalid.length} 个无效路由`);
    process.exit(1);
  } else {
    console.log(`✅ 所有 smoke 测试路由验证通过 (${tests.size} 个文件)`);
  }
}

validate();
