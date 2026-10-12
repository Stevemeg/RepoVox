-- Migration role owns DDL. The non-login executor owns narrowly granted procedures.
CREATE SCHEMA rv;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public, rv TO rv_app, rv_worker, rv_executor;
GRANT CREATE ON SCHEMA rv TO rv_executor;

CREATE FUNCTION rv.owner() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT nullif(current_setting('repovox.owner_id', true), '')::uuid
$$;

CREATE TABLE users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL UNIQUE,
 issuer text NOT NULL, auth_subject text NOT NULL, display_name text NOT NULL,
 email text NOT NULL, status text NOT NULL DEFAULT 'active', deleted_at timestamptz,
 UNIQUE (issuer, auth_subject), UNIQUE(owner_id,id), CHECK(owner_id=id)
);
CREATE TABLE auth_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 nonce_hash text NOT NULL UNIQUE, csrf_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 revoked_at timestamptz, UNIQUE(owner_id,id)
);
CREATE TABLE projects (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 repository_url text NOT NULL, title text NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
 status text NOT NULL DEFAULT 'unprocessed' CHECK(status IN ('unprocessed','deleting','deleted')),
 created_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz,
 UNIQUE(owner_id,id)
);
CREATE TABLE repository_snapshots (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 project_id uuid NOT NULL, commit_sha text NOT NULL CHECK(commit_sha ~ '^[a-f0-9]{40}$'),
 synthetic boolean NOT NULL, acquisition_version text NOT NULL, pipeline_version text NOT NULL,
 metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,id), UNIQUE(owner_id,project_id,commit_sha,acquisition_version),
 FOREIGN KEY(owner_id,project_id) REFERENCES projects(owner_id,id)
);
CREATE TABLE generation_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 project_id uuid NOT NULL, snapshot_id uuid NOT NULL, prior_job_id uuid,
 state text NOT NULL CHECK(state IN ('queued','running','retry_wait','awaiting_reconciliation',
 'cancel_requested','cancelled','failed','succeeded')),
 version integer NOT NULL DEFAULT 1, synthetic boolean NOT NULL DEFAULT true CHECK(synthetic),
 fixture text NOT NULL CHECK(fixture IN ('normal','transient_once','permanent_failure')),
 idempotency_key text NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 128),
 request_digest text NOT NULL, pipeline_version text NOT NULL DEFAULT 'phase1-fixture-v1',
 created_at timestamptz NOT NULL DEFAULT now(), deadline timestamptz NOT NULL,
 cancel_requested_at timestamptz, cancellation_epoch bigint NOT NULL DEFAULT 0,
 error_code text, finished_at timestamptz,
 UNIQUE(owner_id,id), UNIQUE(owner_id,idempotency_key),
 FOREIGN KEY(owner_id,project_id) REFERENCES projects(owner_id,id),
 FOREIGN KEY(owner_id,snapshot_id) REFERENCES repository_snapshots(owner_id,id),
 FOREIGN KEY(owner_id,prior_job_id) REFERENCES generation_jobs(owner_id,id)
);
CREATE TABLE job_stages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL, ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 14),
 stage_key text NOT NULL, state text NOT NULL CHECK(state IN
 ('pending','ready','running','retry_wait','blocked','succeeded','failed','cancelled')),
 fence bigint NOT NULL DEFAULT 0, attempt_count integer NOT NULL DEFAULT 0,
 max_attempts integer NOT NULL, timeout_seconds integer NOT NULL,
 lease_expires_at timestamptz, stage_deadline timestamptz, next_attempt_at timestamptz,
 output_digest text, error_code text,
 UNIQUE(owner_id,id), UNIQUE(job_id,ordinal), UNIQUE(job_id,stage_key),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id)
);
CREATE UNIQUE INDEX one_active_stage ON job_stages(job_id)
 WHERE state IN ('ready','running','retry_wait','blocked');
