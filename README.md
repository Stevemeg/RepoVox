# RepoVox

Bring source code to life visually.

**Status: Phase 0 documentation, awaiting independent validation.** No application features, paid integrations, cloud resources, benchmarks or production deployment exist. Decisions are implementation proposals; owner approvals are listed in the [roadmap](docs/delivery/roadmap.md).

## Reading order

1. [Product requirements and acceptance criteria](docs/product/prd.md)
2. [Architecture and diagram](docs/architecture/overview.md)
3. [Intelligence pipeline and artifact contracts](docs/architecture/pipeline.md)
4. [Persistence and job orchestration](docs/architecture/data-model.md)
5. [Security threat model](docs/security/threat-model.md)
6. [Deployment](docs/operations/deployment.md), [reliability](docs/operations/reliability.md) and [cost model](docs/operations/cost-model.md)
7. [Roadmap and requirements traceability](docs/delivery/roadmap.md)
8. [ADRs](docs/adr/README.md) and [verification record](docs/delivery/phase0-verification.md)

V1: public GitHub URL; Python, JavaScript and TypeScript; asynchronous generation; 3–5 minute 1280×720 narrated MP4; dashboard, progress, playback, download and history; claims tied to source files and the exact commit. Private repositories, arbitrary documents, avatars, teams, custom editing and advanced billing are deferred.

## Documentation checks

Python 3.11+ and Node.js LTS are used for planning tooling only:

```powershell
python -m pip install -r tools/requirements-docs.txt
python tools/check_docs.py
python tools/cost_model.py --check
$diagramConfig = Join-Path $env:TEMP 'repovox-puppeteer.json'
# Use an installed browser; adjust this path if needed. Config and outputs stay outside Git.
@{ executablePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe' } | ConvertTo-Json | Set-Content -LiteralPath $diagramConfig -Encoding ascii
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/overview.md -o "$env:TEMP/repovox-architecture.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/data-model.md -o "$env:TEMP/repovox-data.svg"
git diff --check
```

Local checks validate paths, headings, JSON examples and contract invariants; Mermaid CLI renders diagrams separately. See [conventions and sole-contributor policy](AGENTS.md). Do not begin Phase 1 before independent validation and owner authorization.
