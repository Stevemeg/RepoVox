"""Trusted bitmap layouts for grounded storyboards. No fonts, HTML, templates or plugins.

Repository strings are drawn as pixels only. The 5x7 alphabet is an original project
contribution shared with the offline media experiment, extended for source punctuation.
"""

import struct
import zlib

from repovox.media.storyboard import Scene, Sentence, Storyboard

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
BG = (10, 18, 32)
CARD = (21, 35, 54)
BAND = (15, 26, 42)
TEXT = (230, 239, 249)
MUTED = (150, 174, 200)
ACCENT = (71, 222, 190)
WARN = (240, 190, 90)
Color = tuple[int, int, int]


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
            for yy, row in enumerate(FONT.get(char, UNKNOWN)):
                for xx in range(5):
                    if row & (1 << (4 - xx)):
                        self.rect(
                            x + i * 6 * scale + xx * scale, y + yy * scale, scale, scale, color
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


def base(board: Storyboard, scene: Scene, position: int) -> Canvas:
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
    c.text(64, 684, "STATIC ANALYSIS / CITED SOURCE EVIDENCE / LOCAL SYNTHETIC VOICE", 2, ACCENT)
    label = f"{position + 1}/{len(board.scenes)}"
    c.text(WIDTH - 64 - len(label) * 12, 684, label, 2, MUTED)
    return c


def frame(canvas: Canvas, sentence: Sentence) -> bytes:
    """Caption one sentence onto a copy of its scene; the caption is the narrated text."""
    c = canvas.copy()
    c.rect(0, 548, WIDTH, 116, BAND)
    badge = {"verified": "VERIFIED", "inferred": "INFERRED", "none": "CONTEXT"}[
        sentence.uncertainty
    ]
    color = {"verified": ACCENT, "inferred": WARN, "none": MUTED}[sentence.uncertainty]
    c.text(64, 558, badge, 2, color)
    if sentence.claim_ids:
        cited = f"{len(sentence.claim_ids)} claim(s) / {len(sentence.evidence_ids)} evidence"
        c.text(WIDTH - 64 - len(cited) * 12, 558, cited, 2, MUTED)
    for i, line in enumerate(wrap(sentence.text, 96, 4)):
        c.text(64, 582 + i * 20, line)
    return c.png()