CREATE TABLE job_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL, stage_id uuid NOT NULL, attempt_no integer NOT NULL, fence bigint NOT NULL,
 worker_id text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
 heartbeat_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
 outcome text NOT NULL DEFAULT 'running', error_code text,
 UNIQUE(owner_id,id), UNIQUE(stage_id,attempt_no),
 FOREIGN KEY(owner_id,stage_id) REFERENCES job_stages(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id)
);
CREATE TABLE job_history (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL, version integer NOT NULL, state text NOT NULL, error_code text,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(owner_id,id), UNIQUE(job_id,version),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id)
);
CREATE TABLE outbox_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid, stage_id uuid, event_type text NOT NULL CHECK(event_type IN ('stage','cleanup')),
 due_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
 UNIQUE(owner_id,id), FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id),
 FOREIGN KEY(owner_id,stage_id) REFERENCES job_stages(owner_id,id)
);
CREATE INDEX outbox_due ON outbox_events(due_at) WHERE published_at IS NULL;
CREATE TABLE rv.auth_rate_buckets (
 key_hash text PRIMARY KEY, minute timestamptz NOT NULL, count integer NOT NULL
);
GRANT SELECT,INSERT,UPDATE,DELETE ON rv.auth_rate_buckets TO rv_executor;
CREATE TABLE quota_accounts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL UNIQUE REFERENCES users(id),
 month_limit integer NOT NULL DEFAULT 10, queued_limit integer NOT NULL DEFAULT 10,
 active_limit integer NOT NULL DEFAULT 1, UNIQUE(owner_id,id)
);
CREATE TABLE quota_reservations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL UNIQUE, month date NOT NULL, status text NOT NULL DEFAULT 'reserved'
 CHECK(status IN ('reserved','settled')), budget_units integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), settled_at timestamptz, UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id)
);
CREATE TABLE usage_cost_records (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL, attempt_id uuid, operation_id text NOT NULL, event_type text NOT NULL,
 units numeric NOT NULL DEFAULT 0 CHECK(units>=0), measurements jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(owner_id,id), UNIQUE(owner_id,operation_id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id),
 FOREIGN KEY(owner_id,attempt_id) REFERENCES job_attempts(owner_id,id)
);
CREATE TABLE deletion_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 project_id uuid NOT NULL, state text NOT NULL DEFAULT 'pending', error_code text,
 requested_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(owner_id,id), UNIQUE(project_id),
 FOREIGN KEY(owner_id,project_id) REFERENCES projects(owner_id,id)
);
-- Future payloads remain unavailable through Phase 1 APIs; no integrations populate these tables.
CREATE TABLE knowledge_artifacts (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id), snapshot_id uuid NOT NULL,
 job_id uuid NOT NULL, stage_id uuid NOT NULL, kind text NOT NULL, schema_version text NOT NULL,
 object_key text NOT NULL UNIQUE, checksum text NOT NULL, synthetic boolean NOT NULL,
 published_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz,
 UNIQUE(owner_id,id), UNIQUE(stage_id),
 FOREIGN KEY(owner_id,snapshot_id) REFERENCES repository_snapshots(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id),
 FOREIGN KEY(owner_id,stage_id) REFERENCES job_stages(owner_id,id)
);
CREATE TABLE model_operations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 stage_id uuid NOT NULL, operation_key text NOT NULL, chunk_id text NOT NULL, plan_digest text NOT NULL,
 request_digest text NOT NULL, status text NOT NULL, release_metadata jsonb NOT NULL,
 result_metadata jsonb, UNIQUE(owner_id,id), UNIQUE(stage_id,operation_key),
 FOREIGN KEY(owner_id,stage_id) REFERENCES job_stages(owner_id,id)
);
CREATE TABLE stage_chunks (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 stage_id uuid NOT NULL, chunk_id text NOT NULL, plan_digest text NOT NULL,
 winning_operation_id uuid NOT NULL, checksum text NOT NULL, object_key text NOT NULL UNIQUE,
 UNIQUE(owner_id,id), UNIQUE(stage_id,plan_digest,chunk_id),
 FOREIGN KEY(owner_id,stage_id) REFERENCES job_stages(owner_id,id),
 FOREIGN KEY(owner_id,winning_operation_id) REFERENCES model_operations(owner_id,id)
);
ALTER TABLE model_operations ADD completed_chunk_id uuid,
 ADD FOREIGN KEY(owner_id,completed_chunk_id) REFERENCES stage_chunks(owner_id,id);
