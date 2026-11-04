-- Decks per lecture, an AI call log for limits, and content hashes for re-upload dedupe.
ALTER TABLE decks ADD COLUMN lecture_id uuid REFERENCES lectures(id) ON DELETE CASCADE;
ALTER TABLE decks ADD COLUMN mode text NOT NULL DEFAULT 'cloze'; -- claude | cloze
CREATE UNIQUE INDEX decks_user_lecture_idx ON decks (user_id, lecture_id);

ALTER TABLE cards ADD COLUMN t_s double precision;
ALTER TABLE cards ADD COLUMN position int NOT NULL DEFAULT 0;

CREATE TABLE ai_calls (
    id          bigserial PRIMARY KEY,
    user_id     uuid REFERENCES users(id) ON DELETE SET NULL,
    kind        text NOT NULL,          -- ask | cards
    tokens      int NOT NULL DEFAULT 0, -- input + output
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ai_calls_user_idx ON ai_calls (user_id, at);
CREATE INDEX ai_calls_at_idx ON ai_calls (at);

-- Re-uploading a video the course already has points at the existing lecture.
ALTER TABLE lectures ADD COLUMN source_sha256 text;
CREATE INDEX lectures_course_sha_idx ON lectures (course_id, source_sha256);

-- sign-in links are rate limited per address
CREATE INDEX login_tokens_email ON login_tokens (email, expires_at);
