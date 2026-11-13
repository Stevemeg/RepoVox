"""Deterministic storyboard from a verified stage-9 analysis payload. No model inference.

Every technical sentence cites claims the verifier marked verified/inferred and evidence it
marked valid. Repository strings are data: they become pixels and speech text, never code.
"""

import re
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from repovox.analysis.common import canonical, digest
from repovox.analysis.contracts import PAYLOADS

VERSION: Literal["grounded-storyboard-1.0"] = "grounded-storyboard-1.0"
CITABLE = {"verified", "inferred"}
EXCERPT_LINES = 12
EXCERPT_WIDTH = 86
Uncertainty = Literal["verified", "inferred", "none"]
SceneType = Literal["title", "stack", "architecture", "flow", "code", "summary"]


class GroundingError(Exception):
    """Fixed code only; never repository text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Row(Closed):
    label: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=70)


class Link(Closed):
    source: str = Field(min_length=1, max_length=28)
    target: str = Field(min_length=1, max_length=28)
    label: str = Field(min_length=1, max_length=44)


class Excerpt(Closed):
    evidence_id: str
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    lines: tuple[str, ...] = Field(min_length=1, max_length=EXCERPT_LINES)
    truncated: bool


class Sentence(Closed):
    id: str
    text: str = Field(min_length=1, max_length=400)
    spoken: str = Field(min_length=1, max_length=600)
    technical: bool
    uncertainty: Uncertainty
    claim_ids: tuple[str, ...] = Field(max_length=256)
    evidence_ids: tuple[str, ...] = Field(max_length=256)


class Scene(Closed):
    id: str
    type: SceneType
    title: str = Field(min_length=1, max_length=44)
    claim_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    rows: tuple[Row, ...] = Field(default=(), max_length=8)
    links: tuple[Link, ...] = Field(default=(), max_length=4)
    excerpt: Excerpt | None = None
    sentences: tuple[Sentence, ...] = Field(min_length=1, max_length=6)


class Storyboard(Closed):
    version: Literal["grounded-storyboard-1.0"]
    repository: str
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    pipeline_version: str
    analysis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scenes: tuple[Scene, ...] = Field(min_length=4, max_length=24)


def display(value: object, limit: int) -> str:
    """Printable ASCII only; visible ellipsis instead of silent clipping."""
    text = "".join(c if 32 <= ord(c) < 127 else "?" for c in str(value).replace("\t", "    "))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def short(path: str) -> str:
    parts = path.split("/")
    return path if len(parts) <= 2 else ".../" + "/".join(parts[-2:])


def speakable(text: str) -> str:
    # Speak only the last two segments of a long path; the caption keeps the full path.
    text = re.sub(r"(?:[A-Za-z0-9_.-]+/){2,}([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", r"\1", text)
    text = re.sub(r"\.(py|js|jsx|mjs|cjs|ts|tsx)\b", r" dot \1", text)
    text = text.replace("->", " to ").replace("/", " slash ").replace("_", " ")
    text = re.sub(r"[^A-Za-z0-9 .,;:'-]", " ", text)
    return re.sub(r"\s+", " ", text).strip() or "unnamed"


def plural(count: int, noun: str, many: str | None = None) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {many or noun + 's'}"


class Index:
    def __init__(self, payload: dict[str, Any]) -> None:
        knowledge = payload["knowledge"]
        self.symbols: dict[str, dict[str, Any]] = {s["id"]: s for s in knowledge["symbols"]}
        self.edges: dict[str, dict[str, Any]] = {e["id"]: e for e in knowledge["edges"]}
        self.evidence: dict[str, dict[str, Any]] = {
            e["id"]: e for e in payload["evidence"]["items"]
        }
        self.by_symbol: dict[str, dict[str, Any]] = {
            e["symbol_id"]: e for e in payload["evidence"]["items"]
        }
        self.verdicts: dict[str, dict[str, Any]] = {
            v["claim_id"]: v for v in payload["verification"]["verdicts"]
        }
        self.claim_of: dict[str, dict[str, Any]] = {c["subject_id"]: c for c in knowledge["claims"]}

    def cite(self, subject_id: str) -> tuple[str, tuple[str, ...], str] | None:
        claim = self.claim_of.get(subject_id)
        verdict = self.verdicts.get(claim["id"]) if claim else None
        if claim is None or verdict is None or verdict["status"] not in CITABLE:
            return None
        ids = tuple(verdict["evidence_ids"])
        if not ids or any(
            self.evidence.get(i, {}).get("validation_status") != "valid" for i in ids
        ):
            return None
        return claim["id"], ids, verdict["status"]


class Draft:
    """Accumulates one scene; a technical sentence without citations is a programming error."""

    def __init__(self, index: Index, scene_id: str, kind: SceneType, title: str) -> None:
        self.index, self.id, self.type, self.title = index, scene_id, kind, title
        self.rows: list[Row] = []
        self.links: list[Link] = []
        self.excerpt: Excerpt | None = None
        self.sentences: list[Sentence] = []
        self.claims: list[str] = []
        self.evidence: list[str] = []

    def row(self, label: str, value: object) -> None:
        if len(self.rows) < 8:
            self.rows.append(Row(label=display(label, 40), value=display(value, 70)))

    def say(self, text: str, subjects: list[str] | None = None) -> bool:
        claims: list[str] = []
        evidence: list[str] = []
        statuses: set[str] = set()
        for subject in subjects or []:
            cited = self.index.cite(subject)
            if cited is None:
                return False  # Never narrate a technical statement with an uncitable subject.
            claims.append(cited[0])
            evidence.extend(cited[1])
            statuses.add(cited[2])
        if subjects is not None and not claims:
            return False
        uncertainty: Uncertainty = (
            "none" if subjects is None else "inferred" if "inferred" in statuses else "verified"
        )
        text = display(text, 400)
        self.sentences.append(
            Sentence(
                id=f"{self.id}-s{len(self.sentences) + 1}",
                text=text,
                spoken=speakable(text),
                technical=subjects is not None,
                uncertainty=uncertainty,
                claim_ids=tuple(dict.fromkeys(claims)),
                evidence_ids=tuple(dict.fromkeys(evidence)),
            )
        )
        self.claims.extend(claims)
        self.evidence.extend(evidence)
        return True

    def scene(self, recap: tuple[list[str], list[str]] | None = None) -> Scene | None:
        claims, evidence = (recap[0], recap[1]) if recap else (self.claims, self.evidence)
        if not claims or not evidence or not self.sentences:
            return None
        return Scene(
            id=self.id,
            type=self.type,
            title=display(self.title, 44),
            claim_ids=tuple(dict.fromkeys(claims))[:256],
            evidence_ids=tuple(dict.fromkeys(evidence))[:256],
            rows=tuple(self.rows),
            links=tuple(self.links),
            excerpt=self.excerpt,
            sentences=tuple(self.sentences),
        )


def common_prefix(paths: list[str]) -> str:
    """Longest directory shared by every module, so areas are meaningful for a subtree."""
    if not paths:
        return ""
    shared = paths[0].split("/")[:-1]
    for path in paths[1:]:
        parts = path.split("/")[:-1]
        size = 0
        while size < min(len(shared), len(parts)) and shared[size] == parts[size]:
            size += 1
        shared = shared[:size]
    return "/".join(shared) + "/" if shared else ""


def area(path: str, prefix: str = "") -> str:
    rest = path[len(prefix) :]
    return rest.split("/", 1)[0] if "/" in rest else "(top level)"


def title_scene(index: Index, knowledge: dict[str, Any], counts: dict[str, int]) -> Draft:
    snapshot, coverage = knowledge["repository"], knowledge["coverage"]
    modules = sorted(
        (s for s in index.symbols.values() if s["kind"] == "module"), key=lambda s: s["path"]
    )
    parsed = sum(f["status"] == "parsed" for f in coverage["files"])
    draft = Draft(index, "overview", "title", snapshot["repository"])
    draft.row("Repository", snapshot["repository"])
    draft.row("Pinned commit", snapshot["commit_sha"][:12])
    draft.row("Source files parsed", f"{parsed} of {len(coverage['files'])} files in snapshot")
    draft.row("Languages", ", ".join(knowledge["stack"]) or "none")
    draft.row("Verified static claims", counts["verified"])
    draft.row("Inferred static claims", counts["inferred"])
    draft.say(f"This is a static walkthrough of {snapshot['repository']} at one pinned commit.")
    largest = sorted(modules, key=lambda s: (-(s["end_line"] - s["start_line"]), s["path"]))[:2]
    if largest:
        names = " and ".join(s["path"] for s in largest)
        draft.say(
            f"{plural(parsed, 'source file')} parsed without errors. The longest "
            f"{'are' if len(largest) > 1 else 'is'} {names}.",
            [s["id"] for s in largest],
        )
    draft.say(
        "The purpose of the project is not inferred. Everything shown is static structure "
        "backed by cited source lines."
    )
    return draft


def stack_scene(index: Index, knowledge: dict[str, Any]) -> Draft:
    draft = Draft(index, "stack", "stack", "Languages and frameworks")
    modules = sorted(
        (s for s in index.symbols.values() if s["kind"] == "module"), key=lambda s: s["path"]
    )
    for language, stats in sorted(knowledge["coverage"]["language_coverage"].items()):
        draft.row(
            language, f"{plural(stats['files'], 'file')}, {stats['parsed_bytes']} bytes parsed"
        )
        sample = next((s for s in modules if s["parser_language"] == language), None)
        if sample:
            draft.say(
                f"{plural(stats['files'], 'file')} of {language} source "
                f"{'was' if stats['files'] == 1 else 'were'} parsed, for example {sample['path']}.",
                [sample["id"]],
            )
    seen: set[str] = set()
    for framework in knowledge["frameworks"]:
        symbol = index.symbols.get(framework["symbol_id"])
        if symbol is None or framework["name"] in seen:
            continue
        if draft.say(
            f"An import of {framework['name']} is observed in {symbol['path']}. "
            "Whether it is used at runtime is not asserted.",
            [symbol["id"]],
        ):
            seen.add(framework["name"])
            draft.row(f"Import: {framework['name']}", f"{symbol['path']}:{symbol['start_line']}")
    declared = sorted(
        (s for s in index.symbols.values() if s["kind"] == "declared_dependency"),
        key=lambda s: (s["path"], s["start_line"], s["name"]),
    )[:3]
    for dependency in declared:
        if draft.say(
            f"{dependency['path']} declares a dependency on {dependency['name']}. "
            "No installed version is asserted.",
            [dependency["id"]],
        ):
            draft.row(f"Declared: {dependency['name']}", dependency["path"])
    if not seen:
        draft.say("No import of a recognised web framework was observed.")
    return draft


def architecture_scene(index: Index) -> Draft:
    draft = Draft(index, "architecture", "architecture", "Where the code lives")
    modules = sorted(
        (s for s in index.symbols.values() if s["kind"] == "module"), key=lambda s: s["path"]
    )
    prefix = common_prefix([m["path"] for m in modules])
    if prefix:
        draft.row("Common directory", prefix)
    kinds: dict[str, Counter[str]] = {}
    for symbol in index.symbols.values():
        if symbol["path"].startswith(prefix):
            kinds.setdefault(area(symbol["path"], prefix), Counter())[symbol["kind"]] += 1
    areas = sorted(
        {area(m["path"], prefix) for m in modules}, key=lambda a: (-kinds[a]["module"], a)
    )
    for name in areas[:7]:
        count = kinds[name]
        draft.row(
            name,
            f"{plural(count['module'], 'module')}, {plural(count['class'], 'class', 'classes')}, "
            f"{plural(count['function'] + count['method'], 'function')}",
        )
    for position, name in enumerate(areas[:3]):
        members = [m for m in modules if area(m["path"], prefix) == name]
        biggest = max(members, key=lambda s: (s["end_line"] - s["start_line"], s["path"]))
        lead = "The largest area is" if position == 0 else "Next is"
        draft.say(
            f"{lead} {name}, with {plural(len(members), 'parsed module')}, "
            f"including {biggest['path']}.",
            [biggest["id"]],
        )
    return draft


RULE_TEXT = {
    "python-main-v1": "contains a Python main guard",
    "framework-construction-v1": "constructs a framework application object",
    "framework-route-v1": "registers a framework route",
}
RELATION_TEXT = {
    "inherits": "inherits from",
    "calls_lexically": "calls",
    "imports": "imports",
}


def flow_scene(index: Index, knowledge: dict[str, Any]) -> Draft:
    draft = Draft(index, "flow", "flow", "Entry points and static links")
    paths: set[str] = set()
    for candidate in knowledge["entrypoints"]["candidates"]:
        if candidate["path"] in paths or len(paths) >= 3:
            continue
        reason = RULE_TEXT.get(candidate["rule"], "matches a declared entry rule")
        if draft.say(
            f"{candidate['path']} {reason}, which makes it an entry point candidate.",
            list(candidate["support_ids"]),
        ):
            paths.add(candidate["path"])
            draft.row(candidate["path"], f"{candidate['rule']}, rank {candidate['rank']}")
    if paths:
        draft.say("Whether any candidate actually runs is not asserted.")
    resolved = sorted(
        (
            e
            for e in index.edges.values()
            if e["classification"] == "resolved_static"
            and e["relationship"] in RELATION_TEXT
            and e["source"] in index.symbols
            and e["target"] in index.symbols
        ),
        key=lambda e: (
            list(RELATION_TEXT).index(e["relationship"]),
            index.symbols[e["source"]]["path"],
            index.symbols[e["source"]]["start_line"],
            e["id"],
        ),
    )
    used: set[str] = set()
    for edge in resolved:
        source, target = index.symbols[edge["source"]], index.symbols[edge["target"]]
        if len(draft.links) >= 3 or edge["relationship"] in used:
            continue
        verb = RELATION_TEXT[edge["relationship"]]
        if draft.say(
            f"In {source['path']}, {source['name']} {verb} {target['name']}. "
            "This is a resolved static link, not proof of execution.",
            [edge["id"]],
        ):
            used.add(edge["relationship"])
            draft.links.append(
                Link(
                    source=display(source["name"], 28),
                    target=display(target["name"], 28),
                    label=display(f"{verb} / {short(source['path'])}:{source['start_line']}", 44),
                )
            )
    return draft


def code_scenes(index: Index, knowledge: dict[str, Any]) -> list[Draft]:
    entry_paths = [c["path"] for c in knowledge["entrypoints"]["candidates"]]
    declarations = sorted(
        (
            s
            for s in index.symbols.values()
            if s["kind"] in {"function", "class", "method"}
            and s["name"] != "anonymous"
            and s["end_line"] - s["start_line"] >= 2
        ),
        key=lambda s: (
            s["path"] not in entry_paths,
            -(s["end_line"] - s["start_line"]),
            s["path"],
            s["start_line"],
        ),
    )
    drafts: list[Draft] = []
    files: set[str] = set()
    for symbol in declarations:
        if len(drafts) >= 3:
            break
        item = index.by_symbol.get(symbol["id"])
        if symbol["path"] in files or item is None or item["redacted"]:
            continue
        draft = Draft(
            index, f"code-{len(drafts) + 1}", "code", f"{symbol['kind']} {symbol['name']}"
        )
        said = draft.say(
            f"{symbol['path']} declares the {symbol['kind']} {symbol['name']} on lines "
            f"{symbol['start_line']} to {symbol['end_line']}.",
            [symbol["id"]],
        )
        if not said:
            continue
        parameters = [str(p) for p in symbol.get("parameters", [])][:4]
        if parameters:
            draft.say(f"Its declared parameters include {', '.join(parameters)}.", [symbol["id"]])
        source = item["excerpt"].split("\n")
        draft.excerpt = Excerpt(
            evidence_id=item["id"],
            path=display(symbol["path"], 70),
            start_line=symbol["start_line"],
            end_line=symbol["end_line"],
            file_sha256=symbol["file_sha256"],
            lines=tuple(display(line, EXCERPT_WIDTH) or " " for line in source[:EXCERPT_LINES]),
            truncated=symbol["end_line"] - symbol["start_line"] + 1 > EXCERPT_LINES,
        )
        files.add(symbol["path"])
        drafts.append(draft)
    return drafts


def summary_scene(index: Index, knowledge: dict[str, Any], verification: dict[str, Any]) -> Draft:
    counts = verification["counts"]
    draft = Draft(index, "summary", "summary", "What was and was not established")
    draft.row("Verified against source bytes", counts["verified"])
    draft.row("Inferred, binding unresolved", counts["inferred"])
    draft.row("Documentation only", counts["documentation_only"])
    draft.row("Unsupported", counts["unsupported"])
    draft.row("Documentation conflicts", len(verification["conflicts"]))
    draft.say(
        f"The verifier re-read the original source and confirmed "
        f"{plural(counts['verified'], 'static claim')}. "
        f"{plural(counts['inferred'], 'more claim')} remain inferred."
    )
    wanted = ("runtime", "purpose")
    for limitation in knowledge["limitations"]:
        if any(w in limitation.lower() for w in wanted) and len(draft.sentences) < 3:
            draft.say(limitation)
    return draft


def build(payload: dict[str, Any]) -> Storyboard:
    try:
        TypeAdapter(PAYLOADS["verify"]).validate_python(payload)
    except ValueError:
        raise GroundingError("invalid_analysis_payload") from None
    knowledge, verification = payload["knowledge"], payload["verification"]
    index = Index(payload)
    drafts = [
        title_scene(index, knowledge, verification["counts"]),
        stack_scene(index, knowledge),
        architecture_scene(index),
        flow_scene(index, knowledge),
        *code_scenes(index, knowledge),
    ]
    scenes = [scene for scene in (d.scene() for d in drafts) if scene is not None]
    recap = (
        [c for s in scenes for c in s.claim_ids],
        [e for s in scenes for e in s.evidence_ids],
    )
    final = summary_scene(index, knowledge, verification).scene(recap)
    if final is None or len(scenes) < 3:
        raise GroundingError("insufficient_evidence")
    board = Storyboard(
        version=VERSION,
        repository=display(knowledge["repository"]["repository"], 120),
        commit_sha=knowledge["repository"]["commit_sha"],
        pipeline_version=knowledge["versions"]["pipeline"],
        analysis_sha256=digest(canonical(payload)),
        scenes=(*scenes, final),
    )
    check_grounding(board, payload)
    return board


def check_grounding(board: Storyboard, payload: dict[str, Any]) -> None:
    """Independent of the builder: reject any storyboard whose citations are not verifier-backed."""
    index = Index(payload)
    if board.analysis_sha256 != digest(canonical(payload)):
        raise GroundingError("analysis_mismatch")
    if len({s.id for s in board.scenes}) != len(board.scenes):
        raise GroundingError("duplicate_scene")
    for scene in board.scenes:
        supported: set[str] = set()
        for claim in scene.claim_ids:
            verdict = index.verdicts.get(claim)
            if verdict is None or verdict["status"] not in CITABLE:
                raise GroundingError("unverified_claim")
            supported.update(verdict["evidence_ids"])
        for evidence in scene.evidence_ids:
            item = index.evidence.get(evidence)
            if item is None or item["validation_status"] != "valid" or evidence not in supported:
                raise GroundingError("invalid_evidence")
        for sentence in scene.sentences:
            statuses: set[str] = set()
            backing: set[str] = set()
            for claim in sentence.claim_ids:
                verdict = index.verdicts.get(claim)
                if (
                    verdict is None
                    or verdict["status"] not in CITABLE
                    or claim not in scene.claim_ids
                ):
                    raise GroundingError("unverified_claim")
                statuses.add(verdict["status"])
                backing.update(verdict["evidence_ids"])
            if set(sentence.evidence_ids) != backing or not backing <= set(scene.evidence_ids):
                raise GroundingError("invalid_evidence")
            expected = (
                "none"
                if not sentence.technical
                else "inferred"
                if "inferred" in statuses
                else "verified"
            )
            if sentence.technical != bool(sentence.claim_ids) or sentence.uncertainty != expected:
                raise GroundingError("uncited_technical_sentence")
            if sentence.spoken != speakable(sentence.text):
                raise GroundingError("speech_text_mismatch")
        if scene.excerpt is not None:
            item = index.evidence.get(scene.excerpt.evidence_id)
            if (
                item is None
                or item["validation_status"] != "valid"
                or item["redacted"]
                or scene.excerpt.evidence_id not in scene.evidence_ids
                or item["file_sha256"] != scene.excerpt.file_sha256
                or (item["start_line"], item["end_line"])
                != (scene.excerpt.start_line, scene.excerpt.end_line)
                or tuple(
                    display(line, EXCERPT_WIDTH) or " "
                    for line in item["excerpt"].split("\n")[:EXCERPT_LINES]
                )
                != scene.excerpt.lines
            ):
                raise GroundingError("excerpt_mismatch")


def validate(board: Storyboard, payload: dict[str, Any]) -> None:
    """Grounding plus exact reproducibility: nothing but the deterministic output is accepted."""
    check_grounding(board, payload)
    if build(payload) != board:
        raise GroundingError("storyboard_not_reproducible")
