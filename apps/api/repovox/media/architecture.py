"""Architecture IR, source-evidence discovery and an independent validator.

Discovery reads verified analysis output plus the exact analysed source bytes. A pattern is
reported only when the code shows the defining relationships; names, comments, README text and
imports never classify anything. Missing parts are listed as unresolved, never filled in.
"""

import re
from typing import Any, Literal
from urllib.parse import quote as urlquote

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from repovox.analysis.common import canonical, digest
from repovox.analysis.contracts import PAYLOADS
from repovox.media.pyflow import (
    Layer,
    ModuleCall,
    ModuleClass,
    Scope,
    SourceFile,
    Tag,
    arguments,
    unwrap,
)

VERSION: Literal["architecture-ir-1.0"] = "architecture-ir-1.0"
Status = Literal["VERIFIED", "INFERRED", "UNRESOLVED"]
MENTION = re.compile(r"(?i)\b(gan|generative adversarial|generator|discriminator)\b")
DECLARATIONS = {"class", "function", "method"}


class ArchitectureError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(Closed):
    path: str
    file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=400)
    claim_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    permalink: str


class LayerIR(Closed):
    index: int
    type: str
    text: str
    resolved: bool
    citation: Citation


class Component(Closed):
    id: str
    role: str
    kind: Literal["module", "tensor", "loss", "optimizer", "service", "handler"]
    label: str = Field(min_length=1, max_length=28)
    lines: tuple[str, ...] = Field(default=(), max_length=7)
    layers: tuple[LayerIR, ...] = ()
    status: Status
    anchors: tuple[str, ...] = Field(min_length=1)
    citations: tuple[Citation, ...] = Field(min_length=1)


class Connection(Closed):
    id: str
    source: str
    target: str
    kind: Literal["data", "condition", "score", "gradient", "update", "registers"]
    label: str = Field(max_length=40)
    phase: Literal["training", "inference", "structure"]
    status: Status
    anchors: tuple[str, ...] = Field(min_length=1)
    citations: tuple[Citation, ...] = Field(min_length=1)


class Step(Closed):
    order: int
    text: str
    component_ids: tuple[str, ...]
    connection_ids: tuple[str, ...]
    status: Status
    citations: tuple[Citation, ...] = Field(min_length=1)


class Flow(Closed):
    name: Literal["training", "inference", "request"]
    steps: tuple[Step, ...] = Field(min_length=1)


class Fact(Closed):
    text: str
    status: Status
    component_ids: tuple[str, ...]
    citations: tuple[Citation, ...] = Field(min_length=1)


class Variant(Closed):
    name: str
    status: Status
    reason: str
    citations: tuple[Citation, ...] = Field(min_length=1)


class Unresolved(Closed):
    topic: str
    reason: str


