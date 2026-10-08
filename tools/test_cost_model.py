"""Offline formula invariants; no GPU benchmark, billing request or application test."""
import copy
import json
import math
import unittest
from pathlib import Path
from cost_model import calculate, fleet, gpu_hours_per_video, break_even


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
            self.assertAlmostEqual(s['total_with_research']-s['production_total'],598.36)
            self.assertAlmostEqual(s['reserve'],s['production_total']*1.2)
        self.assertAlmostEqual(r['research_cash'],112*1.59+40*.08)
        self.assertAlmostEqual(r['research_monthly'],(181.28+1600)/3+200*.023)

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


if __name__=='__main__':unittest.main()
