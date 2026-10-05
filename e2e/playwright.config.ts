import { defineConfig, devices } from '@playwright/test';
import { PYTHON } from './support/config';

/**
 * End-to-end tests against a real bench site.
 *
 * `webServer` starts the Frappe development server for the configured site on a
 * free port (never 8000), so a run needs nothing but the bench and this folder.
 * Set E2E_BASE_URL to reuse a server that is already running.
 */
const port = Number(process.env.E2E_PORT ?? 8010);
const externalBaseUrl = process.env.E2E_BASE_URL;
const baseURL = externalBaseUrl ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests',
  globalSetup: './support/global-setup.ts',
  outputDir: './test-results/artifacts',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: './playwright-report', open: 'never' }],
    ['json', { outputFile: './test-results/results.json' }],
  ],
  use: {
    // The server pins the site in code (support/py/serve.py), so neither a
    // hosts entry nor a Host header is needed.
    baseURL,
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'api',
      testIgnore: /desk\.spec\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'ui',
      testMatch: /desk\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        launchOptions: {
          executablePath: process.env.PLAYWRIGHT_CHROME_PATH ?? '/usr/bin/google-chrome',
        },
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: externalBaseUrl
    ? undefined
    : {
        command: `${PYTHON} support/py/serve.py ${port}`,
        cwd: __dirname,
        url: `${baseURL}/api/method/ping`,
        reuseExistingServer: false,
        timeout: 180_000,
        stdout: 'ignore',
        stderr: 'pipe',
      },
});