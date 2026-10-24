-- 0018 account: a way back in without email, and the ability to delete an account and everything in it.

-- A recovery code is made when someone signs up (and can be remade when signed in). The person is shown it once; only its SHA-256 is
-- stored. The code is 20 random characters (about 98 bits), so a fast hash is enough: there is nothing to guess.
ALTER TABLE app_user ADD COLUMN recovery_hash bytea, ADD COLUMN recovery_set_at timestamptz;

-- Deleting an account (a tenant) and all its data. Everything that belongs to a tenant is removed by its foreign key, except the log
-- of Qloo calls, which carries the tenant id without one; that is deleted here. A venue that had joined the City Taste Atlas has its
-- counts taken out of the pooled table in the same step, so leaving does not wait for the next scheduled rebuild.
-- Only an owner can call it, and only as themselves; the demo venues' own tenant can never be deleted.
CREATE OR REPLACE FUNCTION delete_tenant(p_tenant uuid, p_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS
$$
DECLARE v_atlas boolean;
BEGIN
  IF p_user IS DISTINCT FROM current_app_user() THEN
    RAISE EXCEPTION 'an account can only be deleted by the signed-in user' USING ERRCODE = '42501';
  END IF;
  IF NOT has_role(p_tenant, p_user, ARRAY['owner']) THEN
    RAISE EXCEPTION 'only an owner can delete an account' USING ERRCODE = '42501';
  END IF;
  IF p_tenant = '6e1c0de0-0000-4000-8000-00000000d3a0'::uuid THEN
    RAISE EXCEPTION 'the demo venues cannot be deleted' USING ERRCODE = '42501';
  END IF;
  v_atlas := EXISTS (SELECT 1 FROM business WHERE tenant_id = p_tenant AND atlas_opt_in);
  DELETE FROM qloo_call WHERE tenant_id = p_tenant;
  DELETE FROM tenant WHERE id = p_tenant;
  IF v_atlas THEN
    PERFORM atlas_rebuild();
  END IF;
END
$$;

-- The accounts a person alone holds up: where they are an owner and no one else is. Deleting their login, or leaving, would leave such
-- an account without an owner, so the person has to hand it on or delete it first. Names only, and only the caller's own.
CREATE OR REPLACE FUNCTION sole_owner_of(p_user uuid) RETURNS TABLE (tenant_id uuid, tenant_name text, others integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT t.id, t.name, (SELECT count(*)::integer FROM membership x WHERE x.tenant_id = t.id AND x.user_id <> p_user)
  FROM membership m JOIN tenant t ON t.id = m.tenant_id
  WHERE p_user = current_app_user() AND m.user_id = p_user AND m.role = 'owner' AND t.deleted_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM membership o WHERE o.tenant_id = m.tenant_id AND o.role = 'owner' AND o.user_id <> p_user)
  ORDER BY t.created_at
$$;

REVOKE ALL ON FUNCTION delete_tenant(uuid, uuid), sole_owner_of(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_tenant(uuid, uuid), sole_owner_of(uuid) TO nigiwai_app;
