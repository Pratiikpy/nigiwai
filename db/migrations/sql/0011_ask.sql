-- 0011 ask: the answers Ask Nigiwai gave (M12), kept so a refresh restores them and the owner can reopen the trace.

-- The question, the validated answer, and the Qloo traces behind it. Only answers that passed validation are stored; an
-- answer is never edited afterwards. `kind` says how it was produced: `model` (the model wrote it and every item in it was
-- returned by a Qloo call during the question) or `template` (the model could not produce a valid answer, so the items
-- Qloo returned are listed plainly).
CREATE TABLE ask_answer (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  created_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  mode text NOT NULL CHECK (mode IN ('crowd', 'culture')),
  question text NOT NULL CHECK (char_length(question) BETWEEN 1 AND 600),
  kind text NOT NULL CHECK (kind IN ('model', 'template')),
  answer jsonb NOT NULL,
  trace_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  model text,
  prompt_hash text,
  input_tokens integer NOT NULL DEFAULT 0,
  output_tokens integer NOT NULL DEFAULT 0,
  duration_ms integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ask_answer_recent_idx ON ask_answer (business_id, created_at DESC);

ALTER TABLE ask_answer ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ask_answer
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT, INSERT, DELETE ON ask_answer TO nigiwai_app, nigiwai_worker;
