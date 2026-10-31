import { test, expect } from "@playwright/test";

test.afterEach(async ({ page }) => {
  // Polling can leave route.fetch()/response.json() in flight at fixture teardown.
  await page.unrouteAll({ behavior: "wait" });
});

test("Feed settings persist and incoming price observations preserve the chart viewport", async ({
  page,
}) => {
  await page.route("**/api/dashboard", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    // Explicit UI contract fixture: simulate new observation times without trading.
    data.markets[0].price_at = new Date().toISOString();
    await route.fulfill({ response, json: data });
  });
  await page.goto("/#/settings");
  const input = page.getByLabel("Price update interval (seconds)");
  await input.fill("1");
  await page.getByRole("button", { name: "Save feed refresh" }).click();
  await page.reload();
  await expect(input).toHaveValue("1");
  await page.goto("/#/desk");
  const chart = page.locator(".desk-chart-panel svg.candles");
  await expect(chart).toHaveAttribute("data-visible-bars", "72");
  await page.getByLabel("Zoom in chart").click();
  const zoomed = await chart.getAttribute("data-visible-bars");
  await page.waitForResponse(
    (response) => response.url().endsWith("/api/dashboard") && response.ok(),
  );
  await expect(chart).toHaveAttribute("data-visible-bars", zoomed!);
  await page.goto("/#/settings");
  await input.fill("5");
  await page.getByRole("button", { name: "Save feed refresh" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Feed refresh settings saved",
  );
});

test("News shows provider allowance and polls the selected breaking feed", async ({
  page,
}) => {
  let breakingRequests = 0;
  await page.route("**/api/dashboard", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.news.limited = true;
    data.news.max_results = 3;
    data.news.limitation = "Fixture provider allowance";
    await route.fulfill({ response, json: data });
  });
  await page.route("**/api/news?breaking=true", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.articles = [
      {
        ...data.articles[0],
        title: `Fixture breaking update ${++breakingRequests}`,
        urgency: "breaking",
      },
    ];
    await route.fulfill({ response, json: data });
  });
  await page.goto("/#/news");
  await expect(
    page.getByText(/Provider-limited feed.*up to 3 results/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Breaking", exact: true }).click();
  await expect(page.getByText("Fixture breaking update 1")).toBeVisible();
  await expect(page.getByText("Fixture breaking update 2")).toBeVisible({
    timeout: 20000,
  });
});

test("Trading Desk charts, validated indicators, alerts and sizing are functional", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#/desk");
  await expect(page.getByLabel("Desk trade notional")).toBeVisible();
  const chart = page.locator(".desk-chart-panel svg.candles");
  await expect(chart).toHaveAttribute("data-visible-bars", "72");
  await page.getByLabel("Zoom in chart").click();
  await expect(chart).not.toHaveAttribute("data-visible-bars", "72");
  await page.getByLabel("Reset chart viewport").click();
  await expect(chart).toHaveAttribute("data-visible-bars", "72");
  await page.getByRole("button", { name: "MACD", exact: true }).click();
  await expect(chart).toContainText("MACD");
  await page.getByRole("button", { name: "Risk cap", exact: true }).click();
  await expect(page.getByLabel("Desk trade notional")).toHaveValue(
    "100.00000000",
  );
  await page
    .locator(".desk-dock-tabs")
    .getByRole("button", { name: /alerts/ })
    .click();
  await page.getByLabel("Alert target price").fill("90000");
  await page.getByRole("button", { name: "Add alert", exact: true }).click();
  await expect(page.locator(".desk-dock-content")).toContainText("ARMED");
  await page.reload();
  await page
    .locator(".desk-dock-tabs")
    .getByRole("button", { name: /alerts/ })
    .click();
  await expect(page.locator(".desk-dock-content")).toContainText("ARMED");
  await page.getByRole("button", { name: "Delete BTC price alert" }).click();
  await expect(page.locator(".desk-dock-content")).not.toContainText("ARMED");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "artifacts/krono-trading-desk.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Desk trade notional")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
test("Unconfigured AWS platform shows setup state without invented agents or cloud success", async ({
  page,
}) => {
  await page.route("**/platform/health", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { message: "AWS account is not configured" },
      }),
    }),
  );
  await page.goto("/#/platform");
  await expect(
    page.getByRole("heading", { name: "Your agent platform starts here." }),
  ).toBeVisible();
  await expect(page.locator(".platform-setup")).toContainText(
    "No cloud agents or Bedrock access are being represented as connected",
  );
  await page.screenshot({
    path: "artifacts/krono-platform-setup.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
});

test("Platform UI contract: conversation, reviewed deployment, runtime controls and logout isolation (test providers)", async ({
  page,
}) => {
  await page.goto("/#/platform");
  await expect(
    page.getByRole("heading", { name: "Welcome to your workspace" }),
  ).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill("alice@fixture.test");
  await page.getByLabel("Password", { exact: true }).fill("fixture");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".platform-workspace")).toContainText(
    "ISOLATED TEST FIXTURE",
  );
  await page
    .getByLabel("Describe an agent or command")
    .fill("Create a conservative BTC momentum agent");
  await page.getByLabel("Send platform message").click();
  await expect(page.locator(".platform-agent-row")).toContainText(
    "Browser fixture operator",
  );
  await page
    .getByRole("button", { name: "Review deployment", exact: true })
    .click();
  await expect(page.locator(".platform-deployment-preview")).toContainText(
    "DEPLOYMENT APPROVAL",
  );
  await page
    .getByRole("button", {
      name: "Authorize AWS simulation deployment",
      exact: true,
    })
    .click();
  await expect(page.locator(".platform-runtime-state")).toContainText(
    "RUNNING",
  );
  await page
    .locator(".platform-runtime-controls")
    .getByRole("button", { name: "pause", exact: true })
    .click();
  await expect(page.locator(".platform-runtime-state")).toContainText("PAUSED");
  await page
    .locator(".platform-runtime-controls")
    .getByRole("button", { name: "resume", exact: true })
    .click();
  await expect(page.locator(".platform-runtime-state")).toContainText(
    "RUNNING",
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "artifacts/krono-platform-fixture.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill("bob@fixture.test");
  await page.getByLabel("Password", { exact: true }).fill("fixture");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".platform-agent-row")).toHaveCount(0);
  await expect(page.locator(".platform-workspace")).not.toContainText(
    "Browser fixture operator",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 2,
    ),
  ).toBe(true);
});
