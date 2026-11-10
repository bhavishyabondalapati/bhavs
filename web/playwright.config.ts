import { defineConfig } from "@playwright/test";

/**
 * E2E tests. Target with E2E_BASE_URL (default: a local `npm run start -- -p 3100`).
 *   public   - no credentials: pages, redirects, security headers, BFF guard rails. Safe to run anywhere, CI included.
 *   journey  - login -> browse -> search -> play -> resume with the test account in E2E_EMAIL / E2E_PASSWORD.
 *              Uses installed Google Chrome: the stream is H.264 and Playwright's open-source Chromium cannot decode it.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3100",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "public", testMatch: /public\.spec\.ts/ },
    { name: "journey", testMatch: /journey\.spec\.ts/, use: { channel: process.env.E2E_CHANNEL ?? "chrome" } },
  ],
});
