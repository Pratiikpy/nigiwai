-- 0009 demo: judge mode (M25). A few real venues, built from public lineups and Qloo, that anyone can open without an
-- account. They are ordinary businesses under one fixed system tenant that has no users and no memberships, so nobody can
-- sign in to it. This table says which venues are public and holds the short summary shown on the landing page, so
-- listing them touches no tenant data.
INSERT INTO tenant (id, name) VALUES ('6e1c0de0-0000-4000-8000-00000000d3a0', 'Nigiwai demo venues');

CREATE TABLE demo_venue (
  slug text PRIMARY KEY CHECK (slug ~ '^[a-z0-9-]{2,40}$'),
  name text NOT NULL,
  city text NOT NULL,
  blurb text NOT NULL,
  -- The only tenant a public demo route will ever read. The check means that even a bad write cannot list a real
  -- customer's venue for anonymous visitors.
  tenant_id uuid NOT NULL DEFAULT '6e1c0de0-0000-4000-8000-00000000d3a0'
    CHECK (tenant_id = '6e1c0de0-0000-4000-8000-00000000d3a0')
    REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'building' CHECK (status IN ('building', 'ready', 'failed')),
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  refreshed_at timestamptz,
  error text,
  UNIQUE (business_id)
);
GRANT SELECT ON demo_venue TO nigiwai_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON demo_venue TO nigiwai_worker;
-- The embedded worker of a single-process deployment runs as the application role, so it may build and refresh them too.
GRANT INSERT, UPDATE ON demo_venue TO nigiwai_app;
