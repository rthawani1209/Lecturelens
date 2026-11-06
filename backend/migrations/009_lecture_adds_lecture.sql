-- Which lecture each addition was for, so a file that turns out not to be a
-- video gives its slot back.
ALTER TABLE lecture_adds ADD COLUMN lecture_id uuid;
