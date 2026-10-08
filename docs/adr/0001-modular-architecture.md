# ADR-001: Modular application, separate process roles

Status: proposed · Date: 2026-10-08

Context: parsing/Chromium workloads differ from HTTP requests; solo maintenance limits service overhead.

Decision: Next.js/TypeScript UI, FastAPI modular backend, shared PostgreSQL/Redis; Python analysis, private GPU Director inference, isolated CPU self-hosted TTS and trusted Remotion/FFmpeg render tasks; research/training isolated from production. API/dispatcher/analysis share modules/release versions. Render has a separate image for Node/Chromium, with versioned artifact contracts. No Kubernetes.

Alternatives: Next.js-only reduces languages but complicates Python analysis; independent microservices add deployment/auth/tracing overhead; one process lets rendering exhaust API resources. Process isolation provides resource control without separate data ownership.

Consequences: CPU, CUDA inference, TTS and render images increase compatibility/patching work; modular backend remains one durable business boundary; contract compatibility tested each release. Split services only for measured contention or changed human ownership. Revisit orchestration only when ECS cannot meet measured scheduling needs economically.

Evidence: [architecture](../architecture/overview.md#technology-decisions-and-alternatives), [deployment](../operations/deployment.md).
