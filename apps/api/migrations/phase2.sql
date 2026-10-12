-- Additive migration. No resets, deleted rows, media handlers or production admission.
GRANT CREATE ON SCHEMA rv TO rv_executor;
ALTER TABLE generation_jobs DROP CONSTRAINT generation_jobs_synthetic_check;
ALTER TABLE generation_jobs DROP CONSTRAINT generation_jobs_fixture_check;
ALTER TABLE generation_jobs ADD CONSTRAINT job_mode CHECK(
 (synthetic AND fixture IN ('normal','transient_once','permanent_failure') AND pipeline_version='phase1-fixture-v1')
 OR (NOT synthetic AND fixture='analysis' AND pipeline_version='phase2-static-v1'));
ALTER TABLE job_stages ADD input_digest text CHECK(input_digest ~ '^[a-f0-9]{64}$');
ALTER TABLE knowledge_artifacts ADD byte_count bigint NOT NULL DEFAULT 0 CHECK(byte_count>=0),
 ADD input_digest text CHECK(input_digest ~ '^[a-f0-9]{64}$'),
 ADD pipeline_version text NOT NULL DEFAULT 'phase1-fixture-v1',
 ADD versions jsonb NOT NULL DEFAULT '{}';
ALTER TABLE generation_jobs ADD UNIQUE(owner_id,id,snapshot_id);
ALTER TABLE job_stages ADD UNIQUE(owner_id,id,job_id);
ALTER TABLE knowledge_artifacts ADD FOREIGN KEY(owner_id,job_id,snapshot_id)
 REFERENCES generation_jobs(owner_id,id,snapshot_id),
 ADD FOREIGN KEY(owner_id,stage_id,job_id) REFERENCES job_stages(owner_id,id,job_id),
 ADD UNIQUE(owner_id,id,job_id,snapshot_id);

CREATE TABLE analysis_results (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES users(id),
 job_id uuid NOT NULL UNIQUE, snapshot_id uuid NOT NULL, artifact_id uuid NOT NULL,
 state text NOT NULL CHECK(state='verified_static_analysis'), summary jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,job_id,snapshot_id) REFERENCES generation_jobs(owner_id,id,snapshot_id),
 FOREIGN KEY(owner_id,artifact_id,job_id,snapshot_id) REFERENCES knowledge_artifacts(owner_id,id,job_id,snapshot_id));
ALTER TABLE analysis_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_results FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant ON analysis_results TO rv_app USING(owner_id=rv.owner()) WITH CHECK(owner_id=rv.owner());
CREATE POLICY internal ON analysis_results TO rv_executor USING(true) WITH CHECK(true);
GRANT SELECT ON analysis_results TO rv_app;
GRANT SELECT,INSERT ON analysis_results TO rv_executor;

