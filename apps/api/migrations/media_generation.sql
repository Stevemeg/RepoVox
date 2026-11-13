-- Additive product video mode. Existing fixture/analysis jobs, their stage ordinals, terminal
-- states, pilot control plane and historical rows are unchanged: analysis jobs still end at
-- Stage 9 with phase2_pipeline_boundary. Only fixture='video' jobs may reach Stages 10-14.
GRANT CREATE ON SCHEMA rv TO rv_executor;

ALTER TABLE generation_jobs DROP CONSTRAINT job_mode;
ALTER TABLE generation_jobs ADD CONSTRAINT job_mode CHECK(
 (synthetic AND fixture IN ('normal','transient_once','permanent_failure') AND pipeline_version='phase1-fixture-v1')
 OR (NOT synthetic AND fixture='analysis' AND pipeline_version='phase2-static-v1')
 OR (NOT synthetic AND fixture='video' AND pipeline_version='phase2-static-v1'));
CREATE UNIQUE INDEX storyboards_one_per_job ON storyboards(job_id);

-- Published media records are immutable; only expiry may set deleted_at once.
CREATE FUNCTION rv.video_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'video_immutable'; END IF;
 IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL
  AND (to_jsonb(NEW)-'deleted_at')=(to_jsonb(OLD)-'deleted_at') THEN RETURN NEW; END IF;
 IF NEW IS DISTINCT FROM OLD THEN RAISE EXCEPTION 'video_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER video_update BEFORE UPDATE OR DELETE ON video_artifacts FOR EACH ROW EXECUTE FUNCTION rv.video_guard();
CREATE TRIGGER storyboard_update BEFORE UPDATE ON storyboards FOR EACH ROW EXECUTE FUNCTION rv.artifact_guard();

-- The publication row is accepted only for a video-mode job whose encode stage already holds a
-- committed artifact with the same checksum. Every other insert stays disabled as before.
CREATE OR REPLACE FUNCTION rv.video_disabled() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(
  SELECT 1 FROM generation_jobs j
  JOIN job_stages s ON s.job_id=j.id AND s.owner_id=j.owner_id AND s.ordinal=14 AND s.state='succeeded'
  JOIN knowledge_artifacts a ON a.stage_id=s.id AND a.owner_id=j.owner_id AND a.kind='encode'
  JOIN storyboards b ON b.id=NEW.storyboard_id AND b.job_id=j.id AND b.owner_id=j.owner_id
  WHERE j.id=NEW.job_id AND j.owner_id=NEW.owner_id AND NOT j.synthetic AND j.fixture='video'
  AND j.state='running' AND a.checksum=NEW.metadata->>'sha256' AND a.id::text=NEW.metadata->>'artifact_id')
 THEN RAISE EXCEPTION 'video_generation_disabled'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION rv.media_scope(sid uuid,epoch bigint) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; snap repository_snapshots; outputs jsonb; compatible boolean;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id;
 IF NOT rv.valid_lease(s,j,epoch) OR j.synthetic OR j.fixture<>'video' THEN RETURN NULL; END IF;
 SELECT * INTO snap FROM repository_snapshots WHERE id=j.snapshot_id AND owner_id=j.owner_id;
 SELECT coalesce(jsonb_agg(jsonb_build_object('ordinal',t.ordinal,'id',a.id,'checksum',a.checksum,
 'key',a.object_key,'bytes',a.byte_count,'kind',a.kind,'input_digest',a.input_digest) ORDER BY t.ordinal),'[]') INTO outputs
 FROM knowledge_artifacts a JOIN job_stages t ON t.id=a.stage_id AND t.owner_id=a.owner_id
 WHERE a.job_id=j.id AND a.owner_id=j.owner_id AND t.ordinal<s.ordinal;
 SELECT NOT EXISTS(SELECT 1 FROM knowledge_artifacts a WHERE a.job_id=j.id AND a.pipeline_version='phase2-static-v1'
  AND (a.schema_version<>'2.3' OR a.versions->>'rules' IS DISTINCT FROM 'static-rules-v2')) INTO compatible;
 RETURN jsonb_build_object('snapshot',snap.metadata,'snapshot_id',snap.id,'outputs',outputs,
 'validate_digest',(SELECT output_digest FROM job_stages WHERE job_id=j.id AND ordinal=1),
 'version_compatible',compatible,'ordinal',s.ordinal);
END $$;

