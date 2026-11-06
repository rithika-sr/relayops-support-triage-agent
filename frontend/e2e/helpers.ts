import { expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

interface Creds { accounts: Record<string, { password: string; role: string }> }

export function password(email: string): string {
  const path = process.env.E2E_CREDENTIALS ?? resolve(__dirname, "../../.local/demo-credentials.json");
  const creds = JSON.parse(readFileSync(path, "utf8")) as Creds;
  const entry = creds.accounts[email];
  if (!entry) throw new Error(`no seeded credentials for ${email}; run make seed`);
  return entry.password;
}

export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password(email));
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(email.startsWith("customer") ? /\/portal/ : /\/app/);
}

export const CUSTOMER = "customer@northstar.local";
export const SUPPORT = "support@relayops.local";
export const ADMIN = "admin@relayops.local";
