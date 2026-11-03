import { expect, test } from "@playwright/test";

test("research brief content keeps an inset from the panel and wrapped metrics", async ({
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
    page.locator(".research-brief-body .brief-summary"),
  ).toBeVisible();
  for (const width of [1880, 1504, 1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const body = page.locator(".research-brief-body");
    const panel = await body.evaluate((e) =>
      e.parentElement!.getBoundingClientRect().toJSON(),
    );
    for (const child of await body.locator(":scope > div, :scope > p").all()) {
      const box = await child.boundingBox();
      expect(box!.x - panel.x).toBeGreaterThanOrEqual(16);
      expect(panel.right - box!.x - box!.width).toBeGreaterThanOrEqual(16);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
  }
});

test("research desk tabs and expanded market features fit all viewport and ticket sizes", async ({
  page,
}) => {
  await page.goto("/#/desk");
  await expect(page.locator(".desk-chart-panel svg.candles")).toBeVisible();
  for (const width of [1880, 1504, 1280, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const size of [260, 460]) {
      const layout = page.locator(".desk-layout");
      if ((await layout.getAttribute("open")) === null)
        await layout.locator("summary").click();
      await page
        .getByLabel("Execution ticket width")
        .press(size === 260 ? "Home" : "End");
      await expect(page.getByLabel("Execution ticket width")).toHaveValue(
        String(size),
      );
      const features = page.getByText("Measured market features", {
        exact: true,
      });
      if (await features.isVisible()) {
        const details = page.locator(".desk-market-notes details");
        if ((await details.getAttribute("open")) === null)
          await features.click();
        expect(
          await details.evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
        ).toBe(true);
      }
      const buttons = page.locator(".desk-dock-tabs button");
      for (const button of await buttons.all()) {
        const rect = await button.boundingBox();
        expect(rect!.height).toBeGreaterThanOrEqual(40);
        expect(
          await button.evaluate((e) =>
            Number.parseFloat(getComputedStyle(e).fontSize),
          ),
        ).toBeGreaterThanOrEqual(12);
        expect(
          await button.evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
        ).toBe(true);
      }
      const overlaps = await page.locator(".desk-surface").evaluate((e) => {
        const rows = [...e.children]
          .filter((c) => c.checkVisibility())
          .map((c) => c.getBoundingClientRect());
        return rows.some((a, i) =>
          rows
            .slice(i + 1)
            .some(
              (b) =>
                Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
                Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1,
            ),
        );
      });
      expect(overlaps).toBe(false);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      ).toBe(true);
    }
    await page
      .locator(".desk-dock-tabs")
      .getByRole("button", { name: /activity/i })
      .click();
    await expect(
      page
        .locator(".desk-dock-tabs")
        .getByRole("button", { name: /activity/i }),
    ).toHaveClass(/active/);
  }
});
