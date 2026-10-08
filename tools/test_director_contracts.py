"""Phase 0 synthetic contract tests, not production inference/restart tests."""
import copy
import json
import unittest
from pathlib import Path
from jsonschema import ValidationError
from director_contract_checks import assemble_stage10, validate, validate_director, validate_usage

ROOT=Path(__file__).resolve().parents[1]


class DirectorContractsTests(unittest.TestCase):
    def setUp(self):
        self.e=json.loads((ROOT/'docs/architecture/examples/pipeline.json').read_text(encoding='utf-8'))
        self.s=json.loads((ROOT/'docs/ai/director.schema.json').read_text(encoding='utf-8'))

    def rejected(self, e):
        with self.assertRaises((AssertionError,ValidationError)):validate_director(e,self.s)

    def test_valid_stage10_stage11_chunks_and_assembled_outputs(self):
        validate_director(self.e,self.s)
        for stage in (10,11):
            for c in self.e[f'director_stage{stage}_chunks']:validate(self.s,f'stage{stage}_chunk',c)
            validate(self.s,f'stage{stage}_output',self.e[f'director_stage{stage}_output'])

    def test_wrong_stage_chunks_and_final_outputs(self):
        for a,b in ((10,11),(11,10)):
            for kind in ('chunk','output'):
                value=self.e[f'director_stage{b}_chunks'][0] if kind=='chunk' else self.e[f'director_stage{b}_output']
                with self.assertRaises(ValidationError):validate(self.s,f'stage{a}_{kind}',value)

    def test_stage10_missing_claim(self):
        self.e['director_stage10_chunks'][0]['storyboard']['scenes'][0]['claim_ids']=[]
        self.rejected(self.e)

    def test_stage11_missing_claim(self):
        self.e['director_stage11_chunks'][0]['narration']['sentences'][0]['claim_ids']=[]
        self.rejected(self.e)

    def test_duplicate_scene_rejected(self):
        c=self.e['director_stage10_chunks'][0];c['storyboard']['scenes'].append(copy.deepcopy(c['storyboard']['scenes'][0]))
        self.rejected(self.e)

    def test_unsafe_visual_code_url_and_command_fields(self):
        for field in ('jsx','asset_url','ffmpeg_command'):
            e=copy.deepcopy(self.e);e['director_stage10_chunks'][0]['visual_instructions'][0][field]='untrusted'
            self.rejected(e)

    def test_stage11_cannot_emit_visuals(self):
        self.e['director_stage11_chunks'][0]['visual_instructions']=[]
        self.rejected(self.e)

    def test_missing_and_duplicate_completed_chunks(self):
        for key in ('director_stage10_chunks','director_stage11_chunks'):
            e=copy.deepcopy(self.e);e[key].pop();self.rejected(e)
            e=copy.deepcopy(self.e);e[key][-1]=copy.deepcopy(e[key][0]);self.rejected(e)

    def test_immutable_completed_chunks_assemble_in_delivery_independent_order(self):
        before=copy.deepcopy(self.e['director_stage10_chunks'])
        self.e['director_stage10_chunks'].reverse();self.e['director_stage11_chunks'].reverse()
        validate_director(self.e,self.s)
        self.assertEqual(assemble_stage10(self.e,self.s),self.e['director_stage10_output'])
        self.assertEqual(self.e['director_stage10_chunks'],list(reversed(before)))

    def test_tampered_completed_chunk_manifest(self):
        self.e['director_stage10_output']['assembly']['chunk_digests'][0]['sha256']='f'*64
        self.rejected(self.e)

    def test_citation_or_uncertainty_upgrade_rejected(self):
        e=copy.deepcopy(self.e);e['director_stage10_chunks'][1]['citation_mappings'][0]['claim_bindings'][0]['status']='verified';self.rejected(e)
        e=copy.deepcopy(self.e);e['director_stage11_chunks'][1]['narration']['sentences'][0]['uncertainty']='verified';self.rejected(e)
        e=copy.deepcopy(self.e);e['director_stage11_chunks'][0]['narration']['sentences'][0]['evidence_ids']=['e6'];self.rejected(e)

    def test_stage11_wrong_storyboard_digest(self):
        self.e['director_stage11_chunks'][0]['storyboard_digest']='f'*64
        self.rejected(self.e)

    def test_invented_claim_and_wrong_topic_chunk(self):
        e=copy.deepcopy(self.e);e['director_stage10_chunks'][0]['storyboard']['scenes'][0]['claim_ids']=['invented'];self.rejected(e)
        e=copy.deepcopy(self.e);e['director_stage10_chunks'][0]['storyboard']['scenes'][0]['topic']='flow';self.rejected(e)

    def test_one_failed_call_and_completed_chunk_resume_within_budget(self):
        failed=copy.deepcopy(self.e['director_usage_receipts'][1])
        failed.update(operation_id='failed-within-budget',status='failed',input_tokens=500,
                      output_tokens=0,duration_seconds=10,gpu_seconds=5)
        self.e['director_usage_receipts'][2]['stage_attempt']=2
        self.e['director_usage_receipts'].append(failed)
        m=next(a for a in self.e['artifacts'] if a['kind']=='storyboard')['generation_metadata']
        m.update(input_tokens=30500,inference_duration_seconds=160,gpu_seconds=140)
        validate_director(self.e,self.s)

    def test_failed_replay_calls_count_against_stage_budget(self):
        for i in (1,2):
            r=copy.deepcopy(self.e['director_usage_receipts'][0]);r.update(operation_id='failed-'+str(i),status='failed',stage_attempt=2)
            self.e['director_usage_receipts'].append(r)
        with self.assertRaises(AssertionError):validate_usage(self.e,self.s)

    def test_stage_attempt_time_budget(self):
        for r in self.e['director_usage_receipts']:
            r.update(duration_seconds=121, gpu_seconds=100)
        with self.assertRaises(AssertionError):validate_usage(self.e,self.s)

    def test_context_and_cumulative_output_gpu_caps(self):
        e=copy.deepcopy(self.e);e['director_usage_receipts'][0]['input_tokens']=12289
        with self.assertRaises(ValidationError):validate_usage(e,self.s)
        e=copy.deepcopy(self.e)
        for r in e['director_usage_receipts']:r['output_tokens']=3000
        with self.assertRaises(AssertionError):validate_usage(e,self.s)
        e=copy.deepcopy(self.e)
        for stage in ('storyboard','narration'):
            r=copy.deepcopy(e['director_usage_receipts'][0]);r.update(operation_id=stage+'-failed',stage=stage,status='failed',stage_attempt=2)
            e['director_usage_receipts'].append(r)
        for stage in ('storyboard','narration'):
            rs=[r for r in e['director_usage_receipts'] if r['stage']==stage]
            for i,r in enumerate(rs):r.update(gpu_seconds=151,duration_seconds=151,stage_attempt=1 if i<2 else 2)
        with self.assertRaises(AssertionError):validate_usage(e,self.s)


if __name__=='__main__':unittest.main()
