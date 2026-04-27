import { test, expect, Page } from '@playwright/test';

const ADMIN_USER = 'admin';
const ADMIN_PASS = 'admin123';

async function login(page: Page, baseUrl: string) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' });
  await page.getByPlaceholder('用户名').fill(ADMIN_USER);
  await page.getByPlaceholder('密码').fill(ADMIN_PASS);
  await page.getByRole('button', { name: '登录' }).click();
  await page.waitForURL(`${baseUrl}/**`, { timeout: 10000 });
  await page.waitForTimeout(1500);
}

test('debug mcp debugger network', async ({ page }) => {
  const baseUrl = process.env.BASE_URL ?? 'http://localhost:5173';

  // capture all requests/responses
  const fetchedUrls: string[] = [];
  page.on('response', async (resp) => {
    if (resp.url().includes('tableau-mcp')) {
      fetchedUrls.push(`${resp.status()} ${resp.url()}`);
    }
  });

  await login(page, baseUrl);
  await page.goto(`${baseUrl}/system/mcp-debugger`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000); // wait for tools to load

  console.log('Fetched URLs:', JSON.stringify(fetchedUrls));

  // Check what's on the page
  const bodyText = await page.locator('body').innerText();
  console.log('Page text snippet:', bodyText.slice(0, 500));
});
