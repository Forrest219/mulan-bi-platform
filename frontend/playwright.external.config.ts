import { defineConfig } from '@playwright/test';
import baseConfig from './playwright.config';

const grep = process.env.PLAYWRIGHT_GREP
  ? new RegExp(process.env.PLAYWRIGHT_GREP)
  : /@external/;

export default defineConfig({
  ...baseConfig,
  testDir: './tests/external',
  grep,
  timeout: 60_000,
});
