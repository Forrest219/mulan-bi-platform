# 测试与覆盖率统计配置方案

> 项目：mulan-bi-platform（约 20 万行代码）
> 目标：覆盖率 >= 50%（流水线门控）
> 输出时间：2025-05-15

---

## 一、技术栈嗅探结论

### 前端
| 现状 | 推荐框架 |
|------|---------|
| Vite 7 + React 19 + TypeScript 5.8 | **Vitest 3.2 + @vitest/coverage-v8**（已部分安装） |
| 已有 `@testing-library/react` + `jsdom` | 复用，无需替换 |
| 已有 Playwright（smoke 测试） | 保持，不改动 |

**结论**：前端基础设施已就绪，只需补充 `vitest.config.ts` 覆盖配置、调整 package scripts、安装缺失依赖。

### 后端
| 现状 | 推荐框架 |
|------|---------|
| Python 3.10 + FastAPI | **pytest 8 + pytest-cov**（已安装） |
| 已有 `pytest-asyncio`、`pytest-mock` | 保持 |
| `pyproject.toml`（setuptools） | 复用，补充 `[tool.coverage]` 配置 |

**结论**：后端基础设施已就绪，只需完善 `pyproject.toml` 覆盖配置、补充 `.coveragerc` 忽略规则。

---

## 二、核心配置文件

### 2.1 前端 — `frontend/vitest.config.ts`（新建）

```typescript
// frontend/vitest.config.ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react-swc'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react()],

  // ─── 测试环境 ──────────────────────────────────────────────────────────────
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],   // 见下方说明
    globals: true,                          // 让 describe/it/expect 全局可用

    // 覆盖范围（v8 provider，输出 lcov + text + html）
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      reportsDirectory: './coverage',

      // 阈值门控（阶段一：放宽，快速破冰）
      thresholds: {
        lines: 30,
        functions: 30,
        branches: 20,
        statements: 30,
      },

      // 排除列表（不需要统计的路径）
      exclude: [
        'node_modules/**',
        'dist/**',
        'out/**',
        'coverage/**',
        '**/*.d.ts',
        '**/*.stories.tsx',          // Storybook 文件
        '**/*.styles.ts',            // CSS-in-JS 样式文件
        'mocks/**',                  // Mock 数据文件
        'src/test-setup.ts',         // 全局测试 setup
        'src/main.tsx',              // 入口文件
        'src/vite-env.d.ts',         // Vite 类型声明
        // Router / App 暂时不覆盖（集成测试范畴）
        'src/App.tsx',
      ],

      // 按文件类型决定是否处理
      include: ['src/**/*.{ts,tsx}'],
    },

    // 全局测试目录（与 src 平级）
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },

  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
})
```

**说明**：`test-setup.ts` 内容见 2.3。

---

### 2.2 前端 — `frontend/src/test-setup.ts`（新建）

```typescript
// frontend/src/test-setup.ts
import '@testing-library/jest-dom'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// 每个测试后清理 React 树，避免状态泄漏
afterEach(() => {
  cleanup()
})

// ─── 全局 vi mock（可选，按需启用）───────────────────────────────
// 避免组件内直接调用 localStorage / sessionStorage 报错
vi.stubGlobal('sessionStorage', {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
})

// 避免 window.matchMedia 报错（部分组件用到响应式断点）
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})
```

---

### 2.3 后端 — `backend/pyproject.toml`（追加 coverage 配置）

