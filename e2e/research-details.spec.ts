import { expect, test } from "@playwright/test";

test("recorded research brief exposes source context, risk plan and verified local receipt", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#/observatory");
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Run analysis", exact: true }).click(),
  ]);
  await expect(
    page.getByRole("button", { name: "Run analysis", exact: true }),
  ).toBeEnabled();
  const report = page.getByRole("button", { name: "Read evidence report" });
  await expect(report).toBeVisible();
  await report.click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText("Snapshot integrity verified", { exact: true }),
  ).toBeVisible();
  for (const title of [
    "Market & technicals",
    "News context",
    "Model debate",
    "Risk & position plan",
    "Source evidence",
    "Evidence gaps & risk flags",
  ]) {
    await expect(
      dialog.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
  }
  await expect(dialog.locator(".brief-citations li")).toHaveCount(4);
  await expect(
    dialog.getByText(/Optional model debate did not complete/),
  ).toBeVisible();
  await expect(dialog.getByText(/Local report integrity only/)).toBeVisible();
  for (const width of [1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(12);
    expect(bounds!.y).toBeGreaterThanOrEqual(8);
    expect(
      await dialog.evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(report).toBeFocused();
  expect(errors).toEqual([]);
});

test("research report never verifies content that disagrees with its receipt", async ({
  page,
}) => {
  await page.route("**/api/runs/*/brief", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: { ...body, rationale: "Changed after snapshot creation" },
    });
  });
  await page.goto("/#/observatory");
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Run analysis", exact: true }).click(),
  ]);
  await expect(
    page.getByRole("button", { name: "Run analysis", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Read evidence report" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByText("Snapshot integrity unverified", { exact: true }),
  ).toBeVisible();
});

test("finishing a new analysis closes the previous run's report instead of carrying it over", async ({
  page,
}) => {
  await page.goto("/#/observatory");
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Run analysis", exact: true }).click(),
  ]);
  await expect(
    page.getByRole("button", { name: "Run analysis", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Read evidence report" }),
  ).toBeVisible();
  const previous = (await (await page.request.get("/api/dashboard")).json())
    .latest_run.id;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/runs", async (route) => {
    await gate;
    await route.continue();
  });
  try {
    await page
      .getByRole("button", { name: "Run analysis", exact: true })
      .click();
    await page.getByRole("button", { name: "Read evidence report" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    const finished = page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    );
    release();
    const current = await (await finished).json();
    expect(current.id).not.toBe(previous);
    await expect(
      page.getByRole("button", { name: "Run analysis", exact: true }),
    ).toBeEnabled();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByRole("button", { name: "Read evidence report" }).click();
    const brief = await (
      await page.request.get(`/api/runs/${current.id}/brief`)
    ).json();
    await expect(
      page.getByRole("dialog").locator(".brief-integrity code"),
    ).toHaveText(brief.receipt.digest);
  } finally {
    release();
  }
});

test("executable HSKSwap quote details expire, remain read-only and reset with asset selection", async ({
  page,
}) => {
  await page.goto("/#/aegis/markets");
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/aegis/check") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Refresh HSKSwap data" }).click(),
  ]);
  await expect(
    page.getByRole("button", { name: "Inspect executable routes" }),
  ).toBeVisible();
  const before = await (await page.request.get("/api/aegis/state")).json();
  await page.getByRole("button", { name: "Inspect executable routes" }).click();
  const details = page.getByRole("region", {
    name: "Executable HSKSwap route details",
  });
  await expect(
    details.getByRole("heading", { name: "USDT → WHSK", exact: true }),
  ).toBeVisible();
  await expect(
    details.getByText("Highest quoted output", { exact: true }),
  ).toBeVisible();
  await details.getByText("Pool telemetry, fee tiers & exact amounts").click();
  await expect(
    details.getByText("sqrt price x96", { exact: true }),
  ).toBeVisible();
  for (const width of [1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
  const after = await (await page.request.get("/api/aegis/state")).json();
  expect(after.fills).toEqual(before.fills);
  expect(after.params).toEqual(before.params);
  await page.clock.install();
  await page.clock.fastForward(21000);
  await expect(
    details.getByText("EXPIRED", { exact: true }).first(),
  ).toBeVisible();
  await page.getByLabel("HSKSwap analysis asset").selectOption("WETH");
  await expect(
    details.getByRole("heading", { name: "USDT → WHSK", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Inspect executable routes" }).click();
  await expect(
    details.getByRole("heading", { name: "USDT → WETH", exact: true }),
  ).toBeVisible();
});

test("route quote failure is visible and retry obtains an actual backend response", async ({
  page,
}) => {
  await page.goto("/#/aegis/markets");
  await page.getByRole("button", { name: "Refresh HSKSwap data" }).click();
  await expect(
    page.getByRole("button", { name: "Inspect executable routes" }),
  ).toBeVisible();
  await page.route("**/api/aegis/market-details?*", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { message: "Pinned RPC snapshot unavailable" } },
    }),
  );
  await page.getByRole("button", { name: "Inspect executable routes" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Pinned RPC snapshot unavailable",
  );
  await expect(
    page.getByText("Highest quoted output", { exact: true }),
  ).toHaveCount(0);
  await page.unroute("**/api/aegis/market-details?*");
  await page.getByRole("button", { name: "Inspect executable routes" }).click();
  await expect(
    page.getByRole("heading", { name: "USDT → WHSK", exact: true }),
  ).toBeVisible();
});
