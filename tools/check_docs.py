"""Offline Phase 0 documentation/contract checks, not application tests."""
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ['README.md', 'AGENTS.md', 'docs/product/prd.md',
            'docs/architecture/overview.md', 'docs/architecture/pipeline.md',
            'docs/architecture/data-model.md', 'docs/security/threat-model.md',
            'docs/operations/deployment.md', 'docs/operations/reliability.md',
            'docs/operations/cost-model.md', 'docs/delivery/roadmap.md',
            'docs/delivery/phase0-verification.md', 'docs/adr/README.md',
            'docs/architecture/artifact.schema.json', 'docs/architecture/examples/pipeline.json']
REQUIRED += ['docs/ai/'+name for name in ('director-architecture.md','model-selection.md','training-strategy.md','evaluation-plan.md','speech-strategy.md','change-impact.md','director.schema.json','pre-revision-reference-audit.json','research-sources.json')]
REQUIRED += ['docs/delivery/phase0-revision-verification.md','docs/operations/cost-inputs.json','tools/cost_model.py','tools/test_cost_model.py']



def plain_markdown(text):
    return re.sub(r'^```.*?^```\s*$', '', text, flags=re.M | re.S)


def anchors(path):
    found = set()
    counts = {}
    for heading in re.findall(r'^#{1,6}\s+(.+)$', plain_markdown(path.read_text(encoding='utf-8')), re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        found.add(slug if count == 0 else f'{slug}-{count}')
    return found


def validate_example(example, validator):
    assert example['synthetic'] is True
    kinds = [a['kind'] for a in example['artifacts']]
    assert len(kinds) == len(set(kinds)) == 10
    by_kind = {a['kind']: a for a in example['artifacts']}
    first = example['artifacts'][0]
    for a in example['artifacts']:
        validator.validate(a)
        for field in ('owner_id', 'snapshot_id', 'commit_sha', 'pipeline_version'):
            assert a[field] == first[field], f'Inconsistent {field}'
    payload = {k: a['payload'] for k, a in by_kind.items()}
    files = {f['path']: f for f in payload['source_manifest']['files']}
    assert len(files) == len(payload['source_manifest']['files'])
    for path, f in files.items():
        assert not path.startswith(('/', '\\')) and '..' not in Path(path).parts and ':' not in path
        content = f['example_content'].encode('utf-8')
        assert hashlib.sha256(content).hexdigest() == f['file_sha256']
        assert len(content) == f['bytes']
    manifest = payload['source_manifest']
    assert manifest['eligible_bytes'] > 0 and manifest['parsed_bytes']/manifest['eligible_bytes'] >= 0.9
    evidence = {e['id']: e for e in payload['evidence']['items']}
    assert len(evidence) == len(payload['evidence']['items'])
    for e in evidence.values():
        assert e['commit_sha'] == first['commit_sha']
        f = files[e['path']]
        assert e['file_sha256'] == f['file_sha256']
        assert 1 <= e['start_line'] <= e['end_line'] <= len(f['example_content'].splitlines())
    claims = {c['id']: c for c in payload['knowledge']['claims']}
    assert len(claims) == len(payload['knowledge']['claims'])
    for c in claims.values():
        for eid in c['evidence_ids']:
            assert eid in evidence
        if c['status'] == 'verified':
            assert c['evidence_ids'] and all(evidence[eid]['kind'] != 'documentation' for eid in c['evidence_ids'])
    verdicts = {v['claim_id']: v for v in payload['verification']['verdicts']}
    assert set(verdicts) == set(claims)
    for cid, v in verdicts.items():
        assert v['status'] == claims[cid]['status'] and v['evidence_ids'] == claims[cid]['evidence_ids']
    scenes = {s['id']: s for s in payload['storyboard']['scenes']}
    assert len(scenes) == len(payload['storyboard']['scenes'])
    assert set(s['topic'] for s in scenes.values()) == {'purpose','stack','architecture','flow','code','summary'}
    for s in scenes.values():
        assert s['claim_ids'] and all(cid in claims and claims[cid]['status'] != 'unsupported' for cid in s['claim_ids'])
        assert all(eid in evidence for eid in s['evidence_ids'])
        assert set(s['evidence_ids']) == {eid for cid in s['claim_ids'] for eid in claims[cid]['evidence_ids']}
    for sentence in payload['narration']['sentences']:
        assert sentence['scene_id'] in scenes
        if sentence['technical']:
            assert sentence['claim_ids']
        for cid in sentence['claim_ids']:
            assert cid in scenes[sentence['scene_id']]['claim_ids']
            assert claims[cid]['status'] != 'unsupported'
            assert sentence['uncertainty'] == claims[cid]['status']
    symbols = {s['id'] for s in payload['structure']['symbols']}
    for edge in payload['structure']['edges']:
        assert edge['source'] in symbols and edge['target'] in symbols
        assert all(eid in evidence for eid in edge['evidence_ids'])
    for edge in payload['knowledge']['edges']:
        assert edge['source'] in symbols and edge['target'] in symbols
        assert all(cid in claims for cid in edge['claim_ids'])
    assert set(payload['knowledge']['entrypoint_ids']) <= symbols
    audio_payload=payload['audio']
    assert audio_payload['alignment_status']=='illustrative_not_executed'
    sentence_indices=[]
    for sc in audio_payload['scenes']:
        last=0
        for span in sc['sentences']:
            assert span['start_sample']==last
            last=span['end_sample_exclusive']
            sentence_indices.append(span['sentence_index'])
            assert payload['narration']['sentences'][span['sentence_index']]['scene_id']==sc['scene_id']
        assert last/audio_payload['sample_rate']==sc['duration_seconds']
    assert sorted(sentence_indices)==list(range(len(payload['narration']['sentences'])))
    audio = payload['audio']['scenes']
    assert {s['scene_id'] for s in audio} == set(scenes)
    audio_by_id = {s['scene_id']: s for s in audio}
    frame_end = 0
    for scene in payload['render_manifest']['scenes']:
        assert scene['start_frame'] == frame_end
        frame_end = scene['end_frame_exclusive']
        a = audio_by_id[scene['scene_id']]
        assert scene['audio_sha256'] == a['sha256']
        assert scene['end_frame_exclusive'] - scene['start_frame'] == round(a['duration_seconds']*30)
    assert frame_end/30 == sum(s['duration_seconds'] for s in audio) == payload['video']['duration_seconds']
    assert payload['video']['probe_status'] == 'illustrative_not_executed', 'Do not imply an example was rendered'



def validate_director(example, schema):
    for name in ('input','output'):
        contract={**schema,'oneOf':[{'$ref':'#/$defs/'+name}]}
        Draft202012Validator(contract,format_checker=FormatChecker()).validate(example['director_'+name])
    inp=example['director_input'];out=example['director_output']
    by_kind={a['kind']:a for a in example['artifacts']}
    first=example['artifacts'][0]
    for key in ('owner_id','snapshot_id','commit_sha'):assert inp[key]==first[key]
    for kind in ('knowledge','evidence','verification'):assert inp[kind]==by_kind[kind]['payload']
    assert out['narration']==by_kind['narration']['payload']
    assert out['storyboard']['scenes']==by_kind['storyboard']['payload']['scenes']
    for key in ('visual_instructions','citation_mappings'):assert out[key]==by_kind['storyboard']['payload'][key]
    claims={c['id']:c for c in inp['knowledge']['claims']}
    evidence={e['id']:e for e in inp['evidence']['items']}
    allowed=set(inp['allowed_claim_ids'])
    assert allowed and allowed<=set(claims)
    assert all(claims[c]['status']!='unsupported' for c in allowed)
    assert set(inp['selected_evidence_ids'])<=set(evidence)
    assert not allowed.intersection(inp['omitted_claim_ids'])
    scenes={s['id']:s for s in out['storyboard']['scenes']}
    assert set(scenes)=={v['scene_id'] for v in out['visual_instructions']}=={c['scene_id'] for c in out['citation_mappings']}
    assert len(scenes)==len(out['visual_instructions'])==len(out['citation_mappings'])
    for v in out['visual_instructions']+out['citation_mappings']:
        sc=scenes[v['scene_id']]
        assert set(v['claim_ids'])==set(sc['claim_ids'])<=allowed
        expected={e for c in v['claim_ids'] for e in claims[c]['evidence_ids']}
        assert set(v['evidence_ids'])==expected<=set(inp['selected_evidence_ids'])
    for v in out['visual_instructions']:
        nodes={n['id'] for n in v['nodes']}
        assert len(nodes)==len(v['nodes'])
        for n in v['nodes']:assert n['claim_ids'] and set(n['claim_ids'])<=set(v['claim_ids'])
        for e in v['edges']:
            assert e['source'] in nodes and e['target'] in nodes
            assert e['claim_ids'] and set(e['claim_ids'])<=set(v['claim_ids'])
    # Metadata is server-owned; examples must never imply actual GPU execution.
    for a in example['artifacts']:
        m=a['generation_metadata']
        if m is not None:
            assert m['measurement_status']=='illustrative_not_executed'
            assert m['validation_status']=='passed'
            assert (m['adapter_id'] is None)==(m['adapter_sha256'] is None)==(m['training_dataset_version'] is None)
            if a['kind'] in ('storyboard','narration'):
                assert m['base_model_id']=='Qwen/Qwen2.5-Coder-14B-Instruct'
                assert m['gpu_seconds']<=m['inference_duration_seconds']
    assert by_kind['storyboard']['generation_metadata']['release_id']==by_kind['narration']['generation_metadata']['release_id']


def main():
    for name in REQUIRED:
        assert (ROOT/name).is_file(), f'Missing {name}'
    md_files = [ROOT/'README.md', ROOT/'AGENTS.md', *sorted((ROOT/'docs').rglob('*.md'))]
    links = 0
    for path in md_files:
        text = path.read_text(encoding='utf-8')
        assert len(re.findall(r'^```', text, re.M)) % 2 == 0, f'Unbalanced fence: {path}'
        for table in re.findall(r'(?:^\|.*\|\n)+',plain_markdown(text),re.M):
            rows=table.splitlines()
            assert len(rows)>=2 and re.fullmatch(r'\|[ :|\-]+\|',rows[1]), f'Orphan/malformed table: {path}'
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', plain_markdown(text)):
            target = target.strip('<>')
            if urlsplit(target).scheme:
                continue
            filename, _, fragment = unquote(target).partition('#')
            resolved = (path.parent/filename).resolve() if filename else path
            assert resolved.is_relative_to(ROOT), f'Link outside repository: {target}'
            assert resolved.is_file(), f'Broken link in {path.name}: {target}'
            if fragment:
                assert fragment in anchors(resolved), f'Broken anchor in {path.name}: {target}'
            links += 1
        for body in re.findall(r'^```json\s*\n(.*?)^```', text, re.M | re.S):
            json.loads(body)
    json_files = sorted((ROOT/'docs').rglob('*.json'))
    for path in json_files:
        json.loads(path.read_text(encoding='utf-8'))
    # Residual named API references are historical/economic, never normal dependencies.
    for path in md_files:
        if path.name in ('cost-model.md','change-impact.md','phase0-verification.md','phase0-revision-verification.md'):
            continue
        assert not re.search(r'Claude Haiku|Amazon Polly|Polly Neural',path.read_text(encoding='utf-8'),re.I), f'API-centric reference outside labeled comparison/history: {path}'
    assert json.loads((ROOT/'docs/operations/cost-inputs.json').read_text(encoding='utf-8'))['production_strategy']=='self_hosted'
    schema = json.loads((ROOT/'docs/architecture/artifact.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    example = json.loads((ROOT/'docs/architecture/examples/pipeline.json').read_text(encoding='utf-8'))
    validate_example(example, validator)
    ds=json.loads((ROOT/'docs/ai/director.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(ds)
    for part in schema['allOf'][:-1]:
        kind=part['if']['properties']['kind']['const']
        if kind=='storyboard':
            assert part['then']['properties']['payload']['properties']['scenes']==ds['$defs'][kind]['properties']['scenes']
        elif kind in ds['$defs']:assert part['then']['properties']['payload']==ds['$defs'][kind], 'Shared contract drift'
    assert schema['$defs']['visual']==ds['$defs']['visual']
    validate_director(example,ds)
    for mutation in ('unsupported_narration', 'wrong_sha', 'bad_range', 'unsafe_jsx', 'forged_verification', 'wrong_director_sha', 'adapter_without_dataset', 'bad_visual_edge', 'missing_model_digest','unsafe_artifact_command','bad_audio_sample'):

        bad = copy.deepcopy(example)
        if mutation == 'unsupported_narration':
            bad['artifacts'][6]['payload']['sentences'][0]['claim_ids'] = ['c7']
        elif mutation == 'wrong_sha':
            bad['artifacts'][3]['payload']['items'][0]['commit_sha'] = 'b'*40
        elif mutation=='bad_range':
            bad['artifacts'][3]['payload']['items'][0]['end_line'] = 999
        elif mutation=='unsafe_jsx':bad['director_output']['visual_instructions'][0]['jsx']='alert(1)'
        elif mutation=='forged_verification':bad['director_input']['knowledge']['claims'][6]['status']='verified'
        elif mutation=='wrong_director_sha':bad['director_input']['commit_sha']='b'*40
        elif mutation=='adapter_without_dataset':bad['artifacts'][5]['generation_metadata']['adapter_id']='candidate'
        elif mutation=='bad_visual_edge':bad['director_output']['visual_instructions'][3]['edges'][0]['claim_ids']=['c7']
        elif mutation=='missing_model_digest':del bad['artifacts'][5]['generation_metadata']['served_weight_sha256']
        elif mutation=='unsafe_artifact_command':bad['artifacts'][5]['payload']['visual_instructions'][0]['ffmpeg_command']='touch tripwire'
        elif mutation=='bad_audio_sample':bad['artifacts'][7]['payload']['scenes'][0]['sentences'][0]['end_sample_exclusive']=999999
        try:
            validate_example(bad, validator)
            validate_director(bad,ds)
        except (AssertionError, ValidationError):
            pass
        else:
            raise AssertionError(f'Negative contract probe accepted: {mutation}')
    prd = (ROOT/'docs/product/prd.md').read_text(encoding='utf-8')
    roadmap = (ROOT/'docs/delivery/roadmap.md').read_text(encoding='utf-8')
    for req in [f'F-{i:02}' for i in range(1,14)] + [f'N-{i:02}' for i in range(1,9)]:
        assert req in prd and req in roadmap, f'Missing traceability {req}'
    model = (ROOT/'docs/architecture/data-model.md').read_text(encoding='utf-8')
    actual = set(re.findall(r'^\s+(\w+) --> (\w+)\s*$', model, re.M))
    expected = {('queued','running'),('queued','cancelled'),('queued','failed'),('running','retry_wait'),('retry_wait','running'),('running','awaiting_reconciliation'),('awaiting_reconciliation','running'),('running','succeeded'),('running','failed'),('retry_wait','failed'),('awaiting_reconciliation','failed'),('running','cancel_requested'),('retry_wait','cancel_requested'),('awaiting_reconciliation','cancel_requested'),('cancel_requested','cancelled'),('cancel_requested','failed')}
    assert actual == expected, 'State diagram differs from documented transition contract'
    log = subprocess.check_output(['git','log','--all','--format=%an|%ae|%cn|%ce%n%B'], cwd=ROOT, text=True)
    assert not re.search(r'^(?:Co-authored-by|Generated-by):', log, re.M | re.I), 'Unexpected attribution trailer'
    email = subprocess.check_output(['git','config','user.email'],cwd=ROOT,text=True).strip()
    for identity in re.findall(r'^([^|\n]+)\|([^|\n]+)\|([^|\n]+)\|([^|\n]+)$', log, re.M):
        assert identity == ('Stevemeg',email,'Stevemeg',email), f'Unexpected commit identity: {identity}'
    print(f'PASS: {len(REQUIRED)} required paths, {len(md_files)} Markdown files, {links} local links/anchors, {len(json_files)} JSON files')
    print('PASS: schema + 10 synthetic contracts/provenance/timing; 11 rejected mutations + Director safe visual/provenance/input-output contracts; requirement IDs; state diagram transition set; Git identities/trailers')
    print('LIMIT: no application/security/load/media/deployment tests; Mermaid rendering checked separately; source entailment requires later independent audit')


if __name__ == '__main__':
    main()
