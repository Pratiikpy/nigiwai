-- Runs once when the local database is first created.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- The application connects as a role that does not own the tables and cannot bypass row-level security.
-- Passwords here are for local development only; production sets its own through the environment.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nigiwai_app') THEN
    CREATE ROLE nigiwai_app LOGIN PASSWORD 'nigiwai-app-dev-only' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nigiwai_worker') THEN
    CREATE ROLE nigiwai_worker LOGIN PASSWORD 'nigiwai-worker-dev-only' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE nigiwai TO nigiwai_app, nigiwai_worker;
