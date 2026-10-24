-- 0016 atlas: the City Taste Atlas groundwork (M16): an opt-in, anonymous roll-up of what guests pick, per neighbourhood cell.

-- A venue takes part only if its owner switched it on. Nothing is shared, and nothing of the Atlas is shown to the venue, until then.
ALTER TABLE business
  ADD COLUMN atlas_opt_in boolean NOT NULL DEFAULT false,
  ADD COLUMN atlas_opt_in_at timestamptz;

-- One row per (cell, picked item), only where the minimums below hold. A cell is a 0.01 degree square (about a kilometre), named by
-- floor(longitude x 100) and floor(latitude x 100). There is deliberately no business, tenant or location column: the table cannot
-- say which venue a count came from. The checks restate the minimums so a row that breaks them cannot be written even by hand;
-- "no venue supplies more than half of an item's responses" cannot be a column check and is enforced in atlas_rebuild().
CREATE TABLE atlas_cell (
  cell_x integer NOT NULL,
  cell_y integer NOT NULL,
  entity_id text NOT NULL,
  entity_type text NOT NULL,
  responses integer NOT NULL CONSTRAINT atlas_min_responses CHECK (responses >= 10),
  venues integer NOT NULL CONSTRAINT atlas_min_item_venues CHECK (venues >= 3),
  cell_responses integer NOT NULL,
  cell_venues integer NOT NULL CONSTRAINT atlas_min_cell_venues CHECK (cell_venues >= 5),
  built_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cell_x, cell_y, entity_id),
  CONSTRAINT atlas_cell_total CHECK (cell_responses >= responses)
);
CREATE INDEX atlas_cell_xy_idx ON atlas_cell (cell_x, cell_y, entity_type, responses DESC);

-- Rebuilds the whole table from the opted-in venues' own responses. It reads across tenants, which row-level security forbids the
-- application role to do; as a definer function owned by the migration role it does that one thing, and only ever writes rows that
-- meet the minimums:
--   * a venue counts in a cell only with at least 10 clean responses there;
--   * a cell is open only with at least 5 such venues;
--   * an item is listed only with at least 10 responses from at least 3 venues, and only if no single venue supplies more than half.
-- Replacing the table in one transaction means readers see the old rows or the new ones, never a mixture. It returns the rows built.
CREATE OR REPLACE FUNCTION atlas_rebuild() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE
  k_venue_responses constant integer := 10;
  k_cell_venues constant integer := 5;
  k_item_responses constant integer := 10;
  k_item_venues constant integer := 3;
  k_max_share constant numeric := 0.5;
  n integer;
BEGIN
  DELETE FROM atlas_cell;
  WITH located AS (
    SELECT r.id AS response_id, b.id AS business_id,
           floor(ST_X(l.geom::geometry) * 100)::integer AS cx,
           floor(ST_Y(l.geom::geometry) * 100)::integer AS cy
    FROM response r
    JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version
    JOIN business b ON b.id = s.business_id AND b.atlas_opt_in
    JOIN qr_point q ON q.id = r.qr_point_id
    JOIN location l ON l.id = q.location_id AND l.geom IS NOT NULL
    WHERE r.quality_flag = 'ok'
  ),
  venue_in_cell AS (
    SELECT cx, cy, business_id, count(*) AS responses
    FROM located GROUP BY cx, cy, business_id HAVING count(*) >= k_venue_responses
  ),
  open_cells AS (
    SELECT cx, cy, count(*)::integer AS venues, sum(responses)::integer AS responses
    FROM venue_in_cell GROUP BY cx, cy HAVING count(*) >= k_cell_venues
  ),
  counted AS (
    SELECT l.cx, l.cy, l.response_id, l.business_id
    FROM located l
    JOIN venue_in_cell v ON v.cx = l.cx AND v.cy = l.cy AND v.business_id = l.business_id
    JOIN open_cells o ON o.cx = l.cx AND o.cy = l.cy
  ),
  per_item_venue AS (
    SELECT c.cx, c.cy, p.entity_id, p.entity_type, c.business_id, count(DISTINCT c.response_id) AS responses
    FROM counted c JOIN pick p ON p.response_id = c.response_id
    GROUP BY c.cx, c.cy, p.entity_id, p.entity_type, c.business_id
  ),
  per_item AS (
    SELECT cx, cy, entity_id, entity_type, sum(responses)::integer AS responses, count(*)::integer AS venues,
           max(responses) AS biggest
    FROM per_item_venue GROUP BY cx, cy, entity_id, entity_type
  )
  INSERT INTO atlas_cell (cell_x, cell_y, entity_id, entity_type, responses, venues, cell_responses, cell_venues)
  SELECT i.cx, i.cy, i.entity_id, i.entity_type, i.responses, i.venues, o.responses, o.venues
  FROM per_item i JOIN open_cells o ON o.cx = i.cx AND o.cy = i.cy
  WHERE i.responses >= k_item_responses AND i.venues >= k_item_venues AND i.biggest <= k_max_share * i.responses;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END
$$;

-- The table holds only aggregates that already meet the minimums, so reading it is safe for the application role. The embedded
-- worker runs on that role; a separate worker process uses its own. Neither can write the table except through the function.
GRANT SELECT ON atlas_cell TO nigiwai_app, nigiwai_worker;
REVOKE ALL ON FUNCTION atlas_rebuild() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION atlas_rebuild() TO nigiwai_app, nigiwai_worker;
