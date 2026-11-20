"""Deterministic problem-to-solution extraction and an independent citation verifier.

Inputs are only the verified Stage 9 payload, hash-pinned files from the Stage 2 archive
(README, documentation, manifests, source, tests, examples) and an optional validated
Architecture IR report. Evidence is extracted first; the narrative is built from it later.

Repository text is untrusted data. It is redacted, reduced to printable ASCII and quoted; it
never chooses a status, a scene or a template. Lines that read like instructions to a model
are counted and never become claims. Statuses follow fixed rules from the kind of evidence:
documentation is DOCUMENTATION_ONLY until code corroborates it (then INFERRED), code backed by
a Stage 9 verified claim is VERIFIED, and an outcome nothing supports is UNVERIFIED. When the
repository does not document its problem, the story says so; nothing is inferred from the
repository name.

In the media worker, `extract_story` runs inside the parser sandbox with architecture
discovery (`repovox.media.sandbox`). `verify_story` runs in the worker: it compares text and
hashes only, parses nothing, and refuses any claim whose citation, wording or status is not
reproducible from the pinned source bytes.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from repovox.analysis.budget import BUDGET_REASONS
from repovox.analysis.budget import REASONS as BUDGET_TIERS
from repovox.analysis.common import DEFAULT_LIMITS, canonical, digest
from repovox.analysis.contracts import PAYLOADS
from repovox.analysis.privacy import redact
from repovox.media.archgraph import sentence
from repovox.media.architecture import Architecture, ArchitectureError, Citation, Report, check
from repovox.media.story import (
    EXTRACTOR_VERSION,
    SCHEMA_VERSION,
    ArchitectureDescription,
    Claim,
    ClaimStatus,
    DemonstratedOutcomes,
    EngineeringStory,
    EvidenceRef,
    EvidenceType,
    ImplementationApproach,
    ImplementationEvidence,
    IntendedSolution,
    Limitations,
    Mismatch,
    MismatchKind,
    ProblemContext,
    ProblemStatement,
    ProofKind,
    SourceRole,
    StoryError,
    StorySource,
    UnresolvedQuestions,
)
from repovox.media.storyboard import RULE_TEXT, area, common_prefix, display

DOC_SUFFIXES = {".md", ".markdown", ".rst", ".adoc", ".txt"}
DOC_DIRS = {"docs", "doc", "documentation", "adr", "adrs", "design", "rfcs"}
NOT_NARRATIVE = {
    "license",
    "licence",
    "copying",
    "notice",
    "changelog",
    "changes",
    "history",
    "authors",
    "contributors",
    "contributing",
    "code_of_conduct",
    "security",
    "requirements",
}
EXAMPLE_DIRS = {"examples", "example", "samples", "sample", "demo", "demos"}
DOC_FILE_LIMIT = 256 * 1024
DOC_TOTAL_LIMIT = 2 * 1024**2
DOC_FILES = 64
DOC_LINES = 4000

INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿]")
ASCII = str.maketrans(
    {
        "—": "-",
        "–": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
        " ": " ",
        "•": "-",
    }
)
# Repository text that addresses a model instead of a reader. Counted, never narrated.
INSTRUCTION = re.compile(
    r"(?i)\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|prompts?|rules|guidelines)\b"
    r"|\bsystem prompt\b|\bjailbreak\b|\bas an ai\b"
    r"|\byou are (now )?(an? )?(ai|assistant|language model|llm|chatbot|chatgpt|claude|gpt)\b"
    r"|<\|?(system|assistant|im_start|im_end)\|?>"
)
FENCE = re.compile(r"^(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
BULLET = re.compile(r"^\s{0,6}([-*+]|\d{1,3}[.)])\s+")
SKIP_LINE = re.compile(r"^(\||<|!\[|\[!\[|\[[^\]]+\]:\s|[-=*_~]{3,}$|\.\. )")
SECTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "limitations",
        re.compile(
            r"\b(limitations?|known (issues?|limitations?|bugs?)|caveats?|non-goals?|"
            r"not supported|unsupported|todo|future work|roadmap)\b"
        ),
    ),
    ("problem", re.compile(r"\b(problems?|challenges?|pain points?|why\b|the need)")),
    ("context", re.compile(r"\b(motivation|background|context|rationale)\b")),
    ("decisions", re.compile(r"\b(decisions?|trade-?offs?|alternatives)\b")),
    ("performance", re.compile(r"\b(performance|benchmarks?|scalability)\b")),
    (
        "solution",
        re.compile(
            r"\b(solution|approach|goals?|features?|overview|about|introduction|"
            r"what it does|how it works|highlights|capabilit\w*)\b"
        ),
    ),
    (
        "usage",
        re.compile(
            r"\b(usage|getting started|quick ?start|install\w*|setup|examples?|tutorial|"
            r"running|how to|development|contributing|license|api reference)\b"
        ),
    ),
)
PROBLEM_CUE = re.compile(
    r"(?i)\b(problems?|struggle\w*|pain(ful)?|difficult|hard to|tedious|time-consuming|"
    r"error-prone|lack of|lacks|frustrat\w*)\b"
)
PERFORMANCE = re.compile(
    r"(?i)\b(blazing(ly)?|lightning|high[- ]performance|low[- ]latency|scalable|"
    r"\d+(\.\d+)?\s*(x|times)\s+(faster|quicker|smaller)|faster than|"
    r"\d+(\.\d+)?\s*(ms|milliseconds|requests per second|req/s|rps|qps|ops/s))\b"
)
PRODUCTION = re.compile(
    r"(?i)\b(in production|production[- ]ready|production[- ]grade|battle[- ]tested|"
    r"trusted by|used by (thousands|millions|hundreds|\d+))\b"
)
ASSERTION = re.compile(
    r"^(assert\b|self\.assert\w*\(|expect\(|assert\.\w+\(|(with )?pytest\.raises\(|"
    r"t\.(is|deepEqual|equal|true|false|throws)\()"
)
MARKER = re.compile(r"(?:#|//|/\*+|^\s*\*)\s*(TODO|FIXME|XXX|HACK)\b[:\s-]*(.{0,200})")
STUB = re.compile(
    r"(pass|\.\.\.|raise NotImplementedError(\(.*\))?|return NotImplemented|"
    r"throw new Error\((['\"`]).{0,60}not implemented.{0,20}\3\);?)",
    re.IGNORECASE,
)
DOCSTRING = re.compile(r"^[rRbBuU]?(\"\"\"|''')")

# name, documentation pattern, case-sensitive, import or dependency names
TECHNOLOGIES: tuple[tuple[str, str, bool, frozenset[str]], ...] = (
    ("FastAPI", r"fast ?api", False, frozenset({"fastapi"})),
    ("Flask", r"flask", False, frozenset({"flask"})),
    ("Django", r"django", False, frozenset({"django"})),
    ("Express", r"Express(?:\.js|JS)?|express\.js|expressjs", True, frozenset({"express"})),
    ("React", r"React(?:\.js|JS)?|react\.js|reactjs", True, frozenset({"react", "react-dom"})),
    ("Next.js", r"next\.?js", False, frozenset({"next"})),
    ("Vue", r"Vue(?:\.js|JS)?|vue\.js|vuejs", True, frozenset({"vue"})),
    (
        "PostgreSQL",
        r"postgres(?:ql)?",
        False,
        frozenset({"psycopg", "psycopg2", "psycopg2-binary", "asyncpg", "pg", "postgres"}),
    ),
    ("MySQL", r"mysql", False, frozenset({"mysql", "pymysql", "mysqlclient", "mysql2"})),
    ("SQLite", r"sqlite3?", False, frozenset({"sqlite3", "better-sqlite3", "sqlite"})),
    ("MongoDB", r"mongo(?:db)?", False, frozenset({"pymongo", "mongodb", "mongoose", "motor"})),
    ("Redis", r"redis", False, frozenset({"redis", "ioredis", "aioredis"})),
    ("SQLAlchemy", r"sqlalchemy", False, frozenset({"sqlalchemy"})),
    ("Celery", r"celery", False, frozenset({"celery"})),
    ("Kafka", r"kafka", False, frozenset({"kafka", "kafkajs", "confluent_kafka", "aiokafka"})),
    (
        "GraphQL",
        r"graphql",
        False,
        frozenset({"graphql", "strawberry", "ariadne", "graphene", "@apollo/server"}),
    ),
    ("PyTorch", r"py ?torch", False, frozenset({"torch"})),
    ("TensorFlow", r"tensor ?flow", False, frozenset({"tensorflow"})),
    ("scikit-learn", r"scikit-learn|sklearn", False, frozenset({"sklearn", "scikit-learn"})),
    ("pandas", r"pandas", False, frozenset({"pandas"})),
    ("NumPy", r"numpy", False, frozenset({"numpy"})),
    ("LangChain", r"lang ?chain", False, frozenset({"langchain"})),
    ("OpenAI API", r"openai", False, frozenset({"openai"})),
)
TECH_PATTERNS = {
    name: re.compile(rf"(?<![\w.-])(?:{pattern})(?![\w-])", 0 if case else re.IGNORECASE)
    for name, pattern, case, _ in TECHNOLOGIES
}
STOPWORDS = frozenset(
    """
    about above across after allow allows also among another based been before being below
    best better build built cannot code could does done each easy easily every fast fully
    from full have help helps high into just large level library light lightweight like make
    makes many modern more most much must need needs only other over powerful project
    provide provides python javascript typescript quick quickly simple single small some such
    support supports supported than that their them then there these they this those through
    tool tools under used uses using various very want well what when where which while will
    with within without work works your application applications system systems data file
    files user users feature features ready free open source easy-to-use offers include
    includes including written write runs running main self none true false return value
    values function functions class classes method methods module modules test tests
    """.split()
)
GENERIC_NAMES = frozenset({"main", "init", "run", "get", "set", "call", "self", "anonymous"})
TEMPLATES = {
    "problem_insufficient": (
        "The repository does not document the problem it solves, so no problem statement is "
        "given and none is inferred from its name."
    ),
    "language": "{count} of {language} source parsed, for example {path}.",
    "technology": "{path} imports {module}, which is {tech}.",
    "dependency": "{path} declares a dependency on {name}.",
    "entrypoint": "{path} {reason}, which makes it an entry point candidate.",
    "tests_present": "{count} found, for example {path}.",
    "subsystem": "The {area} area holds {count}, including {path}.",
    "route": "{path} registers a framework route on line {line}.",
    "declaration": "{path} declares the {kind} {name}.",
    "architecture_overview": ("{title}: {components} connected by {connections} in the source."),
    "component": "{label} is a {kind} in {group}.",
    "component_external": "{label} stands for a {kind} outside this repository.",
    "architecture_unavailable": (
        "Architecture discovery did not run for this story, so no architecture is described."
    ),
    "architecture_rejected": "Not established: {candidate}. {detail}",
    "test": "The test {name} in {path} asserts {assertion}",
    "example": "{path} is an example program in the repository; it was not run.",
    "benchmark": (
        "{path} is a benchmark file; it was not run, so no performance figure is established."
    ),
    "stub": "{kind} {name} in {path} has a placeholder body.",
    "marker": "{path} line {line} carries a {marker} marker: {text}",
    "runtime": (
        "Runtime behaviour, correctness and performance were not observed; RepoVox reads the "
        "source without running it."
    ),
    "no_tests": "No test files were found, so no behaviour is demonstrated by tests.",
    # The deterministic test-fact budget of a repository over the fact cap (ADR-0030).
    "fact_budget_1": (
        "The analysis exceeded its {limit}-fact cap, so call facts from {files} were omitted; "
        "their test definitions and imports were kept."
    ),
    "fact_budget_2": (
        "The analysis exceeded its {limit}-fact cap, so call and import facts from {files} "
        "were omitted; their test definitions were kept."
    ),
    "fact_budget_3": (
        "The analysis exceeded its {limit}-fact cap, so every fact from {files} was omitted, "
        "and those tests are not described."
    ),
    "feature_unbacked": (
        'Whether the documented feature "{feature}" is implemented is not established.'
    ),
    "technology_unused": (
        "Whether {tech} is used is not established: no analysed import or declared "
        "dependency names it."
    ),
    "performance_unbacked": (
        'The performance claim "{claim}" is not supported by any benchmark in the repository.'
    ),
    "production_unbacked": (
        'The claim "{claim}" about real-world use is not evidenced in the repository.'
    ),
    "architecture_unresolved": "{topic}: {reason}",
    "readme_only_feature": (
        "The documentation describes this feature, but no matching declaration was found in "
        "the analysed code."
    ),
    "mention_only_technology": (
        "The documentation names {tech}, but no analysed import or declared dependency uses it."
    ),
    "declared_only_technology": (
        "{tech} is declared as a dependency, but no analysed source file imports it."
    ),
    "unstated_implementation": "The code imports {tech}, which the documentation does not name.",
    "incomplete_implementation": (
        "{name} in {path} has a placeholder body, so what it names is not implemented here."
    ),
    "unbenchmarked_performance_claim": (
        "The documentation makes a performance claim that no benchmark in the repository supports."
    ),
    "unsupported_architecture_claim": (
        "The documentation names an architecture that static analysis did not find implemented."
    ),
}
DOC_ROLES: frozenset[str] = frozenset({"readme", "documentation"})
CODE_ROLES: frozenset[str] = frozenset({"source", "test", "example", "manifest"})
DOC_TYPES = frozenset({"author_stated_problem", "inferred_problem_context", "unverified_outcome"})


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9]*", text.lower()))


VOCABULARY = frozenset(
    set().union(*(words(re.sub(r"\{[a-z_]+\}", " ", t)) for t in TEMPLATES.values()))
    | set().union(*(words(name) for name, *_ in TECHNOLOGIES))
    | set().union(*(words(text) for text in RULE_TEXT.values()))
    | words("file files test tests parsed module modules function class method constructed")
    | words("part declared route source parameter returned value python javascript typescript")
    | words("tsx documentation configuration top level matches declared entry rule service")
    | words("handler external client library builtin built in component components")
    | words("relationship relationships static was were")
)


def file_lines(body: bytes) -> list[str]:
    return body.decode("utf-8", "replace").split("\n")


def quote_of(lines: list[str], start: int, end: int) -> str:
    """The exact cited text: each line redacted and stripped, nothing else changed."""
    return "\n".join(redact(line)[0].strip() for line in lines[start - 1 : end])[:1200]


def plain(text: str, limit: int = 300) -> str:
    """Documentation markup removed, then printable ASCII only; never adds a word."""
    text = INVISIBLE.sub("", text).translate(ASCII)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    text = re.sub(r"^\s{0,6}(#{1,6}\s+|>\s*|([-*+]|\d{1,3}[.)])\s+(\[[ xX]\]\s+)?)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    return display(text, limit)


def clip(text: str, limit: int) -> str:
    """Shorten at a word boundary so no partial word is ever narrated."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 3]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "..."