```toml
# backend/pyproject.toml 追加以下内容

[tool.coverage.run]
# 测量范围：所有 .py 文件（排除已知的非业务代码）
source = ["app", "services"]
branch = true           # 开启分支覆盖（if/else/try/except 路径）
parallel = true         # 多进程并行收集（pytest-xdist 兼容）

# 不需要统计的路径
omit = [
    "*/tests/*",
    "*/test_*.py",
    "*/__pycache__/*",
    "*/alembic/*",
    "*/migrations/*",
    "*/scripts/*",
    "*/seed_*.py",
    "*/__init__.py",          # __init__ 通常不包含可测试逻辑
    "*/config.py",            # 配置读取（外部依赖）
    "*/main.py",              # FastAPI 入口（集成测试对象）
]

[tool.coverage.report]
# 展示格式：控制台 + lcov 文件 + HTML 报告
precision = 2              # 百分比保留 2 位小数
skip_covered = false      # 在控制台也显示已覆盖的文件（便于分析）
sort = "Cover"            # 按覆盖率从低到高排序（最需要补测的排在前面）

# 排除的行（不计入覆盖率）
exclude_lines = [
    # pragma: no cover（明确不期望覆盖）
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",

    # type guard / stub（类型守卫不计入覆盖）
    "if TYPE_CHECKING:",
    "if typing.TYPE_CHECKING:",

    # 异常处理中的 fallback（降级路径故意不触发）
    "except:",
    "except Exception:",

    # FastAPI 路径装饰器（通常在集成测试覆盖）
    "@app.get",
    "@app.post",
    "@app.put",
    "@app.delete",
    "@app.patch",
    "@router.get",
    "@router.post",
    "@router.put",
    "@router.delete",
    "@router.patch",
]

# 按目录/文件忽略特定行（局部排除）
[tool.coverage.path_filter]
"*/app/utils/*" = ["if settings.DEBUG:"]
"*/services/auth/*" = ["# ignore auth on dev"]

[tool.coverage.html]
directory = "coverage_html"

[tool.coverage.lcov]
output = "coverage.lcov"

[tool.coverage.json]
output = "coverage.json"
```

---

### 2.4 后端 — `backend/.coveragerc`（新建，可独立使用）

```ini
# backend/.coveragerc
# 当 pyproject.toml [tool.coverage.run] 不生效时（某些 CI 环境），
# coverage run 会自动读取此文件作为补充配置。

[run]
source = app,services
branch = True
parallel = True
omit =
    */tests/*
    */test_*.py
    */__pycache__/*
    */alembic/*
    */migrations/*
    */scripts/*
    */__init__.py

[report]
precision = 2
skip_covered = False
sort = Cover
exclude_lines =
    pragma: no cover
    def __repr__
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    @app\.
    @router\.
```

---

### 2.5 后端 — `backend/pytest.ini`（追加 coverage 报告格式）

```ini
# backend/pytest.ini  — 在现有 addopts 后追加以下内容
# 原始内容（保留）：
# addopts = -v --tb=short --import-mode=importlib --cov=services --cov=app --cov-report=term-missing

# 追加以下行（支持多格式输出）：
cov = services,app
addopts =
    -v
    --tb=short
    --import-mode=importlib
    --cov=services
    --cov=app
    --cov-report=term-missing
    --cov-report=lcov:coverage_lcov
    --cov-report=html:coverage_html
    --cov-report=json:coverage.json
    --cov-fail-under=30
```

> **注意**：`--cov-fail-under=30` 是阶段一门槛，流水线规范要求 50%，后续 CI 需同步更新为 50。

---

## 三、Package Scripts & CI 脚本

### 3.1 前端 `frontend/package.json` 补充

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 100",
    "type-check": "tsc --noEmit --project tsconfig.app.json",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage",
    "test:coverage:open": "vitest run --coverage && open coverage/index.html",
    "smoke": "playwright test",
    "smoke:ui": "playwright test --ui",

    "diagram:architecture": "mmdc -i ../docs/diagrams/mulan-architecture.mmd -o ../docs/diagrams/mulan-architecture.svg -p puppeteer-config.json",
    "diagram:requirement": "mmdc -i ../docs/diagrams/mulan-requirement-flow.mmd -o ../docs/diagrams/mulan-requirement-flow.svg -p puppeteer-config.json",
    "diagram:lineage": "mmdc -i ../docs/diagrams/mulan-data-lineage.mmd -o ../docs/diagrams/mulan-data-lineage.svg -p puppeteer-config.json",
    "diagram:all": "npm run diagram:architecture && npm run diagram:requirement && npm run diagram:lineage"
  }
}
```

**需要安装的新依赖（执行以下命令）：**

```bash
# 进入 frontend 目录
cd /path/to/mulan-bi-platform/frontend

