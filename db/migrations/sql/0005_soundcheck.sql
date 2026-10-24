-- 0005 soundcheck: stored Fit Verdicts, the act suggestions job result, and the versioned fit weights (M19, M9).

-- The weights a score was computed with. Global and read-only to the application: a new version is a migration, so
-- every stored score names the weights it used. v0 is a starting design and NOT VERIFIED (ARCHITECTURE 5.3).
CREATE TABLE fit_weights (
  version text PRIMARY KEY,
  weights jsonb NOT NULL,
  note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO fit_weights (version, weights, note) VALUES (
  'v0',
  '{"group_fit": 0.8, "peer": 0.2, "risk": 0.5, "risk_floor": 0.5, "min_references": 8, "min_scored_share": 0.6,
    "bootstrap": 200, "interval": [0.1, 0.9], "strong": 0.75, "weak": 0.35}'::jsonb,
  'Starting design from ARCHITECTURE 5.3. Not calibrated against held-out picks or outcomes.'
);

-- One row per distinct input: asking again with the same crowd, act and weights finds the stored verdict.
CREATE TABLE soundcheck (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  candidate_entity_id text NOT NULL,
  candidate_name text NOT NULL,
  basis_kind text NOT NULL CHECK (basis_kind IN ('guests', 'lineup')),
  basis_ref text NOT NULL,          -- the tribe version number, or the lineup profile's finish time
  input_hash text NOT NULL,
  weights_version text NOT NULL REFERENCES fit_weights(version),
  result jsonb NOT NULL,
  trace_ids jsonb NOT NULL DEFAULT '[]'::jsonb,   -- the Qloo traces behind this verdict, for the call list in the inspector
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, candidate_entity_id, input_hash)
);
CREATE INDEX soundcheck_recent_idx ON soundcheck (business_id, created_at DESC);

-- The suggested acts and the Wildcard for a crowd, built by the worker.
CREATE TABLE act_suggestion (
  business_id uuid PRIMARY KEY REFERENCES business(id) ON DELETE CASCADE,
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'ready', 'failed')),
  basis_kind text,
  basis_ref text,
  result jsonb,
  error text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE soundcheck ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON soundcheck
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());
ALTER TABLE act_suggestion ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON act_suggestion
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT ON fit_weights TO nigiwai_app, nigiwai_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON soundcheck, act_suggestion TO nigiwai_app, nigiwai_worker;
