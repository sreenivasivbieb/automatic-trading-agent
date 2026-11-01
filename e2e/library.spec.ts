import { test, expect } from "@playwright/test";
import { openWorkspace } from "./navigation";

test("the original strategy library reaches the HSKSwap paper ledger and existing screens", async ({
  page,
}) => {
  const session = await page.request.post("/api/session");
  const { csrf_token } = await session.json();
  const previous = await (await page.request.get("/api/aegis/state")).json();
  if (previous.fills.length)
    await expect
      .poll(() => Date.now() / 1000 - previous.fills[0].created_at, {
        timeout: 35000,
        message:
          "Wait for the preserved entry cooldown from earlier browser workflows",
      })
      .toBeGreaterThanOrEqual(31);
  const seeded = await page.request.post("/api/test/aegis/seed-library-entry", {
    headers: { "X-Terminal-CSRF": csrf_token },
  });
  expect(seeded.ok()).toBe(true);
  const outcome = await seeded.json();
  expect(
    outcome.library_signals.some(
      (s: { execution_status: string }) =>
        s.execution_status === "ENTRY_EXECUTED",
    ),
    JSON.stringify(outcome.library_signals),
  ).toBe(true);
  await page.goto("/#/aegis/positions");
  await expect(
    page.getByRole("cell", { name: "WBTC", exact: true }),
  ).toBeVisible();
  const state = await (await page.request.get("/api/aegis/state")).json();
  expect(state.fills[0].origin.strategy_id).toBe("momentum_v1");
  expect(state.positions[0].strategy_id).toBe("momentum_v1");
  await openWorkspace(page, "Strategies");
  for (const name of [
    "Momentum Trading",
    "Mean reversion",
    "Trend Following",
    "Breakout Trading",
    "Arbitrage Detection",
  ])
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  await openWorkspace(page, "Trading Desk");
  await page.getByLabel("HSKSwap analysis asset").selectOption("WBTC");
  await expect(
    page.getByText("Momentum Trading · WBTC / USDT", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("ENTRY_EXECUTED", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("main").getByText("TEST_FIXTURE", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Emergency stop", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Refresh HSKSwap data", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Review and clear stop" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Review and clear stop" }).click();
});
