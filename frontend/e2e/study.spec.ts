import { expect, seed, signIn, test } from "./fixtures";

test("flashcards: open a deck, flip, grade, and ask", async ({ page }) => {
  await page.goto("/study");
  await expect(page.getByRole("heading", { name: "Flashcards from every lecture" })).toBeVisible();
  await signIn(page, "student@example.com", "/study");

  await expect(page.getByRole("heading", { name: "Choose a deck on the left" })).toBeVisible();
  const decks = page.getByRole("complementary", { name: "Decks" });
  const deck = decks.getByRole("button", { name: /L1 · Shortest Paths/ });
  await expect(deck).toContainText("new");
  await deck.click();
  await expect(page).toHaveURL(new RegExp(`lecture=${seed.lecture_id}`));

  const card = page.getByRole("region", { name: "Card" });
  await expect(card.getByText("Question", { exact: true })).toBeVisible({ timeout: 30_000 });
  const counter = card.getByText(/^card 1 of (\d+)/);
  await expect(counter).toBeVisible();
  const total = Number((await counter.innerText()).match(/of (\d+)/)![1]);
  expect(total).toBeGreaterThanOrEqual(2);

  // space flips, the answer links back to the moment
  await page.keyboard.press("Space");
  await expect(card.getByText("Answer", { exact: true })).toBeVisible();
  const watch = card.getByRole("link", { name: /Watch where this was taught/ });
  await expect(watch).toHaveAttribute("href", new RegExp(`/watch/${seed.lecture_id}\\?t=\\d+`));

  // buttons show when each card comes back
  const rates = page.getByRole("group", { name: "How well did you know it?" });
  await expect(rates.getByRole("button", { name: /Again 1m · 1/ })).toBeVisible();
  await expect(rates.getByRole("button", { name: /Good 1d · 3/ })).toBeVisible();
  await page.keyboard.press("3");
  await expect(card.getByText(`card 2 of ${total}`)).toBeVisible();
  await expect(decks.getByRole("button", { name: /L1 · Shortest Paths/ })).toContainText(
    `${total - 1} due`,
  );

  // "again" puts the card back in this session
  await card.getByRole("button", { name: "Show answer" }).click();
  await rates.getByRole("button", { name: /^Again/ }).click();
  await expect(card.getByText(`card 3 of ${total + 1}`)).toBeVisible();

  // work through the rest with the mouse
  for (let left = total; left > 0; left--) {
    const counter = await card.getByText(/^card \d+ of/).innerText();
    await card.getByRole("button", { name: "Show answer" }).click();
    await rates.getByRole("button", { name: /^Easy/ }).click();
    await expect(card.getByText(counter, { exact: true })).toHaveCount(0);
    if (await card.getByText("All caught up").isVisible()) break;
  }
  await expect(card.getByText("All caught up")).toBeVisible();
  await expect(decks.getByRole("button", { name: /L1 · Shortest Paths/ })).toContainText("done");

  // ask: an answer with timestamps, and an honest "not covered"
  await page
    .getByLabel("Ask about this lecture")
    .fill("why must weights be non negative for dijkstra");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.getByText(/Quoted from the lecture|Answer · from this lecture/);
  await expect(answer).toBeVisible();
  const cite = page
    .locator("form")
    .getByRole("link", { name: /^\d+:\d\d$/ })
    .first();
  await expect(cite).toHaveAttribute("href", new RegExp(`/watch/${seed.lecture_id}\\?t=\\d+`));

  await page.getByLabel("Ask about this lecture").fill("what is the capital of france");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText("Not covered")).toBeVisible();
  await page.getByRole("link", { name: "Search the whole course" }).click();
  await expect(page).toHaveURL(/\/search\?q=what/);
});
