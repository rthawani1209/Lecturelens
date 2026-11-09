-- Fill-in-the-blank decks are gone (they blanked words out of small talk). Drop the
-- ones already made so opening the lecture writes real cards instead.
DELETE FROM decks WHERE mode = 'cloze';
ALTER TABLE decks ALTER COLUMN mode SET DEFAULT 'claude';