CREATE TABLE storyboards (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL, snapshot_id uuid NOT NULL, knowledge_artifact_id uuid NOT NULL,
 version text NOT NULL, digest text NOT NULL, UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id),
 FOREIGN KEY(owner_id,snapshot_id) REFERENCES repository_snapshots(owner_id,id),
 FOREIGN KEY(owner_id,knowledge_artifact_id) REFERENCES knowledge_artifacts(owner_id,id)
);
CREATE TABLE video_artifacts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL UNIQUE, storyboard_id uuid NOT NULL, metadata jsonb NOT NULL,
 expires_at timestamptz NOT NULL, deleted_at timestamptz, UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES generation_jobs(owner_id,id),
 FOREIGN KEY(owner_id,storyboard_id) REFERENCES storyboards(owner_id,id)
);
CREATE TABLE delivery_grants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 video_id uuid NOT NULL, session_id uuid NOT NULL, nonce_hash text NOT NULL UNIQUE,
 expires_at timestamptz NOT NULL, revoked_at timestamptz, reserved_bytes bigint NOT NULL DEFAULT 0,
 served_bytes bigint NOT NULL DEFAULT 0, UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,video_id) REFERENCES video_artifacts(owner_id,id),
 FOREIGN KEY(owner_id,session_id) REFERENCES auth_sessions(owner_id,id)
);

