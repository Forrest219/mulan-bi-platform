const { chromium } = require('playwright');

const PAGES = [
  '/login',
  '/register',
  '/home',
  '/ddl-validator',
  '/rule-config',
  '/database-monitor',
  '/tableau/assets',
  '/tableau/connections',
  '/tableau/health',
  '/tableau/sync-logs',
  '/tableau/asset-detail',
  '/semantic-maintenance/field-list',
  '/semantic-maintenance/datasource-list',
  '/semantic-maintenance/datasource-detail',
  '/data-governance/quality',
  '/data-governance/health',
  '/knowledge',
  '/admin/datasources',
  '/admin/tasks',
  '/admin/llm',
  '/admin/activity',
  '/admin/groups',
  '/admin/permissions',
  '/admin/user-management',
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });
  const page = await context.newPage();

  const fs = require('fs');
  if (!fs.existsSync('screenshots')) {
    fs.mkdirSync('screenshots');
  }

  for (const p of PAGES) {
    const filename = 'screenshots' + p.replace(/\//g, '_') + '.png';
    console.log(`Capturing: ${p} -> ${filename}`);
    try {
      await page.goto('http://localhost:3000' + p, { timeout: 15000 });
      await page.waitForLoadState('networkidle', { timeout: 10000 });
      await page.screenshot({ path: filename, fullPage: false });
      console.log(`  OK: ${filename}`);
    } catch (e) {
      console.error(`  FAILED: ${e.message}`);
    }
  }

  await browser.close();
  console.log('Done!');
})();