-- One fenced transaction publishes the artifact pointer and advances exactly one stage.
CREATE FUNCTION rv.finish_media(sid uuid,epoch bigint,artifact uuid,checksum text,object_path text,
 bytes bigint,input_hash text,summary jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; expected text; upstream text; calculated text; area text; board uuid;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=s.owner_id FOR UPDATE;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) THEN RETURN false; END IF;
 IF j.synthetic OR j.fixture<>'video' OR s.ordinal NOT BETWEEN 2 AND 14
  OR EXISTS(SELECT 1 FROM pilot_bindings WHERE job_id=j.id) THEN RAISE EXCEPTION 'media_boundary'; END IF;
 area:=CASE WHEN s.ordinal<=9 THEN 'analysis' ELSE 'media' END;
 expected:='development/'||j.owner_id||'/'||j.snapshot_id||'/'||j.id||'/'||area||'/'||artifact||'/'||checksum;
 IF object_path<>expected OR checksum !~ '^[a-f0-9]{64}$' OR bytes<=0 OR bytes>104857600 THEN
  RAISE EXCEPTION 'invalid_artifact'; END IF;
 SELECT string_agg(output_digest,'|' ORDER BY ordinal) INTO upstream FROM job_stages
 WHERE job_id=j.id AND ordinal<s.ordinal AND state='succeeded';
 IF (SELECT count(*) FROM job_stages WHERE job_id=j.id AND ordinal<s.ordinal AND state='succeeded')<>s.ordinal-1 THEN
  RAISE EXCEPTION 'invalid_upstream'; END IF;
 SELECT encode(sha256(convert_to(commit_sha||'|phase2-static-v1|'||upstream,'UTF8')),'hex') INTO calculated
 FROM repository_snapshots WHERE id=j.snapshot_id;
 IF input_hash<>calculated THEN RAISE EXCEPTION 'input_digest_mismatch'; END IF;
 IF s.ordinal<=9 THEN
  INSERT INTO knowledge_artifacts(id,owner_id,snapshot_id,job_id,stage_id,kind,schema_version,object_key,
  checksum,synthetic,byte_count,input_digest,pipeline_version,versions,expires_at)
  VALUES(artifact,j.owner_id,j.snapshot_id,j.id,s.id,CASE s.ordinal WHEN 2 THEN 'source_archive' ELSE s.stage_key END,
  '2.3',object_path,checksum,false,bytes,input_hash,'phase2-static-v1',
  '{"parser":"tree-sitter-0.25.2","rules":"static-rules-v2"}',j.created_at+interval '24 hours');
 ELSE
  INSERT INTO knowledge_artifacts(id,owner_id,snapshot_id,job_id,stage_id,kind,schema_version,object_key,
  checksum,synthetic,byte_count,input_digest,pipeline_version,versions,expires_at)
  VALUES(artifact,j.owner_id,j.snapshot_id,j.id,s.id,s.stage_key,'media-1.0',object_path,checksum,false,bytes,
  input_hash,'product-media-v1','{"media":"grounded-media-run-1.0"}',j.created_at+interval '24 hours');
 END IF;
 UPDATE job_stages SET state='succeeded',input_digest=input_hash,output_digest=checksum,lease_expires_at=NULL WHERE id=sid;
 UPDATE job_attempts SET outcome='succeeded',ended_at=now() WHERE stage_id=sid AND fence=epoch;
 INSERT INTO usage_cost_records(owner_id,job_id,attempt_id,operation_id,event_type,measurements)
 SELECT j.owner_id,j.id,id,id::text||':artifact',CASE WHEN s.ordinal<=9 THEN 'analysis_artifact' ELSE 'media_artifact' END,
 jsonb_build_object('bytes',bytes)||coalesce(summary->'measurements','{}'::jsonb)
 FROM job_attempts WHERE stage_id=sid AND fence=epoch;
 IF s.ordinal=9 THEN
  IF summary->>'schema' IS DISTINCT FROM 'phase2-summary-v1' THEN RAISE EXCEPTION 'invalid_summary'; END IF;
  INSERT INTO analysis_results(owner_id,job_id,snapshot_id,artifact_id,state,summary)
  VALUES(j.owner_id,j.id,j.snapshot_id,artifact,'verified_static_analysis',summary);
 ELSIF s.ordinal=10 THEN
  INSERT INTO storyboards(owner_id,job_id,snapshot_id,knowledge_artifact_id,version,digest)
  SELECT j.owner_id,j.id,j.snapshot_id,r.artifact_id,'grounded-storyboard-1.0',checksum
  FROM analysis_results r WHERE r.job_id=j.id AND r.owner_id=j.owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'invalid_upstream'; END IF;
 END IF;
 IF s.ordinal=14 THEN
  SELECT id INTO board FROM storyboards WHERE job_id=j.id AND owner_id=j.owner_id;
  IF board IS NULL OR jsonb_typeof(summary->'video')<>'object'
   OR coalesce((summary->'video'->>'video_frames')::bigint,0)<=0
   OR summary->'video'->>'full_decode' IS DISTINCT FROM 'passed' THEN RAISE EXCEPTION 'invalid_summary'; END IF;
  INSERT INTO video_artifacts(owner_id,job_id,storyboard_id,metadata,expires_at)
  VALUES(j.owner_id,j.id,board,(summary->'video')||jsonb_build_object('artifact_id',artifact,'sha256',checksum,'bytes',bytes),
  j.created_at+interval '24 hours');
  PERFORM rv.end_job(j.id,'succeeded',NULL);
 ELSE
  UPDATE job_stages SET state='ready' WHERE job_id=j.id AND ordinal=s.ordinal+1;
  INSERT INTO outbox_events(owner_id,job_id,stage_id,event_type)
  SELECT j.owner_id,j.id,id,'stage' FROM job_stages WHERE job_id=j.id AND ordinal=s.ordinal+1;
 END IF;
 RETURN true;
