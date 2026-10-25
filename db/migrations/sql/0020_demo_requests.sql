-- 0020 demo requests: a visitor to judge mode can ask for a venue that is not one of the three prepared ones (PRD M24, M25: "a search
-- box lets a visitor try any venue"). It is built from the same public lineups by the same code, under the same system tenant, listed
-- nowhere, kept for a week and then deleted. The row says where it came from so the same place is never built twice.
ALTER TABLE demo_venue
  ADD COLUMN requested boolean NOT NULL DEFAULT false,
  ADD COLUMN place_mbid text,
  ADD COLUMN requested_at timestamptz;
CREATE UNIQUE INDEX demo_venue_place_idx ON demo_venue (place_mbid) WHERE place_mbid IS NOT NULL;
-- A single-process deployment runs the worker as the application role, which therefore also clears out expired requests.
GRANT DELETE ON demo_venue TO nigiwai_app;
