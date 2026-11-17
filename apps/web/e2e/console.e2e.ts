import { expect, type Page, test } from "@playwright/test";

// Sprint 20: dashboard, audit log, platform page, phone and tablet layouts, keyboard
// and offline behaviour. Needs the demo seed data, like journey.e2e.ts.
const PASSWORD = process.env.E2E_PASSWORD ?? "local-dev-password";
const AGENT = process.env.E2E_EMAIL ?? "sunrise.agent@demo.example.com";
const ADMIN = process.env.E2E_ADMIN_EMAIL ?? "sunrise.admin@demo.example.com";
const PLATFORM =
  process.env.E2E_PLATFORM_EMAIL ?? "platform.admin@demo.example.com";

async function signIn(page: Page, email: string) {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

/** No sideways scrolling of the whole page; wide tables scroll inside their own box. */
async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test("administrator reads the dashboard and filters the audit log", async ({
  page,
}) => {
  await signIn(page, ADMIN);
  await expect(
    page.getByRole("article", { name: "Policy findings to review" }),
  ).toBeVisible();
  await expect(page.getByText("Failed background jobs")).toBeVisible();

  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();

  await page.getByLabel("Area").selectOption("listing.");
  const actions = page.locator("tbody tr td:nth-child(3)");
  await expect(actions.first()).toHaveText(/^listing\./);
  for (const text of await actions.allTextContents())
    expect(text).toMatch(/^listing\./);

  // Choose the first person in the list; every row shown is then by them, or none are.
  await page.getByLabel("Area").selectOption("");
  const person = page.getByLabel("Person");
  const name = (await person.locator("option").nth(1).textContent())!;
  const filtered = page.waitForResponse((r) =>
    r.url().includes("actor_user_id="),
  );
  await person.selectOption({ label: name });
  await filtered;
  await expect(
    page.locator("tbody tr").first().or(page.getByText("No events match.")),
  ).toBeVisible();
  for (const who of await page
    .locator("tbody tr td:nth-child(2)")
    .allTextContents())
    expect(who).toBe(name);
});

test("an agent's dashboard has no admin parts and the audit page is refused", async ({
  page,
}) => {
  await signIn(page, AGENT);
  await expect(
    page.getByRole("article", { name: "My listings" }),
  ).toBeVisible();
  await expect(
    page.getByRole("article", { name: "Policy findings to review" }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Audit" })).toHaveCount(0);
  await page.goto("/#/audit");
  await expect(
    page.getByText("Only administrators see the audit log."),
  ).toBeVisible();
});

test("platform administrator lists organisations and works in one", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Email").fill(PLATFORM);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Platform" }).click();
  const table = page.getByRole("table", { name: "Organisations" });
  await expect(table).toContainText("Harbour Homes");
  await page.getByRole("button", { name: "Work in Harbour Homes" }).click();
  await expect(page.getByText(/Working in Harbour Homes/)).toBeVisible();
});

test("keyboard: the first Tab reaches the skip link, which jumps to the content", async ({
  page,
}) => {
  await signIn(page, AGENT);
  // Fresh page load: after signing in, Chrome continues Tab order from the removed form.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main#content")).toBeFocused();
});

test.describe("phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("the menu folds the navigation and every main page fits the screen", async ({
    page,
  }) => {
    await signIn(page, AGENT);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav).toBeHidden();
    await expectNoPageOverflow(page);

    await page.getByRole("button", { name: "Menu" }).click();
    await expect(nav).toBeVisible();
    await nav.getByRole("link", { name: "Listings" }).click();
    await expect(nav).toBeHidden();
    await expect(page.locator("tbody tr").first()).toBeVisible();
    await expectNoPageOverflow(page);

    await page.locator("tbody tr a").first().click();
    await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
    await expectNoPageOverflow(page);

    for (const name of ["Monitor", "Notifications", "Profile"]) {
      await page.getByRole("button", { name: "Menu" }).click();
      await nav.getByRole("link", { name: new RegExp(`^${name}`) }).click();
      await expect(nav).toBeHidden();
      await expectNoPageOverflow(page);
    }
  });
});

test.describe("tablet", () => {
  test.use({ viewport: { width: 768, height: 1024 } });

  test("navigation is visible and pages fit the screen", async ({ page }) => {
    await signIn(page, ADMIN);
    await expect(page.getByRole("button", { name: "Menu" })).toBeHidden();
    await expectNoPageOverflow(page);
    for (const name of ["Listings", "Review queue", "Audit", "Members"]) {
      await page
        .getByRole("navigation", { name: "Main" })
        .getByRole("link", { name, exact: true })
        .click();
      await expect(
        page.getByRole("heading", { level: 2 }).first(),
      ).toBeVisible();
      await expectNoPageOverflow(page);
    }
  });
});

test("offline: a banner shows and failed requests say why", async ({
  page,
  context,
}) => {
  await signIn(page, AGENT);
  await context.setOffline(true);
  await expect(
    page.getByText(/You are offline\. What is on screen/),
  ).toBeVisible();

  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: /^Notifications/ })
    .click();
  await expect(page.getByRole("alert").first()).toContainText(
    "You are offline. Try again when the connection is back.",
  );

  await context.setOffline(false);
  await expect(
    page.getByText(/You are offline\. What is on screen/),
  ).toBeHidden();
});

test("the installed app shell opens offline (production build only)", async ({
  page,
  context,
}) => {
  await page.goto("/");
  const dev = await page.locator('script[src="/@vite/client"]').count();
  test.skip(dev > 0, "The service worker registers only in production builds.");

  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload(); // now controlled by the service worker
  await context.setOffline(true);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "AI-Native MLS" }),
  ).toBeVisible();
  await expect(
    page.getByText(/You are offline\. What is on screen/),
  ).toBeVisible();
  await context.setOffline(false);
});
