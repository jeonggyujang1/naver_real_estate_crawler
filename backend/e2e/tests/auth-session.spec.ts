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

test("guest auth controls are shown before login", async ({ page }) => {
  await openFreshPage(page);
  await expect(page.locator("#authGuestControls")).toHaveClass(/active/);
  await expect(page.locator("#authUserControls")).not.toHaveClass(/active/);
  await expect(page.locator("#email")).toBeVisible();
  await expect(page.locator("#password")).toBeVisible();
});

test("extract complexNo from naver url input", async ({ page }) => {
  await openFreshPage(page);

  await page.fill(
    "#watchComplexUrl",
    "https://new.land.naver.com/complexes/2977?ms=37.55,127.03,17&a=APT&b=A1&e=RETAIL"
  );
  await page.click("#parseComplexUrlBtn");

  await expect(page.locator("#watchStatus")).toContainText("단지 번호 추출 완료: 2977");
  await expect(page.locator("#watchComplexNo")).toHaveValue("2977");
});

test("complex name autocomplete fills complex number and name", async ({ page }) => {
  await openFreshPage(page);

  await page.route("**/crawler/search/complexes**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        keyword: "래미안",
        count: 1,
        items: [
          {
            complex_no: 2977,
            complex_name: "래미안 대치 팰리스",
            real_estate_type_name: "아파트",
            sido_name: "서울시",
            gugun_name: "강남구",
            dong_name: "대치동",
          },
        ],
      }),
    });
  });

  await page.fill("#watchComplexKeyword", "래미안");
  await expect(page.locator("#watchComplexSearchList")).toContainText("래미안 대치 팰리스");

  await page.click("#watchComplexSearchList button");
  await expect(page.locator("#watchComplexNo")).toHaveValue("2977");
  await expect(page.locator("#watchComplexName")).toHaveValue("래미안 대치 팰리스");
});

test("watch complex can be deleted from table", async ({ page }) => {
  const email = `watch_del_${Date.now()}@example.com`;
  const password = "Password123!";

  await openFreshPage(page);
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click("#registerBtn");
  await expect(page.locator("#authStatus")).toContainText("회원가입 완료");
  await page.click("#loginBtn");
  await expect(page.locator("#authStatus")).toContainText("로그인 성공");
  await expect(page.locator("#authUserControls")).toHaveClass(/active/);

  await page.fill("#watchComplexNo", "2977");
  await page.fill("#watchComplexName", "삭제테스트단지");
  await page.click("#addWatchBtn");
  await expect(page.locator("#watchStatus")).toContainText("관심 단지 1건");
  await page.click("#loadWatchBtn");

  await expect(page.locator("#watchBody")).toContainText("2977");
  await expect(page.locator("#watchBody")).toContainText("삭제테스트단지");

  await page.click("#watchBody button[data-watch-id]");
  await expect(page.locator("#watchStatus")).toContainText("관심 단지 0건");
  await expect(page.locator("#watchBody")).not.toContainText("삭제테스트단지");
});
