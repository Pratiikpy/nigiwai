-- 0019 login tables: row-level security, so the application role sees a person's own login and nothing else (before this, a query run
-- as the application role could read every address and password hash; the tenant tables were already protected and these were not).

-- Signing in and loading a session happen before anyone is known, so they cannot be done as "the signed-in person". These definer
-- functions are the only way the application role reads a login it is not yet signed in as: each answers one question for one key.
CREATE OR REPLACE FUNCTION auth_user_by_email(p_email text) RETURNS TABLE (id uuid, password_hash text, recovery_hash bytea)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$
  SELECT u.id, u.password_hash, u.recovery_hash FROM app_user u WHERE u.email = p_email::citext AND u.deleted_at IS NULL
$$;

-- The session behind a cookie, and (at most once a minute) a note that it was used. VOLATILE because it writes.
CREATE OR REPLACE FUNCTION auth_session(p_hash bytea) RETURNS TABLE (id uuid, user_id uuid, csrf_secret text, email text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public AS
$$
BEGIN
  RETURN QUERY
    SELECT s.id, s.user_id, s.csrf_secret, u.email::text
    FROM app_session s JOIN app_user u ON u.id = s.user_id
    WHERE s.token_hash = p_hash AND s.expires_at > now() AND u.deleted_at IS NULL;
  UPDATE app_session SET last_seen_at = now() WHERE token_hash = p_hash AND last_seen_at < now() - interval '1 minute';
END
$$;

REVOKE ALL ON FUNCTION auth_user_by_email(text), auth_session(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_user_by_email(text), auth_session(bytea) TO nigiwai_app;

-- Everything else is a person acting on their own login, inside a transaction that carries who they are.
CREATE POLICY own_login ON app_user
  USING (id = current_app_user()) WITH CHECK (id = current_app_user());
ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;

CREATE POLICY own_sessions ON app_session
  USING (user_id = current_app_user()) WITH CHECK (user_id = current_app_user());
ALTER TABLE app_session ENABLE ROW LEVEL SECURITY;
