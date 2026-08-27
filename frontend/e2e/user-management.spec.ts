import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { expectLoginRejected, login, logout } from "./fixtures/authentication";

const ADMIN_USERNAME = "admin";
const ADMIN_PASSWORD = "admin";

function uniqueUsername(prefix: string, testInfo: TestInfo) {
  return `${prefix}-${testInfo.workerIndex}-${testInfo.retry}-${Date.now()}`;
}

async function openUserManagement(page: Page) {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Manage users" }).click();
  await expect(page).toHaveURL("/admin/users");
  await expect(page.getByText("Manage accounts and roles.")).toBeVisible();
}

async function createOperator(page: Page, username: string, password: string) {
  await page.getByRole("button", { name: "Add user" }).click();
  const dialog = page.getByRole("dialog", { name: "Add user" });
  await dialog.getByLabel("Username").fill(username);
  await dialog.getByLabel("Password").fill(password);
  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(
    page.getByRole("row").filter({ hasText: username }),
  ).toBeVisible();
}

async function deleteUser(page: Page, username: string) {
  await page.getByRole("button", { name: `Delete ${username}` }).click();
  const dialog = page.getByRole("alertdialog", {
    name: `Delete '${username}'?`,
  });
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("row").filter({ hasText: username })).toHaveCount(
    0,
  );
}

test("admin can create and delete an operator", async ({ page }, testInfo) => {
  const username = uniqueUsername("e2e-created", testInfo);
  const password = "operator-test-password";

  await login(page, ADMIN_USERNAME, ADMIN_PASSWORD);
  await openUserManagement(page);
  await createOperator(page, username, password);
  await deleteUser(page, username);

  await logout(page);
  await expectLoginRejected(page, username, password);
});

test("operator can change their own password", async ({ page }, testInfo) => {
  const username = uniqueUsername("e2e-password", testInfo);
  const oldPassword = "old-test-password";
  const newPassword = "new-test-password";

  await login(page, ADMIN_USERNAME, ADMIN_PASSWORD);
  await openUserManagement(page);
  await createOperator(page, username, oldPassword);
  await logout(page);

  await login(page, username, oldPassword);
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Change password" }).click();

  const dialog = page.getByRole("dialog", { name: "Change password" });
  await dialog.getByLabel("Current password").fill(oldPassword);
  await dialog.getByLabel("New password", { exact: true }).fill(newPassword);
  await dialog.getByLabel("Confirm new password").fill(newPassword);
  await dialog.getByRole("button", { name: "Change password" }).click();

  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Account menu" }),
  ).toBeVisible();
  await logout(page);

  await expectLoginRejected(page, username, oldPassword);
  await login(page, username, newPassword);
  await logout(page);

  await login(page, ADMIN_USERNAME, ADMIN_PASSWORD);
  await openUserManagement(page);
  await deleteUser(page, username);
});

test("the last admin cannot be demoted, disabled, or deleted", async ({
  page,
}) => {
  await login(page, ADMIN_USERNAME, ADMIN_PASSWORD);
  await openUserManagement(page);

  const adminRow = page.getByRole("row").filter({ hasText: ADMIN_USERNAME });
  const roleSelect = adminRow.getByRole("combobox");
  const enabledSwitch = adminRow.getByRole("switch");

  await expect(roleSelect).toHaveText("admin");
  await roleSelect.click();
  await page.getByRole("option", { name: "operator" }).click();
  await expect(page.getByText("Cannot remove the last admin")).toBeVisible();
  await expect(roleSelect).toHaveText("admin");

  await expect(enabledSwitch).toBeChecked();
  await enabledSwitch.click();
  await expect(page.getByText("Cannot remove the last admin")).toBeVisible();
  await expect(enabledSwitch).toBeChecked();

  await expect(
    adminRow.getByRole("button", { name: `Delete ${ADMIN_USERNAME}` }),
  ).toBeDisabled();
});