# 安装 vitest 覆盖 v8 reporter（Vitest 内置，但需要确保版本）
npm install -D @vitest/coverage-v8

# Vitest 全局类型（让 describe/it/expect 在 .ts 文件中不被 TS 报错）
npm install -D vitest
```

> **已有，无需重复安装**：`vitest@3.2`、`@vitest/coverage-v8@3.2`、`@testing-library/react@16.3`、`jsdom@26.1`、`@testing-library/jest-dom@6.9`

### 3.2 后端 `requirements.txt` 补充

```bash
# backend/requirements.txt 追加以下内容（按需安装）
# 已有的包无需重复：pytest, pytest-cov, pytest-asyncio, pytest-mock
# 如需 JSON 格式覆盖报告（GitHub Actions 官方 Action 支持），安装：

pytest-json-report>=0.5.0    # 可选：生成 JSON 格式覆盖报告
```

### 3.3 CI 脚本示例（GitHub Actions — `.github/workflows/test.yml`）

```yaml
name: Test & Coverage

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  backend-test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: mulan
          POSTGRES_PASSWORD: mulan
          POSTGRES_DB: mulan_bi_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt

      - name: Run backend tests with coverage
        run: |
          cd backend
          pytest tests/ \
            --cov=services \
            --cov=app \
            --cov-report=term-missing \
            --cov-report=lcov:coverage_lcov/lcov.info \
            --cov-report=html:coverage_html \
            --cov-fail-under=30
        env:
          DATABASE_URL: postgresql://mulan:mulan@localhost:5432/mulan_bi_test
          SESSION_SECRET: test-session-secret
          DATASOURCE_ENCRYPTION_KEY: test-datasource-key-32-bytes-ok!!
          TABLEAU_ENCRYPTION_KEY: test-tableau-key-32-bytes-ok!!
          LLM_ENCRYPTION_KEY: test-llm-key-32-bytes-ok!!!!
          ADMIN_USERNAME: admin
          ADMIN_PASSWORD: admin123
          SECURE_COOKIES: 'false'
          SERVICE_JWT_SECRET: test-jwt-secret

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          files: backend/coverage_lcov/lcov.info
          fail_ci_if_error: false
          verbose: true

  frontend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: |
          cd frontend
          npm ci

      - name: Run frontend tests with coverage
        run: |
          cd frontend
          npm run test:coverage

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        with:
          files: frontend/coverage/lcov.info
          fail_ci_if_error: false
          verbose: true
