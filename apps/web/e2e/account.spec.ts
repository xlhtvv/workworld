import {expect, test} from "@playwright/test";

test("a new account receives signup tokens and can claim the daily grant", async ({page}) => {
  const email = `browser-${Date.now()}@example.com`;

  await page.goto("/en/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("browser-test-password");
  await page.getByRole("button", {name: "Create account"}).click();
  await expect(page.getByText("Access token saved in this browser.")).toBeVisible();

  await page.goto("/en/wallet");
  await page.getByRole("button", {name: "Refresh balances"}).click();
  await expect(page.getByRole("heading", {name: "Ledger balances"}).locator("..").getByText(/100000/)).toBeVisible();

  await page.getByRole("button", {name: "Claim daily 10,000 Tokens"}).click();
  await expect(page.getByRole("heading", {name: "Ledger balances"}).locator("..").getByText(/110000/)).toBeVisible();
});
