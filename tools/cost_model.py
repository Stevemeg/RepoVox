"""Offline Phase 0 self-hosted cost planning, never a benchmark/provisioner."""
import argparse
import json
import math
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def gpu_hours_per_video(c, prefill=None, decode=None):
    prefill = c['prefill_tokens_per_second'] if prefill is None else prefill
    decode = c['decode_tokens_per_second'] if decode is None else decode
    if prefill <= 0 or decode <= 0 or c['attempt_multiplier'] < 1:
        raise ValueError('Positive throughput and attempt multiplier >=1 required')
    return (c['prompt_tokens']/prefill + c['output_tokens']/decode + c['request_overhead_seconds']) * c['attempt_multiplier']/3600


def fleet(c, n, utilization=None, rate=None):
    u = c['target_gpu_utilization'] if utilization is None else utilization
    r = c['gpu_hourly'] if rate is None else rate
    if not 0 < u <= 1 or r < 0 or n < 0:
        raise ValueError('Invalid fleet inputs')
    busy = n * gpu_hours_per_video(c)
    load_per_gpu = c['model_load_seconds'] * c['reloads_per_gpu_month']/3600
    usable = c['monthly_hours']*u - load_per_gpu
    if usable <= 0:
        raise ValueError('Loading consumes all target capacity')
    replicas = max(1, math.ceil(busy/usable))  # one warm minimum even at zero jobs
    warm = replicas*c['monthly_hours']
    load = replicas*load_per_gpu
    idle = warm-busy-load
    if idle < -1e-8:
        raise ValueError('Negative idle hours: invalid sizing')
    return dict(replicas=replicas, busy_hours=busy, load_hours=load,
                idle_hours=max(0,idle), warm_hours=warm, cost=warm*r,
                utilization=(busy+load)/warm,
                busy_cost=busy*r, load_cost=load*r, idle_cost=max(0,idle)*r)


def break_even(c, hourly, utilization):
    """First integer crossover for ONE warm GPU, capacity-constrained.
    Extra replicas create price steps, so not a universal volume guarantee.
    """
    load = c['model_load_seconds']*c['reloads_per_gpu_month']/3600
    capacity = math.floor((c['monthly_hours']*utilization-load)/gpu_hours_per_video(c))
    reference = (c['prompt_tokens']*c['api_reference']['input_per_million'] + c['output_tokens']*c['api_reference']['output_per_million'])/1e6*c['attempt_multiplier']
    fixed = c['monthly_hours']*hourly + c['gpu_disk_gib']*c['gpu_disk_per_gib_month'] + c['model_object_gib']*c['storage_per_gib_month']
    volume = math.ceil(fixed/reference) if reference > 0 else None
    return dict(gpu_hourly=hourly, target_utilization=utilization,
                capacity_videos=max(0,capacity), unconstrained_crossover_videos=volume,
                feasible_crossover_videos=volume if volume is not None and volume <= capacity else None,
                reason='within one-replica capacity' if volume is not None and volume <= capacity else 'no crossover before capacity requires another replica')


