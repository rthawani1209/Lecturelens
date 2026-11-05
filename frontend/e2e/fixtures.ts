import { readFileSync } from "node:fs";
import { expect, test as base, type Page } from "@playwright/test";

export type Seed = {
  course_id: string;
  lecture_id: string;
  mp4: string;
  slides: { title: string; spoken: string; start_s: number; end_s: number; kind: string }[];
};

export const seed: Seed = JSON.parse(readFileSync(process.env.E2E_SEED ?? "", "utf8"));

/** Sign in through the real email-link flow; the API prints the link (no SMTP in tests). */
export async function signIn(page: Page, email: string, next = "/") {
  await page.goto(`/signin?next=${encodeURIComponent(next)}`);
  await page.getByLabel(/email/i).fill(email);
  await page.getByRole("button", { name: /link/i }).click();
  await expect(page.getByText(/check your email|sent/i).first()).toBeVisible();
  let link: string | undefined;
  for (let i = 0; i < 20 && !link; i++) {
    const log = readFileSync(process.env.E2E_API_LOG ?? "", "utf8");
    const all = [...log.matchAll(/(http\S+\/signin\/verify\?token=\S+)/g)];
    const mine = log.lastIndexOf(`email to ${email}`);
    link = all.filter((m) => (m.index ?? 0) > mine).at(0)?.[1];
    if (!link) await page.waitForTimeout(250);
  }
  if (!link) throw new Error(`no sign-in link for ${email}`);
  await page.goto(link);
  await page.waitForURL((u) => !u.pathname.startsWith("/signin"));
}

/** Every test fails on a console error or page crash, unless it says it expects one. */
export const test = base.extend<{ allowConsole: (re: RegExp) => void }>({
  allowConsole: [
    async ({ page }, use) => {
      const allowed: RegExp[] = [];
      const errors: string[] = [];
      const failed: string[] = []; // the browser's console line doesn't say which URL
      page.on("response", (r) => {
        if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
      });
      page.on("console", (m) => {
        const text = /^Failed to load resource/.test(m.text())
          ? `${m.text()} [${failed.join(", ")}]`
          : m.text();
        if (m.type() === "error" && !allowed.some((re) => re.test(text))) errors.push(text);
      });
      page.on("pageerror", (e) => errors.push(String(e)));
      await use((re) => allowed.push(re));
      expect(errors, "console errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
