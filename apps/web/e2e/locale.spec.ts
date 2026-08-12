import {expect, test} from "@playwright/test";

test("browser language selects Chinese and the user can switch to English", async ({browser}) => {
  const context = await browser.newContext({locale: "zh-CN"});
  const page = await context.newPage();

  await page.goto("/");
  await expect(page).toHaveURL(/\/zh$/);
  await expect(page.getByRole("heading", {level: 1})).toHaveText("让可靠的 Agent 完成真实工作。");

  await page.getByRole("link", {name: "English"}).click();
  await expect(page).toHaveURL(/\/en$/);
  await expect(page.getByRole("heading", {level: 1})).toHaveText("Bring capable Agents to real work.");

  await context.close();
});

test("interactive product controls are localized on Chinese routes", async ({page}) => {
  await page.goto("/zh/tasks/new");
  await expect(page.getByLabel("访问令牌")).toBeVisible();
  await expect(page.getByLabel("任务类型")).toBeVisible();
  await expect(page.getByLabel("招募截止时间")).not.toBeVisible();
  await page.getByLabel("分配方式").selectOption("open_call");
  await expect(page.getByLabel("招募截止时间")).toBeVisible();
  await expect(page.getByText("Access token", {exact: true})).toHaveCount(0);
});
