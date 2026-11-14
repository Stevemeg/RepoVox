-- Media database, revision m001. A separate database with its own roles and version table.
-- Nothing here exists in, reads from or writes to the core/pilot database, and there is no
-- cross-database transaction: analysis outputs are referenced by immutable object identity.
CREATE SCHEMA mv;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public, mv TO rvm_app, rvm_worker, rvm_executor;
GRANT CREATE ON SCHEMA mv TO rvm_executor;

CREATE FUNCTION mv.owner() RETURNS uuid LANGUAGE sql STABLE AS $$
 SELECT nullif(current_setting('repovox.owner_id', true), '')::uuid
$$;

CREATE TABLE media_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL, project_id uuid NOT NULL,
 analysis_job_id uuid NOT NULL,
 idempotency_key text NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 128),
 request_digest text NOT NULL CHECK(request_digest ~ '^[a-f0-9]{64}$'),
 state text NOT NULL CHECK(state IN ('awaiting_analysis','queued','running','retry_wait',
 'cancelled','failed','succeeded')),
 version integer NOT NULL DEFAULT 1, analysis jsonb, repository text,
 commit_sha text CHECK(commit_sha ~ '^[a-f0-9]{40}$'),
 architecture text CHECK(architecture IN ('supported','unsupported','failed')),
 error_code text, created_at timestamptz NOT NULL DEFAULT now(), deadline timestamptz NOT NULL,
 finished_at timestamptz, UNIQUE(owner_id,idempotency_key), UNIQUE(owner_id,id)
);
CREATE TABLE media_stages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL, job_id uuid NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal BETWEEN 10 AND 15), stage_key text NOT NULL,
 state text NOT NULL CHECK(state IN ('pending','ready','running','retry_wait','succeeded','failed','cancelled')),
 fence bigint NOT NULL DEFAULT 0, attempt_count integer NOT NULL DEFAULT 0,
 max_attempts integer NOT NULL, timeout_seconds integer NOT NULL,
 lease_expires_at timestamptz, stage_deadline timestamptz, next_attempt_at timestamptz,
 output_digest text, error_code text,
 UNIQUE(job_id,ordinal), UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,job_id) REFERENCES media_jobs(owner_id,id)
);
CREATE UNIQUE INDEX media_one_active_stage ON media_stages(job_id)
 WHERE state IN ('ready','running','retry_wait');
CREATE TABLE media_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL, job_id uuid NOT NULL,
 stage_id uuid NOT NULL, attempt_no integer NOT NULL, fence bigint NOT NULL, worker_id text NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
 outcome text NOT NULL DEFAULT 'running', error_code text, UNIQUE(stage_id,attempt_no),
 FOREIGN KEY(owner_id,stage_id) REFERENCES media_stages(owner_id,id)
);
CREATE TABLE media_history (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL, job_id uuid NOT NULL,
 version integer NOT NULL, state text NOT NULL, error_code text,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(job_id,version),
 FOREIGN KEY(owner_id,job_id) REFERENCES media_jobs(owner_id,id)
);
CREATE TABLE media_artifacts (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL, job_id uuid NOT NULL, stage_id uuid NOT NULL UNIQUE,
 ordinal integer NOT NULL, kind text NOT NULL, object_key text NOT NULL UNIQUE,
 checksum text NOT NULL CHECK(checksum ~ '^[a-f0-9]{64}$'), byte_count bigint NOT NULL CHECK(byte_count>0),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(owner_id,job_id) REFERENCES media_jobs(owner_id,id)
);
CREATE TABLE media_videos (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL, job_id uuid NOT NULL,
 category text NOT NULL CHECK(category IN ('walkthrough','architecture')),
 position integer NOT NULL CHECK(position BETWEEN 0 AND 3), title text NOT NULL,
 object_key text NOT NULL UNIQUE, checksum text NOT NULL CHECK(checksum ~ '^[a-f0-9]{64}$'),
 byte_count bigint NOT NULL CHECK(byte_count>0), captions text NOT NULL, metadata jsonb NOT NULL,
 published_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, deleted_at timestamptz,
 UNIQUE(job_id,category,position),
 FOREIGN KEY(owner_id,job_id) REFERENCES media_jobs(owner_id,id)
);

