import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";

test.describe.configure({ mode: "serial" });
test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Command center", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("SIMULATION WORKSPACE", { exact: true }),
  ).toBeVisible();
});

test("complete research, risk, authorization, simulated fill, ledger and audit workflow", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await expect(
    page.getByText("Portfolio equity", { exact: false }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Hourly candlestick/ }),
  ).toBeVisible();
  mkdirSync("artifacts", { recursive: true });
  await page.screenshot({
    path: "artifacts/terminal-overview-desktop.png",
    fullPage: true,
  });
  await page.screenshot({ path: "artifacts/krono-discovery-desktop.png" });
  await page.getByRole("button", { name: "Analyze BTC", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Review trade preview" }),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Agent Observatory", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Agent observatory", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /03 Analyst Team/ }).click();
  await expect(
    page.getByText("Deterministic analyst evidence", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/terminal-observatory.png",
    fullPage: true,
  });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Execution History", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Transaction preview", exact: true }),
  ).toBeVisible();
  const refresh = page.getByRole("button", {
    name: "Refresh risk check & quote",
  });
  if (await refresh.isVisible()) await refresh.click();
  await page
    .getByRole("button", { name: "Authorize simulated fill", exact: true })
    .click();
  await expect(
    page.getByText("Simulated fill reconciled", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/terminal-execution.png",
    fullPage: true,
  });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Positions", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Owned simulation inventory" }),
  ).toBeVisible();
  const portfolio = await (await page.request.get("/api/portfolio")).json();
  expect(portfolio.mode).toBe("SIMULATION");
  expect(portfolio.positions).toHaveLength(1);
  expect(Number(portfolio.cash)).toBe(9900);
  const ledger = await (await page.request.get("/api/history/ledger")).json();
  expect(ledger.total).toBe(1);
  const audit = await (
    await page.request.get("/api/history/audit?limit=200")
  ).json();
  expect(
    audit.items.some(
      (a: { kind: string }) => a.kind === "portfolio.reconciled",
    ),
  ).toBe(true);
  const status = await (await page.request.get("/api/status")).json();
  expect(status.live_enabled).toBe(false);
  expect(errors).toEqual([]);
});

test("strategy configuration is versioned and backtests report measured holdout metrics", async ({
  page,
}) => {
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Strategies", exact: true })
    .click();
  const card = page.locator(".strategy-card").filter({
    has: page.getByRole("heading", { name: "Momentum Trading", exact: true }),
  });
  await card.getByRole("button", { name: "Configure" }).click();
  await page.getByLabel("Fast EMA period", { exact: true }).fill("13");
  await page
    .getByRole("button", { name: "Save strategy configuration" })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const strategies = await (await page.request.get("/api/strategies")).json();
  expect(
    strategies.items.find((s: { id: string }) => s.id === "momentum_v1").config
      .fast_period,
  ).toBe(13);
  await card
    .getByRole("button", { name: "Backtest Momentum Trading", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Chronological strategy comparison" }),
  ).toBeVisible();
  await expect(
    page.getByText("synthetic_fixture_v1 · SYNTHETIC", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: "artifacts/terminal-strategies.png",
    fullPage: true,
  });
});

test("news filters and evidence detail preserve source and timestamp provenance", async ({
  page,
}) => {
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "News Intelligence", exact: true })
    .click();
  await page.getByLabel("Filter news asset").selectOption("BTC");
  await page.getByLabel("Search headlines").fill("adoption");
  await expect(page.locator(".news-row")).toHaveCount(1);
  await page.locator(".news-row").click();
  await expect(
    page.getByRole("dialog", { name: "News evidence" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Synthetic development story. This is a fixture, not a report of a real event.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Synthetic source URL" }),
  ).toHaveAttribute("href", /example\.invalid/);
  await page.screenshot({
    path: "artifacts/terminal-news-evidence.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close dialog" }).click();
});

test("assistant lowers allowed risk, emergency stop latches and blocks entries", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Open trading assistant" }).click();
  await page
    .getByLabel("Message assistant")
    .fill("Lower maximum trade size to 0.5% of equity");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByText("Maximum trade allocation is now", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close assistant" }).click();
  await page
    .getByRole("button", { name: "Emergency stop", exact: true })
    .click();
  await expect(
    page.getByText("EMERGENCY STOP ACTIVE", { exact: true }),
  ).toBeVisible();
  const status = await (await page.request.get("/api/status")).json();
  expect(status.scheduler.emergency).toBe(true);
  const risk = await (await page.request.get("/api/risk")).json();
  expect(Number(risk.config.max_equity_per_trade)).toBe(0.005);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Risk Controls", exact: true })
    .click();
  await page.getByLabel("I reviewed the incident").check();
  await page
    .getByRole("button", { name: "Clear emergency latch", exact: true })
    .click();
  await expect(
    page.getByText("EMERGENCY STOP ACTIVE", { exact: true }),
  ).toHaveCount(0);
  const cleared = await (await page.request.get("/api/status")).json();
  expect(cleared.scheduler.entries_paused).toBe(true);
});

test("responsive navigation exposes every workspace and wallet disconnect is honest", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const labels = [
    ["Markets", "Market intelligence"],
    ["News Intelligence", "News intelligence"],
    ["Strategies", "Strategy lab"],
    ["Positions", "Positions & portfolio"],
    ["Execution History", "Execution terminal"],
    ["Agent Observatory", "Agent observatory"],
    ["Risk Controls", "Risk controls"],
    ["Wallet", "Wallet & network"],
    ["Settings", "Workspace settings"],
    ["Overview", "Command center"],
  ];
  for (const [nav, heading] of labels) {
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page
      .getByRole("navigation")
      .getByRole("button", { name: nav, exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: "artifacts/terminal-overview-mobile.png",
    fullPage: true,
  });
  await page.screenshot({ path: "artifacts/krono-discovery-mobile.png" });
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Wallet", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Connect read-only wallet", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "No EIP-1193 wallet" }),
  ).toBeVisible();
});

