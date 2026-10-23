# Botocore trust hardening review handoff

Date: 2026-10-23. Branch: `security/botocore-trust-hardening`, stacked on exact
PR #13 `caf540fb582a0609acb0e62728467e6a58ce9f50`. Status: independent review
required; no AWS activation, merge or deployment. [ADR-0023](../adr/0023-sdk-certificate-trust-boundary.md).

## Finding and upstream resolution

The prior application/dev/runtime lock selects boto3/botocore **1.43.111** and
s3transfer **0.19.2**. The independent cfn-lint lock selects boto3/botocore
**1.43.116**, s3transfer **0.19.3**. Actual previous installed .111 files and
hash-verified upstream .111/.116 wheels have a **127-root** fallback bundle:
SHA-256 `ed93d6346236d4f0278f617f5245091f37d001806a49ce42ce0ad5bec858d28e`.
It contains AAA Certificate Services DER
`d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4`.
Display names are not used for acceptance. The emSign ECC G3 blocked DER is
`86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`.

The [official botocore 1.43.118 distribution](https://pypi.org/project/botocore/1.43.118/)
was published October 22. Its actual wheel was downloaded over normal verified
HTTPS, checked against PyPI SHA-256, and opened without executing it. Its
[bundled source](https://github.com/boto/botocore/blob/1.43.118/botocore/cacert.pem)
has **126 roots**, neither blocked fingerprint, SHA-256
`4658f1ddf2d0a9e70c8f760323704c8fb9c0bf2f1f1e7d2dbc5939ca04ea2612`.
Wheel SHA-256: `a45d7ae570674161e4a3542d8c68633bf7503f92d1de781ef7361b79488eda6f`.
Source archive: `7f3f9d88cc9e847587690f82a42e3c3c292c3026c92c1e60d68a9310018e003f`.
Provenance is upstream HTTPS, release metadata, lock hashes and original artifact
inspection; no unverified signing identity or AWS attestation is invented.

Only botocore upgrades to **1.43.118**. Existing boto3 versions permit it within
their >=1.43.x,<1.44 range, and existing s3transfer versions remain compatible.
The application lock has the same 104 records; only botocore and root metadata
change. cfn-lint retains 27 packages and changes only botocore's version/artifact
hashes. No unrelated dependency or type-stub refresh is required.

This upstream wheel changes service/endpoint model data and seven non-model
package files across the seven patch releases, including auth, credentials,
endpoint provider, HTTPS session, documentation and bundle/version files. We retain
the complete 987-member archive difference. Compatibility is assessed through
existing parameter/model validation, synthetic SDK adapter/cleanup tests and real
local S3 integration, not an unsupported claim of AWS service compatibility.

## Enforced selection and configuration precedence

`repovox.sdk_trust` is the shared boundary for application S3 storage, local bucket
initialization and the synthetic SDK harness. The offline AWS adapter rejects
bypassed clients before its existing refusal. Model-only imports (validation and
DynamoDB type serialization) create no transport and need no factory.

`approved_trust` requires botocore 1.43.118 and certifi 2026.10.19, validates installed
distribution inventory/path containment, regular single-link files and exact
bundle bytes. Parsing uses a fresh explicit SSLContext, not the Windows default
store. Full DER fingerprint lists are emitted by `tools/security_sdk_check.py`.
Approved certifi: **120 roots**, SHA-256
`50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785`.
Botocore's actual `get_cert_path(True)` must select that exact certifi path.

The SDK's upstream `get_cert_path` returns arbitrary explicit verify paths unchanged
and catches missing certifi to select its own bundle. A default certifi import
therefore never constituted a complete policy. Our factory rejects any verify
argument other than True, then supplies its own verified certifi path. Missing
certifi, wrong interpreter, unknown SDK version, malformed/replaced bytes or a
selected fallback path fail before session/transport construction.

The [official configuration precedence](https://docs.aws.amazon.com/boto3/latest/guide/configuration.html)
includes environment/shared CA configuration and independent HTTPS proxy options.
We reject present AWS_CA_BUNDLE, AWS_CONFIG_FILE, AWS_SHARED_CREDENTIALS_FILE,
AWS_PROFILE, AWS_DEFAULT_PROFILE, REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE, SSL_CERT_FILE,
SSL_CERT_DIR, proxy environment names (case-insensitive), AWS_ENDPOINT_URL* and
nonempty Config proxies/proxies_config or client_cert. Values are never logged.
Default ~/.aws files are ignored through public `set_config_variable` paths pointing
to the OS null device, with explicit synthetic/local credentials and region.
No credential discovery, metadata service, owner AWS profile or private key is used.

Before-send checks re-read files and revalidate effective transport verification
and proxy settings. Parsed validation is cached only by complete immutable input
bytes plus expected hash; changed bytes cannot hit a previous successful cache
entry. A marker alone does not authorize a client: actual transport settings are
checked too. Private transport attributes are read-only, version-bound inspection;
no third-party internals or PEMs are monkeypatched.

## Installation profiles and reproduction

| Profile | boto3 / s3transfer | Final botocore | Effective trust |
| --- | --- | --- | --- |
| Application/development | 1.43.111 / 0.19.2 | 1.43.118 | Explicit validated certifi |
| Runtime without development group | 1.43.111 / 0.19.2 | 1.43.118 | Same; actual synthetic storage constructor checked |
| Isolated cfn-lint | 1.43.116 / 0.19.3 | 1.43.118 | Both bundles validated; Python socket connections prohibited |
| Fresh disposable API/test images | Application lock | 1.43.118 | Build and restricted runtime checks; final image IDs in PR |
| Offline AWS fixtures/adapters | Application lock | 1.43.118 | Factory validated; existing independent network refusal retained |

Use patched tooling and a fresh environment, without using old global pip:

```sh
uv sync --frozen --link-mode copy
uv run python tools/security_sdk_check.py
uv run pytest tests/unit/test_sdk_trust.py -q
UV_PROJECT_ENVIRONMENT=/tmp/repovox-runtime uv sync --frozen --link-mode copy --no-dev
/tmp/repovox-runtime/bin/python tools/security_sdk_check.py --synthetic-storage
```

The last command installs a process-local socket refusal and constructs only a
synthetic local HTTP storage client; it sends no request. cfn-lint is installed
separately using the existing hash-verified pip bootstrap and complete hashed lock,
then run via `tools/security_sdk_lint.py --template ...`. This trusted static-tool
wrapper validates CA files and prohibits Python socket/DNS operations throughout
the process. It is not permission to run update-specs, CloudFormation operations,
arbitrary plugins/native code or deployment. Direct cfn-lint/AWS CLI use outside
this wrapper is not a supported RepoVox execution path.

Controlled installs use copy mode because uv cache hard links failed the strict
single-link file check. We preserve that rejection and reinstall copies rather
than weakening validation. A runtime-only test also exposed a prior import of a
development typing package; that import is now TYPE_CHECKING-only. No new runtime
dependency or S3 behavior was introduced by that correction.

## Adversarial verification and limitations

Tests distinguish actual installed files from synthetic negative mutations. They
cover normal selection, real no-dev construction, absent packages in a real minimal
venv, missing certifi import, corrupt/changed CA bytes, actual AAA reintroduction,
all ambient override classes, invalid/custom verify paths, verify=False/None,
proxy/client certificates, default shared files, changed selected path/transport,
wrong interpreter, unknown versions, offline Stubber behavior, transport-construction
inventory and a real socket audit refusal before the socket can connect.
Imported SDK versions/module locations must agree with the selected distribution,
including cached or shadowed modules; metadata alone cannot attest the loaded code.

The original focused test failed because an extra fixture-level refusal changed
the expected existing AWS error class. The harness retains the accepted independent
before-send refusal, and the added TLS hook validates trust without replacing that
error. Original failure logs are preserved. Lint/type issues were fixed without
waivers. Full Linux, PostgreSQL, restricted custody, Node/frontend/browser, audits,
media and secret-scan results are reported at the exact final head in the draft PR.
Initial Linux integration rejected the new minimal-venv test's copied interpreter
on the existing noexec scratch mount. The test now uses standard POSIX venv
symlinks to the trusted installed interpreter, preserving noexec, assertions and
the actual empty environment. No copied scratch executable or permission waiver.

The first host environment selected old Python 3.11.0. The cfn-lint lock's existing
networkx 3.7 requires Python 3.12, so that installation failed and was preserved;
no dependency was downgraded. Its full application run also hit two unchanged
legacy tests: an old ensurepip seed layout lacks the expected pip CA member, and
the DNS transport's synthetic TLS fixture lacks a Python-3.11-required attribute.
Their source is unchanged from the accepted base. The new trust/adapter tests
passed on 3.11, but full 3.11 compatibility is not claimed. Complete application
and lint verification uses the established Python 3.12 CI profile. Global Python,
seed files and frozen analyzer tests were not modified to hide those host findings.

Security claim: these selected, locked, inspected paths remove both known blocked
roots and prevent RepoVox clients from accepting an unreviewed CA override or
missing-certifi fallback. The upstream SDK itself still accepts raw verify=False
and arbitrary paths; arbitrary external SDK consumers are not made safe by this
factory. Old environments remain unsupported and fail closed until reinstalled.
The old .111/.116 bundle remains UNRESOLVED_DORMANT_CA wherever still installed;
no existing environment or historical image is silently claimed migrated. The
existing `all_bundled_stores_remediated` output applies only to the inspected
selected Python profile, never every host/image/platform trust store.

The owner Windows system store and unrelated tools remain separate maintenance
obligations. No global store is modified. Neither these tests nor a clean audit
proves universal PKI validity, exploitation resistance, actual AWS authorization,
provider behavior or independent acceptance. Existing read-only/identity controls
are required; hostile same-process code and privileged host races are outside this
Python policy boundary.

Original public engineering evidence is outside Git/OneDrive at
`C:\Users\konab\AppData\Local\RepoVox\botocore-trust-bcb5e8e0cae541cc8f7a3733afe11c52`.
PRs #9–#13 remain draft/unmerged and unchanged. Frozen analyzer/scorer, control SQL,
migration 0004, custody/evidence, owner keys, historical 0/84, November deadlines,
CR-04 pending and official EVAL-ENTRY UNFROZEN remain unchanged. No AWS requests,
credentials, provisioning/spend, real acquisition/pilot/gold/A/B, reveal, scoring,
merge, deployment, training or Phase 3/6.
