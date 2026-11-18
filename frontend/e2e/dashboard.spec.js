// Real-browser journeys. Each test registers its own fresh user, so tests never
// depend on each other or on leftover data.
import { expect, test } from "@playwright/test";

const PASSWORD = "correct horse battery staple";

async function register(page) {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Username").fill("tester");
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.getByLabel("Repeat password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/");
  return email;
}

async function startGoal(page, goal) {
  await page.getByLabel("Goal").fill(goal);
  await page.getByRole("button", { name: "Run agent" }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f]{32}$/);
}

test("an anonymous visitor is sent to login, then back to the page they wanted", async ({ page }) => {
  await page.goto("/memories");
  await expect(page).toHaveURL("/login?next=%2Fmemories");
});

test("a new user runs a goal and reads the report", async ({ page }) => {
  await register(page);
  await startGoal(page, "Calculate the average of 45000, 52000 and 61000 and write a report");

  await expect(page.getByText("Completed").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Average salary report" })).toBeVisible();
  await expect(page.locator(".markdown strong", { hasText: "52,666.67" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tool calls (2)" })).toBeVisible();
});

test("approve what you see: the exact email is shown, nothing is pre-approved", async ({ page }) => {
  await register(page);
  await startGoal(page, "Calculate the average salary and email it to my mentor");

  const panel = page.getByRole("form", { name: "Approval required" });
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("arguments-t2")).toContainText("mentor@example.com");
  await expect(panel.getByRole("button", { name: "Reject all" })).toBeVisible(); // safe default

  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: "Approve 1" }).click();

  await expect(page.getByText("Completed").first()).toBeVisible();
  await expect(panel).toBeHidden();
});

test("tokens stay out of reach of page scripts; reload keeps you in; logout ends it", async ({ page, context }) => {
  await register(page);

  // Nothing in web storage, and the refresh cookie is invisible to JavaScript...
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  expect(await page.evaluate(() => document.cookie)).not.toContain("refresh_token");
  // ...yet the browser holds it, httpOnly and SameSite=Strict, only for /auth/session.
  const cookie = (await context.cookies()).find((c) => c.name === "refresh_token");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/auth/session" });

  await page.reload(); // the in-memory access token is gone: silent refresh via the cookie
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/login/); // (may carry ?next= back to where you were)
  await page.goto("/");
  await expect(page).toHaveURL("/login?next=%2F");
});

test("memories can be added and forgotten", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: "Memories" }).click();

  await page.getByLabel("New memory").fill("I prefer remote jobs");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("I prefer remote jobs")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept()); // the "Forget ...?" confirmation
  await page.getByRole("button", { name: "Forget" }).click();
  await expect(page.getByText("Nothing remembered yet")).toBeVisible();
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("a failed script load can never put the password in the URL", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Email").fill("nojs@example.com");
    await page.getByLabel("Username").fill("nojs");
    await page.getByLabel(/^Password/).fill(PASSWORD);
    await page.getByLabel("Repeat password").fill(PASSWORD);
    await page.getByRole("button", { name: "Create account" }).click();

    expect(page.url()).not.toContain("password");
    expect(page.url()).not.toContain(encodeURIComponent(PASSWORD).slice(0, 10));
  });
});
