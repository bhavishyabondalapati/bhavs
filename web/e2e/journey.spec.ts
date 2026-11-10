import { expect, test, type Page } from "@playwright/test";

// The full viewer journey on the real backend: login -> browse -> search -> play -> resume.
// Needs the test account: E2E_EMAIL / E2E_PASSWORD (kept in the gitignored .env; `make e2e` loads them).
const email = process.env.E2E_EMAIL;
const password = process.env.E2E_PASSWORD;
test.skip(!email || !password, "set E2E_EMAIL and E2E_PASSWORD to run the journey test");

const TITLE = "sintel";
const SEEK_TO = 40;

async function videoTime(page: Page) {
  return page.getByTestId("video").evaluate((v: HTMLVideoElement) => v.currentTime);
}

test("login, browse, search, play, then resume where we stopped", async ({ page }) => {
  // 1. Sign in and land on browse.
  await page.goto("/login?next=/");
  await page.getByLabel("Email").fill(email!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "All films" })).toBeVisible();

  // 2. Semantic search: a description, not the name.
  await page.getByRole("searchbox", { name: /search films/i }).fill("a lonely dragon");
  await page.getByRole("searchbox", { name: /search films/i }).press("Enter");
  await expect(page).toHaveURL(/\/search\?q=/);
  await page.getByRole("link", { name: /Sintel/ }).first().click();

  // 3. Title page -> Play. The video must really advance (HLS manifest + segments through the token-checked CDN).
  await expect(page).toHaveURL(new RegExp(`/title/${TITLE}$`));
  await page.getByRole("link", { name: "Play" }).click();
  await expect(page).toHaveURL(new RegExp(`/watch/${TITLE}$`));
  const video = page.getByTestId("video");
  await video.evaluate(async (v: HTMLVideoElement) => { v.muted = true; await v.play(); });
  await expect.poll(() => videoTime(page), { timeout: 30_000 }).toBeGreaterThan(1);

  // 4. Jump ahead, watch a moment, pause: pause sends the position to /events, which saves it for resume.
  await video.evaluate((v: HTMLVideoElement, t) => { v.currentTime = t; }, SEEK_TO);
  await expect.poll(() => videoTime(page), { timeout: 30_000 }).toBeGreaterThan(SEEK_TO + 1);
  await video.evaluate((v: HTMLVideoElement) => v.pause());
  await page.waitForTimeout(1500);

  // 5. Back on browse, the film is in "Continue watching".
  await page.goto("/");
  const row = page.getByRole("region", { name: "Continue watching" });
  await expect(row.getByRole("link", { name: /Sintel/ })).toBeVisible();

  // 6. Open it again: the page says where it resumes, and playback starts there (not at 0).
  await page.goto(`/watch/${TITLE}`);
  await expect(page.getByText(/Resuming from 0:4\d/)).toBeVisible();
  await video.evaluate(async (v: HTMLVideoElement) => { v.muted = true; await v.play(); });
  await expect.poll(() => videoTime(page), { timeout: 30_000 }).toBeGreaterThan(SEEK_TO - 5);
});
