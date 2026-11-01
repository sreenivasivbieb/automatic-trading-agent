import { expect, type Page } from "@playwright/test";

export async function openWorkspace(page: Page, name: string) {
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  if (!(await navigation.isVisible()))
    await page.getByRole("button", { name: "Toggle navigation" }).click();
  const primary = navigation.getByRole("button", { name, exact: true });
  if (await primary.count()) {
    await primary.click();
    return;
  }
  await navigation
    .getByRole("button", { name: "Settings", exact: true })
    .click();
  const tools = page.locator("details").filter({
    has: page.locator("summary", { hasText: "More tools and setup" }),
  });
  await expect(tools).toBeVisible();
  if ((await tools.getAttribute("open")) === null)
    await tools.locator("summary").click();
  await tools.getByRole("link", { name, exact: true }).click();
}
