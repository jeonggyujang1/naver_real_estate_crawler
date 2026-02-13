import { expect, test, type Page } from "@playwright/test";

async function openFreshPage(page: Page) {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
}

test("ingest status shows user-facing explanation instead of raw run/count only", async ({ page }) => {
  await openFreshPage(page);

  await page.route("**/crawler/ingest/2977**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        crawl_run_id: 11,
        complex_no: 2977,
        listing_count: 20,
        pages_fetched: 2,
      }),
    });
  });

  await page.route("**/analytics/trend/2977?days=7", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        complex_no: 2977,
        days: 7,
        series: [
          {
            date: "2026-02-13",
            avg_price_manwon: 125000,
            min_price_manwon: 98000,
            max_price_manwon: 163000,
            listing_count: 20,
          },
        ],
      }),
    });
  });

  await page.fill("#ingestComplexNo", "2977");
  await page.fill("#ingestPage", "1");
  await page.click("#ingestBtn");

  await expect(page.locator("#ingestStatus")).toContainText("데이터 새로고침 완료");
  await expect(page.locator("#ingestStatus")).toContainText("20건");
  await expect(page.locator("#ingestStatus")).toContainText("평균 125000만원");
  await expect(page.locator("#ingestStatus")).not.toContainText("run=11, count=20");
});
