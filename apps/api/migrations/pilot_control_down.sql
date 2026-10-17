-- Empty-ledger guard and original procedure restoration run before this file.
RESET ROLE;
REVOKE SELECT ON alembic_version FROM rv_pilot_controller,rv_pilot_executor;
DROP TRIGGER pilot_attempt_guard ON pilot_attempts;
DROP TRIGGER pilot_binding_guard ON pilot_bindings;
DROP TRIGGER pilot_validation_guard ON pilot_validations;
DROP TRIGGER pilot_audit_guard ON pilot_audit;
SET LOCAL ROLE rv_executor;
REVOKE ALL ON FUNCTION rv.heartbeat(uuid,bigint),rv.analysis_scope_v23(uuid,bigint),
 rv.fail_analysis(uuid,bigint,text,boolean),rv.finish_analysis_v23(uuid,bigint,uuid,text,text,bigint,text,jsonb)
 FROM rv_pilot_executor;
DO $$ DECLARE f regprocedure; BEGIN
 FOR f IN SELECT oid::regprocedure FROM pg_proc WHERE pronamespace='rv'::regnamespace
 AND proname LIKE 'pilot_%' LOOP EXECUTE 'DROP FUNCTION '||f; END LOOP;
END $$;
