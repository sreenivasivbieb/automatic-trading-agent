import { expect, test } from "@playwright/test";

test("entry selections disclose blocked engines and supported engine toggles stay versioned and immediate", async ({
  page,
}) => {
  await page.goto("/#/aegis/strategies");
  await expect(
    page.getByRole("heading", { name: "Strategy engines", exact: true }),
  ).toBeVisible();
  const fieldset = page.locator("fieldset").filter({
    has: page.getByText("Active entry strategies", { exact: true }),
  });
  await expect(fieldset.getByRole("checkbox")).toHaveCount(7);
  await expect(fieldset).toContainText("Unavailable · research only");
  await expect(
    page.getByRole("button", {
      name: "Enable Arbitrage Detection engine",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByText(
      "Compatible executable buy/sell routes, fees, gas and a funded settlement model are not configured.",
      { exact: false },
    ),
  ).toBeVisible();
  const before = await (await page.request.get("/api/aegis/state")).json();
  const engine = before.library_catalog.find(
    (s: { id: string }) => s.id === "momentum_v1",
  );
  const action = engine.enabled ? "Disable" : "Enable";
  await page
    .getByRole("button", {
      name: `${action} Momentum Trading engine`,
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", {
      name: `${engine.enabled ? "Enable" : "Disable"} Momentum Trading engine`,
      exact: true,
    }),
  ).toBeEnabled();
  const changed = await (await page.request.get("/api/aegis/state")).json();
  const current = changed.library_catalog.find(
    (s: { id: string }) => s.id === "momentum_v1",
  );
  expect(current.enabled).toBe(!engine.enabled);
  expect(current.version).toBe(engine.version + 1);
  expect(changed.params.active_strategies).toEqual(
    before.params.active_strategies,
  );
  if (!current.enabled)
    await expect(
      fieldset
        .getByLabel("Momentum Trading entries", { exact: true })
        .locator(".."),
    ).toContainText("Blocked · engine disabled");
  await page
    .getByRole("button", {
      name: `${engine.enabled ? "Enable" : "Disable"} Momentum Trading engine`,
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", {
      name: `${action} Momentum Trading engine`,
      exact: true,
    }),
  ).toBeEnabled();
});
