"""Deterministic architecture diagrams drawn only from a validated Architecture IR.

One renderer serves every architecture. Components are placed in tier bands, top to bottom:
client and frontend, API and routes, core services, then models, workers, storage and external
dependencies. A tier is read from what the IR records about a component (kind, role, declaring
path); it orders the drawing and never adds a node. Inside a band each boundary (for example a
source file) is a labelled container, and cards follow the direction of the relationships.
When the bands do not fit, the column layout of `automatic` is used: it is the layout the IR's
own drawability check already guarantees. A small table of fixed positions exists for two
reviewed layouts; it only places roles and can never add a node or an arrow. A box exists only
for an IR component and a line only for an IR connection.

Cards carry a role badge (UI, API, SVC, ML, DATA, EXT) and a status border: solid for
VERIFIED, dashed otherwise. A narrated frame spotlights its components (glow, callout) and
dims the rest; a workflow step is drawn from its source toward its target and then carries a
travelling packet, with a step bar and the cited file and line.
"""

import re

from repovox.media.architecture import Architecture, Citation, Component, Connection, View
from repovox.media.raster import (
    ACCENT,
    BAND,
    BG,
    CARD,
    HEIGHT,
    MUTED,
    TEXT,
    WARN,
    WIDTH,
    Canvas,
    Color,
    LayoutError,
    mix,
    wrap,
)
from repovox.media.storyboard import display

Box = tuple[int, int, int, int]
Point = tuple[int, int]
Lane = tuple[str, Box]
DIM: Color = (58, 78, 104)
DIM_TEXT: Color = (120, 140, 165)
LANE: Color = (30, 46, 68)
FEEDBACK = {"gradient", "update"}
ROLE_NAMES = {
    "noise": "noise",
    "condition": "condition",
    "real": "real batch",
    "generated": "generated",
    "input": "parameter",
    "output": "result",
    "prediction": "prediction",
    "source_file": "source file",
    "http_client": "http client",
    "object_storage": "object storage",
    "message_broker": "message broker",
}
LAYOUTS: dict[str, dict[str, Box]] = {
    "gan": {
        "noise": (40, 160, 150, 56),
        "condition": (40, 236, 150, 56),
        "real": (40, 468, 150, 56),
        "generator": (230, 150, 320, 190),
        "generated": (590, 284, 150, 56),
        "discriminator": (780, 350, 300, 190),
        "loss_g": (1110, 150, 140, 56),
        "opt_g": (1110, 222, 140, 56),
        "loss_d": (1110, 366, 140, 56),
        "opt_d": (1110, 468, 140, 56),
    },
    "supervised_network": {
        "input": (40, 290, 150, 56),
        "model": (240, 220, 320, 190),
        "prediction": (620, 290, 150, 56),
        "loss": (840, 290, 150, 56),
        "optimizer": (620, 440, 150, 56),
    },
}
# Horizontal-then-vertical where the default vertical-then-horizontal route would cross a box.
HV = {("optimizer", "model")}
TOP, ROW, BOX_H, LANE_HEAD = 130, 72, 56, 26


def layers(components: list[Component], connections: list[Connection]) -> dict[str, int]:
    """Column per component: longest path along forward relationships, cycles cut."""
    ids = [c.id for c in components]
    outgoing: dict[str, list[str]] = {i: [] for i in ids}
    for connection in connections:
        if connection.kind not in FEEDBACK and connection.source in outgoing:
            if connection.target in outgoing:
                outgoing[connection.source].append(connection.target)
    state: dict[str, int] = {}
    forward: list[tuple[str, str]] = []

    def visit(node: str) -> None:
        state[node] = 1
        for target in outgoing[node]:
            if state.get(target) == 1:
                continue  # A back edge closes a loop; it does not push the layout further.
            forward.append((node, target))
            if target not in state:
                visit(target)
        state[node] = 2

    for node in ids:
        if node not in state:
            visit(node)
    level = dict.fromkeys(ids, 0)
    for _ in ids:
        for source, target in forward:
            level[target] = max(level[target], level[source] + 1)
    return level


