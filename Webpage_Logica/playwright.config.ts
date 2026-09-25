import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 2,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  outputDir: 'test-results',
  use: {
    baseURL: process.env.TEST_BASE_URL || 'http://127.0.0.1:18080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // Test an already running static export through Nginx, including its CSP and
  // redirects. Starting next dev here would bypass those release checks.
});
