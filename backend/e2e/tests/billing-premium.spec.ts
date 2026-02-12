import { expect, test, type Page } from "@playwright/test";

async function openFreshPage(page: Page) {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
}

test("free user is blocked by compare limit and dummy payment unlocks premium access", async ({ page }) => {
  const email = `pw_billing_${Date.now()}@example.com`;
  const password = "Password123!";

  await openFreshPage(page);

  await page.fill("#email", email);
  await page.fill("#password", password);

  await page.click("#registerBtn");
  await expect(page.locator("#authStatus")).toContainText("회원가입 완료");
  await page.click("#loginBtn");
  await expect(page.locator("#authStatus")).toContainText("로그인 성공");

  const tokens = await page.evaluate(() => ({
    access: window.localStorage.getItem("nab_token"),
  }));
  expect(tokens.access).toBeTruthy();

  const freeCompareProbe = await page.evaluate(async (accessToken) => {
    const query = new URLSearchParams({
      days: "30",
    });
    query.append("complex_nos", "101");
    query.append("complex_nos", "102");
    query.append("complex_nos", "103");
    const response = await fetch(`/analytics/compare?${query.toString()}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return {
      status: response.status,
      body: await response.text(),
    };
  }, tokens.access);
  expect(freeCompareProbe.status).toBe(403);

  await page.click("#billingCheckoutBtn");
  await expect(page.locator("#billingStatus")).toContainText("결제 세션 생성 완료");

  await page.click("#billingCompleteBtn");
  await expect(page.locator("#billingStatus")).toContainText("결제 완료 처리됨");
  await expect(page.locator("#billingPlanBadge")).toContainText("PRO");

  const proCompareProbe = await page.evaluate(async (accessToken) => {
    const query = new URLSearchParams({
      days: "30",
    });
    query.append("complex_nos", "101");
    query.append("complex_nos", "102");
    query.append("complex_nos", "103");
    const response = await fetch(`/analytics/compare?${query.toString()}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return {
      status: response.status,
      body: await response.text(),
    };
  }, tokens.access);
  expect(proCompareProbe.status).toBe(200);
});
