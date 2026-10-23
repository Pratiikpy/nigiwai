-- 0001 foundation: accounts, tenancy, surveys, responses, the private Qloo cache, traces, quota, audit.
-- Tenant tables carry tenant_id and a row-level-security policy that compares it with the transaction's
-- `app.tenant_id`. The application role does not own the tables and cannot bypass it. Public survey traffic uses two narrow
-- SECURITY DEFINER functions instead of a bypass role.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- ---------------------------------------------------------------------------------------------- identity
CREATE TABLE app_user (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext NOT NULL UNIQUE,
  password_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE app_session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL UNIQUE,
  csrf_secret text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX app_session_user_idx ON app_session (user_id);

CREATE TABLE tenant (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  plan text NOT NULL DEFAULT 'free',
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE membership (
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner', 'manager', 'viewer')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);

-- ---------------------------------------------------------------------------------------------- business
CREATE TABLE business (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  name text NOT NULL,
  type text NOT NULL,
  language text NOT NULL DEFAULT 'en',
  currency text NOT NULL DEFAULT 'USD',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX business_tenant_idx ON business (tenant_id);

CREATE TABLE location (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  name text NOT NULL,
  address text,
  geom geography(Point, 4326),
  hours jsonb NOT NULL DEFAULT '{}'::jsonb,
  price_level smallint CHECK (price_level BETWEEN 1 AND 4),
  radius_m integer NOT NULL DEFAULT 800 CHECK (radius_m BETWEEN 50 AND 50000),
  timezone text NOT NULL DEFAULT 'UTC',
  capacity integer CHECK (capacity > 0),
  curfew text,
  excluded_genres text[] NOT NULL DEFAULT '{}',
  show_nights smallint[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX location_tenant_idx ON location (tenant_id, business_id);
CREATE INDEX location_geom_idx ON location USING gist (geom);

CREATE TABLE qr_point (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  location_id uuid NOT NULL REFERENCES location(id) ON DELETE CASCADE,
  label text NOT NULL,
  token_hash bytea NOT NULL UNIQUE,
  token_enc bytea NOT NULL,  -- the token, AES-GCM encrypted with a key derived from the application secret: lets an owner reprint a poster
  token_hint text NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  created_at timestamptz NOT NULL DEFAULT now(),
  rotated_at timestamptz
);
CREATE INDEX qr_point_tenant_idx ON qr_point (tenant_id, location_id);

CREATE TABLE consent_text (
  version text PRIMARY KEY,
  language text NOT NULL,
  body text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE survey (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  version integer NOT NULL DEFAULT 1,
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  questions jsonb NOT NULL,
  reward jsonb,
  consent_text_version text NOT NULL REFERENCES consent_text(version),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, version)
);
CREATE INDEX survey_tenant_idx ON survey (tenant_id, business_id);

-- No IP address, user agent, device id or exact timestamp is stored with a response (ARCHITECTURE 6, 7).
CREATE TABLE response (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  survey_id uuid NOT NULL,
  survey_version integer NOT NULL,
  qr_point_id uuid NOT NULL REFERENCES qr_point(id),
  local_date date NOT NULL,
  local_weekday smallint NOT NULL CHECK (local_weekday BETWEEN 0 AND 6),
  local_hour smallint NOT NULL CHECK (local_hour BETWEEN 0 AND 23),
  age_band text CHECK (age_band IN ('18-24', '25-34', '35-44', '45-54', '55-64', '65+')),
  district text CHECK (char_length(district) <= 60),
  budget smallint CHECK (budget BETWEEN 1 AND 4),
  consent_text_version text NOT NULL REFERENCES consent_text(version),
  quality_flag text NOT NULL DEFAULT 'ok' CHECK (quality_flag IN ('ok', 'quarantined', 'flagged')),
  delete_token_hash bytea UNIQUE,  -- the guest's receipt: hashing it lets a guest remove their own answers
  FOREIGN KEY (survey_id, survey_version) REFERENCES survey (id, version)
);
CREATE INDEX response_tenant_date_idx ON response (tenant_id, local_date);
CREATE INDEX response_point_idx ON response (qr_point_id);

CREATE TABLE pick (
  response_id uuid NOT NULL REFERENCES response(id) ON DELETE CASCADE,
  position smallint NOT NULL CHECK (position BETWEEN 1 AND 10),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  entity_id text NOT NULL,
  entity_type text NOT NULL,
  PRIMARY KEY (response_id, position)
);
CREATE INDEX pick_tenant_entity_idx ON pick (tenant_id, entity_id);

-- ---------------------------------------------------------------------------------------------- Qloo (global, private)
CREATE TABLE qloo_entity (
  entity_id text PRIMARY KEY,
  type text NOT NULL,
  types text[] NOT NULL DEFAULT '{}',
  name_nfc text NOT NULL,
  disambiguation text,
  popularity real,
  tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  props jsonb NOT NULL DEFAULT '{}'::jsonb,
  insights_eligible boolean,
  eligibility_checked_at timestamptz,
  is_closed boolean,
  closed_checked_at timestamptz,
  musicbrainz_id text,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qloo_entity_name_trgm ON qloo_entity USING gin (name_nfc gin_trgm_ops);
CREATE INDEX qloo_entity_type_idx ON qloo_entity (type);

CREATE TABLE qloo_response (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cache_key text NOT NULL UNIQUE,
  host text NOT NULL,
  endpoint text NOT NULL,
  params jsonb NOT NULL,
  status integer NOT NULL,
  body bytea,
  headers jsonb NOT NULL DEFAULT '{}'::jsonb,
  transport text NOT NULL DEFAULT 'none',
  fetched_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  guard_version text NOT NULL
);
CREATE INDEX qloo_response_expires_idx ON qloo_response (expires_at);

CREATE TABLE trace (
  id uuid PRIMARY KEY,
  tenant_id uuid REFERENCES tenant(id) ON DELETE CASCADE,
  kind text NOT NULL,
  guard_version text,
  prompt_version text,
  model_id text,
  budget integer,
  calls_used integer NOT NULL DEFAULT 0,
  tokens_in integer,
  tokens_out integer,
  outcome text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX trace_tenant_idx ON trace (tenant_id, started_at);

CREATE TABLE qloo_call (
  id uuid PRIMARY KEY,
  trace_id uuid NOT NULL,
  tenant_id uuid,
  purpose text NOT NULL,
  endpoint text NOT NULL,
  params jsonb NOT NULL,
  status text NOT NULL,
  http_status integer,
  transport text NOT NULL,
  cache text NOT NULL,
  latency_ms integer NOT NULL DEFAULT 0,
  result_entity_ids text[] NOT NULL DEFAULT '{}',
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  rule_events jsonb NOT NULL DEFAULT '[]'::jsonb,
  key_fingerprint text NOT NULL,
  host text NOT NULL,
  guard_version text NOT NULL,
  cache_key text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qloo_call_trace_idx ON qloo_call (trace_id);
CREATE INDEX qloo_call_tenant_idx ON qloo_call (tenant_id, created_at);
CREATE INDEX qloo_call_ids_idx ON qloo_call USING gin (result_entity_ids);

CREATE TABLE quota_ledger (
  day date NOT NULL,
  key_fingerprint text NOT NULL,
  purpose text NOT NULL,
  calls_live integer NOT NULL DEFAULT 0,
  calls_cached integer NOT NULL DEFAULT 0,
  month_remaining_last integer,
  PRIMARY KEY (day, key_fingerprint, purpose)
);

CREATE TABLE audit_log (
  id bigserial PRIMARY KEY,
  tenant_id uuid REFERENCES tenant(id) ON DELETE CASCADE,
  actor text NOT NULL,
  action text NOT NULL,
  target text,
  at timestamptz NOT NULL DEFAULT now(),
  payload_hash text
);
CREATE INDEX audit_log_tenant_idx ON audit_log (tenant_id, at);

-- ---------------------------------------------------------------------------------------------- row-level security
CREATE OR REPLACE FUNCTION current_tenant() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION current_app_user() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['business', 'location', 'qr_point', 'survey', 'response', 'pick', 'trace', 'qloo_call', 'audit_log']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant())', t);
  END LOOP;
END
$$;

-- Trace and call records may be written without a tenant (global jobs, canaries): INSERT is open, but SELECT stays
-- tenant-scoped, so a row with a NULL tenant_id is invisible to every tenant session.
CREATE POLICY insert_any ON trace FOR INSERT WITH CHECK (true);
CREATE POLICY insert_any ON qloo_call FOR INSERT WITH CHECK (true);

-- Row-level security binds the application role because it does not own the tables. The migration role owns them
-- and bypasses RLS, which is what lets the SECURITY DEFINER functions below work. The API refuses to start if it is
-- connected as a role that would bypass RLS (see nigiwai_api.db.assert_rls_effective).

-- Role checks are definer functions so that a policy never has to read `membership` through its own policy.
CREATE OR REPLACE FUNCTION has_role(p_tenant uuid, p_user uuid, p_roles text[]) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM membership WHERE tenant_id = p_tenant AND user_id = p_user AND role = ANY (p_roles)) $$;

-- A new account creates its tenant and becomes its owner in one step. This is the only way a membership is born
-- without an existing owner's say-so, so nobody can enrol themselves in a tenant that already exists.
CREATE OR REPLACE FUNCTION create_tenant(p_name text, p_user uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE v_id uuid;
BEGIN
  IF p_user IS DISTINCT FROM current_app_user() THEN
    RAISE EXCEPTION 'tenant can only be created for the signed-in user' USING ERRCODE = '42501';
  END IF;
  INSERT INTO tenant (name) VALUES (p_name) RETURNING id INTO v_id;
  INSERT INTO membership (tenant_id, user_id, role) VALUES (v_id, p_user, 'owner');
  RETURN v_id;
END
$$;

ALTER TABLE membership ENABLE ROW LEVEL SECURITY;
CREATE POLICY membership_select ON membership FOR SELECT
  USING (user_id = current_app_user() OR tenant_id = current_tenant());
CREATE POLICY membership_write ON membership FOR ALL
  USING (tenant_id = current_tenant() AND has_role(tenant_id, current_app_user(), ARRAY['owner']))
  WITH CHECK (tenant_id = current_tenant() AND has_role(tenant_id, current_app_user(), ARRAY['owner']));

ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_select ON tenant FOR SELECT
  USING (id = current_tenant() OR has_role(id, current_app_user(), ARRAY['owner', 'manager', 'viewer']));
CREATE POLICY tenant_update ON tenant FOR UPDATE
  USING (id = current_tenant() AND has_role(id, current_app_user(), ARRAY['owner']))
  WITH CHECK (id = current_tenant());

-- ---------------------------------------------------------------------------------------------- public survey functions
-- The anonymous survey runs as the application role with no tenant set. These two functions are its only way in.

CREATE OR REPLACE FUNCTION public_resolve_qr(p_hash bytea)
RETURNS TABLE (
  tenant_id uuid, qr_point_id uuid, location_id uuid, business_name text, location_name text, timezone text,
  survey_id uuid, survey_version integer, questions jsonb, reward jsonb, consent_text_version text,
  consent_body text, consent_language text
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS
$$
  SELECT q.tenant_id, q.id, q.location_id, b.name, l.name, l.timezone,
         s.id, s.version, s.questions, s.reward, s.consent_text_version, c.body, c.language
  FROM qr_point q
  JOIN location l ON l.id = q.location_id
  JOIN business b ON b.id = l.business_id
  JOIN LATERAL (
    SELECT * FROM survey s2
    WHERE s2.business_id = b.id AND s2.status = 'published'
    ORDER BY s2.created_at DESC, s2.version DESC LIMIT 1
  ) s ON true
  JOIN consent_text c ON c.version = s.consent_text_version
  WHERE q.token_hash = p_hash AND q.status = 'active'
$$;

CREATE OR REPLACE FUNCTION public_insert_response(
  p_qr_point_id uuid, p_survey_id uuid, p_survey_version integer, p_consent_text_version text,
  p_age_band text, p_district text, p_budget smallint, p_quality text,
  p_entity_ids text[], p_entity_types text[], p_delete_hash bytea
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE
  v_tenant uuid; v_tz text; v_response uuid; v_local timestamp; i integer;
BEGIN
  SELECT q.tenant_id, l.timezone INTO v_tenant, v_tz
  FROM qr_point q JOIN location l ON l.id = q.location_id
  WHERE q.id = p_qr_point_id AND q.status = 'active';
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'unknown or revoked qr point' USING ERRCODE = 'P0002'; END IF;
  IF NOT EXISTS (SELECT 1 FROM survey WHERE id = p_survey_id AND version = p_survey_version AND tenant_id = v_tenant AND status = 'published') THEN
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
  RETURN v_response;
END
$$;

CREATE OR REPLACE FUNCTION public_delete_response(p_hash bytea) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE n integer;
BEGIN
  DELETE FROM response WHERE delete_token_hash = p_hash;  -- picks go with it (ON DELETE CASCADE)
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n > 0;
END
$$;

REVOKE ALL ON FUNCTION public_resolve_qr(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION public_insert_response(uuid, uuid, integer, text, text, text, smallint, text, text[], text[], bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION public_delete_response(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public_resolve_qr(bytea) TO nigiwai_app, nigiwai_worker;
GRANT EXECUTE ON FUNCTION public_insert_response(uuid, uuid, integer, text, text, text, smallint, text, text[], text[], bytea) TO nigiwai_app;
GRANT EXECUTE ON FUNCTION public_delete_response(bytea) TO nigiwai_app;

-- ---------------------------------------------------------------------------------------------- grants
GRANT USAGE ON SCHEMA public TO nigiwai_app, nigiwai_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  app_user, app_session, tenant, membership, business, location, qr_point, survey, response, pick,
  qloo_entity, qloo_response, trace, qloo_call, quota_ledger
TO nigiwai_app, nigiwai_worker;
GRANT SELECT ON consent_text TO nigiwai_app, nigiwai_worker;
GRANT SELECT, INSERT ON audit_log TO nigiwai_app, nigiwai_worker;  -- append only: no update, no delete
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO nigiwai_app, nigiwai_worker;
GRANT EXECUTE ON FUNCTION current_tenant(), current_app_user(), has_role(uuid, uuid, text[]) TO nigiwai_app, nigiwai_worker;
REVOKE ALL ON FUNCTION create_tenant(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION create_tenant(text, uuid) TO nigiwai_app;
