"""Offline synthetic documentation-contract checks; not an inference/job implementation."""
import hashlib
import json
import math
from collections import Counter

from jsonschema import Draft202012Validator, FormatChecker

PLAN = {'purpose_stack': ('purpose', 'stack'),
        'architecture_flow': ('architecture', 'flow'),
        'code_summary': ('code', 'summary')}
TOPICS = tuple(topic for pair in PLAN.values() for topic in pair)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate(schema, name, value):
    contract = {**schema, 'oneOf': [{'$ref': '#/$defs/' + name}]}
    Draft202012Validator(contract, format_checker=FormatChecker()).validate(value)


def contexts(example, schema, stage):
    inputs = example[f'director_stage{stage}_inputs']
    assert len(inputs) == 3
    by_id = {i['chunk_id']: i for i in inputs}
    assert set(by_id) == set(PLAN)
    payloads = {a['kind']: a['payload'] for a in example['artifacts']}
    for inp in inputs:
        validate(schema, f'stage{stage}_input', inp)
        assert inp['input_digest'] == digest({k: v for k, v in inp.items() if k != 'input_digest'})
        for k in ('owner_id', 'snapshot_id', 'commit_sha'):
            assert inp[k] == example['artifacts'][0][k]
        for k in ('knowledge', 'evidence', 'verification'):
            assert inp[k] == payloads[k]
        claims = {c['id']: c for c in inp['knowledge']['claims']}
        allowed = set(inp['allowed_claim_ids'])
        assert allowed and allowed <= set(claims)
        assert all(claims[c]['status'] != 'unsupported' for c in allowed)
        assert set(inp['omitted_claim_ids']) == set(claims) - allowed
        expected = {eid for c in allowed for eid in claims[c]['evidence_ids']}
        assert set(inp['selected_evidence_ids']) == expected
        assert inp['request_limits']['prompt_tokens_max'] + inp['request_limits']['output_tokens_max'] <= inp['request_limits']['context_tokens_max']
    return by_id


def assembly(chunks):
    return {'plan_version': 'topic-pairs-v1', 'chunk_digests': [
        {'chunk_id': cid, 'sha256': digest(chunks[cid])} for cid in PLAN]}


def assemble_stage10(example, schema):
    inputs = contexts(example, schema, 10)
    rows = example['director_stage10_chunks']
    chunks = {c['chunk_id']: c for c in rows}
    assert len(rows) == len(chunks) == 3 and set(chunks) == set(PLAN)
    scenes, visuals, citations = [], [], []
    for cid, topics in PLAN.items():
        chunk, inp = chunks[cid], inputs[cid]
        validate(schema, 'stage10_chunk', chunk)
        assert chunk['input_digest'] == inp['input_digest']
        claims = {c['id']: c for c in inp['knowledge']['claims']}
        allowed = set(inp['allowed_claim_ids'])
        ss = chunk['storyboard']['scenes']
        by_scene = {s['id']: s for s in ss}
        assert len(by_scene) == len(ss) and {s['topic'] for s in ss} == set(topics)
        ordered = []
        for topic in topics:
            group = [s for s in ss if s['topic'] == topic]
            assert 1 <= len(group) <= 4
            assert {s['id'] for s in group} == {f'{topic}-{i}' for i in range(1, len(group) + 1)}
            ordered += [by_scene[f'{topic}-{i}'] for i in range(1, len(group) + 1)]
        vv = {v['scene_id']: v for v in chunk['visual_instructions']}
        cc = {c['scene_id']: c for c in chunk['citation_mappings']}
        assert set(vv) == set(cc) == set(by_scene)
        assert len(vv) == len(chunk['visual_instructions']) and len(cc) == len(chunk['citation_mappings'])
        for sc in ordered:
            sid = sc['id']
            claim_ids = set(sc['claim_ids'])
            assert claim_ids and claim_ids <= allowed
            expected = {eid for c in claim_ids for eid in claims[c]['evidence_ids']}
            assert set(sc['evidence_ids']) == expected <= set(inp['selected_evidence_ids'])
            for v in (vv[sid], cc[sid]):
                assert set(v['claim_ids']) == claim_ids and set(v['evidence_ids']) == expected
            bindings = cc[sid]['claim_bindings']
            assert len(bindings) == len(claim_ids) and {b['claim_id'] for b in bindings} == claim_ids
            for b in bindings:
                c = claims[b['claim_id']]
                assert b['status'] == c['status'] and set(b['evidence_ids']) == set(c['evidence_ids'])
            vis = vv[sid]
            nodes = {n['id'] for n in vis['nodes']}
            assert len(nodes) == len(vis['nodes'])
            for node in vis['nodes']:
                assert set(node['claim_ids']) <= claim_ids
            for edge in vis['edges']:
                assert edge['source'] in nodes and edge['target'] in nodes
                assert set(edge['claim_ids']) <= claim_ids
            scenes.append(sc); visuals.append(vv[sid]); citations.append(cc[sid])
    assert len({s['id'] for s in scenes}) == len(scenes)
    return {'contract_version': '2.1', 'stage': 'storyboard', 'storyboard': {'scenes': scenes},
            'visual_instructions': visuals, 'citation_mappings': citations, 'assembly': assembly(chunks)}


