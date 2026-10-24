-- Vectors on transcript lines let search jump to the exact sentence inside a 30s window.
ALTER TABLE transcript_lines ADD COLUMN text_emb vector(384);

-- Search filters by course; keep that join cheap.
CREATE INDEX IF NOT EXISTS segments_lecture_start_idx ON segments (lecture_id, start_s, end_s);