def automatic(
    components: list[Component], connections: list[Connection]
) -> tuple[dict[str, Box], list[Lane]]:
    level = layers(components, connections)
    columns = max(level.values(), default=0) + 1
    width = 1200 // columns
    box_w = min(210, width - 36)
    if box_w < 110:
        raise LayoutError("diagram_overflow")
    groups = list(dict.fromkeys(c.group for c in components))
    lanes: list[str] = []
    rows: list[int] = []
    head = 0
    for candidate in (groups if 1 < len(groups) <= 4 else [""], [""]):
        single = candidate == [""]
        counts = []
        for lane in candidate:
            members = [c for c in components if single or c.group == lane]
            counts.append(
                max(
                    (sum(level[m.id] == col for m in members) for col in range(columns)),
                    default=1,
                )
            )
        head = 0 if single else LANE_HEAD
        if sum(counts) * ROW + len(candidate) * head <= 420:
            lanes, rows = candidate, counts
            break
    if not lanes:
        raise LayoutError("diagram_overflow")
    single = lanes == [""]
    placed: dict[str, Box] = {}
    frames: list[Lane] = []
    y = TOP
    for lane, count in zip(lanes, rows, strict=True):
        members = [c for c in components if single or c.group == lane]
        if not single:
            frames.append((lane, (40, y, 1200, head + count * ROW - 6)))
        for column in range(columns):
            stacked = [m for m in members if level[m.id] == column]
            for index, member in enumerate(stacked):
                x = 40 + column * width + (width - box_w) // 2
                placed[member.id] = (x, y + head + index * ROW, box_w, BOX_H)
        y += head + count * ROW
    return placed, frames


def route(a: Box, b: Box, hv: bool, lane: int) -> list[Point]:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if ay < by + bh and by < ay + ah and (ax + aw <= bx or bx + bw <= ax):
        small = a if ah <= bh else b
        y = small[1] + small[3] // 2
        return [(ax + aw, y), (bx, y)] if ax < bx else [(ax, y), (bx + bw, y)]
    if ax < bx + bw and bx < ax + aw:
        small = a if aw <= bw else b
        x = small[0] + small[2] // 2
        return [(x, ay + ah), (x, by)] if ay < by else [(x, ay), (x, by + bh)]
    if hv:
        y = ay + ah // 2
        x = bx + bw // 2
        start = (ax, y) if bx < ax else (ax + aw, y)
        return [start, (x, y), (x, by + bh if by < ay else by)]
    x = ax + aw // 2
    y = by + bh // 2 if bh < 100 else by + 40 + 45 * lane
    start = (x, ay + ah) if by > ay else (x, ay)
    return [start, (x, y), (bx if bx > ax else bx + bw, y)]


def crossings(points: list[Point], others: list[Box]) -> int:
    count = 0
    for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
        left, right, top, bottom = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
        for x, y, w, h in others:
            if left < x + w and right > x and top < y + h and bottom > y:
                count += 1
    return count


def length(points: list[Point]) -> int:
    return sum(
        abs(x2 - x1) + abs(y2 - y1) for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False)
    )


def along(points: list[Point], fraction: float) -> Point:
    remaining = fraction * length(points)
    for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
        span = abs(x2 - x1) + abs(y2 - y1)
        if remaining <= span and span:
            part = remaining / span
            return round(x1 + (x2 - x1) * part), round(y1 + (y2 - y1) * part)
        remaining -= span
    return points[-1]


def segment(canvas: Canvas, start: Point, end: Point, color: Color, width: int = 3) -> None:
    x, y = min(start[0], end[0]), min(start[1], end[1])
    half = width // 2
    canvas.rect(
        max(0, x - half),
        max(0, y - half),
        abs(end[0] - start[0]) + width,
        abs(end[1] - start[1]) + width,
        color,
    )


def arrowhead(canvas: Canvas, before: Point, tip: Point, color: Color) -> None:
    dx = (tip[0] > before[0]) - (tip[0] < before[0])
    dy = (tip[1] > before[1]) - (tip[1] < before[1])
    for n in range(1, 8):
        cx, cy = tip[0] - dx * n, tip[1] - dy * n
        if dx:
            canvas.rect(max(0, cx - 1), max(0, cy - n), 2, 2 * n + 1, color)
        else:
            canvas.rect(max(0, cx - n), max(0, cy - 1), 2 * n + 1, 2, color)


def short_layer(value: str) -> str:
    return re.sub(r" [ksp]\d+", "", value).replace(" -> ", ">")


# ----------------------------------------------------------------------- layered topology

