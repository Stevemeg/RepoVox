# Repository conventions and phase gates

## Sole contributor policy — every phase

RepoVox is solo-maintained by GitHub owner **Stevemeg**. Codex is the implementation assistant; ChatGPT is the independent validator. Neither is an additional human contributor.

- Use the owner's existing verified Git author **and** committer identity. Before every commit, inspect `git config --show-origin user.name`, `git config --show-origin user.email`, `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`. Confirm GitHub account association with Stevemeg, not merely the displayed name. Never invent, impersonate, substitute or silently change identity. If tooling cannot comply, stop and report it.
- Never add AI assistants as co-authors, unnecessary `Co-authored-by` / `Generated-by` trailers, fictitious contributors or bot commit identities. CI may report results/publish authorized build artifacts but must not write commits. Dependency automation sends notifications for owner-authored updates, not bot-authored commits.
- Preserve legitimate history and attribution. No force pushes, history rewriting or attribution concealment. Use follow-up commits for corrections.
- Before requesting validation, inspect all authors/committers, full messages, unexpected trailers and automation identities; report issues. GitHub account association differs from a cryptographic “Verified” signature; do not describe unsigned commits as signed.
- No credentials, generated secrets, customer repository contents, customer artifacts or provider payloads in Git.

## No premature phase advancement

The owner authorized independent cloud-retention architecture and mock-only
synthetic engineering on 2026-10-20. Continue the draft PR #9 branch; preserve
accepted analyzer/scorer, control SQL, custody and historical deadlines. No AWS
provisioning, paid resource, real evidence, acquisition or pilot is authorized.
Stop at design/security review and separate test-budget approval. See
[ADR-0021](docs/adr/0021-independent-cloud-retention.md).

The owner authorized execution-to-review integration on 2026-10-19, continuing
draft PR #9. Separate genuine SQL execution leases from bounded offline owner-key
review grants; use disposable synthetic PostgreSQL/Linux custody verification.
Preserve accepted analyzer/scorer, migration 0004 and historical evidence. No real
acquisition, A/B generation, reference, reveal, scoring, persistent migration or
Phase 3. Stop at final independent review. See
[ADR-0020](docs/adr/0020-post-execution-custody-authority.md).

The owner subsequently authorized the additive growing-custodian lifecycle and
complete isolated synthetic verification, continuing on the PR #9 branch. Preserve
all accepted analyzer/scorer/control-plane code and historical evidence. New local
SQLite retention metadata is not an application DB migration. Stop for independent
security/engineering review and fresh owner execution confirmation before any real
acquisition or prediction. See [ADR-0019](docs/adr/0019-growing-evaluation-custodian.md).

The owner authorized coordinated Phase 2 completion work on 2026-10-18, including
a dedicated VMware Ubuntu environment and isolated retention/runtime verification.
Use `phase2/retention-runtime-verification` stacked on accepted control plane
`925752b8df38668349b9ef5a45a34cac7d948253`. Preserve analyzer/scorer
`711184e82128c7b0a6f3978cfc1cf13975db39ef`, control-plane SQL, historical custody
and official UNFROZEN gates. New operational code requires independent review;
synthetic-only retention must not be activated for growing real custody. A future
real attempt remains conditional on all runtime/custody/control-plane gates and
the accepted source-only review chronology. No merges, production, paid services,
training or Phase 3. See [ADR-0018](docs/adr/0018-isolated-retention-runtime.md).

The owner authorized the Phase 2C-E control-plane safety correction on 2026-10-16,
stacked on accepted `711184e82128c7b0a6f3978cfc1cf13975db39ef`. Use
`phase2/pilot-control-plane-safety`: durable attempt fencing, mandatory scoped
execution, minimal authenticated offline routing, additive migration/role definitions,
disposable synthetic tests and a draft PR only. Preserve analyzer/scorer source,
evaluation contracts, private custody and historical evidence. Apply migration 0004
only to explicitly isolated disposable databases. No real acquisition/re-execution,
prediction packets, production migration, packet reuse, reveal, gold, scoring, merge
or Phase 3. Stop for independent review. See
[ADR-0017](docs/adr/0017-pilot-control-plane-safety.md).

The owner accepted Phase 2C-C at `9557938f69f0c71f124abe4633089e531e753693`
and authorized Phase 2C-D additive source-fact-2.0 evaluation infrastructure.
Use `phase2/source-fact-v2-evaluation`, stacked on `phase2/canonical-fact-remediation`.
Preserve production schemas, v1 evaluation, historical evidence and official gates.
No new blind pilot, acquisition, database migration, model work, merge or Phase 3.
Stop at draft PR and independent evaluator review. See
[ADR-0016](docs/adr/0016-independent-source-fact-v2-evaluation.md).

The owner authorized Phase 2C-C engineering on 2026-10-14 from accepted
`8b1674de8459725bba25646e3fdd223a57316150`: canonical facts, conservative static
relationships, candidate discovery, citation precision and synthetic regression
coverage only. Use `phase2/canonical-fact-remediation`, stacked against
`phase2/ai-audited-pilot`. The owner separately approved the narrow additive 2.3
completion migration and local synthetic database tests; no pilot/production
database changes. Preserve original 2C-B evidence and official evaluation gates.
Stop at draft PR and independent engineering review. See
[ADR-0015](docs/adr/0015-canonical-source-fact-semantics.md).

