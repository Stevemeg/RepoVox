# Cost model and quota policy

Planning estimate as of **2026-10-08**, USD before taxes. No paid account/API call/purchase initiated. [Inputs](cost-inputs.json) · [Calculator](../../tools/cost_model.py) · [Deployment](deployment.md) · [PRD](../product/prd.md)

## Price evidence versus estimates

| Component | Rate used | Evidence/status |
| --- | --- | --- |
| LLM cost candidate Claude Haiku 4.5 | $1/M input tokens, $5/M output tokens | Verified on [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), accessed 2026-10-08. Base uncached rates, no batch/cache discounts assumed. Model availability/quality must be rechecked at integration. |
| TTS cost candidate Polly Neural | $16/M billed characters | Verified on [Polly pricing](https://aws.amazon.com/polly/pricing/), accessed 2026-10-08. Speech marks separately billed; base model does **not** request speech marks. Timing from measured per-scene audio; caption precision evaluated later. |
| Fargate Linux/x86 us-east-1 | $0.000011244/vCPU-second; $0.000001235/GiB-second | Verified from regional worked example on [Fargate pricing](https://aws.amazon.com/fargate/pricing/), accessed 2026-10-08. 20 GiB included ephemeral storage, minimum billing and image-pull duration apply. Not a contractual quote or benchmark. |
| S3 Standard | $0.023/GiB-month; $0.005/1k PUT, $0.0004/1k GET | **Regional planning assumptions**, not verified current rates: [S3 pricing](https://aws.amazon.com/s3/pricing/) inspected 2026-10-08 but regional dynamic tables were not exposed. Recheck official calculator before launch. |
| Internet delivery | $0.09/GiB | **Estimate**, not verified current price: [AWS EC2 transfer pricing](https://aws.amazon.com/ec2/pricing/on-demand/) is the API-host egress reference; region/geography/tier recheck required. No free transfer credit assumed. Private same-region S3→API origin transfer assumed no incremental egress; verify. |
| Remotion automation | $0.01/render, $100/month minimum if company license applies | Verified on [Remotion pricing](https://www.remotion.dev/docs/license/pricing), accessed 2026-10-08. Free license eligibility may apply to ≤3-person organizations under terms. Conservatively reserve paid minimum in all scenarios; owner must verify organization/licensing, not assume “open-source means free”. No purchase now. |
| RDS/Redis/network/auth/backup/monitoring | Fixed allowances below | **Estimates**, not current provider quotes. References: [RDS](https://aws.amazon.com/rds/postgresql/pricing/), [ElastiCache](https://aws.amazon.com/elasticache/pricing/), [VPC](https://aws.amazon.com/vpc/pricing/), [ALB](https://aws.amazon.com/elasticloadbalancing/pricing/), [Cognito](https://aws.amazon.com/cognito/pricing/). Detailed SKU calculator quote required before provisioning. |

Price references are separate from assumed utilization. Provider billed usage is measured later; illustrative numbers cannot establish profitability or production performance.

## Workload and formulas

Base successful video: four minutes (~560 words, 3,500 characters), 720p H.264/AAC ~90 MiB (**0.09 GiB rounded**), three full-video delivery equivalents across playback/download/range requests. Source temporary storage 0.25 GiB for one day; intermediates/audio 0.035 GiB for 30 days; final video 30 days. Steady monthly volume/30-day retention, not indefinite history media storage. Source caps 250 MiB, output cap 150 MiB differ from average assumptions.

Aggregate across inference/verification/storyboard/narration: 60k input + 6k output tokens, including repeated context per call. No token estimate deduced from repository byte size alone. Stage estimate split: inference 30k/2k, verification 15k/1k, storyboard 8k/1.5k, narration 7k/1.5k. Actual provider tokenizer must enforce 120k/12k ceilings. Average analysis/acquisition/AI-wait task time **600 seconds at 1 vCPU/2 GiB**, render+encode **720 seconds at 4 vCPU/8 GiB**, including cold starts/image pulls. These are assumptions to benchmark, not observed speed. 10% extra charged work factor covers failed attempts/repair on LLM/TTS/worker compute; does not assert failures cost only 10% in practice.

For monthly completed videos `N`, attempt factor `a=1.1`, source `Rs`, retained media `V`, intermediates `I`, storage rate `ps`, delivery count `d`, egress rate `pe`:

```text
LLM = (60000 * 1 + 6000 * 5) / 1000000 = $0.090000
TTS = 3500 * 16 / 1000000 = $0.056000
analysis = 600 * (1 * 0.000011244 + 2 * 0.000001235) = $0.0082284
render = 720 * (4 * 0.000011244 + 8 * 0.000001235) = $0.03949632
source_storage = 0.25 * (1/30) * 0.023 = $0.00019167
persistent_storage = (0.09 + 0.035) * (30/30) * 0.023 = $0.002875
delivery = 0.09 * 3 * 0.09 = $0.024300
requests = (50 * 0.005 + 500 * 0.0004) / 1000 = $0.000450
marginal = a * (LLM + TTS + analysis + render)
           + source_storage + persistent_storage + delivery + requests
         = $0.2409138587/video
fixed_compute = 730 * 3600 * (allocated_vCPU * cpu_rate + allocated_GiB * memory_rate)
license = max(100, N * a * 0.01)
monthly_total = production_fixed + license + N * marginal + staging
reserved_budget = monthly_total * 1.20
fully_allocated_per_video = monthly_total / N
```

Worker compute is on-demand, separately counted per video; not counted twice as always-on infrastructure. API media route meters byte-range transfer, capped at three output-size equivalents/job by default; each stream reserves bytes before S3 fetch. Repeat/grant replay still counts. Reject extra delivery after cap; owner can grant extra only with new budget. API/control fixed compute allowances include signed streaming at assumed bandwidth, not dedicated delivery service; benchmark against burst limits before launch. 50 PUT and 500 GET/video includes artifacts/checks/ranges; temporary multipart uploads require cleanup. Network allowance includes proxy/NAT/endpoint data overhead; free tiers, discounts and credits ignored.

## Monthly scenarios

| Cost allowance | 100 videos | 1,000 videos | 10,000 videos |
| --- | --- | --- | --- |
| Frontend/API + dispatcher/proxy compute | $90.10 | $90.10 | $180.20 |
| Managed PostgreSQL incl HA/storage | $120 | $160 | $300 |
| Managed Redis primary/replica | $60 | $90 | $180 |
| ALB/NAT/endpoints/proxy data/IP | $160 | $180 | $260 |
| Logs/metrics/traces | $20 | $35 | $90 |
| Auth/secrets/DNS | $15 | $30 | $80 |
| Backup allowance | $20 | $30 | $60 |
| Staging (separate allowance) | $100 | $100 | $150 |

Fixed SKU allowances are estimates and may be too low for regional HA/endpoints/traffic; before production require calculator quote. Staging allowance assumes reduced/scheduled capacity and mocks, not a second full production deployment. MAU assumptions 100/1,000/5,000 respectively; auth allowance must be replaced with selected Cognito tier pricing. 10k scenario doubles web/control resources and proposes eight analysis/eight render slots **only after** reviewed scaling approval. Launch remains two/two.

<!-- Reproduced by tools/cost_model.py; do not hand-edit values. -->
| Videos/month | Production fixed | Remotion license | Variable | Staging | Total/month | With 20% reserve | Allocated/video | Reserved/video |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 100 | $485.10 | $100.00 | $24.09 | $100.00 | $709.19 | $851.03 | $7.09 | $8.51 |
| 1,000 | $615.10 | $100.00 | $240.91 | $100.00 | $1,056.01 | $1,267.22 | $1.06 | $1.27 |
| 10,000 | $1,150.20 | $110.00 | $2,409.14 | $150.00 | $3,819.34 | $4,583.21 | $0.38 | $0.46 |

Run `python tools/cost_model.py --check` to reproduce table; `--json` prints unrounded components/utilization. Average render capacity utilization: 1.5% / 15.1% / 37.7%; analysis 1.3% / 12.6% / 31.4%. These do not prove p95 latency under burst load. At 10k, launch two render slots would exceed average capacity (~151%); scale or admit fewer jobs. Keep target average utilization <50%, bounded queues and a benchmarked admission envelope. DB/Redis/storage rows increase by scenario, not a linear extrapolation of only tokens.

Sensitivity: doubling input/output tokens adds $0.099/video after retry factor; doubling render time adds $0.04345; moving 30→90-day media retention adds ~$0.00575; three→ten delivery equivalents adds ~$0.0567. At 100 videos/month fixed costs dominate. Omits human labor, payment processing (billing deferred), taxes, legal/support, extraordinary abuse and regional outages; these must enter commercial pricing. Illustrative 70% gross-margin price floor = allocated cost / 0.30: ~$23.64 / $3.52 / $1.27/video before omitted business costs. Marginal-only floor ~$0.80 would not cover low-volume fixed costs. No pricing or profitable business claim is approved.

## Cost protection

- Pilot allowlist; proposed 10 videos/month/user and two/day, one active/ten queued; two admissions/minute/user and IP ceiling ten/minute. Global pilot 100 completed videos/month unless owner raises capacity/budget. No unlimited trial or unauthenticated generation.
- Proposed initial infrastructure+usage monthly budget **$1,000** (owner approval required), warning 80%, admission blocked at forecast/reservations 100%. 1k/10k scenarios require new approved monthly budget; not implicit permission to spend.
- Reserve **$1 marginal/job** plus assigned fixed budget before admission under atomic ledger lock. Hard 120k/12k aggregate tokens and 6k TTS chars across attempts; reserve provider max output price before each send. Stage timeouts cap compute, and all attempts share absolute deadline. Unknown provider costs retain worst-case reservation; no automatic escalation/uncertain resubmit.
- Meter streaming delivery: default total three output-size equivalents (≤450 MiB at cap), two simultaneous streams/owner, ≤8 MiB per range request, ≤50 MiB/minute/owner, global media bandwidth ceiling 100 MiB/minute at launch; full downloads chunked by gateway. Reserve response bytes before read, count pessimistically on dropped streams, revoke grants on deletion/logout. Signed URL replay cannot bypass aggregate reservations; DB unavailable means fail closed. Use token-bucket byte-rate enforcement, not request count alone.
- Cache successful paid outputs by owner/SHA/input digest/provider/prompt version; never reuse across tenants or repeated changed HEAD. Fixed templates limit output/compute. Provider account caps are secondary controls, not durable ledger substitutes.
- Reconcile actual billed tokens/chars/task time/storage/egress daily; account-level budget alert and paid-send kill switch. Daily max charged operations/job tracked, anomalies block. Before paid launch benchmark worst-case admitted workload fits $1 reservation; otherwise lower caps or raise owner-approved budget/price.

For V1, operator-funded quotas contain pilot loss; advanced billing deferred. Commercial release needs owner-approved price/plan floors including allocated infrastructure and taxes/fees, not just marginal cost. No automatic purchases, account creation or billing configuration in this phase.