DO $$ DECLARE t text; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'alembic_version' LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant ON %I TO rv_app USING(owner_id=rv.owner()) WITH CHECK(owner_id=rv.owner())',t);
  EXECUTE format('CREATE POLICY internal ON %I TO rv_executor USING(true) WITH CHECK(true)',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON %I TO rv_executor',t);
 END LOOP;
END $$;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rv_app;
GRANT INSERT, UPDATE ON projects, auth_sessions TO rv_app;
GRANT INSERT ON repository_snapshots TO rv_app;
GRANT SELECT ON alembic_version TO rv_app,rv_worker;

CREATE FUNCTION rv.job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  INSERT INTO job_history(owner_id,job_id,version,state,error_code)
  VALUES(NEW.owner_id,NEW.id,NEW.version,NEW.state,NEW.error_code);
  RETURN NEW;
 END IF;
 IF OLD.state IN ('succeeded','failed','cancelled') AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'terminal_immutable';
 END IF;
 IF NEW.state<>OLD.state THEN
  IF NOT ((OLD.state='queued' AND NEW.state IN ('running','cancelled','failed')) OR
   (OLD.state='running' AND NEW.state IN ('retry_wait','awaiting_reconciliation','cancel_requested','failed','succeeded')) OR
   (OLD.state='retry_wait' AND NEW.state IN ('running','cancel_requested','failed')) OR
   (OLD.state='awaiting_reconciliation' AND NEW.state IN ('running','cancel_requested','failed')) OR
   (OLD.state='cancel_requested' AND NEW.state IN ('cancelled','failed'))) THEN
   RAISE EXCEPTION 'invalid_transition';
  END IF;
  NEW.version:=OLD.version+1;
  IF NEW.state='succeeded' AND NEW.synthetic THEN RAISE EXCEPTION 'phase1_boundary'; END IF;
  INSERT INTO job_history(owner_id,job_id,version,state,error_code)
  VALUES(NEW.owner_id,NEW.id,NEW.version,NEW.state,NEW.error_code);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER job_insert AFTER INSERT ON generation_jobs FOR EACH ROW EXECUTE FUNCTION rv.job_guard();
CREATE TRIGGER job_update BEFORE UPDATE ON generation_jobs FOR EACH ROW EXECUTE FUNCTION rv.job_guard();
CREATE FUNCTION rv.stage_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.state IN ('succeeded','failed','cancelled') AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'terminal_stage_immutable';
 END IF;
 IF NEW.state<>OLD.state AND NOT (
  (OLD.state='pending' AND NEW.state IN ('ready','failed','cancelled')) OR
  (OLD.state='ready' AND NEW.state IN ('running','failed','cancelled')) OR
  (OLD.state='running' AND NEW.state IN ('succeeded','retry_wait','blocked','failed','cancelled')) OR
  (OLD.state='retry_wait' AND NEW.state IN ('ready','failed','cancelled')) OR
  (OLD.state='blocked' AND NEW.state IN ('ready','failed','cancelled'))) THEN
   RAISE EXCEPTION 'invalid_stage_transition';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER stage_update BEFORE UPDATE ON job_stages FOR EACH ROW EXECUTE FUNCTION rv.stage_guard();

CREATE FUNCTION rv.dev_identity(subject text,client_hash text) RETURNS SETOF users LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE calls int;
BEGIN
 INSERT INTO rv.auth_rate_buckets(key_hash,minute,count) VALUES(client_hash,date_trunc('minute',now()),1)
 ON CONFLICT(key_hash) DO UPDATE SET minute=date_trunc('minute',now()),
 count=CASE WHEN auth_rate_buckets.minute=date_trunc('minute',now()) THEN auth_rate_buckets.count+1 ELSE 1 END
 RETURNING count INTO calls;
 IF calls>5 THEN RAISE EXCEPTION 'authentication_rate'; END IF;
 RETURN QUERY SELECT * FROM users WHERE issuer='repovox-dev-v1' AND auth_subject=subject AND status='active';
END
$$;

CREATE FUNCTION rv.settle(j generation_jobs) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
 UPDATE quota_reservations SET status='settled',settled_at=now() WHERE job_id=j.id AND status='reserved';
 INSERT INTO usage_cost_records(owner_id,job_id,operation_id,event_type,units)
 VALUES(j.owner_id,j.id,j.id::text||':settled','settled',1) ON CONFLICT(owner_id,operation_id) DO NOTHING;
END $$;
CREATE FUNCTION rv.end_job(jid uuid, target text, code text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE j generation_jobs;
BEGIN
 SELECT * INTO j FROM generation_jobs WHERE id=jid FOR UPDATE;
 IF j.state IN ('succeeded','failed','cancelled') THEN RETURN; END IF;
 UPDATE generation_jobs SET state=target,error_code=code,finished_at=now() WHERE id=jid;
 UPDATE job_stages SET state=CASE WHEN target='cancelled' THEN 'cancelled' ELSE 'failed' END,
 fence=fence+1,lease_expires_at=NULL,error_code=code
 WHERE job_id=jid AND state NOT IN ('succeeded','failed','cancelled');
 UPDATE job_attempts SET outcome=target,error_code=code,ended_at=now() WHERE job_id=jid AND outcome='running';
 PERFORM rv.settle(j);
END $$;

CREATE FUNCTION rv.admit(pid uuid, idem text, digest text, fixture_name text, prior uuid DEFAULT NULL)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE o uuid:=rv.owner(); existing generation_jobs; jid uuid:=gen_random_uuid(); sid uuid;
 keys text[]:=ARRAY['validate','acquire','filter','structure','entrypoints','infer','knowledge',
 'evidence','verify','storyboard','narration','tts','render','encode'];
 timeouts int[]:=ARRAY[10,120,30,120,30,90,30,30,90,360,360,240,600,180];
 q quota_accounts; i int; stageid uuid; total int;
BEGIN
 IF o IS NULL THEN RAISE EXCEPTION 'unauthorized'; END IF;
 -- Serialize global monthly reservations, then all owner admissions/claims/cancellations.
 PERFORM pg_advisory_xact_lock(712031);
 SELECT * INTO q FROM quota_accounts WHERE owner_id=o FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'unauthorized'; END IF;
 SELECT * INTO existing FROM generation_jobs WHERE owner_id=o AND idempotency_key=idem;
 IF FOUND THEN
  IF existing.request_digest<>digest THEN RAISE EXCEPTION 'idempotency_conflict'; END IF;
  RETURN existing.id;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM projects WHERE id=pid AND owner_id=o AND deleted_at IS NULL) THEN
  RAISE EXCEPTION 'not_found';
 END IF;
 IF prior IS NOT NULL AND NOT EXISTS(SELECT 1 FROM generation_jobs WHERE id=prior AND owner_id=o
  AND project_id=pid AND state IN ('failed','cancelled')) THEN RAISE EXCEPTION 'invalid_retry'; END IF;
 IF fixture_name NOT IN ('normal','transient_once','permanent_failure') THEN RAISE EXCEPTION 'invalid_fixture'; END IF;
 SELECT count(*) INTO total FROM quota_reservations WHERE month=date_trunc('month',now())::date;
 IF total>=100 OR (SELECT count(*) FROM quota_reservations WHERE owner_id=o
  AND month=date_trunc('month',now())::date)>=q.month_limit THEN RAISE EXCEPTION 'monthly_quota'; END IF;
 IF (SELECT count(*) FROM generation_jobs WHERE owner_id=o AND state='queued')>=q.queued_limit THEN
  RAISE EXCEPTION 'queue_quota'; END IF;
 IF (SELECT count(*) FROM generation_jobs WHERE owner_id=o AND created_at>now()-interval '1 minute')>=2 THEN
  RAISE EXCEPTION 'admission_rate'; END IF;
 INSERT INTO repository_snapshots(owner_id,project_id,commit_sha,synthetic,acquisition_version,pipeline_version)
 VALUES(o,pid,repeat('a',40),true,'trusted-fixture-v1','phase1-fixture-v1')
 ON CONFLICT(owner_id,project_id,commit_sha,acquisition_version) DO NOTHING;
 SELECT id INTO sid FROM repository_snapshots WHERE owner_id=o AND project_id=pid
 AND acquisition_version='trusted-fixture-v1';
 INSERT INTO generation_jobs(id,owner_id,project_id,snapshot_id,state,fixture,idempotency_key,
 request_digest,deadline,prior_job_id) VALUES(jid,o,pid,sid,'queued',fixture_name,idem,digest,now()+interval '45 minutes',prior);
 FOR i IN 1..14 LOOP
  INSERT INTO job_stages(owner_id,job_id,ordinal,stage_key,state,max_attempts,timeout_seconds)
  VALUES(o,jid,i,keys[i],CASE i WHEN 1 THEN 'succeeded' WHEN 2 THEN 'ready' ELSE 'pending' END,
  CASE i WHEN 1 THEN 1 WHEN 2 THEN 3 ELSE 2 END,timeouts[i]) RETURNING id INTO stageid;
  IF i=2 THEN INSERT INTO outbox_events(owner_id,job_id,stage_id,event_type) VALUES(o,jid,stageid,'stage'); END IF;
 END LOOP;
 INSERT INTO quota_reservations(owner_id,job_id,month) VALUES(o,jid,date_trunc('month',now())::date);
 INSERT INTO usage_cost_records(owner_id,job_id,operation_id,event_type,units)
 VALUES(o,jid,jid::text||':reserved','reserved',1);
 RETURN jid;
END $$;

CREATE FUNCTION rv.cancel(jid uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE j generation_jobs;
BEGIN
 PERFORM 1 FROM quota_accounts WHERE owner_id=rv.owner() FOR UPDATE;
 SELECT * INTO j FROM generation_jobs WHERE id=jid AND owner_id=rv.owner() FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM projects WHERE id=j.project_id AND deleted_at IS NULL) THEN
  RAISE EXCEPTION 'not_found'; END IF;
 IF j.state IN ('succeeded','failed','cancelled') THEN RAISE EXCEPTION 'terminal_conflict'; END IF;
 IF j.state='queued' THEN PERFORM rv.end_job(jid,'cancelled','owner_cancelled'); ELSE
  UPDATE generation_jobs SET state='cancel_requested',cancel_requested_at=now(),
  cancellation_epoch=cancellation_epoch+1 WHERE id=jid;
  -- Trusted fixture work has no subprocess or inference to terminate; revoke synchronously.
  PERFORM rv.end_job(jid,'cancelled','owner_cancelled');
 END IF;
END $$;

CREATE FUNCTION rv.delete_project(pid uuid) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE did uuid; j generation_jobs;
BEGIN
 PERFORM 1 FROM quota_accounts WHERE owner_id=rv.owner() FOR UPDATE;
 PERFORM 1 FROM projects WHERE id=pid AND owner_id=rv.owner() AND deleted_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'not_found'; END IF;
 UPDATE projects SET status='deleting',deleted_at=now() WHERE id=pid;
 FOR j IN SELECT * FROM generation_jobs WHERE project_id=pid AND owner_id=rv.owner()
 AND state NOT IN ('succeeded','failed','cancelled') FOR UPDATE LOOP
  IF j.state<>'queued' THEN UPDATE generation_jobs SET state='cancel_requested',
   cancel_requested_at=now(),cancellation_epoch=cancellation_epoch+1 WHERE id=j.id; END IF;
  PERFORM rv.end_job(j.id,'cancelled','project_deleted');
 END LOOP;
 INSERT INTO deletion_requests(owner_id,project_id) VALUES(rv.owner(),pid) RETURNING id INTO did;
 INSERT INTO outbox_events(id,owner_id,event_type) VALUES(did,rv.owner(),'cleanup');
 RETURN did;
END $$;

CREATE FUNCTION rv.claim(sid uuid, worker text) RETURNS TABLE(owner_id uuid,job_id uuid,
 snapshot_id uuid,stage_id uuid,fence bigint,attempt_no int,fixture text,ordinal int)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; q quota_accounts;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT * INTO q FROM quota_accounts WHERE quota_accounts.owner_id=s.owner_id FOR UPDATE;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF j.state NOT IN ('queued','running','retry_wait') OR j.deadline<=clock_timestamp()
 OR s.state<>'ready' OR s.attempt_count>=s.max_attempts
 OR NOT EXISTS(SELECT 1 FROM projects WHERE id=j.project_id AND deleted_at IS NULL)
 OR NOT EXISTS(SELECT 1 FROM quota_reservations WHERE quota_reservations.job_id=j.id AND status='reserved') THEN RETURN; END IF;
 IF j.state='queued' AND (SELECT count(*) FROM generation_jobs WHERE generation_jobs.owner_id=j.owner_id
 AND state IN ('running','retry_wait','awaiting_reconciliation','cancel_requested'))>=q.active_limit THEN RETURN; END IF;
 IF j.state IN ('queued','retry_wait') THEN UPDATE generation_jobs SET state='running' WHERE id=j.id; END IF;
 UPDATE job_stages SET state='running',fence=job_stages.fence+1,attempt_count=attempt_count+1,
 stage_deadline=least(j.deadline,clock_timestamp()+s.timeout_seconds*interval '1 second'),
 lease_expires_at=least(j.deadline,clock_timestamp()+interval '60 seconds') WHERE id=sid RETURNING * INTO s;
 INSERT INTO job_attempts(owner_id,job_id,stage_id,attempt_no,fence,worker_id)
 VALUES(j.owner_id,j.id,s.id,s.attempt_count,s.fence,left(worker,100));
 RETURN QUERY SELECT j.owner_id,j.id,j.snapshot_id,s.id,s.fence,s.attempt_count,j.fixture,s.ordinal;
END $$;

CREATE FUNCTION rv.valid_lease(s job_stages,j generation_jobs,epoch bigint) RETURNS boolean
 LANGUAGE sql AS $$ SELECT s.state='running' AND s.fence=epoch
 AND s.lease_expires_at>clock_timestamp() AND s.stage_deadline>clock_timestamp()
 AND j.deadline>clock_timestamp() AND j.state='running'
 AND EXISTS(SELECT 1 FROM projects WHERE id=j.project_id AND deleted_at IS NULL) $$;

CREATE FUNCTION rv.heartbeat(sid uuid,epoch bigint) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) THEN RETURN false; END IF;
 UPDATE job_stages SET lease_expires_at=least(clock_timestamp()+interval '60 seconds',stage_deadline,j.deadline) WHERE id=sid;
 UPDATE job_attempts SET heartbeat_at=now() WHERE stage_id=sid AND fence=epoch;
 RETURN true;
