import { expect, test } from "@playwright/test";
import { login, logout } from "./fixtures/authentication";

test("admin can sign in and sign out", async ({ page }) => {
  await login(page, "admin", "admin");
  await expect(
    page.getByRole("button", { name: "Account menu" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await expect(page.getByText("admin · admin")).toBeVisible();
  await page.keyboard.press("Escape");
  await logout(page);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});