Phase 2B engineering was independently accepted at
`e87a95c4763331e3cb73211eb02f7acbc738941a`. Owner authorized Phase 2C-A
`AI_AUDITED_EXPLORATORY`: free local rights-screened static analysis and a manual,
blind ChatGPT source-review handoff only. Use `phase2/ai-audited-pilot` stacked on
`phase2/eval-entry`. Click/p-limit pins are authorized; ai-job-agent is explicitly
excluded for third-party job-description rights; owner separately approved
jupyterlite/echo-kernel `16221829f0ba38374db8f2b8fda10f989d1a6cdd` as replacement.
No AI reference may count toward official human-reviewed EVAL-ENTRY. Preserve all
official manifests/counts and UNFROZEN status. Stop at Package A readiness, before
prediction reveal or comparison. No paid services, training, Director experiments,
merges, deployment or Phase 3. See [exploratory handoff](docs/development/exploratory-handoff.md).

Phase 2 engineering was independently accepted at
`b60ba5484a0710caf64c310e910110d625a01768`. Owner authorized Phase 2B evaluation
preparation on 2026-10-12: use `phase2/eval-entry` from that exact SHA and target
`phase2/repository-intelligence` while PR #3 remains unmerged. Preserve the accepted
engineering; no models/training/paid services/merge/Phase 3. Complete the Phase 2B
A–M handoff. Official corpus remains UNFROZEN until genuine rights, hidden authorship,
independent human review, approved custodian controls and every existing count gate
are satisfied. Reviewer appointment and other owner decisions remain pending.

Phase 1 was independently accepted at `ec09b733ab3ceffe592ad96d07902b92596dfd1b`.
The owner explicitly authorized Phase 2 on 2026-10-12: secure static GitHub analysis
through Stage 9 and evaluation preparation only. Use `phase2/repository-intelligence`
from that accepted SHA and target `phase1/saas-foundation` while PRs #1/#2 remain
unmerged. The earlier Phase 1 restrictions below describe that phase's historical
scope. Phase 2 permits acquisition/parsing as untrusted data; no submitted code
execution, models, training, AI/TTS/media, paid infrastructure, merge or Phase 3.
The official evaluation corpus stays UNFROZEN and the reviewer is PENDING OWNER
APPOINTMENT. Engineering fixtures cannot count as independently reviewed gold.
Use the Phase 2 A–M handoff report and stop at the unmerged PR.

Phase 0 was independently accepted at `e35d8ef8a8a53cb34e46271a9813b5332ea42c1f`; the owner explicitly authorized Phase 1 on 2026-10-12. Phase 1 permits the local SaaS/durable-job foundation and trusted synthetic tests only. No actual acquisition/analysis, AI inference/training, TTS, rendering, paid API integration, cloud provisioning, purchases or production-readiness claims. Stop at independent-review handoff; the implementation assistant cannot declare Phase 1 complete, merge or start Phase 2. Independent validation and owner next-phase authorization remain mandatory. No auto-merge bypass.

## Conventions and review

- Use `phase1/saas-foundation` from the accepted Phase 0 SHA; while PR #1 is unmerged, target `phase0/foundation`. If Phase 0 merges later, verify accepted history/diff before retargeting to main. Descriptive conventional commits and existing owner identity only; no history rewrite.
- Markdown under `docs/`; requirement IDs `F-*` / `N-*`, security IDs `S-*`, numbered ADRs with status/date. Explicit artifact, pipeline and template versions. Cross-link related documents.
- Limits belong to [PRD](docs/product/prd.md); workflow rules to [data model](docs/architecture/data-model.md); retention/deployment to [deployment](docs/operations/deployment.md); assumptions/formulas to [cost model](docs/operations/cost-model.md). Update dependencies together.
- Examples are synthetic. All technical narration has claim references and pinned evidence or labelled uncertainty. Never execute submitted repository code or treat README as implementation truth.
- Carry forward Phase 0 documentation/estimate checks; Phase 1 application/integration tests are separate. Generated logs, diagrams and credentials stay outside Git.
- Run [README checks](README.md#documentation-checks), inspect diff and deliver A-K revision completion report with exact commands, failures, limitations, attribution audit and evidence. Never fabricate tests/deployment results. Future PRs need appropriate tests, authorization coverage, migration/rollback/security/cost analysis and [roadmap](docs/delivery/roadmap.md) traceability. Owner approval cannot replace independent validation.

## Model policy

Self-hosted Director inference and self-hosted TTS are primary production strategy; normal generation must not require paid third-party LLM/TTS APIs. External AI evaluation only with explicit owner approval, permitted data and documented terms; never silent fallback. Director cannot assign verified status. Outputs are strict data schemas, never executable renderer code. Separate upstream base licenses from independently produced datasets/adapters; no scratch-training claim. Model releases need comparative evaluation/rights/security gates; customer jobs are not training data. No GPU purchase/provisioning/paid training or model/AI/media implementation during Phase 1.