END $$;

CREATE FUNCTION rv.finish(sid uuid,epoch bigint,artifact uuid,checksum text,object_path text)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; expected text;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) THEN RETURN false; END IF;
 IF s.ordinal<>2 THEN RAISE EXCEPTION 'phase1_boundary'; END IF;
 expected:='development/'||j.owner_id||'/'||j.snapshot_id||'/'||j.id||'/fixture/'||artifact||'/'||checksum;
 IF object_path<>expected OR checksum !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'invalid_artifact'; END IF;
 INSERT INTO knowledge_artifacts(id,owner_id,snapshot_id,job_id,stage_id,kind,schema_version,object_key,checksum,synthetic)
 VALUES(artifact,j.owner_id,j.snapshot_id,j.id,s.id,'fixture','phase1-fixture-v1',object_path,checksum,true);
 UPDATE job_stages SET state='succeeded',output_digest=checksum,lease_expires_at=NULL WHERE id=sid;
 UPDATE job_attempts SET outcome='succeeded',ended_at=now() WHERE stage_id=sid AND fence=epoch;
 UPDATE job_stages SET state='ready' WHERE job_id=j.id AND ordinal=3;
 INSERT INTO outbox_events(owner_id,job_id,stage_id,event_type)
 SELECT j.owner_id,j.id,id,'stage' FROM job_stages WHERE job_id=j.id AND ordinal=3;
 RETURN true;
