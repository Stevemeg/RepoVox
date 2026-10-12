# RepoVox

Bring source code to life visually.

**Status: Phase 1 local foundation under implementation and verification.** Phase 0 was independently accepted at `e35d8ef8a8a53cb34e46271a9813b5332ea42c1f`; PR #1 remains open, so Phase 1 uses a stacked branch. No production deployment, real analysis, AI, speech or video generation exists. Phase 1 requires independent validation and cannot be merged or advanced by the implementation assistant.

## Local development

Requirements: Docker Desktop (Linux containers), Compose v2, Python 3.11+ and Node 24.18.0. Keep at least 15 GB free for builds. Generate distinct ignored local credentials and start the stack:

```powershell
python tools/phase1_env.py
docker compose up -d --build
docker compose ps -a
```

Open `http://localhost:3000` and choose Alex Chen or Sam Rivera. Create/view/delete owned GitHub repository locators. Project details can run labelled synthetic job fixtures; generation is unavailable. PostgreSQL is durable truth, Redis/Celery delivers notifications, and private SeaweedFS provides local S3 storage. Database/storage volumes survive `docker compose down`. [Detailed setup/reset](docs/development/local.md), [API](docs/development/api.md), [migrations](docs/development/migrations.md), [orchestration](docs/development/orchestration.md), [tests/CI](docs/development/testing.md), [Phase 1 evidence](docs/delivery/phase1-verification.md).

## Application checks

```powershell
uv sync --frozen
uv run ruff check apps/api tests tools/phase1*.py
uv run ruff format --check apps/api tests tools/phase1*.py
uv run mypy
uv run pytest tests/unit -q
uv run python tools/phase1_contracts.py --check
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

Integration tests use an explicitly disposable database with real PostgreSQL RLS, Redis and S3 operations; no mocked isolation proof or silent service skips. Read [test execution](docs/development/testing.md) before destructive test reset. Full production security, deletion/restore, managed identity and later media/AI gates remain in the approved Phase 0 roadmap.

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

V1: public GitHub URL; Python, JavaScript and TypeScript; asynchronous generation; 3–5 minute 1280×720 narrated MP4; dashboard, progress, playback, download and history; claims tied to source files and the exact commit. Private repositories, arbitrary documents, avatars, teams, custom editing and advanced billing are deferred.

Self-hosted RepoVox Director and speech are the primary production strategy. Normal videos require no paid third-party LLM/TTS API; external AI evaluation needs explicit owner approval. No model has been trained/evaluated locally. [Revision verification](docs/delivery/phase0-revision-verification.md) distinguishes design checks from future GPU/training results.

## Documentation checks

Python 3.11+ and Node.js LTS are used for planning tooling only:

```powershell
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

Documentation checks validate paths, headings, JSON examples and contract invariants; Mermaid CLI renders diagrams separately. See [conventions and sole-contributor policy](AGENTS.md). Application evidence is separate. Owner authorization permits Phase 1 only; do not merge or start Phase 2 without independent validation and the next authorization.
