import { expect, test } from "@playwright/test";

// Captures the first-run experience of an *operational* instance: a newly registered organization with no data.
// Run against a scratch operational stack only (never a working database). Enabled with SCREENSHOTS_OPERATIONAL=1.
test.skip(!process.env.SCREENSHOTS_OPERATIONAL, "set SCREENSHOTS_OPERATIONAL=1 against a scratch operational stack");

const OUT = process.env.SHOT_OUT ?? "../docs/images";

test("operational first run: empty, no sample data, no banner", async ({ browser, baseURL }) => {
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: width >= 1280 ? 900 : 844 } });
    const page = await ctx.newPage();
    const instance = await page.request.get("/api/instance").then((r) => r.json());
    expect(instance.data_mode).toBe("operational");
    const email = `owner-${width}@first-run.example`;
    const r = await page.request.post("/api/auth/register", {
      headers: { "X-Requested-With": "relayops", Origin: baseURL ?? "" },
      data: { name: "First Owner", email, password: "a-long-first-run-password", organization_name: `First Run Co ${width}` },
    });
    expect(r.ok()).toBeTruthy();
    for (const [name, path] of [["op-home", "/app"], ["op-inbox", "/app/inbox"], ["op-settings", "/app/settings"],
      ["op-success", "/app/success"], ["op-analytics", "/app/analytics"]] as const) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.getByText(/Demo instance/)).toHaveCount(0);
      await expect(page.getByText(/^Loading/)).toHaveCount(0, { timeout: 20_000 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${name} at ${width}px scrolls horizontally`).toBeLessThanOrEqual(0);
      await page.screenshot({ path: `${OUT}/${name}-${width}.png`, fullPage: width >= 1280 });
    }
    await ctx.close();
  }
});
