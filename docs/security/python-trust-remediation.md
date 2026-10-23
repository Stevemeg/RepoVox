# Isolated Python trust-store remediation

Date: 2026-10-23. Status: draft security engineering for independent review.
Base: PR #11 `0aad19c041f9a854a60ea4636c202c03abd9ee82`.
Branch: `security/python-ca-bootstrap`. No merge, deployment or release approval.
PRs #9/#10/#11 keep their original heads, descriptions and draft/unmerged state.
Final head, command evidence and CI results are recorded in the new draft PR.

## Finding and upstream authority

The [PSF security announcement](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)
requires certifi 2026.10.19, pip 26.2.2, uv 0.13.4 and affected sigstore 4.5.1 or
newer. These are minimum incident fixes, not a guarantee against all future issues.
The [certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
lists 2026.10.18, but PSF recommends 2026.10.19 for compatibility with unaffected
roots. [uv 0.13.4](https://github.com/astral-sh/uv/releases/tag/0.13.4) updates its
embedded `webpki-root-certs` to 1.0.10. Its roots are independent of Python certifi.
No evidence of an actual RepoVox compromise is asserted.

System trust is an independent path too: signed Ubuntu
[USN-8944-1](https://ubuntu.com/security/notices/USN-8944-1) and Debian
[DSA-6572-1](https://lists.debian.org/debian-security-announce/2026/msg00487.html)
remove affected roots. All disposable Python CI jobs refresh only official
Ubuntu source metadata/CA packages before bootstrapping and inspect effective
roots. The API image refreshes signed Debian CA packages. No system trust check
is disabled to accommodate a stale runner image.

## Installation inventory

| Surface at original head | Original affected component | Draft correction |
|---|---|---|
| Application/development `uv.lock` | certifi 2026.7.22 | 2026.10.19; direct runtime minimum, including no-dev installs |
| `pip-api` transitive dependency in the same lock | pip 26.2.1, independently vendored certifi | pip 26.2.2; direct dev minimum |
| Python quality and offline media CI | uv 0.11.29, seeded runner pip | verified pip wheel first, then hash-pinned uv 0.13.4 |
| API/worker/tests/migration/storage-helper image | copied uv 0.11.29; base pip and ensurepip seed; system roots | same bootstrap, replace dormant seed, signed Debian CA refresh, strict inspection |
| Disposable cfn-lint environment | pip 26.2.0; no standalone certifi, activating botocore fallback | pip 26.2.2 and explicit certifi 2026.10.19; all 26 prior package versions retained, now 27 hash-locked packages |
| Host integration smoke | unpinned transitive certifi from standalone HTTPX installation | use the existing application's locked HTTPX/environment; same host smoke code |
| Documented local/docs installs | unspecified host pip/uv | explicit selected-environment bootstrap prerequisite |
| botocore fallback PEM (app 1.43.111; lint 1.43.116) | AAA Certificate Services remains in the fallback | active standalone certifi is patched; fallback remains explicitly unresolved; SDK unchanged |

There are no Sigstore, conda or pixi distributions in the application lock,
temporary lint requirements, bootstrap requirements or Dockerfile. No speculative
Sigstore dependency is added. This is a repository-controlled installation-path
inventory, not an inventory of unrelated software installed on the owner's PC,
GitHub's whole runner, Windows Docker Desktop or a VMware guest.

## Hash-anchored bootstrap

[security_bootstrap.py](../../tools/security_bootstrap.py) downloads exactly the pip
26.2.2 wheel identified by PSF, with normal HTTPS verification enabled, and checks
its full SHA-256 **before executing anything from it**. The expected hash comes
from the independently consulted PSF announcement, not the download response:

```text
pip wheel: fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70
certifi wheel: 42d35340cc5b9ba78e818ddbff0c5b1c2b779de448a340fd1b989f5fa8670e1b
certifi sdist: 035c1e85572b141bf1c3a3eff0e33a8eb74917522f2559075ff8d2fea780a1ae
uv Linux x86-64 wheel: 05e4332791b4d55b6dde8695b7fa6079b26991519f44760887c5dfbd5ca4fe53
uv Windows x86-64 wheel: b2ff80397273fff0e02c20eacae6882834c811827d6fc08f658db156fe754386
```

The verified wheel executes in isolated Python mode and installs itself with
`--no-index --no-deps`; neither old pip nor old uv makes a bootstrap network
request. The patched pip then installs only uv 0.13.4 using
[requirements-bootstrap.txt](../../tools/requirements-bootstrap.txt), all upstream
wheel hashes, `--require-hashes --only-binary=:all: --no-deps`, and HTTPS PyPI.
No insecure index, trusted-host exception, certificate-validation override or
vulnerability-ignore rule is introduced. A network attacker can deny availability
but cannot substitute an executable wheel without breaking the pinned hash.
The trust assumption is the independently reviewed PSF hash and repository change
review; checksums fetched alongside compromised bytes alone would be insufficient.

Only public package bytes use an automatically cleaned temporary directory.
No protected evidence, source, prediction or owner key is involved.

For an explicitly selected **disposable** virtual environment:

```powershell
python -m venv --without-pip C:\path\to\new-disposable-environment
C:\path\to\new-disposable-environment\Scripts\python.exe tools/security_bootstrap.py
# Activate it so the hash-installed uv, rather than a different PATH binary, runs.
# Then run uv sync --frozen using a fresh UV_PROJECT_ENVIRONMENT if needed.
```

Do not run this against an unrelated persistent interpreter. This remediation does
not globally repair the owner's existing Python installations. Original host
Python/uv and unrelated environments are deliberately left unchanged; never reuse
their old package managers for network installation. Seeded environments must be
bootstrapped before any network use, even if their application certifi is current.

## Dormant seeds and effective trust inspection

Fresh CI and image builds explicitly pass `--repair-ensurepip`. On the reviewed
CPython layout this replaces the original pip wheel and `_PIP_VERSION` constant,
preserving seed functionality. It refuses an unknown layout, external seed
directory, extra wheel, symlink or invocation from a venv targeting its shared
base. A failed partial image build is not published. This narrow stdlib seed
change is confined to disposable CI/image Python, not host-wide mutation. Future
venvs created from that repaired base receive the verified patched pip seed.

[security_trust.py](../../tools/security_trust.py) separately inspects:

- Active standalone certifi and pip's vendored PEM, their hashes and DER roots.
- Installed pip/certifi/uv versions; sigstore minimum only if actually installed.
- Dormant ensurepip wheel contents and full original PSF wheel commitment.
- Effective default OpenSSL/system CA roots, not just the application bundle.
- The actual PATH uv version, selected Python scripts location and binary SHA-256.

The exact removed DER anchor (emSign ECC Root CA - G3) is
`86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`.
It was independently derived by comparing hash-verified original and patched
certifi wheels. Patched certifi and pip vendored PEMs have 120 roots and SHA-256
`50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785`.
No certificate subjects/comments are used as the security identity. This targeted
anchor check is not a universal revocation/PKI correctness test. uv's compiled
Rust roots are opaque to this PEM checker: evidence is the verified patched wheel,
upstream release dependency change, actual executable version and recorded hash,
not a claim of extracting or independently rebuilding its Rust bundle.

The independent installed-file inventory found three Python PEM stores: standalone
certifi, pip's vendor and botocore's fallback. The latter's SHA-256 is
`ed93d6346236d4f0278f617f5245091f37d001806a49ce42ce0ad5bec858d28e`, with 127 roots.
It retains AAA Certificate Services, DER SHA-256
`d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4`, also named in
DSA-6572-1. The checker now rejects both listed roots in active/system stores and
records the fallback as `UNRESOLVED_DORMANT_CA` and
`all_bundled_stores_remediated: false`. Its zero exit status means **active-store
checks passed**, not complete remediation of dormant bundles. No false overall
acceptance follows from that exit status.

Offline inspection of the [SDK's local certificate selection](https://github.com/boto/botocore/blob/develop/botocore/httpsession.py)
and installed `get_cert_path(True)` proves the tested environment selects the
patched certifi PEM; no AWS client/request or credential is used. If that selected
store is affected, inspection rejects it. The fallback remains a blocker for
repository-wide trust acceptance, especially for dependency profiles without
certifi. A separately reviewed SDK/bundle resolution is needed; no ad hoc editing
of third-party CA files, unreviewed SDK upgrade or AWS behavior change is made.

The first local inspection intentionally remained failed until the separately
locked pip 26.2.1 was corrected; original stderr is retained. The owner's shared
Python 3.12.0 ensurepip seed remains old and is reported `clean: false` in local
non-strict observations. It is not used for network bootstrap and not claimed
patched. **CI and rebuilt image checks require `--seed`; they cannot pass this
condition.** No permissive flag is used to waive their seed gate.

## Minimal resolution and compatibility

104 application lock entries remain. Only certifi and pip change package versions;
all unrelated package records remain byte-equivalent after parsing. Root metadata
gains runtime certifi and development pip security minimums. uv 0.13.4 rewrites lock revision 3
to revision 5; old uv is therefore unsupported for this remediation branch.
Parser, analysis/scoring, SQL, migrations, custody and AWS behavior are untouched.

The [lint tooling lock](../../tools/requirements-cfn-lint.txt) preserves the exact
26 packages observed in original CI 39540415375, plus required certifi 2026.10.19;
pip is bootstrapped separately. Normal and no-dev application profiles now require
patched certifi without modifying SDK service behavior.
No application dependency is upgraded to accommodate lint tooling. The temporary
lint environment's separate pip/vendored store is inspected and audited.

The API image retains Python 3.12.12 and normal UID 10001 behavior. It refreshes
signed Debian `ca-certificates`, uses the same verified bootstrap instead of the
old uv image, and validates both base and application Python. CI rebuilds with
`--pull --no-cache`; records image identity, CA package version, root/bundle hashes;
and audits application and base site-packages separately. Public old certificates
may remain in immutable ancestor image layers, but are not loadable through the
final filesystem's trust/ensurepip paths. Cached or already deployed images are
**not** repaired by this branch. No deployment or persistent runtime is changed.

## Required verification and review limits

The existing full workflow and media workflow also trigger for a draft PR based
on `experiment/offline-source-to-video`. All prior checks remain; additive gates
cover security tool formatting/types, strict trust inspections and separate audit
of bootstrap/base/lint environments. Disposable services remain PostgreSQL, Redis
and local S3; no real AWS endpoint or custodian is used.

Commands and exact results are attached to the final-head draft PR:

```text
uv sync --frozen
python tools/security_trust.py --uv --seed
uv run python tools/security_trust.py --certifi --seed
uv run pip-audit --local
uv run pip-audit --path <bootstrap/base/lint site-packages>
uv run pytest tests/unit -q
uv run ruff check tools/security_*.py tests/unit/test_security_bootstrap.py
uv run ruff format --check tools/security_*.py tests/unit/test_security_bootstrap.py
uv run mypy --strict tools/security_bootstrap.py tools/security_trust.py
docker compose build --pull --no-cache migrate tests
```

The new offline negatives cover corrupt bootstrap bytes, empty and relabeled bad
CA stores, duplicate/unknown seed inventories and external seed substitution.
Real CI must separately exercise fresh bootstrapping, dormant-seed replacement,
container scans, all PostgreSQL/security/service tests and actual media decoding.
Audit success is advisory-database evidence only; it does not prove CA correctness,
all OS/browser/Node/image vulnerabilities absent, or universal MITM resistance.
`repovox` is local unpublished code and cannot be audited as a PyPI distribution;
that explicit tool limitation is reported, not suppressed.

Independent reviewers must inspect the hash provenance, effective/dormant stores,
unaffected lock records, precise CI checks and final image results. No independent
security acceptance is self-awarded. Original PR heads and all historical evidence
remain untouched; the new branch must never be described as patching old heads.

First Linux runs at `45f885a` failed closed on the stale runner's system roots
after patched pip/uv/seed installation. The follow-up refreshes the official
Ubuntu CA security package before bootstrap; the root rejection is unchanged.
Those failed runs are preserved, not relabeled as passes.

At `33f5dca`, the Python job passed all audits and 823 tests (99 explicit skips).
Rebuilt image base/application/seed inspections passed. Its new container audit
then failed because its default cache path was under the read-only home directory.
The follow-up directs only audit cache into the existing bounded `/tmp` tmpfs;
read-only root, UID, capabilities, network rules and audit assertions are unchanged.

The same run found a **separate pre-existing frontend security blocker** in
unchanged Next.js 16.4.0: npm audit reports critical findings
[GHSA-2464-fhr4-w9xw](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw),
[GHSA-p3m5-59mp-jv5r](https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r)
and [GHSA-673q-mjm6-r5xr](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr).
It lists Next.js 16.4.2 as a fix outside the current exact constraint. Frontend
lint/types/17 tests/build passed; its audit did not. This Python-only correction
does not change the Node lockfile, suppress the audit or claim overall green CI.
Separate owner authorization/review is required for that unrelated remediation.

The bundled-CA inventory also inspected installed Node 24.18.0 with its `tls` and
`crypto.X509Certificate` APIs: 120 bundled roots, including the exact removed
emSign ECC G3 DER fingerprint above. The web Dockerfile and frontend/browser CI
pin that Node release. [Node's October security release](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
and [Node 24.22.1](https://nodejs.org/en/blog/release/v24.22.1) describe updated
roots and other security fixes. Node/Next/npm changes are **not** silently folded
into this isolated Python remediation. Neither a patched system store nor Python
certifi repairs Node's bundled roots. Thus repository-wide trust remediation and
all-green security acceptance remain **blocked** pending a separately authorized
Node/Next follow-up. No Node process/image or unrelated host installation is
claimed patched, and no production server is started or promoted here.

At `6b6ed35`, the expanded checker correctly rejected cfn-lint's active botocore
fallback because that isolated environment had no standalone certifi. The final
follow-up adds pinned certifi to that tooling environment and makes certifi an
application **runtime** requirement. All 26 existing lint package versions and
all unrelated application records remain fixed. An additional real locked
`--no-dev` install/inspection/audit gate prevents a development-only fix from
concealing an affected runtime profile. SDK code and service models are unchanged.

The expanded two-anchor check also rejects the owner's unchanged Windows default
store because AAA Certificate Services remains present. Earlier G3-only local
observations are retained, but do not establish complete current system trust.
No Windows CA/registry/global installation is edited. All new downloads are
hash-anchored or use the reviewed patched CA bundle explicitly; authenticated
handoff transport uses that bundle without loading the affected default roots.
The seed/PATH unit tests use labeled synthetic OS contexts to test their intended
boundaries; mandatory Linux/CLI system checks still inspect real roots. Existing
host remediation remains a separate operator obligation, not an automatic fix.

Historical deadlines remain 2026-11-14 17:43:39 UTC and 2026-11-16 16:53:29 UTC.
No historical custodian or owner key is accessed. Historical 0/84 is unchanged,
EVAL-ENTRY remains UNFROZEN, CR-04 remains pending. No cloud, pilot, protected A/B,
reveal, scoring, paid service, promotion, merge or Phase 3/6 is authorized.
