import { test, expect } from '@playwright/test';

test('Q&A 端到端: 闲聊问题也进入 Agent 回答', async ({ page }) => {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill('admin');
  await page.locator('input[type="password"]').fill('admin123');
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 8000 });
  await page.waitForTimeout(2000);

  const askbar = page.locator('textarea[data-askbar-input]');
  await askbar.fill('你好');
  await askbar.press('Enter');

  // 去掉意图识别后，闲聊也走 ReAct Engine，等待 assistant 消息渲染
  await expect(page.locator('text=木兰').first()).toBeVisible({ timeout: 90000 });
});

test('Q&A 端到端: 数据查询意图进入 Agent', async ({ page }) => {
  await page.goto('/login');
  await page.locator('input[type="text"]').fill('admin');
  await page.locator('input[type="password"]').fill('admin123');
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL('/', { timeout: 8000 });
  await page.waitForTimeout(2000);

  const askbar = page.locator('textarea[data-askbar-input]');
  await askbar.fill('你有多少个数据源');
  await askbar.press('Enter');

  // Agent 回答会出现在 MessageBubble 中（"木兰" 标识 + 回答内容）
  // 等待 "木兰" 标签出现（表示 assistant 消息已渲染）
  await expect(page.locator('text=木兰').first()).toBeVisible({ timeout: 90000 });
});
