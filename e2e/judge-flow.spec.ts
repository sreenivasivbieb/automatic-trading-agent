import { test, expect } from "@playwright/test";
import { openWorkspace } from "./navigation";

test("judge pipeline and conversational controls share live runtime preferences", async ({
  page,
}) => {
  await page.goto("/#/aegis");
  await page.getByRole("button", { name: "Refresh HSKSwap data" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Closed-Loop Pipeline & Risk Status",
      exact: true,
    }),
  ).toBeVisible();
  const pipeline = page.getByRole("list", { name: "Closed-loop pipeline" });
  await expect(pipeline.getByRole("listitem")).toHaveCount(5);
  await expect(pipeline).toContainText("On-Chain Data Analysis");
  await expect(
    page.getByText("AI Engine: Deterministic Fallback", { exact: true }),
  ).toBeVisible();
  const configurations = await (
    await page.request.get("/api/strategies")
  ).json();
  await page.getByRole("button", { name: "Open trading assistant" }).click();
  await page
    .getByRole("button", {
      name: "Show my open positions and real-time P&L",
      exact: true,
    })
    .click();
  const messages = page.locator(".aegis-assistant .chat-message.assistant");
  await expect(messages.last()).toContainText("Balances are virtual");
  const before = await (await page.request.get("/api/aegis/state")).json();
  await page
    .getByRole("button", {
      name: "Set position size to 25 USDT and frequency to 30s",
      exact: true,
    })
    .click();
  await expect(page.getByRole("alert")).toContainText("NAV cap");
  const refused = await (await page.request.get("/api/aegis/state")).json();
  expect(refused.params_version).toBe(before.params_version);
  expect(refused.params).toEqual(before.params);
  await page
    .getByRole("button", {
      name: "Switch risk appetite to conservative with a 1.5% stop-loss",
      exact: true,
    })
    .click();
  await expect(messages.last()).toContainText("stop_loss_pct");
  await page
    .getByRole("button", {
      name: "Focus target assets on WHSK and WETH arbitrage spreads",
      exact: true,
    })
    .click();
  await expect(messages.last()).toContainText("target_assets");
  await page
    .getByLabel("Message AEGIS")
    .fill("Set position size to 8 USDT and frequency to 45s");
  await page
    .getByRole("button", { name: "Send to AEGIS", exact: true })
    .click();
  await expect(messages.last()).toContainText("position_size_usdt");
  await page.getByRole("button", { name: "Close AEGIS assistant" }).click();
  await openWorkspace(page, "Strategies");
  await expect(page.getByLabel("AEGIS position budget")).toHaveValue("8");
  await expect(page.getByLabel("AEGIS monitor frequency")).toHaveValue("45");
  await expect(page.getByLabel("AEGIS stop loss")).toHaveValue("1.5");
  expect(await (await page.request.get("/api/strategies")).json()).toEqual(
    configurations,
  );
  await openWorkspace(page, "Agent Observatory");
  await expect(
    page.getByRole("heading", { name: "Decision feed", exact: true }),
  ).toBeVisible();
  const closed = page
    .locator(".aegis-decisions details")
    .filter({ has: page.locator("summary strong", { hasText: "closed loop" }) })
    .first();
  await closed.locator("summary").click();
  await expect(
    closed.getByLabel("Recorded closed-loop steps").locator(".badge"),
  ).toHaveCount(5);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(pipeline.getByRole("listitem").last()).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  // Restore only AEGIS preferences changed here; original strategy configs were never written.
  const { csrf_token } = await (await page.request.post("/api/session")).json();
  const restored = await page.request.put("/api/aegis/settings", {
    headers: { "X-Terminal-CSRF": csrf_token },
    data: {
      expected_version: (
        await (await page.request.get("/api/aegis/state")).json()
      ).params_version,
      patch: before.params,
    },
  });
  expect(restored.ok()).toBe(true);
});
