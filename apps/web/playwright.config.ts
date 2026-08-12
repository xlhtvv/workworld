import {defineConfig, devices} from "@playwright/test";

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
      command: "cd ../.. && WORKWORLD_ENV=test DATABASE_URL=sqlite+pysqlite:////tmp/workworld-playwright.db WORKWORLD_ALLOWED_ORIGINS='[\"http://127.0.0.1:3000\"]' JWT_SECRET=playwright-jwt-secret-at-least-32-characters PUSH_SIGNING_SECRET=playwright-push-secret-at-least-32-characters PYTHONPATH=apps/api/src:sdk/python/src .venv/bin/python scripts/browser_test_api.py",
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
