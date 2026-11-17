import { expect, test } from "@playwright/test";

// Phase C journey. Needs the demo seed and a running worker.
const EMAIL = process.env.E2E_EMAIL ?? "sunrise.agent@demo.example.com";
const PASSWORD = process.env.E2E_PASSWORD ?? "local-dev-password";

test("agent runs the workflow, comments, sees it on the monitor, and cleans up", async ({
  page,
}) => {
  const title = `E2E workflow ${Date.now()}`;

  await page.goto("/");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/Working in Sunrise Realty/)).toBeVisible();

  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Listings" })
    .click();
  await page.getByRole("link", { name: "New listing" }).click();
  await page.getByLabel("Address line 1").fill("2 Workflow Way");
  await page.getByLabel("City").fill("Mumbai");
  await page.getByLabel("Bedrooms").fill("2");
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("List price").fill("15000000");
  await page.getByRole("button", { name: "Create draft listing" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();

  // Without photos nothing waits for review, so the run finishes on its own.
  await page.getByRole("button", { name: "Run workflow" }).click();
  await expect(page.getByText("Finished.")).toBeVisible({ timeout: 45_000 });
  const steps = page.getByRole("list", { name: "Workflow steps" });
  await expect(steps).toContainText("Read the photos: Skipped");
  await expect(steps).toContainText("Estimate value: Finished");

  // A team comment and a private note.
  await page.getByLabel("Comment", { exact: true }).fill("Ready for photos.");
  await page.getByRole("button", { name: "Post comment" }).click();
  await expect(
    page.getByRole("list", { name: "Comments" }).getByText("Ready for photos."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Show activity" }).click();
  await expect(
    page
      .getByRole("list", { name: "Activity" })
      .getByText(/started the workflow/),
  ).toBeVisible();

  // The run is on the monitor.
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Monitor" })
    .click();
  await page.getByLabel("Show").selectOption("");
  await expect(page.getByRole("link", { name: title }).first()).toBeVisible();

  // Clean up: archive the draft.
  await page.getByRole("link", { name: title }).first().click();
  await page.getByRole("button", { name: "Archive" }).click();
  await page.getByRole("button", { name: "Confirm archive" }).click();
  await expect(page.getByRole("heading", { name: "Listings" })).toBeVisible();
});
