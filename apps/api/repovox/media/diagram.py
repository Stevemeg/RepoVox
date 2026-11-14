"""Deterministic architecture diagrams drawn only from a validated Architecture IR.

Layout tables decide where a role is placed; they never add a node or an arrow. A box exists
only for an IR component and a line only for an IR connection.
"""

import re

from repovox.media.architecture import Architecture, Citation, Component, Connection
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
DIM: Color = (58, 78, 104)
DIM_TEXT: Color = (120, 140, 165)
ROLE_NAMES = {
    "noise": "noise",
    "condition": "condition",
    "real": "real batch",
    "generated": "generated",
    "input": "input batch",
    "prediction": "prediction",
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
    "http_service": {"application": (80, 290, 240, 56)},
}
# Horizontal-then-vertical where the default vertical-then-horizontal route would cross a box.
HV = {("optimizer", "model")}


def boxes(architecture: Architecture) -> dict[str, Box]:
    table = LAYOUTS[architecture.type]
    placed: dict[str, Box] = {}
    spare = 0
    for component in architecture.components:
        if component.id in table:
            placed[component.id] = table[component.id]
        else:
            if spare >= 5:
                raise LayoutError("diagram_overflow")
            placed[component.id] = (520, 150 + spare * 76, 360, 56)
            spare += 1
    return placed


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
    def __init__(self, architecture: Architecture, repository: str, commit_sha: str) -> None:
        self.architecture = architecture
        self.header = f"REPOVOX / {repository} @ {commit_sha[:12]}"[:96]
        self.boxes = boxes(architecture)
        lanes: dict[str, int] = {}
        self.routes: dict[str, list[Point]] = {}
        for connection in architecture.connections:
            a, b = self.boxes[connection.source], self.boxes[connection.target]
            lane = lanes.get(connection.target, 0)
            points = route(a, b, (connection.source, connection.target) in HV, lane)
            if len(points) == 3:
                lanes[connection.target] = lane + 1
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
        detail = (
            component.lines[0]
            if component.lines
            else ROLE_NAMES.get(component.role, component.role)
        )
        canvas.text(x + 8, y + 8, display(component.label, room), 2, ink)
        canvas.text(x + 8, y + 31, display(detail.replace("latent size", "size"), room), 2, soft)

    def edge(self, canvas: Canvas, connection: Connection, active: bool) -> None:
        feedback = connection.kind in {"gradient", "update"}
        color = (WARN if feedback else ACCENT) if active else DIM
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
        canvas.text(40, 62, display(self.architecture.title, 50), 4)
        canvas.rect(40, 114, 1200, 2, MUTED)
        for connection in self.architecture.connections:
            if connection.id not in connections:
                self.edge(canvas, connection, False)
        for connection in self.architecture.connections:
            if connection.id in connections:
                self.edge(canvas, connection, True)
        for component in self.architecture.components:
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
        canvas.text(40, 684, "ARCHITECTURE FROM SOURCE EVIDENCE / LOCAL SYNTHETIC VOICE", 2, ACCENT)
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
