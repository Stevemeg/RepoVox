# Repository conventions and phase gates

## Sole contributor policy — every phase

RepoVox is solo-maintained by GitHub owner **Stevemeg**. Codex is the implementation assistant; ChatGPT is the independent validator. Neither is an additional human contributor.

- Use the owner's existing verified Git author **and** committer identity. Before every commit, inspect `git config --show-origin user.name`, `git config --show-origin user.email`, `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`. Confirm GitHub account association with Stevemeg, not merely the displayed name. Never invent, impersonate, substitute or silently change identity. If tooling cannot comply, stop and report it.
- Never add AI assistants as co-authors, unnecessary `Co-authored-by` / `Generated-by` trailers, fictitious contributors or bot commit identities. CI may report results/publish authorized build artifacts but must not write commits. Dependency automation sends notifications for owner-authored updates, not bot-authored commits.
- Preserve legitimate history and attribution. No force pushes, history rewriting or attribution concealment. Use follow-up commits for corrections.
- Before requesting validation, inspect all authors/committers, full messages, unexpected trailers and automation identities; report issues. GitHub account association differs from a cryptographic “Verified” signature; do not describe unsigned commits as signed.
- No credentials, generated secrets, customer repository contents, customer artifacts or provider payloads in Git.

## No premature phase advancement

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
