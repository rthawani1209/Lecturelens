import { expect, seed, signIn, test } from "./fixtures";

const clock = (page: import("@playwright/test").Page) =>
  page.locator("video").evaluate((v: HTMLVideoElement) => v.currentTime);

test("player controls, transcript, frames and notes", async ({ page }) => {
  await page.goto(`/watch/${seed.lecture_id}?t=5`);
  await expect(page.getByRole("heading", { name: /Shortest Paths/ })).toBeVisible();
  const video = page.locator("video");
  await expect(video)
    .toHaveJSProperty("readyState", 4, { timeout: 20_000 })
    .catch(() => undefined);
  await expect.poll(() => clock(page)).toBeGreaterThanOrEqual(4.5);

  // K plays and pauses, L and J jump 10 s
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("k");
  await expect(page.getByRole("button", { name: "Pause (K)" })).toBeVisible();
  await page.keyboard.press("k");
  await expect(page.getByRole("button", { name: "Play (K)" })).toBeVisible();
  const before = await clock(page);
  await page.keyboard.press("l");
  await expect.poll(() => clock(page)).toBeGreaterThan(before + 9);
  await page.keyboard.press("j");
  await expect.poll(() => clock(page)).toBeLessThan(before + 1);
  await page.getByRole("button", { name: "Forward 10 seconds (L)" }).click();
  await page.getByRole("button", { name: "Back 10 seconds (J)" }).click();
  await page.getByRole("button", { name: "Play (K)" }).click();
  await page.getByRole("button", { name: "Pause (K)" }).click();

  // speed cycles through the steps
  await page.getByRole("button", { name: "Playback speed 1x" }).click();
  await expect(page.getByRole("button", { name: /Playback speed 1\.25x/ })).toBeVisible();
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.playbackRate)).toBe(1.25);

  // captions start on
  await page.getByRole("button", { name: "Hide captions (C)" }).click();
  await expect(page.getByRole("button", { name: "Show captions (C)" })).toBeVisible();
  await page.keyboard.press("c");
  await expect(page.getByRole("button", { name: "Hide captions (C)" })).toBeVisible();
  // they sit above the control bar, not under it
  const caption = page.getByTestId("caption");
  await expect(caption).toBeVisible();
  const capBox = (await caption.boundingBox())!;
  const seekBox = (await page.getByRole("slider", { name: "Seek" }).boundingBox())!;
  expect(capBox.y + capBox.height).toBeLessThanOrEqual(seekBox.y);

  // transcript: find, then click a line to seek
  const transcript = page.getByRole("region", { name: "Transcript" });
  // (the seed is a synthetic voice, so stick to words whisper hears reliably)
  await transcript.getByPlaceholder("Find in this lecture").fill("smallest estimate");
  const line = transcript.getByRole("button", { name: /smallest estimate/i }).first();
  await line.click();
  await expect
    .poll(() => clock(page))
    .toBeGreaterThanOrEqual(Math.floor(seed.slides[2].start_s) - 1);
  await transcript.getByPlaceholder("Find in this lecture").fill("zebra crossing");
  await expect(transcript.getByText("Not said in this lecture.")).toBeVisible();
  await transcript.getByPlaceholder("Find in this lecture").fill("");

  // frames strip and scope band seek too
  await page.getByRole("group", { name: "Boards and slides" }).getByRole("button").first().click();
  await expect.poll(() => clock(page)).toBeLessThan(3);
  await page.getByRole("region", { name: "What's on screen" }).getByRole("button").last().click();
  await expect.poll(() => clock(page)).toBeGreaterThan(seed.slides[3].start_s - 3);

  // notes need an account
  await expect(
    page.getByRole("region", { name: "Your notes" }).getByRole("link", { name: /sign in/i }),
  ).toBeVisible();
  await signIn(page, "watcher@example.com", `/watch/${seed.lecture_id}?t=12`);
  const notes = page.getByRole("region", { name: "Your notes" });
  await expect(notes.getByText("No notes yet. Press N to add one.")).toBeVisible();
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("n");
  await expect(notes.locator("textarea")).toBeFocused();
  await notes.locator("textarea").fill("relaxation lowers the estimate");
  await notes.getByRole("button", { name: /Save note at/ }).click();
  await expect(notes.getByText("relaxation lowers the estimate")).toBeVisible();
  await page.reload();
  await expect(notes.getByText("relaxation lowers the estimate")).toBeVisible();
  await notes.getByRole("button", { name: /Delete note at/ }).click();
  await expect(notes.getByText("No notes yet. Press N to add one.")).toBeVisible();
});

test("a lecture that doesn't exist says so", async ({ page, allowConsole }) => {
  allowConsole(/404/);
  await page.goto("/watch/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("heading", { name: /doesn't exist/ })).toBeVisible();
  await page.getByRole("link", { name: "Back to all lectures" }).click();
  await expect(page).toHaveURL(/\/watch$/);
});
