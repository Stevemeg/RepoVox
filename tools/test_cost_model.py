"""Offline formula invariants; no GPU benchmark, billing request or application test."""
import copy
import json
import math
import unittest
from pathlib import Path
from cost_model import calculate, fleet, gpu_hours_per_video, break_even, dataset_preparation, evaluation_preparation, research_plan


class CostModelTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((Path(__file__).resolve().parents[1]/'docs/operations/cost-inputs.json').read_text(encoding='utf-8'))

    def test_workload_units_and_attempts(self):
        self.assertAlmostEqual(gpu_hours_per_video(self.c), 308/3600)
        self.assertAlmostEqual(gpu_hours_per_video(self.c,500,15),594/3600)
        self.assertAlmostEqual(gpu_hours_per_video(self.c,2000,60),165/3600)
        c=copy.deepcopy(self.c);c['attempt_multiplier']=2.2
        self.assertAlmostEqual(gpu_hours_per_video(c),2*gpu_hours_per_video(self.c))

    def test_idle_cost_exists_at_zero_volume(self):
        g=fleet(self.c,0)
        self.assertEqual(g['replicas'],1)
        self.assertEqual(g['busy_hours'],0)
        self.assertAlmostEqual(g['cost'],876)
        self.assertGreater(g['idle_cost'],875)

    def test_capacity_boundary_adds_replica(self):
        # Independent integer capacity: loading consumes usable time on every host.
        capacity=math.floor((730*.5-600*4/3600)/(308/3600))
        self.assertEqual(capacity,4258)
        self.assertEqual(fleet(self.c,capacity)['replicas'],1)
        self.assertEqual(fleet(self.c,capacity+1)['replicas'],2)

    def test_busy_load_idle_partition_not_double_billed(self):
        for n in (0,100,1000,10000):
            g=fleet(self.c,n)
            self.assertAlmostEqual(g['busy_hours']+g['load_hours']+g['idle_hours'],g['warm_hours'])
            self.assertAlmostEqual(g['busy_cost']+g['load_cost']+g['idle_cost'],g['cost'])
            self.assertLessEqual(g['utilization'],.5)

    def test_scenario_totals_and_research_separation(self):
        r=calculate(self.c)
        expected=(1596.957148,1806.842663,4965.598787)
        for s,e in zip(r['scenarios'],expected):
            self.assertAlmostEqual(s['production_total'],e,places=5)
            self.assertAlmostEqual(s['production_total'],s['fixed']+s['gpu']['cost']+s['model_storage']+s['variable']+s['license']+s['staging'])
            self.assertAlmostEqual(s['allocated_per_video']*s['videos'],s['production_total'])
            self.assertAlmostEqual(s['total_with_research']-s['production_total'],r['research']['recurring_monthly'])
            self.assertAlmostEqual(s['reserve'],s['production_total']*1.2)
        self.assertAlmostEqual(r['research_cash'],120*1.59+6*.08+47*.08)
        self.assertAlmostEqual(r['research_monthly'],(120*1.59+6*.08+2143.3333333333+1700)/3+125.6*.023)

    def test_reference_removes_local_tts_gpu_and_model_only(self):
        r=calculate(self.c)
        for s in r['scenarios']:
            difference=s['production_total']-s['api_reference_total']
            expected=s['gpu']['cost']+s['model_storage']+16*1.2+s['videos']*(r['tts']*1.1-r['api_llm_per_video']-r['api_tts_per_video'])
            self.assertAlmostEqual(difference,expected)

    def test_break_even_capacity_conditions(self):
        for u in (.25,.5,.8):
            a=break_even(self.c,1.2,u)
            self.assertEqual(a['unconstrained_crossover_videos'],8928)
            self.assertIsNone(a['feasible_crossover_videos'])
        self.assertIsNone(break_even(self.c,.49,.25)['feasible_crossover_videos'])
        self.assertEqual(break_even(self.c,.49,.5)['feasible_crossover_videos'],3692)
        self.assertEqual(break_even(self.c,.49,.8)['feasible_crossover_videos'],3692)

    def test_loading_and_throughput_sensitivity(self):
        c=copy.deepcopy(self.c);c['model_load_seconds']=0
        self.assertGreater(break_even(c,.49,.5)['capacity_videos'],break_even(self.c,.49,.5)['capacity_videos'])
        c['decode_tokens_per_second']=15
        self.assertGreater(fleet(c,10000)['replicas'],fleet(self.c,10000)['replicas'])

    def test_invalid_rates_capacity_and_budget_inputs(self):
        for u in (0,-.1,1.01):
            with self.assertRaises(ValueError):fleet(self.c,100,u)
        for n in (-1,):
            with self.assertRaises(ValueError):fleet(self.c,n)
        with self.assertRaises(ValueError):fleet(self.c,100,rate=-1)
        with self.assertRaises(ValueError):gpu_hours_per_video(self.c,decode=0)
        c=copy.deepcopy(self.c);c['model_load_seconds']=730*3600
        with self.assertRaises(ValueError):fleet(c,100)

    def test_dataset_size_scaling_and_review_floor(self):
        expected=((100,10,100,2143.3333333333),(500,50,100,8076.6666666667),(1000,100,100,15493.3333333333))
        for n,families,reviewed,labor in expected:
            d=dataset_preparation(self.c,n)
            self.assertEqual(d['families'],families);self.assertEqual(d['reviewed_examples'],reviewed)
            self.assertAlmostEqual(d['imputed_labor'],labor)
            self.assertAlmostEqual(d['hours']['annotation'],n*20/60)
            self.assertAlmostEqual(d['hours']['source_verification'],n*15/60)
            self.assertAlmostEqual(d['cash_infrastructure'],(2+n*.04)*.08)
        self.assertEqual(dataset_preparation(self.c,2000)['reviewed_examples'],200)
        self.assertEqual(dataset_preparation(self.c,101)['families'],11)

    def test_annotation_sensitivity_changes_only_writing_time(self):
        b=dataset_preparation(self.c,1000);fast=dataset_preparation(self.c,1000,10);slow=dataset_preparation(self.c,1000,40)
        self.assertAlmostEqual(b['imputed_labor']-fast['imputed_labor'],1000*10/60*20)
        self.assertAlmostEqual(slow['imputed_labor']-b['imputed_labor'],1000*20/60*20)
        for key in ('source_verification','independent_review','provenance','family_rights','preparation'):
            self.assertEqual(b['hours'][key],fast['hours'][key]);self.assertEqual(b['hours'][key],slow['hours'][key])
        self.assertEqual(b['cash_infrastructure'],fast['cash_infrastructure'])

    def test_separate_evaluation_corpus_and_scoring_costs(self):
        e=evaluation_preparation(self.c)
        self.assertEqual(e['heldout']['families'],60);self.assertEqual(e['heldout']['hidden_families'],10)
        self.assertEqual(e['development']['families'],20)
        self.assertAlmostEqual(e['imputed_labor'],10306.6666666667)
        self.assertAlmostEqual(e['heldout']['imputed_labor'],8113.3333333333)
        self.assertAlmostEqual(e['cash_infrastructure'],47*.08)
        self.assertAlmostEqual(e['scoring_labor_per_cycle'],1700)
        c=copy.deepcopy(self.c);c['research']['selected_training_examples']=1000
        self.assertEqual(evaluation_preparation(c),e)

    def test_research_cash_labor_initial_and_recurring_not_mixed(self):
        for n,expected in ((100,14345.04),(500,20279.6533333333),(1000,27697.92)):
            r=research_plan(self.c,n)
            self.assertAlmostEqual(r['initial_total'],expected)
            self.assertAlmostEqual(r['initial_total'],r['initial_cash_infrastructure']+r['initial_imputed_labor'])
            self.assertAlmostEqual(r['initial_cash_infrastructure']-r['recurring_cycle_cash_infrastructure'],r['evaluation']['cash_infrastructure'])
            self.assertAlmostEqual(r['initial_imputed_labor']-r['recurring_cycle_imputed_labor'],r['evaluation']['imputed_labor'])
        self.assertAlmostEqual(research_plan(self.c)['recurring_monthly'],1347.7599111111)

    def test_zero_datasets_and_zero_corpus(self):
        d=dataset_preparation(self.c,0)
        for k in ('families','reviewed_examples','human_hours','imputed_labor','cpu_hours','cash_infrastructure','storage_gib','storage_monthly'):
            self.assertEqual(d[k],0)
        c=copy.deepcopy(self.c)
        for key in ('development_families','heldout_families','hidden_families','adversarial_variants'):c['research']['evaluation_corpus'][key]=0
        c['research']['selected_training_examples']=0
        e=evaluation_preparation(c)
        self.assertEqual(e['imputed_labor'],0);self.assertEqual(e['cash_infrastructure'],0)
        r=research_plan(c)
        for k in ('initial_total','initial_cash_infrastructure','initial_imputed_labor','recurring_monthly','storage_monthly'):self.assertEqual(r[k],0)
        # Empty training alone does not remove independently prepared evaluation costs.
        self.assertGreater(research_plan(self.c,0)['initial_total'],10000)

    def test_invalid_dataset_and_effort_inputs(self):
        for n in (-1,1.5,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):dataset_preparation(self.c,n)
        for minutes in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):dataset_preparation(self.c,100,minutes)
        for key,val in (('examples_per_family',0),('review_fraction',1.1),('source_verification_minutes',-1),('minimum_reviewed_examples',-1)):
            c=copy.deepcopy(self.c);c['research']['dataset'][key]=val
            with self.assertRaises(ValueError):dataset_preparation(c,100)
        for key,val in (('hidden_families',61),('heldout_families',-1),('family_annotation_minutes',0)):
            c=copy.deepcopy(self.c);c['research']['evaluation_corpus'][key]=val
            with self.assertRaises(ValueError):evaluation_preparation(c)
        c=copy.deepcopy(self.c);c['research']['repeat_every_months']=0
        with self.assertRaises(ValueError):research_plan(c)



if __name__=='__main__':unittest.main()
