/*
 * Deterministic, user-actionable next steps for the codes a job or an admission request can
 * stop with. The input is the fixed `code` alone, so guidance can never include a detail the
 * API did not disclose: no file path, line, matched value or count is ever invented here.
 *
 * Every limit and rule below is stated from the analysis pipeline as implemented
 * (apps/api/repovox/analysis: `Limits`, the Stage 2 credential screen, archive extraction and
 * source filtering) and the admission checks in the database migrations. When those change,
 * this file must change with them.
 */

export type RemediationContext = "job" | "request";

export type Remediation = {
  code: string;
  /** A short heading for the panel. */
  title: string;
  /** What RepoVox checked and why it stopped, in our own words. */
  explanation: string;
  /** Concrete next steps, in order. */
  steps: string[];
  /** The rule or limit RepoVox applies, stated as policy. */
  policy?: { heading: string; items: string[] };
  /** What RepoVox deliberately does not show, and why. */
  withheld?: string;
  /** What retrying does in this context. */
  retry?: string;
};

type Entry = Omit<Remediation, "code" | "retry"> & {
  retry?: Partial<Record<RemediationContext, string>>;
};

const NEW_COMMIT =
  "Retrying this job re-reads the same pinned commit, so it would stop the same way. After you push a fix, start a new analysis or video job from the project page: it pins the repository's current default branch.";
const NOTHING_STARTED = "Nothing was started by this attempt, and no allowance was used.";
const START_NEW =
  "Push the change, then start a new analysis or video job from the project page.";
const SKIPPED_DIRECTORIES =
  "Directories named node_modules, vendor, vendored, third_party, dist, build, .next, coverage, generated, __pycache__, .venv and venv are skipped automatically, as are lockfiles, minified files and files marked @generated or automatically generated.";
const SIZE_STEPS = [
  "Remove large binaries, media, datasets and committed dependencies or build outputs from the repository.",
  "GitHub builds its source archives with git archive, which leaves out paths marked export-ignore in .gitattributes. Use that to exclude assets RepoVox does not need.",
  START_NEW,
];

