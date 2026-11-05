-- Public demo limits by network address, so making new demo accounts doesn't
-- get anyone a fresh allowance.
CREATE TABLE demo_signins (
    ip  text NOT NULL,
    at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX demo_signins_ip_idx ON demo_signins (ip, at);

ALTER TABLE lecture_adds ADD COLUMN ip text;
CREATE INDEX lecture_adds_ip_idx ON lecture_adds (ip, at);
