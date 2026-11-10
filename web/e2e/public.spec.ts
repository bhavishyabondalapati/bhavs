import { expect, test } from "@playwright/test";

// Everything here works signed out, so it needs no secrets.

test("sign-in page renders and hydrates", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text()); });
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  expect(violations, "no CSP violations on a real page load").toEqual([]);
});

for (const path of ["/", "/search?q=dragon", "/title/sintel", "/watch/sintel"]) {
  test(`signed-out visit to ${path} ends on sign-in with a return path`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login\?next=/);
    expect(new URL(page.url()).searchParams.get("next")).toBe(path);
  });
}

test("admin page is hidden (404) from anyone who is not an admin, including signed-out visitors", async ({ request }) => {
  expect((await request.get("/admin", { maxRedirects: 0 })).status()).toBe(404);
});

test("security headers are set", async ({ request }) => {
  const res = await request.get("/login");
  const h = res.headers();
  const csp = h["content-security-policy"] ?? "";
  expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(csp).not.toMatch(/script-src[^;]*'unsafe-inline'/);
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).toContain("object-src 'none'");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(h["strict-transport-security"]).toContain("max-age=");
  expect(h["x-powered-by"]).toBeUndefined();
});

test("each request gets a fresh nonce", async ({ request }) => {
  const nonce = async () => /'nonce-([^']+)'/.exec((await request.get("/login")).headers()["content-security-policy"])?.[1];
  expect(await nonce()).not.toBe(await nonce());
});

test("API proxy: needs a session, and only forwards allow-listed paths", async ({ request }) => {
  expect((await request.get("/api/bhavs/titles")).status()).toBe(401);
  expect((await request.get("/api/bhavs/search?q=dragon")).status()).toBe(401);
  expect((await request.get("/api/bhavs/users/everyone")).status()).toBe(404);
});
