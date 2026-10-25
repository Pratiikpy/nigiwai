-- 0022 place tags minimised. Qloo lists a place with up to two hundred tags, and until now the first ten were kept as they came: mostly
-- facilities and context, and some that describe the place's customers, owners and diets ("Lgbtq+", "Students", "Halal"). Nothing reads
-- them, and holding them is holding claims about people for no use. The Guard now stores only the tags that say what a place is, serves
-- and feels like (qloo_guard.parse.PLACE_TASTE_NAMESPACES); this removes the others from what is already stored. The list below is a copy of
-- that constant, and a test keeps the two equal. An entity that is not a place is not touched.
CREATE OR REPLACE FUNCTION minimise_place_tags(p_keep text[]) RETURNS integer
LANGUAGE plpgsql AS
$$
DECLARE n integer;
BEGIN
  UPDATE qloo_entity e
  SET tags = coalesce(
        (SELECT jsonb_agg(t ORDER BY o) FROM jsonb_array_elements(e.tags) WITH ORDINALITY AS x(t, o)
         WHERE split_part(t->>0, ':', 3) = ANY (p_keep)),
        '[]'::jsonb)
  WHERE e.type LIKE 'urn:entity:place%' AND e.tags <> '[]'::jsonb
    AND EXISTS (SELECT 1 FROM jsonb_array_elements(e.tags) t WHERE NOT (split_part(t->>0, ':', 3) = ANY (p_keep)));
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END
$$;
REVOKE ALL ON FUNCTION minimise_place_tags(text[]) FROM PUBLIC;

-- The private cache holds Qloo's answers as they came, so it held the same tags. It is a cache: what held a place is dropped and fetched
-- again when next wanted, now minimised as it is stored.
DELETE FROM qloo_response WHERE body::text LIKE '%urn:entity:place%';

SELECT minimise_place_tags(ARRAY['genre', 'category', 'cuisine', 'culinary_style', 'menu_highlight', 'beverage_offering', 'specialty_dish', 'ambience', 'decor', 'activity_type']);
