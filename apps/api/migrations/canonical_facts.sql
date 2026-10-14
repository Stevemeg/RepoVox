-- Additive 2.3 completion path. Legacy function and historical rows remain unchanged.
GRANT CREATE ON SCHEMA rv TO rv_executor;

CREATE FUNCTION rv.finish_analysis_v23(sid uuid,epoch bigint,artifact uuid,checksum text,object_path text,
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
 VALUES(artifact,j.owner_id,j.snapshot_id,j.id,s.id,kind,'2.3',object_path,checksum,false,bytes,input_hash,
 'phase2-static-v1','{"parser":"tree-sitter-0.25.2","rules":"static-rules-v2"}',j.created_at+interval '24 hours');
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

-- Both legacy and current writers must keep a job on one artifact/rule version.
-- Completion procedures already hold the generation_jobs row lock.
CREATE FUNCTION rv.analysis_versions_match() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog,public,rv AS $$
BEGIN
 IF NEW.pipeline_version='phase2-static-v1' THEN
  IF NOT ((NEW.schema_version='2.2' AND NEW.versions->>'rules'='static-rules-v1') OR
          (NEW.schema_version='2.3' AND NEW.versions->>'rules'='static-rules-v2'))
     OR NEW.versions->>'rules' IS NULL THEN
   RAISE EXCEPTION 'analysis_version_mismatch'; END IF;
  IF EXISTS(SELECT 1 FROM knowledge_artifacts a WHERE a.job_id=NEW.job_id
    AND (a.schema_version<>NEW.schema_version OR a.versions->>'rules' IS DISTINCT FROM NEW.versions->>'rules')) THEN
   RAISE EXCEPTION 'analysis_version_mismatch'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER analysis_version_guard BEFORE INSERT ON knowledge_artifacts
 FOR EACH ROW EXECUTE FUNCTION rv.analysis_versions_match();

CREATE FUNCTION rv.analysis_scope_v23(sid uuid,epoch bigint) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,rv AS $$
DECLARE result jsonb; compatible boolean;
BEGIN
 result:=rv.analysis_scope(sid,epoch);
 IF result IS NULL THEN RETURN NULL; END IF;
 SELECT NOT EXISTS(SELECT 1 FROM knowledge_artifacts a JOIN job_stages s ON s.id=sid
   WHERE a.job_id=s.job_id AND (a.schema_version<>'2.3' OR
     a.versions->>'rules' IS DISTINCT FROM 'static-rules-v2')) INTO compatible;
 RETURN result||jsonb_build_object('version_compatible',compatible);
END $$;

ALTER FUNCTION rv.finish_analysis_v23(uuid,bigint,uuid,text,text,bigint,text,jsonb) OWNER TO rv_executor;
ALTER FUNCTION rv.analysis_scope_v23(uuid,bigint) OWNER TO rv_executor;
ALTER FUNCTION rv.analysis_versions_match() OWNER TO rv_executor;
SET LOCAL ROLE rv_executor;
REVOKE ALL ON FUNCTION rv.finish_analysis_v23(uuid,bigint,uuid,text,text,bigint,text,jsonb),
 rv.analysis_scope_v23(uuid,bigint),rv.analysis_versions_match() FROM PUBLIC,rv_app;
GRANT EXECUTE ON FUNCTION rv.finish_analysis_v23(uuid,bigint,uuid,text,text,bigint,text,jsonb),
 rv.analysis_scope_v23(uuid,bigint) TO rv_worker;
RESET ROLE;
REVOKE CREATE ON SCHEMA rv FROM rv_executor;
