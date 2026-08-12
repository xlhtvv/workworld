import path from "node:path";

import {defineConfig, devices} from "@playwright/test";

const repositoryRoot = path.resolve(__dirname, "../..");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {...devices["Desktop Chrome"]},
    },
  ],
  webServer: [
    {
      command: "python scripts/browser_test_api.py",
      cwd: repositoryRoot,
      env: {
        WORKWORLD_ENV: "test",
        DATABASE_URL: "sqlite+pysqlite:////tmp/workworld-playwright.db",
        WORKWORLD_ALLOWED_ORIGINS: '["http://127.0.0.1:3000"]',
        JWT_SECRET: "playwright-jwt-secret-at-least-32-characters",
        PUSH_SIGNING_SECRET: "playwright-push-secret-at-least-32-characters",
        PYTHONPATH: [
          path.join(repositoryRoot, "apps/api/src"),
          path.join(repositoryRoot, "sdk/python/src"),
        ].join(path.delimiter),
      },
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 pnpm dev --hostname 127.0.0.1 --port 3000",
      url: "http://127.0.0.1:3000/api/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