def checked_words(text: str) -> set[str]:
    """Words a claim asserts; a token cut short by an ellipsis is not one of them."""
    return words(re.sub(r"[A-Za-z0-9_]*\.\.\.", " ", text))


def plural(count: int, noun: str, many: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {many or noun + 's'}"


BUDGET_OPENING = "The analysis exceeded its "


def fact_budget(payload: dict[str, Any]) -> tuple[int, str | None]:
    """The test-fact budget tier the verified manifest records, and the story's statement."""
    reasons = [
        f["reason"]
        for f in payload["knowledge"]["coverage"]["files"]
        if f["reason"] in BUDGET_REASONS
    ]
    if not reasons:
        return 0, None
    tier = max(level for level, reason in BUDGET_TIERS.items() if reason in reasons)
    text = TEMPLATES[f"fact_budget_{tier}"].format(
        limit=f"{DEFAULT_LIMITS.facts:,}", files=plural(len(reasons), "test file")
    )
    return tier, clip(display(text, 4000), 300)


def variants(word: str) -> set[str]:
    """A word and its plain inflections, so "invoices" and "invoice" match."""
    found = {word}
    for suffix, replacement in (
        ("ies", "y"),
        ("es", ""),
        ("s", ""),
        ("ing", ""),
        ("ing", "e"),
        ("ed", ""),
        ("d", ""),
        ("er", ""),
        ("r", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            found.add(word[: -len(suffix)] + replacement)
    return found


def identifier_words(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return {w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if len(w) >= 4}


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z]{3,}", text.lower()) if w not in STOPWORDS}


def report_digest(report: Report) -> str:
    return digest(canonical(report.model_dump(mode="json")))


def report_words(report: Report | None) -> set[str]:
    if report is None:
        return set()
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.update(words(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(report.model_dump(mode="json"))
    return found


# ---------------------------------------------------------------------------------- sources


def role_of(entry: dict[str, Any]) -> SourceRole | None:
    path = PurePosixPath(entry["path"])
    first = path.parts[0].lower() if path.parts else ""
    if entry["status"] == "context":
        if entry["classification"] == "documentation":
            return "readme"
        return "manifest" if entry["classification"] == "configuration" else None
    if entry["status"] == "parsed":
        if entry["classification"] == "test":
            return "test"
        if entry["classification"] == "source":
            return "example" if first in EXAMPLE_DIRS and len(path.parts) > 1 else "source"
        return None
    if (entry["status"], entry["reason"], entry["classification"]) != (
        "skipped",
        "unsupported_language",
        "unsupported",
    ) or entry["bytes"] > DOC_FILE_LIMIT:
        return None
    suffix, stem = path.suffix.lower(), path.stem.lower()
    if len(path.parts) > 1 and first in DOC_DIRS and suffix in DOC_SUFFIXES:
        return "documentation"
    if len(path.parts) == 1 and suffix in DOC_SUFFIXES - {".txt"} and stem not in NOT_NARRATIVE:
        return "documentation"
    return None


def inventory(payload: dict[str, Any]) -> tuple[StorySource, ...]:
    """The files a story may cite, decided from the verified manifest alone."""
    found: list[StorySource] = []
    documents: list[dict[str, Any]] = []
    for entry in payload["knowledge"]["coverage"]["files"]:
        role = role_of(entry)
        if role == "documentation":
            documents.append(entry)
        elif role is not None:
            found.append(
                StorySource(path=entry["path"], file_sha256=entry["file_sha256"], role=role)
            )
    total = 0
    for entry in sorted(documents, key=lambda e: (e["path"].count("/"), e["path"]))[:DOC_FILES]:
        if total + entry["bytes"] <= DOC_TOTAL_LIMIT:
            total += entry["bytes"]
            found.append(
                StorySource(
                    path=entry["path"], file_sha256=entry["file_sha256"], role="documentation"
                )
            )
    return tuple(sorted(found, key=lambda s: s.path))


def story_sources(root: Path, payload: dict[str, Any]) -> dict[str, bytes]:
    """Read every inventoried file from an extracted archive, each checked against its hash."""
    base = root.resolve()
    found: dict[str, bytes] = {}
    for source in inventory(payload):
        candidate = root / source.path
        path = candidate.resolve()
        if candidate.is_symlink() or not path.is_relative_to(base) or not path.is_file():
            raise StoryError("source_mismatch")
        body = path.read_bytes()
        if digest(body) != source.file_sha256:
            raise StoryError("source_mismatch")
        found[source.path] = body
    return found


# ------------------------------------------------------------------------------- extraction


@dataclass(frozen=True)
class DocLine:
    path: str
    number: int
    section: str
    bullet: bool
    text: str


@dataclass(frozen=True)
class Stub:
    symbol: dict[str, Any]
    line: int


class Facts:
    """Verified payload, inventoried sources and the claims each symbol may cite."""

    def __init__(
        self, payload: dict[str, Any], sources: dict[str, bytes], report: Report | None
    ) -> None:
        try:
            PAYLOADS["verify"].model_validate(payload)
        except ValueError:
            raise StoryError("invalid_analysis_payload") from None
        knowledge = payload["knowledge"]
        self.payload, self.report = payload, report
        self.snapshot = knowledge["repository"]
        self.inventory = inventory(payload)
        self.roles: dict[str, str] = {s.path: s.role for s in self.inventory}
        if set(sources) != set(self.roles) or any(
            digest(sources[s.path]) != s.file_sha256 for s in self.inventory
        ):
            raise StoryError("source_mismatch")
        self.sources = sources
        self.hashes = {s.path: s.file_sha256 for s in self.inventory}
        self.lines = {path: file_lines(body) for path, body in sources.items()}
        self.manifest = {f["path"]: f for f in knowledge["coverage"]["files"]}
        self.symbols: dict[str, dict[str, Any]] = {s["id"]: s for s in knowledge["symbols"]}
        verdicts = {v["claim_id"]: v for v in payload["verification"]["verdicts"]}
        valid = {e["id"] for e in payload["evidence"]["items"] if e["validation_status"] == "valid"}
        self.citable: dict[str, tuple[str, str]] = {}  # subject id -> (claim id, status)
        self.subject_of: dict[str, str] = {}
        for claim in knowledge["claims"]:
            verdict = verdicts.get(claim["id"])
            if (
                verdict is not None
                and verdict["status"] in {"verified", "inferred"}
                and verdict["evidence_ids"]
                and all(e in valid for e in verdict["evidence_ids"])
            ):
                self.citable[claim["subject_id"]] = (claim["id"], verdict["status"])
                self.subject_of[claim["id"]] = claim["subject_id"]

    def role(self, path: str) -> str | None:
        return self.roles.get(path)

    def cited(self, symbol: dict[str, Any]) -> tuple[str, str] | None:
        return self.citable.get(symbol["id"])

    def first_line(self, path: str, start: int = 1, end: int | None = None) -> int | None:
        lines = self.lines.get(path, [])
        for number in range(start, min(end or len(lines), len(lines)) + 1):
            if quote_of(lines, number, number):
                return number
        return None

    def symbols_where(
        self, *kinds: str, roles: Iterable[str] = ("source",)
    ) -> list[dict[str, Any]]:
        wanted = set(roles)
        return sorted(
            (
                s
                for s in self.symbols.values()
                if s["kind"] in kinds and self.role(s["path"]) in wanted and self.cited(s)
            ),
            key=lambda s: (s["path"], s["start_line"], s["id"]),
        )


class Builder:
    """Accumulates claims per artifact; identical claims are kept once."""

    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.groups: dict[str, dict[str, Claim]] = {}
        self.mismatches: dict[str, Mismatch] = {}
        self.instructions = 0

    def ref(self, owner: str, path: str, start: int, end: int) -> EvidenceRef | None:
        lines = self.facts.lines.get(path)
        if lines is None or not 1 <= start <= end <= len(lines) or end - start > 7:
            return None
        quote = quote_of(lines, start, end)
        if not quote or not quote.split("\n")[0]:
            return None
        snapshot = self.facts.snapshot
        return EvidenceRef(
            id=f"e-{digest(canonical([owner, path, start, end]))[:20]}",
            path=path,
            file_sha256=self.facts.hashes[path],
            start_line=start,
            end_line=end,
            quote=quote,
            permalink=permalink(snapshot, path, start, end),
        )

    def claim(
        self,
        artifact: str,
        evidence_type: EvidenceType,
        status: ClaimStatus,
        text: str,
        spans: list[tuple[str, int, int]],
        *,
        analysis: Iterable[str] = (),
        supports: Iterable[str] = (),
        proof: ProofKind | None = None,
        components: Iterable[str] = (),
        connections: Iterable[str] = (),
    ) -> Claim | None:
        text = clip(display(text, 4000), 300)
        spans = list(dict.fromkeys(spans))[:8]
        key = digest(canonical([artifact, evidence_type, text, [list(s) for s in spans]]))
        identity = f"{artifact[:1]}-{key[:20]}"
        refs = [r for r in (self.ref(identity, *span) for span in spans) if r is not None]
        if spans and len(refs) != len(spans):
            return None  # A citation that cannot be quoted exactly is dropped, never published.
        group = self.groups.setdefault(artifact, {})
        if identity in group:
            return group[identity]
        try:
            claim = Claim(
                id=identity,
                text=text,
                evidence_type=evidence_type,
                status=status,
                evidence_refs=tuple(refs),
                source_location=f"{refs[0].path}:{refs[0].start_line}" if refs else None,
                analysis_claim_ids=tuple(dict.fromkeys(analysis))[:16],
                supports=tuple(dict.fromkeys(supports))[:8],
                proof=proof,
                component_ids=tuple(dict.fromkeys(components))[:16],
                connection_ids=tuple(dict.fromkeys(connections))[:16],
            )
        except ValidationError:
            raise StoryError("story_invalid") from None
        group[identity] = claim
        return claim

    def take(self, artifact: str, limit: int) -> tuple[Claim, ...]:
        return tuple(self.groups.get(artifact, {}).values())[:limit]

    def mismatch(
        self, kind: MismatchKind, detail: str, stated: Iterable[Claim], evidence: Iterable[Claim]
    ) -> None:
        stated_ids = tuple(dict.fromkeys(c.id for c in stated))[:8]
        evidence_ids = tuple(dict.fromkeys(c.id for c in evidence))[:8]
        if not stated_ids and not evidence_ids:
            return
        # Two technologies named on one line are two mismatches, so the detail is part of it.
        identity = f"x-{digest(canonical([kind, detail, stated_ids, evidence_ids]))[:20]}"
        self.mismatches.setdefault(
            identity,
            Mismatch(
                id=identity,
                kind=kind,
                detail=display(detail, 300),
                stated_claim_ids=stated_ids,
                evidence_claim_ids=evidence_ids,
            ),
        )


def permalink(snapshot: dict[str, Any], path: str, start: int, end: int) -> str:
    from urllib.parse import quote

    return (
        f"{snapshot['canonical_url']}/blob/{snapshot['commit_sha']}/"
        f"{quote(path, safe='/')}#L{start}-L{end}"
    )


def classify(title: str, adr: bool) -> str:
    title = title.lower()
    if adr and re.search(r"\bcontext\b", title):
        return "context"
    if adr and re.search(r"\bdecision\b", title):
        return "decisions"
    for name, pattern in SECTIONS:
        if pattern.search(title):
            return name
    return "other"


def document_lines(builder: Builder, path: str, readme: bool) -> list[DocLine]:
    lines = builder.facts.lines[path]
    adr = bool(re.search(r"(^|/)(adrs?|decisions)/|(^|/)adr[-_ ]?\d", path.lower()))
    section, titled, fence = ("intro" if readme else "other"), False, False
    found: list[DocLine] = []
    for number, raw in enumerate(lines[:DOC_LINES], 1):
        stripped = raw.strip()
        if FENCE.match(stripped):
            fence = not fence
            continue
        if fence or not stripped:
            continue
        heading = HEADING.match(stripped)
        if heading:
            if len(heading.group(1)) == 1 and not titled:
                titled = True
                continue  # The document title; the paragraph after it is the introduction.
            section = classify(plain(heading.group(2), 120), adr)
            continue
        if SKIP_LINE.match(stripped):
            continue
        text = plain(quote_of(lines, number, number))
        if INSTRUCTION.search(text) or INSTRUCTION.search(raw):
            builder.instructions += 1
            continue
        if len(text) < 12 or len(text.split()) < 3:
            continue
        found.append(DocLine(path, number, section, bool(BULLET.match(raw)), text))
    return found


def module_root(name: str) -> str | None:
    name = name.strip()
    if not name or name.startswith((".", "/")):
        return None
    if name.startswith("@"):
        return "/".join(name.split("/")[:2]).lower()
    return re.split(r"[./]", name, maxsplit=1)[0].lower() or None


def technology_of(root: str) -> str | None:
    for name, _, _, roots in TECHNOLOGIES:
        if root in roots:
            return name
    return None


def stub_line(facts: Facts, symbol: dict[str, Any]) -> int | None:
    """The placeholder statement of a declaration whose whole body is a placeholder."""
    path, start, end = symbol["path"], symbol["start_line"], symbol["end_line"]
    lines = facts.lines.get(path, [])
    if end <= start or end > len(lines) or path.endswith(".pyi"):
        return None
    above = " ".join(lines[max(0, start - 3) : start - 1])
    if re.search(r"@(abc\.)?abstract|@(typing\.)?overload|Protocol", above):
        return None
    remaining: list[tuple[int, str]] = []
    in_docstring = False
    for number in range(start + 1, end + 1):
        text = lines[number - 1].strip()
        if in_docstring:
            in_docstring = not (text.endswith('"""') or text.endswith("'''"))
            continue
        if DOCSTRING.match(text):
            body = DOCSTRING.sub("", text, count=1)
            in_docstring = not (body.endswith('"""') or body.endswith("'''"))
            continue
        if not text or text.startswith(("#", "//", "/*", "*")) or text in {"{", "}", "};", "})"}:
            continue
        remaining.append((number, text))
    if not remaining:
        return None  # An empty or docstring-only body is not flagged.
    if all(STUB.fullmatch(text) for _, text in remaining):
        return remaining[0][0]
    return None


def extract_story(
    payload: dict[str, Any],
    sources: dict[str, bytes],
    report: Report | None = None,
    unavailable: str | None = None,
) -> EngineeringStory:
    """Build the evidence-first engineering story for one pinned commit, then verify it."""
    facts = Facts(payload, sources, report)
    builder = Builder(facts)
    knowledge = payload["knowledge"]
    # Stated first, so no cap on open questions can drop it.
    budget_tier, budget_text = fact_budget(payload)
    if budget_text is not None:
        builder.claim("unresolved_questions", "unresolved", "UNVERIFIED", budget_text, [])

    # 1. Documentation: what the authors state. Never VERIFIED.
    readmes = sorted(
        (s.path for s in facts.inventory if s.role == "readme"),
        key=lambda p: (p.count("/"), p),
    )
    documents = readmes + [s.path for s in facts.inventory if s.role == "documentation"]
    lines: list[DocLine] = []
    for path in documents:
        lines += document_lines(builder, path, bool(readmes) and path == readmes[0])

    def doc_claim(artifact: str, kind: EvidenceType, line: DocLine) -> Claim | None:
        status: ClaimStatus = "UNVERIFIED" if kind == "unverified_outcome" else "DOCUMENTATION_ONLY"
        span = [(line.path, line.number, line.number)]
        return builder.claim(artifact, kind, status, line.text, span)

    intro = [line for line in lines if line.section == "intro"][:4]
    problems = [line for line in intro if PROBLEM_CUE.search(line.text)]
    problems += [line for line in lines if line.section == "problem"]
    for line in problems[:6]:
        doc_claim("problem_statement", "author_stated_problem", line)
    for line in [line for line in lines if line.section == "context"][:4]:
        doc_claim("problem_context", "inferred_problem_context", line)
    intended_lines = [line for line in intro if not PROBLEM_CUE.search(line.text)][:3]
    intended_lines += [line for line in lines if line.section == "solution"][:8]
    for line in [line for line in lines if line.section == "decisions"][:4]:
        doc_claim("implementation_approach", "intended_solution", line)
    limitation_lines = [line for line in lines if line.section == "limitations"][:6]
    outcome_lines = [
        line
        for line in lines
        if line.section not in {"usage", "limitations"}
        and (PERFORMANCE.search(line.text) or PRODUCTION.search(line.text))
    ][:4]
    mentions: dict[str, DocLine] = {}
    for line in lines:
        if line.section in {"usage", "limitations"}:
            continue
        for name, pattern in TECH_PATTERNS.items():
            if name not in mentions and pattern.search(line.text):
                mentions[name] = line
    for line in mentions.values():
        if line not in intended_lines:
            intended_lines.append(line)

    # 2. Implementation: what the pinned commit contains, from Stage 9 claims.
    declared_symbols = facts.symbols_where(
        "function", "class", "method", roles=("source", "example")
    )
    stubs = {
        s["id"]: Stub(s, at)
        for s in declared_symbols
        if s["kind"] != "class" and (at := stub_line(facts, s)) is not None
    }
    imports: dict[str, tuple[dict[str, Any], str]] = {}
    for symbol in facts.symbols_where("import", roles=("source", "example", "test")):
        root = module_root(str(symbol["syntax"].get("import_module") or symbol["name"]))
        tech = technology_of(root) if root else None
        if tech is None or root is None:
            continue
        held = imports.get(tech)
        if held is None or (
            facts.role(held[0]["path"]) == "test" and facts.role(symbol["path"]) != "test"
        ):
            imports[tech] = (symbol, root)
    dependencies = facts.symbols_where("declared_dependency", roles=("manifest",))

    def dependency_name(symbol: dict[str, Any]) -> str:
        return re.split(r"[\s\[<>=!~^;]", str(symbol["name"]).strip(), maxsplit=1)[0]

    def symbol_claim(
        artifact: str, symbol: dict[str, Any], text: str, numbers: list[int]
    ) -> Claim | None:
        cited = facts.cited(symbol)
        if cited is None or not all(numbers):
            return None
        status: ClaimStatus = "VERIFIED" if cited[1] == "verified" else "INFERRED"
        spans = [(symbol["path"], n, n) for n in numbers]
        return builder.claim(
            artifact, "implemented_solution", status, text, spans, analysis=[cited[0]]
        )

    def module_line(symbol: dict[str, Any]) -> int:
        return facts.first_line(symbol["path"], symbol["start_line"], symbol["end_line"]) or 0

    modules = facts.symbols_where("module", roles=("source",))
    languages = sorted(
        knowledge["coverage"].get("language_coverage", {}).items(),
        key=lambda item: (-item[1]["files"], item[0]),
    )[:3]
    for language, stats in languages:
        sample = next((m for m in modules if m["parser_language"] == language), None)
        if sample is not None:
            symbol_claim(
                "implementation_approach",
                sample,
                TEMPLATES["language"].format(
                    count=plural(stats["files"], "file"), language=language, path=sample["path"]
                ),
                [module_line(sample)],
            )
    technology_claims: dict[str, Claim] = {}
    for tech, (symbol, root) in sorted(imports.items()):
        made = symbol_claim(
            "implementation_approach",
            symbol,
            TEMPLATES["technology"].format(path=symbol["path"], module=root, tech=tech),
            [symbol["start_line"]],
        )
        if made is not None:
            technology_claims[tech] = made
    dependency_claims: dict[str, Claim] = {}
    ranked = sorted(
        dependencies,
        key=lambda s: (
            technology_of(dependency_name(s).lower()) is None,
            s["path"],
            s["start_line"],
        ),
    )
    for position, symbol in enumerate(ranked):
        tech = technology_of(dependency_name(symbol).lower())
        if position >= 3 and (tech is None or tech in dependency_claims):
            continue
        made = symbol_claim(
            "implementation_approach",
            symbol,
            TEMPLATES["dependency"].format(path=symbol["path"], name=dependency_name(symbol)),
            [symbol["start_line"]],
        )
        if made is not None and tech is not None:
            dependency_claims.setdefault(tech, made)

    def support_claim(artifact: str, candidate: dict[str, Any], text: str) -> Claim | None:
        # The candidate's own symbol first, so the claim's location is the line it describes.
        ordered = sorted(candidate["support_ids"], key=lambda i: i != candidate["symbol_id"])
        supports = [facts.symbols[i] for i in ordered if i in facts.symbols]
        cited = [facts.cited(s) for s in supports]
        if not supports or any(c is None for c in cited):
            return None
        found = [c for c in cited if c is not None]
        spans = [(s["path"], s["start_line"], s["start_line"]) for s in supports]
        return builder.claim(
            artifact,
            "implemented_solution",
            "VERIFIED" if all(c[1] == "verified" for c in found) else "INFERRED",
            text,
            spans,
            analysis=[c[0] for c in found],
        )

    candidates = knowledge["entrypoints"]["candidates"]
    entries: set[str] = set()
    for candidate in candidates:
        if (
            candidate["rule"] == "framework-route-v1"
            or candidate["path"] in entries
            or len(entries) >= 3
            or facts.role(candidate["path"]) not in {"source", "example"}
        ):
            continue
        reason = RULE_TEXT.get(candidate["rule"], "matches a declared entry rule")
        if support_claim(
            "implementation_approach",
            candidate,
            TEMPLATES["entrypoint"].format(path=candidate["path"], reason=reason),
        ):
            entries.add(candidate["path"])
    test_modules = facts.symbols_where("module", roles=("test",))
    if test_modules:
        symbol_claim(
            "implementation_approach",
            test_modules[0],
            TEMPLATES["tests_present"].format(
                count=plural(len(test_modules), "test file"), path=test_modules[0]["path"]
            ),
            [module_line(test_modules[0])],
        )

    prefix = common_prefix([m["path"] for m in modules])
    areas: dict[str, list[dict[str, Any]]] = {}
    for module in modules:
        areas.setdefault(area(module["path"], prefix), []).append(module)
    for name, members in sorted(areas.items(), key=lambda item: (-len(item[1]), item[0]))[:5]:
        biggest = max(members, key=lambda s: (s["end_line"] - s["start_line"], s["path"]))
        symbol_claim(
            "implementation_evidence",
            biggest,
            TEMPLATES["subsystem"].format(
                area=name, count=plural(len(members), "parsed module"), path=biggest["path"]
            ),
            [module_line(biggest)],
        )
    for candidate in [c for c in candidates if c["rule"] == "framework-route-v1"][:4]:
        route = facts.symbols.get(candidate["symbol_id"])
        if route is not None and facts.role(candidate["path"]) in {"source", "example"}:
            support_claim(
                "implementation_evidence",
                candidate,
                TEMPLATES["route"].format(path=candidate["path"], line=route["start_line"]),
            )

    # Incomplete implementations and unfinished-work markers.
    stub_claims: dict[str, Claim] = {}
    for stub in list(stubs.values())[:6]:
        symbol = stub.symbol
        cited = facts.cited(symbol)
        made = builder.claim(
            "limitations",
            "limitation",
            "INFERRED",
            TEMPLATES["stub"].format(
                kind=symbol["kind"].capitalize(), name=symbol["name"], path=symbol["path"]
            ),
            [
                (symbol["path"], symbol["start_line"], symbol["start_line"]),
                (symbol["path"], stub.line, stub.line),
            ],
            analysis=[cited[0]] if cited else [],
        )
        if made is not None:
            stub_claims[symbol["id"]] = made
            builder.mismatch(
                "incomplete_implementation",
                TEMPLATES["incomplete_implementation"].format(
                    name=symbol["name"], path=symbol["path"]
                ),
                (),
                (made,),
            )
    markers = 0
    for source in facts.inventory:
        if source.role not in {"source", "test", "example"}:
            continue
        for number, raw in enumerate(facts.lines[source.path], 1):
            found = MARKER.search(raw)
            if found is None or markers >= 4:
                continue
            if INSTRUCTION.search(raw):
                builder.instructions += 1
                continue
            if builder.claim(
                "limitations",
                "limitation",
                "INFERRED",
                TEMPLATES["marker"].format(
                    path=source.path,
                    line=number,
                    marker=found.group(1),
                    text=plain(found.group(2), 160) or "-",
                ),
                [(source.path, number, number)],
            ):
                markers += 1
    for line in limitation_lines:
        doc_claim("limitations", "limitation", line)

    # 3. Intended solution, corroborated by code whose declared names match.
    index: list[tuple[dict[str, Any], set[str]]] = []
    for symbol in declared_symbols:
        named = identifier_words(str(symbol["name"])) - GENERIC_NAMES - STOPWORDS
        found_words = {v for w in named for v in variants(w)}
        if found_words:
            index.append((symbol, found_words))
    declared_words = set().union(*(found for _, found in index))
    for line in intended_lines:
        terms = content_words(line.text)
        wanted = {v for w in terms for v in variants(w)}
        covered = sum(bool(variants(w) & declared_words) for w in terms)
        # One shared word is coincidence: corroboration needs two of the statement's content
        # words in declared names, or the only word of a one- or two-word statement.
        enough = covered >= 2 or (0 < len(terms) <= 2 and covered >= 1)
        matched = sorted(
            (
                (symbol, len(found & wanted))
                for symbol, found in (index if enough else [])
                if found & wanted
            ),
            key=lambda item: (-item[1], item[0]["path"], item[0]["start_line"]),
        )
        supports: list[Claim] = []
        stubbed: list[tuple[dict[str, Any], Claim]] = []
        for symbol, _ in matched[:4]:
            if symbol["id"] in stubs:
                if symbol["id"] in stub_claims:
                    stubbed.append((symbol, stub_claims[symbol["id"]]))
                continue
            if len(supports) >= 2:
                continue
            made = symbol_claim(
                "implementation_evidence",
                symbol,
                TEMPLATES["declaration"].format(
                    path=symbol["path"], kind=symbol["kind"], name=symbol["name"]
                ),
                [symbol["start_line"]],
            )
            # Only a claim the story will publish can corroborate; one past its cap cannot.
            if made is not None and made.id in kept_ids(builder):
                supports.append(made)
        named_tech = [tech for tech, mention in mentions.items() if mention == line]
        supports += [
            technology_claims[t]
            for t in named_tech
            if t in technology_claims and technology_claims[t].id in kept_ids(builder)
        ]
        intended = builder.claim(
            "intended_solution",
            "intended_solution",
            "INFERRED" if supports else "DOCUMENTATION_ONLY",
            line.text,
            [(line.path, line.number, line.number)],
            supports=[c.id for c in supports],
        )
        if intended is None:
            continue
        span = [(line.path, line.number, line.number)]
        if stubbed and not supports:
            for symbol, evidence in stubbed:
                builder.mismatch(
                    "incomplete_implementation",
                    TEMPLATES["incomplete_implementation"].format(
                        name=symbol["name"], path=symbol["path"]
                    ),
                    (intended,),
                    (evidence,),
                )
        elif not supports and not named_tech:
            builder.mismatch(
                "readme_only_feature", TEMPLATES["readme_only_feature"], (intended,), ()
            )
            builder.claim(
                "unresolved_questions",
                "unresolved",
                "UNVERIFIED",
                TEMPLATES["feature_unbacked"].format(feature=clip(line.text, 160)),
                span,
            )
        for tech in named_tech:
            if tech in technology_claims:
                continue
            if tech in dependency_claims:
                builder.mismatch(
                    "declared_only_technology",
                    TEMPLATES["declared_only_technology"].format(tech=tech),
                    (intended,),
                    (dependency_claims[tech],),
                )
                continue
            builder.mismatch(
                "mention_only_technology",
                TEMPLATES["mention_only_technology"].format(tech=tech),
                (intended,),
                (),
            )
            builder.claim(
                "unresolved_questions",
                "unresolved",
                "UNVERIFIED",
                TEMPLATES["technology_unused"].format(tech=tech),
                span,
            )
    if intended_lines:
        for tech, made in sorted(technology_claims.items()):
            if tech not in mentions:
                builder.mismatch(
                    "unstated_implementation",
                    TEMPLATES["unstated_implementation"].format(tech=tech),
                    (),
                    (made,),
                )

    # 4. Demonstrated outcomes: assertions in tests and examples, never executed.
    benchmark = False
    tests = [
        s
        for s in facts.symbols_where("function", "method", "call", roles=("test",))
        if (s["kind"] != "call" and str(s["name"]).startswith("test"))
        or (s["kind"] == "call" and s["name"] in {"it", "test"})
    ]
    per_file: Counter[str] = Counter()
    for symbol in tests:
        outcomes = builder.groups.get("demonstrated_outcomes", {})
        if len(outcomes) >= 6 or per_file[symbol["path"]] >= 2:
            continue
        body = facts.lines[symbol["path"]]
        found_line = next(
            (
                n
                for n in range(symbol["start_line"], min(symbol["end_line"], len(body)) + 1)
                if ASSERTION.match(body[n - 1].strip())
            ),
            None,
        )
        cited = facts.cited(symbol)
        if found_line is None or cited is None or INSTRUCTION.search(body[found_line - 1]):
            continue
        name = str(symbol["name"])
        if symbol["kind"] == "call":
            label = re.search(r"\(\s*(['\"`])(.{1,80}?)\1", body[symbol["start_line"] - 1])
            if label is None:
                continue
            name = f'"{plain(label.group(2), 80)}"'
        parts = {p.lower() for p in PurePosixPath(symbol["path"]).parts}
        proof: ProofKind = (
            "benchmark"
            if "bench" in symbol["path"].lower()
            else "integration_test"
            if parts & {"integration", "e2e", "functional", "acceptance"}
            else "unit_test"
        )
        benchmark = benchmark or proof == "benchmark"
        if builder.claim(
            "demonstrated_outcomes",
            "demonstrated_outcome",
            "VERIFIED" if cited[1] == "verified" else "INFERRED",
            TEMPLATES["test"].format(
                name=name,
                path=symbol["path"],
                assertion=re.sub(
                    r"^assert\s+", "", plain(quote_of(body, found_line, found_line), 160)
                ),
            ),
            [
                (symbol["path"], symbol["start_line"], symbol["start_line"]),
                (symbol["path"], found_line, found_line),
            ],
            analysis=[cited[0]],
            proof=proof,
        ):
            per_file[symbol["path"]] += 1
    for module in facts.symbols_where("module", roles=("source", "test", "example")):
        cited = facts.cited(module)
        number = module_line(module)
        if cited is None or not number:
            continue
        status: ClaimStatus = "VERIFIED" if cited[1] == "verified" else "INFERRED"
        kind: ProofKind | None = (
            "benchmark"
            if "bench" in module["path"].lower()
            else "example"
            if facts.role(module["path"]) == "example"
            else None
        )
        if kind is None:
            continue
        benchmark = benchmark or kind == "benchmark"
        builder.claim(
            "demonstrated_outcomes",
            "demonstrated_outcome",
            status,
            TEMPLATES[kind].format(path=module["path"]),
            [(module["path"], number, number)],
            analysis=[cited[0]],
            proof=kind,
        )
    for line in outcome_lines:
        made = doc_claim("demonstrated_outcomes", "unverified_outcome", line)
        if made is None:
            continue
        span = [(line.path, line.number, line.number)]
        if not PERFORMANCE.search(line.text):
            builder.claim(
                "unresolved_questions",
                "unresolved",
                "UNVERIFIED",
                TEMPLATES["production_unbacked"].format(claim=clip(line.text, 160)),
                span,
            )
        elif not benchmark:
            builder.mismatch(
                "unbenchmarked_performance_claim",
                TEMPLATES["unbenchmarked_performance_claim"],
                (made,),
                (),
            )
            builder.claim(
                "unresolved_questions",
                "unresolved",
                "UNVERIFIED",
                TEMPLATES["performance_unbacked"].format(claim=clip(line.text, 160)),
                span,
            )

    # 5. Architecture, linked to the validated Universal Architecture IR.
    architecture = describe_architecture(builder, report, unavailable)
    if report is not None and report.explanation == "unsupported":
        named_lines = {
            (m.path, m.line)
            for r in report.rejected
            if r.reason == "mention_without_implementation"
            for m in r.mentions
            if facts.role(m.path) in DOC_ROLES
        }
        stated = [
            c
            for c in builder.groups.get("intended_solution", {}).values()
            if (c.evidence_refs[0].path, c.evidence_refs[0].start_line) in named_lines
        ]
        if stated:
            builder.mismatch(
                "unsupported_architecture_claim",
                TEMPLATES["unsupported_architecture_claim"],
                stated,
                (),
            )

    # 6. What remains open.
    # When the budget omitted every test fact, test files exist and the budget says so.
    if not test_modules and budget_tier < 3:
        builder.claim("unresolved_questions", "unresolved", "UNVERIFIED", TEMPLATES["no_tests"], [])
    if report is not None and report.architectures:
        for item in report.architectures[0].unresolved[:3]:
            builder.claim(
                "unresolved_questions",
                "unresolved",
                "UNVERIFIED",
                TEMPLATES["architecture_unresolved"].format(
                    topic=item.topic.capitalize(), reason=item.reason
                ),
                [],
            )
    builder.claim("unresolved_questions", "unresolved", "UNVERIFIED", TEMPLATES["runtime"], [])

    problem_claims = builder.take("problem_statement", 12)
    if not problem_claims:
        insufficient = builder.claim(
            "problem_statement", "unresolved", "UNVERIFIED", TEMPLATES["problem_insufficient"], []
        )
        problem_claims = (insufficient,) if insufficient else ()
    approach = tuple(builder.groups.get("implementation_approach", {}).values())
    try:
        story = EngineeringStory(
            schema_version=SCHEMA_VERSION,
            extractor_version=EXTRACTOR_VERSION,
            repository=display(facts.snapshot["repository"], 200),
            commit_sha=facts.snapshot["commit_sha"],
            analysis_sha256=digest(canonical(payload)),
            sources=facts.inventory,
            problem_statement=ProblemStatement(
                sufficiency="documented"
                if any(c.evidence_type == "author_stated_problem" for c in problem_claims)
                else "insufficient",
                claims=problem_claims,
            ),
            problem_context=ProblemContext(claims=builder.take("problem_context", 12)),
            intended_solution=IntendedSolution(claims=builder.take("intended_solution", 16)),
            implementation_approach=ImplementationApproach(
                claims=tuple(c for c in approach if c.evidence_type == "implemented_solution")[:16],
                decisions=tuple(c for c in approach if c.evidence_type == "intended_solution")[:4]
                + decisions_of(builder, report),
            ),
            architecture=architecture,
            implementation_evidence=ImplementationEvidence(
                claims=builder.take("implementation_evidence", 16)
            ),
            demonstrated_outcomes=DemonstratedOutcomes(
                claims=builder.take("demonstrated_outcomes", 16)
            ),
            limitations=Limitations(claims=builder.take("limitations", 16)),
            unresolved_questions=UnresolvedQuestions(
                claims=builder.take("unresolved_questions", 24)
            ),
            mismatches=tuple(m for m in builder.mismatches.values() if referenced(m, builder))[:32],
            instruction_like_lines=builder.instructions,
        )
    except ValidationError:
        raise StoryError("story_invalid") from None
    verify_story(story, payload, sources, report)  # The extractor's output gets no exemption.
    return story


# The artifact caps `extract_story` applies when it assembles the story, as the schema allows.
CAPS = {
    "problem_statement": 12,
    "problem_context": 12,
    "intended_solution": 16,
    "implementation_evidence": 16,
    "demonstrated_outcomes": 16,
    "limitations": 16,
    "unresolved_questions": 24,
}


def kept_ids(builder: Builder) -> set[str]:
    """Claims that survive the artifact caps. A claim keeps its position once it is made."""
    approach = list(builder.groups.get("implementation_approach", {}).values())
    implemented = [c for c in approach if c.evidence_type == "implemented_solution"][:16]
    decisions = [c for c in approach if c.evidence_type == "intended_solution"][:4]
    return {c.id for artifact, limit in CAPS.items() for c in builder.take(artifact, limit)} | {
        c.id for c in implemented + decisions
    }


def referenced(mismatch: Mismatch, builder: Builder) -> bool:
    """A mismatch survives only if every claim it names survived the artifact caps."""
    return set(mismatch.stated_claim_ids + mismatch.evidence_claim_ids) <= kept_ids(builder)


def citation_spans(citations: Iterable[Citation], limit: int = 4) -> list[tuple[str, int, int]]:
    return list(dict.fromkeys((c.path, c.line, c.line) for c in citations))[:limit]


def citation_claims(citations: Iterable[Citation]) -> list[str]:
    return [claim for c in citations for claim in c.claim_ids]


def ir_status(status: str) -> ClaimStatus | None:
    return "VERIFIED" if status == "VERIFIED" else "INFERRED" if status == "INFERRED" else None


def primary_view(architecture: Architecture) -> tuple[set[str], set[str], str | None]:
    if architecture.views:
        view = architecture.views[0]
        return set(view.component_ids), set(view.connection_ids), view.id
    return (
        {c.id for c in architecture.components},
        {c.id for c in architecture.connections},
        None,
    )


def describe_architecture(
    builder: Builder, report: Report | None, unavailable: str | None
) -> ArchitectureDescription:
    if report is None:
        made = builder.claim(
            "architecture", "unresolved", "UNVERIFIED", TEMPLATES["architecture_unavailable"], []
        )
        return ArchitectureDescription(
            ir_version=None,
            report_sha256=None,
            explanation="unavailable",
            unavailable_reason=unavailable or "architecture_not_supplied",
            architecture_ids=(),
            primary=None,
            view=None,
            claims=(made,) if made else (),
            workflow=(),
        )
    ids = tuple(a.id for a in report.architectures[:3])
    if not report.architectures:
        for rejected in report.rejected[:2]:
            spans = [
                (m.path, m.line, m.line) for m in rejected.mentions if builder.facts.role(m.path)
            ][:4]
            builder.claim(
                "architecture",
                "unresolved",
                "UNVERIFIED",
                TEMPLATES["architecture_rejected"].format(
                    candidate=(
                        "an architecture"
                        if rejected.candidate == "architecture"
                        else f"a {rejected.candidate.replace('_', ' ')} architecture"
                    ),
                    detail=rejected.detail,
                ),
                spans,
            )
        return ArchitectureDescription(
            ir_version=report.version,
            report_sha256=report_digest(report),
            explanation=report.explanation,
            unavailable_reason=None,
            architecture_ids=ids,
            primary=None,
            view=None,
            claims=builder.take("architecture", 12),
            workflow=(),
        )
    primary = report.architectures[0]
    members, links, view = primary_view(primary)
    parts = {c.id: c for c in primary.components}
    shown = [c for c in primary.components if c.id in members and c.kind not in {"input", "output"}]
    status = ir_status(primary.status)
    if status is not None:
        builder.claim(
            "architecture",
            "implemented_solution",
            status,
            TEMPLATES["architecture_overview"].format(
                title=primary.title,
                components=plural(len(shown), "component"),
                connections=plural(len(links), "static relationship"),
            ),
            [span for c in shown[:4] for span in citation_spans(c.citations, 1)],
            analysis=citation_claims(c for comp in shown[:4] for c in comp.citations[:1]),
            components=[c.id for c in shown],
        )
    for component in shown[:5]:
        status = ir_status(component.status)
        if status is None:
            continue
        kind = component.kind.replace("_", " ")
        template = "component_external" if component.group == "external" else "component"
        builder.claim(
            "architecture",
            "implemented_solution",
            status,
            TEMPLATES[template].format(
                label=component.label, kind=kind, group=component.group or "the repository"
            ),
            citation_spans(component.citations, 2),
            analysis=citation_claims(component.citations[:2]),
            components=[component.id],
        )
    steps: list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[Citation, ...]]] = []
    for flow in primary.flows:
        for step in flow.steps:
            steps.append(
                (step.text, step.status, step.component_ids, step.connection_ids, step.citations)
            )
    if not steps:
        for connection in primary.connections:
            if connection.id in links:
                steps.append(
                    (
                        sentence(connection, parts),
                        connection.status,
                        (connection.source, connection.target),
                        (connection.id,),
                        connection.citations,
                    )
                )
    workflow: list[Claim] = []
    for text, raw_status, components, connections, citations in steps:
        status = ir_status(raw_status)
        if (
            status is None
            or len(workflow) >= 6
            or not set(components) <= members
            or not set(connections) <= links
        ):
            continue
        made = builder.claim(
            "workflow",
            "implemented_solution",
            status,
            text,
            citation_spans(citations, 3),
            analysis=citation_claims(citations[:3]),
            components=components,
            connections=connections,
        )
        if made is not None and made not in workflow:
            workflow.append(made)
    return ArchitectureDescription(
        ir_version=report.version,
        report_sha256=report_digest(report),
        explanation=report.explanation,
        unavailable_reason=None,
        architecture_ids=ids,
        primary=primary.id,
        view=view,
        claims=builder.take("architecture", 12),
        workflow=tuple(workflow),
    )


def decisions_of(builder: Builder, report: Report | None) -> tuple[Claim, ...]:
    if report is None or not report.architectures:
        return ()
    found: list[Claim] = []
    for fact in report.architectures[0].decisions:
        status = ir_status(fact.status)
        if status is None or len(found) >= 4:
            continue
        made = builder.claim(
            "decisions",
            "implemented_solution",
            status,
            fact.text,
            citation_spans(fact.citations, 3),
            analysis=citation_claims(fact.citations[:3]),
            components=fact.component_ids,
        )
        if made is not None:
            found.append(made)
    return tuple(found)


# ------------------------------------------------------------------------------ verification


def verify_story(
    story: EngineeringStory,
    payload: dict[str, Any],
    sources: dict[str, bytes],
    report: Report | None,
) -> None:
    """Fail closed unless every claim is exactly grounded in the pinned inputs.

    Text and hash comparison only; nothing is parsed, so this is safe to run outside the
    parser sandbox on a story produced inside it.
    """
    facts = Facts(payload, sources, report)
    snapshot = facts.snapshot
    if (
        story.schema_version != SCHEMA_VERSION
        or story.extractor_version != EXTRACTOR_VERSION
        or story.commit_sha != snapshot["commit_sha"]
        or story.repository != display(snapshot["repository"], 200)
        or story.analysis_sha256 != digest(canonical(payload))
    ):
        raise StoryError("story_analysis_mismatch")
    if story.sources != facts.inventory:
        raise StoryError("story_source_inventory_mismatch")
    description = story.architecture
    citations: set[tuple[str, int]] = set()
    view_members: set[str] = set()
    view_links: set[str] = set()
    every_component: set[str] = set()
    if report is None:
        if description.explanation != "unavailable":
            raise StoryError("story_architecture_mismatch")
    else:
        architecture_sources = {
            path: body
            for path, body in sources.items()
            if facts.manifest[path]["status"] in {"parsed", "context"}
        }
        try:
            check(report, payload, architecture_sources)
        except ArchitectureError:
            raise StoryError("story_architecture_invalid") from None
        primary = report.architectures[0] if report.architectures else None
        if (
            description.report_sha256 != report_digest(report)
            or description.ir_version != report.version
            or description.explanation != report.explanation
            or description.architecture_ids != tuple(a.id for a in report.architectures[:3])
            or description.primary != (primary.id if primary else None)
            or description.view != (primary_view(primary)[2] if primary else None)
        ):
            raise StoryError("story_architecture_mismatch")
        if primary is not None:
            view_members, view_links, _ = primary_view(primary)
            every_component = {c.id for c in primary.components}
            groups = [
                *(c.citations for c in primary.components),
                *(c.citations for c in primary.connections),
                *(s.citations for f in primary.flows for s in f.steps),
                *(d.citations for d in primary.decisions),
            ]
            citations = {(c.path, c.line) for group in groups for c in group}
        for rejected in report.rejected:
            citations.update((m.path, m.line) for m in rejected.mentions)
    from_ir = {c.id for c in description.claims + description.workflow} | {
        c.id
        for c in story.implementation_approach.decisions
        if c.evidence_type == "implemented_solution"
    }
    in_view = {c.id for c in description.claims + description.workflow}
    verdicts = {v["claim_id"]: v["status"] for v in payload["verification"]["verdicts"]}
    known = report_words(report)
    for _, group in story.grouped():
        for claim in group:
            verify_claim(facts, claim, verdicts, known)
            if claim.id in from_ir:
                if any((r.path, r.start_line) not in citations for r in claim.evidence_refs):
                    raise StoryError("story_architecture_mismatch")
                members = view_members if claim.id in in_view else every_component
                links = view_links if claim.id in in_view else set()
                if not set(claim.component_ids) <= members or not set(claim.connection_ids) <= (
                    links
                ):
                    raise StoryError("story_architecture_mismatch")
            elif claim.component_ids or claim.connection_ids:
                raise StoryError("story_architecture_mismatch")
    budget = fact_budget(payload)[1]
    budget_said = [
        c.text for c in story.unresolved_questions.claims if c.text.startswith(BUDGET_OPENING)
    ]
    if budget_said != ([budget] if budget else []):
        raise StoryError("story_budget_mismatch")
    problem = story.problem_statement
    unresolved = [c.text for c in problem.claims if c.evidence_type == "unresolved"]
    expected = [TEMPLATES["problem_insufficient"]] if problem.sufficiency == "insufficient" else []
    if unresolved != expected or (expected and len(problem.claims) != 1):
        raise StoryError("story_problem_fabricated")
    claims = story.claims()
    for mismatch in story.mismatches:
        stated = [claims[i] for i in mismatch.stated_claim_ids]
        evidence = [claims[i] for i in mismatch.evidence_claim_ids]
        if any(c.evidence_type not in {"intended_solution", "unverified_outcome"} for c in stated):
            raise StoryError("story_mismatch_invalid")
        if any(c.evidence_type not in {"implemented_solution", "limitation"} for c in evidence):
            raise StoryError("story_mismatch_invalid")
        allowed = set(VOCABULARY).union(*(words(c.text) for c in stated + evidence))
        if not checked_words(mismatch.detail) <= allowed:
            raise StoryError("story_mismatch_invalid")


def documentary(claim: Claim) -> bool:
    """Claims whose wording is the cited documentation line itself."""
    return (
        claim.evidence_type in DOC_TYPES
        or claim.evidence_type == "intended_solution"
        or (claim.evidence_type == "limitation" and claim.status == "DOCUMENTATION_ONLY")
    )


def verify_claim(facts: Facts, claim: Claim, verdicts: dict[str, str], known: set[str]) -> None:
    if any(not 32 <= ord(c) < 127 for c in claim.text):
        raise StoryError("story_unsafe_text")
    for ref in claim.evidence_refs:
        lines = facts.lines.get(ref.path)
        if (
            lines is None
            or ref.file_sha256 != facts.hashes[ref.path]
            or ref.end_line > len(lines)
            or ref.quote != quote_of(lines, ref.start_line, ref.end_line)
            or ref.permalink != permalink(facts.snapshot, ref.path, ref.start_line, ref.end_line)
        ):
            raise StoryError("story_false_citation")
    roles = {facts.roles[r.path] for r in claim.evidence_refs}
    if documentary(claim):
        if len(claim.evidence_refs) != 1 or not roles <= DOC_ROLES:
            raise StoryError("story_evidence_role")
        ref = claim.evidence_refs[0]
        if ref.start_line != ref.end_line or claim.text != plain(ref.quote):
            raise StoryError("story_unsupported_wording")
        if INSTRUCTION.search(claim.text):
            raise StoryError("story_unsafe_text")
    elif claim.evidence_type != "unresolved" and not roles <= CODE_ROLES:
        raise StoryError("story_evidence_role")
    if claim.evidence_type == "unresolved" and claim.analysis_claim_ids:
        raise StoryError("story_unverified_claim")
    for identity in claim.analysis_claim_ids:
        symbol = facts.symbols.get(facts.subject_of.get(identity, ""))
        if symbol is None or (claim.status == "VERIFIED" and verdicts.get(identity) != "verified"):
            raise StoryError("story_unverified_claim")
        if not any(
            r.path == symbol["path"] and symbol["start_line"] <= r.start_line <= symbol["end_line"]
            for r in claim.evidence_refs
        ):
            raise StoryError("story_unverified_claim")
    if (
        claim.evidence_type in {"implemented_solution", "demonstrated_outcome"}
        and not claim.analysis_claim_ids
    ):
        raise StoryError("story_unverified_claim")
    if not documentary(claim):
        allowed = set(VOCABULARY) | known
        for ref in claim.evidence_refs:
            allowed |= words(ref.quote) | words(ref.path)
        for identity in claim.analysis_claim_ids:
            symbol = facts.symbols.get(facts.subject_of.get(identity, ""))
            if symbol is not None:
                allowed |= words(str(symbol["name"]))
        if not checked_words(claim.text) <= allowed:
            raise StoryError("story_unsupported_wording")


__all__ = [
    "BUDGET_OPENING",
    "TEMPLATES",
    "extract_story",
    "inventory",
    "plain",
    "report_digest",
    "story_sources",
    "verify_story",
]