END $$;

CREATE FUNCTION rv.fail_media(sid uuid,epoch bigint,code text,transient boolean) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE s job_stages; j generation_jobs; due timestamptz;
BEGIN
 SELECT * INTO s FROM job_stages WHERE id=sid;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM quota_accounts WHERE owner_id=s.owner_id FOR UPDATE;
 SELECT * INTO j FROM generation_jobs WHERE id=s.job_id FOR UPDATE;
 SELECT * INTO s FROM job_stages WHERE id=sid FOR UPDATE;
 IF NOT rv.valid_lease(s,j,epoch) OR j.synthetic OR j.fixture<>'video' OR s.ordinal<10 THEN RETURN false; END IF;
 IF code NOT IN ('artifact_corrupt','invalid_analysis_payload','insufficient_evidence','unverified_claim',
 'invalid_evidence','uncited_technical_sentence','excerpt_mismatch','speech_text_mismatch','analysis_mismatch',
 'duplicate_scene','storyboard_not_reproducible','narration_engine_unavailable','narration_text_rejected',
 'speech_synthesis_failed','speech_format_unsupported','speech_silent','visual_overflow','caption_overflow',
 'missing_installed_ffmpeg','missing_installed_ffprobe','media_command_failed','media_streams','media_video',
 'media_audio','media_duration','media_timeout','media_bundle_invalid','invalid_storyboard','media_storage_unavailable','media_failure') THEN
  code:='media_failure'; END IF;
 IF transient AND code IN ('media_storage_unavailable','media_failure')
 AND s.attempt_count<s.max_attempts AND j.deadline>clock_timestamp()+interval '10 seconds' THEN
  due:=clock_timestamp()+least(120,5*power(2,s.attempt_count-1))*interval '1 second'+random()*interval '5 seconds';
  UPDATE job_attempts SET outcome='retry_wait',error_code=code,ended_at=now() WHERE stage_id=sid AND fence=epoch;
  UPDATE job_stages SET state='retry_wait',fence=fence+1,lease_expires_at=NULL,next_attempt_at=due,error_code=code WHERE id=sid;
  UPDATE generation_jobs SET state='retry_wait' WHERE id=j.id;
 ELSE PERFORM rv.end_job(j.id,'failed',code); END IF;
 RETURN true;
END $$;

-- Expired published videos: resolve exact job prefixes, then record deletion once.
CREATE FUNCTION rv.expired_video_scope() RETURNS TABLE(owner_id uuid,snapshot_id uuid,job_id uuid)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
 SELECT j.owner_id,j.snapshot_id,j.id FROM generation_jobs j JOIN video_artifacts v ON v.job_id=j.id
 WHERE NOT j.synthetic AND j.fixture='video' AND j.state='succeeded' AND v.deleted_at IS NULL
 AND v.expires_at<=clock_timestamp() $$;
CREATE FUNCTION rv.video_expired(jid uuid) RETURNS void LANGUAGE sql SECURITY DEFINER
 SET search_path=pg_catalog,public,rv AS $$
 UPDATE video_artifacts SET deleted_at=clock_timestamp()
 WHERE job_id=jid AND deleted_at IS NULL AND expires_at<=clock_timestamp() $$;