const ENTRIES: Record<string, Entry> = {
  secret_detected: {
    title: "The credential screen refused this snapshot",
    explanation:
      "Before anything is parsed, RepoVox screens the bytes of every file, and every file and directory name, at the pinned commit. Tests, documentation and examples are screened too. A match stops the job immediately, so nothing from this snapshot was parsed or published.",
    withheld:
      "RepoVox deliberately does not show which file, line or value matched, so that a real credential is never repeated back on screen. Use the patterns below to find it in your repository.",
    policy: {
      heading: "What the screen refuses",
      items: [
        "Private key blocks: PEM “BEGIN … PRIVATE KEY” blocks and PGP private key blocks.",
        "Known provider token formats, for example AWS access key IDs (AKIA…, ASIA…), GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_, github_pat_), Slack tokens (xox…), Stripe live keys (sk_live_, rk_live_), OpenAI- and Anthropic-style sk- keys, Google API keys (AIza…), GitLab tokens (glpat-), Hugging Face and npm tokens, and PyPI upload tokens.",
        "Credential URLs with a literal password and a remote host, such as scheme://user:password@db.example.com. Database and queue URLs on a loopback or single-label development host (localhost, postgres, db) with a short development password are allowed.",
        "Any literal value of 8 or more characters assigned to a password, passwd, secret, api_key, access_token or client_secret field.",
        "File or directory names that contain a long random-looking token of 24 or more characters.",
      ],
    },
    steps: [
      "Search the repository at its current commit for the patterns below, for example with a secret scanner such as gitleaks or trufflehog, or a text search for BEGIN PRIVATE KEY, AKIA, ghp_, xox and sk_live_.",
      "If a real credential was ever committed, revoke or rotate it with its provider first. Deleting it from the repository does not make it safe again, because it remains in Git history.",
      "Replace literal values with references or obvious placeholders, which the screen accepts: ${API_KEY}, {settings.DB_PASSWORD}, %(password)s, {{ db_password }}, env(API_SECRET), <your-api-key>, changeme or a mask such as ********.",
      "Rename any file or directory whose name contains a long random-looking token.",
      "Push the change, then start a new analysis from the project page. RepoVox reads only the snapshot of the commit it pins, not older history.",
    ],
    retry: { job: NEW_COMMIT },
  },

  archive_nested: {
    title: "The repository contains an archive",
    explanation:
      "RepoVox never unpacks an archive found inside a repository. A file is refused when its name ends in an archive extension, or when its contents begin with a ZIP, gzip or 7z signature, whatever it is called.",
    policy: {
      heading: "How archive-like files are treated",
      items: [
        "Refused by name: .zip, .tar, .tgz, .gz, .bz2, .xz, .7z and .rar files.",
        "Refused by content under any name: ZIP-based formats such as .jar, .whl, .docx, .xlsx, .pptx and .apk files, and gzip or 7z data.",
        "Skipped, not refused: PyTorch .pt and .pth and Keras .keras model weight files. Their bytes are hashed and screened for credentials, then recorded as skipped (ml_weight_container) without being written, unpacked or parsed.",
      ],
    },
    steps: [
      "List the archive-like files your repository tracks, for example by filtering git ls-files for the extensions above.",
      "Remove packaged libraries, build outputs, office documents and data bundles from the repository, or publish them as release assets or packages instead.",
      START_NEW,
    ],
    retry: { job: NEW_COMMIT },
  },

  archive_download_limit: {
    title: "The repository download is too large",
    explanation:
      "RepoVox downloads GitHub's compressed archive of the pinned commit and stops once it is larger than 100 MB.",
    steps: SIZE_STEPS,
    retry: { job: NEW_COMMIT },
  },

  archive_expansion_limit: {
    title: "The repository expands beyond the size limit",
    explanation:
      "GitHub's archive of the pinned commit decompresses to more than 280 MB, the most RepoVox reads from one archive.",
    steps: SIZE_STEPS,
    retry: { job: NEW_COMMIT },
  },

  archive_extraction_limit: {
    title: "The repository is larger than RepoVox extracts",
    explanation:
      "RepoVox extracts at most 250 MB of file content and 10,000 files from one snapshot. Skipped files, such as model weights, count toward both limits.",
    steps: SIZE_STEPS,
    retry: { job: NEW_COMMIT },
  },

  archive_member_limit: {
    title: "The repository archive has too many entries",
    explanation:
      "The archive of the pinned commit lists more than 20,032 entries, counting files and directories together, so RepoVox stopped reading it.",
    steps: [
      "Remove generated, vendored or data trees that add many small files to the repository.",
      "Paths marked export-ignore in .gitattributes are left out of GitHub's source archives.",
      START_NEW,
    ],
    retry: { job: NEW_COMMIT },
  },

  archive_unsafe_entry: {
    title: "The repository contains a link or special file",
    explanation:
      "RepoVox extracts regular files and directories only. The archive contains a symbolic link, hard link, device or other special entry, so extraction stopped.",
    steps: [
      "Find symbolic links: git ls-files -s lists them with mode 120000.",
      "Replace each link with a regular file, or remove it.",
      START_NEW,
    ],
    retry: { job: NEW_COMMIT },
  },

  archive_unsafe_path: {
    title: "The repository contains an unsafe file path",
    explanation:
      "A path in the archive cannot be extracted safely, so RepoVox stopped before writing anything from it.",
    policy: {
      heading: "Paths RepoVox refuses",
      items: [
        "Absolute paths, empty, . or .. segments, and paths containing a backslash, a colon or a control character.",
        "Names that end in a dot or a space, and reserved device names such as CON, PRN, AUX, NUL, COM1 to COM9 and LPT1 to LPT9.",
        "Paths longer than 1,024 bytes or more than 32 levels deep.",
      ],
    },
    steps: ["Rename or move the affected files and directories.", START_NEW],
    retry: { job: NEW_COMMIT },
  },

  analysis_fact_limit: {
    title: "Too much source to analyse in one job",
    explanation:
      "Parsing records each definition, import and call as a fact, with a cap of 10,000 facts per repository. Facts from test files are dropped first, in fixed tiers, and the analysis discloses it. This repository exceeded the cap with non-test source alone, so RepoVox stopped rather than analyse part of it without saying so.",
    steps: [
      "Analyse a smaller repository, or a fork that keeps only the part you want explained.",
      SKIPPED_DIRECTORIES,
      "Move other bundled or generated source into one of those directories, or out of the repository, then start a new analysis.",
    ],
    retry: { job: NEW_COMMIT },
  },

  eligible_source_limit: {
    title: "More source than one analysis covers",
    explanation:
      "One analysis covers at most 5,000 eligible source files and 100 MB of eligible source. Eligible source is Python, JavaScript and TypeScript that is not skipped.",
    steps: [
      "Analyse a smaller repository, or a fork that keeps only the part you want explained.",
      SKIPPED_DIRECTORIES,
      "Move other bundled or generated source into one of those directories, or out of the repository, then start a new analysis.",
    ],
    retry: { job: NEW_COMMIT },
  },

  repository_private: {
    title: "The repository is private",
    explanation:
      "RepoVox reads public GitHub repositories only and never asks for access to private ones.",
    steps: [
      "Make the repository public if that is appropriate for it, or add a project for a public repository instead.",
      "Once it is public, start a new analysis from the project page.",
    ],
    retry: { request: "Nothing was started by this attempt." },
  },

  repository_not_found: {
    title: "GitHub has no public repository at this address",
    explanation:
      "GitHub reports that no public repository exists at the project's repository URL. It may be misspelled, renamed, moved, deleted or private.",
    steps: [
      "Open the repository on GitHub and compare its owner and name with the project's URL.",
      "A project's repository URL cannot be changed. If it was wrong or the repository moved, add a new project with the correct URL and delete this one.",
    ],
    retry: { request: "Nothing was started by this attempt." },
  },

  source_changed: {
    title: "The snapshot did not match on re-verification",
    explanation:
      "Before publishing, RepoVox re-reads the snapshot and checks every file against the hashes recorded when it was first read. They did not match, so nothing was published.",
    steps: [
      "Start a new analysis from the project page. It downloads a fresh snapshot of the current default branch.",
      "If it happens again for the same repository, share the reference below when you ask for help.",
    ],
    retry: { job: "Retrying this job downloads the same pinned commit again." },
  },

  insufficient_evidence: {
    title: "Not enough verifiable evidence",
    explanation:
      "RepoVox publishes only what it can verify against the pinned source. This job could not verify enough evidence to continue, so it stopped without publishing anything.",
    steps: [
      "Check that the repository contains Python, JavaScript or TypeScript source that is not in a skipped directory. RepoVox analyses only those languages.",
      "Files that fail to parse are excluded from verified evidence, so fix syntax errors in the main source files.",
      "Then start a new analysis or video job from the project page.",
    ],
  },

  monthly_quota: {
    title: "Monthly analysis allowance used",
    explanation:
      "Each analysis counts against this account's monthly allowance, including the analysis that every video job starts and every retry. The environment also has an overall monthly limit.",
    steps: [
      "Wait for the allowance to renew at the start of next month.",
      "Completed analyses and published videos stay available until they expire, so you can keep working with existing results.",
      "If you need more this month, ask whoever administers this RepoVox environment.",
    ],
    retry: { request: NOTHING_STARTED },
  },

  queue_quota: {
    title: "Too many jobs waiting to start",
    explanation: "This account already has the maximum number of jobs queued to start.",
    steps: [
      "Wait for a queued job to start running, then try again.",
      "Or cancel a queued job you no longer need from Job history.",
    ],
    retry: { request: NOTHING_STARTED },
  },

  project_quota: {
    title: "Project limit reached",
    explanation:
      "An account can hold up to 100 projects, and can create up to 30 projects in any one minute.",
    steps: [
      "Delete projects you no longer need. A deleted project stops counting immediately; its stored data is cleaned up in the background.",
      "If you created many projects quickly, wait a minute and try again.",
    ],
    retry: { request: "No project was created by this attempt." },
  },

  admission_rate: {
    title: "Too many jobs started at once",
    explanation: "RepoVox admits at most two jobs per account in any one minute.",
    steps: ["Wait a minute, then try again. Jobs you already started keep running."],
    retry: { request: NOTHING_STARTED },
  },

  github_rate_limited: {
    title: "GitHub is limiting requests",
    explanation: "GitHub is temporarily limiting the requests RepoVox makes to it.",
    steps: ["Wait a few minutes, then try again. GitHub lifts the limit on its own."],
    retry: {
      request: NOTHING_STARTED,
      job: "Retrying this job requests the same pinned commit again, once GitHub allows it.",
    },
  },

  media_timeout: {
    title: "Video encoding took too long",
    explanation:
      "Encoding or verifying a video took longer than the media worker allows, so the video job stopped. The analysis it used is unaffected.",
    steps: [
      "Start a new video job from the project page. Each video job starts its own analysis, which counts against the monthly allowance.",
      "If it times out again for the same repository, share the reference below when you ask for help.",
    ],
  },
};

/** Codes with guidance, for tests and documentation. */
export const REMEDIATION_CODES = Object.freeze(Object.keys(ENTRIES));

/**
 * Guidance for a code, or null when RepoVox has none beyond the error message. Takes only
 * the fixed code, so no repository detail can reach the result.
 */
export function remediationFor(
  code: string | null | undefined,
  context: RemediationContext = "job",
): Remediation | null {
  if (!code || !Object.hasOwn(ENTRIES, code)) return null;
  const { retry, ...entry } = ENTRIES[code];
  return { code, ...entry, retry: retry?.[context] };
}
