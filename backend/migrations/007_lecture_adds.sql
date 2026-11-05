-- Every lecture someone adds, kept even after the lecture is deleted, so deleting
-- doesn't hand back today's allowance.
CREATE TABLE lecture_adds (
    user_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lecture_adds_user_idx ON lecture_adds (user_id, at);
CREATE INDEX lecture_adds_at_idx ON lecture_adds (at);
