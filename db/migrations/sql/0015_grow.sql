-- 0015 grow: the last Grow run for a venue (M8): ghost customers, who serves the crowd nearby, and lookalike venues elsewhere.

-- One row per venue, replaced by each run. `basis_ref` is the groups version the run was made against, so a page can say when the
-- groups have moved on since. `result` holds our own derived record (names, ids, distances, counts and the checks that decided what
-- was shown), never Qloo's response. Opening the page reads this row and makes no Qloo call.
CREATE TABLE grow_run (
  business_id uuid PRIMARY KEY REFERENCES business(id) ON DELETE CASCADE,
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'ready', 'failed')),
  basis_kind text,
  basis_ref text,
  result jsonb,
  error text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE grow_run ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON grow_run
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT, INSERT, UPDATE, DELETE ON grow_run TO nigiwai_app, nigiwai_worker;