def calculate(c):
    def cpu(prefix):
        return c[prefix+'_seconds']*(c[prefix+'_vcpu']*c['cpu_per_second'] + c[prefix+'_memory_gib']*c['memory_gib_per_second'])
    analysis, orchestration, tts, render = [cpu(p) for p in ('analysis','orchestration','tts','render')]
    temporary = c['temporary_source_gib']*c['temporary_source_days']/30*c['storage_per_gib_month']
    artifacts = (c['video_gib']+c['intermediate_gib'])*c['artifact_retention_days']/30*c['storage_per_gib_month']
    delivery = c['video_gib']*c['full_delivery_equivalents']*c['delivery_per_gib']
    requests = (c['puts_per_video']*c['put_per_1000']+c['gets_per_video']*c['get_per_1000'])/1000
    non_gpu_variable = (analysis+orchestration+tts+render)*c['attempt_multiplier']+temporary+artifacts+delivery+requests
    research = c['research']
    research_cash = (research['training_gpu_hours']+research['evaluation_gpu_hours'])*research['gpu_hourly'] + research['dataset_cpu_hours']*research['dataset_cpu_hourly']
    research_labor = research['annotation_hours']*research['annotation_hourly']
    research_storage = (research['dataset_gib']+research['checkpoint_gib'])*c['storage_per_gib_month']
    research_monthly = (research_cash+research_labor)/research['repeat_every_months']+research_storage
    rows=[]
    api_llm = (c['prompt_tokens']*c['api_reference']['input_per_million']+c['output_tokens']*c['api_reference']['output_per_million'])/1e6*c['attempt_multiplier']
    api_tts = c['narration_characters']*c['api_reference']['tts_per_million_characters']/1e6*c['attempt_multiplier']
    for s in c['scenarios']:
        n=s['videos']; g=fleet(c,n)
        fixed=c['monthly_hours']*3600*((s['web_vcpu']+s['control_vcpu'])*c['cpu_per_second']+(s['web_memory_gib']+s['control_memory_gib'])*c['memory_gib_per_second'])
        fixed+=sum(s[k] for k in ('database','redis','network','observability','auth_secrets_dns','backups'))
        weights=c['model_object_gib']*c['storage_per_gib_month']+g['replicas']*c['gpu_disk_gib']*c['gpu_disk_per_gib_month']
        license_cost=max(c['license_minimum_monthly'],n*c['attempt_multiplier']*c['license_per_render'])
        staging=s['staging_cpu']+c['staging_gpu_hours']*c['gpu_hourly']
        variable=n*non_gpu_variable
        total=fixed+weights+g['cost']+license_cost+staging+variable
        # Economic reference keeps common infrastructure/render/delivery, replaces local model and TTS.
        reference=fixed+license_cost+s['staging_cpu']+variable-n*tts*c['attempt_multiplier']+n*(api_llm+api_tts)
        rows.append(dict(videos=n, fixed=fixed, gpu=g, model_storage=weights, license=license_cost,
                         variable=variable, staging=staging, production_total=total,
                         reserve=total*(1+c['contingency_fraction']), allocated_per_video=total/n,
                         research_monthly=research_monthly, total_with_research=total+research_monthly,
                         api_reference_total=reference,
                         orchestration_utilization=n*c['orchestration_seconds']*c['attempt_multiplier']/(c['monthly_hours']*3600*g['replicas']),
                         analysis_utilization=n*c['analysis_seconds']*c['attempt_multiplier']/(c['monthly_hours']*3600*s['analysis_concurrency']),
                         tts_utilization=n*c['tts_seconds']*c['attempt_multiplier']/(c['monthly_hours']*3600*s['tts_concurrency']),
                         render_utilization=n*c['render_seconds']*c['attempt_multiplier']/(c['monthly_hours']*3600*s['render_concurrency'])))
    return dict(gpu_hours_per_video=gpu_hours_per_video(c), non_gpu_variable=non_gpu_variable,
                analysis=analysis, orchestration=orchestration, tts=tts, render=render, temporary=temporary, artifacts=artifacts,
                delivery=delivery, requests=requests, api_llm_per_video=api_llm, api_tts_per_video=api_tts,
                research_cash=research_cash, research_labor=research_labor,
                research_storage_monthly=research_storage, research_monthly=research_monthly,
                scenarios=rows,
                break_even=[dict(provider=name,**break_even(c,rate,u)) for name,rate in c['gpu_hourly_alternatives'].items() for u in c['break_even_utilizations']],
                sensitivities=[dict(name=s['name'],gpu_hours_per_video=gpu_hours_per_video(c,s['prefill'],s['decode'])) for s in c['throughput_sensitivities']])


def markdown(r):
    lines=['| Videos/month | GPU replicas | Warm GPU | Fixed SaaS | Models/disk | Other variable | License | Staging | Production total | Allocated/video | API reference |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for s in r['scenarios']:
        values=[s['gpu']['cost'],s['fixed'],s['model_storage'],s['variable'],s['license'],s['staging'],s['production_total'],s['allocated_per_video'],s['api_reference_total']]
        lines.append('| '+f"{s['videos']:,}"+' | '+str(s['gpu']['replicas'])+' | '+' | '.join(f'${x:,.2f}' for x in values)+' |')
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--json',action='store_true');a=p.parse_args()
    c=json.loads((ROOT/'docs/operations/cost-inputs.json').read_text(encoding='utf-8'));r=calculate(c);table=markdown(r)
    if a.check:
        assert table in (ROOT/'docs/operations/cost-model.md').read_text(encoding='utf-8'), 'Document table differs'
        for s in r['scenarios']:
            g=s['gpu'];assert math.isclose(g['warm_hours'],g['busy_hours']+g['load_hours']+g['idle_hours'])
            assert g['utilization']<=c['target_gpu_utilization']+1e-9
            assert all(s[k]<0.5 for k in ('analysis_utilization','orchestration_utilization','tts_utilization','render_utilization'))
        print('PASS: self-hosted table, GPU busy/load/idle partition, fleet sizing and CPU capacity; no API-cheaper target')
    print(json.dumps(r,indent=2) if a.json else table)


if __name__=='__main__':main()
