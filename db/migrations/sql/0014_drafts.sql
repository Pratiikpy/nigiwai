-- 0014 drafts: text the owner reviews before anything leaves the product (M17 Autopilot, M10 Ads hand-off).

-- A draft is plain text built from stored facts, with its gaps marked [like this]. `status` is the owner's decision about the
-- exact text: editing an approved draft takes the approval back. The product never sends, posts or books anything; approval
-- only records that the owner stands behind these words. Who did what and when is in the audit log.
CREATE TABLE draft (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('outreach', 'event_page', 'social_post', 'ad_copy')),
  subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 200),
  body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'withdrawn')),
  facts jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_key text CHECK (char_length(source_key) <= 120),
  created_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  edited_at timestamptz,
  decided_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  decided_at timestamptz
);
CREATE INDEX draft_business_idx ON draft (business_id, created_at DESC);

ALTER TABLE draft ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON draft
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT, INSERT, UPDATE, DELETE ON draft TO nigiwai_app, nigiwai_worker;