END $$;

CREATE FUNCTION rv.fail(sid uuid,epoch bigint,transient boolean) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; due timestamptz; code text;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) THEN RETURN false; END IF;
 IF s.ordinal=3 THEN code:='phase1_fixture_boundary'; ELSE code:='fixture_failure'; END IF;
 IF transient AND s.attempt_count<s.max_attempts AND j.deadline>clock_timestamp()+interval '10 seconds' THEN
  due:=clock_timestamp()+least(120,5*power(2,s.attempt_count-1))*interval '1 second'+random()*interval '5 seconds';
  UPDATE job_attempts SET outcome='retry_wait',error_code='fixture_transient',ended_at=now() WHERE stage_id=sid AND fence=epoch;
  UPDATE job_stages SET state='retry_wait',fence=fence+1,lease_expires_at=NULL,next_attempt_at=due,error_code='fixture_transient' WHERE id=sid;
  UPDATE generation_jobs SET state='retry_wait' WHERE id=j.id;
 ELSE PERFORM rv.end_job(j.id,'failed',code); END IF;
 RETURN true;
END $$;

CREATE FUNCTION rv.reconcile() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; n int:=0;
BEGIN
 FOR j IN SELECT * FROM generation_jobs WHERE state NOT IN ('failed','cancelled','succeeded') ORDER BY created_at LOOP
  PERFORM 1 FROM quota_accounts WHERE owner_id=j.owner_id FOR UPDATE;
  SELECT * INTO j FROM generation_jobs WHERE id=j.id FOR UPDATE;
  IF j.state IN ('failed','cancelled','succeeded') THEN CONTINUE; END IF;
  IF j.deadline<=clock_timestamp() THEN PERFORM rv.end_job(j.id,'failed','job_deadline'); CONTINUE; END IF;
  FOR s IN SELECT * FROM job_stages WHERE job_id=j.id AND state IN ('running','retry_wait','ready') FOR UPDATE LOOP
   IF s.state='running' AND (s.lease_expires_at<=clock_timestamp() OR s.stage_deadline<=clock_timestamp()) THEN
    IF s.attempt_count>=s.max_attempts THEN PERFORM rv.end_job(j.id,'failed','attempt_limit'); CONTINUE; END IF;
    UPDATE job_attempts SET outcome='lease_expired',ended_at=now(),error_code='lease_expired' WHERE stage_id=s.id AND outcome='running';
    UPDATE job_stages SET state='retry_wait',fence=fence+1,lease_expires_at=NULL,
     next_attempt_at=clock_timestamp()+least(120,5*power(2,s.attempt_count-1))*interval '1 second',error_code='lease_expired' WHERE id=s.id;
    UPDATE generation_jobs SET state='retry_wait' WHERE id=j.id;
   ELSIF s.state='retry_wait' AND s.next_attempt_at<=clock_timestamp() THEN
    UPDATE job_stages SET state='ready' WHERE id=s.id;
   END IF;
   IF EXISTS(SELECT 1 FROM job_stages WHERE id=s.id AND state='ready') THEN
    IF NOT EXISTS(SELECT 1 FROM outbox_events WHERE stage_id=s.id AND published_at IS NULL) AND
     NOT EXISTS(SELECT 1 FROM outbox_events WHERE stage_id=s.id AND published_at>clock_timestamp()-interval '30 seconds') THEN
     INSERT INTO outbox_events(owner_id,job_id,stage_id,event_type) VALUES(s.owner_id,s.job_id,s.id,'stage'); n:=n+1;
    END IF;
   END IF;
  END LOOP;
 END LOOP;
 -- Reissue cleanup after lost published notification, independently of terminal jobs.
 INSERT INTO outbox_events(owner_id,event_type,id)
 SELECT owner_id,'cleanup',id FROM deletion_requests d WHERE state='pending'
 AND NOT EXISTS(SELECT 1 FROM outbox_events e WHERE e.id=d.id AND
 (published_at IS NULL OR published_at>clock_timestamp()-interval '30 seconds'))
 ON CONFLICT(id) DO UPDATE SET published_at=NULL,due_at=now();
 DELETE FROM auth_sessions WHERE expires_at<now()-interval '24 hours' OR revoked_at<now()-interval '24 hours';
 RETURN n;
