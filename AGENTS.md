# Repository conventions and phase gates

## Sole contributor policy — every phase

RepoVox is solo-maintained by GitHub owner **Stevemeg**. Codex is the implementation assistant; ChatGPT is the independent validator. Neither is an additional human contributor.

- Use the owner's existing verified Git author **and** committer identity. Before every commit, inspect `git config --show-origin user.name`, `git config --show-origin user.email`, `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`. Confirm GitHub account association with Stevemeg, not merely the displayed name. Never invent, impersonate, substitute or silently change identity. If tooling cannot comply, stop and report it.
- Never add AI assistants as co-authors, unnecessary `Co-authored-by` / `Generated-by` trailers, fictitious contributors or bot commit identities. CI may report results/publish authorized build artifacts but must not write commits. Dependency automation sends notifications for owner-authored updates, not bot-authored commits.
- Preserve legitimate history and attribution. No force pushes, history rewriting or attribution concealment. Use follow-up commits for corrections.
- Before requesting validation, inspect all authors/committers, full messages, unexpected trailers and automation identities; report issues. GitHub account association differs from a cryptographic “Verified” signature; do not describe unsigned commits as signed.
- No credentials, generated secrets, customer repository contents, customer artifacts or provider payloads in Git.

## No premature phase advancement

Phase 0 permits requirements, architecture, threat analysis, estimates, documentation and documentation checks only. No application implementation, paid API integration, provisioning, purchases or production-readiness claims. Stop at review handoff. Independent validation must pass and the owner must authorize the next phase. Apply this gate to every later phase. No merge without independent validation; no auto-merge bypass.

## Conventions and review

- Use `phase0/foundation`, PR base `main`, descriptive conventional commits and the existing owner identity. Establish only a minimal baseline on main if the remote is empty.
- Markdown under `docs/`; requirement IDs `F-*` / `N-*`, security IDs `S-*`, numbered ADRs with status/date. Explicit artifact, pipeline and template versions. Cross-link related documents.
- Limits belong to [PRD](docs/product/prd.md); workflow rules to [data model](docs/architecture/data-model.md); retention/deployment to [deployment](docs/operations/deployment.md); assumptions/formulas to [cost model](docs/operations/cost-model.md). Update dependencies together.
- Examples are synthetic. All technical narration has claim references and pinned evidence or labelled uncertainty. Never execute submitted repository code or treat README as implementation truth.
- Phase 0 scripts check documentation/estimates only, with no runtime scaffolding. Generated diagram previews stay outside Git.
- Run [README checks](README.md#documentation-checks), inspect diff and deliver A–I completion report with exact commands, failures, limitations, attribution audit and evidence. Never fabricate tests/deployment results. Future PRs need appropriate tests, authorization coverage, migration/rollback/security/cost analysis and [roadmap](docs/delivery/roadmap.md) traceability. Owner approval cannot replace independent validation.
