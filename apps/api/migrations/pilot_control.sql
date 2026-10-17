-- Additive control-plane state. No historical jobs, artifacts or evaluation rows are updated.
RESET ROLE;
GRANT CREATE ON SCHEMA rv TO rv_executor;
CREATE TABLE pilot_attempts (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id),
 manifest_body text NOT NULL, manifest_sha text NOT NULL CHECK(manifest_sha ~ '^[a-f0-9]{64}$'),
 state text NOT NULL DEFAULT 'ACTIVE' CHECK(state IN ('ACTIVE','INVALIDATED','EXECUTION_CLOSED')),
 generation bigint NOT NULL DEFAULT 1 CHECK(generation>0),
 expires_at timestamptz NOT NULL, reason text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,id)
);
CREATE TABLE pilot_bindings (
 job_id uuid PRIMARY KEY, owner_id uuid NOT NULL, attempt_id uuid NOT NULL,
 project_id uuid NOT NULL, family text NOT NULL, generation bigint NOT NULL,
 FOREIGN KEY(owner_id,attempt_id) REFERENCES pilot_attempts(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id),
 FOREIGN KEY(owner_id,project_id) REFERENCES projects(owner_id,id),
 UNIQUE(attempt_id,family), UNIQUE(project_id)
);
CREATE TABLE pilot_validations (
 stage_id uuid NOT NULL, fence bigint NOT NULL, owner_id uuid NOT NULL,
 manifest_sha text NOT NULL, PRIMARY KEY(stage_id,fence),
 FOREIGN KEY(owner_id,stage_id) REFERENCES job_stages(owner_id,id)
);
CREATE TABLE pilot_audit (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL,
 attempt_id uuid NOT NULL, event text NOT NULL, generation bigint NOT NULL,
 stage_id uuid, actor text NOT NULL DEFAULT session_user, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(owner_id,attempt_id) REFERENCES pilot_attempts(owner_id,id)
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['pilot_attempts','pilot_bindings','pilot_validations','pilot_audit'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY internal ON %I TO rv_executor USING(true) WITH CHECK(true)',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE,TRIGGER ON %I TO rv_executor',t);
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public,rv TO rv_pilot_controller,rv_pilot_executor;
GRANT SELECT ON alembic_version TO rv_pilot_controller,rv_pilot_executor;
SET LOCAL ROLE rv_executor;

CREATE FUNCTION rv.pilot_record(a pilot_attempts,event text,sid uuid DEFAULT NULL) RETURNS void
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 INSERT INTO pilot_audit(owner_id,attempt_id,event,generation,stage_id)
 VALUES(a.owner_id,a.id,event,a.generation,sid) $$;

CREATE FUNCTION rv.pilot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME<>'pilot_attempts' THEN RAISE EXCEPTION 'pilot_record_immutable'; END IF;
 IF TG_OP='DELETE' OR OLD.state<>'ACTIVE' THEN RAISE EXCEPTION 'pilot_terminal_immutable'; END IF;
 IF (NEW.id,NEW.owner_id,NEW.manifest_body,NEW.manifest_sha,NEW.created_at)
  IS DISTINCT FROM (OLD.id,OLD.owner_id,OLD.manifest_body,OLD.manifest_sha,OLD.created_at)
  OR NEW.expires_at>OLD.expires_at OR NEW.generation<>OLD.generation+1
  OR NEW.state NOT IN ('INVALIDATED','EXECUTION_CLOSED') THEN RAISE EXCEPTION 'pilot_transition'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pilot_attempt_guard BEFORE UPDATE OR DELETE ON pilot_attempts FOR EACH ROW EXECUTE FUNCTION rv.pilot_guard();
CREATE TRIGGER pilot_binding_guard BEFORE UPDATE OR DELETE ON pilot_bindings FOR EACH ROW EXECUTE FUNCTION rv.pilot_guard();
CREATE TRIGGER pilot_validation_guard BEFORE UPDATE OR DELETE ON pilot_validations FOR EACH ROW EXECUTE FUNCTION rv.pilot_guard();
CREATE TRIGGER pilot_audit_guard BEFORE UPDATE OR DELETE ON pilot_audit FOR EACH ROW EXECUTE FUNCTION rv.pilot_guard();

CREATE FUNCTION rv.pilot_register(aid uuid,body text,sha text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE m jsonb:=body::jsonb; f jsonb; p jsonb; o uuid:=rv.owner();
BEGIN
 IF o IS NULL OR NOT pg_has_role(session_user,'rv_pilot_controller','member') THEN RAISE EXCEPTION 'pilot_unauthorized'; END IF;
 IF octet_length(body)>1048576 OR encode(sha256(convert_to(body,'UTF8')),'hex')<>sha
  OR NOT coalesce(m->>'version'='pilot-control-1.0' AND m->>'owner'=o::text
   AND m->>'engine'='711184e82128c7b0a6f3978cfc1cf13975db39ef'
   AND m->>'scorer'=m->>'engine' AND m->>'approval_sha256' ~ '^[a-f0-9]{64}$'
   AND jsonb_typeof(m->'engine_files')='object' AND jsonb_typeof(m->'families')='array'
   AND jsonb_array_length(m->'families') BETWEEN 1 AND 3,false) THEN RAISE EXCEPTION 'pilot_manifest'; END IF;
 IF (SELECT count(*)<>count(DISTINCT v->>'id') OR count(*)<>count(DISTINCT lower(v->>'repository'))
     FROM jsonb_array_elements(m->'families') v) THEN RAISE EXCEPTION 'pilot_duplicate_family'; END IF;
 FOR f IN SELECT * FROM jsonb_array_elements(m->'families') LOOP
  IF NOT coalesce(f->>'id' ~ '^[a-z][a-z0-9_-]{0,63}$' AND f->>'repository' ~ '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
   AND f->>'commit' ~ '^[a-f0-9]{40}$' AND jsonb_typeof(f->'files')='array'
   AND jsonb_array_length(f->'files') BETWEEN 1 AND 5000,false) THEN RAISE EXCEPTION 'pilot_family'; END IF;
  IF (SELECT count(*)<>count(DISTINCT v->>'path') OR sum((v->>'size')::bigint)>104857600
      OR count(*) FILTER(WHERE v->>'role'='source')=0 FROM jsonb_array_elements(f->'files') v)
   THEN RAISE EXCEPTION 'pilot_files'; END IF;
  FOR p IN SELECT * FROM jsonb_array_elements(f->'files') LOOP
   IF NOT coalesce(p->>'sha256' ~ '^[a-f0-9]{64}$' AND (p->>'size')::bigint BETWEEN 1 AND 1048576
     AND p->>'role' IN ('source','context') AND length(p->>'path') BETWEEN 1 AND 1024,false)
     OR position(chr(92) IN p->>'path')>0 OR position(':' IN p->>'path')>0
     OR EXISTS(SELECT 1 FROM unnest(string_to_array(p->>'path','/')) v WHERE v IN ('','.','..'))
    THEN RAISE EXCEPTION 'pilot_file'; END IF;
  END LOOP;
 END LOOP;
 INSERT INTO pilot_attempts(id,owner_id,manifest_body,manifest_sha,expires_at)
 VALUES(aid,o,body,sha,clock_timestamp()+interval '45 minutes');
 PERFORM rv.pilot_record(a,'registered') FROM pilot_attempts a WHERE id=aid;
 RETURN aid;
END $$;

CREATE FUNCTION rv.pilot_invalidate(aid uuid,gen bigint,why text) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts; b record;
BEGIN
 SELECT * INTO a FROM pilot_attempts WHERE id=aid;
 IF NOT FOUND OR a.owner_id IS DISTINCT FROM rv.owner()
 THEN RAISE EXCEPTION 'pilot_not_found'; END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=a.owner_id FOR UPDATE;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid FOR UPDATE;
 IF a.state<>'ACTIVE' THEN PERFORM rv.pilot_record(a,'duplicate_invalidation'); RETURN a.state; END IF;
 IF a.generation<>gen THEN PERFORM rv.pilot_record(a,'stale_invalidation'); RETURN a.state; END IF;
 UPDATE pilot_attempts SET state='INVALIDATED',generation=generation+1,reason=left(why,128) WHERE id=aid RETURNING * INTO a;
 FOR b IN SELECT job_id FROM pilot_bindings WHERE attempt_id=aid ORDER BY job_id LOOP
  PERFORM rv.end_job(b.job_id,'failed','pilot_invalidated');
 END LOOP;
 PERFORM rv.pilot_record(a,'invalidated'); RETURN a.state;
END $$;

CREATE FUNCTION rv.pilot_admit(aid uuid,gen bigint,fid text,pid uuid,body text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts; f jsonb; m jsonb:=body::jsonb; jid uuid; vhash text;
BEGIN
 IF NOT pg_has_role(session_user,'rv_pilot_controller','member') THEN RAISE EXCEPTION 'pilot_unauthorized'; END IF;
 PERFORM pg_advisory_xact_lock(712031);
 PERFORM 1 FROM quota_accounts WHERE owner_id=rv.owner() FOR UPDATE;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid AND owner_id=rv.owner() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'pilot_not_found'; END IF;
 IF a.state<>'ACTIVE' OR a.generation<>gen OR a.expires_at<=clock_timestamp()
 THEN PERFORM rv.pilot_record(a,'admission_denied'); RETURN NULL; END IF;
 SELECT v INTO f FROM jsonb_array_elements(a.manifest_body::jsonb->'families') v WHERE v->>'id'=fid;
 IF f IS NULL OR NOT coalesce(m->>'repository'=f->>'repository' AND m->>'commit_sha'=f->>'commit'
  AND m->>'canonical_url'='https://github.com/'||(f->>'repository') AND m->>'public'='true',false)
  OR NOT EXISTS(SELECT 1 FROM projects WHERE id=pid AND owner_id=a.owner_id AND deleted_at IS NULL
    AND repository_url='https://github.com/'||(f->>'repository')) THEN RAISE EXCEPTION 'pilot_scope_binding'; END IF;
 SELECT job_id INTO jid FROM pilot_bindings WHERE attempt_id=aid AND family=fid;
 IF FOUND THEN
  IF NOT EXISTS(SELECT 1 FROM pilot_bindings WHERE job_id=jid AND project_id=pid)
  THEN RAISE EXCEPTION 'pilot_scope_binding'; END IF;
  RETURN jid;
 END IF;
 IF EXISTS(SELECT 1 FROM generation_jobs WHERE project_id=pid) THEN RAISE EXCEPTION 'pilot_project_not_empty'; END IF;
 vhash:=encode(sha256(convert_to(body,'UTF8')),'hex');
 jid:=rv.admit_analysis(pid,'pilot:'||aid||':'||fid,vhash,f->>'commit',m,vhash,NULL);
 INSERT INTO pilot_bindings(job_id,owner_id,attempt_id,project_id,family,generation)
 VALUES(jid,a.owner_id,aid,pid,fid,gen);
 PERFORM rv.pilot_record(a,'admitted'); RETURN jid;
END $$;

CREATE OR REPLACE FUNCTION rv.admit_analysis(pid uuid,idem text,digest text,sha text,metadata jsonb,validation_hash text,prior uuid DEFAULT NULL)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(712031);
 PERFORM 1 FROM quota_accounts WHERE owner_id=rv.owner() FOR UPDATE;
 IF EXISTS(SELECT 1 FROM pilot_bindings WHERE project_id=pid) THEN RAISE EXCEPTION 'pilot_admission_route_required'; END IF;
 RETURN rv.cp_original_admit_analysis(pid,idem,digest,sha,metadata,validation_hash,prior);
END $$;
CREATE OR REPLACE FUNCTION rv.admit(pid uuid,idem text,digest text,fixture_name text,prior uuid DEFAULT NULL)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(712031);
 PERFORM 1 FROM quota_accounts WHERE owner_id=rv.owner() FOR UPDATE;
 IF EXISTS(SELECT 1 FROM pilot_bindings WHERE project_id=pid) THEN RAISE EXCEPTION 'pilot_admission_route_required'; END IF;
 RETURN rv.cp_original_admit(pid,idem,digest,fixture_name,prior);
END $$;
CREATE OR REPLACE FUNCTION rv.delete_project(pid uuid) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE b pilot_bindings;
BEGIN
 SELECT * INTO b FROM pilot_bindings WHERE project_id=pid AND owner_id=rv.owner();
 IF FOUND THEN PERFORM rv.pilot_invalidate(b.attempt_id,b.generation,'source_withdrawn'); END IF;
 RETURN rv.cp_original_delete_project(pid);
END $$;

CREATE FUNCTION rv.pilot_permitted(jid uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
 SELECT CASE WHEN EXISTS(SELECT 1 FROM pilot_bindings WHERE job_id=jid) THEN
  pg_has_role(session_user,'rv_pilot_executor','member') AND EXISTS(
   SELECT 1 FROM pilot_bindings b JOIN pilot_attempts a ON a.id=b.attempt_id AND a.owner_id=b.owner_id
   WHERE b.job_id=jid AND a.owner_id=rv.owner() AND a.state='ACTIVE' AND a.generation=b.generation AND a.expires_at>clock_timestamp())
 ELSE NOT pg_has_role(session_user,'rv_pilot_executor','member') END $$;

CREATE OR REPLACE FUNCTION rv.valid_lease(s job_stages,j generation_jobs,epoch bigint) RETURNS boolean
 LANGUAGE sql SET search_path=pg_catalog,public,rv AS $$
 SELECT rv.cp_original_valid_lease(s,j,epoch) AND rv.pilot_permitted(j.id) $$;

CREATE OR REPLACE FUNCTION rv.claim(sid uuid,worker text) RETURNS TABLE(owner_id uuid,job_id uuid,
 snapshot_id uuid,stage_id uuid,fence bigint,attempt_no int,fixture text,ordinal int)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts;
BEGIN
 SELECT a0.* INTO a FROM pilot_attempts a0 JOIN pilot_bindings b ON b.attempt_id=a0.id
 JOIN job_stages s ON s.job_id=b.job_id WHERE s.id=sid;
 IF FOUND THEN PERFORM rv.pilot_record(a,'routine_claim_denied',sid); RETURN; END IF;
 IF pg_has_role(session_user,'rv_pilot_executor','member') THEN RETURN; END IF;
 RETURN QUERY SELECT * FROM rv.cp_original_claim(sid,worker);
END $$;

CREATE FUNCTION rv.pilot_claim(sid uuid,aid uuid,gen bigint,sha text,fid text) RETURNS TABLE(owner_id uuid,job_id uuid,
 snapshot_id uuid,stage_id uuid,fence bigint,attempt_no int,fixture text,ordinal int)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts;
BEGIN
 IF NOT pg_has_role(session_user,'rv_pilot_executor','member') THEN RAISE EXCEPTION 'pilot_unauthorized'; END IF;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid;
 IF NOT FOUND THEN RETURN; END IF;
 PERFORM 1 FROM quota_accounts WHERE quota_accounts.owner_id=a.owner_id FOR UPDATE;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid FOR UPDATE;
 IF a.owner_id IS DISTINCT FROM rv.owner() OR a.state<>'ACTIVE' OR a.generation<>gen OR a.manifest_sha<>sha OR a.expires_at<=clock_timestamp()
  OR NOT EXISTS(SELECT 1 FROM pilot_bindings b JOIN job_stages s ON s.job_id=b.job_id
    WHERE s.id=sid AND b.attempt_id=aid AND b.generation=gen AND b.owner_id=a.owner_id AND b.family=fid)
 THEN PERFORM rv.pilot_record(a,'claim_denied',sid); RETURN; END IF;
 RETURN QUERY SELECT * FROM rv.cp_original_claim(sid,'authenticated-pilot');
 IF FOUND THEN PERFORM rv.pilot_record(a,'claimed',sid);
 ELSE PERFORM rv.pilot_record(a,'claim_unavailable',sid); END IF;
END $$;

CREATE FUNCTION rv.pilot_close(aid uuid,gen bigint) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts;
BEGIN
 IF NOT pg_has_role(session_user,'rv_pilot_controller','member') THEN RAISE EXCEPTION 'pilot_unauthorized'; END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=rv.owner() FOR UPDATE;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid AND owner_id=rv.owner() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'pilot_not_found'; END IF;
 IF a.state<>'ACTIVE' THEN RETURN a.state; END IF;
 IF a.generation<>gen OR a.expires_at<=clock_timestamp()
 OR (SELECT count(*) FROM pilot_bindings WHERE attempt_id=aid)<>jsonb_array_length(a.manifest_body::jsonb->'families')
 OR EXISTS(SELECT 1 FROM pilot_bindings b WHERE b.attempt_id=aid AND NOT EXISTS(
   SELECT 1 FROM job_stages s WHERE s.job_id=b.job_id AND s.ordinal=9 AND s.state='succeeded'))
 THEN PERFORM rv.pilot_record(a,'close_denied'); RETURN a.state; END IF;
 UPDATE pilot_attempts SET state='EXECUTION_CLOSED',generation=generation+1,reason='execution_complete' WHERE id=aid RETURNING * INTO a;
 PERFORM rv.pilot_record(a,'execution_closed'); RETURN 'EXECUTION_CLOSED';
END $$;

CREATE FUNCTION rv.pilot_scope(sid uuid,epoch bigint) RETURNS text
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts; s job_stages; j generation_jobs;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid; SELECT * INTO j FROM generation_jobs WHERE id=s.job_id;
 IF NOT rv.valid_lease(s,j,epoch) THEN RETURN NULL; END IF;
 SELECT a0.* INTO a FROM pilot_attempts a0 JOIN pilot_bindings b ON b.attempt_id=a0.id WHERE b.job_id=j.id;
 RETURN a.manifest_body;
END $$;

CREATE FUNCTION rv.pilot_verified(sid uuid,epoch bigint,sha text) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE body text; b pilot_bindings;
BEGIN
 SELECT b0.* INTO b FROM pilot_bindings b0 JOIN job_stages s ON s.job_id=b0.job_id WHERE s.id=sid;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=b.owner_id FOR UPDATE;
 PERFORM 1 FROM pilot_attempts WHERE id=b.attempt_id FOR UPDATE;
 body:=rv.pilot_scope(sid,epoch);
 IF body IS NULL OR encode(sha256(convert_to(body,'UTF8')),'hex')<>sha THEN RETURN false; END IF;
 INSERT INTO pilot_validations(stage_id,fence,owner_id,manifest_sha)
 SELECT sid,epoch,owner_id,sha FROM job_stages WHERE id=sid ON CONFLICT DO NOTHING;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION rv.fail_analysis(sid uuid,epoch bigint,code text,transient boolean) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE b pilot_bindings; s job_stages; j generation_jobs;
BEGIN
 SELECT b0.* INTO b FROM pilot_bindings b0 JOIN job_stages s0 ON s0.job_id=b0.job_id WHERE s0.id=sid;
 IF FOUND THEN
  SELECT * INTO s FROM job_stages WHERE id=sid; SELECT * INTO j FROM generation_jobs WHERE id=s.job_id;
  IF NOT rv.valid_lease(s,j,epoch) THEN RETURN false; END IF;
  PERFORM rv.pilot_invalidate(b.attempt_id,b.generation,code); RETURN false;
 END IF;
 RETURN rv.cp_original_fail_analysis(sid,epoch,code,transient);
END $$;

CREATE OR REPLACE FUNCTION rv.cancel(jid uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE b pilot_bindings;
BEGIN
 SELECT * INTO b FROM pilot_bindings WHERE job_id=jid AND owner_id=rv.owner();
 IF FOUND THEN PERFORM rv.pilot_invalidate(b.attempt_id,b.generation,'owner_cancelled');
 ELSE PERFORM rv.cp_original_cancel(jid); END IF;
END $$;

CREATE OR REPLACE FUNCTION rv.reconcile() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts;
BEGIN
 FOR a IN SELECT * FROM pilot_attempts WHERE state='ACTIVE' AND
  (expires_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM pilot_bindings b JOIN job_stages s ON s.job_id=b.job_id
   WHERE b.attempt_id=pilot_attempts.id AND (s.state='retry_wait' OR
    (s.state='running' AND (s.lease_expires_at<=clock_timestamp() OR s.stage_deadline<=clock_timestamp()))))) LOOP
  -- Recovery is internal, not a caller-supplied execution authorization.
  PERFORM 1 FROM quota_accounts WHERE owner_id=a.owner_id FOR UPDATE;
  PERFORM 1 FROM pilot_attempts WHERE id=a.id FOR UPDATE;
  IF (SELECT state FROM pilot_attempts WHERE id=a.id)='ACTIVE' THEN
   UPDATE pilot_attempts SET state='INVALIDATED',generation=generation+1,reason='pilot_recovery_closed' WHERE id=a.id RETURNING * INTO a;
   PERFORM rv.end_job(b.job_id,'failed','pilot_invalidated') FROM pilot_bindings b WHERE b.attempt_id=a.id;
   PERFORM rv.pilot_record(a,'recovery_invalidated');
  END IF;
 END LOOP;
 RETURN rv.cp_original_reconcile();
END $$;

CREATE OR REPLACE FUNCTION rv.dispatch_batch() RETURNS TABLE(event_id uuid,stage_id uuid,event_type text)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT e.id,e.stage_id,e.event_type FROM outbox_events e WHERE e.published_at IS NULL AND e.due_at<=now()
 AND NOT EXISTS(SELECT 1 FROM pilot_bindings b WHERE b.job_id=e.job_id) ORDER BY due_at LIMIT 100 $$;

CREATE OR REPLACE FUNCTION rv.published(eid uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM pilot_bindings b JOIN outbox_events e ON e.job_id=b.job_id WHERE e.id=eid) THEN RETURN; END IF;
 PERFORM rv.cp_original_published(eid);
END $$;

CREATE FUNCTION rv.pilot_delivery(aid uuid,gen bigint) RETURNS TABLE(event_id uuid,stage_id uuid)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT e.id,e.stage_id FROM outbox_events e JOIN pilot_bindings b ON b.job_id=e.job_id
 JOIN pilot_attempts a ON a.id=b.attempt_id WHERE a.id=aid AND a.generation=gen AND b.generation=gen
 AND a.state='ACTIVE' AND a.expires_at>clock_timestamp() AND e.published_at IS NULL AND e.due_at<=now()
 AND a.owner_id=rv.owner() AND pg_has_role(session_user,'rv_pilot_executor','member') ORDER BY e.due_at LIMIT 100 $$;

CREATE FUNCTION rv.pilot_published(eid uuid,aid uuid,gen bigint) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts; notification outbox_events; j generation_jobs; s job_stages;
BEGIN
 IF NOT pg_has_role(session_user,'rv_pilot_executor','member') THEN RAISE EXCEPTION 'pilot_unauthorized'; END IF;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid AND owner_id=rv.owner();
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=a.owner_id FOR UPDATE;
 SELECT * INTO a FROM pilot_attempts WHERE id=aid FOR UPDATE;
 IF a.state<>'ACTIVE' OR a.generation<>gen OR a.expires_at<=clock_timestamp()
 THEN PERFORM rv.pilot_record(a,'delivery_denied'); RETURN false; END IF;
 SELECT e.* INTO notification FROM outbox_events e JOIN pilot_bindings b ON b.job_id=e.job_id
 WHERE e.id=eid AND e.owner_id=a.owner_id AND e.event_type='stage'
 AND b.attempt_id=aid AND b.owner_id=a.owner_id AND b.generation=gen;
 IF NOT FOUND THEN PERFORM rv.pilot_record(a,'delivery_denied'); RETURN false; END IF;
 -- Match claim/completion lock order. Keep job/stage readiness stable until commit.
 SELECT * INTO j FROM generation_jobs WHERE id=notification.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=notification.stage_id AND job_id=j.id FOR UPDATE;
 IF NOT FOUND OR j.state NOT IN ('queued','running') OR s.state<>'ready' OR s.attempt_count>=s.max_attempts
 OR NOT EXISTS(SELECT 1 FROM projects WHERE id=j.project_id AND deleted_at IS NULL)
 OR NOT EXISTS(SELECT 1 FROM quota_reservations WHERE job_id=j.id AND status='reserved')
 THEN PERFORM rv.pilot_record(a,'delivery_ineligible',notification.stage_id); RETURN false; END IF;
 -- Acquire the event lock before evaluating time predicates, even if its holder
 -- only SELECTed FOR UPDATE and left the tuple unchanged while authorization expired.
 PERFORM 1 FROM outbox_events WHERE id=eid FOR UPDATE;
 -- Recheck current event identity/eligibility and time after all possible row waits.
 UPDATE outbox_events e SET published_at=clock_timestamp()
 WHERE e.id=eid AND e.owner_id=a.owner_id AND e.job_id=j.id AND e.stage_id=s.id AND e.event_type='stage'
 AND e.published_at IS NULL AND e.due_at<=clock_timestamp()
 AND a.expires_at>clock_timestamp() AND j.deadline>clock_timestamp();
 IF NOT FOUND THEN PERFORM rv.pilot_record(a,'delivery_ineligible',s.id); RETURN false; END IF;
 RETURN true;
END $$;

CREATE FUNCTION rv.pilot_status(aid uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE a pilot_attempts;
BEGIN
 SELECT * INTO a FROM pilot_attempts WHERE id=aid AND owner_id=rv.owner();
 IF NOT FOUND THEN RAISE EXCEPTION 'pilot_not_found'; END IF;
 RETURN jsonb_build_object('state',a.state,'generation',a.generation,'reason',a.reason,'manifest_sha',a.manifest_sha);
END $$;

-- Gate final publication under the same owner/attempt locks as cancellation.
CREATE FUNCTION rv.pilot_finish_allowed(sid uuid,epoch bigint) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE b pilot_bindings; a pilot_attempts; s job_stages; j generation_jobs;
BEGIN
 SELECT b0.* INTO b FROM pilot_bindings b0 JOIN job_stages s0 ON s0.job_id=b0.job_id WHERE s0.id=sid;
 IF NOT FOUND THEN RETURN NOT pg_has_role(session_user,'rv_pilot_executor','member'); END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=b.owner_id FOR UPDATE;
 SELECT * INTO a FROM pilot_attempts WHERE id=b.attempt_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid; SELECT * INTO j FROM generation_jobs WHERE id=s.job_id;
 IF NOT rv.valid_lease(s,j,epoch) THEN PERFORM rv.pilot_record(a,'publication_denied',sid); RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM pilot_validations WHERE stage_id=sid AND fence=epoch AND manifest_sha=a.manifest_sha)
 THEN PERFORM rv.pilot_invalidate(a.id,a.generation,'pilot_scope_unverified'); RETURN false; END IF;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION rv.finish_analysis_v23(sid uuid,epoch bigint,artifact uuid,checksum text,object_path text,
 bytes bigint,input_hash text,summary jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
BEGIN
 IF NOT rv.pilot_finish_allowed(sid,epoch) THEN RETURN false; END IF;
 RETURN rv.cp_original_finish_analysis_v23(sid,epoch,artifact,checksum,object_path,bytes,input_hash,summary);
END $$;
CREATE OR REPLACE FUNCTION rv.finish_analysis(sid uuid,epoch bigint,artifact uuid,checksum text,object_path text,
 bytes bigint,input_hash text,summary jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM pilot_bindings b JOIN job_stages s ON s.job_id=b.job_id WHERE s.id=sid) THEN RETURN false; END IF;
 RETURN rv.cp_original_finish_analysis(sid,epoch,artifact,checksum,object_path,bytes,input_hash,summary);
END $$;

DO $$ DECLARE f regprocedure; BEGIN
 FOR f IN SELECT oid::regprocedure FROM pg_proc WHERE pronamespace='rv'::regnamespace
 AND (proname LIKE 'pilot_%' OR proname LIKE 'cp_original_%') LOOP
  EXECUTE 'ALTER FUNCTION '||f||' OWNER TO rv_executor';
  EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM PUBLIC,rv_app,rv_worker,rv_pilot_controller,rv_pilot_executor';
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION rv.pilot_register(uuid,text,text),rv.pilot_admit(uuid,bigint,text,uuid,text),
 rv.pilot_invalidate(uuid,bigint,text),rv.pilot_status(uuid),rv.pilot_close(uuid,bigint) TO rv_pilot_controller;
GRANT EXECUTE ON FUNCTION rv.pilot_claim(uuid,uuid,bigint,text,text),rv.pilot_scope(uuid,bigint),
 rv.pilot_verified(uuid,bigint,text),rv.pilot_delivery(uuid,bigint),rv.pilot_published(uuid,uuid,bigint),rv.pilot_invalidate(uuid,bigint,text),
 rv.heartbeat(uuid,bigint),rv.analysis_scope_v23(uuid,bigint),rv.fail_analysis(uuid,bigint,text,boolean),
 rv.finish_analysis_v23(uuid,bigint,uuid,text,text,bigint,text,jsonb) TO rv_pilot_executor;
RESET ROLE;
REVOKE CREATE ON SCHEMA rv FROM rv_executor;