-- Same admission checks, locks, quotas, deadline and fourteen stage rows as analysis admission.
CREATE FUNCTION rv.admit_video(pid uuid, idem text, digest text, sha text, metadata jsonb, validation_hash text, prior uuid DEFAULT NULL)
 RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE o uuid:=rv.owner(); existing generation_jobs; jid uuid:=gen_random_uuid(); sid uuid;
 keys text[]:=ARRAY['validate','acquire','filter','structure','entrypoints','infer','knowledge',
 'evidence','verify','storyboard','narration','tts','render','encode'];
 timeouts int[]:=ARRAY[10,120,30,120,30,90,30,30,90,360,360,240,600,180];
 q quota_accounts; i int; stageid uuid; total int;
BEGIN
 IF o IS NULL THEN RAISE EXCEPTION 'unauthorized'; END IF;
 PERFORM pg_advisory_xact_lock(712031);
 SELECT * INTO q FROM quota_accounts WHERE owner_id=o FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'unauthorized'; END IF;
 IF NOT EXISTS(SELECT 1 FROM projects WHERE id=pid AND owner_id=o AND deleted_at IS NULL) THEN
  RAISE EXCEPTION 'not_found';
 END IF;
 IF EXISTS(SELECT 1 FROM pilot_bindings WHERE project_id=pid) THEN RAISE EXCEPTION 'pilot_admission_route_required'; END IF;
 SELECT * INTO existing FROM generation_jobs WHERE owner_id=o AND idempotency_key=idem;
 IF FOUND THEN
  IF existing.request_digest<>digest THEN RAISE EXCEPTION 'idempotency_conflict'; END IF;
  RETURN existing.id;
 END IF;
 IF prior IS NOT NULL AND NOT EXISTS(SELECT 1 FROM generation_jobs WHERE id=prior AND owner_id=o
  AND project_id=pid AND fixture='video' AND state IN ('failed','cancelled')) THEN RAISE EXCEPTION 'invalid_retry'; END IF;
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
 VALUES(jid,o,pid,sid,'queued',false,'video',idem,digest,'phase2-static-v1',now()+interval '45 minutes',prior);
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

ALTER FUNCTION rv.media_scope(uuid,bigint) OWNER TO rv_executor;
ALTER FUNCTION rv.finish_media(uuid,bigint,uuid,text,text,bigint,text,jsonb) OWNER TO rv_executor;
ALTER FUNCTION rv.fail_media(uuid,bigint,text,boolean) OWNER TO rv_executor;
ALTER FUNCTION rv.expired_video_scope() OWNER TO rv_executor;
ALTER FUNCTION rv.video_expired(uuid) OWNER TO rv_executor;
ALTER FUNCTION rv.admit_video(uuid,text,text,text,jsonb,text,uuid) OWNER TO rv_executor;
SET LOCAL ROLE rv_executor;
REVOKE ALL ON FUNCTION rv.media_scope(uuid,bigint),rv.finish_media(uuid,bigint,uuid,text,text,bigint,text,jsonb),
 rv.fail_media(uuid,bigint,text,boolean),rv.expired_video_scope(),rv.video_expired(uuid),
 rv.admit_video(uuid,text,text,text,jsonb,text,uuid) FROM PUBLIC,rv_app,rv_worker;
GRANT EXECUTE ON FUNCTION rv.media_scope(uuid,bigint),rv.finish_media(uuid,bigint,uuid,text,text,bigint,text,jsonb),
 rv.fail_media(uuid,bigint,text,boolean),rv.expired_video_scope(),rv.video_expired(uuid) TO rv_worker;
GRANT EXECUTE ON FUNCTION rv.admit_video(uuid,text,text,text,jsonb,text,uuid) TO rv_app;

-- Success remains disabled for every job except a video-mode job with all fourteen stages
-- succeeded and a committed publication row. Other transitions are byte-identical to 0002.
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
  IF NEW.state='succeeded' AND NOT (NOT NEW.synthetic AND NEW.fixture='video'
   AND (SELECT count(*) FROM job_stages WHERE job_id=NEW.id AND state='succeeded')=14
   AND EXISTS(SELECT 1 FROM video_artifacts WHERE job_id=NEW.id AND owner_id=NEW.owner_id AND deleted_at IS NULL))
  THEN RAISE EXCEPTION 'video_generation_disabled'; END IF;
  INSERT INTO job_history(owner_id,job_id,version,state,error_code)
  VALUES(NEW.owner_id,NEW.id,NEW.version,NEW.state,NEW.error_code);
 END IF;
 RETURN NEW;
END $$;

RESET ROLE;
REVOKE CREATE ON SCHEMA rv FROM rv_executor;
