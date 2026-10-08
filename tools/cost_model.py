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


def number(value, name, *, positive=False, integer=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be finite numeric')
    if value < 0 or (positive and value == 0) or (integer and int(value) != value):
        raise ValueError(f'Invalid {name}')
    return value


def dataset_preparation(c, examples, annotation_minutes=None):
    """Licensed training examples only. Zero examples incur zero preparation; no GPU work."""
    number(examples,'examples',integer=True)
    r=c['research'];d=r['dataset']
    for key in ('examples_per_family','minimum_reviewed_examples'):
        number(d[key],key,positive=True,integer=True)
    for key in ('annotation_minutes','source_verification_minutes','provenance_minutes','family_rights_minutes','independent_review_minutes'):
        number(d[key],key,positive=True)
    for key in ('preparation_setup_hours','cpu_setup_hours','cpu_hours_per_example','storage_gib_per_example','storage_gib_per_family','manifest_gib'):
        number(d[key],key)
    number(d['review_fraction'],'review_fraction',positive=True)
    if d['review_fraction']>1:raise ValueError('review_fraction must be <=1')
    for v,k in ((r['annotator_hourly'],'annotator_hourly'),(r['independent_reviewer_hourly'],'independent_reviewer_hourly'),(r['dataset_cpu_hourly'],'dataset_cpu_hourly'),(c['storage_per_gib_month'],'storage_rate')):number(v,k)
    minutes=d['annotation_minutes'] if annotation_minutes is None else annotation_minutes
    number(minutes,'annotation_minutes',positive=True)
    families=math.ceil(examples/d['examples_per_family'])
    reviewed=min(examples,max(d['minimum_reviewed_examples'],math.ceil(examples*d['review_fraction']))) if examples else 0
    hours={'annotation':examples*minutes/60,'source_verification':examples*d['source_verification_minutes']/60,
           'provenance':examples*d['provenance_minutes']/60,'family_rights':families*d['family_rights_minutes']/60,
           'independent_review':reviewed*d['independent_review_minutes']/60,
           'preparation':d['preparation_setup_hours'] if examples else 0}
    labor={k:v*(r['independent_reviewer_hourly'] if k=='independent_review' else r['annotator_hourly']) for k,v in hours.items()}
    cpu=d['cpu_setup_hours']+examples*d['cpu_hours_per_example'] if examples else 0
    gib=examples*d['storage_gib_per_example']+families*d['storage_gib_per_family']+(d['manifest_gib'] if examples else 0)
    return dict(examples=examples,families=families,reviewed_examples=reviewed,annotation_minutes=minutes,
                hours=hours,human_hours=sum(hours.values()),labor_components=labor,imputed_labor=sum(labor.values()),
                cpu_hours=cpu,cash_infrastructure=cpu*r['dataset_cpu_hourly'],storage_gib=gib,storage_monthly=gib*c['storage_per_gib_month'])


def evaluation_preparation(c):
    """Independent pre-baseline corpus; cannot be substituted by training examples."""
    r=c['research'];e=r['evaluation_corpus']
    for k in ('development_families','heldout_families','hidden_families','adversarial_variants','scored_models_per_cycle'):
        number(e[k],k,integer=True)
    if e['hidden_families']>e['heldout_families']:raise ValueError('Hidden families must be within heldout pool')
    for k,v in e.items():
        if k not in ('development_families','heldout_families','hidden_families','adversarial_variants','scored_models_per_cycle'):
            number(v,k,positive=k.endswith('_minutes'))
    for v,k in ((r['annotator_hourly'],'annotator_hourly'),(r['independent_reviewer_hourly'],'reviewer_rate'),(r['dataset_cpu_hourly'],'cpu_rate'),(c['storage_per_gib_month'],'storage_rate')):number(v,k)
    dev=e['development_families'];test=e['heldout_families'];families=dev+test;variants=e['adversarial_variants']
    if variants and not test:raise ValueError('Variants require heldout families')
    def pool(n, variant_n, hidden_n, share):
        hours={'annotation':(n*e['family_annotation_minutes']+variant_n*e['variant_annotation_minutes'])/60,
               'source_verification':(n*e['family_source_verification_minutes']+variant_n*e['variant_source_verification_minutes'])/60,
               'independent_review':(n*e['family_independent_review_minutes']+variant_n*e['variant_independent_review_minutes'])/60,
               'rights':n*e['family_rights_minutes']/60,
               'preparation':(n*e['family_preparation_minutes']+variant_n*e['variant_preparation_minutes'])/60+e['preparation_setup_hours']*share,
               'hidden_creation':hidden_n*e['hidden_creation_minutes']/60}
        labor=sum(v*(r['independent_reviewer_hourly'] if k=='independent_review' else r['annotator_hourly']) for k,v in hours.items())
        cpu=n*e['cpu_hours_per_family']+variant_n*e['cpu_hours_per_variant']+e['cpu_setup_hours']*share
        gib=n*e['storage_gib_per_family']+variant_n*e['storage_gib_per_variant']+e['manifest_gib']*share
        return dict(families=n,variants=variant_n,hidden_families=hidden_n,hours=hours,human_hours=sum(hours.values()),
                    imputed_labor=labor,cpu_hours=cpu,cash_infrastructure=cpu*r['dataset_cpu_hourly'],storage_gib=gib,storage_monthly=gib*c['storage_per_gib_month'])
    development=pool(dev,0,0,dev/families if families else 0)
    heldout=pool(test,variants,e['hidden_families'],test/families if families else 0)
    scoring=(test*e['scoring_minutes_per_family_per_model']+variants*e['scoring_minutes_per_variant_per_model'])*e['scored_models_per_cycle']/60
    return dict(development=development,heldout=heldout,imputed_labor=development['imputed_labor']+heldout['imputed_labor'],
                human_hours=development['human_hours']+heldout['human_hours'],cash_infrastructure=development['cash_infrastructure']+heldout['cash_infrastructure'],
                storage_gib=development['storage_gib']+heldout['storage_gib'],storage_monthly=development['storage_monthly']+heldout['storage_monthly'],
                scoring_hours_per_cycle=scoring,scoring_labor_per_cycle=scoring*r['independent_reviewer_hourly'])


def research_plan(c, examples=None):
    r=c['research'];examples=r['selected_training_examples'] if examples is None else examples
    for k in ('training_gpu_hours','evaluation_gpu_hours','gpu_hourly','checkpoint_gib'):number(r[k],k)
    number(r['repeat_every_months'],'repeat_every_months',positive=True)
    dataset=dataset_preparation(c,examples);ev=evaluation_preparation(c)
    training_gpu=r['training_gpu_hours']*r['gpu_hourly'] if examples else 0
    eval_gpu=r['evaluation_gpu_hours']*r['gpu_hourly'] if ev['development']['families']+ev['heldout']['families'] else 0
    recurring_cash=training_gpu+eval_gpu+dataset['cash_infrastructure']
    # Gold corpus prepared once; periodic scoring remains a new cost on every model cycle.
    recurring_labor=dataset['imputed_labor']+ev['scoring_labor_per_cycle']
    initial_cash=recurring_cash+ev['cash_infrastructure']
    initial_labor=recurring_labor+ev['imputed_labor']
    checkpoint_storage=r['checkpoint_gib']*c['storage_per_gib_month'] if examples else 0
    storage=dataset['storage_monthly']+ev['storage_monthly']+checkpoint_storage
    return dict(dataset=dataset,evaluation=ev,training_gpu_cash=training_gpu,evaluation_gpu_cash=eval_gpu,
                initial_cash_infrastructure=initial_cash,initial_imputed_labor=initial_labor,
                initial_total=initial_cash+initial_labor,recurring_cycle_cash_infrastructure=recurring_cash,
                recurring_cycle_imputed_labor=recurring_labor,storage_monthly=storage,
                recurring_monthly=(recurring_cash+recurring_labor)/r['repeat_every_months']+storage)


def calculate(c):
    def cpu(prefix):
        return c[prefix+'_seconds']*(c[prefix+'_vcpu']*c['cpu_per_second'] + c[prefix+'_memory_gib']*c['memory_gib_per_second'])
    analysis, orchestration, tts, render = [cpu(p) for p in ('analysis','orchestration','tts','render')]
    temporary = c['temporary_source_gib']*c['temporary_source_days']/30*c['storage_per_gib_month']
    artifacts = (c['video_gib']+c['intermediate_gib'])*c['artifact_retention_days']/30*c['storage_per_gib_month']
    delivery = c['video_gib']*c['full_delivery_equivalents']*c['delivery_per_gib']
    requests = (c['puts_per_video']*c['put_per_1000']+c['gets_per_video']*c['get_per_1000'])/1000
    non_gpu_variable = (analysis+orchestration+tts+render)*c['attempt_multiplier']+temporary+artifacts+delivery+requests
    research=research_plan(c)
    research_cash=research['initial_cash_infrastructure'];research_labor=research['initial_imputed_labor']
    research_storage=research['storage_monthly'];research_monthly=research['recurring_monthly']
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
                research_storage_monthly=research_storage, research_monthly=research_monthly, research=research,
                research_scenarios=[research_plan(c,n) for n in c['research']['training_example_scenarios']],
                annotation_sensitivities=[dict(name=s['name'],scenarios=[dataset_preparation(c,n,s['annotation_minutes']) for n in c['research']['training_example_scenarios']]) for s in c['research']['annotation_sensitivities']],
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


def research_markdown(r):
    lines=['| Training examples | Families | Independently reviewed examples | Preparation hours | Dataset labor | Dataset CPU cash | Initial research cash | Initial research labor | Initial total |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for s in r['research_scenarios']:
        d=s['dataset']
        lines.append(f"| {d['examples']:,} | {d['families']} | {d['reviewed_examples']} | {d['human_hours']:,.2f} | ${d['imputed_labor']:,.2f} | ${d['cash_infrastructure']:,.2f} | ${s['initial_cash_infrastructure']:,.2f} | ${s['initial_imputed_labor']:,.2f} | ${s['initial_total']:,.2f} |")
    return '\n'.join(lines)


def annotation_markdown(r):
    lines=['| Annotation hypothesis | Minutes/example (writing only) | Labor: 100 examples | Labor: 500 examples | Labor: 1,000 examples |',
           '| --- | --- | --- | --- | --- |']
    for s in r['annotation_sensitivities']:
        ds=s['scenarios'];lines.append(f"| {s['name']} | {ds[0]['annotation_minutes']} | "+' | '.join(f"${d['imputed_labor']:,.2f}" for d in ds)+' |')
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--json',action='store_true');a=p.parse_args()
    c=json.loads((ROOT/'docs/operations/cost-inputs.json').read_text(encoding='utf-8'));r=calculate(c);table=markdown(r)
    if a.check:
        doc=(ROOT/'docs/operations/cost-model.md').read_text(encoding='utf-8')
        assert research_markdown(r) in doc and annotation_markdown(r) in doc, 'Research tables differ'
        assert table in (ROOT/'docs/operations/cost-model.md').read_text(encoding='utf-8'), 'Document table differs'
        for s in r['scenarios']:
            g=s['gpu'];assert math.isclose(g['warm_hours'],g['busy_hours']+g['load_hours']+g['idle_hours'])
            assert g['utilization']<=c['target_gpu_utilization']+1e-9
            assert all(s[k]<0.5 for k in ('analysis_utilization','orchestration_utilization','tts_utilization','render_utilization'))
        print('PASS: research/dataset/annotation tables, self-hosted table, GPU busy/load/idle partition, fleet sizing and CPU capacity; no API-cheaper target')
    print(json.dumps(r,indent=2) if a.json else table+"\n\n"+research_markdown(r)+"\n\n"+annotation_markdown(r))


if __name__=='__main__':main()