-- Protected corpus metadata has a distinct schema with no application/worker grants.
CREATE SCHEMA evaluation;
REVOKE ALL ON SCHEMA evaluation FROM PUBLIC,rv_app,rv_worker,rv_executor;
CREATE TABLE evaluation.manifests (
 version text PRIMARY KEY, checksum text NOT NULL CHECK(checksum ~ '^[a-f0-9]{64}$'),
 state text NOT NULL CHECK(state IN ('UNFROZEN','FROZEN','WITHDRAWN')),
 object_key text NOT NULL, access_policy_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
REVOKE ALL ON ALL TABLES IN SCHEMA evaluation FROM PUBLIC,rv_app,rv_worker,rv_executor;

CREATE FUNCTION rv.snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'snapshot_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER snapshot_update BEFORE UPDATE ON repository_snapshots FOR EACH ROW EXECUTE FUNCTION rv.snapshot_guard();
CREATE FUNCTION rv.artifact_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'artifact_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER artifact_update BEFORE UPDATE ON knowledge_artifacts FOR EACH ROW EXECUTE FUNCTION rv.artifact_guard();
CREATE TRIGGER result_update BEFORE UPDATE ON analysis_results FOR EACH ROW EXECUTE FUNCTION rv.artifact_guard();

-- Stage pointer publication remains one PostgreSQL transaction under the existing lease.
CREATE FUNCTION rv.analysis_scope(sid uuid,epoch bigint) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; snap repository_snapshots; outputs jsonb;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id;
 IF NOT rv.valid_lease(s,j,epoch) OR j.synthetic OR j.fixture<>'analysis' THEN RETURN NULL; END IF;
 SELECT * INTO snap FROM repository_snapshots WHERE id=j.snapshot_id AND owner_id=j.owner_id;
 SELECT coalesce(jsonb_agg(jsonb_build_object('ordinal',t.ordinal,'id',a.id,'checksum',a.checksum,
 'key',a.object_key,'bytes',a.byte_count,'kind',a.kind,'input_digest',a.input_digest) ORDER BY t.ordinal),'[]') INTO outputs
 FROM knowledge_artifacts a JOIN job_stages t ON t.id=a.stage_id AND t.owner_id=a.owner_id
 WHERE a.job_id=j.id AND a.owner_id=j.owner_id AND t.ordinal<s.ordinal;
 RETURN jsonb_build_object('snapshot',snap.metadata,'snapshot_id',snap.id,'outputs',outputs,
 'validate_digest',(SELECT output_digest FROM job_stages WHERE job_id=j.id AND ordinal=1));
END $$;

CREATE FUNCTION rv.finish_analysis(sid uuid,epoch bigint,artifact uuid,checksum text,object_path text,
 bytes bigint,input_hash text,summary jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; expected text; upstream text; calculated text; kind text;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) THEN RETURN false; END IF;
 IF j.synthetic OR j.fixture<>'analysis' OR s.ordinal NOT BETWEEN 2 AND 9 THEN RAISE EXCEPTION 'phase2_boundary'; END IF;
 expected:='development/'||j.owner_id||'/'||j.snapshot_id||'/'||j.id||'/analysis/'||artifact||'/'||checksum;
 IF object_path<>expected OR checksum !~ '^[a-f0-9]{64}$' OR bytes<0 OR bytes>104857600 THEN
  RAISE EXCEPTION 'invalid_artifact'; END IF;
 SELECT string_agg(output_digest,'|' ORDER BY ordinal) INTO upstream FROM job_stages
 WHERE job_id=j.id AND ordinal<s.ordinal AND state='succeeded';
 IF (SELECT count(*) FROM job_stages WHERE job_id=j.id AND ordinal<s.ordinal AND state='succeeded')<>s.ordinal-1 THEN
  RAISE EXCEPTION 'invalid_upstream'; END IF;
 SELECT encode(sha256(convert_to(commit_sha||'|phase2-static-v1|'||upstream,'UTF8')),'hex') INTO calculated
 FROM repository_snapshots WHERE id=j.snapshot_id;
 IF input_hash<>calculated THEN RAISE EXCEPTION 'input_digest_mismatch'; END IF;
 kind:=CASE s.ordinal WHEN 2 THEN 'source_archive' ELSE s.stage_key END;
 INSERT INTO knowledge_artifacts(id,owner_id,snapshot_id,job_id,stage_id,kind,schema_version,object_key,
 checksum,synthetic,byte_count,input_digest,pipeline_version,versions,expires_at)
 VALUES(artifact,j.owner_id,j.snapshot_id,j.id,s.id,kind,'2.2',object_path,checksum,false,bytes,input_hash,
 'phase2-static-v1','{"parser":"tree-sitter-0.25.2","rules":"static-rules-v1"}',j.created_at+interval '24 hours');
 UPDATE job_stages SET state='succeeded',input_digest=input_hash,output_digest=checksum,lease_expires_at=NULL WHERE id=sid;
 UPDATE job_attempts SET outcome='succeeded',ended_at=now() WHERE stage_id=sid AND fence=epoch;
 INSERT INTO usage_cost_records(owner_id,job_id,attempt_id,operation_id,event_type,measurements)
 SELECT j.owner_id,j.id,id,id::text||':artifact','analysis_artifact',
 jsonb_build_object('bytes',bytes)||coalesce(summary->'measurements','{}'::jsonb)
 FROM job_attempts WHERE stage_id=sid AND fence=epoch;
 IF s.ordinal=9 THEN
  IF summary->>'schema'<>'phase2-summary-v1' THEN RAISE EXCEPTION 'invalid_summary'; END IF;
  INSERT INTO analysis_results(owner_id,job_id,snapshot_id,artifact_id,state,summary)
  VALUES(j.owner_id,j.id,j.snapshot_id,artifact,'verified_static_analysis',summary);
  PERFORM rv.end_job(j.id,'failed','phase2_pipeline_boundary');
 ELSE
  UPDATE job_stages SET state='ready' WHERE job_id=j.id AND ordinal=s.ordinal+1;
  INSERT INTO outbox_events(owner_id,job_id,stage_id,event_type)
  SELECT j.owner_id,j.id,id,'stage' FROM job_stages WHERE job_id=j.id AND ordinal=s.ordinal+1;
 END IF;
 RETURN true;
END $$;

CREATE FUNCTION rv.fail_analysis(sid uuid,epoch bigint,code text,transient boolean) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; due timestamptz;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) OR j.synthetic THEN RETURN false; END IF;
 IF code NOT IN ('github_unavailable','github_timeout','github_rate_limited','github_address_blocked',
 'github_redirect_rejected','github_response_type','github_response_encoding','github_truncated_response',
 'archive_download_limit','archive_unsafe_path','archive_duplicate','archive_collision','archive_multiple_roots',
 'archive_unsafe_entry','archive_missing_root','archive_extraction_limit','archive_expansion_limit','archive_member_limit',
 'archive_nested','archive_malformed','scratch_not_fresh','secret_detected','eligible_source_limit',
 'source_changed','insufficient_evidence','parser_timeout','parser_resource_limit','analysis_fact_limit',
 'invalid_evidence_range','duplicate_grounding_id','parser_isolation_unavailable','parser_isolation_or_analysis_failed',
 'analysis_timeout','artifact_corrupt','analysis_failure','repository_not_found','repository_removed','github_access_denied') THEN
  code:='analysis_failure'; END IF;
 IF transient AND code IN ('github_unavailable','github_timeout','github_rate_limited','github_truncated_response','analysis_failure')
 AND s.attempt_count<s.max_attempts AND j.deadline>clock_timestamp()+interval '10 seconds' THEN
  due:=clock_timestamp()+least(120,5*power(2,s.attempt_count-1))*interval '1 second'+random()*interval '5 seconds';
  UPDATE job_attempts SET outcome='retry_wait',error_code=code,ended_at=now() WHERE stage_id=sid AND fence=epoch;
  UPDATE job_stages SET state='retry_wait',fence=fence+1,lease_expires_at=NULL,next_attempt_at=due,error_code=code WHERE id=sid;
  UPDATE generation_jobs SET state='retry_wait' WHERE id=j.id;
 ELSE PERFORM rv.end_job(j.id,'failed',code); END IF;
 RETURN true;
