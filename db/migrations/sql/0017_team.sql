-- 0017 team: inviting people into an account by a link (no email service is needed), and keeping an account from losing its last owner.

-- An invitation is a random link the owner passes on. Only its hash is stored, so a database copy cannot be used to join; it works
-- once, for the role it names, until it expires or the owner revokes it. An invitation can never make an owner.
CREATE TABLE invitation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('manager', 'viewer')),
  token_hash bytea NOT NULL UNIQUE,
  created_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  accepted_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  accepted_at timestamptz,
  revoked_at timestamptz,
  CONSTRAINT invitation_window CHECK (expires_at > created_at)
);
CREATE INDEX invitation_tenant_idx ON invitation (tenant_id, created_at DESC);

ALTER TABLE invitation ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_manages ON invitation
  USING (tenant_id = current_tenant() AND has_role(tenant_id, current_app_user(), ARRAY['owner']))
  WITH CHECK (tenant_id = current_tenant() AND has_role(tenant_id, current_app_user(), ARRAY['owner']));
GRANT SELECT, INSERT, UPDATE ON invitation TO nigiwai_app, nigiwai_worker;

-- What someone holding a link may learn before they have an account: the account's name, the role offered and whether it still
-- works. Nothing else about the account or who is in it.
CREATE OR REPLACE FUNCTION invitation_peek(p_hash bytea) RETURNS TABLE (tenant_name text, role text, state text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT t.name, i.role,
         CASE WHEN i.accepted_at IS NOT NULL THEN 'used'
              WHEN i.revoked_at IS NOT NULL THEN 'revoked'
              WHEN i.expires_at <= now() THEN 'expired'
              ELSE 'open' END
  FROM invitation i JOIN tenant t ON t.id = i.tenant_id
  WHERE i.token_hash = p_hash AND t.deleted_at IS NULL
$$;

-- Joining. It runs as the signed-in person (never a name in the request), fails unless the link still works, and makes the
-- membership and marks the link used in one step so a link cannot be used twice. Someone already in the account is refused
-- rather than changed: a link never changes an existing role.
CREATE OR REPLACE FUNCTION invitation_accept(p_hash bytea, p_user uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE v_inv invitation%ROWTYPE;
BEGIN
  IF p_user IS DISTINCT FROM current_app_user() THEN
    RAISE EXCEPTION 'an invitation can only be accepted by the signed-in user' USING ERRCODE = '42501';
  END IF;
  SELECT * INTO v_inv FROM invitation WHERE token_hash = p_hash FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'invitation not found' USING ERRCODE = 'P0002';
  END IF;
  IF v_inv.accepted_at IS NOT NULL OR v_inv.revoked_at IS NOT NULL OR v_inv.expires_at <= now() THEN
    RAISE EXCEPTION 'invitation is not open' USING ERRCODE = 'P0001';
  END IF;
  IF EXISTS (SELECT 1 FROM membership WHERE tenant_id = v_inv.tenant_id AND user_id = p_user) THEN
    RAISE EXCEPTION 'already a member' USING ERRCODE = '23505';
  END IF;
  INSERT INTO membership (tenant_id, user_id, role) VALUES (v_inv.tenant_id, p_user, v_inv.role);
  UPDATE invitation SET accepted_by = p_user, accepted_at = now() WHERE id = v_inv.id;
  RETURN v_inv.tenant_id;
END
$$;

-- The people in an account, with their sign-in addresses. Only someone who is themselves a member may ask, because the address
-- table is private to each person.
CREATE OR REPLACE FUNCTION team_members(p_tenant uuid) RETURNS TABLE (user_id uuid, email text, role text, joined_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT m.user_id, u.email::text, m.role, m.created_at
  FROM membership m JOIN app_user u ON u.id = m.user_id
  WHERE m.tenant_id = p_tenant AND u.deleted_at IS NULL
    AND has_role(p_tenant, current_app_user(), ARRAY['owner', 'manager', 'viewer'])
  ORDER BY (m.role = 'owner') DESC, m.created_at, u.email
$$;

REVOKE ALL ON FUNCTION invitation_peek(bytea), invitation_accept(bytea, uuid), team_members(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION invitation_peek(bytea), invitation_accept(bytea, uuid), team_members(uuid) TO nigiwai_app;

-- An account always keeps an owner: the last one cannot be removed or demoted. (Deleting the whole account still works.)
CREATE OR REPLACE FUNCTION keep_one_owner() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
BEGIN
  IF OLD.role = 'owner'
     AND (TG_OP = 'DELETE' OR NEW.role IS DISTINCT FROM 'owner')
     AND EXISTS (SELECT 1 FROM tenant WHERE id = OLD.tenant_id)
     AND NOT EXISTS (
       SELECT 1 FROM membership
       WHERE tenant_id = OLD.tenant_id AND role = 'owner' AND user_id <> OLD.user_id
     )
  THEN
    RAISE EXCEPTION 'an account must keep at least one owner' USING ERRCODE = 'P0001';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;
CREATE TRIGGER keep_one_owner_upd BEFORE UPDATE ON membership FOR EACH ROW EXECUTE FUNCTION keep_one_owner();
CREATE TRIGGER keep_one_owner_del BEFORE DELETE ON membership FOR EACH ROW EXECUTE FUNCTION keep_one_owner();
