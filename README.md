# RepoVox

Bring source code to life visually. RepoVox turns a public GitHub repository into narrated,
evidence-grounded engineering videos. It reads the repository at one pinned commit as data,
never runs it, and cites every statement it makes to a file and line.

> **Status:** implementation output, not independently reviewed. Public production deployment
> stays gated on an independent security review. The official evaluation corpus is UNFROZEN and
> the independent reviewer appointment is pending; see the
> [sole-contributor policy and phase authority](AGENTS.md).

## What it does

- **Sandboxed static analysis (Stages 1–9).**
  - A public GitHub URL is resolved to a commit and its archive is fetched read-only.
  - The archive is screened before anything is parsed: credentials, nested archives, unsafe
    paths, size and fact limits. Any hit fails closed.
  - Python, JavaScript, TypeScript, JSX and TSX are parsed with tree-sitter in a Linux child
    process. That process is confined by Landlock, a seccomp filter and resource limits.
  - The output is a verified analysis artifact (contract `2.3`) of symbols, relationships,
    entry points, evidence and claims. See [analysis, API and limits](docs/development/analysis.md).
- **Problem-to-solution engineering story.** The walkthrough video covers:
  - the problem the authors document, and the solution they propose;
  - how it was built, the architecture and the main workflow;
  - technical decisions, demonstrated results, limitations and open questions.

  Each sentence cites claims and is labelled with the weakest status among them: `VERIFIED`,
  `INFERRED`, `AUTHOR-STATED` or `UNVERIFIED`. Mismatches between the documentation and the code
  are stated. An undocumented problem is reported as such, never inferred
  ([ADR-0025](docs/adr/0025-problem-to-solution-engineering-story.md)).
- **Animated system architecture.**
  - A whole-repository map places cited subsystems in up to four tiers: client and frontend,
    API and routes, core services, and ML, data and external. It animates one cross-tier path.
  - Further explainer videos zoom into route services and component graphs.
  - Every card and arrow carries citations; inferred relationships are drawn dashed
    ([ADR-0032](docs/adr/0032-whole-repository-system-architecture-view.md)).
- **Voice.**
  - Narration is spoken locally: the operating-system voice (`espeak-ng`) by default, or the
    optional Kokoro-82M neural voice on CPU through `kokoro-onnx`. No paid speech API is used.
  - Technical terms get a spoken pronunciation; captions keep the exact text
    ([ADR-0031](docs/adr/0031-neural-voice-and-animated-architecture.md)).
