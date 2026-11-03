import { expect, test, type Page } from "@playwright/test";

async function analyze(page: Page) {
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "Run analysis", exact: true }).click(),
  ]);
  await expect(
    page.getByRole("button", { name: "Run analysis", exact: true }),
  ).toBeEnabled();
  return response.json();
}

test("configuration errors stay visible in the dialog and valid saves persist", async ({
  page,
}) => {
  await page.goto("/#/strategies");
  const configure = page
    .getByRole("button", { name: "Configure", exact: true })
    .first();
  await configure.click();
  const dialog = page.getByRole("dialog");
  const field = dialog.getByLabel("Fast EMA period");
  const original = await field.inputValue();
  await field.fill("999");
  await dialog
    .getByRole("button", { name: "Save strategy configuration" })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    /fast period|fast period|config/i,
  );
  await expect(dialog.getByRole("alert")).toContainText(/less than|smaller/i);
  await field.fill(original === "8" ? "9" : "8");
  const changed = await field.inputValue();
  await dialog
    .getByRole("button", { name: "Save strategy configuration" })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(configure).toBeEnabled();
  await configure.click();
  await expect(dialog.getByLabel("Fast EMA period")).toHaveValue(changed);
  await dialog.getByLabel("Fast EMA period").fill(original);
  await dialog
    .getByRole("button", { name: "Save strategy configuration" })
    .click();
  await expect(dialog).toHaveCount(0);
  await page
    .getByRole("button", { name: "Configure", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("dialog").getByText("Research-only engine", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save strategy configuration" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Close requirements" }).click();
});

test("new analysis replaces a selected historical run and history failures can retry", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#/observatory");
  const first = await analyze(page);
  await analyze(page);
  await page
    .getByRole("cell", { name: first.id.slice(0, 12), exact: true })
    .click();
  await expect(page.locator(".run-strip")).toContainText(first.id.slice(0, 12));
  await expect(
    page.getByRole("button", { name: "Return to latest analysis" }),
  ).toBeVisible();
  const latest = await analyze(page);
  await expect(page.locator(".run-strip")).toContainText(
    latest.id.slice(0, 12),
  );
  await page.route("**/api/history/runs?*", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { message: "History temporarily unavailable" } },
    }),
  );
  await page.reload();
  await expect(page.locator(".inline-action-error")).toContainText(
    "History temporarily unavailable",
  );
  await page.unroute("**/api/history/runs?*");
  await page.getByRole("button", { name: "Retry run history" }).click();
  await expect(
    page.getByRole("button", { name: "Retry run history" }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a failed response after recording analysis still refreshes the recorded run", async ({
  page,
}) => {
  let savedRun = "";
  await page.goto("/#/observatory");
  await page.route("**/api/runs", async (route) => {
    const response = await route.fetch();
    savedRun = (await response.json()).id;
    await route.fulfill({
      status: 503,
      json: { error: { message: "Response lost after recording analysis" } },
    });
  });
  await page.getByRole("button", { name: "Run analysis", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Response lost after recording analysis",
  );
  await expect(
    page.getByRole("button", { name: "Run analysis", exact: true }),
  ).toBeEnabled();
  expect(savedRun).not.toBe("");
  await expect(page.locator(".run-strip")).toContainText(savedRun.slice(0, 12));
});

test("risk rejection explains the missing quote and keeps authorization unavailable", async ({
  page,
}) => {
  await page.goto("/#/observatory");
  const run = await analyze(page);
  expect(run.intent).toBeTruthy();
  const blocked = {
    ...run.intent,
    state: "REJECTED",
    quote: null,
    risk: {
      ...run.intent.risk,
      verdict: "REJECTED",
      approved_notional: "0",
      reasons: ["New execution is disabled while paused or stopped."],
      checks: run.intent.risk.checks.map((c: { code: string }) =>
        c.code === "EMERGENCY_OR_PAUSE"
          ? { ...c, passed: false, actual: "True" }
          : c,
      ),
    },
  };
  await page.route("**/api/history/intents?*", (route) =>
    route.fulfill({
      json: { items: [blocked], total: 1, limit: 20, offset: 0 },
    }),
  );
  await page.goto("/#/executions");
  await expect(
    page.getByRole("heading", { name: "Trade blocked before quoting" }),
  ).toBeVisible();
  await expect(page.locator(".execution-blocked")).toContainText(
    "New execution is disabled while paused or stopped",
  );
  await expect(page.locator(".execution-blocked")).toContainText(
    "Requested notional",
  );
  await expect(
    page.getByRole("button", { name: "Authorize simulated fill", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".swap-preview")).toHaveCount(0);
  for (const width of [1504, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
});

test("news fetches its own stories when the shared dashboard has no headlines", async ({
  page,
}) => {
  await page.route("**/api/dashboard", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({
      response,
      json: {
        ...body,
        news: {
          ...body.news,
          articles: [],
          status: "UNAVAILABLE",
          error: "Dashboard feed snapshot unavailable",
        },
      },
    });
  });
  await page.goto("/#/news");
  await expect(page.locator(".news-row")).toHaveCount(4);
  await expect(page.locator(".news-feed-status .badge")).toHaveText("FIXTURE");
  await expect(
    page.getByText("Dashboard feed snapshot unavailable", { exact: true }),
  ).toHaveCount(0);
});

test("research chat displays a failed command and accepts the next command", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open trading assistant", exact: true })
    .click();
  await expect(
    page.getByText("Command mode · no API key required", { exact: true }),
  ).toBeVisible();
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { message: "Command service unavailable; try again" } },
    }),
  );
  await page.getByLabel("Message assistant").fill("Show my exposure");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".chat-message.error")).toContainText(
    "Command service unavailable",
  );
  await page.unroute("**/api/chat");
  await page.getByLabel("Message assistant").fill("Show my exposure");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "Simulation equity",
  );
});

test("a configuration save waits for a fresh snapshot after an in-flight dashboard poll", async ({
  page,
}) => {
  await page.goto("/#/strategies");
  const configure = page
    .getByRole("button", { name: "Configure", exact: true })
    .first();
  await configure.click();
  const original = await page
    .getByRole("dialog")
    .getByLabel("Fast EMA period")
    .inputValue();
  const target = original === "8" ? "9" : "8";
  let release!: () => void;
  let captured!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const ready = new Promise<void>((resolve) => {
    captured = resolve;
  });
  let hold = true;
  await page.route("**/api/dashboard", async (route) => {
    const response = await route.fetch();
    if (hold) {
      hold = false;
      captured();
      await gate;
    }
    await route.fulfill({ response });
  });
  try {
    await ready;
    await page.getByRole("dialog").getByLabel("Fast EMA period").fill(target);
    const saved = page.waitForResponse(
      (r) =>
        r.url().includes("/api/strategies/") && r.request().method() === "PUT",
    );
    await page
      .getByRole("button", { name: "Save strategy configuration" })
      .click();
    expect((await saved).ok()).toBe(true);
    release();
    await expect(configure).toBeEnabled();
    await configure.click();
    await expect(
      page.getByRole("dialog").getByLabel("Fast EMA period"),
    ).toHaveValue(target);
    await page.getByRole("dialog").getByLabel("Fast EMA period").fill(original);
    await page
      .getByRole("button", { name: "Save strategy configuration" })
      .click();
  } finally {
    release();
  }
});