# Tiers order the drawing only. A component's tier is read from what the IR already records
# about it (its kind, role and declaring path); no component or relationship is ever added.
TIER_ORDER = ("client", "api", "service", "platform")
TIER_NAMES = {
    "client": ("CLIENT", "FRONTEND"),
    "api": ("API", "ROUTES"),
    "service": ("CORE", "SERVICES"),
    "platform": ("ML/WORKERS", "DATA & EXT"),
}
TIER_COLORS: dict[str, Color] = {
    "client": (96, 165, 250),
    "api": ACCENT,
    "service": (167, 139, 250),
    "platform": (244, 114, 182),
}
BADGE_COLORS: dict[str, Color] = {
    "UI": (96, 165, 250),
    "API": ACCENT,
    "SVC": (167, 139, 250),
    "ML": (244, 114, 182),
    "DATA": WARN,
    "EXT": (148, 163, 184),
}
EXTERNAL_KINDS = {"database", "cache", "object_storage", "message_broker", "http_client"}
DATA_KINDS = {"database", "cache", "object_storage"}
ML_KINDS = {"module", "part", "tensor"}
ML_ROLES = {
    "generator",
    "discriminator",
    "model",
    "loss",
    "loss_d",
    "loss_g",
    "optimizer",
    "opt_d",
    "opt_g",
    "noise",
    "condition",
    "real",
    "generated",
    "prediction",
}
UI_PARTS = {"frontend", "client", "web", "ui", "components", "pages", "hooks", "views_ui", "e2e"}
UI_SUFFIXES = (".tsx", ".jsx", ".vue", ".svelte", ".html", ".css")
API_PARTS = {
    "api",
    "apis",
    "routes",
    "routers",
    "router",
    "controllers",
    "handlers",
    "endpoints",
    "server",
    "http",
    "graphql",
    "rest",
    "views",
}
API_STEMS = {"main", "app", "server", "urls", "routes", "router", "wsgi", "asgi"}
ML_PARTS = {"ml", "models", "model", "training", "train", "inference", "nn", "networks", "gan"}
WORKER_PARTS = {"workers", "worker", "tasks", "jobs", "queue", "celery", "pipelines"}
DATA_PARTS = {
    "db",
    "database",
    "storage",
    "migrations",
    "repositories",
    "repository",
    "persistence",
    "data",
    "datasets",
    "store",
}
# Card sizes, largest first: a view uses the largest that fits, so a small view is not lost in
# empty space and a large one still fits.
CARD_SIZES = (
    (236, 62),
    (236, 54),
    (214, 62),
    (214, 54),
    (196, 54),
    (236, 46),
    (214, 46),
    (196, 46),
    (176, 46),
    (158, 46),
    (140, 46),
)
CARD_H, GAP, PAD, HEAD, BAND_GAP = 46, 10, 8, 20, 8
AREA_TOP, AREA_BOTTOM, CONTENT_X, CONTENT_W = 126, 540, 182, 1052
Band = tuple[str, Box]


def classify(component: Component) -> tuple[str, str]:
    """(tier, role badge) from the IR's own kind, role and declaring path."""
    cited = component.citations[0].path.lower()
    path = f"{component.group.lower()}/{cited}"
    parts = set(re.split(r"[/\\]", path))
    stem = cited.rsplit("/", 1)[-1].split(".")[0]
    if component.group == "external" or component.kind in EXTERNAL_KINDS:
        return "platform", "DATA" if component.kind in DATA_KINDS else "EXT"
    if component.kind in ML_KINDS or component.role in ML_ROLES or parts & ML_PARTS:
        return "platform", "ML"
    if parts & DATA_PARTS:
        return "platform", "DATA"
    if parts & WORKER_PARTS:
        return "platform", "SVC"
    if (
        component.kind in {"endpoint", "handler", "application", "service"}
        or component.role == "application"
        or parts & API_PARTS
        or (stem in API_STEMS and cited.endswith(".py"))
    ):
        return "api", "API"
    if cited.endswith(UI_SUFFIXES) or parts & UI_PARTS:
        return "client", "UI"
    return "service", "SVC"