DO $$ DECLARE t text; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'media_%' LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant ON %I FOR SELECT TO rvm_app USING(owner_id=mv.owner())',t);
  EXECUTE format('CREATE POLICY internal ON %I TO rvm_executor USING(true) WITH CHECK(true)',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON %I TO rvm_executor',t);
  EXECUTE format('GRANT SELECT ON %I TO rvm_app',t);
 END LOOP;
END $$;
GRANT SELECT ON alembic_version TO rvm_app,rvm_worker;

CREATE FUNCTION mv.job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'awaiting_analysis' THEN RAISE EXCEPTION 'invalid_transition'; END IF;
  INSERT INTO media_history(owner_id,job_id,version,state,error_code)
  VALUES(NEW.owner_id,NEW.id,NEW.version,NEW.state,NEW.error_code);
  RETURN NEW;
 END IF;
 IF OLD.state IN ('succeeded','failed','cancelled') AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'terminal_immutable';
 END IF;
 IF OLD.analysis IS NOT NULL AND NEW.analysis IS DISTINCT FROM OLD.analysis THEN
  RAISE EXCEPTION 'analysis_reference_immutable';
 END IF;
 IF NEW.state<>OLD.state THEN
  IF NOT ((OLD.state='awaiting_analysis' AND NEW.state IN ('queued','cancelled','failed')) OR
   (OLD.state='queued' AND NEW.state IN ('running','cancelled','failed')) OR
   (OLD.state='running' AND NEW.state IN ('retry_wait','cancelled','failed','succeeded')) OR
   (OLD.state='retry_wait' AND NEW.state IN ('running','cancelled','failed'))) THEN
   RAISE EXCEPTION 'invalid_transition';
  END IF;
  NEW.version:=OLD.version+1;
  -- Success means the walkthrough was encoded, validated and published. Nothing less.
  IF NEW.state='succeeded' AND NOT (
   (SELECT count(*) FROM media_stages WHERE job_id=NEW.id AND ordinal<=14 AND state='succeeded')=5
   AND EXISTS(SELECT 1 FROM media_videos WHERE job_id=NEW.id AND category='walkthrough')
   AND NEW.architecture IS NOT NULL) THEN RAISE EXCEPTION 'video_not_published'; END IF;
  INSERT INTO media_history(owner_id,job_id,version,state,error_code)
  VALUES(NEW.owner_id,NEW.id,NEW.version,NEW.state,NEW.error_code);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER media_job_insert AFTER INSERT ON media_jobs FOR EACH ROW EXECUTE FUNCTION mv.job_guard();
CREATE TRIGGER media_job_update BEFORE UPDATE ON media_jobs FOR EACH ROW EXECUTE FUNCTION mv.job_guard();

CREATE FUNCTION mv.stage_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.state IN ('succeeded','failed','cancelled') AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'terminal_stage_immutable';
 END IF;
 IF NEW.state<>OLD.state AND NOT (
  (OLD.state='pending' AND NEW.state IN ('ready','failed','cancelled')) OR
  (OLD.state='ready' AND NEW.state IN ('running','failed','cancelled')) OR
  (OLD.state='running' AND NEW.state IN ('succeeded','retry_wait','failed','cancelled')) OR
  (OLD.state='retry_wait' AND NEW.state IN ('ready','failed','cancelled'))) THEN
   RAISE EXCEPTION 'invalid_stage_transition';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER media_stage_update BEFORE UPDATE ON media_stages FOR EACH ROW EXECUTE FUNCTION mv.stage_guard();

-- Published records are immutable. Expiry may set deleted_at once; nothing else changes.
CREATE FUNCTION mv.published_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'published_immutable'; END IF;
 -- Field access goes through jsonb so one function serves tables with different columns.
 IF TG_TABLE_NAME='media_videos' AND (to_jsonb(OLD)->>'deleted_at') IS NULL
  AND (to_jsonb(NEW)->>'deleted_at') IS NOT NULL
  AND (to_jsonb(NEW)-'deleted_at')=(to_jsonb(OLD)-'deleted_at') THEN RETURN NEW; END IF;
 IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'published_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER media_video_guard BEFORE UPDATE OR DELETE ON media_videos FOR EACH ROW EXECUTE FUNCTION mv.published_guard();
CREATE TRIGGER media_artifact_guard BEFORE UPDATE OR DELETE ON media_artifacts FOR EACH ROW EXECUTE FUNCTION mv.published_guard();
CREATE TRIGGER media_history_guard BEFORE UPDATE OR DELETE ON media_history FOR EACH ROW EXECUTE FUNCTION mv.published_guard();

CREATE FUNCTION mv.valid_object(o jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(o->>'artifact' ~ '^[a-f0-9-]{36}$' AND o->>'checksum' ~ '^[a-f0-9]{64}$'
  AND (o->>'bytes') ~ '^[0-9]{1,12}$' AND (o->>'bytes')::bigint>0, false)
$$;

CREATE FUNCTION mv.end_job(p_job uuid, p_target text, p_code text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE j media_jobs;
BEGIN
 SELECT * INTO j FROM media_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.state IN ('succeeded','failed','cancelled') THEN RETURN; END IF;
 UPDATE media_jobs SET state=p_target,error_code=p_code,finished_at=clock_timestamp() WHERE id=p_job;
 UPDATE media_stages SET state=CASE WHEN p_target='cancelled' THEN 'cancelled' ELSE 'failed' END,
  fence=fence+1,lease_expires_at=NULL,error_code=coalesce(error_code,p_code)
  WHERE job_id=p_job AND state NOT IN ('succeeded','failed','cancelled');
 UPDATE media_attempts SET outcome=p_target,error_code=p_code,ended_at=clock_timestamp()
  WHERE job_id=p_job AND outcome='running';
END $$;

-- Admission: owner-scoped, idempotent, quota-bounded. The analysis job id is an opaque
-- reference into another database; it is not trusted until attach() supplies its outputs.
CREATE FUNCTION mv.admit(p_project uuid, p_analysis uuid, p_key text, p_digest text) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE o uuid:=mv.owner(); existing media_jobs; jid uuid:=gen_random_uuid(); i integer;
 keys text[]:=ARRAY['storyboard','narration','tts','render','encode','architecture'];
 timeouts integer[]:=ARRAY[360,360,240,600,180,600];
BEGIN
 IF o IS NULL THEN RAISE EXCEPTION 'unauthorized'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text, 71203));
 SELECT * INTO existing FROM media_jobs WHERE owner_id=o AND idempotency_key=p_key;
 IF FOUND THEN
  IF existing.request_digest<>p_digest THEN RAISE EXCEPTION 'idempotency_conflict'; END IF;
  RETURN existing.id;
 END IF;
 IF p_key !~ '^[!-~]{1,128}$' OR p_digest !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'invalid_request'; END IF;
 IF (SELECT count(*) FROM media_jobs WHERE owner_id=o AND state NOT IN ('succeeded','failed','cancelled'))>=2 THEN
  RAISE EXCEPTION 'queue_quota'; END IF;
 IF (SELECT count(*) FROM media_jobs WHERE owner_id=o AND created_at>now()-interval '30 days')>=20 THEN
  RAISE EXCEPTION 'monthly_quota'; END IF;
 INSERT INTO media_jobs(id,owner_id,project_id,analysis_job_id,idempotency_key,request_digest,state,deadline)
 VALUES(jid,o,p_project,p_analysis,p_key,p_digest,'awaiting_analysis',now()+interval '45 minutes');
 FOR i IN 1..6 LOOP
  INSERT INTO media_stages(owner_id,job_id,ordinal,stage_key,state,max_attempts,timeout_seconds)
  VALUES(o,jid,9+i,keys[i],'pending',2,timeouts[i]);
 END LOOP;
 RETURN jid;
END $$;

-- Attach the immutable analysis reference once. A repeated identical attach is a no-op;
-- a different reference for the same job is refused.
CREATE FUNCTION mv.attach(p_job uuid, p_reference jsonb) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE j media_jobs;
BEGIN
 SELECT * INTO j FROM media_jobs WHERE id=p_job AND owner_id=mv.owner() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'not_found'; END IF;
 IF j.analysis IS NOT NULL THEN
  IF j.analysis<>p_reference THEN RAISE EXCEPTION 'analysis_reference_conflict'; END IF;
  RETURN false;
 END IF;
 IF j.state<>'awaiting_analysis' THEN RETURN false; END IF;
 IF NOT coalesce(p_reference->>'analysis_job_id'=j.analysis_job_id::text
  AND p_reference->>'owner_id'=j.owner_id::text
  AND p_reference->>'commit_sha' ~ '^[a-f0-9]{40}$'
  AND p_reference->>'snapshot_id' ~ '^[a-f0-9-]{36}$'
  AND length(p_reference->>'repository') BETWEEN 3 AND 200
  AND mv.valid_object(p_reference->'verify') AND mv.valid_object(p_reference->'archive'), false) THEN
  RAISE EXCEPTION 'invalid_analysis_reference'; END IF;
 UPDATE media_jobs SET analysis=p_reference,repository=p_reference->>'repository',
  commit_sha=p_reference->>'commit_sha',state='queued' WHERE id=p_job;
 UPDATE media_stages SET state='ready' WHERE job_id=p_job AND ordinal=10;
 RETURN true;
END $$;

CREATE FUNCTION mv.analysis_failed(p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE j media_jobs;
BEGIN
 SELECT * INTO j FROM media_jobs WHERE id=p_job AND owner_id=mv.owner() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'not_found'; END IF;
 IF j.state='awaiting_analysis' THEN PERFORM mv.end_job(p_job,'failed','analysis_failed'); END IF;
END $$;

CREATE FUNCTION mv.cancel(p_job uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE j media_jobs;
BEGIN
 SELECT * INTO j FROM media_jobs WHERE id=p_job AND owner_id=mv.owner() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'not_found'; END IF;
 IF j.state IN ('succeeded','failed','cancelled') THEN RAISE EXCEPTION 'terminal_conflict'; END IF;
 PERFORM mv.end_job(p_job,'cancelled','owner_cancelled');
END $$;

CREATE FUNCTION mv.valid_lease(s media_stages, j media_jobs, p_fence bigint) RETURNS boolean
 LANGUAGE sql AS $$ SELECT s.state='running' AND s.fence=p_fence
 AND s.lease_expires_at>clock_timestamp() AND s.stage_deadline>clock_timestamp()
 AND j.deadline>clock_timestamp() AND j.state='running' $$;

-- Claim one ready stage. Lock order is always job, then stage.
CREATE FUNCTION mv.claim(p_worker text) RETURNS TABLE(o_job uuid,o_owner uuid,o_stage uuid,
 o_ordinal integer,o_fence bigint,o_attempt integer)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE sid uuid; jid uuid; s media_stages; j media_jobs;
BEGIN
 SELECT st.id,st.job_id INTO sid,jid FROM media_stages st JOIN media_jobs jb ON jb.id=st.job_id
  WHERE st.state='ready' AND jb.state IN ('queued','running','retry_wait')
  AND jb.deadline>clock_timestamp() ORDER BY jb.created_at,st.ordinal LIMIT 1;
 IF sid IS NULL THEN RETURN; END IF;
 SELECT * INTO j FROM media_jobs WHERE id=jid FOR UPDATE;
 SELECT * INTO s FROM media_stages WHERE id=sid FOR UPDATE;
 IF s.state<>'ready' OR j.state NOT IN ('queued','running','retry_wait')
  OR j.deadline<=clock_timestamp() OR s.attempt_count>=s.max_attempts THEN RETURN; END IF;
 IF j.state<>'running' THEN UPDATE media_jobs SET state='running' WHERE id=j.id; END IF;
 UPDATE media_stages SET state='running',fence=fence+1,attempt_count=attempt_count+1,
  next_attempt_at=NULL,error_code=NULL,
  stage_deadline=least(j.deadline,clock_timestamp()+s.timeout_seconds*interval '1 second'),
  lease_expires_at=least(j.deadline,clock_timestamp()+interval '60 seconds')
  WHERE id=sid RETURNING * INTO s;
 INSERT INTO media_attempts(owner_id,job_id,stage_id,attempt_no,fence,worker_id)
 VALUES(j.owner_id,j.id,s.id,s.attempt_count,s.fence,left(p_worker,100));
 RETURN QUERY SELECT j.id,j.owner_id,s.id,s.ordinal,s.fence,s.attempt_count;
END $$;

CREATE FUNCTION mv.scope(p_stage uuid, p_fence bigint) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE s media_stages; j media_jobs; outputs jsonb;
BEGIN
 SELECT * INTO s FROM media_stages WHERE id=p_stage;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO j FROM media_jobs WHERE id=s.job_id;
 IF NOT mv.valid_lease(s,j,p_fence) THEN RETURN NULL; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('ordinal',a.ordinal,'id',a.id,'checksum',a.checksum,
  'key',a.object_key,'bytes',a.byte_count) ORDER BY a.ordinal),'[]'::jsonb) INTO outputs
  FROM media_artifacts a WHERE a.job_id=j.id AND a.ordinal<s.ordinal;
 RETURN jsonb_build_object('job_id',j.id,'owner_id',j.owner_id,'ordinal',s.ordinal,
  'analysis',j.analysis,'outputs',outputs);
END $$;

CREATE FUNCTION mv.heartbeat(p_stage uuid, p_fence bigint) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE s media_stages; j media_jobs;
BEGIN
 SELECT * INTO s FROM media_stages WHERE id=p_stage;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO j FROM media_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM media_stages WHERE id=p_stage FOR UPDATE;
 IF NOT mv.valid_lease(s,j,p_fence) THEN RETURN false; END IF;
 UPDATE media_stages SET lease_expires_at=least(clock_timestamp()+interval '60 seconds',
  s.stage_deadline,j.deadline) WHERE id=p_stage;
 RETURN true;
END $$;

-- One transaction publishes a stage output and advances exactly one stage. Object keys are
-- recomputed here; a caller cannot point a record at another tenant's or job's object.
CREATE FUNCTION mv.finish(p_stage uuid, p_fence bigint, p_artifact uuid, p_checksum text,
 p_key text, p_bytes bigint, p_summary jsonb) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE s media_stages; j media_jobs; prefix text; v jsonb; n integer:=0; arch text;
BEGIN
 SELECT * INTO s FROM media_stages WHERE id=p_stage;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO j FROM media_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM media_stages WHERE id=p_stage FOR UPDATE;
 IF NOT mv.valid_lease(s,j,p_fence) THEN RETURN false; END IF;
 prefix:='media/'||j.owner_id||'/'||j.id||'/'||s.ordinal||'/';
 IF p_key<>prefix||p_artifact||'/'||p_checksum OR p_checksum !~ '^[a-f0-9]{64}$'
  OR p_bytes<=0 OR p_bytes>104857600 THEN RAISE EXCEPTION 'invalid_artifact'; END IF;
 INSERT INTO media_artifacts(id,owner_id,job_id,stage_id,ordinal,kind,object_key,checksum,byte_count)
 VALUES(p_artifact,j.owner_id,j.id,s.id,s.ordinal,s.stage_key,p_key,p_checksum,p_bytes);
 UPDATE media_stages SET state='succeeded',output_digest=p_checksum,lease_expires_at=NULL WHERE id=p_stage;
 UPDATE media_attempts SET outcome='succeeded',ended_at=clock_timestamp()
  WHERE stage_id=p_stage AND fence=p_fence;
 IF s.ordinal=14 THEN
  IF NOT coalesce(jsonb_typeof(p_summary->'video')='object'
   AND (p_summary->'video'->>'video_frames')::bigint>0
   AND p_summary->'video'->>'full_decode'='passed'
   AND length(p_summary->'video'->>'captions')>0, false) THEN RAISE EXCEPTION 'invalid_summary'; END IF;
  INSERT INTO media_videos(id,owner_id,job_id,category,position,title,object_key,checksum,byte_count,
   captions,metadata,expires_at)
  VALUES(p_artifact,j.owner_id,j.id,'walkthrough',0,'Repository walkthrough',p_key,p_checksum,p_bytes,
   p_summary->'video'->>'captions',(p_summary->'video')-'captions',j.created_at+interval '24 hours');
 END IF;
 IF s.ordinal=15 THEN
  arch:=p_summary->>'architecture';
  IF arch IS NULL OR arch NOT IN ('supported','unsupported')
   OR jsonb_typeof(coalesce(p_summary->'videos','[]'::jsonb))<>'array' THEN RAISE EXCEPTION 'invalid_summary'; END IF;
  FOR v IN SELECT * FROM jsonb_array_elements(coalesce(p_summary->'videos','[]'::jsonb)) LOOP
   n:=n+1;
   IF n>3 OR NOT coalesce(mv.valid_object(v)
    AND v->>'key'=prefix||(v->>'artifact')||'/'||(v->>'checksum')
    AND (v->>'bytes')::bigint<=104857600 AND length(v->>'title') BETWEEN 1 AND 80
    AND length(v->>'captions')>0 AND jsonb_typeof(v->'metadata')='object', false) THEN
    RAISE EXCEPTION 'invalid_summary'; END IF;
   INSERT INTO media_videos(id,owner_id,job_id,category,position,title,object_key,checksum,byte_count,
    captions,metadata,expires_at)
   VALUES((v->>'artifact')::uuid,j.owner_id,j.id,'architecture',n,v->>'title',v->>'key',v->>'checksum',
    (v->>'bytes')::bigint,v->>'captions',v->'metadata',j.created_at+interval '24 hours');
  END LOOP;
  IF (arch='supported')<>(n>0) THEN RAISE EXCEPTION 'invalid_summary'; END IF;
  UPDATE media_jobs SET architecture=arch WHERE id=j.id;
  PERFORM mv.end_job(j.id,'succeeded',NULL);
 ELSE
  UPDATE media_stages SET state='ready' WHERE job_id=j.id AND ordinal=s.ordinal+1;
 END IF;
 RETURN true;
END $$;

-- The walkthrough is the product; the architecture stage is additional. If it cannot finish,
-- the job still succeeds with architecture='failed' and the reason kept on the stage.
CREATE FUNCTION mv.architecture_failed(p_job uuid, p_stage uuid, p_code text) RETURNS void
 LANGUAGE plpgsql AS $$
BEGIN
 UPDATE media_stages SET state='failed',fence=fence+1,lease_expires_at=NULL,error_code=p_code WHERE id=p_stage;
 UPDATE media_attempts SET outcome='failed',error_code=p_code,ended_at=clock_timestamp()
  WHERE stage_id=p_stage AND outcome='running';
 UPDATE media_jobs SET architecture='failed' WHERE id=p_job;
 PERFORM mv.end_job(p_job,'succeeded',NULL);
END $$;

CREATE FUNCTION mv.fail(p_stage uuid, p_fence bigint, p_code text, p_transient boolean) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE s media_stages; j media_jobs; code text:=p_code;
BEGIN
 SELECT * INTO s FROM media_stages WHERE id=p_stage;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO j FROM media_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM media_stages WHERE id=p_stage FOR UPDATE;
 IF NOT mv.valid_lease(s,j,p_fence) THEN RETURN false; END IF;
 IF code IS NULL OR code !~ '^[a-z][a-z0-9_]{0,63}$' THEN code:='media_failure'; END IF;
 IF p_transient AND s.attempt_count<s.max_attempts AND j.deadline>clock_timestamp()+interval '10 seconds' THEN
  UPDATE media_attempts SET outcome='retry_wait',error_code=code,ended_at=clock_timestamp()
   WHERE stage_id=p_stage AND fence=p_fence;
  UPDATE media_stages SET state='retry_wait',fence=fence+1,lease_expires_at=NULL,error_code=code,
   next_attempt_at=clock_timestamp()+least(120,5*power(2,s.attempt_count-1))*interval '1 second'
   WHERE id=p_stage;
  UPDATE media_jobs SET state='retry_wait' WHERE id=j.id;
 ELSIF s.ordinal=15 THEN PERFORM mv.architecture_failed(j.id,s.id,code);
 ELSE PERFORM mv.end_job(j.id,'failed',code); END IF;
 RETURN true;
END $$;

-- Recovery after a lost worker: an expired lease is fenced off and retried or ended.
CREATE FUNCTION mv.reconcile() RETURNS integer
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
DECLARE s media_stages; j media_jobs; n integer:=0;
BEGIN
 FOR j IN SELECT * FROM media_jobs WHERE state NOT IN ('succeeded','failed','cancelled') ORDER BY created_at LOOP
  SELECT * INTO j FROM media_jobs WHERE id=j.id FOR UPDATE;
  IF j.state IN ('succeeded','failed','cancelled') THEN CONTINUE; END IF;
  IF j.deadline<=clock_timestamp() THEN
   PERFORM mv.end_job(j.id,'failed',CASE WHEN j.state='awaiting_analysis'
    THEN 'analysis_wait_timeout' ELSE 'job_deadline' END);
   n:=n+1; CONTINUE;
  END IF;
  FOR s IN SELECT * FROM media_stages WHERE job_id=j.id AND state IN ('running','retry_wait') FOR UPDATE LOOP
   IF s.state='running' AND (s.lease_expires_at<=clock_timestamp() OR s.stage_deadline<=clock_timestamp()) THEN
    UPDATE media_attempts SET outcome='lease_expired',error_code='lease_expired',ended_at=clock_timestamp()
     WHERE stage_id=s.id AND outcome='running';
    IF s.attempt_count>=s.max_attempts THEN
     IF s.ordinal=15 THEN PERFORM mv.architecture_failed(j.id,s.id,'attempt_limit');
     ELSE PERFORM mv.end_job(j.id,'failed','attempt_limit'); END IF;
    ELSE
     UPDATE media_stages SET state='retry_wait',fence=fence+1,lease_expires_at=NULL,error_code='lease_expired',
      next_attempt_at=clock_timestamp()+least(120,5*power(2,s.attempt_count-1))*interval '1 second'
      WHERE id=s.id;
     UPDATE media_jobs SET state='retry_wait' WHERE id=j.id;
    END IF;
    n:=n+1;
   ELSIF s.state='retry_wait' AND s.next_attempt_at<=clock_timestamp() THEN
    UPDATE media_stages SET state='ready' WHERE id=s.id;
    n:=n+1;
   END IF;
  END LOOP;
 END LOOP;
 RETURN n;
END $$;

CREATE FUNCTION mv.expired() RETURNS TABLE(o_owner uuid,o_job uuid)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
 SELECT DISTINCT v.owner_id,v.job_id FROM media_videos v
 WHERE v.deleted_at IS NULL AND v.expires_at<=clock_timestamp() $$;
CREATE FUNCTION mv.mark_deleted(p_job uuid) RETURNS void
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,mv AS $$
 UPDATE media_videos SET deleted_at=clock_timestamp()
 WHERE job_id=p_job AND deleted_at IS NULL AND expires_at<=clock_timestamp() $$;

-- Procedures run as a no-login role under an explicit internal policy; no login bypasses RLS.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT oid::regprocedure AS signature FROM pg_proc WHERE pronamespace='mv'::regnamespace LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO rvm_executor',f.signature);
 END LOOP;
END $$;
SET LOCAL ROLE rvm_executor;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA mv FROM PUBLIC,rvm_app,rvm_worker;
GRANT EXECUTE ON FUNCTION mv.owner() TO rvm_app;
GRANT EXECUTE ON FUNCTION mv.admit(uuid,uuid,text,text),mv.attach(uuid,jsonb),
 mv.analysis_failed(uuid),mv.cancel(uuid) TO rvm_app;
GRANT EXECUTE ON FUNCTION mv.claim(text),mv.scope(uuid,bigint),mv.heartbeat(uuid,bigint),
 mv.finish(uuid,bigint,uuid,text,text,bigint,jsonb),mv.fail(uuid,bigint,text,boolean),
 mv.reconcile(),mv.expired(),mv.mark_deleted(uuid) TO rvm_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA mv FROM rvm_executor;
