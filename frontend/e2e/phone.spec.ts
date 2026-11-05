import { expect, seed, test } from "./fixtures";

// 390 px wide: nothing scrolls sideways and the main controls are reachable.
for (const path of [
  "/",
  "/search?q=dijkstra",
  `/watch/${seed.lecture_id}`,
  "/study",
  "/upload",
  "/signin",
]) {
  test(`fits a phone: ${path}`, async ({ page }) => {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const wide = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(wide).toBeLessThanOrEqual(0);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  });
}

test("phone search and jump", async ({ page }) => {
  await page.goto("/search?q=relax%20an%20edge");
  const first = page.getByRole("region", { name: "Results" }).getByRole("link").first();
  await first.tap();
  await expect(page).toHaveURL(/\/watch\//);
  await expect(page.getByRole("button", { name: "Play (K)" })).toBeVisible();
});
