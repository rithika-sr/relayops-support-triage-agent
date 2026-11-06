import { expect, test, type Page } from "@playwright/test";
import { ADMIN, CUSTOMER, signIn } from "./helpers";

// Captures docs/images from a running *demo* instance (make demo-dev). Enabled only with SCREENSHOTS=1.
// Every capture must show the demo banner, so no screenshot can be mistaken for real customer data.
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture documentation screenshots");

const OUT = "../docs/images";
const WIDTHS = [1440, 1280, 768, 390] as const;
const BANNER = /Demo instance: every record here is synthetic sample data/;

async function shot(page: Page, name: string, width: number) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(BANNER).first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/${name}-${width}.png`, fullPage: width >= 1280 });
}

test("staff and customer screens at four widths", async ({ browser }) => {
  test.setTimeout(600_000);
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: width >= 1280 ? 900 : width >= 768 ? 1024 : 844 } });
    const page = await ctx.newPage();
    await signIn(page, ADMIN);
    await shot(page, "home", width);
    await page.goto("/app/inbox?queue=open&sort=priority");
    await shot(page, "inbox", width);
    const runs = await page.request.get("/api/investigations?status=awaiting_review").then((r) => r.json());
    const done = await page.request.get("/api/investigations?status=completed").then((r) => r.json());
    const run = runs.items?.[0] ?? done.items?.[0];
    if (run) {
      await page.goto(`/app/tickets/${run.ticket_id}`);
      await shot(page, "ticket", width);
      await page.goto(`/app/investigations/${run.id}`);
      await shot(page, "investigation", width);
    }
    for (const [name, path] of [
      ["analytics", "/app/analytics"], ["success-accounts", "/app/success"], ["success-retention", "/app/success/retention"],
      ["success-opportunities", "/app/success/opportunities"], ["knowledge", "/app/knowledge"], ["engineering", "/app/engineering"],
      ["service-hours", "/app/settings/service-hours"], ["integrations", "/app/settings/integrations"],
    ] as const) {
      await page.goto(path);
      await shot(page, name, width);
    }
    await ctx.close();
    const cctx = await browser.newContext({ viewport: { width, height: 900 } });
    const cpage = await cctx.newPage();
    await signIn(cpage, CUSTOMER);
    await shot(cpage, "portal", width);
    await cpage.goto("/portal/help");
    await cpage.getByLabel("Search Help").fill("export rows limit");
    await cpage.getByRole("button", { name: "Search" }).click();
    await expect(cpage.getByRole("button").filter({ hasText: /export/i }).first()).toBeVisible();
    await shot(cpage, "portal-help", width);
    await cctx.close();
  }
});
