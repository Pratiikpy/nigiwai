-- 0003 tribes: immutable tribe versions, a small job queue, recomputation triggers, and the card's receipt lookup.

-- ---------------------------------------------------------------------------------------------- tribe versions
-- One immutable row per computation. `result` is the whole TribeResult document (profiles, cards, stability, config),
-- so a shown number can always be traced to the run that produced it. `input_hash` lets an unchanged crowd be skipped.
CREATE TABLE tribe_version (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  version integer NOT NULL,
  state text NOT NULL CHECK (state IN ('none', 'unstable', 'provisional', 'named')),
  n integer NOT NULL,
  input_hash text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, version)
);
CREATE INDEX tribe_version_latest_idx ON tribe_version (business_id, version DESC);

ALTER TABLE tribe_version ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tribe_version
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

-- ---------------------------------------------------------------------------------------------- jobs
-- A queue the worker drains with SKIP LOCKED. It holds only ids and a kind, never guest data, so it carries no
-- row-level security: the worker claims a job, then does the real work inside that job's tenant scope.
CREATE TABLE job (
  id bigserial PRIMARY KEY,
  kind text NOT NULL,
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'done', 'failed')),
  run_after timestamptz NOT NULL DEFAULT now(),
  attempts integer NOT NULL DEFAULT 0,
  locked_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
-- At most one waiting job of a kind per business: a burst of responses is one recomputation, not fifty.
CREATE UNIQUE INDEX job_one_pending ON job (kind, business_id) WHERE state = 'pending';
CREATE INDEX job_claim_idx ON job (run_after, id) WHERE state = 'pending';

GRANT SELECT, INSERT, UPDATE, DELETE ON tribe_version TO nigiwai_app, nigiwai_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON job TO nigiwai_app, nigiwai_worker;
GRANT USAGE, SELECT ON SEQUENCE job_id_seq TO nigiwai_app, nigiwai_worker;

-- ---------------------------------------------------------------------------------------------- triggers
-- Recomputation is queued in the same transaction as the response (or its removal), so it can never be lost.
CREATE OR REPLACE FUNCTION enqueue_recompute(p_tenant uuid, p_business uuid, p_delay interval) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public AS
$$
  INSERT INTO job (kind, tenant_id, business_id, run_after)
  VALUES ('recompute_tribes', p_tenant, p_business, now() + p_delay)
  ON CONFLICT (kind, business_id) WHERE state = 'pending' DO NOTHING
