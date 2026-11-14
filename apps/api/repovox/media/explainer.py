"""Architecture IR -> source-grounded narration synchronised with an animated diagram.

Narration is generated from the validated IR only. Each technical line names the diagram
elements it lights up and carries their citations; nothing is said that the IR does not hold.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from repovox.analysis.common import digest
from repovox.media.archgraph import sentence
from repovox.media.architecture import (
    Architecture,
    ArchitectureError,
    Citation,
    Component,
    Report,
    validate,
)
from repovox.media.diagram import Diagram
from repovox.media.narration import FPS, Engine, assemble, detect, synthesize
from repovox.media.stages import Checkpoint, RenderError, encode_sequence, encoded, noop, timestamp
from repovox.media.storyboard import display, speakable

VERSION = "architecture-explainer-1.0"
ANIMATION_STEP = 6  # Video frames per animation frame: five diagram updates per second.
PULSE_SECONDS = 1.6
LineStatus = Literal["VERIFIED", "INFERRED", "UNRESOLVED", "CONTEXT"]
DESCRIPTIONS = {
    "noise": "random noise tensor",
    "condition": "conditioning labels",
    "real": "real data batch",
    "generated": "generated sample",
    "input": "input batch",
    "prediction": "prediction",
}


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    section: str
    text: str = Field(min_length=1, max_length=290)
    spoken: str = Field(min_length=1, max_length=600)
    status: LineStatus
    component_ids: tuple[str, ...]
    connection_ids: tuple[str, ...]
    citations: tuple[Citation, ...]
    view: str = "overview"  # Which diagram this line is narrated over.


class Script:
    def __init__(self, architecture: Architecture) -> None:
        self.architecture = architecture
        self.lines: list[Line] = []
        self.links = {c.id for c in architecture.connections}

    def say(
        self,
        section: str,
        text: str,
        status: LineStatus = "CONTEXT",
        components: tuple[str, ...] = (),
        connections: tuple[str, ...] = (),
        citations: tuple[Citation, ...] = (),
        view: str = "overview",
    ) -> None:
        text = display(text, 290)
        self.lines.append(
            Line(
                id=f"{self.architecture.id}-n{len(self.lines) + 1}",
                section=section,
                text=text,
                spoken=speakable(text)[:600],
                status=status,
                component_ids=components,
                connection_ids=tuple(c for c in connections if c in self.links),
                citations=tuple(dict.fromkeys(citations))[:6],
                view=view,
            )
        )


def listing(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def narrate(architecture: Architecture) -> tuple[Line, ...]:
    """Educational order: purpose, components, inputs and outputs, flow, decisions, unknowns."""
    if architecture.views:
        return narrate_graph(architecture)
    script = Script(architecture)
    parts = {c.id: c for c in architecture.components}
    links = {c.id: c for c in architecture.connections}

    def link_citations(*ids: str) -> tuple[Citation, ...]:
        return tuple(c for i in ids if i in links for c in links[i].citations)

    if architecture.type == "gan":
        g, d = parts["generator"], parts["discriminator"]
        core = ("generator-to-generated", "generated-to-discriminator", "real-to-discriminator")
        script.say(
            "purpose",
            f"This code implements a generative adversarial network. {g.label} turns random noise "
            f"into samples, and {d.label} scores both those samples and real data.",
            architecture.status,
            ("generator", "discriminator"),
            core,
            link_citations(*core),
        )
    elif architecture.type == "supervised_network":
        model = parts["model"]
        script.say(
            "purpose",
            f"This code trains one network, {model.label}, by comparing its predictions with "
            "targets from a data loader.",
            architecture.status,
            ("model",),
            ("input-to-model", "prediction-to-loss"),
            link_citations("input-to-model", "prediction-to-loss"),
        )
    else:
        app = parts["application"]
        script.say(
            "purpose",
            f"This code constructs a web application object, {app.label}, and registers route "
            "handlers on it.",
            architecture.status,
            ("application",),
            (),
            app.citations,
        )
    for variant in architecture.variants:
        script.say(
            "purpose",
            f"Variant: {variant.name}. {variant.reason}",
            variant.status,
            (),
            (),
            variant.citations,
        )

    for component in architecture.components:
        if component.kind == "module":
            where = component.citations[0].path
            if component.layers:
                kinds = listing(list(dict.fromkeys(layer.type for layer in component.layers)))
                script.say(
                    "components",
                    f"{component.label} is declared in {where} with {len(component.layers)} "
                    f"layers, using {kinds}.",
                    "VERIFIED",
                    (component.id,),
                    (),
                    (component.citations[0], *(layer.citation for layer in component.layers[:5])),
                )
                first, last = component.layers[0], component.layers[-1]
                if first.resolved and last.resolved and len(component.layers) > 1:
                    script.say(
                        "components",
                        f"Its first layer is {first.text} and its last layer is {last.text}.",
                        "VERIFIED",
                        (component.id,),
                        (),
                        (first.citation, last.citation),
                    )
            else:
                script.say(
                    "components",
                    f"{component.label} is declared in {where}. Its layers are built dynamically "
                    "and are not listed.",
                    "VERIFIED",
                    (component.id,),
                    (),
                    component.citations,
                )
        elif component.kind in {"service", "handler"} and component.role != "application":
            script.say(
                "components",
                f"{component.label} is a candidate route handler.",
                component.status,
                (component.id,),
                tuple(c.id for c in architecture.connections if c.target == component.id),
                component.citations,
            )

    for role in architecture.inputs:
        component = parts[role]
        detail = f", with {component.lines[0]}" if component.lines else ""
        outgoing = tuple(c.id for c in architecture.connections if c.source == role)
        script.say(
            "inputs and outputs",
            f"Input: the {DESCRIPTIONS.get(role, role)}, named {component.label} in the "
            f"code{detail}.",
            component.status,
            (role,),
            outgoing,
            (*component.citations, *link_citations(*outgoing)),
        )
    for role in architecture.outputs:
        component = parts[role]
        incoming = tuple(c.id for c in architecture.connections if c.target == role)
        script.say(
            "inputs and outputs",
            f"Output: the {DESCRIPTIONS.get(role, role)}, named {component.label} in the code.",
            component.status,
            (role,),
            incoming,
            (*component.citations, *link_citations(*incoming)),
        )

    for flow in architecture.flows:
        script.say("flow", f"Now the {flow.name} path, in source order.")
        for step in flow.steps:
            script.say(
                "flow",
                step.text,
                step.status,
                step.component_ids,
                step.connection_ids,
                step.citations,
            )

    for fact in architecture.decisions:
        script.say("decisions", fact.text, fact.status, fact.component_ids, (), fact.citations)

    if architecture.unresolved:
        script.say("unknowns", "Static analysis did not establish the following.")
        for item in architecture.unresolved[:5]:
            script.say("unknowns", f"{item.topic.capitalize()}: {item.reason}", "UNRESOLVED")
    return tuple(script.lines)


KIND_WORDS = {
    "function": "function",
    "class": "class",
    "part": "constructed part",
    "endpoint": "declared route",
    "source_file": "source file",
    "input": "parameter",
    "output": "returned value",
}


def describe(component: Component) -> str:
    """One sentence about a component, using only what the IR records about it."""
    detail = component.lines[0] if component.lines else ""
    weak = "" if component.status == "VERIFIED" else " Its binding is inferred, not confirmed."
    if component.kind in {"function", "class"}:
        extra = f", which {detail}" if detail.startswith("takes") else ""
        extra = f", with {detail}" if detail.startswith("methods") else extra
        return (
            f"{component.label} is a {component.kind} declared in {component.group}{extra}.{weak}"
        )
    if component.kind == "part":
        return f"{component.label} is a part the class constructs as {detail}.{weak}"
    if component.kind == "endpoint":
        return f"{component.label} is a route declared in {component.group}."
    if component.kind == "source_file":
        return f"{component.label} is a {detail} file under {component.group}."
    if component.group == "external":
        kind = component.kind.replace("_", " ")
        return (
            f"{component.label} is a client library for a {kind}. It stands for something "
            f"outside this repository.{weak}"
        )
    return f"{component.label} is a {KIND_WORDS.get(component.kind, component.kind)}.{weak}"


def narrate_graph(architecture: Architecture) -> tuple[Line, ...]:
    """Narration for any component graph: no wording depends on a named architecture."""
    script = Script(architecture)
    parts = {c.id: c for c in architecture.components}
    links = {c.id: c for c in architecture.connections}
    overview = architecture.views[0]
    top = [parts[i] for i in overview.component_ids]
    shown = [c for c in top if c.kind not in {"input", "output"}]
    files = sorted({c.group for c in shown if c.group and c.group != "external"})
    script.say(
        "purpose",
        f"{architecture.title}. This view connects {len(shown)} components through "
        f"{len(overview.connection_ids)} static source relationships across {len(files)} "
        f"{'area' if len(files) == 1 else 'areas'} of the repository. What the code is for is "
        "not inferred.",
        architecture.status,
        tuple(c.id for c in top),
        (),
        tuple(c.citations[0] for c in shown[:6]),
    )
    for component in shown[:9]:
        script.say(
            "components",
            describe(component),
            component.status,
            (component.id,),
            (),
            component.citations,
        )
    if len(files) > 1:
        for group in files[:4]:
            members = [c for c in shown if c.group == group]
            script.say(
                "boundaries",
                f"Boundary {group} holds {listing([c.label for c in members])}.",
                "VERIFIED" if all(c.status == "VERIFIED" for c in members) else "INFERRED",
                tuple(c.id for c in members),
                (),
                tuple(c.citations[0] for c in members[:6]),
            )
    for role, word in ((architecture.inputs, "Input"), (architecture.outputs, "Output")):
        for identity in role:
            component = parts[identity]
            near = tuple(
                c.id
                for c in architecture.connections
                if identity in (c.source, c.target) and c.id in overview.connection_ids
            )
            script.say(
                "inputs and outputs",
                f"{word}: {component.label}, the {KIND_WORDS.get(component.kind, component.kind)} "
                f"of the scope shown.",
                component.status,
                (identity,),
                near,
                component.citations,
            )
    script.say("flow", "Now the relationships of this view, in source order.")
    for flow in architecture.flows:
        for step in flow.steps:
            script.say(
                "flow",
                step.text,
                step.status,
                step.component_ids,
                step.connection_ids,
                step.citations,
            )
    for view in architecture.views[1:]:
        parent = parts[view.parent] if view.parent else None
        script.say(
            "zoom",
            f"Zooming into {parent.label if parent else view.title}: {view.title}.",
            view=view.id,
        )
        for identity in view.connection_ids:
            connection = links[identity]
            script.say(
                "zoom",
                sentence(connection, parts),
                connection.status,
                (connection.source, connection.target),
                (identity,),
                connection.citations[:1],
                view.id,
            )
    if architecture.unresolved:
        script.say("unknowns", "Static analysis did not establish the following.")
        for item in architecture.unresolved[:5]:
            script.say("unknowns", f"{item.topic.capitalize()}: {item.reason}", "UNRESOLVED")
    return tuple(script.lines)


def check_narration(lines: tuple[Line, ...], architecture: Architecture) -> None:
    """Independent of narrate(): each line must be backed by the validated IR it animates."""
    components = {c.id for c in architecture.components}
    connections = {c.id for c in architecture.connections}
    known: set[Citation] = set()
    for component in architecture.components:
        known.update(component.citations)
        known.update(layer.citation for layer in component.layers)
    for group in (architecture.connections, architecture.decisions, architecture.variants):
        for item in group:
            known.update(item.citations)
    for flow in architecture.flows:
        for step in flow.steps:
            known.update(step.citations)
    views = {view.id: view for view in architecture.views}
    if len({line.id for line in lines}) != len(lines) or not lines:
        raise ArchitectureError("narration_invalid")
    for line in lines:
        view = views.get(line.view)
        if architecture.views and (
            view is None
            or not set(line.component_ids) <= set(view.component_ids)
            or not set(line.connection_ids) <= set(view.connection_ids)
        ):
            raise ArchitectureError("narration_unsupported_element")
        if not set(line.component_ids) <= components or not set(line.connection_ids) <= connections:
            raise ArchitectureError("narration_unsupported_element")
        if not set(line.citations) <= known:
            raise ArchitectureError("narration_false_citation")
        if line.status in {"VERIFIED", "INFERRED"} and not line.citations:
            raise ArchitectureError("narration_uncited")
        if line.spoken != speakable(line.text)[:600]:
            raise ArchitectureError("narration_speech_mismatch")
    if narrate(architecture) != lines:
        raise ArchitectureError("narration_not_reproducible")


def exclusive(path: Path, body: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)


def render_architecture(
    report: Report,
    architecture: Architecture,
    work: Path,
    engine: Engine,
    checkpoint: Checkpoint = noop,
) -> dict[str, Any]:
    """Write one architecture's validated video bundle into an empty directory."""
    lines = narrate(architecture)
    check_narration(lines, architecture)
    diagrams = {
        view.id: Diagram(architecture, report.repository, report.commit_sha, view)
        for view in architecture.views
    } or {"overview": Diagram(architecture, report.repository, report.commit_sha)}
    scratch = work / "scratch"
    scratch.mkdir(mode=0o700)
    speech = []
    for i, line in enumerate(lines):
        checkpoint()
        speech.append(synthesize(engine, line.spoken, scratch, f"speech{i:03d}"))
    audio, timings = assemble(speech)

    entries: list[tuple[str, int]] = []
    cues = ["WEBVTT", ""]
    narration = []
    for i, (line, timing) in enumerate(zip(lines, timings, strict=True)):
        checkpoint()
        diagram = diagrams[line.view]
        base = diagram.base(
            line.component_ids,
            line.connection_ids,
            line.status,
            line.text,
            line.citations[0] if line.citations else None,
            i,
            len(lines),
        )
        exclusive(work / f"key{i:03d}.png", base.png())
        count = -(-timing.frames // ANIMATION_STEP)
        for j in range(count):
            name = f"a{i:03d}_{j:03d}.png"
            phase = (j * ANIMATION_STEP / FPS) / PULSE_SECONDS
            (scratch / name).write_bytes(diagram.animate(base, line.connection_ids, phase))
            last = j == count - 1
            entries.append((name, timing.frames - ANIMATION_STEP * j if last else ANIMATION_STEP))
        end = timing.start_frame + timing.frames
        cues += [f"{timestamp(timing.start_frame)} --> {timestamp(end)}", line.text, ""]
        narration.append(
            {
                **line.model_dump(mode="json"),
                "start_frame": timing.start_frame,
                "frames": timing.frames,
                "speech_seconds": round(timing.speech_seconds, 6),
            }
        )
    video, media = encode_sequence(scratch, entries, audio, checkpoint)
    for leftover in scratch.iterdir():
        leftover.unlink()
    scratch.rmdir()

    citations = []
    seen: set[tuple[str, str, int]] = set()

    def record(element: str, kind: str, items: tuple[Citation, ...]) -> None:
        for citation in items:
            key = (element, citation.path, citation.line)
            if key not in seen:
                seen.add(key)
                citations.append(
                    {"element": element, "kind": kind, **citation.model_dump(mode="json")}
                )

    for component in architecture.components:
        record(component.id, "component", component.citations)
        record(component.id, "layer", tuple(layer.citation for layer in component.layers))
    for connection in architecture.connections:
        record(connection.id, "connection", connection.citations)
    for flow in architecture.flows:
        for step in flow.steps:
            record(f"{flow.name}-step-{step.order}", "flow", step.citations)
    for n, fact in enumerate(architecture.decisions, 1):
        record(f"decision-{n}", "decision", fact.citations)
    for variant in architecture.variants:
        record(f"variant-{variant.name}", "variant", variant.citations)

    exclusive(work / "architecture.json", encoded(architecture.model_dump(mode="json")))
    exclusive(work / "narration.json", encoded(narration))
    exclusive(work / "citations.json", encoded(citations))
    exclusive(work / "captions.vtt", "\n".join(cues).encode())
    exclusive(work / "narration.wav", audio)
    exclusive(work / "video.mp4", video)
    return {
        "id": architecture.id,
        "type": architecture.type,
        "level": architecture.level,
        "status": architecture.status,
        "variants": [{"name": v.name, "status": v.status} for v in architecture.variants],
        "components": len(architecture.components),
        "connections": len(architecture.connections),
        "narration_lines": len(lines),
        "cited_lines": sum(bool(line.citations) for line in lines),
        "citations": len(citations),
        "animation_frames": len(entries),
        "unresolved": [u.topic for u in architecture.unresolved],
        "media": {k: v for k, v in media.items() if k != "ffmpeg_version"},
        "ffmpeg_version": media["ffmpeg_version"],
        "artifacts": {
            p.name: {"sha256": digest(p.read_bytes()), "bytes": p.stat().st_size}
            for p in sorted(work.iterdir())
        },
    }


def explain(
    report: Report,
    payload: dict[str, Any],
    sources: dict[str, bytes],
    output: Path,
    *,
    engine: Engine | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Publish architecture explainers, or an explicit unsupported record. Never a generic video."""
    started = time.perf_counter()
    validate(report, payload, sources)  # Evidence and reproducibility, before any drawing.
    if not output.is_absolute() or not output.parent.is_dir() or output.exists():
        raise RenderError("output_must_be_new_absolute_directory")
    output.mkdir(mode=0o700)
    work = output / "work"
    work.mkdir(mode=0o700)
    exclusive(work / "architecture-report.json", encoded(report.model_dump(mode="json")))
    rendered = []
    if report.architectures:
        engine = engine or detect()
        for architecture in report.architectures[:limit]:
            target = work / architecture.id
            target.mkdir(mode=0o700)
            rendered.append(render_architecture(report, architecture, target, engine))
    manifest: dict[str, Any] = {
        "version": VERSION,
        "status": "implementation output; not independently reviewed or accepted",
        "repository": report.repository,
        "commit_sha": report.commit_sha,
        "analysis_sha256": report.analysis_sha256,
        "architecture_explanation": report.explanation,
        "architectures": rendered,
        "not_rendered": [a.id for a in report.architectures[limit:]],
        "rejected": [
            {"candidate": r.candidate, "reason": r.reason, "detail": r.detail}
            for r in report.rejected
        ],
        "narration_engine": engine.name if engine else None,
        "model_inference": "none",
        "paid_services": "none",
        "platform": sys.platform,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "report_sha256": digest((work / "architecture-report.json").read_bytes()),
    }
    exclusive(work / "manifest.json", encoded(manifest))
    os.rename(work, output / "published")
    return manifest
