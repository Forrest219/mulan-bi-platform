import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import routeElementPlugin from './eslint-rules/route-element-jsx.js'

const autoImportGlobals = {
  // React
  React: 'readonly',
  useState: 'readonly',
  useEffect: 'readonly',
  useContext: 'readonly',
  useReducer: 'readonly',
  useCallback: 'readonly',
  useMemo: 'readonly',
  useRef: 'readonly',
  useImperativeHandle: 'readonly',
  useLayoutEffect: 'readonly',
  useDebugValue: 'readonly',
  useDeferredValue: 'readonly',
  useId: 'readonly',
  useInsertionEffect: 'readonly',
  useSyncExternalStore: 'readonly',
  useTransition: 'readonly',
  startTransition: 'readonly',
  lazy: 'readonly',
  memo: 'readonly',
  forwardRef: 'readonly',
  createContext: 'readonly',
  createElement: 'readonly',
  cloneElement: 'readonly',
  isValidElement: 'readonly',
  // React Router
  useNavigate: 'readonly',
  useLocation: 'readonly',
  useParams: 'readonly',
  useSearchParams: 'readonly',
  Link: 'readonly',
  NavLink: 'readonly',
  Navigate: 'readonly',
  Outlet: 'readonly',
  // React i18n
  useTranslation: 'readonly',
  Trans: 'readonly',
}

// =====================================================================
// P0 质量门（必须通过，error 级别）
// =====================================================================
const P0_ERROR_RULES = {
  // 未定义变量 — 立即发现引用错误
  'no-undef': 'error',

  // TypeScript 硬错误
  '@typescript-eslint/no-namespace': 'error',
  '@typescript-eslint/ban-ts-comment': 'error',
  '@typescript-eslint/prefer-ts-expect-error': 'error',

  // React Hooks 缺失依赖（硬错误）
  'react-hooks/exhaustive-deps': 'error',
}

// =====================================================================
// P1 风格门（warn 级别，--max-warnings 容忍）
// =====================================================================
const P1_WARN_RULES = {
  // 减少 let 滥用
  'prefer-const': 'warn',
  'prefer-rest-params': 'warn',
  'prefer-spread': 'warn',

  // 减少 any
  '@typescript-eslint/no-explicit-any': 'warn',

  // 未使用变量（warn，允许用 _ 前缀绕过）
  '@typescript-eslint/no-unused-vars': ['warn', {
    argsIgnorePattern: '^_',
    varsIgnorePattern: '^_',
    caughtErrorsIgnorePattern: '^_',
  }],
  'no-unused-vars': 'off',

  // 表达式副作用
  'no-unused-expressions': 'warn',
  '@typescript-eslint/no-unused-expressions': 'off',

  // 规避 JS 奇怪行为
  'no-useless-escape': 'warn',
  'no-useless-catch': 'warn',

  // 空格/缩进等格式问题（已在 prettier 处理，仅作 warn 提示）
  'no-irregular-whitespace': 'warn',
  'no-case-declarations': 'warn',
}

// =====================================================================
// React Hooks 分级治理规则
// 说明：exhaustive-deps 有两种级别：
//   - error：缺少真实意义的依赖（会导致 stale closure bug）
//   - warn：理论上可忽略但不符合规范（eslint-disable 需注明原因）
// =====================================================================
// 注：error 已在 P0_ERROR_RULES 中声明
// P1 阶段考虑进一步区分：callback+useCallback 场景允许 warn

export default [
  { ignores: ['dist', 'node_modules', 'out'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: {
        ...globals.browser,
        ...autoImportGlobals,
        NodeJS: 'readonly',
        JSX: 'readonly',
        IdleRequestCallback: 'readonly',
        __BASE_PATH__: 'readonly',
        __IS_PREVIEW__: 'readonly',
        __READDY_PROJECT_ID__: 'readonly',
        __READDY_VERSION_ID__: 'readonly',
        __READDY_AI_DOMAIN__: 'readonly',
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      // ---- P0 质量门 ----
      ...P0_ERROR_RULES,

      // ---- P1 风格门 ----
      ...P1_WARN_RULES,

      // ---- React Refresh（仅 warn，不强制）----
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],

      // ---- 项目特有规则（error）----
      // 注：local-route/route-element-jsx 在下方的 router config 专用块中启用
    },
  },

  // 仅对 router config 文件启用路由 JSX 元素检查
  {
    files: ['src/router/config.tsx'],
    plugins: {
      'local-route': routeElementPlugin,
    },
    rules: {
      'local-route/route-element-jsx': 'error',
    },
  },
]