class Architecture(Closed):
    id: str
    type: Literal["gan", "supervised_network", "http_service"]
    level: Literal["model", "system"]
    title: str
    scope: tuple[str, ...] = Field(min_length=1)
    status: Status
    variants: tuple[Variant, ...] = ()
    components: tuple[Component, ...] = Field(min_length=2)
    connections: tuple[Connection, ...] = Field(min_length=1)
    flows: tuple[Flow, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    decisions: tuple[Fact, ...] = ()
    unresolved: tuple[Unresolved, ...] = ()


class Mention(Closed):
    path: str
    line: int
    quote: str


class Rejected(Closed):
    candidate: str
    reason: Literal[
        "mention_without_implementation", "unbound_models", "incomplete_adversarial_path"
    ]
    detail: str
    mentions: tuple[Mention, ...]


class Report(Closed):
    version: Literal["architecture-ir-1.0"]
    repository: str
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    analysis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    explanation: Literal["supported", "unsupported"]
    architectures: tuple[Architecture, ...]
    rejected: tuple[Rejected, ...]


class Context:
    """Verified payload plus hash-checked source; the only inputs discovery may use."""

    def __init__(self, payload: dict[str, Any], sources: dict[str, bytes]) -> None:
        try:
            TypeAdapter(PAYLOADS["verify"]).validate_python(payload)
        except ValueError:
            raise ArchitectureError("invalid_analysis_payload") from None
        knowledge = payload["knowledge"]
        self.payload, self.snapshot = payload, knowledge["repository"]
        self.manifest = {f["path"]: f for f in knowledge["coverage"]["files"]}
        for path, body in sources.items():
            entry = self.manifest.get(path)
            if entry is None or entry["file_sha256"] != digest(body):
                raise ArchitectureError("source_mismatch")
        self.sources = sources
        self.files = {
            path: SourceFile(path, body)
            for path, body in sorted(sources.items())
            if self.manifest[path]["status"] == "parsed"
            and self.manifest[path]["language"] == "python"
        }
        verdicts = {v["claim_id"]: v for v in payload["verification"]["verdicts"]}
        valid = {e["id"] for e in payload["evidence"]["items"] if e["validation_status"] == "valid"}
        claims = {c["subject_id"]: c["id"] for c in knowledge["claims"]}
        self.symbols: dict[str, list[dict[str, Any]]] = {}
        self.verified: dict[str, str] = {}
        for symbol in knowledge["symbols"]:
            claim = claims.get(symbol["id"])
            verdict = verdicts.get(claim or "")
            if claim and verdict and verdict["status"] == "verified" and verdict["evidence_ids"]:
                if all(e in valid for e in verdict["evidence_ids"]):
                    self.verified[symbol["id"]] = claim
                    self.symbols.setdefault(symbol["path"], []).append(symbol)
        self.claim_symbols = {
            claim: symbol for symbol, claim in self.verified.items()
        }  # claim id -> symbol id
        self.symbol_index = {s["id"]: s for group in self.symbols.values() for s in group}
        found: dict[str, list[ModuleClass]] = {}
        for file in self.files.values():
            for item in file.module_classes():
                found.setdefault(item.name, []).append(item)
        # A class name declared twice cannot be bound from a bare constructor call.
        self.classes = {name: items[0] for name, items in found.items() if len(items) == 1}
        self.scopes: list[tuple[SourceFile, Scope]] = [
            (file, scope) for file in self.files.values() for scope in file.scopes(self.classes)
        ]

    def claims_at(self, path: str, number: int) -> tuple[str, ...]:
        """Narrowest verified syntax claims covering one source line."""
        group = self.symbols.get(path, [])
        exact = [
            s for s in group if s["start_line"] <= number <= s["end_line"] and s["kind"] != "module"
        ]
        on_line = [s for s in exact if s["start_line"] == number and s["kind"] not in DECLARATIONS]
        declared = [s for s in exact if s["start_line"] == number and s["kind"] in DECLARATIONS]
        enclosing = sorted(
            (s for s in exact if s["kind"] in DECLARATIONS),
            key=lambda s: (s["end_line"] - s["start_line"], s["id"]),
        )[:1]
        chosen = declared or on_line or enclosing or [s for s in group if s["kind"] == "module"]
        return tuple(sorted(self.verified[s["id"]] for s in chosen))[:8]

    def cite(self, path: str, number: int) -> Citation | None:
        file = self.files.get(path)
        claims = self.claims_at(path, number)
        text = file.quote(number) if file else ""
        if not text or not claims:
            return None
        return Citation(
            path=path,
            file_sha256=self.manifest[path]["file_sha256"],
            line=number,
            quote=text[:400],
            claim_ids=claims,
            permalink=(
                f"{self.snapshot['canonical_url']}/blob/{self.snapshot['commit_sha']}/"
                f"{urlquote(path, safe='/')}#L{number}-L{number}"
            ),
        )

    def must(self, path: str, number: int) -> Citation:
        found = self.cite(path, number)
        if found is None:
            raise ArchitectureError("uncitable_fact")
        return found


def layer_text(layer: Layer) -> str:
    a = list(layer.arguments)
    if layer.type == "Linear" and len(a) >= 2:
        body = f"{a[0]} -> {a[1]}"
    elif layer.type in {"Conv2d", "ConvTranspose2d", "Conv1d"} and len(a) >= 2:
        extra = "".join(f" {k}{v}" for k, v in zip("ksp", a[2:5], strict=False))
        body = f"{a[0]} -> {a[1]}{extra}"
    elif layer.type == "Embedding" and len(a) >= 2:
        body = f"{a[0]} x {a[1]}"
    else:
        body = " ".join(a + [f"{k}={v}" for k, v in layer.keywords])
    text = f"{layer.type} {body}".strip()
    return text if layer.resolved else f"{text} (not literal)"


def module_component(ctx: Context, role: str, item: ModuleClass) -> Component:
    layers = tuple(
        LayerIR(
            index=i,
            type=layer.type,
            text=layer_text(layer)[:44],
            resolved=layer.resolved,
            citation=ctx.must(item.path, layer.line),
        )
        for i, layer in enumerate(item.layers)
    )
    shown = [layer.text for layer in layers[:6]]
    if len(layers) > 6:
        shown[5] = f"... {len(layers) - 5} more layers"
    return Component(
        id=role,
        role=role,
        kind="module",
        label=item.name[:28],
        lines=tuple(shown) or ("layers not statically listed",),
        layers=layers,
        status="VERIFIED",
        anchors=(f"class {item.name}",),
        citations=(ctx.must(item.path, item.line),),
    )


def bound(scope: Scope, variable: str) -> Status:
    return "VERIFIED" if len(scope.assignments.get(variable, [])) == 1 else "INFERRED"


def derived(tag: Tag | None, cls: str) -> bool:
    return tag is not None and tag.kind == "output" and tag.cls == cls


def named(value: str) -> str:
    return re.split(r"[^A-Za-z0-9_]", value, maxsplit=1)[0] or value


class Builder:
    def __init__(self, ctx: Context, path: str) -> None:
        self.ctx, self.path = ctx, path
        self.components: dict[str, Component] = {}
        self.connections: list[Connection] = []

    def tensor(
        self, role: str, label: str, number: int, status: Status, lines: tuple[str, ...] = ()
    ) -> None:
        self.components.setdefault(
            role,
            Component(
                id=role,
                role=role,
                kind="tensor",
                label=label[:28],
                lines=lines,
                status=status,
                anchors=(label,),
                citations=(self.ctx.must(self.path, number),),
            ),
        )

    def node(
        self,
        role: str,
        kind: Any,
        label: str,
        numbers: list[int],
        lines: tuple[str, ...],
        anchor: str,
    ) -> None:
        self.components.setdefault(
            role,
            Component(
                id=role,
                role=role,
                kind=kind,
                label=label[:28],
                lines=lines,
                status="VERIFIED",
                anchors=(anchor,),
                citations=tuple(self.ctx.must(self.path, n) for n in sorted(set(numbers))),
            ),
        )

    def link(
        self,
        source: str,
        target: str,
        kind: Any,
        label: str,
        numbers: list[int],
        anchors: tuple[str, ...],
        status: Status = "VERIFIED",
        phase: Any = "training",
    ) -> str | None:
        if source not in self.components or target not in self.components:
            return None  # Never draw a connection to a component the code did not establish.
        identity = f"{source}-to-{target}" + ("" if phase == "training" else f"-{phase}")
        if any(c.id == identity for c in self.connections):
            return identity
        self.connections.append(
            Connection(
                id=identity,
                source=source,
                target=target,
                kind=kind,
                label=label[:40],
                phase=phase,
                status=status,
                anchors=anchors,
                citations=tuple(self.ctx.must(self.path, n) for n in sorted(set(numbers))),
            )
        )
        return identity


Event = tuple[int, str, tuple[str, ...], tuple[str | None, ...], Status, Citation]


def steps(
    items: list[tuple[int, str, tuple[str, ...], tuple[str | None, ...], Status, Citation]],
) -> tuple[Step, ...]:
    return tuple(
        Step(
            order=i + 1,
            text=text,
            component_ids=components,
            connection_ids=tuple(c for c in connections if c),
            status=status,
            citations=(citation,),
        )
        for i, (_, text, components, connections, status, citation) in enumerate(
            sorted(items, key=lambda x: x[0])
        )
    )


def gan(
    ctx: Context, file: SourceFile, scope: Scope, g_cls: str, d_cls: str, index: int
) -> Architecture:
    b = Builder(ctx, scope.path)
    g_call = next(
        c
        for c in scope.calls
        if c.cls == g_cls and any(a and a.kind == "noise" for a in c.arguments)
    )
    fake_calls = [
        c for c in scope.calls if c.cls == d_cls and c.arguments and derived(c.arguments[0], g_cls)
    ]
    real_call = next(
        c
        for c in scope.calls
        if c.cls == d_cls and c.arguments and not derived(c.arguments[0], g_cls)
    )
    unresolved: list[Unresolved] = []
    decisions: list[Fact] = []
    generator, discriminator = ctx.classes[g_cls], ctx.classes[d_cls]
    b.components["generator"] = module_component(ctx, "generator", generator)
    b.components["discriminator"] = module_component(ctx, "discriminator", discriminator)
    for role, item in (("generator", generator), ("discriminator", discriminator)):
        if item.dynamic or not item.layers:
            unresolved.append(
                Unresolved(
                    topic=f"{role} layers",
                    reason=f"{item.name} builds layers dynamically; they are not listed.",
                )
            )
        elif any(not layer.resolved for layer in item.layers):
            unresolved.append(
                Unresolved(
                    topic=f"{role} layer sizes",
                    reason="Some layer arguments are not literals or module constants.",
                )
            )

    noise_name = named(g_call.names[0])
    noise_tag = next(a for a in g_call.arguments if a and a.kind == "noise")
    noise_lines: tuple[str, ...] = ()
    history = scope.assignments.get(noise_name, [])
    if history:
        positional, _ = arguments(unwrap(history[-1][0], file.body))
        if positional:
            value, known = file.literal(positional[-1], {})
            if known and value.isdigit():
                noise_lines = (f"latent size {value}",)
    if not noise_lines:
        unresolved.append(
            Unresolved(
                topic="latent size",
                reason="The noise dimension is not a literal or module constant.",
            )
        )
    b.tensor("noise", noise_name, noise_tag.line, "VERIFIED", noise_lines)
    generated_name = named(fake_calls[0].names[0])
    b.tensor("generated", generated_name, g_call.line, bound(scope, generated_name))
    real_name = named(real_call.names[0])
    real_tag = real_call.arguments[0]
    real_status: Status = (
        "VERIFIED" if real_tag is not None and real_tag.kind == "batch" else "INFERRED"
    )
    b.tensor("real", real_name, real_tag.line if real_tag else real_call.line, real_status)
    if real_status == "INFERRED":
        unresolved.append(
            Unresolved(
                topic="real data origin",
                reason=(
                    f"{real_name} is not derived from the generator, but its source is "
                    f"not a data-loader loop."
                ),
            )
        )

    conditional = (
        len(g_call.names) >= 2
        and all(len(c.names) >= 2 for c in [*fake_calls, real_call])
        and len({c.names[1] for c in [g_call, real_call, *fake_calls]}) == 1
        and len(generator.forward_parameters) >= 2
        and len(discriminator.forward_parameters) >= 2
    )
    if conditional:
        label = named(g_call.names[1])
        tag = g_call.arguments[1]
        b.tensor(
            "condition", label, tag.line if tag else g_call.line, "VERIFIED" if tag else "INFERRED"
        )

    g_var, d_var = g_call.variable, real_call.variable
    status: Status = (
        bound(scope, g_var)
        if bound(scope, g_var) == bound(scope, d_var) == "VERIFIED"
        else "INFERRED"
    )
    c_noise = b.link(
        "noise", "generator", "data", "noise in", [g_call.line], (f"{g_var}(", noise_name), status
    )
    c_cond_g = b.link(
        "condition",
        "generator",
        "condition",
        "label",
        [g_call.line],
        (f"{g_var}(", g_call.names[1] if conditional else ""),
        status,
    )
    c_out = b.link(
        "generator",
        "generated",
        "data",
        "generated sample",
        [g_call.line],
        (f"{g_var}(", generated_name),
        status,
    )
    detached = [c for c in fake_calls if c.arguments[0] is not None and c.arguments[0].detached]
    c_fake = b.link(
        "generated",
        "discriminator",
        "data",
        "generated in",
        [c.line for c in fake_calls],
        (f"{d_var}(", generated_name),
        status,
    )
    c_real = b.link(
        "real",
        "discriminator",
        "data",
        "real in",
        [real_call.line],
        (f"{d_var}(", real_name),
        status if real_status == "VERIFIED" else "INFERRED",
    )
    c_cond_d = b.link(
        "condition",
        "discriminator",
        "condition",
        "label",
        [real_call.line],
        (f"{d_var}(", real_call.names[1] if conditional else ""),
        status,
    )

    trained: dict[str, dict[str, Any]] = {}
    for loss_name, backward_line in scope.backwards:
        following = [s for s in scope.steps if s[1] > backward_line]
        optimizer = scope.optimizers.get(following[0][0]) if following else None
        if optimizer is None or optimizer["model"] not in {g_cls, d_cls}:
            continue
        side = "g" if optimizer["model"] == g_cls else "d"
        trained.setdefault(
            side,
            {
                "loss": loss_name,
                "backward": backward_line,
                "optimizer": following[0][0],
                "step": following[0][1],
                "settings": optimizer,
                "terms": file.loss_terms(scope, loss_name, backward_line),
            },
        )
    events: list[tuple[int, str, tuple[str, ...], tuple[str | None, ...], Status, Citation]] = [
        (
            g_call.line,
            f"{generator.name} maps {noise_name} to {generated_name}.",
            ("noise", "generator", "generated"),
            (c_noise, c_cond_g, c_out),
            status,
            ctx.must(scope.path, g_call.line),
        ),
        (
            real_call.line,
            f"{discriminator.name} scores the real batch {real_name}.",
            ("real", "discriminator"),
            (c_real, c_cond_d),
            status,
            ctx.must(scope.path, real_call.line),
        ),
    ]
    events.append(
        (
            fake_calls[0].line,
            f"{discriminator.name} scores the generated sample {generated_name}.",
            ("generated", "discriminator"),
            (c_fake,),
            status,
            ctx.must(scope.path, fake_calls[0].line),
        )
    )
    for side, target, name in (
        ("d", "discriminator", discriminator.name),
        ("g", "generator", generator.name),
    ):
        info = trained.get(side)
        if info is None:
            unresolved.append(
                Unresolved(
                    topic=f"{target} update",
                    reason=(
                        f"No loss with a backward pass followed by an optimizer step on "
                        f"{name} parameters was found."
                    ),
                )
            )
            continue
        functions = sorted({t.function for t in info["terms"]})
        formula = ", ".join(functions) if functions else "expression not recognised"
        if not functions:
            unresolved.append(
                Unresolved(
                    topic=f"{target} loss formulation",
                    reason="The loss expression does not use a recognised loss function.",
                )
            )
        lines = sorted({t.line for t in info["terms"]}) or [info["backward"]]
        b.node(
            f"loss_{side}",
            "loss",
            info["loss"],
            [*lines, info["backward"]],
            (formula[:44],),
            info["loss"],
        )
        settings = ", ".join(f"{k}={v}" for k, v in info["settings"]["settings"])
        b.node(
            f"opt_{side}",
            "optimizer",
            info["optimizer"],
            [info["settings"]["line"]],
            (info["settings"]["type"], settings[:44]) if settings else (info["settings"]["type"],),
            info["optimizer"],
        )
        score = b.link(
            "discriminator",
            f"loss_{side}",
            "score",
            "scores",
            [*lines, info["backward"]],
            (info["loss"],),
        )
        grad = b.link(
            f"loss_{side}",
            f"opt_{side}",
            "gradient",
            "backward",
            [info["backward"]],
            (f"{info['loss']}.backward",),
        )
        update = b.link(
            f"opt_{side}",
            target,
            "update",
            "updates weights",
            [info["step"]],
            (f"{info['optimizer']}.step",),
        )
        events.append(
            (
                lines[0],
                f"{info['loss']} is computed from discriminator scores using {formula}.",
                ("discriminator", f"loss_{side}"),
                (score,),
                "VERIFIED",
                ctx.must(scope.path, lines[0]),
            )
        )
        events.append(
            (
                info["step"],
                f"{info['loss']}.backward() then {info['optimizer']}.step() update {name}.",
                (f"loss_{side}", f"opt_{side}", target),
                (grad, update),
                "VERIFIED",
                ctx.must(scope.path, info["step"]),
            )
        )
        decisions.append(
            Fact(
                text=f"{name} is optimised with {info['settings']['type']}"
                + (f" ({settings})" if settings else "")
                + ".",
                status="VERIFIED",
                component_ids=(f"opt_{side}",),
                citations=(ctx.must(scope.path, info["settings"]["line"]),),
            )
        )
    if "d" in trained and "g" in trained:
        first = "discriminator" if trained["d"]["step"] < trained["g"]["step"] else "generator"
        decisions.append(
            Fact(
                text=f"Within one iteration the {first} is updated first.",
                status="VERIFIED",
                component_ids=("opt_d", "opt_g"),
                citations=(
                    ctx.must(scope.path, trained["d"]["step"]),
                    ctx.must(scope.path, trained["g"]["step"]),
                ),
            )
        )
    if detached:
        decisions.append(
            Fact(
                text=(
                    f"{generated_name} is detached before the discriminator update, so "
                    f"that step does not send gradients into {generator.name}."
                ),
                status="VERIFIED",
                component_ids=("generated", "discriminator"),
                citations=(ctx.must(scope.path, detached[0].line),),
            )
        )
    for role, item in (("generator", generator), ("discriminator", discriminator)):
        final = item.layers[-1] if item.layers else None
        if final is not None and final.type in {"Tanh", "Sigmoid", "Softmax"}:
            decisions.append(
                Fact(
                    text=f"{item.name} ends with a {final.type} layer.",
                    status="VERIFIED",
                    component_ids=(role,),
                    citations=(ctx.must(item.path, final.line),),
                )
            )

    flows = [Flow(name="training", steps=steps(events))]
    inference = [
        (f, s, c)
        for f, s in ctx.scopes
        if not s.steps and (s.path, s.name) != (scope.path, scope.name)
        for c in s.calls
        if c.cls == g_cls and any(a and a.kind == "noise" for a in c.arguments)
    ]
    scope_paths = {scope.path, generator.path, discriminator.path}
    if inference:
        other_file, other, call = inference[0]
        citation = ctx.must(other.path, call.line)
        guard = " under torch.no_grad()" if other.no_grad else ""
        flows.append(
            Flow(
                name="inference",
                steps=(
                    Step(
                        order=1,
                        text=(
                            f"{other.name} in {other.path} calls {generator.name} on fresh "
                            f"noise{guard}, without any optimizer step."
                        ),
                        component_ids=("noise", "generator", "generated"),
                        connection_ids=tuple(c for c in (c_noise, c_out) if c),
                        status="VERIFIED",
                        citations=(citation,),
                    ),
                ),
            )
        )
        scope_paths.add(other.path)
    else:
        unresolved.append(
            Unresolved(
                topic="inference flow",
                reason="No function calls the generator on noise outside the training loop.",
            )
        )

    variants: list[Variant] = []
    if conditional:
        variants.append(
            Variant(
                name="conditional",
                status="VERIFIED",
                reason=(
                    "The same label argument is passed to the generator call and to every "
                    "discriminator call, and both forward methods take a second parameter."
                ),
                citations=(ctx.must(scope.path, g_call.line), ctx.must(scope.path, real_call.line)),
            )
        )
    g_types, d_types = {x.type for x in generator.layers}, {x.type for x in discriminator.layers}
    if "ConvTranspose2d" in g_types and "Conv2d" in d_types:
        up = next(x for x in generator.layers if x.type == "ConvTranspose2d")
        down = next(x for x in discriminator.layers if x.type == "Conv2d")
        variants.append(
            Variant(
                name="convolutional (DCGAN-style)",
                status="INFERRED",
                reason=(
                    "The generator uses transposed convolutions and the discriminator "
                    "uses convolutions. Whether it follows every DCGAN guideline is not "
                    "established."
                ),
                citations=(
                    ctx.must(generator.path, up.line),
                    ctx.must(discriminator.path, down.line),
                ),
            )
        )
    unresolved.append(
        Unresolved(
            topic="tensor shapes",
            reason=(
                "Only declared layer arguments are reported; intermediate tensor shapes "
                "are not computed."
            ),
        )
    )
    unresolved.append(
        Unresolved(
            topic="training outcome",
            reason=(
                "Static analysis cannot establish convergence, sample quality or runtime behavior."
            ),
        )
    )
    return Architecture(
        id=f"gan-{index}",
        type="gan",
        level="model",
        title=f"GAN: {generator.name} vs {discriminator.name}"[:60],
        scope=tuple(sorted(scope_paths)),
        status=status,
        variants=tuple(variants),
        components=tuple(b.components.values()),
        connections=tuple(b.connections),
        flows=tuple(flows),
        inputs=tuple(r for r in ("noise", "condition", "real") if r in b.components),
        outputs=("generated",),
        decisions=tuple(decisions),
        unresolved=tuple(unresolved),
    )


def supervised(
    ctx: Context, file: SourceFile, scope: Scope, call: ModuleCall, index: int
) -> Architecture | None:
    model = ctx.classes[call.cls]
    b = Builder(ctx, scope.path)
    for loss_name, backward_line in scope.backwards:
        following = [s for s in scope.steps if s[1] > backward_line]
        optimizer = scope.optimizers.get(following[0][0]) if following else None
        terms = file.loss_terms(scope, loss_name, backward_line)
        term = next((t for t in terms if derived(t.score, call.cls)), None)
        if optimizer is None or optimizer["model"] != call.cls or term is None:
            continue
        b.components["model"] = module_component(ctx, "model", model)
        input_name = named(call.names[0])
        tag = call.arguments[0]
        b.tensor("input", input_name, tag.line if tag else call.line, "VERIFIED")
        prediction = next(
            (
                n
                for n, t in scope.tags.items()
                if t.kind == "output" and t.cls == call.cls and t.line == call.line
            ),
            "output",
        )
        b.tensor("prediction", prediction, call.line, "VERIFIED")
        b.node("loss", "loss", loss_name, [term.line, backward_line], (term.function,), loss_name)
        settings = ", ".join(f"{k}={v}" for k, v in optimizer["settings"])
        b.node(
            "optimizer",
            "optimizer",
            following[0][0],
            [optimizer["line"]],
            (optimizer["type"], settings[:44]) if settings else (optimizer["type"],),
            following[0][0],
        )
        variable = call.variable
        c_in = b.link(
            "input", "model", "data", "batch in", [call.line], (f"{variable}(", input_name)
        )
        c_out = b.link(
            "model", "prediction", "data", "prediction", [call.line], (f"{variable}(", prediction)
        )
        c_loss = b.link(
            "prediction", "loss", "score", "compared with targets", [term.line], (prediction,)
        )
        c_grad = b.link(
            "loss", "optimizer", "gradient", "backward", [backward_line], (f"{loss_name}.backward",)
        )
        c_up = b.link(
            "optimizer",
            "model",
            "update",
            "updates weights",
            [following[0][1]],
            (f"{following[0][0]}.step",),
        )
        events: list[Event] = [
            (
                call.line,
                f"{model.name} maps the batch {input_name} to {prediction}.",
                ("input", "model", "prediction"),
                (c_in, c_out),
                "VERIFIED",
                ctx.must(scope.path, call.line),
            ),
            (
                term.line,
                f"{loss_name} compares {prediction} with targets using {term.function}.",
                ("prediction", "loss"),
                (c_loss,),
                "VERIFIED",
                ctx.must(scope.path, term.line),
            ),
            (
                following[0][1],
                f"{loss_name}.backward() then {following[0][0]}.step() update {model.name}.",
                ("loss", "optimizer", "model"),
                (c_grad, c_up),
                "VERIFIED",
                ctx.must(scope.path, following[0][1]),
            ),
        ]
        variants = []
        conv = next((x for x in model.layers if x.type.startswith("Conv")), None)
        if conv is not None:
            variants.append(
                Variant(
                    name="convolutional",
                    status="VERIFIED",
                    reason=f"{model.name} declares {conv.type} layers.",
                    citations=(ctx.must(model.path, conv.line),),
                )
            )
        unresolved = [
            Unresolved(
                topic="task",
                reason="What the predictions mean is not established from code structure.",
            ),
            Unresolved(
                topic="inference flow", reason="No separate inference function was identified."
            ),
        ]
        if model.dynamic or not model.layers:
            unresolved.append(
                Unresolved(
                    topic="model layers",
                    reason=f"{model.name} builds layers dynamically; they are not listed.",
                )
            )
        return Architecture(
            id=f"supervised-{index}",
            type="supervised_network",
            level="model",
            title=f"Supervised network: {model.name}"[:60],
            scope=tuple(sorted({scope.path, model.path})),
            status="VERIFIED",
            variants=tuple(variants),
            components=tuple(b.components.values()),
            connections=tuple(b.connections),
            flows=(Flow(name="training", steps=steps(events)),),
            inputs=("input",),
            outputs=("prediction",),
            decisions=(
                Fact(
                    text=f"{model.name} is optimised with {optimizer['type']}"
                    + (f" ({settings})" if settings else "")
                    + f" against {term.function}.",
                    status="VERIFIED",
                    component_ids=("optimizer", "loss"),
                    citations=(
                        ctx.must(scope.path, optimizer["line"]),
                        ctx.must(scope.path, term.line),
                    ),
                ),
            ),
            unresolved=tuple(unresolved),
        )
    return None


def http_service(ctx: Context) -> Architecture | None:
    """System level: a framework application object and the route handlers bound to it."""
    candidates = ctx.payload["knowledge"]["entrypoints"]["candidates"]
    apps = [
        c
        for c in candidates
        if c["rule"] == "framework-construction-v1" and c["symbol_id"] in ctx.symbol_index
    ]
    if not apps:
        return None
    app = ctx.symbol_index[apps[0]["symbol_id"]]
    routes = [
        ctx.symbol_index[c["symbol_id"]]
        for c in candidates
        if c["rule"] == "framework-route-v1"
        and c["path"] == app["path"]
        and c["symbol_id"] in ctx.symbol_index
    ][:5]
    citation = ctx.cite(app["path"], app["start_line"])
    if not routes or citation is None:
        return None
    b = Builder(ctx, app["path"])
    name = app["name"].split(".")[-1][:28] or "application"
    b.components["application"] = Component(
        id="application",
        role="application",
        kind="service",
        label=name,
        lines=("framework application object",),
        status="VERIFIED",
        anchors=(name,),
        citations=(citation,),
    )
    events: list[Event] = []
    for i, route in enumerate(routes):
        role = f"handler_{i + 1}"
        label = route["name"][:28]
        found = ctx.cite(route["path"], route["start_line"])
        if found is None:
            continue
        b.components[role] = Component(
            id=role,
            role="handler",
            kind="handler",
            label=label,
            status="INFERRED",
            anchors=(label.split(".")[-1],),
            citations=(found,),
        )
        link = b.link(
            "application",
            role,
            "registers",
            "route",
            [route["start_line"]],
            (label.split(".")[-1],),
            "INFERRED",
            "structure",
        )
        events.append(
            (
                route["start_line"],
                f"{label} is registered on the application object.",
                ("application", role),
                (link,),
                "INFERRED",
                found,
            )
        )
    if len(b.components) < 2:
        return None
    return Architecture(
        id="http-service-1",
        type="http_service",
        level="system",
        title="HTTP service"[:60],
        scope=(app["path"],),
        status="INFERRED",
        components=tuple(b.components.values()),
        connections=tuple(b.connections),
        flows=(Flow(name="request", steps=steps(events)),),
        unresolved=(
            Unresolved(
                topic="request handling",
                reason=(
                    "Route registration is a candidate binding; which handler runs for "
                    "a request is not executed or verified."
                ),
            ),
            Unresolved(
                topic="dependencies",
                reason=(
                    "Databases, queues and external services are not established by this detector."
                ),
            ),
        ),
    )


def mentions(ctx: Context) -> tuple[Mention, ...]:
    found: list[Mention] = []
    for path, body in sorted(ctx.sources.items()):
        for number, text in enumerate(body.decode("utf-8", "replace").split("\n"), 1):
            if MENTION.search(text) and len(found) < 6:
                found.append(Mention(path=path, line=number, quote=text.strip()[:200]))
    return tuple(found)


def discover(payload: dict[str, Any], sources: dict[str, bytes]) -> Report:
    ctx = Context(payload, sources)
    architectures: list[Architecture] = []
    rejected: list[Rejected] = []
    paired: set[str] = set()
    partial = False
    for file, scope in ctx.scopes:
        generators = {
            c.cls for c in scope.calls if any(a and a.kind == "noise" for a in c.arguments)
        }
        for g_cls in sorted(generators):
            for d_cls in sorted(
                {
                    c.cls
                    for c in scope.calls
                    if c.cls != g_cls and c.arguments and derived(c.arguments[0], g_cls)
                }
            ):
                if any(
                    c.cls == d_cls and c.arguments and not derived(c.arguments[0], g_cls)
                    for c in scope.calls
                ):
                    if {g_cls, d_cls} & paired:
                        continue
                    architectures.append(
                        gan(ctx, file, scope, g_cls, d_cls, len(architectures) + 1)
                    )
                    paired |= {g_cls, d_cls}
                else:
                    partial = True
    for file, scope in ctx.scopes:
        for call in scope.calls:
            tag = call.arguments[0] if call.arguments else None
            if call.cls in paired or tag is None or tag.kind != "batch" or tag.index != 0:
                continue
            found = supervised(ctx, file, scope, call, len(architectures) + 1)
            if found is not None:
                architectures.append(found)
                paired.add(call.cls)
    service = http_service(ctx)
    if service is not None:
        architectures.append(service)
    if not any(a.type == "gan" for a in architectures):
        noted = mentions(ctx)
        unbound = [
            (scope, name, number) for _, scope in ctx.scopes for name, number in scope.unbound
        ]
        declared = sorted(n for n in ctx.classes if MENTION.search(n))
        if unbound and declared:
            scope, name, number = unbound[0]
            rejected.append(
                Rejected(
                    candidate="gan",
                    reason="unbound_models",
                    detail=(
                        f"Module classes {', '.join(declared)} are declared, but {scope.name} "
                        f"in {scope.path} receives its models as parameters. Which class "
                        f"produces the data passed to which model cannot be bound statically, "
                        f"so no adversarial path is reported."
                    ),
                    mentions=noted,
                )
            )
        elif partial:
            rejected.append(
                Rejected(
                    candidate="gan",
                    reason="incomplete_adversarial_path",
                    detail=(
                        "A module output derived from noise reaches a second module, but "
                        "that module is never also applied to data that does not come "
                        "from the first. A real-versus-generated comparison is not established."
                    ),
                    mentions=noted,
                )
            )
        elif noted:
            rejected.append(
                Rejected(
                    candidate="gan",
                    reason="mention_without_implementation",
                    detail=(
                        "GAN-related terms appear in names, comments or documentation, "
                        "but no analysed scope passes a noise-driven module output into "
                        "a second module that also scores other data."
                    ),
                    mentions=noted,
                )
            )
    report = Report(
        version=VERSION,
        repository=ctx.snapshot["repository"],
        commit_sha=ctx.snapshot["commit_sha"],
        analysis_sha256=digest(canonical(payload)),
        explanation="supported" if architectures else "unsupported",
        architectures=tuple(architectures),
        rejected=tuple(rejected),
    )
    check(report, payload, sources)
    return report


GAN_CORE = [
    ("noise", "generator"),
    ("generator", "generated"),
    ("generated", "discriminator"),
    ("real", "discriminator"),
]


def check(report: Report, payload: dict[str, Any], sources: dict[str, bytes]) -> None:
    """Independent of the detectors: every element must be backed by exact, verified source."""
    ctx = Context(payload, sources)
    if (
        report.analysis_sha256 != digest(canonical(payload))
        or report.commit_sha != ctx.snapshot["commit_sha"]
    ):
        raise ArchitectureError("analysis_mismatch")
    if report.explanation != ("supported" if report.architectures else "unsupported"):
        raise ArchitectureError("explanation_mismatch")
    lines = {path: body.decode("utf-8", "replace").split("\n") for path, body in sources.items()}

    def cited(citations: tuple[Citation, ...], anchors: tuple[str, ...] = ()) -> None:
        for c in citations:
            text = lines.get(c.path)
            if text is None or c.file_sha256 != digest(sources[c.path]) or c.line > len(text):
                raise ArchitectureError("false_citation")
            if text[c.line - 1].strip()[:400] != c.quote:
                raise ArchitectureError("false_citation")
            if not c.permalink.startswith(
                f"{ctx.snapshot['canonical_url']}/blob/{report.commit_sha}/"
            ) or not c.permalink.endswith(f"#L{c.line}-L{c.line}"):
                raise ArchitectureError("false_citation")
            for claim in c.claim_ids:
                symbol = ctx.symbol_index.get(ctx.claim_symbols.get(claim, ""))
                if (
                    symbol is None
                    or symbol["path"] != c.path
                    or not symbol["start_line"] <= c.line <= symbol["end_line"]
                ):
                    raise ArchitectureError("unverified_claim")
        joined = " ".join(c.quote for c in citations)
        if any(a and a not in joined for a in anchors):
            raise ArchitectureError("unsupported_element")  # The cited code does not show it.

    for mention in (m for r in report.rejected for m in r.mentions):
        text = lines.get(mention.path)
        if (
            text is None
            or mention.line > len(text)
            or text[mention.line - 1].strip()[:200] != mention.quote
        ):
            raise ArchitectureError("false_citation")
    if len({a.id for a in report.architectures}) != len(report.architectures):
        raise ArchitectureError("duplicate_architecture")
    for architecture in report.architectures:
        ids = [c.id for c in architecture.components]
        if len(set(ids)) != len(ids) or len({c.id for c in architecture.connections}) != len(
            architecture.connections
        ):
            raise ArchitectureError("duplicate_element")
        for component in architecture.components:
            cited(component.citations, component.anchors)
            for layer in component.layers:
                cited((layer.citation,), (layer.type + "(",))
        pairs = set()
        for connection in architecture.connections:
            if (
                connection.source not in ids
                or connection.target not in ids
                or connection.source == connection.target
            ):
                raise ArchitectureError("unsupported_connection")
            cited(connection.citations, connection.anchors)
            pairs.add((connection.source, connection.target))
        for flow in architecture.flows:
            for step in flow.steps:
                if not set(step.component_ids) <= set(ids) or not set(step.connection_ids) <= {
                    c.id for c in architecture.connections
                }:
                    raise ArchitectureError("unsupported_flow")
                cited(step.citations)
        for fact in architecture.decisions:
            if not set(fact.component_ids) <= set(ids):
                raise ArchitectureError("unsupported_flow")
            cited(fact.citations)
        for variant in architecture.variants:
            cited(variant.citations)
        if not set(architecture.inputs) | set(architecture.outputs) <= set(ids):
            raise ArchitectureError("unsupported_flow")
        if not set(architecture.scope) <= set(sources):
            raise ArchitectureError("false_citation")
        if architecture.type == "gan":
            roles = [c.role for c in architecture.components]
            if (
                roles.count("generator") != 1
                or roles.count("discriminator") != 1
                or not set(GAN_CORE) <= pairs
            ):
                raise ArchitectureError("gan_core_missing")
            if any(
                c.kind != "module"
                for c in architecture.components
                if c.role in {"generator", "discriminator"}
            ):
                raise ArchitectureError("gan_core_missing")


def validate(report: Report, payload: dict[str, Any], sources: dict[str, bytes]) -> None:
    """Evidence checks plus exact reproducibility from the same pinned inputs."""
    check(report, payload, sources)
    if discover(payload, sources) != report:
        raise ArchitectureError("architecture_not_reproducible")
