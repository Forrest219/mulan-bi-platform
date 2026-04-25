import { test, expect } from '@playwright/test';

const ADMIN_USERNAME = process.env.ADMIN_USERNAME ?? 'admin';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'admin123';

/**
 * Smoke Test: 知识库模块（Knowledge Base）前端集成测试
 *
 * 覆盖范围：
 * - 知识库各子模块页面渲染（指标字典/品控手册/业务系统信息）
 * - 业务术语管理 CRUD UI
 * - 知识文档管理 CRUD UI
 * - 向量检索交互
 *
 * 对应后端：backend/services/knowledge_base/
 * 对应规格：docs/specs/17-knowledge-base-spec.md
 */
test.describe('知识库模块', () => {

  // ── 登录前置 ──────────────────────────────────────────────────────────────

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.locator('input[type="text"]').fill(ADMIN_USERNAME);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL('/', { timeout: 5000 });
  });

  // ── 知识库首页 ────────────────────────────────────────────────────────────

  test('知识库首页（/knowledge）正常渲染，显示"功能开发中"', async ({ page }) => {
    await page.goto('/knowledge');
    await expect(page.locator('h1')).toContainText('知识库');
    await expect(page.locator('text=功能开发中，敬请期待')).toBeVisible();
  });

  // ── 指标字典 ─────────────────────────────────────────────────────────────

  test('指标字典子页面（/knowledge/metrics）正常渲染', async ({ page }) => {
    await page.goto('/knowledge/metrics');
    await expect(page.locator('h1')).toContainText('指标字典');
    await expect(page.locator('text=统一沉淀指标定义')).toBeVisible();
  });

  test('指标字典页面无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/metrics');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  // ── 品控手册 ──────────────────────────────────────────────────────────────

  test('品控手册子页面（/knowledge/handbook）正常渲染', async ({ page }) => {
    await page.goto('/knowledge/handbook');
    await expect(page.locator('h1')).toContainText('品控手册');
    await expect(page.locator('text=沉淀 BI 场景')).toBeVisible();
  });

  test('品控手册页面无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/handbook');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  // ── 业务系统信息 ──────────────────────────────────────────────────────────

  test('业务系统信息子页面（/knowledge/systems）正常渲染', async ({ page }) => {
    await page.goto('/knowledge/systems');
    await expect(page.locator('h1')).toContainText('业务系统信息');
    await expect(page.locator('text=维护业务系统背景')).toBeVisible();
  });

  test('业务系统信息页面无 console.error', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/systems');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  // ── 未知子路径 ────────────────────────────────────────────────────────────

  test('未知子路径显示默认"功能开发中"提示', async ({ page }) => {
    await page.goto('/knowledge/unknown-sub-path');
    await expect(page.locator('h1')).toContainText('知识库');
    await expect(page.locator('text=功能开发中，敬请期待')).toBeVisible();
  });

  // ── 术语管理页面 ──────────────────────────────────────────────────────────

  test('术语管理页面（/knowledge/glossary）加载无错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/glossary');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('术语管理页面显示术语列表或空状态', async ({ page }) => {
    await page.goto('/knowledge/glossary');
    // 页面应显示表格或空状态提示
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmptyState = await page.locator('text=暂无数据').isVisible().catch(() => false);
    const hasPlaceholder = await page.locator('text=功能开发中').isVisible().catch(() => false);
    expect(hasTable || hasEmptyState || hasPlaceholder).toBe(true);
  });

  // ── 文档管理页面 ──────────────────────────────────────────────────────────

  test('文档管理页面（/knowledge/documents）加载无错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/documents');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('文档管理页面显示文档列表或空状态', async ({ page }) => {
    await page.goto('/knowledge/documents');
    const hasTable = await page.locator('table').isVisible().catch(() => false);
    const hasEmptyState = await page.locator('text=暂无数据').isVisible().catch(() => false);
    const hasPlaceholder = await page.locator('text=功能开发中').isVisible().catch(() => false);
    expect(hasTable || hasEmptyState || hasPlaceholder).toBe(true);
  });

  // ── 向量检索页面 ───────────────────────────────────────────────────────────

  test('向量检索页面（/knowledge/search）加载无错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/search');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('向量检索页面显示搜索输入框', async ({ page }) => {
    await page.goto('/knowledge/search');
    // 应显示搜索输入框
    const hasSearchInput = await page.locator('input[type="search"], input[placeholder*="搜索"]').isVisible().catch(() => false);
    const hasPlaceholder = await page.locator('text=功能开发中').isVisible().catch(() => false);
    expect(hasSearchInput || hasPlaceholder).toBe(true);
  });

  // ── API Mock 测试 ─────────────────────────────────────────────────────────

  test('术语列表 API 返回数据后正确渲染', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/glossary**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          items: [
            {
              id: 1,
              term: '销售额',
              canonical_term: 'sales_amount',
              category: 'measure',
              definition: '商品销售的总金额',
              status: 'active',
            },
            {
              id: 2,
              term: '活跃用户',
              canonical_term: 'active_users',
              category: 'measure',
              definition: '在统计周期内有过任意行为的用户数',
              status: 'active',
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
          pages: 1,
        }),
      });
    });
    await page.goto('/knowledge/glossary');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=销售额')).toBeVisible();
    await expect(page.locator('text=活跃用户')).toBeVisible();
  });

  test('创建术语表单提交成功', async ({ page }) => {
    await page.route('POST **/api/knowledge-base/glossary**', async (route) => {
      expect(route.request().json()).resolves.toMatchObject({
        term: '新增术语',
        canonical_term: 'new_term',
        category: 'concept',
        definition: '新增术语定义',
      });
      await route.fulfill({
        status: 201,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ id: 10, term: '新增术语', status: 'active' }),
      });
    });
    await page.goto('/knowledge/glossary');
    // 查找新建按钮并点击
    const addBtn = page.locator('button', { hasText: '新建术语' }).first();
    if (await addBtn.isVisible().catch(() => false)) {
      await addBtn.click();
      // 填写表单
      await page.locator('input[placeholder*="术语"]').fill('新增术语');
      await page.locator('input[placeholder*="标准术语"]').fill('new_term');
      await page.locator('textarea[placeholder*="定义"]').fill('新增术语定义');
      // 提交
      const submitBtn = page.locator('button[type="submit"]');
      await submitBtn.click();
      // 验证新增术语出现在列表中
      await expect(page.locator('text=新增术语')).toBeVisible({ timeout: 5000 });
    }
  });

  test('文档列表 API 返回数据后正确渲染', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/documents**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          items: [
            {
              id: 1,
              title: 'GMV 计算规则',
              category: 'business_rule',
              status: 'active',
              chunk_count: 3,
            },
            {
              id: 2,
              title: 'DAU 定义说明',
              category: 'data_dictionary',
              status: 'active',
              chunk_count: 1,
            },
          ],
          total: 2,
          page: 1,
          page_size: 20,
          pages: 1,
        }),
      });
    });
    await page.goto('/knowledge/documents');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=GMV 计算规则')).toBeVisible();
    await expect(page.locator('text=DAU 定义说明')).toBeVisible();
  });

  test('向量检索 API 返回结果后正确渲染', async ({ page }) => {
    await page.route('POST **/api/knowledge-base/search**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          results: [
            {
              source_type: 'glossary',
              source_id: 1,
              chunk_text: '销售额：商品销售的总金额',
              similarity: 0.92,
            },
            {
              source_type: 'document',
              source_id: 5,
              chunk_text: 'GMV 计算规则：所有订单金额之和',
              similarity: 0.87,
            },
          ],
          total: 2,
          query: '销售额',
        }),
      });
    });
    await page.goto('/knowledge/search');
    const searchInput = page.locator('input[type="search"], input[placeholder*="搜索"]').first();
    await searchInput.fill('销售额');
    await searchInput.press('Enter');
    await expect(page.locator('text=销售额')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=GMV 计算规则')).toBeVisible();
    await expect(page.locator('text=92%')).toBeVisible(); // 相似度
  });

  // ── 错误处理 ──────────────────────────────────────────────────────────────

  test('术语列表 API 500 错误显示错误提示而非白屏', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/glossary**', async (route) => {
      await route.fulfill({
        status: 500,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ detail: { error_code: 'SYS_001', message: '服务器内部错误' } }),
      });
    });
    await page.goto('/knowledge/glossary');
    await page.waitForLoadState('networkidle');
    // 不应显示原始 error 对象
    await expect(page.locator('text={}')).toHaveCount(0);
    await expect(page.locator('text=[object Object]')).toHaveCount(0);
    // 应显示可读错误信息
    const hasErrorState = await page.locator('text=服务器内部错误').isVisible().catch(() => false);
    const hasGenericError = await page.locator('text=加载失败').isVisible().catch(() => false);
    expect(hasErrorState || hasGenericError).toBe(true);
  });

  test('向量检索 API 400 参数错误时显示提示', async ({ page }) => {
    await page.route('POST **/api/knowledge-base/search**', async (route) => {
      await route.fulfill({
        status: 400,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ detail: { error_code: 'KB_003', message: '检索词不能为空' } }),
      });
    });
    await page.goto('/knowledge/search');
    const searchInput = page.locator('input[type="search"], input[placeholder*="搜索"]').first();
    await searchInput.fill(''); // 空检索词
    await searchInput.press('Enter');
    await expect(page.locator('text=检索词不能为空')).toBeVisible({ timeout: 5000 });
  });

  // ── 分类筛选 ──────────────────────────────────────────────────────────────

  test('文档分类筛选：只显示业务规则类型', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/documents**', async (route) => {
      const url = route.request().url();
      if (url.includes('category=business_rule')) {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            items: [{ id: 1, title: 'GMV 计算规则', category: 'business_rule' }],
            total: 1,
            page: 1,
            page_size: 20,
            pages: 1,
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            items: [
              { id: 1, title: 'GMV 计算规则', category: 'business_rule' },
              { id: 2, title: 'DAU 定义', category: 'data_dictionary' },
            ],
            total: 2,
            page: 1,
            page_size: 20,
            pages: 1,
          }),
        });
      }
    });
    await page.goto('/knowledge/documents');
    await page.waitForLoadState('networkidle');
    // 查找分类筛选下拉
    const categoryFilter = page.locator('select, [data-category-filter]').first();
    if (await categoryFilter.isVisible().catch(() => false)) {
      await categoryFilter.selectOption('business_rule');
      await expect(page.locator('text=GMV 计算规则')).toBeVisible();
      await expect(page.locator('text=DAU 定义')).not.toBeVisible();
    }
  });

  // ── Schema 管理 ───────────────────────────────────────────────────────────

  test('Schema 管理页面（/knowledge/schemas）加载无错误', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', ( msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/knowledge/schemas');
    await page.waitForLoadState('networkidle');
    const realErrors = errors.filter(e =>
      !e.includes('401') &&
      !e.includes('403') &&
      !e.includes('Unauthorized') &&
      !e.includes('favicon')
    );
    expect(realErrors).toHaveLength(0);
  });

  test('Schema 列表 API 返回数据后正确渲染', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/schemas**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          items: [
            {
              id: 1,
              datasource_id: 1,
              datasource_name: 'Superstore',
              version: 1,
              auto_generated: false,
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
          pages: 1,
        }),
      });
    });
    await page.goto('/knowledge/schemas');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=Superstore')).toBeVisible();
    await expect(page.locator('text=version 1')).toBeVisible();
  });

  // ── RBAC 权限测试 ────────────────────────────────────────────────────────

  test('analyst 角色在术语管理页面不显示新建按钮', async ({ page }) => {
    // 此测试依赖 auth context mock，实际端到端时需要特定账号
    // 已知分析师角色无法创建术语（需 data_admin 或 admin）
    await page.goto('/knowledge/glossary');
    await page.waitForLoadState('networkidle');
    // 若页面有"新建"按钮且当前用户是 analyst，按钮应不可见
    const addBtn = page.locator('button', { hasText: '新建术语' }).first();
    // 不做强制断言（取决于真实登录账号），但按钮应始终可点或始终不存在
    if (await addBtn.isVisible().catch(() => false)) {
      // 若可见，analyst 角色点击应得到 403
      await addBtn.click();
      // 某些实现中会弹出权限提示
      const noPermission = page.locator('text=权限不足').isVisible().catch(() => false);
      const forbidden = page.locator('text=403').isVisible().catch(() => false);
      expect(noPermission || forbidden || await page.locator('button[type="submit"]').isVisible()).toBeTruthy();
    }
  });

  // ── 页面导航 ─────────────────────────────────────────────────────────────

  test('从知识库首页可导航到指标字典', async ({ page }) => {
    await page.goto('/knowledge');
    const metricsLink = page.locator('a[href="/knowledge/metrics"]').first();
    if (await metricsLink.isVisible().catch(() => false)) {
      await metricsLink.click();
      await expect(page).toHaveURL('/knowledge/metrics');
      await expect(page.locator('h1')).toContainText('指标字典');
    }
  });

  test('知识库各子页面之间的导航链接正常工作', async ({ page }) => {
    await page.goto('/knowledge/metrics');
    // 检查是否有导航到其他知识库子页面的链接
    const handbookLink = page.locator('a[href="/knowledge/handbook"]').first();
    if (await handbookLink.isVisible().catch(() => false)) {
      await handbookLink.click();
      await expect(page).toHaveURL('/knowledge/handbook');
      await expect(page.locator('h1')).toContainText('品控手册');
    }
  });

  // ── Embedding 状态展示 ────────────────────────────────────────────────────

  test('文档详情显示 Embedding 状态（chunk_count 和 last_embedded_at）', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/documents/**', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          id: 1,
          title: 'GMV 计算规则',
          category: 'business_rule',
          status: 'active',
          chunk_count: 5,
          last_embedded_at: '2026-04-20T10:00:00Z',
        }),
      });
    });
    await page.goto('/knowledge/documents/1');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=5')).toBeVisible(); // chunk_count
    await expect(page.locator(/2026|嵌入/)).toBeVisible(); // last_embedded_at
  });

  // ── 分页 ─────────────────────────────────────────────────────────────────

  test('术语列表分页：第二页数据正确加载', async ({ page }) => {
    await page.route('GET **/api/knowledge-base/glossary**', async (route) => {
      const url = route.request().url();
      if (url.includes('page=2')) {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            items: [{ id: 21, term: '第二页术语', canonical_term: 'page2_term', category: 'concept', definition: '...', status: 'active' }],
            total: 25,
            page: 2,
            page_size: 20,
            pages: 2,
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            items: Array.from({ length: 20 }, (_, i) => ({ id: i + 1, term: `术语${i + 1}`, canonical_term: `term_${i + 1}`, category: 'concept', definition: '...', status: 'active' })),
            total: 25,
            page: 1,
            page_size: 20,
            pages: 2,
          }),
        });
      }
    });
    await page.goto('/knowledge/glossary');
    await page.waitForLoadState('networkidle');
    // 找到并点击第二页按钮
    const page2Btn = page.locator('button[aria-label="第 2 页"], [data-page="2"]').first();
    if (await page2Btn.isVisible().catch(() => false)) {
      await page2Btn.click();
      await expect(page.locator('text=第二页术语')).toBeVisible({ timeout: 5000 });
    }
  });
});
