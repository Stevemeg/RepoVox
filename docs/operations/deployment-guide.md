# Self-hosted deployment guide

Status: readiness runbook, 2026-11-18, on branch `feat/js-ts-frameworks-and-deploy-readiness`;
production GitHub sign-in added the same day ([ADR-0024](../adr/0024-github-oauth-allowlist-identity.md)).
Not independently reviewed or accepted. **Nothing was deployed or provisioned while writing
it**, and no cloud account, paid service or real customer data was used. It does not
authorize a deployment, lift any phase gate or change `Stage 3: BLOCKED`, `CR-04: PENDING`
or `EVAL-ENTRY: UNFROZEN`. Related: [production deployment design](deployment.md),
[media database](media-database.md), [reliability](reliability.md),
[parser process isolation](../adr/0011-parser-process-isolation.md),
[local object storage](../adr/0009-local-object-storage.md),
[Node/Next remediation](../security/node-next-remediation.md),
[sole-contributor policy and phase authority](../../AGENTS.md). Frontend developers start with
the [frontend handoff](../development/frontend-handoff.md): local stack behind
`npm --prefix apps/web run dev`, the frozen API contract, truthfulness rules and quality gates.

The guide covers one Linux host running the repository's `docker-compose.yml`. It names every
service, the order they start in, how each is checked, which identity each runs as, and every
setting and secret they read. There are two modes:

| Mode | Who can sign in | Origin | Command |
| --- | --- | --- | --- |
| [Local / private host](#local--private-host-deployment---mode-local) | the two seeded development identities | `http://localhost:3000`, this host only | `bash scripts/deploy_selfhosted.sh` |
| [Public HTTPS production](#public-https-production-deployment---mode-production) | GitHub accounts an operator provisioned | your `https://` origin behind a TLS reverse proxy | `bash scripts/deploy_selfhosted.sh --mode production` |

Production is not approved by this guide. The GitHub identity adapter is proposed in
[ADR-0024](../adr/0024-github-oauth-allowlist-identity.md) and needs an independent security
review before a public deployment.

## Identity adapters and fail-closed settings

`Settings.fail_closed` (`apps/api/repovox/core/config.py`) runs in the API, the workers, the
dispatcher and the media worker, and refuses to start any of them with an unsafe
combination:

| Environment | Must hold | Refused with |
| --- | --- | --- |
| `production` | `REPOVOX_DEV_AUTH=false` | `Production forbids the development identity adapter` |
| `production` | `REPOVOX_FIXTURES=false` and no `REPOVOX_SYNTHETIC_SOURCE_DIR` | `Production forbids fixtures and synthetic sources` |
| `production` | `REPOVOX_AUTH_PROVIDER=github` with a non-empty `REPOVOX_GITHUB_CLIENT_ID` and `REPOVOX_GITHUB_CLIENT_SECRET` | `Production requires the GitHub identity adapter with a client id and secret` |
| `production` | `REPOVOX_ORIGIN` an exact `https://host[:port]`: lowercase, no path, query, fragment, user info or wildcard. `http://localhost:3000` or `http://127.0.0.1:3000` only with `REPOVOX_ALLOW_LOOPBACK_ORIGIN=true` | `Production requires an exact https:// browser origin` |
| `development`, `test` | with the `dev` adapter: `REPOVOX_DEV_AUTH=true` and a loopback origin | `An explicitly enabled development identity adapter is required`, `Phase 1 requires an authorized local browser origin` |
| `development`, `test` | with the `github` adapter: `REPOVOX_DEV_AUTH=false`, client id and secret, loopback or `https://` origin | `The GitHub identity adapter ...` |
| any | `REPOVOX_SYNTHETIC_SOURCE_DIR` only with `REPOVOX_FIXTURES=true` | `Synthetic source requires the development fixture mode` |

The GitHub adapter signs in **only accounts an operator has provisioned**: the API's database
role cannot create users, so there is no self sign-up (see
[GitHub OAuth App and accounts](#github-oauth-app-and-accounts)).

## Quickstart

On a Linux host that meets the [prerequisites](#1-host-prerequisites), from a checkout of the
reviewed commit:

```sh
bash scripts/deploy_selfhosted.sh --check                    # preflight; no Docker daemon needed
bash scripts/deploy_selfhosted.sh --repair-env               # only if an older .env lacks keys
bash scripts/deploy_selfhosted.sh                            # --mode local (default)
bash scripts/deploy_selfhosted.sh --mode production          # GitHub sign-in, https origin
```

`--check` (with an optional `--mode`) confirms the required files exist and that the script's
secret list matches every `${VAR:?}` in the base Compose file. It generates a throwaway `.env`
in a temporary directory and checks it: every key once, distinct values of at least 32
characters, mode 600. It shows `--repair-env` restoring a copy with keys removed. It checks
the structure of both overlays and, where the Docker CLI exists, runs `docker compose config`
for both modes. Prerequisites and an existing `.env` are reported as warnings in this mode;
nothing is changed.

`--repair-env` appends any missing generated key (for example `MEDIA_MIGRATION_PASSWORD`,
`MEDIA_APP_PASSWORD`, `MEDIA_WORKER_PASSWORD` in a `.env` from before the media database
existed) with a new random value. It never changes or removes an existing key, stops if a key
is set twice, sets the file to mode 600 and prints key names only. A database volume that
already exists keeps the roles it was created with: `infrastructure/local/init-db.sh` runs only
on a new volume, so a role added later must be created with its password before use (see
[section 2](#2-environment-and-secrets)).

A normal run fails on any missing prerequisite. If `.env` is absent, it generates one with
mode 600: `openssl rand -hex 32` (or Python `secrets` when OpenSSL is absent) for each
password and the session secret, plus the two fixed storage identifiers. No value is printed.
It then starts the stack and polls `http://127.0.0.1:8000/health`, `/ready` and
`http://127.0.0.1:3000/sign-in` for up to `DEPLOY_TIMEOUT` seconds (600 by default). It stops
unless `/ready` reports the expected environment, `development` or `production`.

`infrastructure/local/docker-compose.prod.yml` is the hardening overlay, used in both modes;
`docker-compose.yml`, which CI uses, is unchanged. It sets no `REPOVOX_*` value. It adds:

| Service | Overlay change |
| --- | --- |
| `postgres`, `redis`, `storage`, `api`, `web`, `worker`, `dispatcher`, `media-worker` | `restart: unless-stopped` |
| `worker` | healthcheck: the Celery worker answers `celery inspect ping` through the Redis broker |
| `dispatcher` | healthcheck: PID 1 is the dispatcher and PostgreSQL and Redis accept connections |
| `media-worker` | healthcheck: PID 1 is the media worker and PostgreSQL and object storage accept connections |
| `web` | `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`; writable tmpfs only at `/tmp` and `/web/.next/cache` (the image's working directory is `/web`), the cache owned by the `node` user |

The dispatcher and media worker checks confirm the process and its dependencies, not
progress: a loop that is alive but stuck still reports healthy, and its logs remain the
signal.

### Local / private host deployment (`--mode local`)

```sh
bash scripts/deploy_selfhosted.sh
```

Runs the base file with the hardening overlay:
`docker compose -f docker-compose.yml -f infrastructure/local/docker-compose.prod.yml up -d --build`.
The settings are those in `docker-compose.yml`: `REPOVOX_ENVIRONMENT=development`,
`REPOVOX_DEV_AUTH=true`, `REPOVOX_AUTH_PROVIDER=dev` (the default) and
`REPOVOX_ORIGIN=http://localhost:3000`. Open `http://localhost:3000` on the host. On WSL2 the
Windows browser reaches the same address. From another machine use an SSH tunnel
(`ssh -N -L 3000:127.0.0.1:3000 <user>@<host>`), never a published port: the development
identities have no password.

### Public HTTPS production deployment (`--mode production`)

1. **Create a GitHub OAuth App** (GitHub > Settings > Developer settings > OAuth Apps). Set the
   homepage URL to your origin. Set the authorization callback URL to exactly
   `https://<your-host>/api/v1/auth/github/callback`.
2. **Add the production keys to `.env`** on the host (never to Git):

   ```sh
   REPOVOX_ORIGIN=https://repovox.example.com
   REPOVOX_GITHUB_CLIENT_ID=<the OAuth App's client id>
   REPOVOX_GITHUB_CLIENT_SECRET=<the OAuth App's client secret>
   ```

3. **Start** with `bash scripts/deploy_selfhosted.sh --mode production`. The script checks the
   three keys (origin format, non-empty id, secret length) without printing the secret, then
   runs the base file, the hardening overlay and
   `infrastructure/local/docker-compose.production.yml`. That overlay sets
   `REPOVOX_ENVIRONMENT=production`, `REPOVOX_DEV_AUTH=false`, `REPOVOX_FIXTURES=false`,
   `REPOVOX_AUTH_PROVIDER=github`, clears `REPOVOX_SYNTHETIC_SOURCE_DIR`, and passes the three
   keys to `api`, `worker`, `dispatcher` and `media-worker`. Every one of those services
   validates the production settings, so each receives the client secret.
4. **Put a TLS reverse proxy in front** ([TLS reverse proxy](#tls-reverse-proxy)) and
   **provision the people allowed to sign in**
   ([GitHub OAuth App and accounts](#github-oauth-app-and-accounts)).

## 1. Host prerequisites

| Requirement | Why | How to check |
| --- | --- | --- |
| Linux on `x86_64` or `aarch64` | Parser containment refuses any other platform or machine type (`parser_isolation_unavailable`) | `uname -sm` |
| Landlock ABI 1 or later enabled | Parser subprocesses restrict file access with Landlock before parsing untrusted source; see [ADR-0011](../adr/0011-parser-process-isolation.md) | `grep -o landlock /sys/kernel/security/lsm` prints `landlock`, and the probe below prints `1` or higher |
| seccomp | Parser and media sandboxes deny network, `exec` and `fork` (`libseccomp2` is in the API image) | `grep Seccomp: /proc/self/status` |
| Containers not running as root | Containment refuses UID 0; the API image runs as UID 10001 | `docker compose exec api id -u` prints `10001` |
| Docker Engine with Compose v2 | `depends_on` conditions `service_healthy` and `service_completed_successfully` | `docker compose version` |
| Outbound DNS and HTTPS 443 to `api.github.com` and `codeload.github.com` | Repository acquisition; nothing else is contacted at run time | see below |
| Build-time egress to Docker Hub, the Debian archive, PyPI and `registry.npmjs.org` | Image builds only | `docker compose build` |
| CPU and memory: at least 4 vCPU and 12 GiB (estimate, not a benchmark) | `api`, `worker`, `dispatcher` and `media-worker` are each limited to 1 CPU and 2 GiB; PostgreSQL, Redis, storage and web have no limit | `nproc`, `free -g` |

Landlock ABI probe (system call 444 is `landlock_create_ruleset` on both supported
architectures; flag 1 asks for the ABI version):

```sh
python3 -c 'import ctypes; libc = ctypes.CDLL(None, use_errno=True); print(libc.syscall(444, None, 0, 1))'
```

A result of `-1` means Landlock is absent or disabled (check the kernel's `lsm=` boot
parameter). The same probe can be run inside the API container with
`docker compose exec api python -c ...` to confirm the container runtime's seccomp profile
lets the call through.

**GitHub egress.** `apps/api/repovox/analysis/transport.py` resolves each host once, then
connects to the numeric address with TLS for the original host name. It never uses an HTTP
proxy and never follows redirects. Every resolved address must be globally routable: private,
loopback, link-local and special ranges are refused, and so are NAT64 (`64:ff9b::/96`,
`64:ff9b:1::/48`), IPv4-mapped, 6to4 and Teredo IPv6 addresses (`github_address_blocked`).
Use a resolver that returns GitHub's public addresses and a route that reaches them directly:
public IPv4, or native global IPv6. A split-horizon resolver, a DNS64/NAT64-only network or
a mandatory egress proxy will make acquisition fail closed. Only `api.github.com` and
`codeload.github.com` are accepted origins.

## 2. Environment and secrets

### Generate secrets

```sh
python tools/phase1_env.py
chmod 600 .env
```

The tool creates `.env` with distinct random values and refuses to overwrite an existing
file. It never prints a value. `scripts/deploy_selfhosted.sh` writes the same keys, with longer
values, when `.env` is absent, and `--repair-env` adds keys an older file lacks
([Quickstart](#quickstart)). `.env` is ignored by Git and must never be committed, pasted
into an issue, or copied between hosts: generate it on the host that uses it. The file header
says the values are for development; a host serving other users must use values generated
on that host and kept only there.

| Variable in `.env` | Used by | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `postgres` (first start), `tests` profile | PostgreSQL superuser; never given to an application service |
| `MIGRATION_PASSWORD` | `migrate`, `postgres` init | `rv_migrator`, owner of the core `repovox` database |
| `APP_DATABASE_PASSWORD` | `api`, `dispatcher`, `postgres` init | `rv_app`, the API's core role (the dispatcher uses it only for the media handoff reads) |
| `WORKER_DATABASE_PASSWORD` | `worker`, `dispatcher`, `postgres` init | `rv_worker`, analysis workers, dispatch and reconciliation |
| `MEDIA_MIGRATION_PASSWORD` | `media-migrate`, `postgres` init | `rvm_migrator`, owner of the `repovox_media` database |
| `MEDIA_APP_PASSWORD` | `api`, `dispatcher`, `postgres` init | `rvm_app`, the API's media role |
| `MEDIA_WORKER_PASSWORD` | `media-worker`, `postgres` init | `rvm_worker`, video rendering |
| `SESSION_SECRET` | `api` and workers | Session signing; at least 32 characters |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | `storage-config`, `storage-init` | Object storage administrator, used only to write the S3 identity file and create the bucket |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | `storage-config`, `storage-init`, `api` and workers | The application's object storage identity |
| `SYNTHETIC_SOURCE_DIR` (optional, not generated) | `api`, `worker` | Development only: serve locally authored synthetic repositories. Leave unset outside development |
| `REPOVOX_ORIGIN` (production, set by you) | production overlay | The exact public `https://` origin |
| `REPOVOX_GITHUB_CLIENT_ID`, `REPOVOX_GITHUB_CLIENT_SECRET` (production, set by you) | production overlay: `api`, `worker`, `dispatcher`, `media-worker` | The GitHub OAuth App's credentials; the secret is never printed or logged |

Core and media roles are separate and cannot cross: `rv_*` roles connect only to `repovox`,
`rvm_*` roles only to `repovox_media` (`infrastructure/local/init-db.sh`). The init script runs
once, when the `postgres-data` volume is first created. Changing a password in `.env` later
does not change the role; rotate it with `ALTER ROLE ... PASSWORD` and then update `.env`.

### Application settings

Settings are read with the prefix `REPOVOX_` (`apps/api/repovox/core/config.py`). The compose
file sets them in the shared `x-api` block.

| Setting | Code default | `docker-compose.yml` | Target production value | Notes |
| --- | --- | --- | --- | --- |
| `REPOVOX_ENVIRONMENT` | `production` | `development` | `production` | Production rules in [the table above](#identity-adapters-and-fail-closed-settings) |
| `REPOVOX_DEV_AUTH` | `false` | `true` | `false` | Production refuses `true` |
| `REPOVOX_AUTH_PROVIDER` | `dev` | not set (`dev`) | `github` | Set by the production overlay |
| `REPOVOX_GITHUB_CLIENT_ID`, `REPOVOX_GITHUB_CLIENT_SECRET` | unset | not set | from `.env` | Required with `github` |
| `REPOVOX_ALLOW_LOOPBACK_ORIGIN` | `false` | not set | `false` | Only for a production rehearsal on `http://localhost:3000` |
| `REPOVOX_FIXTURES` | `false` | `true` | `false` | Production refuses `true` |
| `REPOVOX_ANALYSIS` | `false` | `true` | `true` | Static analysis through Stage 9 |
| `REPOVOX_VIDEO` | `false` | `true` | `true` | Video jobs in the media database |
| `REPOVOX_ORIGIN` | `http://localhost:3000` | `http://localhost:3000` | your exact `https://` origin | Also the base of the OAuth callback URL |
| `REPOVOX_DATABASE_URL` | none | core role per service | unchanged | `postgresql+psycopg://rv_...@postgres:5432/repovox` |
| `REPOVOX_WORKER_DATABASE_URL` | unset | `rv_worker` for `worker` and `dispatcher` | unchanged | |
| `REPOVOX_MEDIA_DATABASE_URL` | unset | `rvm_app` | unchanged | |
| `REPOVOX_MEDIA_WORKER_DATABASE_URL` | unset | `rvm_worker` for `media-worker` | unchanged | |
| `REPOVOX_MIGRATION_DATABASE_URL` | read by `apps/api/migrations/env.py` | `rv_migrator` for `migrate` | unchanged | |
| `REPOVOX_MEDIA_MIGRATION_DATABASE_URL` | read by `apps/api/migrations_media/env.py` | `rvm_migrator` for `media-migrate` | unchanged | |
| `REPOVOX_SESSION_SECRET` | none (required) | `SESSION_SECRET` | generated on the host | |
| `REPOVOX_SESSION_SECONDS` | `3600` | not set | `3600` | 60 to 86400 |
| `REPOVOX_REDIS_URL` | `redis://redis:6379/0` | same | same | Compose network only |
| `REPOVOX_STORAGE_ENDPOINT` | `http://storage:8333` | same | same | Compose network only |
| `REPOVOX_STORAGE_ACCESS_KEY`, `REPOVOX_STORAGE_SECRET_KEY` | none (required) | from `.env` | generated on the host | |
| `REPOVOX_STORAGE_BUCKET` | `repovox-private` | not set | `repovox-private` | Created by `storage-init` |
| `REPOVOX_GITHUB_TOKEN` | unset | not set | optional | Raises GitHub API rate limits; a secret, store it like `.env` |
| `REPOVOX_MEDIA_HANDOFF_SECONDS` | `3` | not set | `3` | `0` turns the API's pass off; the dispatcher still runs it every 5 seconds |
| `REPOVOX_SYNTHETIC_SOURCE_DIR` | unset | `${SYNTHETIC_SOURCE_DIR:-}` | unset | Development only |
| `REPOVOX_API_URL` (web) | `http://localhost:8000` | `http://api:8000` | `http://api:8000` | Read by `apps/web/src/app/api/v1/[...path]/route.ts` |
| `REPOVOX_LLM_PROVIDER` | `deterministic` | not set | `deterministic` unless you opt in | `ollama`, `openai_compatible` or `anthropic`; see [below](#optional-grounded-narration-model) |
| `REPOVOX_LLM_MODEL` | unset | not set | with a provider | Required by every model provider |
| `REPOVOX_LLM_BASE_URL` | per provider | not set | optional | `https://`; `http://` only on `127.0.0.1`, `localhost` or `host.docker.internal` |
| `REPOVOX_LLM_API_KEY` | unset | not set | hosted providers only | A secret: store it like `.env`; never logged or written to an artifact |
| `REPOVOX_LLM_TIMEOUT_SECONDS` | `20` | not set | `20` | 1 to 120 |
| `REPOVOX_LLM_TEMPERATURE` | unset | not set | unset | `0.0` to `1.0`; unset sends no sampling parameter to hosted providers, and `0` to Ollama |
| `REPOVOX_TTS_PROVIDER` | `auto` | not set | `auto` | `deterministic`, `auto` or `kokoro_onnx`; see [below](#optional-local-neural-voice) |
| `REPOVOX_TTS_MODEL_PATH`, `REPOVOX_TTS_VOICES_PATH` | unset | not set | optional | Absolute `.onnx` and `.bin` paths, both or neither |
| `REPOVOX_TTS_VOICE` | `af_heart` | not set | optional | A Kokoro voice id, `^[a-z0-9_-]{2,32}$` |
| `REPOVOX_TTS_SPEED` | `1.0` | not set | `1.0` | 0.5 to 2.0 |
| `REPOVOX_TTS_THREADS` | unset | not set | optional | Neural voice inference threads, 1 to 64; match the media worker's CPUs |
| `REPOVOX_MEDIA_SPEECH_PREWARM_SECONDS` | `240` | not set | `240` | 0 to 300; how long the narration stage may speak ahead for a neural voice; 0 turns it off |
| `REPOVOX_MEDIA_ENCODE_BASE_SECONDS`, `..._SECONDS_PER_MINUTE`, `..._MAX_SECONDS` | `170`, `30`, `900` | not set | defaults | Encoder and probe time limit per video: base plus a share per minute of video, capped. A stage's own deadline still bounds it |

### Optional grounded narration model

By default the media worker narrates the engineering story in fixed template wording and
makes no network call. Setting `REPOVOX_LLM_PROVIDER` lets one language-model request per
video reword that narration ([ADR-0026](../adr/0026-grounded-llm-narration-refiner.md)).

- **Input.** The model receives only the verified scene plan and the claims each sentence
  cites, never a repository file.
- **Checking.** Each scene it returns must pass a claim-by-claim grounding check, or it keeps
  its template wording.
- **Failures.** A timeout, an error or a malformed answer keeps the template wording for
  every scene.
- **Provenance.** The provider, model, refined and fallback scene counts and the exact
  rejection reasons are recorded in the storyboard and in the published video's
  `metadata.narration`. Stage 11 re-checks the wording without calling the model.

Only the `media-worker` service reads these settings. `docker-compose.yml` does not set them,
so add them to that service in a `docker-compose.override.yml`, or to the production overlay
for a production host:

| Provider | Settings | Notes |
| --- | --- | --- |
| Local Ollama (self-hosted, no API key) | `REPOVOX_LLM_PROVIDER=ollama`, `REPOVOX_LLM_MODEL=<a model you pulled, for example llama3.1:8b>`, `REPOVOX_LLM_BASE_URL=http://host.docker.internal:11434` | From a container, add `extra_hosts: ["host.docker.internal:host-gateway"]` to `media-worker`, and make Ollama listen on an address the bridge reaches. The default `http://127.0.0.1:11434` is the container itself. |
| OpenAI-compatible (hosted, or a local server) | `REPOVOX_LLM_PROVIDER=openai_compatible`, `REPOVOX_LLM_MODEL=<model>`, `REPOVOX_LLM_API_KEY=<key>`, optional `REPOVOX_LLM_BASE_URL=https://...` | Calls `<base>/v1/chat/completions` with JSON object output. Sends `temperature` only when `REPOVOX_LLM_TEMPERATURE` is set; leave it unset for reasoning models, which reject it. |
| Anthropic (hosted) | `REPOVOX_LLM_PROVIDER=anthropic`, `REPOVOX_LLM_MODEL=<model>`, `REPOVOX_LLM_API_KEY=<key>` | Calls `<base>/v1/messages` with `anthropic-version: 2023-06-01`. Sends `temperature` only when `REPOVOX_LLM_TEMPERATURE` is set; current Claude models (Opus 4.7 and later, Sonnet 5 and later) reject it, so leave it unset. |

The worker refuses to start if a provider is set without its model, if a hosted provider has
no key, or if the URL is plain HTTP to any other host, or carries user info, a query or a
fragment. Hosted providers receive the story blueprint (verified claim text, file paths and
the repository name) and bill your account. Choose one only where that provider's terms
permit the data ([model policy](../../AGENTS.md#model-policy)). To turn the feature off, set
`REPOVOX_LLM_PROVIDER=deterministic` or remove the variables and restart `media-worker`.

### Optional local neural voice

By default the media worker speaks narration with the operating-system voice (`espeak-ng` in
the images). A local Kokoro-82M v1.0 ONNX voice can replace it
([ADR-0027](../adr/0027-neural-tts-and-story-api-contract.md),
[ADR-0031](../adr/0031-neural-voice-and-animated-architecture.md)). Two commands enable it on a
self-hosted stack:

```sh
bash scripts/setup_kokoro_voice.sh
docker compose -f docker-compose.yml -f infrastructure/local/docker-compose.prod.yml   -f infrastructure/local/docker-compose.neural-tts.yml up -d --build --wait
```

- **Model files.** `scripts/setup_kokoro_voice.sh` downloads `kokoro-v1.0.onnx` and
  `voices-v1.0.bin` from the official `thewh1teagle/kokoro-onnx` release `model-files-v1.0`
  into the git-ignored `.models/kokoro/`. It checks each file's exact size and SHA-256 and is
  idempotent; `--check` verifies without downloading. kokoro-onnx is MIT and the Kokoro-82M
  weights are Apache-2.0. The application itself never downloads a model.
- **Image.** The overlay builds `media-worker` with `INSTALL_NEURAL_TTS=true`, which installs
  the `neural-tts` extra. The default build argument is `false`, so CI and the standard images
  do not change.
- **Settings.** The overlay sets `REPOVOX_TTS_PROVIDER=kokoro_onnx`, the two model paths under
  `/models/kokoro` (mounted read-only), `REPOVOX_TTS_VOICE=af_heart`, `REPOVOX_TTS_SPEED=1.0`
  and `REPOVOX_TTS_THREADS=4`.
- **Resources.** Neural speech and encoding are CPU-bound and every media stage keeps its fixed
  deadline (speech 240 s, encode 180 s, architecture 600 s). The overlay gives `media-worker` 4
  CPUs and 3 GiB instead of 1 CPU and 2 GiB, and inherits every other limit. The narration stage
  speaks the approved script ahead within its own lease
  (`REPOVOX_MEDIA_SPEECH_PREWARM_SECONDS`), so the speech stage only finishes the rest.

To use your own files instead, mount them read-only and set `REPOVOX_TTS_MODEL_PATH` and
`REPOVOX_TTS_VOICES_PATH` (absolute `.onnx` and `.bin` paths) on `media-worker`.

With `REPOVOX_TTS_PROVIDER=auto` (the default), the worker uses the neural voice when the
package and both files load, and the operating-system voice otherwise.

With `kokoro_onnx`, the worker requires the neural voice. Without it, the speech stage fails
with a fixed code (`neural_tts_unavailable`, `neural_tts_files_missing` or
`neural_tts_load_failed`) and never falls back.

Every voice is given the sentence's technical pronunciation: `FastAPI` is said as "Fast"
and the letters A, P, I, and `backend/app/services/inputs.py` as "inputs dot py in backend app
services" (`apps/api/repovox/media/pronunciation.py`). Captions, subtitles, the storyboard and
every citation keep the exact text.

Which voice spoke is recorded by name, never by path, in the published video's
`metadata.narration.tts_provider`, `tts_engine` and `tts_voice`.

### TLS reverse proxy

In production, terminate TLS at a reverse proxy on the host and forward only to the web
container at `127.0.0.1:3000`. The web server forwards `/api/v1/...` to the API over the
compose network (`REPOVOX_API_URL`), so the API's `127.0.0.1:8000` port must stay on loopback.
The browser's `Origin` header must equal `REPOVOX_ORIGIN` exactly, and session cookies are
`Secure` because the origin is `https://`. Caddy obtains and renews the certificate itself:

```text
repovox.example.com {
	reverse_proxy 127.0.0.1:3000
}
```

Nginx, with a certificate you manage:

```text
server {
    listen 443 ssl;
    server_name repovox.example.com;
    ssl_certificate     /etc/ssl/repovox/fullchain.pem;
    ssl_certificate_key /etc/ssl/repovox/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
server {
    listen 80;
    server_name repovox.example.com;
    return 301 https://$host$request_uri;
}
```

Do not add a path prefix: the OAuth callback is fixed at `/api/v1/auth/github/callback` on the
origin.

### GitHub OAuth App and accounts

Sign-in uses the OAuth 2.0 authorization code flow with scope `read:user`. RepoVox reads the
account's numeric id and discards the access token after that request; the token is not
stored, logged or sent to the browser. The single-use `state` and a PKCE code verifier (S256)
live in `HttpOnly`, `SameSite=Lax`, `Secure` cookies for ten minutes; the state is compared
in constant time. A mismatch or a missing cookie is refused (`400 oauth_state_rejected`)
before GitHub is contacted.

Only provisioned accounts can sign in; anyone else gets `403 account_not_provisioned`.
Provision, list and disable accounts with the migration role on the `migrate` service. Use
the numeric id (`https://api.github.com/users/<login>` shows it), never the login, which can
change:

```sh
compose="docker compose -f docker-compose.yml -f infrastructure/local/docker-compose.prod.yml -f infrastructure/local/docker-compose.production.yml"
$compose run --rm migrate python -m repovox.auth.accounts add --github-id 583231 --name "Ada Lovelace" --email ada@example.com
$compose run --rm migrate python -m repovox.auth.accounts list
$compose run --rm migrate python -m repovox.auth.accounts disable --github-id 583231
```

`add` also creates the account's quota and reactivates a disabled account; a deleted account
stays deleted. `disable` stops sign-in and revokes the account's open sessions; its data is
kept. The account's owner id is derived from the numeric id, so it never changes.

## 3. Services, startup order and health

Every service, in the order Compose starts them. A service waits for every service listed
against it.

| Layer | Service | Waits for | Health or completion check | Runs as |
| --- | --- | --- | --- | --- |
| 0 | `postgres` | nothing | `pg_isready -U postgres -d repovox` every 3 s | upstream `postgres:16.13-alpine` default |
| 0 | `redis` | nothing | `redis-cli ping` every 3 s | upstream `redis:7.4.9-alpine` default |
| 0 | `storage-config` | nothing | one-shot; writes the S3 identity file, exits 0 | UID 10001 (`repovox`) |
| 1 | `migrate` | `postgres` healthy | one-shot `alembic -c apps/api/alembic.ini upgrade head` | UID 10001 |
| 1 | `media-migrate` | `postgres` healthy | one-shot `alembic -c apps/api/alembic_media.ini upgrade head` | UID 10001 |
| 1 | `storage` | `storage-config` completed | `wget http://127.0.0.1:9333/cluster/status` every 3 s | upstream `chrislusf/seaweedfs:4.17` default |
| 2 | `storage-init` | `storage` healthy | one-shot; creates the private bucket, exits 0 | UID 10001 |
| 3 | `api` | `migrate`, `media-migrate`, `storage-init` completed; `redis` healthy | `GET /ready` every 5 s | UID 10001 |
| 3 | `worker` | as `api` | none (process state only) | UID 10001 |
| 3 | `dispatcher` | as `api` | none (process state only) | UID 10001 |
| 3 | `media-worker` | as `api` | none (process state only) | UID 10001 |
| 4 | `web` | `api` healthy | `GET /sign-in` every 5 s | `node` |
| - | `tests` | profile `test` only | runs `pytest`; never part of a deployment | UID 10001 |

`api`, `worker`, `dispatcher`, `media-worker` and `tests` share one hardened block: read-only
root file system, a 2 GiB `noexec,nosuid,nodev` `/tmp`, 1 CPU, 2 GiB memory, 128 processes,
all capabilities dropped and `no-new-privileges`. Only `api` (`127.0.0.1:8000`) and `web`
(`127.0.0.1:3000`) publish ports, both on loopback.

## 4. Build, migrate and start

1. Check out the reviewed commit and confirm it:

   ```sh
   git fetch origin
   git checkout <reviewed-commit-sha>
   git log -1 --format='%H %an'
   ```

2. Generate `.env` (section 2) and build the images:

   ```sh
   docker compose build
   ```

3. Start PostgreSQL and apply both migration chains. The core chain ends at revision `0004`
   and the media chain at `m001`; both are idempotent at head.

   ```sh
   docker compose up -d postgres
   docker compose run --rm migrate        # core repovox: alembic upgrade head -> 0004
   docker compose run --rm media-migrate  # repovox_media: alembic upgrade head -> m001
   docker compose exec -T postgres psql -U postgres -d repovox -tAc 'SELECT version_num FROM alembic_version'
   docker compose exec -T postgres psql -U postgres -d repovox_media -tAc 'SELECT version_num FROM alembic_version'
   ```

   The two queries print `0004` and `m001`. The media migration refuses to run against a
   database that contains `generation_jobs`, so it cannot be pointed at the core database.

4. Start everything else; Compose follows the order in section 3:

   ```sh
   docker compose up -d
   docker compose ps
   ```

   `postgres`, `redis`, `storage`, `api` and `web` report `healthy`; `storage-config`,
   `storage-init`, `migrate` and `media-migrate` show `exited (0)`; `worker`, `dispatcher` and
   `media-worker` show `running`.

## 5. Smoke checks

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/sign-in
docker compose exec -T web node -e 'console.log(require("next/package.json").version, require("sharp").versions.sharp)'
docker compose exec -T api python -c 'import ctypes; print(ctypes.CDLL(None).syscall(444, None, 0, 1))'
docker compose logs --since 5m worker dispatcher media-worker
```

| Check | Expected |
| --- | --- |
| `/health` | `{"status":"alive","version":"0.1.0"}`: the process answers; says nothing about dependencies |
| `/ready` | `{"status":"ready","generation_available":false,"environment":"development"}` (`"production"` in production mode); HTTP 503 with `database_unavailable` when the core database cannot be reached |
| `/sign-in` | `200` |
| Web versions | `16.4.6 0.35.5` |
| Landlock inside the API container | `1` or higher |
| Worker logs | no repeating `reconciliation_dependency_unavailable`, `media_handoff_dependency_unavailable` or `broker_unavailable` events |

An end-to-end analysis or video job is the only check that exercises parser containment and
GitHub egress together. Run one only against a repository you are entitled to analyse; a
containment failure is reported as `parser_isolation_unavailable` and an egress failure as
`github_unavailable`, `github_timeout` or `github_address_blocked`.

## 6. 24-hour retention lifecycle

| Data | Where | Lifetime | What deletes it |
| --- | --- | --- | --- |
| Analysis archive and analysis bodies | object storage, core metadata in `repovox` | job admission + 24 hours | API visibility ends at expiry; reconciliation deletes the expired job's prefix, including upload orphans ([deployment design](deployment.md#phase-2-local-execution-and-retention)) |
| Published videos, captions and metadata | object storage, rows in `repovox_media` | media job creation + 24 hours (`expires_at`) | `media-worker` reconciliation lists `mv.expired()`, deletes the job's objects, then records `mv.mark_deleted` |
| Media job deadline | `repovox_media` | 45 minutes from admission | stages past the deadline end; a lost worker's lease is fenced and retried or ended |
| Media admission | `repovox_media` | 20 jobs per owner per 30 days | refused at admission |
| Scratch files | container `/tmp` (tmpfs) | the job, at most the container's life | removed after each run; tmpfs disappears with the container |

Retention runs inside `media-worker` and the core reconciliation in `dispatcher`, so both must
be running for deletion to happen on time. Stopping them pauses deletion; it does not extend
what users can see, because visibility already fails closed at expiry.

## 7. Backup and restore

- **Databases.** Take logical backups of both databases with the superuser inside the
  `postgres` container, and of the role definitions separately (the role dump contains
  password hashes; treat it as a secret):

  ```sh
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  docker compose exec -T postgres pg_dump -U postgres -Fc repovox > "repovox-$stamp.dump"
  docker compose exec -T postgres pg_dump -U postgres -Fc repovox_media > "repovox_media-$stamp.dump"
  docker compose exec -T postgres pg_dumpall -U postgres --roles-only > "roles-$stamp.sql"
  ```

  Encrypt the files and keep them off the host. Restore only into a disposable instance first
  (`pg_restore -U postgres -d <database> --clean --if-exists <file>`) and check the
  `alembic_version` of each database before using it.
- **Object storage.** Do not back up the `storage-data` volume. Everything in it expires within
  24 hours (section 6); a copy would keep source archives and videos past the retention
  promise. After a restore, rows that point at objects that no longer exist expire through the
  same reconciliation.
- **Redis** is started without persistence (`--save ''`, `--appendonly no`) and holds nothing to
  back up. Jobs and dispatch events are durable in PostgreSQL
  ([ADR-0002](../adr/0002-durable-jobs.md)): the dispatcher leaves an event unacknowledged until
  the broker accepts it and retries on its next poll, and reconciliation fences stages whose
  lease or deadline expired. A Redis restart is designed to delay work, not to lose job state.
- **`.env`** is the only copy of the generated secrets. Keep an encrypted copy with the
  database backups, or plan to rotate every role password on restore.

## 8. Upgrade and rollback

1. Take the backups in section 7.
2. Check out the new reviewed commit, `docker compose build`, then run `migrate` and
   `media-migrate` as in section 4 before `docker compose up -d`.
3. Repeat the smoke checks in section 5.

Rolling back the application: check out the previous reviewed commit, rebuild and
`docker compose up -d`. Rolling back the database: restore the backups taken in step 1 into a
fresh volume. Do not use `alembic downgrade` on a database that holds data: the core `0004`
downgrade refuses while any pilot attempt exists (`pilot_rollback_requires_empty_ledger`) and
the media `m001` downgrade refuses while any media job exists
(`media_rollback_requires_empty_database`), so neither can discard history to make a rollback
look clean.

## 9. Compose readiness audit, 2026-11-18

Read-only audit of `docker-compose.yml`, `infrastructure/local/api.Dockerfile`,
`infrastructure/local/web.Dockerfile` (the images are built from these; there is no
`apps/api/Dockerfile` or `apps/web/Dockerfile`), `infrastructure/local/init-db.sh`,
`apps/api/repovox/core/config.py` and `tools/phase1_env.py`. Docker is not installed on the
machine the audit ran on, so `docker compose config` and `docker compose up` were **not** run
there; the files were checked statically, and the CI `integration` job builds and runs the
stack. The base files are unchanged. A4 to A6 are addressed only by the opt-in overlay
`infrastructure/local/docker-compose.prod.yml` ([Quickstart](#quickstart)).

| # | Finding | Effect | Follow-up (needs its own review) |
| --- | --- | --- | --- |
| A1 | `Settings.fail_closed` refused every production configuration | No production deployment was possible | Addressed by the GitHub identity adapter and the production rules above ([ADR-0024](../adr/0024-github-oauth-allowlist-identity.md)); independent security review still required |
| A2 | All 12 required `${VAR:?}` references are generated by `tools/phase1_env.py`, none is left over; `SYNTHETIC_SOURCE_DIR` is the only optional one | `.env` generation is complete | none |
| A3 | The `depends_on` graph has no cycle and every `service_healthy` target has a healthcheck; every `service_completed_successfully` target is a one-shot service | Startup order is deterministic (section 3) | none |
| A4 | `worker`, `dispatcher` and `media-worker` have no healthcheck in the base file | A hung process shows as `running` | Overlay: Celery ping for `worker`; process and dependency checks for the other two. A progress heartbeat is still open |
| A5 | `web` runs as `node` but without `read_only`, `cap_drop`, `no-new-privileges` or resource limits in the base file | Weaker isolation than the API services | Overlay: read-only root, all capabilities dropped, `no-new-privileges`, tmpfs `/tmp` and `/web/.next/cache`. Resource limits still open |
| A6 | `postgres`, `redis` and `storage` run as their upstream images' default users, without dropped capabilities, resource limits or a restart policy | A crash is not restarted automatically; resource use is unbounded | Overlay: `restart: unless-stopped`. Limits sized from measurements still open |
| A7 | Redis has no password and no persistence; it publishes no port | Reachable only from the compose network; queue contents are transient by design | Optional authentication |
| A8 | Only `api` and `web` publish ports, both on `127.0.0.1` | Nothing is exposed beyond the host | none |
| A9 | Every `REPOVOX_*` value in the compose file is read: by `Settings`, by a migration environment, by the tests, or (`REPOVOX_API_URL`) by the web route handler | No dead configuration | none |

## 10. Release verification and the dependency audit gate

The web application pins Next.js `16.4.6` (from `16.4.2`). `16.4.6` is outside the ranges of
[GHSA-mfr8-8qww-v76h](https://github.com/advisories/GHSA-mfr8-8qww-v76h) (`>= 16.3.0, <= 16.4.4`)
and [GHSA-vc7v-qv4w-wrv8](https://github.com/advisories/GHSA-vc7v-qv4w-wrv8)
(`>= 16.2.0, <= 16.4.4`); `sharp` stays `0.35.5`. CI asserts both versions.

The CI `frontend` job audits in two steps, by owner decision of 2026-11-18:

1. `npm audit --omit=dev --audit-level=high` is the blocking gate. It covers every runtime
   dependency that ships in the web image.
2. `npm audit --audit-level=high` then runs over all dependencies. When it fails, CI records a
   `Dev-only dependency advisory present` warning instead of failing the job: by that point the
   production audit has passed, so what remains is a development tool.

At the time of the decision, the full audit reported
[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf), a high-severity
`picomatch` ReDoS. It reaches the project only through the test runner
(`vitest` -> `vite` / `tinyglobby` -> `fdir` -> `picomatch`), which is not in the production
image (`.next/standalone` only). The advisory covers every published `picomatch` release up to
the latest, `4.0.7`, and npm's only suggested fix is a breaking downgrade of `vitest` to
`3.1.4`. The production audit reported no vulnerabilities. The warning stays visible on every
run until a patched `picomatch` is released.