def tiered(
    components: list[Component], connections: list[Connection]
) -> tuple[dict[str, Box], list[Lane], list[Band]] | None:
    """Tier bands top to bottom, one container per boundary, cards in flow order inside.

    None when the view does not fit; the caller then uses `automatic`, which the IR's own
    drawability check already guarantees.
    """
    level = layers(components, connections)
    index = {c.id: i for i, c in enumerate(components)}
    tier = {c.id: classify(c)[0] for c in components}
    present = [t for t in TIER_ORDER if any(tier[c.id] == t for c in components)]
    groups = {
        t: list(dict.fromkeys(c.group for c in components if tier[c.id] == t)) for t in present
    }
    for card_w, card_h in CARD_SIZES:
        plans: list[tuple[str, int, list[tuple[str, list[Component], int]], int]] = []
        for t in present:
            for rows in range(1, 8):
                packed = []
                width = 0
                for group in groups[t]:
                    members = sorted(
                        (c for c in components if tier[c.id] == t and c.group == group),
                        key=lambda c: (level[c.id], index[c.id]),
                    )
                    cols = -(-len(members) // rows)
                    box_w = cols * card_w + (cols - 1) * GAP + 2 * PAD
                    packed.append((group, members, cols))
                    width += box_w
                width += (len(packed) - 1) * GAP
                if width <= CONTENT_W:
                    plans.append((t, rows, packed, width))
                    break
            else:
                break
        if len(plans) != len(present):
            continue
        heights = [HEAD + rows * (card_h + GAP) - GAP + 2 * PAD for _, rows, _, _ in plans]
        total = sum(heights) + BAND_GAP * (len(plans) - 1)
        if total > AREA_BOTTOM - AREA_TOP:
            continue
        boxes: dict[str, Box] = {}
        lanes: list[Lane] = []
        bands: list[Band] = []
        y = AREA_TOP + (AREA_BOTTOM - AREA_TOP - total) // 2
        for (t, rows, packed, width), height in zip(plans, heights, strict=True):
            bands.append((t, (40, y, 1200, height)))
            x = CONTENT_X + (CONTENT_W - width) // 2
            for group, members, cols in packed:
                box_w = cols * card_w + (cols - 1) * GAP + 2 * PAD
                lanes.append((group, (x, y + 2, box_w, height - 4)))
                for n, member in enumerate(members):
                    column, row = divmod(n, rows)
                    boxes[member.id] = (
                        x + PAD + column * (card_w + GAP),
                        y + HEAD + PAD + row * (card_h + GAP) - 4,
                        card_w,
                        card_h,
                    )
                x += box_w + GAP
            y += height + BAND_GAP
        return boxes, lanes, bands
    return None


def fit(value: str, width: int, scale: int = 2) -> str:
    """As much of `value` as fits `width` pixels; a cut is shown with an ellipsis."""
    room = max(1, width // (6 * scale))
    value = display(value, 400)
    return value if len(value) <= room else value[: max(1, room - 3)] + "..."


def fit_path(value: str, width: int) -> str:
    """A path that fits, keeping its last segments: .../evaluation/EvaluationDetail.tsx."""
    room = max(4, width // 12)
    if len(value) <= room:
        return value
    parts = value.split("/")
    while len(parts) > 1 and len(".../" + "/".join(parts)) > room:
        parts = parts[1:]
    shortened = ".../" + "/".join(parts)
    return shortened if len(shortened) <= room else fit(value, width)


def pill(canvas: Canvas, x: int, y: int, text: str, fill: Color, ink: Color) -> int:
    """A rounded label; returns its width."""
    width = len(text) * 12 + 14
    canvas.round_rect(x, y, width, 22, 11, fill)
    canvas.text(x + 7, y + 4, text, 2, ink)
    return width


def partial(points: list[Point], fraction: float) -> list[Point]:
    """The polyline from its start to `fraction` of its length."""
    if fraction >= 1:
        return points
    end = along(points, fraction)
    remaining = fraction * length(points)
    found = [points[0]]
    for start, stop in zip(points, points[1:], strict=False):
        span = abs(stop[0] - start[0]) + abs(stop[1] - start[1])
        if remaining <= span:
            break
        found.append(stop)
        remaining -= span
    return [*found, end]


class Diagram:
    """The architecture of one view, laid out in tiers and drawn with its narration state."""

    def __init__(
        self, architecture: Architecture, repository: str, commit_sha: str, view: View | None = None
    ) -> None:
        self.architecture = architecture
        self.header = f"REPOVOX / {repository} @ {commit_sha[:12]}"[:96]
        self.title = view.title if view else architecture.title
        members = set(view.component_ids) if view else {c.id for c in architecture.components}
        wanted = set(view.connection_ids) if view else {c.id for c in architecture.connections}
        self.components = [c for c in architecture.components if c.id in members]
        self.connections = [c for c in architecture.connections if c.id in wanted]
        self.parts = {c.id: c for c in self.components}
        self.links = {c.id: c for c in self.connections}
        self.badges = {c.id: classify(c)[1] for c in self.components}
        table = LAYOUTS.get(architecture.type) if view is None else None
        self.lanes: list[Lane] = []
        self.bands: list[Band] = []
        fixed = table is not None and all(c.id in table for c in self.components)
        if fixed and table is not None:
            self.boxes = {c.id: table[c.id] for c in self.components}
        else:
            found = tiered(self.components, self.connections)
            if found is None:
                self.boxes, self.lanes = automatic(self.components, self.connections)
            else:
                self.boxes, self.lanes, self.bands = found
        self.tier_of = {
            c.id: next(
                (t for t, (_, by, _, bh) in self.bands if by <= self.boxes[c.id][1] < by + bh), ""
            )
            for c in self.components
        }
        counts: dict[str, int] = {}
        self.routes: dict[str, list[Point]] = {}
        for connection in self.connections:
            a, b = self.boxes[connection.source], self.boxes[connection.target]
            lane = counts.get(connection.target, 0)
            hv = (connection.source, connection.target) in HV
            points = route(a, b, hv, lane)
            if not fixed and len(points) == 3:
                # Take whichever elbow crosses fewer other boxes.
                others = [
                    box
                    for key, box in self.boxes.items()
                    if key not in (connection.source, connection.target)
                ]
                other = route(a, b, not hv, lane)
                if crossings(other, others) < crossings(points, others):
                    points = other
            if len(points) == 3:
                counts[connection.target] = lane + 1
            self.routes[connection.id] = points

    # ------------------------------------------------------------------------- drawing

    def color(self, component: Component) -> Color:
        return BADGE_COLORS[self.badges[component.id]]

    def box(self, canvas: Canvas, component: Component, state: str) -> None:
        """One card: role badge, status border (solid VERIFIED, dashed otherwise), label."""
        x, y, w, h = self.boxes[component.id]
        tone = self.color(component)
        dashed = component.status != "VERIFIED"
        if state == "dim":
            fill, edge, ink, soft = mix(CARD, BG, 0.45), mix(tone, BG, 0.7), DIM_TEXT, DIM
        elif state == "active":
            fill, edge, ink, soft = mix(CARD, tone, 0.14), tone, TEXT, MUTED
        else:
            fill, edge, ink, soft = CARD, mix(tone, CARD, 0.15), TEXT, MUTED
        canvas.round_rect(x, y, w, h, 7, fill)
        canvas.ring(x, y, w, h, 7, edge, 3 if state == "active" else 2, dashed=dashed)
        badge = self.badges[component.id]
        if component.kind == "module" and h > 100:
            canvas.text(x + 10, y + 9, fit(component.role.upper(), w - 70), 2, tone)
            canvas.text(x + 10, y + 31, fit(component.label, w - 20), 2, ink)
            for i, line in enumerate(component.lines[: (h - 60) // 21]):
                canvas.text(x + 10, y + 56 + i * 21, fit(short_layer(line), w - 20), 2, soft)
        else:
            canvas.text(
                x + 9, y + 7 + max(0, h - CARD_H) // 3, fit(component.label, w - 18), 2, ink
            )
            detail = component.lines[0] if component.lines else component.role
            detail = ROLE_NAMES.get(detail, detail).replace("latent size", "size").replace("_", " ")
            room = w - 18 - (len(badge) * 12 + 18)
            canvas.text(x + 9, y + h - 20, fit(detail, room), 2, soft)
        plate = mix(tone, BG, 0.6) if state == "dim" else tone
        bw = len(badge) * 12 + 10
        canvas.round_rect(x + w - bw - 6, y + h - 22, bw, 17, 8, plate)
        canvas.text(x + w - bw - 1, y + h - 20, badge, 2, BG)

    def edge(self, canvas: Canvas, connection: Connection, state: str) -> None:
        points = self.routes[connection.id]
        if state == "active":
            color: Color = WARN if connection.kind in FEEDBACK else ACCENT
            width = 5
        else:
            color = mix(MUTED, BG, 0.78 if state == "dim" else 0.55)
            width = 3
        for start, end in zip(points, points[1:], strict=False):
            segment(canvas, start, end, color, width)
        arrowhead(canvas, points[-2], points[-1], color)

    def band(self, canvas: Canvas, tier: str, area: Box, state: str) -> Color:
        x, y, w, h = area
        tone = TIER_COLORS[tier]
        fill = mix(BG, tone, 0.12 if state == "active" else 0.05)
        canvas.round_rect(x, y, w, h, 10, fill)
        canvas.round_rect(x, y + 6, 4, h - 12, 2, tone if state != "dim" else mix(tone, BG, 0.6))
        ink = TEXT if state == "active" else (DIM_TEXT if state == "dim" else MUTED)
        top, bottom = TIER_NAMES[tier]
        middle = y + h // 2
        canvas.text(x + 14, middle - 17, top, 2, tone if state != "dim" else ink)
        canvas.text(x + 14, middle + 3, bottom, 2, ink)
        return fill

    def lane(self, canvas: Canvas, area: Box, tone: Color, state: str) -> None:
        x, y, w, h = area
        canvas.ring(x, y, w, h, 8, tone, 1, 0.55 if state != "dim" else 0.25)

    def lane_label(self, canvas: Canvas, label: str, area: Box, plate: Color, state: str) -> None:
        """Drawn after the relationships, on a plate of the surface it sits on, so a line
        never runs through a boundary name."""
        x, y, w, _ = area
        text = fit_path(label or "(unnamed)", w - 20)
        canvas.rect(x + 8, y - 2, len(text) * 12 + 10, 18, plate)
        canvas.text(x + 13, y, text, 2, MUTED if state != "dim" else DIM_TEXT)

    def strip(
        self,
        canvas: Canvas,
        components: tuple[str, ...],
        connections: tuple[str, ...],
        citation: Citation | None,
        step: tuple[int, int] | None,
    ) -> None:
        """The live step bar, or the spotlight callout, between the title and the diagram."""
        x = 40
        if step is not None and connections:
            link = self.links.get(connections[0])
            x += pill(canvas, x, 96, f"STEP {step[0]} OF {step[1]}", ACCENT, BG) + 10
            if link is not None:
                source = self.parts[link.source].label if link.source in self.parts else ""
                target = self.parts[link.target].label if link.target in self.parts else ""
                canvas.text(x, 100, fit(f"{source} -> {target}", 1240 - 360 - x), 2, TEXT)
        elif components and not connections and len(components) <= 3:
            first = self.parts.get(components[0])
            if first is not None:
                badge = self.badges[first.id]
                x += pill(canvas, x, 96, badge, BADGE_COLORS[badge], BG) + 10
                kind = first.kind.replace("_", " ")
                canvas.text(x, 100, fit(f"{first.label} - {kind}", 1240 - 360 - x), 2, TEXT)
        if citation is not None:
            where = fit_path(f"{citation.path}:{citation.line}", 330)
            width = len(where) * 12 + 14
            canvas.round_rect(1240 - width, 96, width, 22, 11, CARD)
            canvas.text(1240 - width + 7, 100, where, 2, MUTED)

    def base(
        self,
        components: tuple[str, ...],
        connections: tuple[str, ...],
        badge: str,
        caption: str,
        citation: Citation | None,
        position: int,
        total: int,
        *,
        step: tuple[int, int] | None = None,
        pending: bool = False,
        glow: float = 1.0,
        reveal: int | None = None,
    ) -> Canvas:
        """One narrated frame. `pending` leaves the active relationships to `animate`, `glow`
        is the spotlight strength, and `reveal` shows only the first that many tiers."""
        canvas = Canvas()
        canvas.rect(0, 0, WIDTH, 6, ACCENT)
        canvas.text(40, 22, self.header, 2, ACCENT)
        canvas.text(40, 48, fit(self.title, 1200, 3), 3)
        canvas.rect(40, 84, 1200, 2, mix(MUTED, BG, 0.5))
        lit = set(components) | {
            end for c in connections if c in self.links for end in self.ends(c)
        }
        if lit >= set(self.parts):
            lit = set()  # The whole view is narrated: nothing is dimmed or spotlit.
        hidden: set[str] = set()
        if reveal is not None and self.bands:
            shown = {t for t, _ in self.bands[:reveal]}
            hidden = {c.id for c in self.components if self.tier_of[c.id] not in shown}
        active_tiers = {self.tier_of[c] for c in lit if c in self.tier_of}
        fills: dict[str, Color] = {}
        for tier, area in self.bands:
            if any(self.tier_of[c.id] == tier and c.id not in hidden for c in self.components):
                state = "active" if tier in active_tiers else ("dim" if lit else "normal")
                fills[tier] = self.band(canvas, tier, area, state)
        labels = []
        for label, area in self.lanes:
            inside = [c for c in self.components if c.group == label and c.id not in hidden]
            if not inside and self.bands:
                continue
            tier = self.tier_of[inside[0].id] if inside else ""
            tone = TIER_COLORS.get(tier, MUTED)
            state = "active" if any(c.id in lit for c in inside) else ("dim" if lit else "")
            self.lane(canvas, area, tone, state)
            labels.append((label, area, fills.get(tier, BG), state))
        visible = [c for c in self.connections if not set(self.ends(c.id)) & hidden]
        for connection in visible:
            if connection.id not in connections or pending:
                self.edge(canvas, connection, "dim" if lit else "normal")
        if not pending:
            for connection in visible:
                if connection.id in connections:
                    self.edge(canvas, connection, "active")
        for label, area, plate, state in labels:
            self.lane_label(canvas, label, area, plate, state)
        for component in self.components:
            if component.id in hidden:
                continue
            state = "active" if component.id in lit else ("dim" if lit else "normal")
            self.box(canvas, component, state)
            if component.id in components and component.id in lit and glow > 0:
                canvas.glow(*self.boxes[component.id], 7, self.color(component), glow)
        self.strip(canvas, components, connections, citation, step)
        canvas.rect(0, 548, WIDTH, 116, BAND)
        color = {"VERIFIED": ACCENT, "INFERRED": WARN, "UNRESOLVED": WARN}.get(badge, MUTED)
        canvas.text(40, 556, badge, 2, color)
        for i, text in enumerate(wrap(caption, 100, 3)):
            canvas.text(40, 578 + i * 20, text)
        if citation is not None:
            source = f"{citation.path}:{citation.line}  {citation.quote}"
            canvas.text(40, 642, display(source, 100), 2, MUTED)
        canvas.rect(0, 664, WIDTH, 56, CARD)
        canvas.text(40, 684, "ARCHITECTURE FROM SOURCE EVIDENCE / LOCAL VOICE", 2, ACCENT)
        canvas.ring(700, 684, 22, 16, 4, MUTED, 2)
        canvas.text(730, 684, "VERIFIED", 2, MUTED)
        canvas.ring(850, 684, 22, 16, 4, MUTED, 2, dashed=True)
        canvas.text(880, 684, "INFERRED", 2, MUTED)
        label = f"{position + 1}/{total}"
        canvas.text(WIDTH - 40 - len(label) * 12, 684, label, 2, MUTED)
        return canvas

    def ends(self, connection: str) -> tuple[str, str]:
        link = self.links[connection]
        return link.source, link.target

    def animate(
        self, base: Canvas, connections: tuple[str, ...], phase: float, progress: float = 1.0
    ) -> bytes:
        """One animation frame. Each active relationship is drawn from its source toward its
        target over the first third of the sentence; then a glowing packet travels along it."""
        canvas = base.copy()
        grow = min(1.0, progress / 0.35)
        for identity in connections:
            if identity not in self.routes:
                continue
            link = self.links[identity]
            color: Color = WARN if link.kind in FEEDBACK else ACCENT
            points = self.routes[identity]
            drawn = partial(points, grow)
            for start, end in zip(drawn, drawn[1:], strict=False):
                segment(canvas, start, end, color, 5)
            if grow < 1:
                x, y = drawn[-1]
                canvas.disc(x, y, 7, color, 0.9)
                continue
            arrowhead(canvas, points[-2], points[-1], color)
            for offset in (0.0, 0.5):
                head = (phase + offset) % 1.0
                for n, alpha in ((3, 0.18), (2, 0.3), (1, 0.45)):
                    x, y = along(points, max(0.0, head - 0.025 * n))
                    canvas.disc(x, y, 5, color, alpha)
                x, y = along(points, head)
                canvas.disc(x, y, 12, color, 0.3)
                canvas.disc(x, y, 7, TEXT)
        return canvas.png(1)  # Many frames: favour speed over size.


__all__ = ["HEIGHT", "Diagram", "classify", "tiered"]
