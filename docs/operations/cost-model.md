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

Normal four-minute, 720p video: 60,000 aggregate input and 6,000 output tokens across six normal calls (three per Director stage); up to eight physical calls including the shared failure/repair allowances; prefill 1,000 tokens/s, decode 30 tokens/s **unmeasured aggregate GPU rates**, not per-request rates multiplied by concurrency. One active sequence/GPU. Overhead 20s/video; 1.1 attempt multiplier covers expected failures/repair across compute and reference APIs, not a guaranteed failure distribution. Hard budgets are higher than typical workloads.

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

All times below are **unmeasured planning hypotheses**, not observed annotation throughput or reviewer quotes. Cash infrastructure, imputed human labor and production operations are separate ledger categories. No expenditure or recruitment is authorized. Retire the prior flat 80-hour annotation allowance and $2,500 pilot budget: they omitted independent gold preparation and source/rights review.

Training preparation assumptions: ten examples/repository family; per example 20 minutes authoring labels/storyboard, 15 minutes source-evidence verification and five minutes provenance processing. Rights intake is 45 minutes/family. Independent human review is ten minutes/example for `min(N, max(100, ceil(0.10*N)))`; all 100 pilot examples are reviewed. Shared setup is eight human hours when N>0. Maintainer/annotator opportunity cost is $20/hour and independent review $30/hour; these are imputed values, not cash staffing contracts. Rights intake budgets manifest/license screening; it does not buy permission or substitute for legal review. Unresolved rights exclude a family. Complex evidence, adjudication, rights outreach or counsel can greatly exceed these allowances.

`F=ceil(N/10)`, `R=min(N,max(100,ceil(0.1*N)))` for N>0. `labor = 20*(N*(20+15+5)/60 + F*45/60 + 8) + 30*R*10/60`. Dataset CPU cash = `(2+0.04*N)*$0.08`; storage = `(0.02*N+0.25*F+0.05) GiB*$0.023/month`. At N=0, preparation/review/setup/CPU/storage are zero; invalid counts, nonfinite values, zero timing assumptions and invalid review fractions are rejected by the calculator.

| Activity (human hours) | 100 examples | 500 examples | 1,000 examples |
| --- | --- | --- | --- |
| Annotation | 33.33 | 166.67 | 333.33 |
| Source-evidence verification | 25.00 | 125.00 | 250.00 |
| Per-example provenance | 8.33 | 41.67 | 83.33 |
| Family rights processing | 7.50 | 37.50 | 75.00 |
| Independent example review | 16.67 | 16.67 | 16.67 |
| Setup | 8.00 | 8.00 | 8.00 |

### Independent evaluation corpus (before baseline)

