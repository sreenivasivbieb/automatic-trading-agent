import { expect, test } from "@playwright/test";
import type { Dashboard } from "../frontend/src/types";

test("research control panels and page text fit laptop, tablet and phone widths", async ({
  page,
}) => {
  for (const width of [1280, 1200, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 982 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Command center", exact: true }),
    ).toBeVisible();
    const panels = page.locator(".command-grid > .side-stack > .panel");
    await expect(panels).toHaveCount(2);
    for (const panel of await panels.all()) {
      const bounds = await panel.boundingBox();
      expect(
        bounds!.width,
        "Control panels need room for their labels and actions",
      ).toBeGreaterThanOrEqual(Math.min(260, width - 32));
      const clipped = await panel
        .locator("button")
        .evaluateAll((buttons) =>
          buttons
            .filter(
              (e) => e.checkVisibility() && e.scrollWidth > e.clientWidth + 2,
            )
            .map((e) => e.textContent),
        );
      expect(clipped).toEqual([]);
    }
    await page.goto("/#/news");
    await expect(
      page.getByRole("heading", { name: "Crypto news and sources" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
    const status = await page.locator(".news-feed-status").boundingBox();
    const title = await page.locator(".news-intro").boundingBox();
    expect(
      Math.min(status!.x + status!.width, title!.x + title!.width) -
        Math.max(status!.x, title!.x) <=
        0 || status!.y >= title!.y + title!.height,
    ).toBe(true);
  }
});

test("AEGIS chat leaves readable pipeline cards and unbroken displayed prices", async ({
  page,
}) => {
  await page.goto("/#/aegis");
  const refresh = page.getByRole("button", { name: "Refresh HSKSwap data" });
  await expect(refresh).toBeEnabled();
  await refresh.click();
  await expect(refresh).toBeEnabled();
  await expect(page.locator(".aegis-market-grid > .panel")).toHaveCount(3);
  await page
    .getByRole("button", { name: "Open trading assistant", exact: true })
    .click();
  for (const width of [1512, 1280]) {
    await page.setViewportSize({ width, height: 982 });
    const widths = await page
      .locator(".aegis-pipeline > li")
      .evaluateAll((items) =>
        items.map((item) => item.getBoundingClientRect().width),
      );
    expect(widths).toHaveLength(5);
    expect(Math.min(...widths)).toBeGreaterThanOrEqual(145);
    const priceLines = await page
      .locator(".aegis-market-grid strong")
      .evaluateAll((items) =>
        items.map((item) => {
          const range = document.createRange();
          range.selectNodeContents(item);
          return range.getClientRects().length;
        }),
      );
    expect(priceLines).toEqual([1, 1, 1]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
  await page.goto("/#/aegis/strategies");
  await expect(page.getByLabel("AEGIS stop loss")).toBeVisible();
  const heights = await page
    .locator('.aegis-form input:not([type="checkbox"])')
    .evaluateAll((inputs) =>
      inputs.map((input) => input.getBoundingClientRect().height),
    );
  expect(Math.max(...heights)).toBeLessThanOrEqual(56);
});

test("a breaking-feed failure does not contaminate the working latest feed", async ({
  page,
}) => {
  await page.route(
    (url) =>
      url.pathname === "/api/news" &&
      url.searchParams.get("breaking") === "true",
    (route) =>
      route.fulfill({
        status: 503,
        json: { error: { message: "Breaking news temporarily unavailable" } },
      }),
  );
  await page.goto("/#/news");
  await expect(page.locator(".news-row")).toHaveCount(4);
  const toggle = page.getByRole("button", { name: "Breaking", exact: true });
  await toggle.click();
  await expect(
    page.locator(".news-workspace").getByRole("alert"),
  ).toContainText("Breaking news temporarily unavailable");
  await expect(page.locator(".intelligence-banner .badge")).toHaveText(
    "UNAVAILABLE",
  );
  await toggle.click();
  await expect(page.locator(".intelligence-banner .badge")).toHaveText(
    "FIXTURE",
  );
  await expect(page.locator(".news-workspace").getByRole("alert")).toHaveCount(
    0,
  );
  await expect(page.locator(".news-row")).toHaveCount(4);
});

test("news refresh retains cached stories on failure and recovers on retry", async ({
  page,
}) => {
  await page.goto("/#/news");
  await expect(page.locator(".news-row")).toHaveCount(4);
  const original = (await (
    await page.request.get("/api/dashboard")
  ).json()) as Dashboard;
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: original }),
  );
  const refreshUrl = (url: URL) =>
    url.pathname === "/api/news/refresh" &&
    url.searchParams.get("breaking") === "false";
  await page.route(refreshUrl, (route) =>
    route.fulfill({
      status: 503,
      json: { error: { message: "Refresh connection failed" } },
    }),
  );
  await page.getByRole("button", { name: "Refresh news" }).click();
  await expect(
    page.locator(".news-workspace").getByRole("alert"),
  ).toContainText("Showing the last retrieved stories");
  await expect(page.locator(".intelligence-banner .badge")).toHaveText("STALE");
  await expect(page.locator(".news-row")).toHaveCount(4);
  await expect(
    page.getByRole("button", { name: "Refresh news" }),
  ).toBeEnabled();
  await page.unroute(refreshUrl);
  await page.route(refreshUrl, (route) =>
    route.fulfill({
      json: { ...original.news, retrieved_at: new Date().toISOString() },
    }),
  );
  await page.getByRole("button", { name: "Refresh news" }).click();
  await expect(page.locator(".news-workspace").getByRole("alert")).toHaveCount(
    0,
  );
  await expect(page.locator(".intelligence-banner .badge")).toHaveText(
    "FIXTURE",
  );
  await expect(
    page.getByRole("button", { name: "Refresh news" }),
  ).toBeEnabled();
});

test("HSK filtering, clear filters and long article evidence stay usable on mobile", async ({
  page,
}) => {
  await page.goto("/#/news");
  await expect(page.locator(".news-row")).toHaveCount(4);
  const original = (await (
    await page.request.get("/api/dashboard")
  ).json()) as Dashboard;
  const news = {
    ...original.news,
    articles: original.news.articles.map((a, i) =>
      i
        ? a
        : {
            ...a,
            assets: ["HSK"],
            publisher: "LongPublisherReference".repeat(8),
            title: "LongHashKeyStoryReference".repeat(8),
            summary: "UnbrokenExcerptReference".repeat(20),
          },
    ),
  };
  await page.route("**/api/dashboard", (route) =>
    route.fulfill({ json: { ...original, news } }),
  );
  // News owns an independent feed request; supply the same explicit fixture
  // there so this long-content layout check does not depend on poll timing.
  await page.route(
    (url) =>
      url.pathname === "/api/news" &&
      url.searchParams.get("breaking") === "false",
    (route) => route.fulfill({ json: news }),
  );
  await page.reload();
  await page.setViewportSize({ width: 320, height: 844 });
  await page.getByLabel("Filter news asset").selectOption("HSK");
  await expect(page.locator(".news-row")).toHaveCount(1);
  await page.getByLabel("Search headlines").fill("unmatched headline query");
  await expect(
    page.getByRole("heading", { name: "No matching stories" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Clear news filters" }).click();
  await expect(page.locator(".news-row")).toHaveCount(4);
  await page.locator(".news-row").first().click();
  const dialog = page.getByRole("dialog", { name: "News evidence" });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((e) => e.scrollWidth <= e.clientWidth + 1)).toBe(
    true,
  );
  const clipped = await dialog
    .locator(".story-title,.story-block p")
    .evaluateAll((items) =>
      items
        .filter((e) => e.scrollWidth > e.clientWidth + 1)
        .map((e) => e.className),
    );
  expect(clipped).toEqual([]);
  await page.getByRole("button", { name: "Close dialog" }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
});