END $$;

-- Expiration exposes only DB-resolved terminal-job prefixes. No project-wide deletion.
CREATE FUNCTION rv.expired_analysis_scope() RETURNS TABLE(owner_id uuid,snapshot_id uuid,job_id uuid)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT j.owner_id,j.snapshot_id,j.id FROM generation_jobs j
 WHERE NOT j.synthetic AND j.state IN ('failed','cancelled') AND j.created_at+interval '24 hours'<=clock_timestamp() $$;

CREATE FUNCTION rv.analysis_scratch_cleanup_scope() RETURNS TABLE(job_id uuid)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT id FROM generation_jobs WHERE NOT synthetic AND state IN ('failed','cancelled') $$;

ALTER FUNCTION rv.analysis_scope(uuid,bigint) OWNER TO rv_executor;
ALTER FUNCTION rv.finish_analysis(uuid,bigint,uuid,text,text,bigint,text,jsonb) OWNER TO rv_executor;
ALTER FUNCTION rv.fail_analysis(uuid,bigint,text,boolean) OWNER TO rv_executor;
ALTER FUNCTION rv.expired_analysis_scope() OWNER TO rv_executor;
ALTER FUNCTION rv.analysis_scratch_cleanup_scope() OWNER TO rv_executor;
SET LOCAL ROLE rv_executor;
REVOKE ALL ON FUNCTION rv.analysis_scope(uuid,bigint),rv.finish_analysis(uuid,bigint,uuid,text,text,bigint,text,jsonb),
 rv.fail_analysis(uuid,bigint,text,boolean),rv.expired_analysis_scope(),rv.analysis_scratch_cleanup_scope() FROM PUBLIC,rv_app;
