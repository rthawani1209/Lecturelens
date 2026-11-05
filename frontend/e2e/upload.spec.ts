import { readFileSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, seed, signIn, test } from "./fixtures";

// The YouTube import is not hit for real here: the link points at a video id that
// doesn't exist, so the fetch stage fails the same way offline or online.
// docs/CLAIMS.md says so; real imports are tested in .github/workflows/youtube.yml.

const video = readFileSync(seed.mp4);
const file = (name: string, buffer: Buffer, mimeType = "video/mp4") => ({ name, mimeType, buffer });

test.describe.configure({ mode: "serial" });

test("upload survives a dropped connection, a cancel, and ends up searchable", async ({
  page,
  allowConsole,
}) => {
  test.setTimeout(240_000);
  allowConsole(/ERR_CONNECTION_RESET|ERR_FAILED|net::/);
  await signIn(page, "uploader@example.com", "/upload");

  await expect(page.getByRole("heading", { name: "Add a lecture" })).toBeVisible();
  await page.getByPlaceholder(/Course name/).fill("Uploads Test");
  await page.getByPlaceholder(/Code/).fill("UP 1");
  await page.getByLabel("Week").fill("3");
  await page.locator("#file").setInputFiles(file("shortest-paths.mp4", video));
  await expect(page.getByText("shortest-paths.mp4")).toBeVisible();
  await expect(page.getByLabel("Lecture title")).toHaveValue("shortest paths");
  await page.getByLabel("Lecture title").fill("Shortest paths, uploaded");

  // kill the third chunk's connection twice; the client asks where it got to and carries on
  let killed = 0;
  await page.route("**/api/uploads/**", async (route) => {
    const range = route.request().headers()["content-range"] ?? "";
    if (range.startsWith(`bytes ${2 * 32 * 1024}-`) && killed < 2) {
      killed++;
      return route.abort("connectionreset");
    }
    // slow enough to press Cancel part way
    await new Promise((r) => setTimeout(r, 400));
    // Cancel may have aborted the request while we waited
    return route.continue().catch(() => undefined);
  });
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  const bar = page.getByRole("progressbar", { name: "Upload progress" });
  await expect.poll(() => killed).toBe(2);
  await expect
    .poll(async () => Number(await bar.getAttribute("aria-valuenow")))
    .toBeGreaterThan(30);

  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText(/Paused at \d+%/)).toBeVisible();
  const paused = Number(await bar.getAttribute("aria-valuenow"));
  expect(paused).toBeGreaterThan(30);
  await page.unroute("**/api/uploads/**");
  await page.getByRole("button", { name: "Resume" }).click();

  // live pipeline over server-sent events, through to ready
  await page.waitForURL(/\/upload\?lecture=/);
  const lectureId = new URL(page.url()).searchParams.get("lecture");
  const pipeline = page.getByRole("region", { name: "Processing" });
  await expect(pipeline.getByRole("heading", { name: "Shortest paths, uploaded" })).toBeVisible();
  await expect(pipeline.getByText("✓ ready")).toBeVisible({ timeout: 200_000 });
  await expect(pipeline.getByText("✓ done")).toHaveCount(9);

  await pipeline.getByRole("link", { name: "Search the course" }).click();
  await page.getByLabel("Ask the course").fill("relaxing an edge lowers the distance estimate");
  await page.keyboard.press("Enter");
  const hit = page.getByRole("region", { name: "Results" }).getByRole("link").first();
  await expect(hit).toHaveAttribute("href", new RegExp(`/watch/${lectureId}`));

  // the same file again lands on the same lecture, not a copy
  await page.goto("/upload");
  await page.locator("#file").setInputFiles(file("again.mp4", video));
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await page.waitForURL(new RegExp(`lecture=${lectureId}`));

  // the course's lecture list: watch it, then delete it from there
  await page.goto("/upload");
  const mine = page.getByRole("region", { name: "Your lectures" });
  const row = mine.getByRole("listitem").filter({ hasText: "Shortest paths, uploaded" });
  await expect(row).toContainText("✓ ready");
  await expect(row.getByRole("link", { name: "Watch" })).toHaveAttribute(
    "href",
    `/watch/${lectureId}`,
  );
  await row.getByRole("button", { name: "Delete Shortest paths, uploaded" }).click();
  await row.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(mine).toHaveCount(0); // that was the only lecture
});

test("bad files get a clear answer", async ({ page, allowConsole }) => {
  test.setTimeout(120_000);
  allowConsole(/status of 41[35]/);
  await signIn(page, "checker@example.com", "/upload");
  await page.getByPlaceholder(/Course name/).fill("Bad Files");

  // a PDF renamed .mp4: refused by its first bytes, not its name
  await page
    .locator("#file")
    .setInputFiles(file("notes.mp4", Buffer.from("%PDF-1.7\n" + "x".repeat(5000))));
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "This file isn't a video" }),
  ).toBeVisible();
  await expect(page).not.toHaveURL(/lecture=/);

  // over the size limit (50 MB in this test setup)
  // (a sparse file on disk: Playwright won't take a buffer this big)
  const huge = join(tmpdir(), "huge.mp4");
  writeFileSync(huge, "");
  truncateSync(huge, 51 * 1024 * 1024);
  await page.locator("#file").setInputFiles(huge);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "too big" })).toContainText("50 MB");

  // a real mp4 header with the rest cut off: accepted, then fails in the pipeline
  await page.locator("#file").setInputFiles(file("cut-off.mp4", video.subarray(0, 60_000)));
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  const pipeline = page.getByRole("region", { name: "Processing" });
  await expect(pipeline.getByRole("alert")).toContainText("This file isn't a playable video.", {
    timeout: 60_000,
  });
  await expect(pipeline.getByText("failed", { exact: true }).first()).toBeVisible();

  // retry runs it again (and it fails again, honestly)
  await pipeline.getByRole("button", { name: "Try again" }).click();
  await expect(pipeline.getByRole("alert")).toContainText("This file isn't a playable video.", {
    timeout: 60_000,
  });

  // later, from the course's lecture list: open it again and retry from there
  await page.goto("/upload");
  const mine = page.getByRole("region", { name: "Your lectures" });
  const row = mine.getByRole("listitem").filter({ hasText: "cut off" });
  await expect(row).toContainText("failed");
  await row.getByRole("button", { name: "Try again" }).click();
  await expect(page).toHaveURL(/lecture=/);
  await expect(pipeline.getByRole("alert")).toContainText("This file isn't a playable video.", {
    timeout: 60_000,
  });

  // delete asks first
  await pipeline.getByRole("button", { name: "Delete" }).click();
  await pipeline.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(page).toHaveURL(/\/upload$/);
  await expect(page.getByRole("region", { name: "Processing" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Your lectures" })).toHaveCount(0);
});

test("a YouTube link that can't be fetched fails with a plain message", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, "importer@example.com", "/upload");
  await page.getByPlaceholder(/Course name/).fill("Imports");
  await page.getByLabel("Import from YouTube").fill("https://www.youtube.com/watch?v=zzzzzzzzzz0");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  const pipeline = page.getByRole("region", { name: "Processing" });
  await expect(pipeline.getByRole("alert")).toContainText("Couldn't download this video", {
    timeout: 90_000,
  });
});
