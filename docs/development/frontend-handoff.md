# Frontend developer handoff

Status: handoff guide, 2026-11-20, branch `feat/neural-tts-and-frontend-handoff`. Not
independently reviewed or accepted. It describes the API contract frozen in
[`packages/contracts/openapi.json`](../../packages/contracts/openapi.json) on that branch.
Related:

- [ADR-0025 engineering story](../adr/0025-problem-to-solution-engineering-story.md)
- [ADR-0026 grounded narration](../adr/0026-grounded-llm-narration-refiner.md)
- [ADR-0027 neural voice and story API](../adr/0027-neural-tts-and-story-api-contract.md)
- [deployment guide](../operations/deployment-guide.md)
- [contributor rules](../../AGENTS.md)

This is for whoever builds the RepoVox web app in `apps/web` (Next.js 16.4.6, React 19.3.0).
The backend is a FastAPI app with workers. It analyses one pinned commit of a public GitHub
repository as data, never runs it, and publishes narrated videos. The frontend's job is to
show that work honestly. Read [section 3](#3-ui-design-and-truthfulness-rules-non-negotiable)
before you design any screen.

## 1. Local backend boot for frontend development

You need Docker with Compose v2, Node 24.22.1 (the exact version in
`apps/web/package.json` `engines`), `uv` 0.13.4 or newer, and Python 3.12.

```sh
# 1. Start the whole local stack (API, workers, databases, object storage and the web image).
#    The first run generates .env with random secrets (mode 600) and waits for health checks.
bash scripts/deploy_selfhosted.sh                      # --mode local (the default)

# Optional: serve locally authored synthetic repositories instead of fetching from GitHub.
SYNTHETIC_SOURCE_DIR=/workspace/tests/fixtures/architectures \
  docker compose up -d --build --wait api worker dispatcher media-worker

# 2. Stop the bundled web container so your dev server can use port 3000.
docker compose stop web

# 3. Run the web app against the API on 127.0.0.1:8000.
npm --prefix apps/web ci
REPOVOX_API_URL=http://localhost:8000 npm --prefix apps/web run dev
```

Open `http://localhost:3000`. The browser only talks to the Next.js app. Every API call goes
through the same-origin proxy `apps/web/src/app/api/v1/[...path]/route.ts`, which forwards an
explicit allowlist of routes to `REPOVOX_API_URL` (default `http://localhost:8000`). **A new
backend route is unreachable until you add it to that allowlist** and to
`apps/web/tests/analysis-proxy.test.ts`.

### Sign-in modes

Call `GET /api/v1/auth/config` first. It is public and returns no credential:

```json
{ "auth_provider": "dev", "github_oauth_enabled": false, "environment": "development" }
```

| `auth_provider` | What the sign-in page offers |
| --- | --- |
| `dev` (local stack) | Two seeded development personas. `POST /api/v1/auth/development/sign-in` with `{"subject": "alex"}` or `{"subject": "sam"}`. The browser `Origin` must equal `REPOVOX_ORIGIN` (`http://localhost:3000`). |
| `github` (production) | A link to `GET /api/v1/auth/github/login`, a top-level navigation; never `fetch` it. GitHub redirects back to `/api/v1/auth/github/callback`, and only operator-provisioned accounts get a session. |

Use the two personas to check tenant isolation by hand: `sam` must never see `alex`'s
projects, jobs or videos, and every such request returns `404`. After sign-in,
`GET /api/v1/auth/session` returns the account and the feature flags `analysis_enabled` and
`video_enabled`.

With the synthetic source directory set, create a project with a repository URL of the form
`https://github.com/synthetic/<directory>`, for example `custom_unnamed` or
`tech_mention_only` from `tests/fixtures/architectures`, then start a video job and follow
its states. Without it, any public `https://github.com/<owner>/<name>` is fetched.

## 2. Frozen API contract and endpoints

The contract is `packages/contracts/openapi.json`. CI fails if the application drifts from it
(`uv run python tools/phase1_contracts.py --check`). Regenerate it with
`uv run python tools/phase1_contracts.py` only together with a backend change, never by
hand. All paths below are relative to `/api/v1` in the browser (`/v1` on the API itself).

### Authentication, CSRF and errors

| Rule | Detail |
| --- | --- |
| Session cookie | `rv_session`: HttpOnly, `SameSite=Strict`, `Secure` on an `https://` origin. Sent automatically with `credentials: "same-origin"`. |
| CSRF token | `rv_csrf`: readable, `SameSite=Strict`. Every mutation (`POST`, `PATCH`, `DELETE`) sends it back as the `X-CSRF-Token` header and must come from the exact `Origin`. `apps/web/src/lib/api.ts` already does this. |
| Idempotency | `POST /projects/{id}/video-jobs` and the development job routes require an `Idempotency-Key` header (1–120 printable ASCII characters, no spaces). Reuse the key when you retry the same click. |
| Errors | JSON `{"error": {"code": "<fixed_code>", "request_id": "..."}}`. Show your own message per code and HTTP status, never server text. `401` means sign in again, `404` means not found or not yours, `409` and `422` mean refused input or state, `429` means a quota was reached, and `503` means a dependency is unavailable. |

### Routes the video UI uses

| Method and path | Purpose |
| --- | --- |
| `GET /auth/config` | Sign-in mode (public) |
| `POST /auth/development/sign-in` | Development persona sign-in |
| `GET /auth/session` | Current account and feature flags |
| `POST /auth/sign-out` | End the session (`204`) |
| `GET /projects`, `POST /projects` | List or create projects: `{"title", "repository_url"}`, where the URL must be a canonical `https://github.com/<owner>/<name>` |
| `GET /projects/{id}`, `PATCH /projects/{id}`, `DELETE /projects/{id}` | One project |
| `POST /projects/{id}/video-jobs` | Start a video job: `{"processing_acknowledged": true}` plus `Idempotency-Key` (`202`) |
| `GET /projects/{id}/video-jobs` | The project's video jobs, newest first (at most 50) |
| `GET /video-jobs/{job_id}` | One video job: poll this |
| `POST /video-jobs/{job_id}/cancel` | Cancel a job that has not finished |
| `GET /video-jobs/{job_id}/videos/{video_id}` | Stream the MP4; honours one `Range: bytes=a-b` |
| `GET /video-jobs/{job_id}/videos/{video_id}/download` | Same bytes as an attachment |
| `GET /video-jobs/{job_id}/videos/{video_id}/captions` | WebVTT captions (`text/vtt`) |
| `GET /video-jobs/{job_id}/videos/{video_id}/story` | The verified engineering story and narration record (new; walkthrough only) |

### Polling states

A video job (`MediaJobView.state`) moves through:

```text
awaiting_analysis -> queued -> running <-> retry_wait -> succeeded
                 \-> failed      \-> failed / cancelled
```

- **Waiting.** `awaiting_analysis` means the repository is being analysed; the media job
  waits for verified analysis output.
- **Working.** `queued`, `running` and `retry_wait` mean stages are being produced. Show the
  six `stages` (`storyboard`, `narration`, `tts`, `render`, `encode`, `architecture`), each
  `pending`, `ready`, `running`, `retry_wait`, `succeeded`, `failed` or `cancelled`.
- **Finished.** `succeeded`, `failed` and `cancelled` are terminal; stop polling. `videos` is
  empty until `succeeded`. On `failed`, show `error_code` through your own message table.
- **Architecture outcome.** `architecture` is reported separately: `published`,
  `unsupported`, `extraction_failed`, `rendering_failed` or `not_completed`. A published
  walkthrough never implies an architecture explainer; `video-panel.tsx` already has
  wording for each value.

Poll every 3–5 seconds while the job is not terminal, and stop when the tab is hidden.
Published videos expire 24 hours after the job was created (`expires_at`).

### TypeScript interfaces

These mirror the OpenAPI schemas `MediaJobView`, `VideoView`, `VideoStoryView`, `StoryView`,
`NarrationView`, `Claim`, `EvidenceRef` and `Mismatch`. Every field is snake_case as sent.

```ts
export type JobState =
  | "awaiting_analysis" | "queued" | "running" | "retry_wait"
  | "succeeded" | "failed" | "cancelled";

export interface MediaJob {
  id: string;
  project_id: string;
  analysis_job_id: string;
  state: JobState;
  version: number;
  repository: string | null;
  commit_sha: string | null;
  architecture:
    | "published" | "unsupported" | "extraction_failed" | "rendering_failed"
    | "not_completed" | null;
  error_code: string | null;
  created_at: string;
  deadline: string;
  finished_at: string | null;
  stages: { ordinal: number; stage_key: string; state: string; attempt_count: number;
            error_code: string | null }[];
  videos: Video[];
}

export interface Video {
  id: string;
  category: "walkthrough" | "architecture";
  position: number;
  title: string;
  checksum: string; // SHA-256 of the MP4 bytes: the stable identity for caching.
  byte_count: number;
  published_at: string;
  expires_at: string;
  metadata: WalkthroughMetadata | ArchitectureMetadata;
}

export interface WalkthroughMetadata {
  video_codec: "h264"; audio_codec: "aac"; width: number; height: number; fps: number;
  video_frames: number; duration_seconds: number; audio_duration_seconds: number;
  full_decode: "passed"; sentences: number; ffmpeg_version: string;
  narration?: Narration; // Present on videos published from this branch on.
}

export interface ArchitectureMetadata {
  id: string; type: string; status: string; components: number; connections: number;
  narration_lines: number; citations: number; unresolved: string[]; // open topics
  media: Record<string, unknown>;
  narration?: VoiceRecord; // Only which voice spoke; explainers are never model-worded.
}

export interface VoiceRecord {
  // null on videos whose speech bundle predates the voice record.
  tts_provider: "deterministic" | "kokoro_onnx" | "local" | null;
  tts_engine: string | null;  // "espeak-ng", "windows-sapi" or "kokoro-onnx"
  tts_voice: string | null;   // the operating-system voice name, or a Kokoro voice id
}

export interface Narration extends VoiceRecord {
  refiner: "deterministic-template-1.0" | "grounded-llm-refiner-1.0";
  provider: "deterministic" | "ollama" | "openai_compatible" | "anthropic";
  model: string | null;            // null exactly when provider is "deterministic"
  blueprint_sha256: string | null;
  scenes_total: number;
  scenes_refined: number;          // scenes whose model wording passed the grounding check
  scenes_fallback: number;         // scenes that kept the template wording
  refined_scene_ids: string[];
  fallback_reason: string | null;  // set when no model wording was used at all
  rejection_reasons: Record<string, string[]>; // scene id -> fixed reason codes
}

export type ClaimStatus = "VERIFIED" | "INFERRED" | "DOCUMENTATION_ONLY" | "UNVERIFIED";
export type EvidenceType =
  | "author_stated_problem" | "inferred_problem_context" | "intended_solution"
  | "implemented_solution" | "demonstrated_outcome" | "unverified_outcome"
  | "limitation" | "unresolved";

export interface EvidenceRef {
  id: string;
  path: string;        // repository-relative, at the pinned commit
  file_sha256: string;
  start_line: number;
  end_line: number;
  quote: string;       // the cited lines; untrusted text; at most 240 characters here
  permalink: string;   // https://github.com/<owner>/<name>/blob/<commit>/<path>#L..
}

export interface Claim {
  id: string;
  text: string;                          // untrusted text: render as plain text only
  evidence_type: EvidenceType;
  status: ClaimStatus;
  evidence_refs: EvidenceRef[];          // at most 3 in this view
  source_location: string | null;        // "<path>:<line>" of the first citation
  analysis_claim_ids: string[];
  supports: string[];                    // implemented claims corroborating an intention
  proof: "unit_test" | "integration_test" | "benchmark" | "example" | null;
  component_ids: string[];
  connection_ids: string[];
}

export interface Mismatch {
  id: string;
  kind:
    | "readme_only_feature" | "mention_only_technology" | "declared_only_technology"
    | "unstated_implementation" | "incomplete_implementation"
    | "unbenchmarked_performance_claim" | "unsupported_architecture_claim";
  detail: string;
  stated_claim_ids: string[];
  evidence_claim_ids: string[];
}

export interface EngineeringStory {
  view_version: "engineering-story-view-1.0";
  schema_version: "problem-to-solution-1.0";
  extractor_version: "problem-to-solution-extractor-1.0";
  repository: string;
  commit_sha: string;
  analysis_sha256: string;
  source_counts: Partial<Record<
    "readme" | "documentation" | "manifest" | "source" | "test" | "example", number>>;
  status_counts: Record<ClaimStatus, number>;
  status_labels: Record<ClaimStatus, string>; // the exact badge text to show
  problem_statement: { sufficiency: "documented" | "insufficient"; claims: Claim[] };
  problem_context: { claims: Claim[] };
  intended_solution: { claims: Claim[] };
  implementation_approach: { claims: Claim[]; decisions: Claim[] };
  architecture: {
    ir_version: "architecture-ir-1.0" | null; report_sha256: string | null;
    explanation: "supported" | "unsupported" | "unavailable";
    unavailable_reason: string | null; architecture_ids: string[];
    primary: string | null; view: string | null; claims: Claim[]; workflow: Claim[];
  };
  implementation_evidence: { claims: Claim[] };
  demonstrated_outcomes: { scope: string; claims: Claim[] };
  limitations: { claims: Claim[] };
  unresolved_questions: { claims: Claim[] };
  mismatches: Mismatch[];
  instruction_like_lines: number; // README lines that addressed a model; never used
  evidence_trimmed: boolean;      // true when citations or quotes were shortened here
}

export interface VideoStory {
  video_id: string;
  job_id: string;
  category: "walkthrough";
  narration: Narration | null;
  story: EngineeringStory;
}
```

`GET .../story` returns `404 story_not_available` for an architecture explainer, and for a
walkthrough published before this branch or one that fell back to the grounded walkthrough
(no story could be established). Treat that as "no story", not as an error page. Another
owner's video returns `404 not_found`, exactly as a missing one does.

### Video streaming and captions

- **Playback.** Use a plain `<video controls preload="metadata" src=".../videos/{id}">`. The
  route answers `Range: bytes=a-b` with `206`, `Content-Range` and `Accept-Ranges: bytes`;
  without a range it answers `200` with the whole file. Multi-range requests get the whole
  file.
- **No ETag.** The route sends no `ETag` header. The server pins every read to the stored
  version it verified, and the `checksum` field (SHA-256 of the bytes) is the identity to use
  as a cache key. A video never changes after publication.
- **Download.** Link to `.../download`, which carries `Content-Disposition: attachment`.
- **Captions.** Add `<track kind="captions" src=".../captions" srcLang="en" default>` and set
  its mode to `"hidden"` when it mounts, exactly as `video-panel.tsx` does. Every frame
  already shows its caption, burned into the lower band. `"hidden"` loads the cues for
  assistive technology and the player's menu without drawing them a second time; a
  `"disabled"` track is never fetched. Set it once on mount, so a viewer's own choice is not
  undone on re-render.
- **Ids.** Validate both ids as UUIDs before putting them in a URL (`videoRoutes()` in
  `video-panel.tsx`).

## 3. UI design and truthfulness rules (non-negotiable)

RepoVox exists to separate what the code shows from what its authors say. A screen that
blurs that is a defect, however good it looks.

1. **Status badges are mandatory and literal.** Every claim, wherever it appears, shows the
   badge text from `story.status_labels`. Use four visibly different treatments, with text
   and not colour alone:

   | Status | Badge text | Meaning |
   | --- | --- | --- |
   | `VERIFIED` | `VERIFIED` | Exact cited code, confirmed by the static verifier |
   | `INFERRED` | `INFERRED` | A fixed rule over cited evidence; the binding is not proven |
   | `DOCUMENTATION_ONLY` | `AUTHOR-STATED / NOT VERIFIED BY CODE` | The authors say so; no code backs it |
   | `UNVERIFIED` | `UNVERIFIED` | An assertion or open question nothing supports |

   Never style a README or documentation claim like a verified fact: no check marks, green
   "confirmed" styling or "Features" heading for `DOCUMENTATION_ONLY` claims.
2. **Mismatches are first-class.** Show every entry in `story.mismatches`: README-only
   features, mention-only and declared-only technologies, unstated implementation,
   placeholder implementations, unbenchmarked performance claims and unsupported
   architecture claims. Link each to the claims it names. Do not hide them behind a toggle
   that is closed by default.
3. **Say when the problem is undocumented.** When `problem_statement.sufficiency` is
   `"insufficient"`, say plainly that the repository does not document the problem it
   solves. Never derive a problem from the repository name or description.
4. **Tests were read, not run.** `demonstrated_outcome` claims come from test and example
   source that RepoVox never executed. Show `demonstrated_outcomes.scope` next to them, and
   never say "tests pass". `benchmark` proofs establish no performance figure.
5. **Say how the narration was made.** Use `metadata.narration`:
   - **Model wording.** If `provider` is not `"deterministic"`, say that a language model
     (`provider` and `model`) reworded the narration. Give `scenes_refined` of
     `scenes_total`, and say the remaining scenes kept the template wording (with
     `rejection_reasons`, or `fallback_reason` when no model wording was used). Hosted
     providers are third-party services.
   - **Voice.** If `tts_provider` is `"kokoro_onnx"`, say the voice is a local neural voice.
   - **Current copy.** The paragraph in `video-panel.tsx` ("No AI model and no paid service
     is used") is only true when `provider` is `"deterministic"`. Make it conditional before
     shipping.
6. **Repository strings are untrusted.** Claim text, quotes, titles, paths, mismatch details,
   repository names and error codes come from submitted repositories or the server:
   - Render them as React text children only, never with `dangerouslySetInnerHTML`, never
     through a Markdown or HTML renderer, and never in `href` or `src` except a `permalink`
     you have checked starts with `https://github.com/`.
   - Do not `eval`, template or `new Function` anything.
   - Keep the Content-Security-Policy in `next.config.ts`; do not loosen it.
7. **Accessibility.** Status must be conveyed in text. Keep the keyboard-operable player
   and the hidden caption track. Respect `prefers-reduced-motion` for any animation.

## 4. Frontend quality gates

Run these from the repository root before every push; the CI `frontend` job runs the same.

```sh
npm --prefix apps/web ci
npm --prefix apps/web run lint        # ESLint 10 with typescript-eslint and react-hooks
npm --prefix apps/web run typecheck   # next typegen && tsc --noEmit
npm --prefix apps/web test            # Vitest + Testing Library (jsdom)
npm --prefix apps/web run build       # Next.js production build (standalone output)
npm --prefix apps/web audit --omit=dev --audit-level=high

# Browser end-to-end tests against the full local stack (CI's "Browser interaction test"):
SYNTHETIC_SOURCE_DIR=/workspace/tests/fixtures/architectures \
  docker compose up -d --build --wait api web worker dispatcher media-worker
cd apps/web && npx playwright install --with-deps chromium && npm run test:e2e
```

The video end-to-end test needs H.264 and AAC decoding, which bundled Chromium lacks.
Install Google Chrome (`npx playwright install chrome`) as CI does.

Repository rules that apply to frontend pull requests ([AGENTS.md](../../AGENTS.md)):

- **Identity.** Commit as yourself with your verified Git identity. No AI co-author,
  `Generated-by` or bot trailers, no force pushes and no history rewriting; correct mistakes
  with follow-up commits.
- **Commit messages.** Descriptive conventional commits (`feat:`, `fix:`, `test:`, `docs:`).
- **No version drift.** Next.js is pinned at `16.4.6` and `sharp` at `0.35.5`, and CI checks
  the installed tree. Changing either, or Node `24.22.1`, means updating
  `.github/workflows/phase1.yml` (version checks and `node-version`), the
  `infrastructure/local/web.Dockerfile` base image and `package-lock.json` together, and
  explaining it in the PR.
- **Contract changes.** A backend contract change regenerates `packages/contracts/openapi.json`
  in the same PR. A new route needs a proxy allowlist entry and a proxy test.
- **Data and secrets.** No credentials, `.env` files, customer repository content or
  generated videos in Git. Test fixtures are synthetic.
- **Review.** Draft PRs stacked on the current branch, with tests and a short note on
  truthfulness impact. The owner merges after independent review.
