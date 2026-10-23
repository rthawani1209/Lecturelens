-- Sentence-level transcript for the synced player. `segments` are the 30s search
-- windows built from these.
CREATE TABLE transcript_lines (
    id          bigserial PRIMARY KEY,
    lecture_id  uuid NOT NULL REFERENCES lectures(id) ON DELETE CASCADE,
    start_s     double precision NOT NULL,
    end_s       double precision NOT NULL,
    speaker     text,
    text        text NOT NULL
);
CREATE INDEX transcript_lines_lecture_idx ON transcript_lines (lecture_id, start_s);
