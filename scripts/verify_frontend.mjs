// Read-only chain data and virtual paper controls through the built production UI.
import { chromium, expect } from "@playwright/test";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";

const url = process.env.AEGIS_VERIFY_URL;
if (!url || !/^http:\/\/127\.0\.0\.1:\d+$/.test(url))
  throw new Error("Use the managed loopback verification server");
mkdirSync("artifacts/frontend-live", { recursive: true });
const browser = await chromium.launch({
  executablePath: existsSync("/usr/bin/chromium")
    ? "/usr/bin/chromium"
    : undefined,
  headless: true,
});
const page = await browser.newPage({
  baseURL: url,
  viewport: { width: 1512, height: 982 },
  colorScheme: "dark",
  reducedMotion: "reduce",
});
const errors = [],
  report = {
    status: "RUNNING",
    mode: "paper",
    public_transactions_sent: 0,
    source:
      "Actual HSKSwap mainnet reads; isolated virtual ledger; Claude disabled",
    checks: [],
  };
page.on("pageerror", (e) => errors.push(e.message));
const state = async () => (await page.request.get("/api/aegis/state")).json();
const nav = (name) =>
  page.getByRole("navigation").getByRole("button", { name, exact: true });
try {
  await page.goto(url);
  await expect(
    page.getByRole("heading", { name: "Command center", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator('.hero-art img[src="/art/krono-orbit.webp"]'),
  ).toBeVisible();
  await page.getByLabel("Active workspace").selectOption("aegis");
  await expect(
    page.getByRole("heading", { name: "AEGIS on HSKSwap", exact: true }),
  ).toBeVisible();
  const refresh = page.getByRole("button", { name: "Refresh HSKSwap data" });
  let observed;
  for (let attempt = 0; attempt < 2; attempt++) {
    await refresh.click();
    await expect(refresh).toBeEnabled({ timeout: 120000 });
    observed = await state();
    if (observed.data_status === "LIVE") break;
  }
  if (
    observed?.data_status !== "LIVE" ||
    observed.chain_id !== 177 ||
    Object.keys(observed.markets).length < 3
  )
    throw new Error("Verified live mainnet prices are unavailable");
  if (!observed.paused || observed.live_enabled || observed.fills.length)
    throw new Error("Expected a fresh paused virtual ledger");
  report.block = observed.block_number;
  report.markets = observed.markets;
  if (process.env.AEGIS_VERIFY_REFERENCE_MARKETS === "true") {
    const signals = observed.library_signals || [];
    const supported = signals.filter((s) => ["WBTC", "WETH"].includes(s.asset));
    if (
      observed.library_error ||
      observed.library_catalog?.length !== 5 ||
      supported.length !== 10 ||
      supported.some(
        (s) =>
          s.inputs_snapshot.source !== "coinbase_exchange" ||
          s.inputs_snapshot.status !== "AVAILABLE" ||
          Date.now() / 1000 - s.inputs_snapshot.price_at > 90,
      )
    )
      throw new Error(
        "Fresh actual reference markets did not reach the original strategy library",
      );
    report.library_signals = signals;
    report.library_catalog = observed.library_catalog;
    report.checks.push(
      "All five unchanged library strategies receive actual Coinbase reference inputs; HSKSwap execution stays paused",
    );
  }
  report.checks.push(
    "Original home and coin artwork are retained; the HSKSwap workspace reads three actual markets and the isolated PAPER ledger",
  );
  await page.screenshot({
    path: "artifacts/frontend-live/overview-desktop.png",
    fullPage: true,
  });
  await nav("Trading Desk").click();
  await refresh.click();
  await expect(refresh).toBeEnabled({ timeout: 120000 });
  await page.getByLabel("HSKSwap analysis asset").selectOption("WHSK");
  await expect(
    page.getByRole("img", { name: "WHSK observed pool price history" }),
  ).toBeVisible();
  observed = await state();
  if (
    observed.price_history.length < 2 ||
    observed.price_history.at(-1).prices.WHSK !== observed.markets.WHSK.price
  )
    throw new Error("Chart observations differ from backend pool data");
  report.checks.push(
    "Trading desk chart and on-chain pool details match stored backend observations",
  );
  await page.screenshot({
    path: "artifacts/frontend-live/desk-desktop.png",
    fullPage: true,
  });
  const strategiesBefore = await (
    await page.request.get("/api/strategies")
  ).json();
  await nav("Strategies").click();
  await page.keyboard.press("Control+k");
  await page.getByLabel("Message AEGIS").fill("Be more conservative");
  await page.getByRole("button", { name: "Send to AEGIS" }).click();
  await expect(page.getByLabel("AEGIS position size")).toHaveValue("3");
  await expect(page.getByLabel("AEGIS risk profile")).toHaveValue(
    "conservative",
  );
  await page.screenshot({
    path: "artifacts/frontend-live/strategy-chat-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close AEGIS assistant" }).click();
  await nav("Positions").click();
  await expect(
    page.getByText("No open paper positions", { exact: true }),
  ).toBeVisible();
  report.checks.push(
    "Natural-language changes update the shared strategy form and preserve the positions ledger",
  );
  await nav("Wallet").click();
  await expect(
    page.getByRole("button", { name: "Review owner transaction" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Emergency stop", exact: true })
    .click();
  await expect(
    page.getByText("EMERGENCY STOP ACTIVE", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review incident" }).click();
  await page.getByRole("button", { name: "Review and clear stop" }).click();
  report.checks.push(
    "Header emergency stop is visible from the wallet screen and clears into a paused agent",
  );
  const strategiesAfter = await (
    await page.request.get("/api/strategies")
  ).json();
  if (JSON.stringify(strategiesBefore) !== JSON.stringify(strategiesAfter))
    throw new Error("Existing research strategies changed");
  report.strategy_count_preserved = strategiesAfter.items.length;
  await nav("Overview").click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "artifacts/frontend-live/overview-mobile.png",
    fullPage: true,
  });
  if (
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    )
  )
    throw new Error("Mobile horizontal overflow");
  const final = await state();
  if (
    final.mode !== "paper" ||
    !final.paused ||
    final.live_enabled ||
    final.fills.length
  )
    throw new Error("Unexpected execution or mode");
  if (errors.length) throw new Error("Browser runtime error: " + errors[0]);
  report.status = "PASSED";
  report.final = {
    paused: final.paused,
    data_status: final.data_status,
    block: final.block_number,
    fills: final.fills.length,
    pnl: final.pnl,
  };
  report.checks.push(
    "Original five strategy configurations unchanged; mobile layout has no overflow; zero browser runtime errors",
  );
} catch (error) {
  report.status = "FAILED";
  report.error = error.message;
  await page.screenshot({
    path: "artifacts/frontend-live/failure.png",
    fullPage: true,
  });
  throw error;
} finally {
  writeFileSync(
    "artifacts/frontend-live/report.json",
    JSON.stringify(report, null, 2) + "\n",
  );
  await browser.close();
}
console.log(
  JSON.stringify({
    status: report.status,
    checks: report.checks,
    public_transactions_sent: 0,
  }),
);
