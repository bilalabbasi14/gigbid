import { expect, test } from "@playwright/test";
import { MockApi } from "./mock-api";

test("mobile: navigation collapses into a menu and the inbox fits the screen", async ({ page }) => {
  const api = new MockApi();
  await api.install(page);
  await page.goto("/inbox");
  await expect(page.getByTestId("job-list")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("navigation", { name: "Main mobile" }).getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings/);
  await expect(page.getByRole("navigation", { name: "Main mobile" })).toHaveCount(0);
});
