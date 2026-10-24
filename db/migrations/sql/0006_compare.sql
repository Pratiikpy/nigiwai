-- 0006 compare: the Qloo against an AI alone panel (M23).

-- What a language model alone answered to a question, by hash of the question and the model. It holds only the question
-- (an act's public name), never anything about a venue or a guest, so it is global and shared: a question is asked once.
CREATE TABLE llm_cache (
  key text PRIMARY KEY,
  model text NOT NULL,
  answer jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- The comparison shown beside one stored Soundcheck, so opening it again costs nothing.
CREATE TABLE soundcheck_comparison (
  soundcheck_id uuid PRIMARY KEY REFERENCES soundcheck(id) ON DELETE CASCADE,
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE soundcheck_comparison ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON soundcheck_comparison
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT, INSERT, UPDATE, DELETE ON llm_cache, soundcheck_comparison TO nigiwai_app, nigiwai_worker;