```

---

## 四、破冰策略（First Blood Strategy）

### 背景
20 万行老项目一次性全量覆盖 = 士气崩溃 + 数据无意义。
**核心原则**：先让数字从 0 到有，再逐步逼近 50% 门槛。

### 优先补测顺序（Top 3）

#### 🥇 第一优先：`backend/services/common/`（纯函数工具库）

**为什么**：无 I/O、无状态依赖、无 FastAPI 路由，纯 Python 函数，直接 assert。

**覆盖目标**：
```
services/common/     → utils.py、validators.py、formatters.py
services/rules/      → 规则引擎的纯函数
services/ddl_checker/ → DDL 解析、SQL 格式化的纯函数
```

**预期覆盖率**：80%+（因为几乎全是纯函数）
**对总覆盖率贡献**：约 8%（取决于该模块占总 LOC 的比例）

---

#### 🥈 第二优先：`frontend/src/hooks/`（React 自定义 Hook）

**为什么**：Hooks 是 React 项目中最容易写单测的部分。给定输入 props，返回确定的 state/ref，直接 `renderHook` + `act` 即可。

**覆盖目标**：
```
src/hooks/useQuerySession.ts    → 查询会话状态管理
src/hooks/useQuerySessions.ts   → 列表管理
src/hooks/useStreamingChat.ts   → 流式聊天 Hook
```

**预期覆盖率**：70%+（Hooks 通常很纯粹）
**对总覆盖率贡献**：约 2%（Hooks 占前端 LOC 比例小，但ROI极高）

---

#### 🥉 第三优先：`backend/services/auth/`（认证服务）

**为什么**：
1. 认证是系统入口，最稳定，几乎不变
2. `conftest.py` 已提供 `admin_client` / `analyst_client` fixture，开箱即用
3. 已有 `test_auth_service.py`（部分覆盖），可继续深化

**覆盖目标**：
```
services/auth/service.py   → login/logout/permission check 纯逻辑
services/auth/utils.py     → token 解析、密码哈希（纯函数）
```

**预期覆盖率**：60%+（业务逻辑清晰）
**对总覆盖率贡献**：约 5%

---

### 三阶段破冰路线图

| 阶段 | 时间 | 目标覆盖率 | 重点模块 | 策略 |
|------|------|-----------|---------|------|
| **Phase 0** | Week 1-2 | 10% | common/ + hooks/ | 扫清纯函数，建立测试习惯 |
| **Phase 1** | Week 3-4 | 20-30% | auth/ + rules/ + ddl_checker/ | 核心业务逻辑，补充 conftest |
| **Phase 2** | Week 5-8 | 30-50% | 其余 services/ + components/ | 全面铺设，逼近 CI 门控 |

---

## 五、覆盖率报告输出格式汇总

| 工具 | 输出格式 | 文件路径 | 用途 |
|------|---------|---------|------|
| **后端 pytest-cov** | `term`（终端） | — | 实时查看 |
| | `lcov` | `backend/coverage_lcov/lcov.info` | Codecov / GitHub PR comment |
| | `html` | `backend/coverage_html/` | 本地浏览器查看（`open coverage_html/index.html`）|
| | `json` | `backend/coverage.json` | 第三方集成 |
| **前端 vitest** | `text`（终端） | — | 实时查看 |
| | `lcov` | `frontend/coverage/lcov.info` | Codecov / GitHub PR comment |
| | `html` | `frontend/coverage/index.html` | 本地浏览器查看 |

---

## 六、快速验证命令（落地检查）

```bash
# ── 后端 ──────────────────────────────────────────────────────────────────
cd backend

# 单跑覆盖率（不触发 CI fail-under）
pytest tests/ --cov=services --cov=app \
  --cov-report=term-missing \
  --cov-report=lcov:coverage_lcov/lcov.info \
  --cov-report=html:coverage_html

# 本地查看 HTML 报告
open coverage_html/index.html

# ── 前端 ──────────────────────────────────────────────────────────────────
cd frontend

# 单跑覆盖率
npm run test:coverage

# 本地查看 HTML 报告
open coverage/index.html
```

---

## 七、常见陷阱 & 解决方案

| 陷阱 | 原因 | 解决 |
|------|------|------|
| `coverage = 0%` | 测试收集了但没有运行任何测试 | 确认 `testpaths` 指向正确目录 |
| `import mode` 冲突 | `--import-mode=importlib` 与 `--cov` 并用时有路径问题 | 使用 `--cov=pkg` 显式指定包名 |
| 前端 `window.matchMedia` 报错 | jsdom 不实现 `matchMedia` | 在 `test-setup.ts` 中 `vi.stubGlobal` mock |
| `conftest.py` 数据库误连生产库 | `DATABASE_URL` 未指向 test 库 | `conftest.py` 已硬拦截，非 test 库名直接抛 `RuntimeError` |
