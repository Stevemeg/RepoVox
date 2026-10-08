"""Phase 0 planning calculator; no APIs or infrastructure operations."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def calculate(inputs):
    c = inputs
    llm = (c['llm_input_tokens'] * c['llm_input_per_million'] +
           c['llm_output_tokens'] * c['llm_output_per_million']) / 1_000_000
    tts = c['tts_characters'] * c['tts_per_million_characters'] / 1_000_000
    analysis = c['analysis_seconds'] * (c['analysis_vcpu'] * c['cpu_per_second'] +
                                      c['analysis_memory_gib'] * c['memory_gib_per_second'])
    render = c['render_seconds'] * (c['render_vcpu'] * c['cpu_per_second'] +
                                  c['render_memory_gib'] * c['memory_gib_per_second'])
    temporary = c['temporary_source_gib'] * c['temporary_source_days'] / 30 * c['storage_per_gib_month']
    persistent = (c['video_gib'] + c['intermediate_gib']) * c['artifact_retention_days'] / 30 * c['storage_per_gib_month']
    delivery = c['video_gib'] * c['full_delivery_equivalents'] * c['delivery_per_gib']
    requests = (c['puts_per_video'] * c['put_per_1000'] + c['gets_per_video'] * c['get_per_1000']) / 1000
    marginal = (llm + tts + analysis + render) * c['attempt_multiplier'] + temporary + persistent + delivery + requests
    rows = []
    for s in c['scenarios']:
        n = s['videos']
        compute_fixed = c['monthly_hours'] * 3600 * (
            (s['web_vcpu'] + s['control_vcpu']) * c['cpu_per_second'] +
            (s['web_memory_gib'] + s['control_memory_gib']) * c['memory_gib_per_second'])
        fixed = compute_fixed + sum(s[k] for k in ('database', 'redis', 'network', 'observability', 'auth_secrets_dns', 'backups'))
        license_cost = max(c['license_minimum_monthly'], n * c['attempt_multiplier'] * c['license_per_render'])
        variable = n * marginal
        total = fixed + license_cost + variable + s['staging']
        budget = total * (1 + c['contingency_fraction'])
        analysis_util = n * c['analysis_seconds'] * c['attempt_multiplier'] / (c['monthly_hours'] * 3600 * s['analysis_concurrency'])
        render_util = n * c['render_seconds'] * c['attempt_multiplier'] / (c['monthly_hours'] * 3600 * s['render_concurrency'])
        rows.append({'videos': n, 'fixed': fixed, 'license': license_cost, 'variable': variable,
                     'staging': s['staging'], 'total': total, 'budget': budget,
                     'per_video': total/n, 'budget_per_video': budget/n,
                     'analysis_utilization': analysis_util, 'render_utilization': render_util})
    return {'llm': llm, 'tts': tts, 'analysis': analysis, 'render': render,
            'temporary_source': temporary, 'persistent_artifacts': persistent,
            'delivery': delivery, 'requests': requests, 'marginal': marginal, 'scenarios': rows}


def markdown(result):
    lines = ['| Videos/month | Production fixed | Remotion license | Variable | Staging | Total/month | With 20% reserve | Allocated/video | Reserved/video |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for s in result['scenarios']:
        lines.append('| ' + f"{s['videos']:,}" + ' | ' + ' | '.join(
            f"${s[k]:,.2f}" for k in ('fixed', 'license', 'variable', 'staging', 'total', 'budget', 'per_video', 'budget_per_video')) + ' |')
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--check', action='store_true')
    p.add_argument('--json', action='store_true')
    args = p.parse_args()
    c = json.loads((ROOT/'docs/operations/cost-inputs.json').read_text(encoding='utf-8'))
    result = calculate(c)
    table = markdown(result)
    if args.check:
        doc = (ROOT/'docs/operations/cost-model.md').read_text(encoding='utf-8')
        assert table in doc, 'Cost document table differs from calculator'
        assert result['marginal'] < 0.5, 'Base workload exceeds stated marginal target'
        assert all(s['render_utilization'] < 0.5 and s['analysis_utilization'] < 0.5 for s in result['scenarios']), 'Average capacity has insufficient headroom'
        print('PASS: documented cost table, marginal target and average capacity assumptions')
    print(json.dumps(result, indent=2) if args.json else table)


if __name__ == '__main__':
    main()
