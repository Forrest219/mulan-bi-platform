const { chromium } = require('playwright');

const BASE_URL = 'http://localhost:3000';
const API_BASE = 'http://localhost:8000';
const LOGIN_URL = `${BASE_URL}/login`;
const LOGIN_USERNAME = 'admin';
const LOGIN_PASSWORD = 'admin123';

const PAGES = [
  { path: '/home', title: '首页' },
  { path: '/ddl-validator', title: 'DDL 校验' },
  { path: '/rule-config', title: '规则配置' },
  { path: '/database-monitor', title: '数据库监控' },
  { path: '/tableau/assets', title: 'Tableau 资产' },
  { path: '/tableau/connections', title: 'Tableau 连接' },
  { path: '/tableau/health', title: 'Tableau 健康' },
  { path: '/tableau/sync-logs', title: 'Tableau 同步日志' },
  { path: '/semantic-maintenance/field-list', title: '语义维护-字段列表' },
  { path: '/semantic-maintenance/datasource-list', title: '语义维护-数据源列表' },
  { path: '/semantic-maintenance/datasource-detail', title: '语义维护-数据源详情' },
  { path: '/data-governance/quality', title: '数据治理-质量' },
  { path: '/data-governance/health', title: '数据治理-健康' },
  { path: '/knowledge', title: '知识库' },
  { path: '/admin/datasources', title: '管理后台-数据源' },
  { path: '/admin/tasks', title: '管理后台-任务' },
  { path: '/admin/llm', title: '管理后台-LLM配置' },
  { path: '/admin/activity', title: '管理后台-活动日志' },
  { path: '/admin/groups', title: '管理后台-用户组' },
  { path: '/admin/permissions', title: '管理后台-权限' },
  { path: '/admin/user-management', title: '管理后台-用户管理' },
];

const OUTPUT_DIR = 'screenshots-auth';

