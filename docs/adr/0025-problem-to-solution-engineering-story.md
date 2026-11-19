# ADR-0025: Problem-to-solution engineering story

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-19. Branch `feat/problem-to-solution-story`, stacked on
`feat/js-ts-frameworks-and-deploy-readiness` at `20f4c73`. Milestone 1 of the
problem-to-solution track. Related: [architecture explainer](../development/architecture-explainer.md),
[media database](../operations/media-database.md),
[media stage compatibility](../delivery/media-stage-compatibility.md),
[ADR-0011 parser isolation](0011-parser-process-isolation.md),
[threat model](../security/threat-model.md).

Core migrations stay at `0004` (`rv.job_guard` and `rv.video_disabled` unchanged), the media
database stays at `m001`, and Stages 1–9 and their `phase2_pipeline_boundary` ending are
untouched. `Settings.fail_closed`, `AGENTS.md` and `docs/ai/` are unchanged. No model, hosted
API, download or paid service is used, and CI stays deterministic and offline.

## Context

The repository video narrated static structure: languages, areas, entry points and code
excerpts. It said nothing about what problem a repository addresses, what its authors
intended, or where their claims and the code disagree. Telling that story is only useful if
it is honest. It must say when the problem is undocumented, label author statements as such,
and never present a README promise, a test that was not run or an unbenchmarked performance
claim as established fact.

## Decision

### 1. Versioned intelligence schema (`repovox.media.story`)

`problem-to-solution-1.0` defines `Claim` as the shared atomic unit. A claim has an id, text,
exact `evidence_refs` (path, file hash, line range, quote, permalink), an `evidence_type` and
a `status`:

| Evidence type | Allowed status |
| --- | --- |
| `author_stated_problem`, `inferred_problem_context` | `DOCUMENTATION_ONLY` |
| `intended_solution` | `DOCUMENTATION_ONLY`, or `INFERRED` exactly when implemented code corroborates it |
| `implemented_solution`, `demonstrated_outcome` | `VERIFIED` (backed by Stage 9 verified claims) or `INFERRED` |
| `unverified_outcome`, `unresolved` | `UNVERIFIED` |
| `limitation` | `DOCUMENTATION_ONLY` (documentation) or `INFERRED` (code) |

The nine artifacts are `ProblemStatement`, `ProblemContext`, `IntendedSolution`,
`ImplementationApproach`, `ArchitectureDescription`, `ImplementationEvidence`,
`DemonstratedOutcomes`, `Limitations` and `UnresolvedQuestions`. `ArchitectureDescription`
links to a validated Universal Architecture IR `Report` by digest, architecture ids, the
primary architecture and its view. `EngineeringStory` bundles the nine artifacts with
`mismatches`. These record README-only features, mention-only or declared-only technologies,
code the documentation does not name, placeholder implementations, unbenchmarked
performance claims and architecture claims the IR does not support.

### 2. Evidence-first extraction and a fail-closed verifier (`repovox.media.story_extract`)

Story sources are inventoried from the verified manifest alone:

- the top-level README;
- narrative Markdown under `docs/`, `adr/` or `design/`, bounded to 64 files and 2 MiB;
- `package.json` and `pyproject.toml`;
- parsed source, test and example files.

Every file is checked against its manifest hash. Problems, context, goals, features, ADR
decisions and limitations come from documentation sections. Implementation, routes,
subsystems, languages and technology imports come from Stage 9 claims and the Architecture
IR. Outcomes come from test assertions and example programs, which are never executed.

- A missing problem statement is a single fixed `unresolved` claim; nothing is inferred
  from the repository name.
- Repository text is redacted, reduced to printable ASCII and quoted. Lines that address a
  model ("ignore previous instructions", "system prompt") are counted and never become
  claims.

`verify_story` re-reads the pinned bytes and refuses any of the following:

- a quote, hash, line or permalink that does not match;
- a documentation claim whose text is not exactly its cited line;
- a code-backed claim containing a word that is neither fixed template wording nor cited
  source;