GRANT EXECUTE ON FUNCTION rv.analysis_scope(uuid,bigint),rv.finish_analysis(uuid,bigint,uuid,text,text,bigint,text,jsonb),
 rv.fail_analysis(uuid,bigint,text,boolean),rv.expired_analysis_scope(),rv.analysis_scratch_cleanup_scope() TO rv_worker;
RESET ROLE;

CREATE FUNCTION rv.admit_analysis(pid uuid, idem text, digest text, sha text, metadata jsonb, validation_hash text, prior uuid DEFAULT NULL)
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
 IF NOT EXISTS(SELECT 1 FROM projects WHERE id=pid AND owner_id=o AND deleted_at IS NULL) THEN
  RAISE EXCEPTION 'not_found';
 END IF;
 SELECT * INTO existing FROM generation_jobs WHERE owner_id=o AND idempotency_key=idem;
 IF FOUND THEN
  IF existing.request_digest<>digest THEN RAISE EXCEPTION 'idempotency_conflict'; END IF;
  RETURN existing.id;
 END IF;
 IF prior IS NOT NULL AND NOT EXISTS(SELECT 1 FROM generation_jobs WHERE id=prior AND owner_id=o
  AND project_id=pid AND state IN ('failed','cancelled')) THEN RAISE EXCEPTION 'invalid_retry'; END IF;
 IF sha !~ '^[a-f0-9]{40}$' OR validation_hash !~ '^[a-f0-9]{64}$' OR metadata->>'commit_sha'<>sha OR metadata->>'public'<>'true' THEN RAISE EXCEPTION 'invalid_snapshot'; END IF;
 SELECT count(*) INTO total FROM quota_reservations WHERE month=date_trunc('month',now())::date;
 IF total>=100 OR (SELECT count(*) FROM quota_reservations WHERE owner_id=o
  AND month=date_trunc('month',now())::date)>=q.month_limit THEN RAISE EXCEPTION 'monthly_quota'; END IF;
 IF (SELECT count(*) FROM generation_jobs WHERE owner_id=o AND state='queued')>=q.queued_limit THEN
  RAISE EXCEPTION 'queue_quota'; END IF;
 IF (SELECT count(*) FROM generation_jobs WHERE owner_id=o AND created_at>now()-interval '1 minute')>=2 THEN
  RAISE EXCEPTION 'admission_rate'; END IF;
 INSERT INTO repository_snapshots(owner_id,project_id,commit_sha,synthetic,acquisition_version,pipeline_version,metadata)
 VALUES(o,pid,sha,false,'github-archive-v1','phase2-static-v1',metadata)
 ON CONFLICT(owner_id,project_id,commit_sha,acquisition_version) DO NOTHING;
 SELECT id INTO sid FROM repository_snapshots WHERE owner_id=o AND project_id=pid AND commit_sha=sha
 AND acquisition_version='github-archive-v1';
 IF (SELECT repository_snapshots.metadata FROM repository_snapshots WHERE id=sid)<>metadata THEN
  RAISE EXCEPTION 'snapshot_metadata_conflict'; END IF;
 IF prior IS NOT NULL AND NOT EXISTS(SELECT 1 FROM generation_jobs WHERE id=prior AND owner_id=o AND snapshot_id=sid AND NOT synthetic) THEN
  RAISE EXCEPTION 'invalid_retry'; END IF;
 INSERT INTO generation_jobs(id,owner_id,project_id,snapshot_id,state,synthetic,fixture,idempotency_key,
 request_digest,pipeline_version,deadline,prior_job_id)
 VALUES(jid,o,pid,sid,'queued',false,'analysis',idem,digest,'phase2-static-v1',now()+interval '45 minutes',prior);
 FOR i IN 1..14 LOOP
  INSERT INTO job_stages(owner_id,job_id,ordinal,stage_key,state,max_attempts,timeout_seconds,output_digest,input_digest,attempt_count)
  VALUES(o,jid,i,keys[i],CASE i WHEN 1 THEN 'succeeded' WHEN 2 THEN 'ready' ELSE 'pending' END,
  CASE i WHEN 1 THEN 1 WHEN 2 THEN 3 ELSE 2 END,timeouts[i],CASE WHEN i=1 THEN validation_hash ELSE NULL END,CASE WHEN i=1 THEN digest ELSE NULL END,CASE WHEN i=1 THEN 1 ELSE 0 END) RETURNING id INTO stageid;
  IF i=2 THEN INSERT INTO outbox_events(owner_id,job_id,stage_id,event_type) VALUES(o,jid,stageid,'stage'); END IF;
 END LOOP;
 INSERT INTO job_attempts(owner_id,job_id,stage_id,attempt_no,fence,worker_id,outcome,ended_at)
 SELECT o,jid,id,1,0,'api-commit-resolution','succeeded',now() FROM job_stages WHERE job_id=jid AND ordinal=1;
 INSERT INTO quota_reservations(owner_id,job_id,month) VALUES(o,jid,date_trunc('month',now())::date);
 INSERT INTO usage_cost_records(owner_id,job_id,operation_id,event_type,units)
 VALUES(o,jid,jid::text||':reserved','reserved',1);
 RETURN jid;
