import { expect, signIn, test } from "./fixtures";

test("sign in, sign out, and the theme sticks", async ({ page }) => {
  // the production build sends a content security policy; any violation on any page
  // shows up as a console error, which fails the test
  const res = await page.goto("/");
  expect(res?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await page.getByRole("link", { name: "Sign in" }).first().click();
  await expect(page).toHaveURL(/\/signin/);
  await signIn(page, "ada@example.com", "/search");
  await expect(page).toHaveURL(/\/search/);

  const account = page.getByRole("button", { name: "Account: ada@example.com" });
  await account.click();
  await expect(page.getByRole("menu")).toContainText("ada@example.com");
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("link", { name: "Sign in" }).first()).toBeVisible();
  await page.reload();
  await expect(account).toHaveCount(0);

  const html = page.locator("html");
  const start = await html.getAttribute("data-theme");
  const toggle = page.getByRole("button", { name: /Switch to (light|dark) theme/ });
  await toggle.click();
  await expect(html).not.toHaveAttribute("data-theme", start ?? "dark");
  const flipped = await html.getAttribute("data-theme");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", flipped!);
  await page.getByRole("button", { name: /Switch to (light|dark) theme/ }).click();
  await expect(html).toHaveAttribute("data-theme", start ?? "dark");

  // the main nav reaches every screen
  for (const [name, path] of [
    ["Watch", "/watch"],
    ["Study", "/study"],
    ["Upload", "/upload"],
    ["Search", "/search"],
  ]) {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
  }
});

test("the demo button signs in without an email", async ({ page }) => {
  await page.goto("/signin?next=/upload");
  await page.getByRole("button", { name: "Try it without an account" }).click();
  await expect(page).toHaveURL(/\/upload$/);
  await expect(page.getByRole("button", { name: /Account: demo-.*@demo\.invalid/ })).toBeVisible();
});
