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

test("trend/compare charts stay horizontally readable and fixed-height", async ({ page }) => {
  await openFreshPage(page);

  await page.route("**/analytics/trend/2977?days=30", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        complex_no: 2977,
        days: 30,
        series: [
          { date: "2026-02-10", avg_price_manwon: 120000, min_price_manwon: 100000, max_price_manwon: 140000, listing_count: 10 },
          { date: "2026-02-11", avg_price_manwon: 121000, min_price_manwon: 101000, max_price_manwon: 141000, listing_count: 11 },
        ],
      }),
    });
  });
  await page.route("**/analytics/compare?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        complex_nos: [2977, 23620],
        days: 30,
        trade_type_name: null,
        series: {
          "2977": [
            { date: "2026-02-10", avg_price_manwon: 120000, listing_count: 10 },
            { date: "2026-02-11", avg_price_manwon: 121000, listing_count: 11 },
          ],
          "23620": [
            { date: "2026-02-10", avg_price_manwon: 90000, listing_count: 8 },
            { date: "2026-02-11", avg_price_manwon: 91000, listing_count: 9 },
          ],
        },
      }),
    });
  });

  await page.fill("#trendComplexNo", "2977");
  await page.fill("#trendDays", "30");
  await page.click("#loadTrendBtn");

  await page.fill("#compareComplexNos", "2977,23620");
  await page.fill("#compareDays", "30");
  await page.click("#loadCompareBtn");

  const layout = await page.evaluate(() => {
    const trendSection = document.getElementById("trendChart")?.closest("section");
    const compareSection = document.getElementById("compareChart")?.closest("section");
    const container = document.querySelector(".container");
    const trendRect = trendSection?.getBoundingClientRect();
    const compareRect = compareSection?.getBoundingClientRect();
    const containerRect = container?.getBoundingClientRect();

    return {
      trendWidth: trendRect?.width ?? 0,
      compareWidth: compareRect?.width ?? 0,
      containerWidth: containerRect?.width ?? 1,
      trendTop: trendRect?.top ?? 0,
      compareTop: compareRect?.top ?? 0,
      trendCanvasHeight: document.getElementById("trendChart")?.getBoundingClientRect().height ?? 0,
      compareCanvasHeight: document.getElementById("compareChart")?.getBoundingClientRect().height ?? 0,
    };
  });

  expect(layout.trendWidth / layout.containerWidth).toBeGreaterThan(0.9);
  expect(layout.compareWidth / layout.containerWidth).toBeGreaterThan(0.9);
  expect(layout.compareTop).toBeGreaterThan(layout.trendTop);
  expect(layout.trendCanvasHeight).toBeLessThanOrEqual(500);
  expect(layout.compareCanvasHeight).toBeLessThanOrEqual(500);
});
