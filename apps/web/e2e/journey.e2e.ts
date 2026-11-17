import { expect, test } from "@playwright/test";

// Needs the demo seed data. The password differs per deployment, so it comes from the
// environment; the default is the local development seed password.
const EMAIL = process.env.E2E_EMAIL ?? "sunrise.agent@demo.example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "local-dev-password";

test("agent signs in, creates a listing, finds it, submits it, and cleans up", async ({
  page,
}) => {
  const title = `E2E listing ${Date.now()}`;

  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/Working in Sunrise Realty/)).toBeVisible();

  // Create a draft listing on a new property.
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Listings" })
    .click();
  await page.getByRole("link", { name: "New listing" }).click();
  await page.getByLabel("Address line 1").fill("1 End-to-End Lane");
  await page.getByLabel("City").fill("Testville");
  await page.getByLabel("Bedrooms").fill("2");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("List price").fill("12345678");
  await page.getByRole("button", { name: "Create draft listing" }).click();

  // The detail page shows what was saved, read back from the database.
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(
    page.getByText("1 End-to-End Lane, Testville, IN"),
  ).toBeVisible();
  await expect(page.getByText("Draft", { exact: true })).toBeVisible();
  await expect(page.getByText(/Created as Draft/)).toBeVisible();

  // Search finds it among the seeded listings.
  await page.getByRole("link", { name: "← Listings" }).click();
  await page.getByLabel("Search").fill(title);
  await page.getByRole("button", { name: "Search" }).click();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Testville");
  await rows.first().getByRole("link", { name: title }).click();

  // Submit for review. An agent may not approve, so no publish button appears.
  await page.getByRole("button", { name: "Submit for review" }).click();
  await page
    .getByLabel("Reason (optional)")
    .fill("Created by the end-to-end test");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Pending review", { exact: true })).toBeVisible();
  await expect(page.getByText(/Draft → Pending review/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve and publish" }),
  ).toHaveCount(0);

  // Clean up through the UI: withdraw, then archive.
  await page.getByRole("button", { name: "Withdraw" }).click();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Withdrawn", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Archive" }).click();
  await page.getByRole("button", { name: "Confirm archive" }).click();
  await expect(page.getByRole("heading", { name: "Listings" })).toBeVisible();
  await page.getByLabel("Search").fill(title);
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText("No listings match.")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});
