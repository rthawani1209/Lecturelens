-- Core schema: people, courses, lectures and what the pipeline extracts from them.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text NOT NULL UNIQUE,
    name        text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- A study group shares one library. Every user also gets a personal group,
-- so ownership checks only ever have to ask "is this user in the group?".
CREATE TABLE groups (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    personal    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE group_members (
    group_id    uuid NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        text NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE courses (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id    uuid NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    code        text NOT NULL DEFAULT '',
    title       text NOT NULL,
    term        text NOT NULL DEFAULT '',
    -- openly licensed courses (MIT OCW) are readable without an account
    public      boolean NOT NULL DEFAULT false,
    license     text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX courses_group_idx ON courses (group_id);

-- Words the transcriber should spell right ("Dijkstra", "eigenvalue").
CREATE TABLE course_terms (
    course_id   uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    term        text NOT NULL,
    PRIMARY KEY (course_id, term)
);

CREATE TABLE lectures (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title       text NOT NULL,
    week        int,
    position    int NOT NULL DEFAULT 0,
    duration_s  double precision,
    status      text NOT NULL DEFAULT 'uploading'
                CHECK (status IN ('uploading', 'queued', 'processing', 'ready', 'failed')),
    storage_key text,
    source_url  text,
    summary     text NOT NULL DEFAULT '',
    created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lectures_course_idx ON lectures (course_id, position);

-- ~30s overlapping transcript windows. These are the unit of text search.
CREATE TABLE segments (
    id          bigserial PRIMARY KEY,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    start_s     double precision NOT NULL,
    end_s       double precision NOT NULL,
    speaker     text,
    text        text NOT NULL,
    text_emb    vector(384),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX segments_lecture_idx ON segments (lecture_id, start_s);
CREATE INDEX segments_tsv_idx ON segments USING gin (tsv);
CREATE INDEX segments_emb_idx ON segments USING hnsw (text_emb vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- One row per captured slide / board snapshot.
CREATE TABLE frames (
    id          bigserial PRIMARY KEY,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    t_s         double precision NOT NULL,
    thumb_key   text NOT NULL,
    phash       bigint,
    ocr_text    text NOT NULL DEFAULT '',
    tag         text,
    tag_scores  jsonb,
    clip_emb    vector(512),
    ocr_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', ocr_text)) STORED
);
CREATE INDEX frames_lecture_idx ON frames (lecture_id, t_s);
CREATE INDEX frames_tag_idx ON frames (tag);
CREATE INDEX frames_ocr_idx ON frames USING gin (ocr_tsv);
CREATE INDEX frames_emb_idx ON frames USING hnsw (clip_emb vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE chapters (
    id          bigserial PRIMARY KEY,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    start_s     double precision NOT NULL,
    title       text NOT NULL,
    summary     text NOT NULL DEFAULT ''
);
CREATE INDEX chapters_lecture_idx ON chapters (lecture_id, start_s);

-- One row per (lecture, stage). Workers claim and update these, which is what
-- makes every stage safe to retry.
CREATE TABLE jobs (
    id          bigserial PRIMARY KEY,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    stage       text NOT NULL,
    status      text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'done', 'failed')),
    attempts    int NOT NULL DEFAULT 0,
    progress    real NOT NULL DEFAULT 0,
    error       text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lecture_id, stage)
);

-- Labeled (query, moment) pairs for training and evaluating search.
CREATE TABLE labels (
    id          bigserial PRIMARY KEY,
    query       text NOT NULL,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    start_s     double precision NOT NULL,
    relevance   smallint NOT NULL CHECK (relevance BETWEEN 0 AND 3),
    source      text NOT NULL CHECK (source IN ('hand', 'synthetic')),
    split       text NOT NULL CHECK (split IN ('train', 'val', 'test'))
);

CREATE TABLE model_versions (
    id            bigserial PRIMARY KEY,
    name          text NOT NULL,
    version       int NOT NULL,
    mlflow_run_id text,
    metrics       jsonb NOT NULL DEFAULT '{}',
    active        boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);
