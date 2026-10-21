"""Typed, closed fictional input vocabulary; no production schema conversion."""

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = {"ripple.py": "python", "spark.js": "javascript", "comet.ts": "typescript"}
SceneKind = Literal["architecture", "code", "relationships", "summary"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(value: object, reason: str) -> None:
    if not value:
        raise ValueError(reason)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Citation(Closed):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    start_byte: int = Field(ge=0)
    end_byte: int = Field(gt=0)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=160)

    @field_validator("path")
    @classmethod
    def path_is_fixture(cls, value: str) -> str:
        require(value in SOURCES, "source_not_fictional_allowlist")
        return value

    @field_validator("quote")
    @classmethod
    def safe_quote(cls, value: str) -> str:
        require(all(32 <= ord(c) < 127 for c in value), "unsafe_text")
        require(not any(c in value for c in "`$<>\\"), "unsafe_text")
        return value


class Fact(Closed):
    id: str = Field(pattern=r"^f_[a-z_]{1,30}$")
    language: Literal["python", "javascript", "typescript"]
    kind: Literal["declaration", "static_call"]
    subject: str = Field(pattern=r"^[a-z][a-z_]{0,18}$")
    target: str | None = Field(default=None, pattern=r"^[a-z][a-z_]{0,18}$")
    status: Literal["observed_syntax"]
    citation: Citation


class Source(Closed):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(gt=0, le=1024)

    @field_validator("path")
    @classmethod
    def allowed(cls, value: str) -> str:
        require(value in SOURCES, "source_not_fictional_allowlist")
        return value


class Grounding(Closed):
    version: Literal["fictional-media-grounding-1.0"]
    synthetic: Literal[True]
    sources: tuple[Source, ...] = Field(min_length=3, max_length=3)
    facts: tuple[Fact, ...] = Field(min_length=9, max_length=9)


class Scene(Closed):
    kind: SceneKind
    title: str = Field(max_length=40)
    start_frame: int = Field(ge=0)
    frames: Literal[90]
    source: str | None = None
    fact_ids: tuple[str, ...]


class Storyboard(Closed):
    version: Literal["fictional-storyboard-1.0"]
    synthetic: Literal[True]
    grounding_sha256: str
    width: Literal[1280]
    height: Literal[720]
    fps: Literal[30]
    audio: Literal["synthetic-tone-no-narration"]
    scenes: tuple[Scene, ...] = Field(min_length=6, max_length=6)


def original_sources() -> dict[str, bytes]:
    require(not FIXTURES.is_symlink(), "source_link")
    result = {}
    for name in SOURCES:
        p = FIXTURES / name
        require(not p.is_symlink() and p.is_file() and p.stat().st_nlink == 1, "source_link")
        body = p.read_bytes()
        require(0 < len(body) <= 1024 and b"\r" not in body, "original_source_bytes")
        require(all(c == 10 or 32 <= c < 127 for c in body), "source_encoding")
        result[name] = body
    return result


def validate_grounding(g: Grounding, sources: dict[str, bytes]) -> None:
    require(set(sources) == set(SOURCES), "source_scope")
    require(len({s.path for s in g.sources}) == 3, "duplicate_source")
    for s in g.sources:
        body = sources[s.path]
        require(s.sha256 == sha(body) and s.bytes == len(body), "source_commitment")
    require(len({f.id for f in g.facts}) == len(g.facts), "duplicate_fact")
    declarations = {}
    for f in g.facts:
        c, body = f.citation, sources[f.citation.path]
        require(f.language == SOURCES[c.path], "source_language")
        require(c.sha256 == sha(body), "citation_hash")
        require(0 <= c.start_byte < c.end_byte <= len(body), "citation_range")
        quote = body[c.start_byte : c.end_byte].decode("ascii")
        require(quote == c.quote, "citation_original_bytes")
        require(c.start_line == body[: c.start_byte].count(b"\n") + 1, "citation_start_line")
        require(c.end_line == body[: c.end_byte - 1].count(b"\n") + 1, "citation_end_line")
        if f.kind == "declaration":
            require(f.target is None, "declaration_target")
            prefix = "def " if f.language == "python" else "function "
            require(
                re.search(r"\b" + prefix + re.escape(f.subject) + r"\(", quote),
                "declaration_binding",
            )
            key = c.path, f.subject
            require(key not in declarations, "duplicate_declaration")
            declarations[key] = f
    for f in g.facts:
        if f.kind == "static_call":
            c = f.citation
            require(f.target is not None, "missing_call_target")
            assert f.target is not None
            caller = declarations.get((c.path, f.subject))
            target = declarations.get((c.path, f.target))
            require(caller is not None and target is not None, "unbound_static_relationship")
            assert caller is not None
            # Only the deliberately small fixture grammar is supported. This is
            # not a production Python/JS/TS parser or runtime verifier.
            source_text = sources[c.path].decode("ascii")
            if f.language == "python":
                pattern = r"(?m)^def " + re.escape(f.subject) + r"\([a-z]+\):\n(?:    [^\n]+\n)+"
            else:
                pattern = (
                    r"(?:export )?function "
                    + re.escape(f.subject)
                    + r"\([^{}\n]*\)(?:: [A-Za-z]+)? \{[^{}]*\}"
                )
            body_match = re.search(pattern, source_text)
            require(body_match is not None, "unsupported_fixture_grammar")
            assert body_match is not None
            require(
                body_match.start() < c.start_byte < c.end_byte <= body_match.end(), "caller_scope"
            )
            next_decl = min(
                (
                    d.citation.start_byte
                    for (p, _), d in declarations.items()
                    if p == c.path and d.citation.start_byte > caller.citation.start_byte
                ),
                default=len(sources[c.path]),
            )
            require(caller.citation.end_byte < c.start_byte < next_decl, "caller_scope")
            require(
                re.fullmatch(r"return " + re.escape(f.target) + r"\([a-z]+\);?", c.quote),
                "call_binding",
            )
    for name in SOURCES:
        require(
            sum(f.citation.path == name and f.kind == "declaration" for f in g.facts) == 2,
            "fixture_declarations",
        )
        require(
            sum(f.citation.path == name and f.kind == "static_call" for f in g.facts) == 1,
            "fixture_relationships",
        )


def storyboard(g: Grounding, sources: dict[str, bytes]) -> Storyboard:
    validate_grounding(g, sources)
    ids = tuple(f.id for f in g.facts)
    rows: list[tuple[SceneKind, str, str | None, tuple[str, ...]]] = [
        ("architecture", "Three fictional source units", None, ids)
    ]
    for name in SOURCES:
        rows.append(
            (
                "code",
                SOURCES[name].title() + " observed syntax",
                name,
                tuple(f.id for f in g.facts if f.citation.path == name),
            )
        )
    rows.extend(
        [
            (
                "relationships",
                "Static call dependencies",
                None,
                tuple(f.id for f in g.facts if f.kind == "static_call"),
            ),
            ("summary", "What this demonstration proves", None, ids),
        ]
    )
    return Storyboard(
        version="fictional-storyboard-1.0",
        synthetic=True,
        grounding_sha256=sha(g.model_dump_json().encode()),
        width=1280,
        height=720,
        fps=30,
        audio="synthetic-tone-no-narration",
        scenes=tuple(
            Scene(
                kind=kind, title=title, source=source, fact_ids=bound, start_frame=i * 90, frames=90
            )
            for i, (kind, title, source, bound) in enumerate(rows)
        ),
    )
