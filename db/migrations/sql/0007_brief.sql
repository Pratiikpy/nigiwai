-- 0007 brief: share links for the Booking Brief (M22).

-- A shared brief is a snapshot: the document as it was when the owner chose to share it, with item names and our own
-- scores only. The token is stored as a hash, links expire, and the owner can revoke one at any time.
CREATE TABLE brief_share (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL UNIQUE,
  snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE INDEX brief_share_business_idx ON brief_share (business_id, created_at DESC);

ALTER TABLE brief_share ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON brief_share
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

-- The only way a reader without an account gets in: one live link, by the hash of its token.
CREATE OR REPLACE FUNCTION public_resolve_brief(p_hash bytea)
RETURNS TABLE (snapshot jsonb, expires_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS
$$
  SELECT s.snapshot, s.expires_at FROM brief_share s
  WHERE s.token_hash = p_hash AND s.revoked_at IS NULL AND s.expires_at > now()
$$;
REVOKE ALL ON FUNCTION public_resolve_brief(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public_resolve_brief(bytea) TO nigiwai_app, nigiwai_worker;

GRANT SELECT, INSERT, UPDATE, DELETE ON brief_share TO nigiwai_app, nigiwai_worker;
