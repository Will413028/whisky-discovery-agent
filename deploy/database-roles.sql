\set ON_ERROR_STOP on
-- Bootstrap administrator is kept only for this one-shot role operation.
-- Passwords arrive through environment variables, never through tracked SQL.
\getenv product_password WHISKY_PRODUCT_DB_PASSWORD
\getenv ddl_password WHISKY_PRODUCT_DDL_PASSWORD
\getenv temporal_password WHISKY_TEMPORAL_DB_PASSWORD
\getenv temporal_schema_password WHISKY_TEMPORAL_SCHEMA_PASSWORD

SELECT 'CREATE ROLE whisky_runtime LOGIN' WHERE NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname='whisky_runtime') \gexec
SELECT 'CREATE ROLE whisky_ddl LOGIN' WHERE NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname='whisky_ddl') \gexec
SELECT 'CREATE ROLE whisky_temporal_runtime LOGIN' WHERE NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname='whisky_temporal_runtime') \gexec
SELECT 'CREATE ROLE whisky_temporal_schema LOGIN' WHERE NOT EXISTS
  (SELECT 1 FROM pg_roles WHERE rolname='whisky_temporal_schema') \gexec

ALTER ROLE whisky_runtime PASSWORD :'product_password';
ALTER ROLE whisky_ddl PASSWORD :'ddl_password';
ALTER ROLE whisky_temporal_runtime PASSWORD :'temporal_password';
ALTER ROLE whisky_temporal_schema PASSWORD :'temporal_schema_password';

SELECT 'CREATE DATABASE temporal OWNER whisky_temporal_schema' WHERE NOT EXISTS
  (SELECT 1 FROM pg_database WHERE datname='temporal') \gexec
SELECT 'CREATE DATABASE temporal_visibility OWNER whisky_temporal_schema' WHERE NOT EXISTS
  (SELECT 1 FROM pg_database WHERE datname='temporal_visibility') \gexec
ALTER DATABASE temporal OWNER TO whisky_temporal_schema;
ALTER DATABASE temporal_visibility OWNER TO whisky_temporal_schema;
REVOKE CONNECT,TEMPORARY ON DATABASE whisky FROM PUBLIC;
REVOKE CONNECT,TEMPORARY ON DATABASE temporal FROM PUBLIC;
REVOKE CONNECT,TEMPORARY ON DATABASE temporal_visibility FROM PUBLIC;

\connect whisky
ALTER DATABASE whisky OWNER TO whisky_ddl;
ALTER SCHEMA public OWNER TO whisky_ddl;
-- T02's identity tables were created by the old bootstrap administrator.
-- Transfer only product-schema objects that administrator still owns.
DO $transfer$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT c.relname, c.relkind FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname='whisky')
      AND c.relkind IN ('r','p','S','v','m')
  LOOP
    EXECUTE format(
      'ALTER %s %I.%I OWNER TO whisky_ddl',
      CASE item.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
        WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
      'public', item.relname
    );
  END LOOP;
END $transfer$;
GRANT CONNECT ON DATABASE whisky TO whisky_runtime;
GRANT CONNECT,TEMPORARY ON DATABASE whisky TO whisky_ddl;
GRANT USAGE ON SCHEMA public TO whisky_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO whisky_runtime;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO whisky_runtime;
-- A rerun after migration must not let the serving role attest recovery.
DO $gate$
BEGIN
  IF to_regclass('public.recovery_gate') IS NOT NULL THEN
    REVOKE ALL ON TABLE recovery_gate FROM whisky_runtime;
    GRANT SELECT ON TABLE recovery_gate TO whisky_runtime;
  END IF;
END $gate$;
ALTER DEFAULT PRIVILEGES FOR ROLE whisky_ddl IN SCHEMA public
  GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO whisky_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE whisky_ddl IN SCHEMA public
  GRANT USAGE,SELECT ON SEQUENCES TO whisky_runtime;

\connect temporal
GRANT CONNECT,TEMPORARY ON DATABASE temporal TO whisky_temporal_runtime;
GRANT USAGE ON SCHEMA public TO whisky_temporal_runtime;
GRANT ALL ON ALL TABLES IN SCHEMA public TO whisky_temporal_runtime;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO whisky_temporal_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE whisky_temporal_schema IN SCHEMA public
  GRANT ALL ON TABLES TO whisky_temporal_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE whisky_temporal_schema IN SCHEMA public
  GRANT ALL ON SEQUENCES TO whisky_temporal_runtime;

\connect temporal_visibility
GRANT CONNECT,TEMPORARY ON DATABASE temporal_visibility TO whisky_temporal_runtime;
GRANT USAGE ON SCHEMA public TO whisky_temporal_runtime;
GRANT ALL ON ALL TABLES IN SCHEMA public TO whisky_temporal_runtime;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO whisky_temporal_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE whisky_temporal_schema IN SCHEMA public
  GRANT ALL ON TABLES TO whisky_temporal_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE whisky_temporal_schema IN SCHEMA public
  GRANT ALL ON SEQUENCES TO whisky_temporal_runtime;