These costs are **additional to training data** and do not scale down when training N=0. The [EVAL-ENTRY corpus](../ai/evaluation-plan.md#evaluation-corpus-preparation-and-freeze) has 20 development and 60 protected held-out families; ten newly authored hidden families are within the 60. One hundred adversarial variants derive from at least twenty held-out families. No evaluation family/descendant enters training or quantization calibration.

Each family: 90 minutes gold authoring, 90 source verification, 60 independent human gold review, 30 rights intake and 20 provenance/preparation. Each variant: ten minutes each authoring/verification/review plus five preparation; rights inherited from parent only after checking scope. Hidden fixture creation adds 60 minutes/hidden family. Shared setup 12 hours, allocated by family count. Human rates match training. CPU = `2 + 0.5*80 + 0.05*100 = 47h` at $0.08/hour. Storage = `0.25*80 + 0.01*100 + 0.05 = 21.05 GiB`. Gold approval covers every family/variant, not merely the later output-scoring sample.

| Gold preparation pool | Human hours | Imputed labor | CPU cash | Storage GiB |
| --- | --- | --- | --- | --- |
| Development: 20 families | 99.67 | $2,193.33 | $0.84 | 5.0125 |
| Held-out: 60 families, 100 variants, ten hidden within 60 | 367.33 | $8,113.33 | $2.92 | 16.0375 |
| Total, prepared once per frozen corpus version | 467.00 | $10,306.67 | $3.76 | 21.05 |

Scoring generated outputs is separate from gold preparation: each model needs 20 reviewer minutes/held-out family and five/variant, covering the rubric's stratified claim/edge checks. Two models (unchanged base and candidate) per cycle: `2*(60*20+100*5)/60 = 56.67h`, **$1,700 imputed labor**. Reserve the two-model cap for baseline plus later comparison; if the unchanged control needs rerunning, add its costs. Gold-review and output-scoring rates are hypotheses; a dry annotation/scoring pilot must validate them before scaling. Independent reviewer is not yet appointed. Human review is distinct from ChatGPT's technical document audit and does not imply another Git contributor.

### Initial and recurring research scenarios

Three 32-hour PEFT trials = 96 GPU-hours; baseline/comparative evaluation cap = 24 GPU-hours, at the separately hosted A100 80GB $1.59/hour planning rate: **$152.64 training + $38.16 evaluation cash**. These caps do not scale automatically with example count or guarantee a successful adapter; revisit after baseline/pilot measurement. Checkpoints reserve 100 GiB when N>0. No training-from-scratch claim.

Initial cash = training/eval GPU + training-preparation CPU + independent-corpus CPU. Initial imputed labor = training preparation + independent gold preparation + output scoring. Initial totals exclude ongoing monthly storage and contingency:

| Training examples | Families | Independently reviewed examples | Preparation hours | Dataset labor | Dataset CPU cash | Initial research cash | Initial research labor | Initial total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 100 | 10 | 100 | 98.83 | $2,143.33 | $0.48 | $195.04 | $14,150.00 | $14,345.04 |
| 500 | 50 | 100 | 395.50 | $8,076.67 | $1.76 | $196.32 | $20,083.33 | $20,279.65 |
| 1,000 | 100 | 100 | 766.33 | $15,493.33 | $3.36 | $197.92 | $27,500.00 | $27,697.92 |

Training dataset storage at 100/500/1,000 examples is 4.55/22.55/45.05 GiB ($0.10/$0.52/$1.04 monthly). Independent corpus storage costs $0.48/month and checkpoint storage $2.30/month, separately from production model/video storage.

Illustrative quarterly repeat for the selected 100-example cycle: cash **$191.28**, labor **$3,843.33** (training preparation plus new output scoring); monthly storage **$2.8888**. Monthly recurring research allowance = `(191.28 + 3843.333333)/3 + 2.8888 = $1,347.76`. The **$10,310.43 one-time independent corpus preparation** is not charged again every quarter; a new corpus version, rights replacement or additional fixtures creates new preparation costs. Repeating full training preparation each cycle is conservative; reuse reduces it only with an explicit reviewed assumption.

Production plus this optional recurring research allowance at 100/1,000/10,000 videos: **$2,944.72 / $3,154.60 / $6,313.36 per month**, excluding the initial corpus cost and contingency. Production-only totals above are unchanged. Research cadence is a sensitivity, not a required monthly bill.

### Annotation throughput sensitivity

Only label-writing time varies; source verification, rights/provenance, setup and independent review remain unchanged. This avoids pretending faster drafting eliminates trust work. These are hypotheses, not measured examples/hour:

| Annotation hypothesis | Minutes/example (writing only) | Labor: 100 examples | Labor: 500 examples | Labor: 1,000 examples |
| --- | --- | --- | --- | --- |
| fast hypothesis | 10 | $1,810.00 | $6,410.00 | $12,160.00 |
| base hypothesis | 20 | $2,143.33 | $8,076.67 | $15,493.33 |
| slow hypothesis | 40 | $2,810.00 | $11,410.00 | $22,160.00 |

At 100 examples, total preparation time ranges from 82.17h (ten-minute drafting) through 98.83h to 132.17h (40-minute drafting). No target throughput is promised. Evaluate a small rights-cleared annotation pilot before approving 500 or 1,000 examples; revise time, reviewer availability, family complexity and GPU caps from actual observations.

## Break-even and utilization sensitivity

Compare **Director LLM only**, with shared TTS/SaaS/render costs canceled: one warm GPU costs `730*hourly + 80*0.08 + 60*0.023`; reference LLM costs `N*0.099`. Integer crossover `ceil(one_GPU_fixed / 0.099)` must fit `floor((730*u - 0.666667)/h)`. This is a one-replica feasibility calculation; another GPU creates a price step and can remove the advantage. No universal linear crossover is asserted.

| GPU hourly assumption | Target utilization ceiling | One-GPU capacity/month | Unconstrained crossover | Feasible before another GPU |
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

Proposed owner-reviewed pilot production budget **$2,000/month** including contingency; independent initial research reserve **$18,000** for 100 training examples plus independent evaluation preparation/scoring (the $14,345.04 estimate plus 20% contingency rounds up). Expansion reserves of **$25,000 / $34,000** for 500/1,000 examples require a new owner decision; no proposal authorizes spending. Monthly recurring research is separate from this first-cycle reserve. Warn forecast >=80%, stop new admission at 100%; existing bounded jobs may complete within reservations. Idle capacity is an infrastructure budget, not attributed to one user as marginal usage. Cap autoscaling at one GPU initially, later at three only after approval/quote. Scale-to-zero requires explicit availability trade-off. No pricing plan until allocated hosting, expected usage, support/payment overhead and chosen gross-margin target are signed off; advanced billing deferred.

Delivery: cumulative bytes <=3 final-video sizes/job over retention, <=2 concurrent streams/grant and owner aggregate enforced atomically; range/download replay counts actual bytes, min accounting quantum 64 KiB. Signed grants expire <=5 min and deletion/logout revokes. Failed upstream byte reservation released only on confirmed non-delivery; egress has no free unbounded tier. Bandwidth quota increase requires explicit pricing/budget policy.

## Limits and refresh procedure

Obtain region-specific quotes for EC2/RDS/Redis/ALB/NAT/S3/EBS/Cognito and model/provider license terms before provisioning. Include taxes, payment fees, customer support, extra availability GPU and disaster reserve in commercial pricing; those are excluded from this technical planning estimate. Network/backup allowances may prove low. Dataset licensing/review time may dominate GPU expense. Update JSON with measured aggregate throughput/p95/load durations, repeat offline tests/table generation, attach quote date/region and compare worst-case failed jobs. No benchmark, paid account, GPU run or production deployment was executed here.
