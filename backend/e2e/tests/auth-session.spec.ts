import { expect, test, type Page } from "@playwright/test";

async function openFreshPage(page: Page) {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
}

test("auth flow works and logout revokes both refresh and access tokens immediately", async ({ page }) => {
  const email = `pw_${Date.now()}@example.com`;
  const password = "Password123!";

  await openFreshPage(page);

  await page.fill("#email", email);
  await page.fill("#password", password);

  await page.click("#registerBtn");
  await expect(page.locator("#authStatus")).toContainText("회원가입 완료");

  await page.click("#loginBtn");
  await expect(page.locator("#authStatus")).toContainText("로그인 성공");
  await expect(page.locator("#userBadge")).toContainText(`로그인됨: ${email}`);

  await page.click("#meBtn");
  await expect(page.locator("#authStatus")).toContainText(`내 계정: ${email}`);

  const tokens = await page.evaluate(() => ({
    access: window.localStorage.getItem("nab_token"),
    refresh: window.localStorage.getItem("nab_refresh_token"),
  }));
  expect(tokens.access).toBeTruthy();
  expect(tokens.refresh).toBeTruthy();

  await page.click("#logoutBtn");
  await expect(page.locator("#authStatus")).toContainText("로그아웃 완료");
  await expect(page.locator("#userBadge")).toContainText("로그인 필요");

  const refreshProbe = await page.evaluate(async (refreshToken) => {
    const response = await fetch("/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    return {
      status: response.status,
      body: await response.text(),
    };
  }, tokens.refresh);

  expect(refreshProbe.status).toBe(401);
  expect(refreshProbe.body).toContain("Refresh token revoked");

  const accessProbe = await page.evaluate(async (accessToken) => {
    const response = await fetch("/me", {
      method: "GET",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return {
      status: response.status,
      body: await response.text(),
    };
  }, tokens.access);

  expect(accessProbe.status).toBe(401);
});

test("duplicate registration and wrong password show clear error messages", async ({ page }) => {
  const email = `pw_dup_${Date.now()}@example.com`;
  const password = "Password123!";

  await openFreshPage(page);
  await page.fill("#email", email);
  await page.fill("#password", password);

  await page.click("#registerBtn");
  await expect(page.locator("#authStatus")).toContainText("회원가입 완료");

  await page.click("#registerBtn");
  await expect(page.locator("#authStatus")).toContainText("Email already registered");

  await page.fill("#password", "WrongPassword123!");
  await page.click("#loginBtn");
  await expect(page.locator("#authStatus")).toContainText("Invalid credentials");
});

test("me button without login shows auth required message", async ({ page }) => {
  await openFreshPage(page);
  await page.click("#meBtn");
  await expect(page.locator("#authStatus")).toContainText("Authorization header is required");
});
