import {expect, type Page, test} from "@playwright/test";

async function register(page: Page, label: string) {
  await page.goto("/en/register");
  await page.getByLabel("Email").fill(`browser-${label}-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("browser-test-password");
  await page.getByRole("button", {name: "Create account"}).click();
  await expect(page.getByText("Access token saved in this browser.")).toBeVisible();
}

async function createTextTask(page: Page) {
  await page.goto("/en/tasks/new");
  await expect(page.getByLabel("Task type").locator("option")).toHaveCount(12);
  await expect(page.getByLabel("Task type")).toHaveValue("text.summarize");
  await page.getByLabel("Title").fill("Browser-created summary task");
  await page.getByLabel("Public summary").fill("Summarize a public test passage.");
  await page.getByLabel("text *", {exact: true}).fill("WorkWorld keeps provider Agents outside the platform boundary.");
  await page.getByLabel("max_characters").fill("1000");
  await page.getByLabel(/I acknowledge that the winning Agent/).check();
  await page.getByRole("button", {name: "Create task"}).click();
  const result = page.locator("form").first().locator("pre");
  await expect(result).toContainText('"id": "task_');
  const document = JSON.parse(await result.innerText()) as {id: string};
  return document.id;
}

test("all twelve published schemas drive a task form that creates a valid task", async ({page}) => {
  await register(page, "schema-owner");
  const taskId = await createTextTask(page);

  expect(taskId).toMatch(/^task_[0-9a-f]+$/);
});

test("a different signed-in user cannot read a private matching task", async ({browser}) => {
  const ownerContext = await browser.newContext();
  const ownerPage = await ownerContext.newPage();
  await register(ownerPage, "private-owner");
  const taskId = await createTextTask(ownerPage);

  const strangerContext = await browser.newContext();
  const strangerPage = await strangerContext.newPage();
  await register(strangerPage, "private-stranger");
  await strangerPage.goto(`/en/tasks/${taskId}`);
  await strangerPage.getByRole("button", {name: "Load task"}).click();
  await expect(strangerPage.getByText(/task_not_found/)).toBeVisible();

  await ownerContext.close();
  await strangerContext.close();
});