END $$;


ALTER FUNCTION rv.admit_analysis(uuid,text,text,text,jsonb,text,uuid) OWNER TO rv_executor;
GRANT CREATE ON SCHEMA rv TO rv_executor;
SET LOCAL ROLE rv_executor;
REVOKE ALL ON FUNCTION rv.admit_analysis(uuid,text,text,text,jsonb,text,uuid) FROM PUBLIC,rv_worker;
GRANT EXECUTE ON FUNCTION rv.admit_analysis(uuid,text,text,text,jsonb,text,uuid) TO rv_app;
CREATE OR REPLACE FUNCTION rv.job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.state='succeeded' THEN RAISE EXCEPTION 'video_generation_disabled'; END IF;
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
  IF NEW.state='succeeded' THEN RAISE EXCEPTION 'video_generation_disabled'; END IF;
  INSERT INTO job_history(owner_id,job_id,version,state,error_code)
  VALUES(NEW.owner_id,NEW.id,NEW.version,NEW.state,NEW.error_code);
 END IF;
 RETURN NEW;
END $$;

RESET ROLE;
REVOKE CREATE ON SCHEMA rv FROM rv_executor;
CREATE FUNCTION rv.video_disabled() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'video_generation_disabled'; END $$;
CREATE TRIGGER no_video BEFORE INSERT ON video_artifacts FOR EACH ROW EXECUTE FUNCTION rv.video_disabled();