- **Optional grounded narration.**
  - Wording is deterministic by default.
  - When the owner configures a language model, it may reword scenes: self-hosted Ollama, or an
    OpenAI-compatible or Anthropic endpoint under the [model policy](AGENTS.md#model-policy).
  - Stage 11 re-checks every reworded sentence against its cited claims; anything that fails
    falls back to the template wording
    ([ADR-0026](docs/adr/0026-grounded-llm-narration-refiner.md)).
- **Web app.** A Next.js dashboard to:
  - sign in and add GitHub repositories;
  - start a video job and follow its progress;
  - play or download each video with captions and the cited story.

  Published media follow a 24-hour retention lifecycle.

## Repository layout

| Path | Contents |
| --- | --- |
| `apps/api/` | FastAPI API, Celery analysis worker, dispatcher and media worker (Python) |
| `apps/api/repovox/analysis/` | Stages 1–9: acquisition, screening, sandboxed parsing, knowledge, evidence and verification |
| `apps/api/repovox/media/` | Stages 10–15: story, storyboard, grounded narration, speech, frames, encoding and architecture explainers |
| `apps/api/migrations/`, `apps/api/migrations_media/` | Core database (`0004`) and media database (`m001`) migrations |
| `apps/web/` | Next.js web app |
| `infrastructure/local/` | Dockerfiles and Compose overlays: hardening, neural voice, production |
| `scripts/` | `deploy_selfhosted.sh` and `setup_kokoro_voice.sh` |
| `docs/` | Product, architecture, security, operations, ADRs and delivery records |
| `tests/` | Unit and integration tests with locally authored synthetic fixtures |
| `tools/` | Documentation, contract, security and evaluation tooling |

## Quickstart (self-hosted)

On a Linux host (WSL 2 works) with Docker Engine, Compose v2, Landlock and seccomp. See the
[host prerequisites](docs/operations/deployment-guide.md#1-host-prerequisites).

```sh
bash scripts/deploy_selfhosted.sh --check   # preflight only; changes nothing
bash scripts/deploy_selfhosted.sh           # generates .env (mode 600), builds, starts and waits for health
```

Open `http://localhost:3000` and choose a development identity (Alex Chen or Sam Rivera). The
API listens on `http://127.0.0.1:8000`. `--mode production` uses GitHub sign-in for provisioned
accounts behind a TLS reverse proxy.

Optional Kokoro neural voice: download the reviewed model files into the git-ignored
`.models/kokoro/`, then add the neural-voice overlay:

```sh
bash scripts/setup_kokoro_voice.sh
docker compose -f docker-compose.yml -f infrastructure/local/docker-compose.prod.yml \
  -f infrastructure/local/docker-compose.neural-tts.yml up -d --build --wait
```

More detail:
- the [self-hosted deployment guide](docs/operations/deployment-guide.md) covers secrets, TLS,
  GitHub OAuth, the optional narration model, backup, upgrade and rollback;
- the [frontend developer handoff](docs/development/frontend-handoff.md) covers running the web
  app against a local backend and the frozen API contract.

Never commit `.env`, `.artifacts/` or `.models/`; all three are git-ignored.

## Application checks

First use the [hash-anchored security bootstrap](docs/security/python-trust-remediation.md)
in an owner-selected disposable Python environment. Do not use an old pip or uv for network installation.

```sh
python tools/security_bootstrap.py
uv sync --frozen
uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py
uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py
uv run mypy
uv run pytest tests/unit -q
uv run python tools/phase1_contracts.py --check
uv run python tools/phase2_contracts.py --check
uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json
uv run python tools/phase2_preparation.py --catalog docs/ai/evaluation-candidates.json --manifest docs/ai/evaluation-corpus.manifest.json
uv run pip-audit --local
npm --prefix apps/web ci
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
docker compose -p repovox-test up -d --build postgres redis storage storage-init migrate
docker compose -p repovox-test run --rm --build tests
docker compose -p repovox-test down --volumes
```

Integration tests use an explicitly disposable database with real PostgreSQL row-level
security, Redis and S3 operations. Read [test execution](docs/development/testing.md) before a
destructive test reset.

## Reading order

1. [Product requirements and acceptance criteria](docs/product/prd.md)
2. [Architecture and diagram](docs/architecture/overview.md)
3. [Intelligence pipeline and artifact contracts](docs/architecture/pipeline.md)
4. [Persistence and job orchestration](docs/architecture/data-model.md)
5. [Security threat model](docs/security/threat-model.md)
6. [Deployment](docs/operations/deployment.md), [reliability](docs/operations/reliability.md) and [cost model](docs/operations/cost-model.md)
7. [Roadmap and requirements traceability](docs/delivery/roadmap.md)
8. [RepoVox Director](docs/ai/director-architecture.md), [model selection](docs/ai/model-selection.md), [training](docs/ai/training-strategy.md), [evaluation](docs/ai/evaluation-plan.md), [self-hosted speech](docs/ai/speech-strategy.md) and [change impact](docs/ai/change-impact.md)
9. [ADRs](docs/adr/README.md) and [targeted remediation verification](docs/delivery/phase0-remediation-verification.md), [revision verification](docs/delivery/phase0-revision-verification.md) ([historical record](docs/delivery/phase0-verification.md))

Self-hosted narration and speech are the primary production strategy. Normal videos need no
paid third-party LLM or TTS API, and external AI evaluation needs explicit owner approval. No
model has been trained or evaluated locally.

## Documentation checks

Python 3.11+ and Node.js LTS are used for documentation tooling only:

```powershell
python tools/security_bootstrap.py
python -m pip install -r tools/requirements-docs.txt
python tools/check_docs.py
python tools/cost_model.py --check
python -m unittest discover -s tools -p "test_*.py" -v
$diagramConfig = Join-Path $env:TEMP 'repovox-puppeteer.json'
# Use an installed browser; adjust this path if needed. Config and outputs stay outside Git.
@{ executablePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe' } | ConvertTo-Json | Set-Content -LiteralPath $diagramConfig -Encoding ascii
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/overview.md -o "$env:TEMP/repovox-architecture.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/data-model.md -o "$env:TEMP/repovox-data.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/ai/director-architecture.md -o "$env:TEMP/repovox-director.svg"
git diff --check
```

Documentation checks validate paths, headings, JSON examples and contract invariants;
Mermaid rendering is separate.
