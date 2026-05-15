// frontend/vitest.config.ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react-swc'
import { resolve } from 'node:path'

export default defineConfig({
  plugins: [react()],

  // ─── 测试环境 ──────────────────────────────────────────────────────────────
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,

    // 覆盖范围（v8 provider，支持 lcov + text + html）
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      reportsDirectory: './coverage',

      // 阶段一门槛（低于此值 CI 失败）
      thresholds: {
        lines: 30,
        functions: 30,
        branches: 20,
        statements: 30,
      },

      // 排除列表
      exclude: [
        'node_modules/**',
        'dist/**',
        'out/**',
        'coverage/**',
        '**/*.d.ts',
        '**/*.stories.tsx',
        '**/*.styles.ts',
        'mocks/**',
        'src/test-setup.ts',
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/App.tsx',
      ],

      include: ['src/**/*.{ts,tsx}'],
    },

    // 全局测试目录
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },

  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
})
