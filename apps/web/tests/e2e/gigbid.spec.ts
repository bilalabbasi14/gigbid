import { expect, test } from "@playwright/test";
import { MockApi, THREAD } from "./mock-api";

test("onboarding: a new user picks a profile, marketplace, budget and lands in the inbox", async ({ page }) => {
  const api = new MockApi({ onboarded: false });
  await api.install(page);
  await page.goto("/inbox");
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByText("Step 1 of 4")).toBeVisible();
  await page.getByText("Data analyst").click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Connect a marketplace")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("portfolio-summary")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Weekly Connects budget").fill("40");
  await page.getByLabel("First saved search").fill("power bi");
  await page.getByRole("button", { name: "Finish" }).click();
  await expect(page).toHaveURL(/\/inbox/);
  expect(api.state.settings).toMatchObject({ persona: "data_analyst", weekly_connects_budget: 40, onboarded: true });
});

test("approve: the studio shows evidence behind claims and submits once on approval", async ({ page }) => {
  const api = new MockApi();
  await api.install(page);
  await page.goto(`/studio/${THREAD}`);
  await expect(page.getByRole("heading", { name: "Build a RAG chatbot over PDFs" })).toBeVisible();
  // evidence on hover/focus
  const cite = page.getByTestId("citation").first();
  await cite.focus();
  await expect(page.getByRole("tooltip")).toContainText("Legal contract RAG bot");
  await expect(page.getByTestId("dry-run")).toContainText("8");
  await page.getByRole("button", { name: /Approve and submit/ }).click();
  await expect(page.getByTestId("approval-result")).toContainText("Proposal submitted");
  expect(api.state.decisions).toEqual([{ action: "approve" }]);
});

test("reject: a reason is required and sent with the decision", async ({ page }) => {
  const api = new MockApi();
  await api.install(page);
  await page.goto(`/studio/${THREAD}`);
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  const confirm = page.getByRole("button", { name: "Reject proposal" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Why are you rejecting this?").fill("budget too low for the scope");
  await confirm.click();
  await expect(page.getByTestId("approval-result")).toContainText("Proposal rejected");
  expect(api.state.decisions).toEqual([{ action: "reject", reason: "budget too low for the scope" }]);
});

test("edit: the edited draft is re-checked and returned for a final approval", async ({ page }) => {
  const api = new MockApi();
  await api.install(page);
  await page.goto(`/studio/${THREAD}`);
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const editor = page.getByTestId("draft-editor");
  await editor.fill((await editor.inputValue()).replace("I would start", "I will start"));
  await page.getByRole("button", { name: "Save edit and re-check" }).click();
  await expect(page.getByText("Your edit passed compliance")).toBeVisible();
  await expect(page.getByTestId("evidence-text").first()).toContainText("I will start");
  expect(api.state.decisions[0]).toMatchObject({ action: "edit" });
  expect(String(api.state.decisions[0].edited_cover_letter)).toContain("I will start");
  await page.getByRole("button", { name: /Approve and submit/ }).click();
  await expect(page.getByTestId("approval-result")).toContainText("Proposal submitted");
});

test("degraded mode: an unreachable marketplace shows a banner and the app keeps working", async ({ page }) => {
  const api = new MockApi({ marketplaceDown: true });
  await api.install(page);
  await page.goto("/inbox");
  await expect(page.getByTestId("degraded-banner")).toContainText("Marketplace unavailable");
  await expect(page.getByTestId("job-list")).toContainText("Build a RAG chatbot over PDFs");
  api.state.marketplaceDown = false;
  await page.reload();
  await expect(page.getByTestId("degraded-banner")).toHaveCount(0);
});

test("auth: signed-out users are sent to sign in and back", async ({ page }) => {
  const api = new MockApi({ signedIn: false });
  await api.install(page);
  await page.goto("/pipeline");
  await expect(page).toHaveURL(/\/login\?next=%2Fpipeline/);
  await page.getByLabel("Email").fill("reviewer@gigbid.local");
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign in" }).last().click();
  await expect(page).toHaveURL(/\/pipeline/);
  await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
});

test("keyboard: the pending approval is reachable without a mouse", async ({ page }) => {
  const api = new MockApi();
  await api.install(page);
  await page.goto("/inbox");
  const review = page.getByRole("link", { name: "Review proposal" });
  await review.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/studio/${THREAD}`));
});
