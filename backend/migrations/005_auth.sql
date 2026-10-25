-- Sign-in: one-time email links, browser sessions, Google accounts, and
-- in-progress uploads. Only hashes of tokens are stored, so a leaked table
-- can't be used to log in.
ALTER TABLE users ADD COLUMN google_sub text UNIQUE;

CREATE TABLE login_tokens (
    token_hash  bytea PRIMARY KEY,
    email       text NOT NULL,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz
);

CREATE TABLE sessions (
    token_hash  bytea PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

CREATE TABLE uploads (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename    text NOT NULL,
    size        bigint NOT NULL,
    received    bigint NOT NULL DEFAULT 0,
    done        boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
