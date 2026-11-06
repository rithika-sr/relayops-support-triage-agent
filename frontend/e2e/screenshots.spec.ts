import { expect, test, type Page } from "@playwright/test";
import { ADMIN, CUSTOMER, signIn } from "./helpers";

// Captures docs/images from a running *demo* instance (make demo-dev). Enabled only with SCREENSHOTS=1.
// Every capture must show the demo banner, so no screenshot can be mistaken for real customer data.
// SHOT_WIDTHS limits widths (comma-separated); SHOT_ONLY limits screens (comma-separated names).
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture documentation screenshots");

const OUT = process.env.SHOT_OUT ?? "../docs/images";
const WIDTHS = (process.env.SHOT_WIDTHS ?? "1440,1280,768,390").split(",").map(Number);
const ONLY = process.env.SHOT_ONLY ? new Set(process.env.SHOT_ONLY.split(",")) : null;
const BANNER = /Demo instance: every record here is synthetic sample data/;
const heightFor = (w: number) => (w >= 1280 ? 900 : w >= 768 ? 1024 : 844);

async function shot(page: Page, name: string, width: number) {
  if (ONLY && !ONLY.has(name)) return;
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(BANNER).first()).toBeVisible();
  await expect(page.getByText(/^Loading/)).toHaveCount(0, { timeout: 20_000 });
  await page.screenshot({ path: `${OUT}/${name}-${width}.png`, fullPage: width >= 1280 });
}

test("staff and customer screens at four widths", async ({ browser }) => {
  test.setTimeout(900_000);
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: heightFor(width) } });
    const page = await ctx.newPage();
    await signIn(page, ADMIN);
    // Load the committed evaluation reports so Model quality shows measured runs, not an empty state.
    await page.request.post("/api/evaluations/import", { headers: { "x-csrf-token": (await ctx.cookies()).find((c) => c.name === "relayops_csrf")?.value ?? "", origin: new URL(page.url()).origin } });
    await shot(page, "home", width);
    await page.goto("/app/inbox?queue=open&sort=priority");
    await shot(page, "inbox", width);
    const pick = async (status: string) =>
      (await page.request.get(`/api/investigations?status=${status}`).then((r) => r.json())).items?.[0];
    const run = (await pick("awaiting_review")) ?? (await pick("completed"));
    if (run) {
      await page.goto(`/app/tickets/${run.ticket_id}`);
      await shot(page, "ticket", width);
      await page.goto(`/app/investigations/${run.id}`);
      await shot(page, "investigation", width);
      await page.getByRole("tab", { name: /Evidence/ }).click();
      await shot(page, "investigation-evidence", width);
    }
    const done = await pick("completed");
    if (done) {
      await page.goto(`/app/investigations/${done.id}`);
      const review = page.getByText("Review status").first();
      if (await review.count()) await review.scrollIntoViewIfNeeded();
      await shot(page, "review", width);
    }
    for (const [name, path] of [
      ["analytics", "/app/analytics"], ["success-accounts", "/app/success"], ["success-retention", "/app/success/retention"],
      ["success-opportunities", "/app/success/opportunities"], ["success-experiments", "/app/success/experiments"],
      ["incidents", "/app/incidents"], ["engineering", "/app/engineering"], ["knowledge", "/app/knowledge"],
      ["playbooks", "/app/playbooks"], ["artifacts", "/app/artifacts"], ["evaluations", "/app/evaluations"],
      ["settings", "/app/settings"], ["integrations", "/app/settings/integrations"], ["service-hours", "/app/settings/service-hours"],
    ] as const) {
      await page.goto(path);
      await shot(page, name, width);
    }
    const pdfDoc = await page.request.get("/api/knowledge").then((r) => r.json())
      .then((docs: { id: string; slug: string }[]) => docs.find((d) => d.slug === "scanned-export-guide"));
    if (pdfDoc) {
      await page.goto(`/app/knowledge?doc=${pdfDoc.id}`);
      await shot(page, "knowledge-pdf", width);
    }
    await ctx.close();

    const cctx = await browser.newContext({ viewport: { width, height: heightFor(width) } });
    const cpage = await cctx.newPage();
    await signIn(cpage, CUSTOMER);
    await shot(cpage, "portal", width);
    await cpage.goto("/portal/help");
    await cpage.getByLabel("Search Help").fill("export rows limit");
    await cpage.getByRole("button", { name: "Search" }).click();
    await expect(cpage.getByRole("listitem").first()).toBeVisible({ timeout: 60_000 });
    await shot(cpage, "portal-help", width);
    await cctx.close();
  }
});