- a `VERIFIED` claim whose Stage 9 claim does not cover its citation;
- an architecture claim outside the IR report;
- a filled-in problem statement.

The extractor verifies its own output, and the worker verifies it again.

### 3. Adaptive storyboard and video (`repovox.media.story_board`)

`problem-to-solution-storyboard-1.0` has up to eleven scenes in fixed order:

1. Introduction
2. Problem
3. Context
4. Proposed solution
5. Development approach
6. Architecture
7. Implementation workflow
8. Technical decisions
9. Demonstrated results
10. Limitations and open questions
11. Conclusion

Scenes without evidence are left out. The introduction, problem, architecture, limitations
and conclusion are always present.

- **Uncertainty labels.** Each sentence's label is the weakest status of the claims it
  cites, and frames show `AUTHOR-STATED / NOT VERIFIED BY CODE`, `INFERRED`, `UNVERIFIED`
  or `VERIFIED`. The results scene says that no test or example was run.
- **Diagrams.** The architecture and workflow scenes are drawn with the existing IR diagram
  renderer. Workflow sentences animate their connections; frames are named
  `frameNNN-MMM.png`, and Stage 14 accepts exactly one still or one complete sequence per
  sentence.
- **Narration seam.** `NarrativeRefiner` may reword planned sentences but cannot change
  their claims or labels. `DeterministicNarrativeRefiner` is the default, and Stage 11
  refuses any other narrator until Milestone 2 adds claim-level grounding.
- **Speech seam.** `narration.Synthesizer` is the speech seam for a local neural voice
  (Milestone 3). Its output passes the same format and silence checks as the
  operating-system voices.

### 4. Pipeline placement without a migration

**Stage 10** extracts the archive, then runs Architecture IR discovery and story extraction
together inside the existing parser sandbox (Landlock, seccomp, resource limits). It then
re-checks the report with `architecture.check` and the story with `verify_story`, and stores
story and report inside the storyboard artifact.

If no story holds, Stage 10 publishes the earlier grounded walkthrough and records the reason
in the stage summary. Examples are isolation being unavailable or a forged or invalid story.

**Stage 11** extracts the archive again, re-verifies the story and requires the storyboard to
be byte-for-byte reproducible. Grounded-walkthrough storyboards keep their original rules
and validator, so artifacts written before this change still validate.

## Consequences

- **Security.** No new network path, credential or execution path. Submitted text is parsed
  only in the sandbox, and the worker compares text and hashes. The prompt-injection rules of
  [S-06](../security/threat-model.md) apply to story text, which can never set a status, a
  scene or a template.
- **Migrations and rollback.** No schema change. Reverting the branch returns Stage 10 to the
  walkthrough. Stored story storyboards from in-flight jobs would then fail Stage 11 under
  the old code and end the job with an explicit error, never a silent publication.
- **Cost.** Deterministic CPU work only. The architecture discovery that already ran in
  Stage 15 now also runs in Stage 10, within its existing 360-second timeout.
- **Limits.** Matching features to code is a word-overlap heuristic, so corroborated
  statements are only ever `INFERRED`. Problem extraction depends on recognisable headings.
  Non-English documentation is not interpreted. Tests are never run, so no runtime result is
  established.

## Evidence

`tests/unit/test_engineering_story.py` covers eight repository shapes:

- strong problem documentation;
- missing problem documentation, never inferred from the name;
- README-only features;
- implementation differing from stated technology;
- multiple problems and subsystems;
- placeholder implementations;
- mention-only technology;
- ambiguous or unavailable architecture.

It also covers forged citations, wording, statuses and storyboards, prompt-injection text,
determinism, the narration and speech seams, and the animated stage chain. Worker Stages 10
and 11 are tested with fallback, and an end-to-end video is probed, fully decoded and checked
caption by caption. `tests/integration/test_media_jobs.py` confirms that the real Linux
sandbox path publishes the story storyboard.

Milestones 2 (grounded language-model narration) and 3 (local neural speech) plug into
`NarrativeRefiner` and `Synthesizer` without changing this schema or verifier.
