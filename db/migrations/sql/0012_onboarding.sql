-- 0012 onboarding: the interview that understands a business (M1), the profile it confirmed and the dashboard plan
-- chosen from it.

-- One open interview per account. `known` holds only values the owner gave and the code accepted; `asked` lists the
-- questions put to the owner (at most eight), each with the words used; `messages` is the conversation the owner sees.
-- `mode` says who chooses the next question: `form` (a fixed order, no model) or `agent` (a model, which can only pick
-- from the checklist and propose answers the code then validates). A session falls back to `form` if the model fails.
CREATE TABLE onboarding_session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  created_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  mode text NOT NULL CHECK (mode IN ('form', 'agent')),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'abandoned')),
  known jsonb NOT NULL DEFAULT '{}'::jsonb,
  skipped jsonb NOT NULL DEFAULT '[]'::jsonb,
  asked jsonb NOT NULL DEFAULT '[]'::jsonb,
  pending text,
  messages jsonb NOT NULL DEFAULT '[]'::jsonb,
  notice text,
  model text,
  input_tokens integer NOT NULL DEFAULT 0,
  output_tokens integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz
);
CREATE UNIQUE INDEX onboarding_one_open_idx ON onboarding_session (tenant_id) WHERE status = 'open';
CREATE INDEX onboarding_tenant_idx ON onboarding_session (tenant_id, created_at DESC);

-- What the owner confirmed about the business, and the modules switched on for it. Versions are only ever added, so the
-- history of what was understood (and what the owner changed) stays readable.
CREATE TABLE business_profile (
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version >= 1),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  profile jsonb NOT NULL,
  session_id uuid REFERENCES onboarding_session(id) ON DELETE SET NULL,
  confirmed_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  confirmed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (business_id, version)
);
CREATE INDEX business_profile_tenant_idx ON business_profile (tenant_id, business_id);

CREATE TABLE dashboard_plan (
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version >= 1),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  profile_version integer NOT NULL,
  plan jsonb NOT NULL,
  overrides jsonb NOT NULL DEFAULT '{}'::jsonb,
  confirmed_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  confirmed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (business_id, version)
);
CREATE INDEX dashboard_plan_tenant_idx ON dashboard_plan (tenant_id, business_id);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['onboarding_session', 'business_profile', 'dashboard_plan']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant())', t);
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON onboarding_session TO nigiwai_app, nigiwai_worker;
GRANT SELECT, INSERT ON business_profile, dashboard_plan TO nigiwai_app, nigiwai_worker;
