import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.pw.ts',
  timeout: 30_000,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:4317', headless: true, viewport: { width: 1280, height: 900 } },
  webServer: {
    command: 'npx --no-install vite --host 127.0.0.1 --port 4317 --strictPort',
    url: 'http://127.0.0.1:4317/e2e/companion.html',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
