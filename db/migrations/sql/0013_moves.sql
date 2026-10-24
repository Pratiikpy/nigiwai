-- 0013 moves: what a move was aimed at and when it ended, so scans in the same slot before and after can be compared (M11, M20).

-- `weekdays` empty means every day; `hour_from` and `hour_to` (exclusive) both empty means every hour. A move that is still
-- going has no end date. Nothing here records an outcome: results are worked out from the scans each time they are asked for.
ALTER TABLE move
  ADD COLUMN ended_on date,
  ADD COLUMN weekdays smallint[] NOT NULL DEFAULT '{}',
  ADD COLUMN hour_from smallint CHECK (hour_from BETWEEN 0 AND 23),
  ADD COLUMN hour_to smallint CHECK (hour_to BETWEEN 1 AND 24),
  ADD COLUMN note text CHECK (char_length(note) <= 400),
  ADD CONSTRAINT move_hours_pair CHECK ((hour_from IS NULL) = (hour_to IS NULL)),
  ADD CONSTRAINT move_hours_order CHECK (hour_from IS NULL OR hour_from < hour_to),
  ADD CONSTRAINT move_ended CHECK (ended_on IS NULL OR ended_on >= started_on),
  ADD CONSTRAINT move_weekdays_valid CHECK (weekdays <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[]);
