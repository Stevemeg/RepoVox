# ADR-008: Warm private GPU inference and isolated training

Status: proposed · Date: 2026-10-08

Context: cheap active GPU seconds hide idle capacity/cold-start and availability constraints.

Decision: private authenticated gateway with vLLM on ECS GPU EC2, one warm single-sequence L4-class replica baseline, bounded context/admission; separate CPU TTS/render and training GPU/account. GPU requests have durable operation leases, owner cache boundaries and no internet/default paid fallback. Costs include idle/loading and replica sizing.

Alternatives: Fargate cannot provide GPU; Runpod dedicated/serverless GPU or private GPU VM may cost less but need network/data/availability parity; scale-to-zero adds model-load/cold-start delay; sharing production GPU with training harms latency/isolation.

Consequences: single-host generation availability risk explicitly accepted only for gated pilot; HA doubles low-volume GPU idle costs. Benchmark memory/prefill/decode/startup and rights/security before deploy. Reverse warm policy only after measured burst/deadline/cost evidence and owner approval. [Deployment](../operations/deployment.md), [economics](../operations/cost-model.md).
