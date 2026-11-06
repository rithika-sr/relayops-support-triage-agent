import { expect, test } from "@playwright/test";
import { CUSTOMER, SUPPORT, signIn } from "./helpers";

test("customer report goes through support review and becomes a visible reply", async ({ browser }) => {
  const subject = `E2E export failure ${Date.now()}`;

  // 1. Customer files a ticket in the portal.
  const customer = await browser.newPage();
  await signIn(customer, CUSTOMER);
  await customer.getByLabel("Subject").fill(subject);
  await customer.getByLabel("What happened?").fill("Exporting the Fleet Planning project (80,000 tasks) fails with EXPORT_500.");
  await customer.getByLabel("Area (optional)").selectOption("exports");
  await customer.getByLabel("Error code (optional)").fill("EXPORT_500");
  await customer.getByRole("button", { name: "Submit ticket" }).click();
  await expect(customer.getByRole("heading", { name: subject })).toBeVisible();
  const ticketUrl = customer.url();
  const ticketId = ticketUrl.split("/").pop()!;
  await expect(customer.getByText("Replies appear here once a team member has reviewed them")).toBeVisible();

  // 2. Support finds it in the inbox with an account and a computed target, and launches an investigation.
  const support = await browser.newPage();
  await signIn(support, SUPPORT);
  await support.goto(`/app/inbox?q=${encodeURIComponent(subject)}`);
  const row = support.getByRole("row", { name: new RegExp(subject) });
  await expect(row).toContainText("Northstar Logistics");
  await expect(row).toContainText(/left/);
  await row.getByRole("link").click();
  await support.getByLabel("Playbook").selectOption("bug");
  await support.getByRole("button", { name: "Launch investigation" }).click();
  await expect(support).toHaveURL(/\/app\/investigations\/run_/);

  // 3. The run pauses for review with a verified proposal.
  await expect(support.getByText("awaiting review").first()).toBeVisible({ timeout: 200_000 });
  await expect(support.getByText("Verification ·")).toBeVisible();
  // The draft is not visible to the customer yet.
  await customer.reload();
  await expect(customer.getByText("TaskFlow support")).toHaveCount(0);

  // 4. Reviewer edits (new version), then approves the exact version.
  const draft = support.getByLabel("Customer reply draft");
  await draft.fill("Thanks for the details. Our team is aware of this export problem on large projects. Please use Prepare in background from the Export menu as a workaround.");
  await support.getByRole("button", { name: /Save edit as v2/ }).click();
  await expect(support.getByRole("button", { name: "Approve v2" })).toBeEnabled();
  await support.getByRole("button", { name: "Approve v2" }).click();
  await expect(support.getByText(/Action receipt/)).toBeVisible({ timeout: 60_000 });
  await expect(support.getByText("No email or external write", { exact: false }).first()).toBeVisible();

  // 5. The customer now sees exactly the approved text.
  await customer.reload();
  await expect(customer.getByText("TaskFlow support")).toBeVisible();
  await expect(customer.getByText("Please use Prepare in background from the Export menu as a workaround.")).toBeVisible();

  // 6. Customers cannot reach staff data, even by URL.
  const api = await customer.request.get(`/api/tickets/${ticketId}`);
  expect(Object.keys(await api.json()).sort()).toEqual(["incidents", "messages", "ticket"]);
  expect((await customer.request.get("/api/investigations")).status()).toBe(403);
  await customer.goto("/app/inbox");
  await expect(customer).toHaveURL(/\/portal/);
});

test("logout revokes the session", async ({ page }) => {
  await signIn(page, SUPPORT);
  await page.getByRole("button", { name: "Sign out" }).first().click();
  await expect(page).toHaveURL(/\/login/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login/);
});

test("wrong password shows a clear error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("support@relayops.local");
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("email or password is incorrect")).toBeVisible();
});
