import { expect, test } from "@playwright/test";
import { ADMIN, CUSTOMER, SUPPORT, signIn } from "./helpers";

// Captures docs/images from the running app. Enabled only with SCREENSHOTS=1 (make screenshots).
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture documentation screenshots");

const OUT = "../docs/images";

test("staff and customer screens", async ({ browser }) => {
  for (const [label, viewport] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]] as const) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await page.goto("/");
    await page.screenshot({ path: `${OUT}/${label}-landing.png` });
    await signIn(page, ADMIN);
    const run = await page.request.get("/api/investigations?status=completed").then((r) => r.json());
    for (const [name, path] of [["overview", "/app"], ["inbox", "/app/inbox"], ["incidents", "/app/incidents"], ["knowledge", "/app/knowledge"], ["engineering", "/app/engineering"]] as const) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `${OUT}/${label}-${name}.png`, fullPage: label === "desktop" });
    }
    if (run.items?.length) {
      await page.goto(`/app/investigations/${run.items[0].id}`);
      await expect(page.getByText("Event timeline")).toBeVisible();
      await page.screenshot({ path: `${OUT}/${label}-investigation.png`, fullPage: label === "desktop" });
    }
    await ctx.close();
    const cctx = await browser.newContext({ viewport });
    const cpage = await cctx.newPage();
    await signIn(cpage, CUSTOMER);
    await cpage.waitForLoadState("networkidle");
    await cpage.screenshot({ path: `${OUT}/${label}-portal.png`, fullPage: label === "desktop" });
    await cctx.close();
  }
  expect(SUPPORT).toBeTruthy();
});
