# ADR-0033: Secret-screen precision for templates, placeholders and local development URLs

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-21. Branch `fix/secret-screen-precision` from `main` at `869dc43`. Amends the content
rules restated in [ADR-0029](0029-prose-path-names-and-oversized-syntax-facts.md). Related:

- [threat model S-07](../security/threat-model.md)
- [static analysis notes](../development/analysis.md)
- [ADR-0011 parser process isolation](0011-parser-process-isolation.md)
- [ADR-0032 review corrections](0032-whole-repository-system-architecture-view.md#4-review-corrections-2026-11-21)

The following are unchanged:

- core migrations (`0004`) and the media database (`m001`);
- the analysis artifact contract (`schema_version` `2.3`) and `Limits.facts = 10_000`;
- every size, archive and fact cap;
- `Settings.fail_closed`, `AGENTS.md` and `docs/ai/`;
- `.env*`, key and credential file exclusion (`sensitive_path`).

## Context

Stage 2 screens every acquired byte with `repovox.analysis.privacy.scan`. Before this change, any
`scheme://user:pass@` URL and any 8-character literal in a `password`, `passwd`, `api_key`,
`access_token`, `secret` or `client_secret` field failed the whole repository with
`secret_detected`. The only exemptions were four literal words.

On 2026-11-21, live runs of six permissively licensed public repositories all failed Stage 2.
A diagnostic in the worker container classified every refused line. It fetched each archive
through the pinned GitHub transport, kept it in memory, and printed path, line and rule class,
never a value. The diagnostic found:

| Repository | Refused lines | What they were |
| --- | --- | --- |
| `fastapi-practices/fastapi-best-architecture` | 3 | `postgresql+asyncpg://…:<dev password>@host` in two example env files; `amqp://guest:<dev>@fba_rabbitmq` in `docker-compose.yml` |
| `Kanaries/pygwalker` | 1 | `mysql+pymysql://user:<dev>@host` in a docstring example |
| `mckaywrigley/chatbot-ui` | 1 | `secret = "env(SUPABASE_AUTH_EXTERNAL_APPLE_SECRET)"`, the Supabase configuration substitution |
| `microsoft/magentic-ui` | 16 | 14-character literal passwords and API keys in TypeScript tests (still refused) |
| `ChatGPTNextWeb/NextChat` | 32 | translated `Password: "<prompt text>"` strings (still refused) |
| `Stevemeg/Synthetic-Data` | 6 | 18 to 26-character literal database passwords on `localhost` (still refused) |

None of the first three held a secret. Each failure came from the generic assignment or URL
rule matching something that cannot carry a secret.

## Decision

### 1. Always refused, anywhere (tests, documentation and examples included)

- **Private key blocks.** `-----BEGIN … PRIVATE KEY-----` and PGP private key blocks.
- **Known provider formats.**
  - Unchanged and case-insensitive: `AKIA…`, `gh[pousr]_…`, `github_pat_…`, `sk_live_…`,
    `xox[baprs]-…`.
  - New and case-sensitive, as issued: `sk-…`, `sk-proj-…`, `sk-ant-…`, `ASIA…`, `AIza…`,
    `glpat-…`, `rk_live_…`, `hf_…`, `npm_…` and PyPI upload tokens.
  - Each new format needs the character mix every issued token has: a digit, or both letter
    cases for `hf_` and `npm_`. So `sk-xxxxxxxxxxxxxxxxxxxxxxxx` written as a placeholder is not
    taken for a key, while any real key is.
- **Remote credential URLs.** Any credential URL whose host is a dotted name or an IP address
  other than loopback, whatever its password, template or not.
- **Literal credential values.** Every value in the six credential fields that is neither a
  template nor a placeholder. This covers high-entropy random literals such as a 20-character
  mixed secret, and plain words such as `canary-secret-fixture` or `hunter2hunter`.

Provider formats and private keys are checked before any exemption and are never exempt.

### 2. Exempt, narrowly

**Interpolation templates (`templated`).** A value is a template when it contains one of the
forms below and its literal remainder is at most twelve characters of short plain pieces:

- f-string or `str.format`: `{password}`, `{settings.DB_PASSWORD}`, `{quote_plus(password)}`,
  `{os.environ['DB_PASSWORD']}`;
- shell or JavaScript: `${API_KEY}`, `${DB_HOST:-localhost}`, `$DB_PASS`;
- printf: `%(pass)s`, `%s`;
- Jinja or Mustache: `{{ db_password }}`;
- configuration substitution: `env(API_SECRET)`;
- documentation placeholders: `<your-api-key>`.

The name inside a template must look like a variable:
- snake_case or lower-case dotted, ALL_CAPS, or camelCase without digits;
- optionally with attribute or subscript steps, or a call on such names.

Several things therefore stay refused:
- a random secret in braces (`{Kx9mP2qR7vL4}`) or in `env(…)`;
- a secret containing `$X`, since `$NAME` must not follow a letter or digit;
- a remainder that mixes letters and digits.

**Placeholders (`placeholder`).** A value is a placeholder when it is one of these:
- made only of these words, split on `-`, `_`, space or `.`: your, my, api, key, here,
  change, me, changeme, changethis, this, replace, replaceme, placeholder, example, sample,
  dummy, fake, mock, test, testing, secret, password, pass, token, not, a, the, value, insert,
  put, enter, redacted;
- a mask of `x` or `*` (`xxxxxxxx`, `********`); a run of any other repeated character, such
  as the `kkkk…` stand-in secret that ADR-0029's tests use, still fails;
- an ascending digit run (`12345678`).

A placeholder cannot carry entropy, because every word is from a fixed public list.

**Local development credential URLs (`credential_url_allowed`).** A credential URL is exempt
only when one of these holds:
1. Its password is a template, and its host is a template or local.
2. Its scheme is a database or queue scheme (`postgres*`, `mysql*`, `mariadb`, `redis`,
   `rediss`, `mongodb*`, `amqp*`), its host is local, and its password is a development value
   of at most 32 characters. The development values are `password`, `passwd`, `pass`,
   `postgres`, `root`, `admin`, `test`, `dev`, `changeme`, `secret`, `guest`, `123456`,
   `12345678`, or any placeholder.

A host is local when it is one of these:
- loopback: `localhost`, `127.0.0.1` or `::1`;
- a **single-label name with no dot**, such as the Compose names `postgres`, `db`, `redis`,
  `mysql`, `fba_rabbitmq`, or a documentation `host`.

**Single-label hosts go one step beyond the original request**, which listed only `postgres`,
`db`, `redis` and `mysql`. The evidence above shows two real repositories using `host` and a
project-prefixed Compose service name. A dotless name is never a public DNS name or an IP
address: it resolves only through a local resolver, Compose or Kubernetes service DNS, or
`/etc/hosts`. A single-label host is exempt only together with a development password, so
`postgresql://app:<random>@proddb` still fails. A dotted name, including
`mq.internal.example.com`, never counts as local. HTTP(S) URLs never get the development
password exemption.

### 3. What does not change

- **Entropy redaction.** The spans that `redact()` records are computed exactly as before.
- **Shared screen.** Path screening (ADR-0029), branch-name checks and the evaluation custody
  tools use the same `scan()`, so one rule holds everywhere.
- **Artifacts.** A repository that passed before passes identically, because an exemption only
  stops a refusal. Its artifacts are byte-identical, so the rule version `static-rules-v2` is
  not changed.
- **No override.** There is still no per-file or per-path override. A secret in `tests/`,
  `README.md` or `docs/` fails exactly like one in source.

### 4. Companion story fix (`media.story_extract`)

ADR-0032 made claim matching need a specific shared word. As a result, on
`openai/openai-cs-agents-demo` "A python backend that handles the agent orchestration logic…"
became a false README-only feature: its words (`backend`, `agent`, `service`) are all generic.

A statement that names a language or framework and a layer ("python backend", "FastAPI
backend", "TypeScript/Next.js frontend", "Next.js UI") now names that layer. It is backed, in
this order, by:
1. an entry point;
2. a technology import;
3. the first declaration.

Each must be in a file of that language under a folder named for the layer: `backend`,
`server`, `api` or `services` for a backend, and `frontend`, `ui`, `client` or `web` for a
frontend. This applies only when nothing else backs the statement.

The cross-language rule is unchanged. A "Next.js UI" claim is backed only by script code and
never by a Python class such as `AirlineAgentChatContext`, and colon lead-ins stay excluded.

## Threat model

| Concern | Effect |
| --- | --- |
| A real key in a placeholder's shape | Provider formats are checked first. A placeholder in a key's shape (`sk-xxxx…`) lacks the digit or capitals issued keys have, so it passes; a real key does not. |
| A secret disguised as a template | The variable name must look like a name, and the literal remainder must be short and unmixed. A random run inside braces, `env()` or after `$` still fails. |
| A production password to an internal host | Only development values are exempt. A random password to `localhost` or a single-label service still fails. |
| A real remote endpoint | Dotted names and non-loopback IPs are never local, even with a templated password. |
| Over-broad words | The placeholder vocabulary is fixed and public. Concatenations (`testpassword123`) and other words (`canary`, `fixture`) are not placeholders. |
| Residual | Scanners have false negatives and false positives. Passphrases and translated prompt strings in credential fields still fail closed. There is still no user override. |

## Consequences

Measured with the diagnostic on the archives above:
- `fastapi-best-architecture`, `pygwalker` and `chatbot-ui` now have no refused line;
- `magentic-ui`, `NextChat` and `Synthetic-Data` still fail, on literal credential values.

On the `openai-cs-agents-demo` README, the python-backend statement is backed by Python code in
`python-backend/` instead of being reported as README-only.

## Rollback

Revert the commits. No migration, schema or stored artifact changes.

## Tests

`tests/unit/test_secret_screen_precision.py` covers the following. Every secret-shaped value is
assembled at run time, so the history scan stays clean.
- **Must pass:**
  - f-string, `str.format`, shell, printf, Jinja, `env()` and `<…>` templates;
  - placeholder words, `x` or `*` masks and digit runs;
  - loopback, Compose-service and documentation-host development URLs;
  - in a real `filter_sources` run, the same content in `tests/` and `README.md`, with
    `.env.example` still excluded as a sensitive path.
- **Must fail:**
  - `sk-proj-`, `sk-ant-`, `sk-`, `ghp_`, `gho_`, `github_pat_`, `AKIA`, `ASIA`, `AIza`,
    `xoxb-`, `xoxp-`, `glpat-`, `sk_live_`, `rk_live_`, PEM and OpenSSH keys;
  - high-entropy and plain literals, secrets in braces, after `$` or inside `env()`;
  - remote, IP and dotted-internal hosts; random passwords to `localhost` or a service name;
    HTTP(S) URLs with a development password;
  - all of the above inside `tests/`, `README.md` and `docs/`.

`tests/unit/test_engineering_story.py` checks that the python-backend statement is backed
only by `python-backend/` Python code, while the Next.js UI statement never cites a Python
file.
