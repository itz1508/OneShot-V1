const path = require('node:path');
const { defineConfig } = require('@playwright/test');

const baseURL = 'http://127.0.0.1:4178';

module.exports = defineConfig({
  testDir: './tests',
  timeout: 20_000,
  expect: { timeout: 5_000 },
  workers: 2,
  reporter: 'list',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || path.join(__dirname, '.artifacts', 'test-results'),
  use: {
    baseURL,
    browserName: 'chromium',
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'node tests/serve.cjs',
    url: baseURL,
    reuseExistingServer: false,
    timeout: 10_000,
  },
});
