"""Trusted bitmap layouts for grounded storyboards. No fonts, HTML, templates or plugins.

Repository strings are drawn as pixels only. The 5x7 alphabet is an original project
contribution shared with the offline media experiment, extended for source punctuation. At even
scales each glyph is smoothed with the EPX (Scale2x) rule, so diagonal strokes step by one
pixel instead of by a whole cell. Rounded cards, rings and discs are anti-aliased by pixel
coverage. Everything is integer arithmetic on one RGB buffer: deterministic on every host.
"""

import math
import struct
import zlib
from functools import lru_cache

from repovox.media.storyboard import Scene, Sentence, Storyboard, display

WIDTH, HEIGHT = 1280, 720

# Original 5x7 glyph patterns, authored for this experiment; no extracted font.
FONT = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        [
            (14, 17, 17, 31, 17, 17, 17),
            (30, 17, 17, 30, 17, 17, 30),
            (14, 17, 16, 16, 16, 17, 14),
            (30, 17, 17, 17, 17, 17, 30),
            (31, 16, 16, 30, 16, 16, 31),
            (31, 16, 16, 30, 16, 16, 16),
            (14, 17, 16, 23, 17, 17, 15),
            (17, 17, 17, 31, 17, 17, 17),
            (14, 4, 4, 4, 4, 4, 14),
            (7, 2, 2, 2, 2, 18, 12),
            (17, 18, 20, 24, 20, 18, 17),
            (16, 16, 16, 16, 16, 16, 31),
            (17, 27, 21, 21, 17, 17, 17),
            (17, 25, 21, 19, 17, 17, 17),
            (14, 17, 17, 17, 17, 17, 14),
            (30, 17, 17, 30, 16, 16, 16),
            (14, 17, 17, 17, 21, 18, 13),
            (30, 17, 17, 30, 20, 18, 17),
            (15, 16, 16, 14, 1, 1, 30),
            (31, 4, 4, 4, 4, 4, 4),
            (17, 17, 17, 17, 17, 17, 14),
            (17, 17, 17, 17, 17, 10, 4),
            (17, 17, 17, 21, 21, 21, 10),
            (17, 17, 10, 4, 10, 17, 17),
            (17, 17, 10, 4, 4, 4, 4),
            (31, 1, 2, 4, 8, 16, 31),
        ],
        strict=True,
    )
)
FONT.update(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        [
            (0, 0, 14, 1, 15, 17, 15),
            (16, 16, 30, 17, 17, 17, 30),
            (0, 0, 14, 17, 16, 17, 14),
            (1, 1, 15, 17, 17, 17, 15),
            (0, 0, 14, 17, 31, 16, 14),
            (6, 8, 8, 28, 8, 8, 8),
            (0, 15, 17, 15, 1, 17, 14),
            (16, 16, 30, 17, 17, 17, 17),
            (4, 0, 12, 4, 4, 4, 14),
            (2, 0, 6, 2, 2, 18, 12),
            (16, 16, 18, 20, 24, 20, 18),
            (12, 4, 4, 4, 4, 4, 14),
            (0, 0, 26, 21, 21, 21, 21),
            (0, 0, 30, 17, 17, 17, 17),
            (0, 0, 14, 17, 17, 17, 14),
            (0, 30, 17, 30, 16, 16, 16),
            (0, 15, 17, 15, 1, 1, 1),
            (0, 0, 22, 25, 16, 16, 16),
            (0, 0, 15, 16, 14, 1, 30),
            (8, 8, 28, 8, 8, 9, 6),
            (0, 0, 17, 17, 17, 19, 13),
            (0, 0, 17, 17, 17, 10, 4),
            (0, 0, 17, 17, 21, 21, 10),
            (0, 0, 17, 10, 4, 10, 17),
            (0, 17, 17, 15, 1, 17, 14),
            (0, 0, 31, 2, 4, 8, 31),
        ],
        strict=True,
    )
)
FONT.update(
    zip(
        "0123456789",
        [
            (14, 17, 19, 21, 25, 17, 14),
            (4, 12, 4, 4, 4, 4, 14),
            (14, 17, 1, 2, 4, 8, 31),
            (30, 1, 1, 14, 1, 1, 30),
            (2, 6, 10, 18, 31, 2, 2),
            (31, 16, 16, 30, 1, 1, 30),
            (14, 16, 16, 30, 17, 17, 14),
            (31, 1, 2, 4, 8, 8, 8),
            (14, 17, 17, 14, 17, 17, 14),
            (14, 17, 17, 15, 1, 1, 14),
        ],
        strict=True,
    )
)
FONT.update(
    {
        " ": (0,) * 7,
        ".": (0, 0, 0, 0, 0, 12, 12),
        ",": (0, 0, 0, 0, 4, 4, 8),
        ":": (0, 4, 4, 0, 4, 4, 0),
        ";": (0, 4, 4, 0, 4, 4, 8),
        "-": (0, 0, 0, 31, 0, 0, 0),
        "_": (0, 0, 0, 0, 0, 0, 31),
        "/": (1, 2, 2, 4, 8, 8, 16),
        "=": (0, 0, 31, 0, 31, 0, 0),
        "+": (0, 4, 4, 31, 4, 4, 0),
        "*": (0, 21, 14, 31, 14, 21, 0),
        "(": (2, 4, 8, 8, 8, 4, 2),
        ")": (8, 4, 2, 2, 2, 4, 8),
        "{": (2, 4, 4, 8, 4, 4, 2),
        "}": (8, 4, 4, 2, 4, 4, 8),
        "[": (14, 8, 8, 8, 8, 8, 14),
        "]": (14, 2, 2, 2, 2, 2, 14),
        "'": (4, 4, 8, 0, 0, 0, 0),
        '"': (10, 10, 0, 0, 0, 0, 0),
        "!": (4, 4, 4, 4, 4, 0, 4),
        "?": (14, 17, 1, 2, 4, 0, 4),
        "#": (10, 10, 31, 10, 31, 10, 10),
        "|": (4, 4, 4, 4, 4, 4, 4),
        ">": (16, 8, 4, 2, 4, 8, 16),
        "<": (1, 2, 4, 8, 4, 2, 1),
    }
)

