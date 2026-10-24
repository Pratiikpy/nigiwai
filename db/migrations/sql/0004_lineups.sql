-- 0004 lineups: the public-lineup start (M24). A venue with no survey yet can borrow a provisional picture of its room
-- from public event data (MusicBrainz, CC0), resolved to Qloo entities.

-- A small cache of what public sources returned, so a rebuild does not ask again within a week and the source is not
-- hammered. Global (no tenant data in it) and private.
CREATE TABLE external_cache (
  key text PRIMARY KEY,
  source text NOT NULL,
  status integer NOT NULL,
  body jsonb,
  fetched_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX external_cache_age_idx ON external_cache (source, fetched_at);

CREATE TABLE lineup_profile (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  place_mbid text NOT NULL,
  place_name text NOT NULL,
  place_area text,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'ready', 'failed')),
  progress jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (business_id)
);

ALTER TABLE lineup_profile ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON lineup_profile
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT, INSERT, UPDATE, DELETE ON external_cache, lineup_profile TO nigiwai_app, nigiwai_worker;