(async () => {
  const fs = require('fs');
  const path = require('path');
  const startTime = Date.now();

  // Ensure output directory exists
  const outputPath = path.join(__dirname, OUTPUT_DIR);
  if (!fs.existsSync(outputPath)) {
    fs.mkdirSync(outputPath, { recursive: true });
  }

  const manifest = {
    version: '1.0',
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    viewport: { width: 1920, height: 1080 },
    login: { username: LOGIN_USERNAME, apiBase: API_BASE },
    pages: [],
    summary: { total: 0, success: 0, failed: 0 },
    duration: 0,
  };

  console.log('🚀 Starting screenshot capture with authentication...\n');

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();

  // Inject CSS to hide scrollbars globally
  await page.addInitScript(() => {
    const style = document.createElement('style');
    style.textContent = `
      * {
        overflow: hidden !important;
        scrollbar-width: none !important;
        -ms-overflow-style: none !important;
      }
      html {
        scrollbar-width: none !important;
      }
      body {
        overflow: hidden !important;
      }
    `;
    document.head.appendChild(style);
  });

  // Step 1: Login
  console.log('📝 Step 1: Logging in...');
  try {
    await page.goto(LOGIN_URL, { timeout: 20000 });
    await page.waitForLoadState('domcontentloaded', { timeout: 15000 });

    // Wait for React to hydrate
    await page.waitForTimeout(2000);

    // Wait for input fields to be visible
    await page.waitForSelector('input', { timeout: 10000 });

    // Fill login form with explicit waits
    const usernameInput = page.locator('input[id="username"]');
    const passwordInput = page.locator('input[id="password"]');
    const submitButton = page.locator('button[type="submit"]');

    await usernameInput.waitFor({ state: 'visible', timeout: 10000 });
    await usernameInput.fill(LOGIN_USERNAME);

    await passwordInput.waitFor({ state: 'visible', timeout: 10000 });
    await passwordInput.fill(LOGIN_PASSWORD);

    await submitButton.waitFor({ state: 'visible', timeout: 10000 });

    // Click and wait for network
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => null),
      submitButton.click(),
    ]);

    // Additional wait for React state update
    await page.waitForTimeout(3000);

    const currentUrl = page.url();
    console.log(`   Current URL after login: ${currentUrl}`);

    // Check if login failed - look for error messages
    const errorSelector = page.locator('[class*="red"], [class*="error"], [class*="alert"]').first();
    const errorText = await errorSelector.textContent().catch(() => null);

    if (currentUrl.includes('/login') || errorText) {
      console.error(`   ❌ Login failed! Error: ${errorText || 'Redirect did not occur'}`);
      console.error('   Saving error screenshot and HTML...');

      const errorFilename = path.join(outputPath, 'LOGIN_ERROR.png');
      await page.screenshot({ path: errorFilename, fullPage: false });

      const errorHtmlPath = path.join(outputPath, 'LOGIN_ERROR.html');
      const htmlContent = await page.content();
      fs.writeFileSync(errorHtmlPath, htmlContent);

      manifest.loginError = {
        screenshot: errorFilename,
        htmlFile: errorHtmlPath,
        errorMessage: errorText || 'Login did not redirect',
        url: currentUrl,
      };

      console.error(`   Saved screenshot: ${errorFilename}`);
      console.error(`   Saved HTML: ${errorHtmlPath}`);
      await browser.close();
      process.exit(1);
    }

    console.log('   ✅ Login successful!\n');
  } catch (err) {
    console.error(`   ❌ Login error: ${err.message}`);
    const errorFilename = path.join(outputPath, 'LOGIN_ERROR.png');
    await page.screenshot({ path: errorFilename, fullPage: false }).catch(() => {});
    manifest.loginError = { screenshot: errorFilename, error: err.message };
    await browser.close();
    process.exit(1);
  }

  // Step 2: Capture screenshots
  console.log('📸 Step 2: Capturing screenshots...\n');

  for (const pageInfo of PAGES) {
    const pageStartTime = Date.now();
    const filename = path.join(outputPath, pageInfo.path.replace(/\//g, '_') + '.png');

    try {
      console.log(`   Capturing: ${pageInfo.path} (${pageInfo.title})`);

      await page.goto(BASE_URL + pageInfo.path, { timeout: 20000, waitUntil: 'domcontentloaded' });

      // Wait for page to fully hydrate
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => null);

      // Wait 2s for animations to complete (Gemini friendly)
      await page.waitForTimeout(2000);

      // Force hide scrollbars again after navigation
      await page.evaluate(() => {
        document.body.style.overflow = 'hidden';
        document.documentElement.style.overflow = 'hidden';
      });

      await page.screenshot({ path: filename, fullPage: false });

      const pageDuration = Date.now() - pageStartTime;

      manifest.pages.push({
        route: pageInfo.path,
        title: pageInfo.title,
        screenshot: filename,
        status: 'success',
        duration: pageDuration,
      });

      manifest.summary.success++;
      console.log(`   ✅ OK: ${filename} (${pageDuration}ms)\n`);
    } catch (err) {
      const pageDuration = Date.now() - pageStartTime;

      manifest.pages.push({
        route: pageInfo.path,
        title: pageInfo.title,
        screenshot: null,
        status: 'failed',
        error: err.message,
        duration: pageDuration,
      });

      manifest.summary.failed++;
      console.error(`   ❌ FAILED: ${pageInfo.path} - ${err.message}\n`);
    }
  }

  manifest.summary.total = PAGES.length;
  manifest.duration = Date.now() - startTime;

  // Save manifest
  const manifestPath = path.join(outputPath, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log(`📄 Manifest saved: ${manifestPath}`);

  // Summary
  console.log('\n========== SUMMARY ==========');
  console.log(`Total pages: ${manifest.summary.total}`);
  console.log(`Success: ${manifest.summary.success}`);
  console.log(`Failed: ${manifest.summary.failed}`);
  console.log(`Duration: ${manifest.duration}ms`);
  console.log('=============================\n');

  await browser.close();
  console.log('🏁 Done!');
})();