END $$;

CREATE FUNCTION rv.dispatch_batch() RETURNS TABLE(event_id uuid,stage_id uuid,event_type text)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT id,stage_id,event_type FROM outbox_events WHERE published_at IS NULL AND due_at<=now()
 ORDER BY due_at LIMIT 100 $$;
CREATE FUNCTION rv.published(eid uuid) RETURNS void LANGUAGE sql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$ UPDATE outbox_events SET published_at=now() WHERE id=eid $$;
CREATE FUNCTION rv.cleanup_scope(did uuid) RETURNS TABLE(owner_id uuid,project_id uuid,snapshot_id uuid,job_id uuid)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT d.owner_id,d.project_id,j.snapshot_id,j.id FROM deletion_requests d
 LEFT JOIN generation_jobs j ON j.project_id=d.project_id
 WHERE d.id=did AND d.state='pending' $$;
CREATE FUNCTION rv.cleanup_done(did uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
BEGIN
 UPDATE projects SET status='deleted' WHERE id IN(SELECT project_id FROM deletion_requests WHERE id=did);
 UPDATE deletion_requests SET state='completed',completed_at=now() WHERE id=did;
END $$;

-- Procedures execute as a no-login role with explicit internal RLS policy; no login bypasses RLS.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT oid::regprocedure AS signature FROM pg_proc WHERE pronamespace='rv'::regnamespace LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO rv_executor',f.signature);
 END LOOP;
END $$;
-- NOINHERIT migrator can transfer ownership, but must SET ROLE to revoke as the new owner.
SET LOCAL ROLE rv_executor;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA rv FROM PUBLIC,rv_app,rv_worker;
GRANT EXECUTE ON FUNCTION rv.owner() TO rv_app;
GRANT EXECUTE ON FUNCTION rv.dev_identity(text,text),rv.admit(uuid,text,text,text,uuid),rv.cancel(uuid),rv.delete_project(uuid) TO rv_app;
GRANT EXECUTE ON FUNCTION rv.claim(uuid,text),rv.heartbeat(uuid,bigint),rv.finish(uuid,bigint,uuid,text,text),
 rv.fail(uuid,bigint,boolean),rv.reconcile(),rv.dispatch_batch(),rv.published(uuid),
 rv.cleanup_scope(uuid),rv.cleanup_done(uuid) TO rv_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA rv FROM rv_executor;
SET LOCAL ROLE rv_executor;
INSERT INTO users(id,owner_id,issuer,auth_subject,display_name,email) VALUES
 ('11111111-1111-4111-8111-111111111111','11111111-1111-4111-8111-111111111111','repovox-dev-v1','alex','Alex Chen','alex@example.test'),
 ('22222222-2222-4222-8222-222222222222','22222222-2222-4222-8222-222222222222','repovox-dev-v1','sam','Sam Rivera','sam@example.test');
INSERT INTO quota_accounts(owner_id) SELECT id FROM users;
RESET ROLE;
