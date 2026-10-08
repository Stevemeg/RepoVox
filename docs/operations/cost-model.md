# Self-hosted production and research cost model

Planning revision, 2026-10-08. USD, 730-hour month, no tax/discount/credits. This replaces the previous API-centric approximately $0.24 marginal estimate; that number is historical and is not the revised product cost. No GPU was benchmarked, rented or provisioned. [Inputs](cost-inputs.json) and [offline calculator](../../tools/cost_model.py) are authoritative arithmetic; workload and unquoted prices are estimates. [Deployment](deployment.md) | [Training](../ai/training-strategy.md)

## Prices and assumptions

| Input | Value and evidence/status as of 2026-10-08 |
| --- | --- |
| AWS g6.2xlarge/L4 GPU host | **$1.20/hour unverified planning allowance**, including host CPU/RAM; obtain regional on-demand quote before provisioning. [G6 hardware](https://aws.amazon.com/ec2/instance-types/g6/) and [ECS GPU support](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-gpu.html) establish capability, not this price. |
| Dedicated GPU alternative | Runpod Secure Cloud L4 **$0.49/hour published list**, A40 also $0.49, A100 80GB $1.59; L4 serverless $0.69/hour shown. [Official price page](https://www.runpod.io/pricing), accessed 2026-10-08. Availability, disks, private networking and terms require a quote; not purchased. |
| CPU tasks | Fargate Linux/x86 us-east-1 reference $0.000011244/vCPU-second + $0.000001235/GiB-second; [official pricing](https://aws.amazon.com/fargate/pricing/). Region is provisional. Task launch minimums included conservatively in workload seconds. |
| Storage/requests | S3 Standard reference $0.023/GiB-month, PUT $0.005/1k, GET $0.0004/1k from [S3 pricing](https://aws.amazon.com/s3/pricing/); planning approximation uses GiB consistently though billing unit conversion must be quoted. Disk $0.08/GiB-month and outbound $0.09/GiB are unverified allowances; no free tier assumed. |
| License reserve | Remotion $100/month minimum or $0.01/render, [license pricing](https://www.remotion.dev/docs/license/pricing), reserve despite possible solo eligibility; exact eligibility must be reviewed. FFmpeg build obligations separately reviewed. |
| API economic reference ONLY | Claude Haiku 4.5 $1/M input, $5/M output [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing); Polly Neural $16/M characters [Polly pricing](https://aws.amazon.com/polly/pricing/). Not selected production dependencies, no external calls authorized. Tokenization/quality differences mean not an equivalent-quality benchmark. |
| Fixed SaaS | DB/Redis/network/observability/auth/backups and staging CPU are scenario allowances in JSON, **not verified vendor quotes**. Network allowance includes ALB/NAT/endpoints/internal transfers; avoid double counting video egress, priced separately. |

Normal four-minute, 720p video: 60,000 aggregate input and 6,000 output tokens across at most six calls; prefill 1,000 tokens/s, decode 30 tokens/s **unmeasured aggregate GPU rates**, not per-request rates multiplied by concurrency. One active sequence/GPU. Overhead 20s/video; 1.1 attempt multiplier covers expected failures/repair across compute and reference APIs, not a guaranteed failure distribution. Hard budgets are higher than typical workloads.

CPU Director orchestration 320 task-seconds at 1 vCPU/2 GiB (including inference wait; only launch after GPU slot reserved). Static analysis 600 task-seconds at 1 vCPU/2 GiB, CPU TTS 120s at 2/4 (3,500 chars, ~240s audio, CPU speed unmeasured), render+encode 720s at 4/8. Temporary source 0.25 GiB for one day; final video 0.09 GiB plus 0.035 GiB intermediates retained 30 days. Three full-delivery equivalents/video, 50 PUT and 500 GET. Request costs include bounded range reads, not unlimited replay. Model object allowance 60 GiB includes pinned base/quantized/adapter/TTS manifests; 80 GiB disk per GPU. Store actual file sizes after packaging; double-size rollback capacity needs quote.

## Reproducible formulas

`h = (input_tokens / prefill_rate + output_tokens / decode_rate + overhead_seconds) * attempt_multiplier / 3600 = 0.08555556 GPU-hours/video` (308 GPU-seconds). Base, slow (500/15), fast (2000/60) rates yield 0.085556, 0.165000, 0.045833 h respectively. These are hypotheses; no throughput result is claimed.

`L = load_seconds * reloads_per_GPU_month / 3600 = 0.666667 h/GPU` (four 600s loads). `replicas = max(1, ceil(N*h / (730*target_utilization - L)))`, default utilization ceiling 50%. `warm_hours = replicas*730`, `busy=N*h`, `load=replicas*L`, `idle=warm-busy-load`. Pay **all** warm hours, not busy hours divided by concurrency. Warm capacity limits, queue bursts and cold loading still require load tests. Load costs are already inside warm cost, not added again. Staging adds 16 GPU-hours/month at the same rate; it must boot/load within those paid hours.

CPU unit cost: `seconds*(vCPU*CPU_rate + GiB*RAM_rate)`. Multiply expected attempts once. Non-GPU variable/video = CPU analysis+Director orchestration+TTS+render with attempts + temporary storage + retained artifacts + delivery + requests = **$0.08876168**. GPU busy allocation at $1.20/hour is $0.10266667/video; this excludes idle, models and fixed services and is **not** whole product unit cost.

`production_total = fixed_CPU_SaaS + warm_GPU + model_object_and_disks + N*non_GPU_variable + max(100, N*1.1*0.01) + staging`. Allocated/video is production_total/N. Reserve = production_total*1.20, not an incurred bill. CPU scenario slots keep average utilization below 50%; bursts are admission-controlled. A one-GPU floor remains expensive at low volume even with no jobs.

## Monthly production scenarios

| Videos/month | GPU replicas | Warm GPU | Fixed SaaS | Models/disk | Other variable | License | Staging | Production total | Allocated/video | API reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 100 | 1 | $876.00 | $485.10 | $7.78 | $8.88 | $100.00 | $119.20 | $1,596.96 | $15.97 | $709.68 |
| 1,000 | 1 | $876.00 | $615.10 | $7.78 | $88.76 | $100.00 | $119.20 | $1,806.84 | $1.81 | $1,060.84 |
| 10,000 | 3 | $2,628.00 | $1,150.20 | $20.58 | $887.62 | $110.00 | $169.20 | $4,965.60 | $0.50 | $3,867.61 |

These are modeled totals, not deployment evidence. Rounded table values come directly from the calculator. At 100/1,000/10,000 videos, total GPU busy/load/idle hours are respectively 8.556/0.667/720.778, 85.556/0.667/643.778 and 855.556/2.000/1,332.444. Actual busy+load utilization is 1.26%, 11.81%, 39.16%. Forecast reserves including 20% contingency: **$1,916.35 / $2,168.21 / $5,958.72**. Fixed SaaS grows with traffic and CPU slots; three GPUs at 10k are a planning scale scenario, not initial provisioned capacity.

API comparison keeps common SaaS/render/storage/delivery/license/staging CPU, replaces GPU/models/staging GPU and CPU TTS with externally billed LLM/TTS. LLM reference/video $0.099 and TTS $0.0616 including attempts. It excludes research for both strategies. Self-hosting is a privacy/ownership/product strategy; there is no automatic requirement to be cheaper than an external API.

## Research and specialization budget

Separate from production: three 32-hour PEFT trials (96 GPU-hours) plus 16 evaluation GPU-hours on an A100 80GB planning rate $1.59/hour; dataset CPU 40h*$0.08; 80 annotation/review hours*$20/hour opportunity-cost allowance (no contracted labor). Initial cash estimate **$181.28**, labor allowance **$1,600**, combined **$1,781.28**. This is a small pilot, not training from scratch or a promise of a successful adapter. Baseline work is included in evaluation GPU-hours; expansion requires a new budget.

Dataset 100 GiB + checkpoints 100 GiB cost $4.60/month. Repeating that research cycle quarterly yields `(181.28+1600)/3 + 4.60 = $598.36/month` including labor. Production+monthly research allocation at the three volumes: **$2,195.32 / $2,405.20 / $5,563.96**, before contingency. Research need not repeat quarterly; cadence is an illustrative sensitivity. Keep research cash, labor and storage separate in the ledger. Dataset rights/deletion and isolated training compute remain gates even if GPU time is cheap.

## Break-even and utilization sensitivity

Compare **Director LLM only**, with shared TTS/SaaS/render costs canceled: one warm GPU costs `730*hourly + 80*0.08 + 60*0.023`; reference LLM costs `N*0.099`. Integer crossover `ceil(one_GPU_fixed / 0.099)` must fit `floor((730*u - 0.666667)/h)`. This is a one-replica feasibility calculation; another GPU creates a price step and can remove the advantage. No universal linear crossover is asserted.

| GPU hourly assumption | Target utilization ceiling | One-GPU capacity/month | Unconstrained crossover | Feasible before another GPU<= |
| --- | --- | --- | --- | --- |
| AWS allowance $1.20 | 25% | 2,125 | 8,928 | No |
| AWS allowance $1.20 | 50% | 4,258 | 8,928 | No |
| AWS allowance $1.20 | 80% | 6,818 | 8,928 | No |
| Runpod list $0.49 | 25% | 2,125 | 3,692 | No |
| Runpod list $0.49 | 50% | 4,258 | 3,692 | Yes, from 3,692 within one-GPU capacity |
| Runpod list $0.49 | 80% | 6,818 | 3,692 | Yes, within one-GPU capacity |

Throughput, quantization quality, adapter overhead, queue SLA and prompt selection can materially change capacity. Even 100% useful compute at baseline AWS rates costs ~$0.103/video versus $0.099 LLM reference before idle/storage. Faster throughput or lower hourly cost can change this. Serverless/scale-to-zero can reduce idle expense but adds repeated weight loads, minimum billing/storage, private-network constraints and cold-start delays; not assumed free or latency-compliant. More active sequences may improve aggregate rate or worsen VRAM/latency: measure before changing the input.

## Cost protection

Proposed pilot allowlist: global 100 admitted jobs/month, 10/user/month, one active and ten queued/user, one Director request/owner, eight pending engine requests, initial two analysis/TTS/render slots and one warm GPU. Atomic owner/month/job reservations in PostgreSQL, reject before work if unavailable. Admission rate <=5/min/IP and <=2/min/user; capacity gate queue age and 45-minute deadline. Retry/new jobs consume quotas; refunds explicit bounded policy, not unlimited retry loophole.

Per job cumulative <=120k input/12k output, <=1,200 GPU compute-seconds (including repairs/replay), <=6k narration characters and bounded TTS attempts; stage limits in data model remain stricter where applicable. Gateway aborts on remaining GPU/time/token budget; estimate reservations pessimistically until actual usage settles. GPU wall occupancy recorded including partial failed attempts; unknown running inference remains reserved until stopped/reconciled. Completed artifacts prevent repeated inference; no silent paid fallback. CPU/task/time caps and delivery byte quotas prevent unbounded ancillary charges.

Proposed owner-reviewed pilot production budget **$2,000/month** including contingency; independent research pilot budget **$2,500** including labor allowance, both proposals and neither authorization to spend. Warn forecast >=80%, stop new admission at 100%; existing bounded jobs may complete within reservations. Idle capacity is an infrastructure budget, not attributed to one user as marginal usage. Cap autoscaling at one GPU initially, later at three only after approval/quote. Scale-to-zero requires explicit availability trade-off. No pricing plan until allocated hosting, expected usage, support/payment overhead and chosen gross-margin target are signed off; advanced billing deferred.

Delivery: cumulative bytes <=3 final-video sizes/job over retention, <=2 concurrent streams/grant and owner aggregate enforced atomically; range/download replay counts actual bytes, min accounting quantum 64 KiB. Signed grants expire <=5 min and deletion/logout revokes. Failed upstream byte reservation released only on confirmed non-delivery; egress has no free unbounded tier. Bandwidth quota increase requires explicit pricing/budget policy.

## Limits and refresh procedure

Obtain region-specific quotes for EC2/RDS/Redis/ALB/NAT/S3/EBS/Cognito and model/provider license terms before provisioning. Include taxes, payment fees, customer support, extra availability GPU and disaster reserve in commercial pricing; those are excluded from this technical planning estimate. Network/backup allowances may prove low. Dataset licensing/review time may dominate GPU expense. Update JSON with measured aggregate throughput/p95/load durations, repeat offline tests/table generation, attach quote date/region and compare worst-case failed jobs. No benchmark, paid account, GPU run or production deployment was executed here.