test("chart timeframe aggregation and aligned correlations are inspectable", async ({
  page,
}) => {
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Markets", exact: true })
    .click();
  await page.getByLabel("Chart candle timeframe").selectOption("4h");
  await expect(
    page.getByRole("img", { name: /Four-hour candlestick/ }),
  ).toBeVisible();
  const bars = await (
    await page.request.get("/api/markets/BTC?timeframe=4h")
  ).json();
  expect(bars.market.timeframe).toBe("4h");
  expect(bars.market.candles).toHaveLength(59);
  await expect(
    page.getByRole("heading", { name: "Aligned market correlation" }),
  ).toBeVisible();
  const correlation = await (
    await page.request.get("/api/correlations")
  ).json();
  expect(correlation.status).toBe("FIXTURE");
  expect(correlation.observations).toBe(237);
  await page.getByLabel("Chart candle timeframe").selectOption("1d");
  await expect(
    page.getByRole("img", { name: /Daily candlestick/ }),
  ).toBeVisible();
  await expect(
    page.getByText("EMA 12 unavailable: fewer than 12 bars", { exact: false }),
  ).toBeVisible();
});

test("Krono branding and bundled fonts stay readable across desktop and mobile", async ({
  page,
}) => {
  // Blocking external browser requests also verifies that the chosen fonts do
  // not depend on Google Fonts or another third-party service being reachable.
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (
      ["http:", "https:"].includes(url.protocol) &&
      url.hostname !== "127.0.0.1"
    )
      await route.abort();
    else await route.continue();
  });
  await page.reload();
  await expect(page).toHaveTitle("Krono · Crypto Trading Workspace");
  await expect(
    page.getByRole("heading", { name: "Command center", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const fonts = await page.evaluate(() =>
    Array.from(document.fonts)
      .filter((font) => font.status === "loaded")
      .map((font) => font.family.replaceAll('"', "")),
  );
  expect(fonts).toContain("Inter Variable");
  await expect(page.locator("body")).not.toContainText(/HSK\s*AGENT/i);
  await expect(
    page.getByText("HSKSwap integration", { exact: true }),
  ).toBeVisible();

  for (const width of [1512, 1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 982 });
    await expect(
      page.getByRole("link", { name: "Krono home" }).filter({ visible: true }),
    ).toHaveCount(width > 760 ? 2 : 1);
    if (width > 760) {
      const rail = await page.locator(".sidebar").boundingBox();
      expect(rail!.width, `Icon rail at ${width}px`).toBeLessThanOrEqual(112);
    } else {
      await expect(
        page.getByRole("navigation", { name: "Main navigation" }),
      ).toHaveCount(0);
    }
    const unreadable = await page.evaluate(() => {
      const selectors =
        ".page-heading p, .metric-label, .metric p, .panel-head p, td, .asset-cell small, .news-meta, .news-text strong, .empty p, .ohlc-line";
      return Array.from(document.querySelectorAll<HTMLElement>(selectors))
        .filter(
          (node) =>
            node.checkVisibility() &&
            parseFloat(getComputedStyle(node).fontSize) < 11.9,
        )
        .map((node) => ({
          text: node.innerText.slice(0, 60),
          size: getComputedStyle(node).fontSize,
        }));
    });
    expect(unreadable, `Reading size at ${width}px`).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
      `Page overflow at ${width}px`,
    ).toBe(true);
    await expect
      .poll(() =>
        page.locator(".candles").evaluate((svg) => {
          const node = svg as SVGSVGElement;
          return Math.abs(
            node.getBoundingClientRect().width - node.viewBox.baseVal.width,
          );
        }),
      )
      .toBeLessThan(2);
    const chartTextSizes = await page
      .locator(".candles text")
      .evaluateAll((labels) =>
        labels.map((label) => {
          const text = label as SVGTextElement;
          return (
            parseFloat(getComputedStyle(text).fontSize) *
            (text.getScreenCTM()?.a ?? 0)
          );
        }),
      );
    expect(
      Math.min(...chartTextSizes),
      `Rendered chart labels at ${width}px`,
    ).toBeGreaterThanOrEqual(11.9);
  }

  await page.setViewportSize({ width: 1512, height: 982 });
  const lowContrast = await page.evaluate(() => {
    const rgb = (value: string) =>
      (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const luminance = (value: string) =>
      rgb(value).reduce((sum, channel, index) => {
        const v = channel / 255;
        return (
          sum +
          (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4) *
            [0.2126, 0.7152, 0.0722][index]
        );
      }, 0);
    return Array.from(
      document.querySelectorAll<HTMLElement>(
        ".page-heading p, .metric-label, .metric p, .panel-head p, .news-meta, .empty p, .ohlc-line",
      ),
    )
      .filter((node) => node.checkVisibility())
      .map((node) => {
        let ancestor: HTMLElement | null = node;
        let background = "rgb(13, 14, 16)";
        while (ancestor) {
          const candidate = getComputedStyle(ancestor).backgroundColor;
          if (candidate !== "rgba(0, 0, 0, 0)" && candidate !== "transparent") {
            background = candidate;
            break;
          }
          ancestor = ancestor.parentElement;
        }
        const text = luminance(getComputedStyle(node).color),
          surface = luminance(background);
        return {
          text: node.innerText.slice(0, 60),
          contrast:
            (Math.max(text, surface) + 0.05) / (Math.min(text, surface) + 0.05),
        };
      })
      .filter((result) => result.contrast < 4.5);
  });
  expect(lowContrast).toEqual([]);

  await page.getByRole("button", { name: "Equity", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.locator(".equity-chart svg").evaluate((svg) => {
        const node = svg as SVGSVGElement;
        return Math.abs(
          node.getBoundingClientRect().width - node.viewBox.baseVal.width,
        );
      }),
    )
    .toBeLessThan(2);
});

test("discovery filters, sorting, measured metrics and view controls use real records", async ({
  page,
}) => {
  await expect(page.locator(".hero-art img")).toHaveJSProperty(
    "complete",
    true,
  );
  expect(
    await page
      .locator(".hero-art img")
      .evaluate((image) => (image as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Strategies", exact: true })
    .click();
  await expect(page.locator(".strategy-card")).toHaveCount(5);
  await expect(
    page
      .locator(".strategy-card .performance-preview figcaption")
      .filter({ hasText: "not strategy P&L" }),
  ).toHaveCount(5);
  expect(
    await page.locator(".strategy-performance strong").allTextContents(),
  ).toEqual(Array(10).fill("—"));
  await page.getByRole("button", { name: "Momentum", exact: true }).click();
  await expect(page.locator(".strategy-card")).toHaveCount(1);
  await expect(page.locator(".strategy-card h2")).toHaveText(
    "Momentum Trading",
  );
  const before = await (await page.request.get("/api/dashboard")).json();
  const count = before.strategies.filter(
    (strategy: { config: { enabled: boolean } }) => strategy.config.enabled,
  ).length;
  const enabled = before.strategies.find(
    (strategy: { id: string }) => strategy.id === "momentum_v1",
  ).config.enabled;
  const toggle = page.getByRole("switch", {
    name: "Enable Momentum Trading",
    exact: true,
  });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", String(!enabled));
  await expect(
    page.getByRole("meter", { name: "Enabled strategy coverage" }),
  ).toHaveAttribute("aria-valuenow", String(count + (enabled ? -1 : 1)));
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", String(enabled));
  await page
    .getByRole("button", { name: "All strategies", exact: true })
    .click();
  await page.getByLabel("Sort strategies").selectOption("name");
  const names = await page.locator(".strategy-card h2").allTextContents();
  expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  await page
    .getByRole("button", { name: "Show strategy list", exact: true })
    .click();
  expect(
    (await page.locator(".strategy-card").first().boundingBox())!.width,
  ).toBeGreaterThan(700);
  await page
    .getByRole("button", { name: "Show strategy grid", exact: true })
    .click();
  expect(
    (await page.locator(".strategy-card").first().boundingBox())!.width,
  ).toBeLessThan(600);
  await page.getByRole("button", { name: "Spread", exact: true }).click();
  await expect(page.locator(".strategy-card")).toHaveCount(1);
  await expect(
    page.getByRole("button", {
      name: "Backtest Arbitrage Detection",
      exact: true,
    }),
  ).toBeDisabled();
});

test("workspace search opens actual markets and remains accessible from mobile navigation", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Search workspace",
    exact: true,
  });
  await dialog
    .getByLabel("Search pages, markets and strategies")
    .fill("Ethereum");
  await dialog.getByRole("button").filter({ hasText: "Ethereum" }).click();
  await expect(
    page.getByRole("heading", { name: "Market intelligence", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".asset-heading")).toContainText("Ethereum");
  await page.keyboard.press("/");
  await dialog
    .getByLabel("Search pages, markets and strategies")
    .fill("news intelligence");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "News intelligence", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Toggle navigation", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Search workspace", exact: true })
    .click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toHaveCount(0);
  await dialog
    .getByLabel("Search pages, markets and strategies")
    .fill("risk controls");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Risk controls", exact: true }),
  ).toBeVisible();
});