def assemble_stage11(example, schema, storyboard):
    inputs = contexts(example, schema, 11)
    rows = example['director_stage11_chunks']
    chunks = {c['chunk_id']: c for c in rows}
    assert len(rows) == len(chunks) == 3 and set(chunks) == set(PLAN)
    story_digest = digest(storyboard)
    sentences = []
    for cid, topics in PLAN.items():
        chunk, inp = chunks[cid], inputs[cid]
        validate(schema, 'stage11_chunk', chunk)
        assert chunk['input_digest'] == inp['input_digest']
        assert chunk['storyboard_digest'] == inp['storyboard_digest'] == story_digest
        scenes = [s for s in storyboard['scenes'] if s['topic'] in topics]
        assert inp['scene_subset'] == scenes
        assert set(inp['allowed_claim_ids']) == {c for scene in scenes for c in scene['claim_ids']}
        assert inp['citation_subset'] == [c for c in storyboard['citation_mappings'] if c['scene_id'] in {s['id'] for s in scenes}]
        by_scene = {s['id']: s for s in scenes}
        claims = {c['id']: c for c in inp['knowledge']['claims']}
        ss = chunk['narration']['sentences']
        assert {s['scene_id'] for s in ss} == set(by_scene)
        for sentence in ss:
            ids = set(sentence['claim_ids'])
            assert ids <= set(by_scene[sentence['scene_id']]['claim_ids'])
            if sentence['technical']:
                assert ids and all(claims[c]['status'] != 'unsupported' for c in ids)
                assert {claims[c]['status'] for c in ids} == {sentence['uncertainty']}
                assert set(sentence['evidence_ids']) == {eid for c in ids for eid in claims[c]['evidence_ids']}
        for scene in scenes:
            group = [s for s in ss if s['scene_id'] == scene['id']]
            assert any(s['technical'] for s in group)
            sentences.extend(group)  # scene order fixed; within-scene spoken order preserved
    return {'contract_version': '2.1', 'stage': 'narration', 'storyboard_digest': story_digest,
            'narration': {'sentences': sentences}, 'assembly': assembly(chunks)}


def validate_usage(example, schema):
    receipts = example['director_usage_receipts']
    assert len({r['operation_id'] for r in receipts}) == len(receipts)
    attempts = Counter((r['stage'], r['stage_attempt']) for r in receipts)
    assert all(n <= 3 for n in attempts.values())
    for stage_attempt in attempts:
        assert sum(r['duration_seconds'] for r in receipts if (r['stage'],r['stage_attempt']) == stage_attempt) <= 360
    assert sum(r['input_tokens'] for r in receipts) <= 120000
    assert sum(r['output_tokens'] for r in receipts) <= 12000
    assert sum(r['gpu_seconds'] for r in receipts) <= 1200
    for r in receipts:
        validate(schema, 'usage_receipt', r)
        assert r['input_tokens'] + r['output_tokens'] <= 16384
        assert r['gpu_seconds'] <= r['duration_seconds']
        assert r['measurement_status'] == 'illustrative_not_executed'
    artifacts = {a['kind']: a for a in example['artifacts']}
    for stage in ('storyboard', 'narration'):
        rs = [r for r in receipts if r['stage'] == stage]
        assert len(rs) <= 4
        assert {r['chunk_id'] for r in rs if r['status'] == 'completed'} == set(PLAN)
        m = artifacts[stage]['generation_metadata']
        for mk, rk in (('input_tokens','input_tokens'), ('output_tokens','output_tokens'),
                       ('gpu_seconds','gpu_seconds'), ('inference_duration_seconds','duration_seconds')):
            assert math.isclose(m[mk], sum(r[rk] for r in rs))


def validate_director(example, schema):
    out10 = assemble_stage10(example, schema)
    validate(schema, 'stage10_output', out10)
    assert out10 == example['director_stage10_output']
    arts = {a['kind']: a for a in example['artifacts']}
    story = {'scenes': out10['storyboard']['scenes'], **{k: out10[k] for k in ('visual_instructions','citation_mappings','assembly')}}
    assert story == arts['storyboard']['payload']
    out11 = assemble_stage11(example, schema, story)
    validate(schema, 'stage11_output', out11)
    assert out11 == example['director_stage11_output']
    assert {**out11['narration'], **{k: out11[k] for k in ('storyboard_digest','assembly')}} == arts['narration']['payload']
    validate_usage(example, schema)
    for a in example['artifacts']:
        m = a['generation_metadata']
        if m is not None:
            assert m['measurement_status'] == 'illustrative_not_executed' and m['validation_status'] == 'passed'
            assert (m['adapter_id'] is None) == (m['adapter_sha256'] is None) == (m['training_dataset_version'] is None)
    assert arts['storyboard']['generation_metadata']['release_id'] == arts['narration']['generation_metadata']['release_id']