$$;
REVOKE ALL ON FUNCTION enqueue_recompute(uuid, uuid, interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION enqueue_recompute(uuid, uuid, interval) TO nigiwai_app, nigiwai_worker;

CREATE OR REPLACE FUNCTION public_insert_response(
  p_qr_point_id uuid, p_survey_id uuid, p_survey_version integer, p_consent_text_version text,
  p_age_band text, p_district text, p_budget smallint, p_quality text,
  p_entity_ids text[], p_entity_types text[], p_delete_hash bytea
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE
  v_tenant uuid; v_tz text; v_response uuid; v_local timestamp; v_business uuid; i integer;
BEGIN
  SELECT q.tenant_id, l.timezone INTO v_tenant, v_tz
  FROM qr_point q JOIN location l ON l.id = q.location_id
  WHERE q.id = p_qr_point_id AND q.status = 'active';
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'unknown or revoked qr point' USING ERRCODE = 'P0002'; END IF;
  SELECT s.business_id INTO v_business FROM survey s
  WHERE s.id = p_survey_id AND s.version = p_survey_version AND s.tenant_id = v_tenant AND s.status = 'published';
  IF v_business IS NULL THEN
    RAISE EXCEPTION 'survey is not published' USING ERRCODE = 'P0003';
  END IF;
  IF coalesce(array_length(p_entity_ids, 1), 0) < 1 OR array_length(p_entity_ids, 1) <> array_length(p_entity_types, 1) THEN
    RAISE EXCEPTION 'picks are required' USING ERRCODE = 'P0004';
  END IF;
  v_local := (now() AT TIME ZONE v_tz);
  INSERT INTO response (tenant_id, survey_id, survey_version, qr_point_id, local_date, local_weekday, local_hour,
                        age_band, district, budget, consent_text_version, quality_flag, delete_token_hash)
  VALUES (v_tenant, p_survey_id, p_survey_version, p_qr_point_id, v_local::date,
          ((extract(isodow FROM v_local)::int + 6) % 7)::smallint, extract(hour FROM v_local)::smallint,
          p_age_band, p_district, p_budget, p_consent_text_version, p_quality, p_delete_hash)
  RETURNING id INTO v_response;
  FOR i IN 1 .. array_length(p_entity_ids, 1) LOOP
    INSERT INTO pick (response_id, position, tenant_id, entity_id, entity_type)
    VALUES (v_response, i, v_tenant, p_entity_ids[i], p_entity_types[i]);
  END LOOP;
  IF p_quality = 'ok' THEN
    PERFORM enqueue_recompute(v_tenant, v_business, interval '20 seconds');
  END IF;
  RETURN v_response;
END
$$;

CREATE OR REPLACE FUNCTION public_delete_response(p_hash bytea) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE v_tenant uuid; v_business uuid;
BEGIN
  SELECT r.tenant_id, s.business_id INTO v_tenant, v_business
  FROM response r JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version
  WHERE r.delete_token_hash = p_hash;
  IF v_tenant IS NULL THEN RETURN false; END IF;
  DELETE FROM response WHERE delete_token_hash = p_hash;  -- picks go with it (ON DELETE CASCADE)
  -- A removed guest must leave the groups too: recompute soon, and at once for the stored result's sake.
  PERFORM enqueue_recompute(v_tenant, v_business, interval '5 seconds');
  RETURN true;
END
$$;

-- ---------------------------------------------------------------------------------------------- the card
-- The Taste Card is shown to the guest who just answered and is authorised by their receipt alone. This returns only
-- what the card needs: the picks, the venue's name and where it is. Nothing about any other guest.
DROP FUNCTION IF EXISTS public_card_context(bytea);
CREATE FUNCTION public_card_context(p_hash bytea)
RETURNS TABLE (
  tenant_id uuid, business_id uuid, business_name text, business_type text, location_name text, timezone text,
  lat double precision, lon double precision, radius_m integer,
  entity_ids text[], entity_types text[], quality_flag text, reward jsonb
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT r.tenant_id, b.id, b.name, b.type, l.name, l.timezone,
         ST_Y(l.geom::geometry), ST_X(l.geom::geometry), l.radius_m,
         array(SELECT p.entity_id FROM pick p WHERE p.response_id = r.id ORDER BY p.position),
         array(SELECT p.entity_type FROM pick p WHERE p.response_id = r.id ORDER BY p.position),
         r.quality_flag, s.reward
  FROM response r
  JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version
  JOIN business b ON b.id = s.business_id
  JOIN qr_point q ON q.id = r.qr_point_id
  JOIN location l ON l.id = q.location_id
  WHERE r.delete_token_hash = p_hash
$$;

-- The most recent tribe result for a business, for the card: the profiles only, never a guest's data.
CREATE OR REPLACE FUNCTION public_card_tribes(p_business uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT result FROM tribe_version WHERE business_id = p_business ORDER BY version DESC LIMIT 1
$$;

REVOKE ALL ON FUNCTION public_card_context(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION public_card_tribes(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public_card_context(bytea) TO nigiwai_app;
GRANT EXECUTE ON FUNCTION public_card_tribes(uuid) TO nigiwai_app;
GRANT EXECUTE ON FUNCTION public_insert_response(uuid, uuid, integer, text, text, text, smallint, text, text[], text[], bytea) TO nigiwai_app;
GRANT EXECUTE ON FUNCTION public_delete_response(bytea) TO nigiwai_app;
