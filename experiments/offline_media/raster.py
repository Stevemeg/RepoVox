"""Original small bitmap alphabet and trusted layouts; no fonts, HTML or plugins."""

import struct
import zlib

from .contracts import Grounding, Scene, require

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
BG = (10, 18, 32)
CARD = (21, 35, 54)
TEXT = (230, 239, 249)
MUTED = (150, 174, 200)
ACCENT = (71, 222, 190)


class Canvas:
    def __init__(self) -> None:
        self.pixels = bytearray(bytes(BG) * (1280 * 720))

    def rect(self, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        require(0 <= x < x + w <= 1280 and 0 <= y < y + h <= 720, "visual_overflow")
        row = bytes(color) * w
        for yy in range(y, y + h):
            start = (yy * 1280 + x) * 3
            self.pixels[start : start + w * 3] = row

    def text(
        self,
        x: int,
        y: int,
        value: str,
        scale: int = 3,
        color: tuple[int, int, int] = TEXT,
        width: int = 1152,
    ) -> None:
        require(1 <= scale <= 5 and value and "\n" not in value, "unsafe_visual_text")
        require(all(c in FONT for c in value), "unsafe_visual_text")
        require(len(value) * 6 * scale - scale <= width, "visual_overflow")
        require(
            0 <= x and x + len(value) * 6 * scale <= 1280 and 0 <= y <= 720 - 7 * scale,
            "visual_overflow",
        )
        for i, char in enumerate(value):
            for yy, row in enumerate(FONT[char]):
                for xx in range(5):
                    if row & (1 << (4 - xx)):
                        self.rect(
                            x + i * 6 * scale + xx * scale, y + yy * scale, scale, scale, color
                        )

    def arrow(self, x: int, y: int, w: int) -> None:
        self.rect(x, y, w, 3, ACCENT)
        for n in range(10):
            self.rect(x + w - n - 1, y - n, 2, 2, ACCENT)
            self.rect(x + w - n - 1, y + n, 2, 2, ACCENT)

    def png(self) -> bytes:
        def chunk(kind: bytes, body: bytes) -> bytes:
            return (
                struct.pack(">I", len(body))
                + kind
                + body
                + struct.pack(">I", zlib.crc32(kind + body))
            )

        raw = b"".join(b"\0" + self.pixels[y * 3840 : (y + 1) * 3840] for y in range(720))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1280, 720, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )


def render(scene: Scene, g: Grounding, sources: dict[str, bytes]) -> bytes:
    c = Canvas()
    c.rect(0, 0, 1280, 6, ACCENT)
    c.text(64, 32, "REPOVOX / OFFLINE FICTIONAL FIXTURE", 2, ACCENT)
    c.text(64, 86, scene.title, 4)
    c.rect(64, 143, 1152, 2, MUTED)
    if scene.kind == "architecture":
        c.text(64, 185, "Independent examples - no cross-language execution claim", 3)
        for i, (path, label) in enumerate(
            zip(sources, ["Python", "JavaScript", "TypeScript"], strict=True)
        ):
            x = 64 + i * 392
            c.rect(x, 258, 368, 200, CARD)
            c.text(x + 24, 286, label, 3, ACCENT, 320)
            c.text(x + 24, 340, path, 3, TEXT, 320)
            c.text(x + 24, 394, "2 declarations", 3, MUTED, 320)
        c.text(64, 525, "Each later assertion binds exact source bytes and lines", 3, MUTED)
    elif scene.kind == "code":
        assert scene.source is not None
        path = scene.source
        facts = [f for f in g.facts if f.id in scene.fact_ids]
        call = next(f for f in facts if f.kind == "static_call")
        c.text(64, 181, path + " / complete fictional source", 3, ACCENT)
        c.rect(64, 223, 1152, 300, CARD)
        for i, line in enumerate(sources[path].decode("ascii").splitlines(), 1):
            y = 248 + (i - 1) * 38
            if i == call.citation.start_line:
                c.rect(76, y - 7, 1128, 35, (28, 67, 70))
            c.text(88, y, f"{i:02d}  {line}", 3)
        citation = call.citation
        c.text(64, 549, f"{call.id}: {call.subject} calls {call.target} syntactically", 2)
        c.text(
            64,
            582,
            f"bytes [{citation.start_byte},{citation.end_byte}) / line {citation.start_line}",
            2,
            MUTED,
        )
        c.text(64, 615, "SHA256 " + citation.sha256, 2, MUTED)
    elif scene.kind == "relationships":
        for i, f in enumerate(f for f in g.facts if f.kind == "static_call"):
            y = 220 + i * 125
            c.rect(64, y, 356, 68, CARD)
            c.text(88, y + 22, f.subject, 3)
            c.arrow(442, y + 33, 170)
            c.rect(640, y, 356, 68, CARD)
            c.text(664, y + 22, f.target or "", 3, ACCENT)
            c.text(
                1020,
                y + 27,
                {"python": "PY", "javascript": "JS", "typescript": "TS"}[f.language],
                3,
                MUTED,
                180,
            )
            c.text(64, y + 84, f"{f.id} / {f.citation.path}:{f.citation.start_line}", 2, MUTED)
        c.text(64, 614, "Static call sites only - no proof a function executed", 3, ACCENT)
    else:
        for i, line in enumerate(
            [
                "3 fictional source units / 9 annotated syntax facts",
                "3 source-bound static call relationships",
                "Deterministic scenes / machine-checked citations",
                "720p / 30fps / synthetic tone / no narration",
                "No AI inference, real source or reviewed gold",
                "Not a product release or roadmap gate acceptance",
            ]
        ):
            c.text(64, 205 + i * 64, line, 3, ACCENT if i == 4 else TEXT)
    c.rect(0, 660, 1280, 60, CARD)
    c.text(64, 681, "SYNTHETIC DEMO / NOT REVIEWED GOLD / PLACEHOLDER AUDIO", 2, ACCENT)
    c.text(1130, 681, f"{scene.start_frame // 90 + 1}/6", 2, MUTED, 86)
    return c.png()
