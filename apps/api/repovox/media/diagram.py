"""Deterministic architecture diagrams drawn only from a validated Architecture IR.

One renderer serves every architecture. Layout is computed from the graph itself: columns
follow the direction of the relationships, rows are grouped into boundary lanes (for example
one lane per source file). A small table of fixed positions exists for two reviewed layouts;
it only places roles and can never add a node or an arrow. A box exists only for an IR
component and a line only for an IR connection.
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


class Diagram:
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
        table = LAYOUTS.get(architecture.type) if view is None else None
        self.lanes: list[Lane] = []
        fixed = table is not None and all(c.id in table for c in self.components)
        if fixed and table is not None:
            self.boxes = {c.id: table[c.id] for c in self.components}
        else:
            self.boxes, self.lanes = automatic(self.components, self.connections)
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

    def box(self, canvas: Canvas, component: Component, active: bool) -> None:
        x, y, w, h = self.boxes[component.id]
        if active:
            canvas.rect(x - 3, y - 3, w + 6, h + 6, ACCENT)
        canvas.rect(x, y, w, h, CARD)
        ink, soft = (TEXT, MUTED) if active else (DIM_TEXT, DIM)
        room = (w - 16) // 12
        if component.kind == "module":
            canvas.text(x + 8, y + 8, component.role.upper()[:room], 2, ACCENT if active else soft)
            canvas.text(x + 8, y + 30, display(component.label, room), 2, ink)
            for i, text in enumerate(component.lines[:6]):
                canvas.text(x + 8, y + 56 + i * 21, display(short_layer(text), room), 2, soft)
            return
        detail = component.lines[0] if component.lines else component.role
        detail = ROLE_NAMES.get(detail, detail).replace("latent size", "size").replace("_", " ")
        canvas.text(x + 8, y + 8, display(component.label, room), 2, ink)
        canvas.text(x + 8, y + 31, display(detail, room), 2, soft)

    def edge(self, canvas: Canvas, connection: Connection, active: bool) -> None:
        color = (WARN if connection.kind in FEEDBACK else ACCENT) if active else DIM
        points = self.routes[connection.id]
        for start, end in zip(points, points[1:], strict=False):
            segment(canvas, start, end, color, 5 if active else 3)
        arrowhead(canvas, points[-2], points[-1], color)

    def base(
        self,
        components: tuple[str, ...],
        connections: tuple[str, ...],
        badge: str,
        caption: str,
        citation: Citation | None,
        position: int,
        total: int,
    ) -> Canvas:
        canvas = Canvas()
        canvas.rect(0, 0, WIDTH, 6, ACCENT)
        canvas.text(40, 26, self.header, 2, ACCENT)
        canvas.text(40, 62, display(self.title, 50), 4)
        canvas.rect(40, 114, 1200, 2, MUTED)
        for label, (x, y, w, h) in self.lanes:
            canvas.rect(x, y, w, h, LANE)
            canvas.rect(x + 2, y + 2, w - 4, h - 4, BG)
            canvas.text(x + 10, y + 5, display(label or "(unnamed)", 60), 2, DIM_TEXT)
        for connection in self.connections:
            if connection.id not in connections:
                self.edge(canvas, connection, False)
        for connection in self.connections:
            if connection.id in connections:
                self.edge(canvas, connection, True)
        for component in self.components:
            self.box(canvas, component, component.id in components)
        canvas.rect(0, 548, WIDTH, 116, BAND)
        color = {"VERIFIED": ACCENT, "INFERRED": WARN, "UNRESOLVED": WARN}.get(badge, MUTED)
        canvas.text(40, 556, badge, 2, color)
        for i, text in enumerate(wrap(caption, 100, 3)):
            canvas.text(40, 578 + i * 20, text)
        if citation is not None:
            source = f"{citation.path}:{citation.line}  {citation.quote}"
            canvas.text(40, 642, display(source, 100), 2, MUTED)
        canvas.rect(0, 664, WIDTH, 56, CARD)
        canvas.text(40, 684, "STATIC ARCHITECTURE FROM SOURCE EVIDENCE / LOCAL VOICE", 2, ACCENT)
        label = f"{position + 1}/{total}"
        canvas.text(WIDTH - 40 - len(label) * 12, 684, label, 2, MUTED)
        return canvas

    def animate(self, base: Canvas, connections: tuple[str, ...], phase: float) -> bytes:
        """One animation frame: a pulse travelling along every active connection."""
        canvas = base.copy()
        for identity in connections:
            points = self.routes[identity]
            for offset in (0.0, 0.5):
                x, y = along(points, (phase + offset) % 1.0)
                canvas.rect(max(0, x - 7), max(0, y - 7), 14, 14, BG)
                canvas.rect(max(0, x - 5), max(0, y - 5), 10, 10, TEXT)
        return canvas.png(1)  # Many frames: favour speed over size.


__all__ = ["HEIGHT", "Diagram"]
