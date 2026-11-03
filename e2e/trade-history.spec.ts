import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("research fills expose retained quote, risk, settings and publisher evidence after reload", async ({
  page,
}) => {
  await page.goto("/#/executions");
  await expect(
    page.getByRole("heading", { name: "Past trades", exact: true }),
  ).toBeVisible();
  let archive = await (await page.request.get("/api/trades")).json();
  if (!archive.total) {
    const session = await (await page.request.post("/api/session")).json();
    const headers = { "X-Terminal-CSRF": session.csrf_token };
    const run = await (
      await page.request.post("/api/runs", { headers, data: { symbol: "BTC" } })
    ).json();
    expect(run.intent.state).toBe("AWAITING_AUTHORIZATION");
    const fill = await page.request.post("/api/execution/authorize", {
      headers,
      data: {
        intent_id: run.intent.id,
        quote_id: run.intent.quote.id,
        acknowledgement: "AUTHORIZE_SIMULATION",
      },
    });
    expect(fill.ok()).toBe(true);
    archive = await (await page.request.get("/api/trades")).json();
  }
  const trade = archive.items[0];
  await page.reload();
  const panel = page.locator(".trade-history");
  await expect(panel).toContainText("Research simulation account (USD)");
  await panel.getByLabel("Search past trades").fill(trade.receipt);
  await expect(panel.locator("tbody tr")).toHaveCount(1);
  await panel
    .getByRole("button", { name: `View trade ${trade.id}`, exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Recorded trade details" });
  await expect(dialog).toContainText(trade.receipt);
  await dialog
    .getByText("Original fill and execution settings", { exact: true })
    .click();
  await expect(dialog).toContainText('"execution_context"');
  await dialog.getByText("Recorded risk checks", { exact: true }).click();
  await expect(dialog).toContainText('"approved_notional"');
  await expect(dialog.locator(".trade-news-sources a").first()).toHaveAttribute(
    "href",
    /example\.invalid/,
  );
  const downloaded = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download trade evidence" }).click();
  const file = await downloaded;
  const retained = JSON.parse(readFileSync((await file.path())!, "utf8"));
  expect(retained.trade.id).toBe(trade.id);
  expect(retained.record.intent.id).toBe(retained.record.intent_id);
  expect(retained.events.length).toBeGreaterThan(0);
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await panel.getByLabel("Filter past trades by asset").selectOption("SOL");
  await expect(
    panel.getByText("No matching past trades", { exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Clear trade filters" }).click();
  await expect(panel.locator("tbody tr").first()).toBeVisible();
});

test("AEGIS archive preserves exact EVM state and remains readable on small screens", async ({
  page,
}) => {
  await page.goto("/#/aegis/executions");
  await expect(
    page.getByRole("heading", { name: "Paper execution ledger" }),
  ).toBeVisible();
  let archive = await (
    await page.request.get("/api/trades?workspace=aegis")
  ).json();
  if (!archive.total) {
    const session = await (await page.request.post("/api/session")).json();
    const seed = await page.request.post("/api/test/aegis/seed-entry", {
      headers: { "X-Terminal-CSRF": session.csrf_token },
    });
    expect(seed.ok()).toBe(true);
    archive = await (
      await page.request.get("/api/trades?workspace=aegis")
    ).json();
    await page.reload();
  }
  const panel = page.locator(".trade-history");
  await expect(panel).toContainText("AEGIS paper account (USDT)");
  const trade = archive.items[0];
  await panel
    .getByRole("button", { name: `View trade ${trade.id}`, exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Recorded trade details" });
  await dialog
    .getByText("Original executable quote and pool state", { exact: true })
    .click();
  await expect(dialog).toContainText('"sqrt_price_x96": "');
  await expect(dialog).toContainText("Local receipts identify simulated fills");
  for (const width of [1512, 1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await dialog.evaluate((e) => e.scrollWidth <= e.clientWidth + 2),
    ).toBe(true);
  }
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  for (const width of [1512, 1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
  const after = await (
    await page.request.get("/api/trades?workspace=aegis")
  ).json();
  expect(after.items[0]).toEqual(trade);
});

test("past-trade transport failures can be retried without masking the rest of execution history", async ({
  page,
}) => {
  await page.route(
    (url) => url.pathname === "/api/trades",
    (route) =>
      route.fulfill({
        status: 503,
        json: { error: { message: "Archive temporarily unavailable" } },
      }),
  );
  await page.goto("/#/executions");
  const panel = page.locator(".trade-history");
  await expect(panel.getByRole("alert")).toContainText(
    "Archive temporarily unavailable",
  );
  await expect(
    page.getByRole("heading", { name: "Execution history", exact: true }),
  ).toBeVisible();
  // Remove this test's interceptor without resetting data or replaying any mutation.
  await page.unrouteAll({ behavior: "wait" });
  await panel.getByRole("button", { name: "Retry past trades" }).click();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(panel).toContainText("retained fills");
});

test("archive pagination and UTC date, side and asset filters send the displayed selection", async ({
  page,
}) => {
  // Explicit read-response fixture for controls; no trades are inserted or authorized.
  const records = Array.from({ length: 31 }, (_, index) => ({
    id: `archive-control-${index}`,
    workspace: "research",
    mode: "SIMULATION",
    at: index < 25 ? "2026-01-01T12:00:00Z" : "2026-01-02T23:59:59.999999Z",
    asset: index < 25 ? "BTC" : "ETH",
    side: index < 25 ? "BUY" : "SELL",
    input_asset: "USD",
    output_asset: "BTC",
    amount_in: "100",
    amount_out: "0.001",
    strategy_ids: ["explicit_browser_history_fixture"],
    trading_fee: "0.3",
    network_fee: "0.01",
    realized_pnl: "0",
    currency: "USD",
    quote_block: null,
    receipt: `sim:archive-control-${index}`,
    transaction_hash: null,
    source: "explicit_browser_history_fixture",
  }));
  const queries: URLSearchParams[] = [];
  await page.route(
    (url) => url.pathname === "/api/trades",
    (route) => {
      const params = new URL(route.request().url()).searchParams;
      queries.push(params);
      const matches = records.filter(
        (record) =>
          (!params.get("asset") || record.asset === params.get("asset")) &&
          (!params.get("side") || record.side === params.get("side")) &&
          (!params.get("q") || record.id.includes(params.get("q")!)) &&
          (!params.get("since") ||
            Math.floor(Date.parse(record.at) / 1000) >=
              Number(params.get("since"))) &&
          (!params.get("until") ||
            Math.floor(Date.parse(record.at) / 1000) <=
              Number(params.get("until"))),
      );
      const offset = Number(params.get("offset") ?? 0);
      return route.fulfill({
        json: {
          items: matches.slice(offset, offset + 20),
          total: matches.length,
          total_stored: records.length,
          limit: 20,
          offset,
          assets: ["BTC", "ETH", "SOL"],
          storage: "SQLite",
          note: "Explicit browser read-response fixture.",
        },
      });
    },
  );
  await page.goto("/#/executions");
  const panel = page.locator(".trade-history");
  await expect(panel.locator("tbody tr")).toHaveCount(20);
  await expect(panel).toContainText("1–20 of 31 matching fills");
  await panel.getByRole("button", { name: "Next trades", exact: true }).click();
  await expect(panel.locator("tbody tr")).toHaveCount(11);
  await expect(panel).toContainText("21–31 of 31 matching fills");
  await expect(
    panel.getByRole("button", { name: "Next trades", exact: true }),
  ).toBeDisabled();
  expect(queries.at(-1)?.get("offset")).toBe("20");
  await panel.getByLabel("Filter past trades by asset").selectOption("ETH");
  await expect(panel.locator("tbody tr")).toHaveCount(6);
  await expect(
    panel.getByRole("button", { name: "Previous trades", exact: true }),
  ).toBeDisabled();
  await panel.getByLabel("Filter past trades by side").selectOption("SELL");
  await panel.getByLabel("Past trades from date").fill("2026-01-02");
  await panel.getByLabel("Past trades through date").fill("2026-01-02");
  await expect.poll(() => queries.at(-1)?.get("until")).toBe("1767398399");
  await expect(panel.locator("tbody tr")).toHaveCount(6);
  expect(queries.at(-1)?.get("since")).toBe("1767312000");
  expect(queries.at(-1)?.get("side")).toBe("SELL");
  expect(queries.at(-1)?.get("asset")).toBe("ETH");
  await panel.getByRole("button", { name: "Clear trade filters" }).click();
  await expect(panel.locator("tbody tr")).toHaveCount(20);
  await panel.getByLabel("Search past trades").fill("archive-control-30");
  await expect(panel.locator("tbody tr")).toHaveCount(1);
  await expect(panel).toContainText("1–1 of 1 matching fills");
});