FONT.update(
    {
        "@": (14, 17, 23, 21, 23, 16, 14),
        "%": (24, 25, 2, 4, 8, 19, 3),
        "&": (12, 18, 20, 8, 21, 18, 13),
        "^": (4, 10, 17, 0, 0, 0, 0),
        "~": (0, 0, 8, 21, 2, 0, 0),
        "\\": (16, 8, 8, 4, 2, 2, 1),
        "$": (4, 15, 20, 14, 5, 30, 4),
        "`": (8, 4, 2, 0, 0, 0, 0),
    }
)
# Production legibility: descender letters sit on the same x-height as the rest.
FONT.update(
    {
        "g": (0, 0, 15, 17, 15, 1, 14),
        "p": (0, 0, 30, 17, 30, 16, 16),
        "q": (0, 0, 15, 17, 15, 1, 1),
        "y": (0, 0, 17, 17, 15, 1, 14),
    }
)
UNKNOWN = (31, 17, 17, 17, 17, 17, 31)
Box = tuple[int, int, int, int]


def epx(grid: list[list[bool]]) -> list[list[bool]]:
    """Scale2x: each cell becomes four, filling the inside corner of a diagonal stroke."""
    rows, cols = len(grid), len(grid[0])

    def at(r: int, c: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols and grid[r][c]

    out = [[False] * (cols * 2) for _ in range(rows * 2)]
    for r in range(rows):
        for c in range(cols):
            p = grid[r][c]
            a, b, cc, d = at(r - 1, c), at(r, c + 1), at(r, c - 1), at(r + 1, c)
            out[2 * r][2 * c] = cc if (cc == a and cc != d and a != b) else p
            out[2 * r][2 * c + 1] = b if (a == b and a != cc and b != d) else p
            out[2 * r + 1][2 * c] = cc if (d == cc and d != b and cc != a) else p
            out[2 * r + 1][2 * c + 1] = d if (b == d and b != a and d != cc) else p
    return out


@lru_cache(maxsize=512)
def blend_tables(color: tuple[int, int, int], level: int) -> tuple[bytes, bytes, bytes]:
    """old byte -> byte mixed toward `color` by level/255, per channel."""
    return tuple(  # type: ignore[return-value]
        bytes(round(v + (target - v) * level / 255) for v in range(256)) for target in color
    )


@lru_cache(maxsize=2048)
def glyph(char: str, scale: int) -> tuple[Box, ...]:
    """Horizontal runs that draw one character at `scale`, smoothed at even scales."""
    bits = FONT.get(char, UNKNOWN)
    grid = [[bool(row & (1 << (4 - c))) for c in range(5)] for row in bits]
    unit = scale
    if scale >= 2 and scale % 2 == 0:
        grid, unit = epx(grid), scale // 2
    runs: list[Box] = []
    for r, row in enumerate(grid):
        c = 0
        while c < len(row):
            if not row[c]:
                c += 1
                continue
            start = c
            while c < len(row) and row[c]:
                c += 1
            runs.append((start * unit, r * unit, (c - start) * unit, unit))
    return tuple(runs)


BG = (10, 18, 32)
CARD = (21, 35, 54)
BAND = (15, 26, 42)
TEXT = (230, 239, 249)
MUTED = (150, 174, 200)
ACCENT = (71, 222, 190)
WARN = (240, 190, 90)
Color = tuple[int, int, int]


def mix(a: Color, b: Color, t: float) -> Color:
    """`a` moved toward `b` by `t` (0..1)."""
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


class LayoutError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Canvas:
    def __init__(self, pixels: bytearray | None = None) -> None:
        self.pixels = pixels if pixels is not None else bytearray(bytes(BG) * (WIDTH * HEIGHT))

    def copy(self) -> "Canvas":
        return Canvas(bytearray(self.pixels))

    def rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        if not (0 <= x < x + w <= WIDTH and 0 <= y < y + h <= HEIGHT):
            raise LayoutError("visual_overflow")
        row = bytes(color) * w
        for yy in range(y, y + h):
            start = (yy * WIDTH + x) * 3
            self.pixels[start : start + w * 3] = row

    def text(self, x: int, y: int, value: str, scale: int = 2, color: Color = TEXT) -> None:
        if not value:
            return
        if "\n" in value or x < 0 or x + len(value) * 6 * scale > WIDTH or y + 7 * scale > HEIGHT:
            raise LayoutError("visual_overflow")  # Never clip silently.
        for i, char in enumerate(value):
            left = x + i * 6 * scale
            for dx, dy, w, h in glyph(char, scale):
                self.rect(left + dx, y + dy, w, h, color)

    # ------------------------------------------------------------------ anti-aliased shapes

    def blend(self, x: int, y: int, color: Color, alpha: float) -> None:
        """One pixel mixed toward `color`; a pixel outside the frame is skipped."""
        if alpha <= 0 or not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            return
        i = (y * WIDTH + x) * 3
        if alpha >= 1:
            self.pixels[i : i + 3] = bytes(color)
            return
        p = self.pixels
        p[i] = round(p[i] + (color[0] - p[i]) * alpha)
        p[i + 1] = round(p[i + 1] + (color[1] - p[i + 1]) * alpha)
        p[i + 2] = round(p[i + 2] + (color[2] - p[i + 2]) * alpha)

    def blend_rect(self, x: int, y: int, w: int, h: int, color: Color, alpha: float) -> None:
        """A translucent rectangle, clipped to the frame. One lookup table per channel."""
        left, right = max(0, x), min(WIDTH, x + w)
        top, bottom = max(0, y), min(HEIGHT, y + h)
        level = round(max(0.0, min(1.0, alpha)) * 255)
        if left >= right or top >= bottom or level == 0:
            return
        tables = blend_tables(color, level)
        pixels = self.pixels
        for row in range(top, bottom):
            start, end = (row * WIDTH + left) * 3, (row * WIDTH + right) * 3
            for channel in range(3):
                part = slice(start + channel, end, 3)
                pixels[part] = pixels[part].translate(tables[channel])

    def corner(
        self, cx: float, cy: float, r: float, inner: float, box: Box, color: Color, alpha: float
    ) -> None:
        """Coverage of the ring between radii `inner` and `r` around (cx, cy), inside `box`."""
        left, top, w, h = box
        for yy in range(top, top + h):
            for xx in range(left, left + w):
                d = math.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
                cover = min(1.0, max(0.0, r - d + 0.5)) - min(1.0, max(0.0, inner - d + 0.5))
                if cover > 0:
                    self.blend(xx, yy, color, cover * alpha)

    def round_rect(self, x: int, y: int, w: int, h: int, r: int, color: Color) -> None:
        """A filled rectangle with anti-aliased rounded corners."""
        r = max(0, min(r, w // 2, h // 2))
        if w - 2 * r > 0:
            self.rect(x + r, y, w - 2 * r, h, color)
        if r:
            if h - 2 * r > 0:
                self.rect(x, y + r, r, h - 2 * r, color)
                self.rect(x + w - r, y + r, r, h - 2 * r, color)
            for cx, cy, box in self.corners(x, y, w, h, r):
                self.corner(cx, cy, r, -1, box, color, 1.0)

    @staticmethod
    def corners(x: int, y: int, w: int, h: int, r: int) -> list[tuple[float, float, Box]]:
        return [
            (x + r, y + r, (x, y, r, r)),
            (x + w - r, y + r, (x + w - r, y, r, r)),
            (x + r, y + h - r, (x, y + h - r, r, r)),
            (x + w - r, y + h - r, (x + w - r, y + h - r, r, r)),
        ]

    def ring(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        r: int,
        color: Color,
        width: int = 2,
        alpha: float = 1.0,
        dashed: bool = False,
    ) -> None:
        """A rounded outline `width` pixels thick, solid or dashed, anti-aliased corners."""
        r = max(width, min(r, w // 2, h // 2))
        for start, stop, fixed, horizontal in (
            (x + r, x + w - r, y, True),
            (x + r, x + w - r, y + h - width, True),
            (y + r, y + h - r, x, False),
            (y + r, y + h - r, x + w - width, False),
        ):
            step = 0
            for a in range(start, stop, 13 if dashed else max(1, stop - start)):
                b = min(stop, a + (8 if dashed else stop - start))
                if b <= a:
                    continue
                if horizontal:
                    box = (a, fixed, b - a, width)
                else:
                    box = (fixed, a, width, b - a)
                if alpha >= 1:
                    self.rect(*box, color)
                else:
                    self.blend_rect(*box, color, alpha)
                step += 1
        for cx, cy, box in self.corners(x, y, w, h, r):
            self.corner(cx, cy, r, r - width, box, color, alpha)

    def disc(self, cx: float, cy: float, r: float, color: Color, alpha: float = 1.0) -> None:
        left, top = math.floor(cx - r - 1), math.floor(cy - r - 1)
        size = math.ceil(2 * r + 3)
        self.corner(cx, cy, r, -1, (left, top, size, size), color, alpha)

    def glow(self, x: int, y: int, w: int, h: int, r: int, color: Color, strength: float) -> None:
        """A soft halo around a card: rings fading outward."""
        for n, alpha in enumerate((0.55, 0.32, 0.18, 0.08)):
            gap = 2 + 2 * n
            self.ring(
                x - gap, y - gap, w + 2 * gap, h + 2 * gap, r + gap, color, 2, alpha * strength
            )

    def arrow(self, x: int, y: int, w: int) -> None:
        self.rect(x, y, w, 3, ACCENT)
        for n in range(8):
            self.rect(x + w - n - 1, y - n, 2, 2, ACCENT)
            self.rect(x + w - n - 1, y + n, 2, 2, ACCENT)

    def png(self, level: int = 6) -> bytes:
        def chunk(kind: bytes, body: bytes) -> bytes:
            return (
                struct.pack(">I", len(body))
                + kind
                + body
                + struct.pack(">I", zlib.crc32(kind + body))
            )

        stride = WIDTH * 3
        raw = b"".join(b"\0" + self.pixels[y * stride : (y + 1) * stride] for y in range(HEIGHT))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, level))
            + chunk(b"IEND", b"")
        )


def wrap(value: str, width: int, lines: int) -> list[str]:
    result: list[str] = []
    current = ""
    for word in value.split(" "):
        while len(word) > width:
            if current:
                result.append(current)
                current = ""
            result.append(word[:width])
            word = word[width:]
        if len(current) + len(word) + bool(current) > width:
            result.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        result.append(current)
    if len(result) > lines:
        raise LayoutError("caption_overflow")
    return result


def clamp(value: str, width: int, lines: int) -> list[str]:
    """`value` wrapped to at most `lines` lines of `width` characters; a cut ends in "..."."""
    words = display(value, 4000).split()
    result: list[str] = []
    current = ""
    for word in words:
        while len(word) > width:
            if current:
                result.append(current)
                current = ""
            result.append(word[:width])
            word = word[width:]
        if current and len(current) + 1 + len(word) > width:
            result.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        result.append(current)
    if len(result) <= lines:
        return result
    kept = result[:lines]
    last = kept[-1]
    kept[-1] = (last if len(last) <= width - 3 else last[: width - 3].rstrip()) + "..."
    return kept


def tail(value: str, width: int) -> str:
    """A citation that fits `width` characters, keeping its end: .../services/jobs.py:42."""
    value = display(value, 400)
    if len(value) <= width:
        return value
    parts = value.split("/")
    while len(parts) > 1 and len(".../" + "/".join(parts)) > width:
        parts = parts[1:]
    shortened = ".../" + "/".join(parts)
    return shortened if len(shortened) <= width else "..." + value[len(value) - width + 3 :]


# Story scenes whose slide lists what they narrate, each item with its status and citation.
CLAIM_SCENES = frozenset(
    {
        "problem",
        "context",
        "solution",
        "approach",
        "architecture",
        "decisions",
        "results",
        "limitations",
    }
)
STATUS_BADGES: dict[str, tuple[str, Color]] = {
    "verified": ("VERIFIED", ACCENT),
    "inferred": ("INFERRED", WARN),
    "documentation": ("AUTHOR-STATED", WARN),
    "unverified": ("UNVERIFIED", (244, 140, 120)),
    "none": ("CONTEXT", MUTED),
}
CLAIM_TOP, CLAIM_BOTTOM = 146, 536


def claim_items(board: Storyboard, scene: Scene) -> list[tuple[str, str, str]]:
    """(status, citation, text) for each cited sentence of a story scene, in narration order.

    The text is the narrated sentence itself, so the slide shows what is said; the citation is
    the source location of each claim the sentence rests on, as the story records it."""
    if board.story is None:
        return []
    claims = board.story.story.claims()
    items: list[tuple[str, str, str]] = []
    for sentence in scene.sentences:
        if not sentence.claim_ids:
            continue
        located = [
            claims[i].source_location
            for i in sentence.claim_ids
            if i in claims and claims[i].source_location
        ]
        places = list(dict.fromkeys(p for p in located if p))
        citation = places[0] if places else "no source location"
        if len(places) > 1:
            citation = f"{places[0]} +{len(places) - 1} more"
        items.append((sentence.uncertainty, citation, sentence.text))
    return items


def claim_cards(c: Canvas, items: list[tuple[str, str, str]]) -> None:
    """Each item as a card: status badge and citation, then its text wrapped to the card.

    Two text lines per card when four or fewer are shown, otherwise one; anything longer ends
    in an ellipsis, and items that do not fit are counted, never drawn over each other."""
    lines = 2 if len(items) <= 4 else 1
    height = 24 + lines * 20 + 10
    room = (CLAIM_BOTTOM - CLAIM_TOP + 8) // (height + 8)
    shown = items if len(items) <= room else items[: max(1, room - 1)]
    y = CLAIM_TOP
    for status, citation, text in shown:
        word, tone = STATUS_BADGES.get(status, STATUS_BADGES["none"])
        c.round_rect(64, y, 1152, height, 8, CARD)
        c.round_rect(64, y + 6, 4, height - 12, 2, tone)
        badge = len(word) * 12 + 14
        c.round_rect(80, y + 6, badge, 20, 10, tone)
        c.text(87, y + 9, word, 2, BG)
        c.text(80 + badge + 12, y + 9, tail(citation, (1200 - 92 - badge - 12) // 12), 2, MUTED)
        for i, line in enumerate(clamp(text, 94, lines)):
            c.text(80, y + 32 + i * 20, line, 2, TEXT)
        y += height + 8
    if len(shown) < len(items):
        more = f"+{len(items) - len(shown)} more in the narration"
        c.text(80, y + 2, more, 2, MUTED)


VOICE_LABELS = {
    "kokoro_onnx": "KOKORO NEURAL VOICE",
    "deterministic": "LOCAL SYNTHETIC VOICE",
    "local": "LOCAL SYNTHETIC VOICE",
}


def voice_label(provider: str | None) -> str:
    """The footer's name for the voice that spoke, from the Stage 12 voice record's provider.
    An unnamed or unknown provider is the local synthetic voice, as before voices were named."""
    return VOICE_LABELS.get(provider or "", "LOCAL SYNTHETIC VOICE")


def base(board: Storyboard, scene: Scene, position: int, voice: str | None = None) -> Canvas:
    """One scene's slide without its caption. `voice` is the Stage 12 voice provider."""
    c = Canvas()
    c.rect(0, 0, WIDTH, 6, ACCENT)
    header = f"REPOVOX / {board.repository} @ {board.commit_sha[:12]}"
    c.text(64, 30, header[:96], 2, ACCENT)
    c.text(64, 70, scene.title, 4)
    c.rect(64, 122, 1152, 2, MUTED)
    y = 146
    if scene.excerpt is not None:
        excerpt = scene.excerpt
        suffix = " (excerpt)" if excerpt.truncated else ""
        c.text(64, y, f"{excerpt.path}  lines {excerpt.start_line}-{excerpt.end_line}{suffix}"[:96])
        c.rect(64, y + 26, 1152, len(excerpt.lines) * 24 + 20, CARD)
        for i, line in enumerate(excerpt.lines):
            number = f"{excerpt.start_line + i:>4}  "
            c.text(80, y + 38 + i * 24, number, 2, MUTED)
            c.text(80 + len(number) * 12, y + 38 + i * 24, line.rstrip())
        c.text(64, y + 56 + len(excerpt.lines) * 24, "SHA256 " + excerpt.file_sha256, 2, MUTED)
    elif board.story is not None and scene.type in CLAIM_SCENES and claim_items(board, scene):
        claim_cards(c, claim_items(board, scene))
    else:
        for row in scene.rows:
            c.text(64, y + 6, row.label, 2, MUTED)
            c.text(
                560,
                y if len(row.value) <= 37 else y + 6,
                row.value,
                3 if len(row.value) <= 37 else 2,
            )
            y += 44
        y += 8
        for link in scene.links:
            c.rect(64, y, 360, 40, CARD)
            c.text(76, y + 13, link.source)
            c.arrow(440, y + 19, 120)
            c.rect(576, y, 360, 40, CARD)
            c.text(588, y + 13, link.target, 2, ACCENT)
            c.text(64, y + 48, link.label, 2, MUTED)
            y += 76
    c.rect(0, 664, WIDTH, 56, CARD)
    footer = (
        "ENGINEERING STORY / CITED EVIDENCE / "
        if board.story is not None
        else "STATIC ANALYSIS / CITED SOURCE EVIDENCE / "
    ) + voice_label(voice)
    c.text(64, 684, footer, 2, ACCENT)
    label = f"{position + 1}/{len(board.scenes)}"
    c.text(WIDTH - 64 - len(label) * 12, 684, label, 2, MUTED)
    return c


def frame(canvas: Canvas, sentence: Sentence) -> bytes:
    """Caption one sentence onto a copy of its scene; the caption is the narrated text."""
    c = canvas.copy()
    c.rect(0, 548, WIDTH, 116, BAND)
    badge = {
        "verified": "VERIFIED",
        "inferred": "INFERRED",
        "none": "CONTEXT",
        "documentation": "AUTHOR-STATED / NOT VERIFIED BY CODE",
        "unverified": "UNVERIFIED",
    }[sentence.uncertainty]
    color = {
        "verified": ACCENT,
        "inferred": WARN,
        "none": MUTED,
        "documentation": WARN,
        "unverified": WARN,
    }[sentence.uncertainty]
    c.text(64, 558, badge, 2, color)
    if sentence.claim_ids:
        cited = f"{len(sentence.claim_ids)} claim(s) / {len(sentence.evidence_ids)} evidence"
        c.text(WIDTH - 64 - len(cited) * 12, 558, cited, 2, MUTED)
    for i, line in enumerate(wrap(sentence.text, 96, 4)):
        c.text(64, 582 + i * 20, line)
    return c.png()
