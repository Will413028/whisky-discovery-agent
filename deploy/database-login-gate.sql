-- Install after product migration as the cluster administrator.
-- PostgreSQL login triggers require superuser, so this is deliberately
-- separate from the product DDL migration.
CREATE OR REPLACE FUNCTION public.whisky_recovery_login_guard()
RETURNS event_trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard$
BEGIN
    IF session_user = 'whisky_runtime'
       AND NOT EXISTS (
           SELECT 1 FROM public.recovery_gate
           WHERE id = 1
             AND postmaster_started_at = pg_postmaster_start_time()
       ) THEN
        RAISE EXCEPTION 'database requires control reconciliation'
            USING ERRCODE = '55000';
    END IF;
END
$guard$;
REVOKE ALL ON FUNCTION public.whisky_recovery_login_guard() FROM PUBLIC;

DO $install$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_event_trigger
        WHERE evtname = 'whisky_recovery_login_gate'
    ) THEN
        CREATE EVENT TRIGGER whisky_recovery_login_gate
            ON login EXECUTE FUNCTION public.whisky_recovery_login_guard();
    END IF;
END
$install$;
ALTER EVENT TRIGGER whisky_recovery_login_gate ENABLE ALWAYS;
