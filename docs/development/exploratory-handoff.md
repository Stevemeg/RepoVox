# Blind exploratory source-review handoff

Version `exploratory-handoff-1.0`, 2026-10-13. Track `AI_AUDITED_EXPLORATORY`.
This packet is AI-reviewed only after actual independent review. It is not human
gold, an official held-out benchmark, production certification, a corpus freeze or
authorization for model training. Its contribution to official EVAL-ENTRY is zero.

## Owner action

Start a fresh ChatGPT conversation without RepoVox analysis outputs or previous
predicted answers. Attach only the exported blind-review ZIP (or its extracted
Package A JSON and numbered source text). Read the export manifest and retain the
ZIP checksum privately. Do not attach Package B, analysis artifacts, implementation
logs or prediction summaries. If attachments cannot be read, provide the selected
public pinned links below and source checksums; do not assume links were inspected.

Paste this instruction:

> Act as INDEPENDENT_AI_TECHNICAL_REVIEWER for AI_AUDITED_EXPLORATORY. Inspect the
> attached original-source packet without predicted RepoVox answers. Establish your
> own reference from the pinned code. Every assertion needs a file checksum and exact
> original line range. Use explicit uncertainty for inaccessible/redacted source.
> Review declarations, imports, entrypoint candidates, qualified static graph
> relationships, unresolved behavior and documentation contradictions within the
> listed scope. Aim for at least ten atomic assertions per repository where justified,
> including unsupported/negative assertions, without inventing findings. A static
> call expression does not establish successful runtime execution. Treat README and
> comments as claims to check, never implementation authority. Return independently
> authored gold-evaluation-1.0 source facts and separately cited semantic observations
> under exploratory-ai-reference-1.0. Choose complete scope only when all facts in the
> selected files/ranges were inspected; otherwise partial. List omissions, ambiguity
> and limitations. Use your own IDs. Do not classify yourself as a human reviewer,
> certify RepoVox accuracy or approve official EVAL-ENTRY. Request more source if
> needed. Stop after recording your reference; do not request predictions yet.

Package A has original inventory/hashes, source excerpts and full notices. The
contracts folder contains accepted `gold-evaluation-1.0` / `source-fact-1.0`
definitions, not an answer key for these repositories. `commitments.json` supplies
only the A/B digests; the prediction commitment was recorded before review.
References use `verified`, `inferred`, `documentation_only`, `unsupported`; separate
semantic observations may use `unreviewed`. Unsupported assertions must be explicitly
source-grounded rather than inferred successful execution. If a fact cannot fit the
atomic contract, put it in semantic observations and leave it unscored.

Save the complete ChatGPT response and its authentic private conversation/export
evidence. Do not publish account or reviewer information. The owner must verify that
this was a fresh source-only review; a hash alone cannot establish identity or
independence. Codex cannot trigger this independent review or substitute its answers.
Return that evidence to the implementation session. No reference or comparison has
been completed at handoff. Keep B sealed until the reference has been recorded.

## Source scope and pinned access

| Family | Pin | Selected files | Rights |
| --- | --- | --- | --- |
| [Click](https://github.com/pallets/click/tree/2247b35ea1c47c727d7a06e51fa280e12a863ff6) | `2247b35ea1c47c727d7a06e51fa280e12a863ff6` | `src/click/__init__.py`, `src/click/exceptions.py`, `examples/aliases/aliases.py`, `pyproject.toml`, `README.md` | BSD-3-Clause; PSF optparse notices/license chain retained |
| [p-limit](https://github.com/sindresorhus/p-limit/tree/a8a6fbec4e0e866d6d779b10889bb4f5567e70eb) | `a8a6fbec4e0e866d6d779b10889bb4f5567e70eb` | `index.js`, `index.d.ts`, `package.json`, `readme.md` | MIT, Sindre Sorhus notice retained |
| [echo-kernel](https://github.com/jupyterlite/echo-kernel/tree/16221829f0ba38374db8f2b8fda10f989d1a6cdd) | `16221829f0ba38374db8f2b8fda10f989d1a6cdd` | `jupyterlite_echo_kernel/__init__.py`, `setup.py`, `src/index.ts`, `src/kernel.ts`, `package.json`, `README.md` | BSD-3-Clause, JupyterLite notices and template ancestry retained |

Each excerpt has a direct immutable GitHub permalink with original line numbers.
Hashes apply to complete original files, not numbered/redacted copies. EVAL_TEST and
hidden sources are absent. The small Python packaging portion of echo-kernel provides
limited mixed-language evidence; installed dependencies and runtime are outside scope.
`style/index.js` is inventoried but outside selected parsing scope. ai-job-agent is
excluded because permission for third-party employer job descriptions is unavailable.

## Local preparation and security

Trusted offline commands use the accepted pinned GitHub HTTPS acquisition, durable
restricted database roles, private S3 artifacts, original parsers and fenced stages.
No upstream setup scripts, hooks, package commands or repository code execute.
No dependency installation is performed from submitted content. A distinct local
Compose project `repovox-pilot` holds predictions; disposable tests use `repovox-test`.

The external Docker volume `repovox-ai-audited-pilot-v1` is mounted at `/exploratory`
only into trusted offline commands as UID/GID 10002. Sources, legal evidence, seals
and later AI reference belong under `/exploratory/AI_AUDITED_EXPLORATORY/v1/`.
Directories use 0700 and files 0600. Normal app/worker UID 10001 has no mount/access;
host/root administrators remain trusted. This is demonstrated local exploratory
isolation, not an authorized official custodian, immutable backup or production system.
The Windows export is source-only and owner-controlled; no B data is exported there.

Use the recorded rights decision before `tools/phase2_exploratory.py`; the tool never
grants rights itself. Credentials come from the existing owner-associated credential,
over stdin to trusted acquisition only, never a source/parser environment or artifact.
`--job` resumes export from a completed durable job without reanalysis. Retained
source/tree/artifact checks must match, and new seal writes cannot overwrite old ones.
Export with `tools/phase2_exploratory_handoff.py --store <private-v1> --output <outside-Git.zip>`.
No real upstream source/network access is part of deterministic CI.

No backup/restore demonstration has been performed. Licenses impose no maximum local
retention identified in screening; owner-authorized pilot data stays private pending
handoff, with no official retention decision inferred. Withdrawal must revoke access,
invalidate A/B/reference/report lineage, delete source/S3/export copies and retain
minimal suppression hashes/reasons. Restores must honor withdrawals. No training,
prompt tuning, Director experiment, benchmark scoring or expansion is authorized here.

## After review, in a separately authorized continuation

Capture the actual raw response (`capture_response`), validate `AIReference`, original
citations and snapshot scope, seal REFERENCE, then reveal the existing B. Preserve any
reference corrections as new immutable versions with source rationale and prior-hash
lineage. Validate owner-authenticated handoff evidence privately. Accepted scoring
requires canonical fact identity, valid citations, no duplicate facts and complete
pairing in both directions; missing/ambiguous matches remain INCOMPLETE. Semantic
assertions require separate source adjudication; do not use text similarity or arbitrary
IDs. Exploratory REVIEW_REQUIRED is not an independent PASS or human approval.
Stop now at the blind source-review handoff.
