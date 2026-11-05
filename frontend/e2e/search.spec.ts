import { expect, seed, test } from "./fixtures";

test("search from the home page jumps to the right second", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Graph Algorithms Demo/ })).toBeVisible();
  await page.getByLabel("Ask the course").fill("why does dijkstra need non negative weights");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page).toHaveURL(/\/search\?q=/);

  const results = page.getByRole("region", { name: "Results" });
  await expect(results.getByRole("heading", { name: /moments? in 1 lecture/ })).toBeVisible();
  const first = results.getByRole("link").first();
  await expect(first).toContainText(/dijkstra/i);

  // the Dijkstra slide is the third one in the seed lecture
  const dijkstra = seed.slides[2];
  await first.click();
  await expect(page).toHaveURL(new RegExp(`/watch/${seed.lecture_id}\\?t=\\d+`));
  const t = Number(new URL(page.url()).searchParams.get("t"));
  expect(t).toBeGreaterThanOrEqual(Math.floor(dijkstra.start_s) - 2);
  expect(t).toBeLessThanOrEqual(Math.ceil(dijkstra.end_s));
});

test("modes, filters, keyboard and empty states", async ({ page }) => {
  await page.goto("/search");
  await expect(
    page.getByRole("heading", { name: "Find the moment it was explained." }),
  ).toBeVisible();

  // "/" focuses the box from anywhere
  await page.locator("body").click();
  await page.keyboard.press("/");
  await expect(page.getByLabel("Ask the course")).toBeFocused();
  await page.keyboard.type("relax an edge");
  await page.keyboard.press("Enter");
  const results = page.getByRole("region", { name: "Results" });
  await expect(results.getByRole("link").first()).toBeVisible();

  for (const mode of ["Hybrid", "Keyword", "Meaning"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
    await expect(page.getByRole("button", { name: mode, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page).toHaveURL(
      new RegExp(mode === "Meaning" ? "q=" : `mode=${mode.toLowerCase()}`),
    );
    await expect(results).toHaveAttribute("aria-busy", "false");
  }

  // filters narrow by what was on screen; every seed frame is a slide (the CLIP
  // fallback tagger, no TF Serving here), so Slides keeps hits and Diagram has none
  await page.getByRole("button", { name: "Slides", exact: true }).click();
  await expect(page).toHaveURL(/tag=slide/);
  await expect(results.getByRole("link").first()).toContainText(/relax/i);
  for (const tag of ["Code", "Whiteboard", "Professor", "Diagram"]) {
    await page.getByRole("button", { name: tag, exact: true }).click();
    await expect(page.getByRole("button", { name: tag, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  }
  await expect(results.getByText(/No diagram frames/i)).toBeVisible();
  await page.keyboard.press("1"); // number keys pick filters
  await expect(page.getByRole("button", { name: "All frames" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // arrow keys move the selection, enter opens it
  await page.locator("body").click();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/watch\//);

  await page.goto("/search?q=photosynthesis%20in%20plants&mode=keyword");
  await expect(page.getByText(/Nothing in these lectures matches that/)).toBeVisible();

  // the example queries are buttons that run a search
  await page.goto("/search");
  await page.getByRole("button", { name: /why can't dijkstra/ }).click();
  await expect(page).toHaveURL(/q=why/);
});
