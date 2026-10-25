-- 0021 picker point: a guest who names a favourite place is searched for near the venue they are in (PRD M3). The anonymous survey runs
-- with no tenant set, so it reads the venue's position through this one function, which answers for a location id that a resolved QR
-- point gave it and returns nothing but that point. The position never goes to the guest's browser: the server sends it to Qloo as
-- the bias of the search and nothing else.
CREATE OR REPLACE FUNCTION public_survey_point(p_location_id uuid)
RETURNS TABLE (lat double precision, lon double precision)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT ST_Y(l.geom::geometry), ST_X(l.geom::geometry) FROM location l WHERE l.id = p_location_id AND l.geom IS NOT NULL
$$;
REVOKE ALL ON FUNCTION public_survey_point(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public_survey_point(uuid) TO nigiwai_app, nigiwai_worker;
