"""Technical pronunciation for speech synthesis input only. Pure, deterministic, no I/O.

`pronounce` turns approved narration text into what a voice is asked to say: acronyms are
spelled letter by letter, common library names get their usual spoken form, code identifiers
and file paths are read as words, versions are read as numbers, commit hashes and links are
not read aloud, and punctuation is reduced to natural clause breaks.

It never changes a caption, a burned-in subtitle, a storyboard, a citation or a hash: its
result is passed only to a `narration.Synthesizer` or speech engine. It adds no fact. Every
word it emits is a reading of a word that is already in the text.

Spelled letters are separated by spaces. The letter A is written "Eh": espeak-ng, which both
the operating-system voice and Kokoro's phonemizer use, reads a lone "A" as the article. Two
spelled names side by side are kept apart by a clause break, so "OpenAI API" is said as
"Open Eh I, Eh P I" and never runs together as one string of letters. A repository or
identifier name is read part by part when a part is technical (`openai-cs-agents-demo` is
"Open Eh I, C S agents demo"), and a lowercase compound with a technical ending is split for
the phonemizer (`chatkit` is "chat kit", `duckdb` is "duck D B").
"""

import re

LIMIT = 600  # The narration layer's own bound on one spoken sentence.

# Exact-case technical names and their spoken form. Checked before any other rule.
TERMS: dict[str, str] = {
    "FastAPI": "Fast Eh P I",
    "PostgreSQL": "Postgres Q L",
    "SQLite": "S Q Lite",
    "MySQL": "My S Q L",
    "NoSQL": "No S Q L",
    "GraphQL": "Graph Q L",
    "PyTorch": "Pie Torch",
    "NumPy": "Num Pie",
    "SciPy": "Sigh Pie",
    "PyPI": "Pie P I",
    "pytest": "pie test",
    "README": "Read me",
    "JSON": "Jason",
    "YAML": "Yammel",
    "OAuth": "Oh Auth",
    "OAuth2": "Oh Auth 2",
    "OpenAPI": "Open Eh P I",
    "OpenAI": "Open Eh I",
    "GitHub": "Git Hub",
    "GitLab": "Git Lab",
    "JavaScript": "Java Script",
    "TypeScript": "Type Script",
    "WebSocket": "Web Socket",
    "MinIO": "Min I O",
    "ONNX": "Onyx",
    "CUDA": "Cooda",
    "TensorFlow": "Tensor Flow",
    "sklearn": "S K learn",
    "RepoVox": "Repo Vox",
    "macOS": "mac O S",
    "iOS": "eye O S",
    "TODO": "to do",
    "FIXME": "fix me",
    "CTGAN": "C T G Eh N",
    "TVAE": "T V Eh E",
}
# Lower-case spellings of those names that are not ordinary English words.
LOWER_TERMS = {
    key.lower(): value
    for key, value in TERMS.items()
    if key.lower() not in {"todo", "fixme", "cuda", "pytest", "ios"}
}
# Tokens that contain a slash but are one spoken term.
SLASHED: dict[str, str] = {
    "CI/CD": "C I C D",
    "UI/UX": "U I U X",
    "I/O": "I O",
    "TCP/IP": "T C P I P",
}
# Lowercase forms of acronyms met inside identifiers, for example build_api or getUrl.
LOWER_ACRONYMS = frozenset(
    "api url uri cli sdk sql uuid http https llm gan vae mri ui ux tsx jsx csv html css "
    "pdf json yaml jwt orm aws gpu cpu ram oidc tls ssl ssh dns tcp udp cors csrf rbac "
    "acl ecg ocr nlp tts id ids db".split()
)
# All-capital words that are said as words, not spelled.
CAPITAL_WORDS = frozenset(
    "MODE DATA AUTH TRUE FALSE NULL NONE GET PUT POST HEAD MAIN OPEN HIGH LOW NOTE INFO WARN "
    "CRUD REST NASA ONLY FROM WITH THIS THAT SOME MORE MOST LIKE PORT HOST TEXT TYPE NAME "
    "PATH FILE LIST USER ROLE TIME DATE SIZE KEY KEYS NOT AND THE FOR ALL ANY BUT CAN USE NEW "
    "OLD OFF OUT SET RUN ADD END YES NO OR IF IS IT IN ON OF TO AT BY AN AS BE DO GO UP WE MY "
    "SO HAS WAS ARE ONE TWO ITS ALSO STEP CODE TEST READ SAFE LIVE MAX MIN".split()
)
EXTENSIONS: dict[str, str] = {
    "py": "pie",
    "pyi": "pie I",
    "ts": "T S",
    "tsx": "T S X",
    "js": "J S",
    "jsx": "J S X",
    "mjs": "M J S",
    "cjs": "C J S",
    "md": "markdown",
    "json": "Jason",
    "yml": "Yammel",
    "yaml": "Yammel",
    "toml": "tommel",
    "txt": "text",
    "sh": "shell",
    "sql": "S Q L",
    "html": "H T M L",
    "css": "C S S",
    "csv": "C S V",
    "ini": "I N I",
    "cfg": "config",
    "ipynb": "notebook",
    "pth": "P T H",
    "pt": "P T",
    "onnx": "Onyx",
    "lock": "lock",
    "env": "env",
    "vtt": "V T T",
    "mp4": "M P 4",
    "png": "P N G",
    "keras": "keras",
}
LETTERS = {"A": "Eh"}
# Technical endings glued to a lowercase word, the shortest stem that may carry each, and
# whether the ending is spelled. A short stem is never split: robot, okapi and sabot stay whole.
COMPOUNDS: tuple[tuple[str, int, bool], ...] = (
    ("kit", 3, False),
    ("bot", 4, False),
    ("sdk", 2, True),
    ("cli", 3, True),
    ("api", 3, True),
    ("db", 3, True),
    ("ql", 3, True),
    ("ui", 3, True),
)
UNIT = r"(?:[A-Z]|Eh)"  # One spelled letter, as `spell` writes it.
SPELLED_END = re.compile(rf"(?:^|\s){UNIT} {UNIT}$")
SPELLED_START = re.compile(rf"^{UNIT} {UNIT}(?:\s|$)")
ABBREVIATIONS = [
    (re.compile(r"\be\.g\.,?", re.IGNORECASE), "for example,"),
    (re.compile(r"\bi\.e\.,?", re.IGNORECASE), "that is,"),
    (re.compile(r"\betc\."), "et cetera."),
    (re.compile(r"\bvs\.?(?=\s)"), "versus"),
]
OPERATORS = [
    (re.compile(r"\(\s*\)"), ""),  # a call's empty argument list is not said
    (re.compile(r"\)\.(?=[A-Za-z_])"), ") "),  # call(...).attribute
    (re.compile(r"\s*(?:->|=>)\s*"), " to "),
    (re.compile(r"\s*==\s*"), " equals "),
    (re.compile(r"\s*!=\s*"), " is not "),
    (re.compile(r"\s*>=\s*"), " at least "),
    (re.compile(r"\s*<=\s*"), " at most "),
    (re.compile(r"\s*&&\s*"), " and "),
    (re.compile(r"\s*\|\|\s*"), " or "),
    (re.compile(r"\s+&\s+"), " and "),
    (re.compile(r"(?<=\d)\s*%"), " percent"),
    (re.compile(r"(?<=\w)\s*\+\s*(?=\w)"), " plus "),
    (re.compile(r"\s*(?<![=!<>])=(?!=)\s*"), " equals "),
]
LINK = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
HASH = re.compile(r"\b(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}\b")
TOKEN = re.compile(
    r"(?P<url>\b[a-z][a-z0-9+.-]*://\S+)"
    r"|(?P<slashed>CI/CD|UI/UX|I/O|TCP/IP)"
    r"|(?P<version>\bv?\d+(?:\.\d+){2,3}\b|\bv\d+(?:\.\d+)?\b)"
    r"|(?P<path>(?:\.{0,2}/)?[A-Za-z0-9_@~-][A-Za-z0-9_.@~-]*(?:/[A-Za-z0-9_.@~-]+)+/?"
    r"(?::\d+)?)"
    r"|(?P<route>(?<![\w/.])/[A-Za-z0-9_.-]+)"
    r"|(?P<file>\b[A-Za-z0-9_-]+\.[A-Za-z][A-Za-z0-9]{0,4}\b(?::\d+)?)"
    r"|(?P<dotted>\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b)"
    r"|(?P<word>\b[A-Za-z][A-Za-z0-9_'-]*[A-Za-z0-9]\b|\b[A-Za-z]\b)"
)


def spell(word: str) -> str:
    """Letters and digits one by one: "SQL" -> "S Q L", "S3" -> "S 3", "API" -> "Eh P I"."""
    return " ".join(LETTERS.get(c, c) for c in word.upper())


def joined(parts: list[str]) -> str:
    """Spoken parts in order; a clause break between two spelled names that meet."""
    said = ""
    for part in (p for p in parts if p):
        gap = ", " if SPELLED_END.search(said) and SPELLED_START.match(part) else " "
        said = f"{said}{gap}{part}" if said else part
    return said


def technical(part: str) -> bool:
    """A part of a name that is read as a term, an acronym or a compound, not as English."""
    lower = part.lower()
    return (
        lower in LOWER_TERMS
        or lower in LOWER_ACRONYMS
        or bool(re.fullmatch(r"[b-df-hj-np-tv-xz]{2}", lower))
        or compound(part) is not None
    )


def piece(part: str) -> str:
    """One part of a file, folder or hyphenated name: a two-consonant part is spelled
    (`cs` is "C S", `ml` is "M L"); anything else is read as a word."""
    if re.fullmatch(r"[b-df-hj-np-tv-xz]{2}", part):
        return spell(part)
    return word(part)


def compound(token: str) -> str | None:
    """`chatkit` -> "chat kit", `duckdb` -> "duck D B", `mysdk` -> "my S D K"; else None."""
    if not token.isalpha() or not (token.islower() or token.istitle()):
        return None
    lower = token.lower()
    for ending, shortest, spelled in COMPOUNDS:
        stem = lower[: -len(ending)]
        if lower.endswith(ending) and len(stem) >= shortest:
            head = word(stem)
            head = head[:1].upper() + head[1:] if token[0].isupper() else head
            return f"{head} {spell(ending) if spelled else ending}"
    return None


def numeral(value: str) -> str:
    return " point ".join(value.split("."))


def version(token: str) -> str:
    if token[0] in "vV":
        return "version " + numeral(token[1:])
    return numeral(token)


def capitals(letters: str, token: str) -> str:
    """An all-capital word, or one with a plural s: spelled when it is an acronym."""
    plural = not letters.isupper()
    core = letters[:-1] if plural else letters
    suffix = "s" if plural else ""
    if core in TERMS:
        return TERMS[core] + suffix
    if len(core) == 1:
        return token
    if any(c.isdigit() for c in core) or (len(core) <= 5 and core not in CAPITAL_WORDS):
        return spell(core) + suffix
    return core.lower() + suffix


def word(token: str) -> str:
    """One identifier or word, as spoken."""
    if token in TERMS:
        return TERMS[token]
    if "_" in token.strip("_"):
        return " ".join(word(part) for part in token.split("_") if part)
    if "-" in token and not token.startswith("-"):
        parts = [p for p in token.split("-") if p]
        if all(p.isalpha() for p in parts) and any(p.isupper() and len(p) > 1 for p in parts):
            return " ".join(word(p) for p in parts)  # GAN-based, CI-friendly
        if any(any(c.isdigit() for c in p) for p in parts):
            return " ".join(word(p) for p in parts)  # ADR-0019, model-v2
        if any(technical(p) for p in parts):
            return joined([piece(p) for p in parts])  # openai-cs-agents-demo
        return token  # an ordinary hyphenated word
    if re.fullmatch(r"[vV]\d+", token):
        return "version " + token[1:]
    letters = token.replace("'", "").strip("_")
    if letters and (
        letters.isupper() or (len(letters) > 2 and letters[-1] == "s" and letters[:-1].isupper())
    ):
        return capitals(letters, token)
    parts = CAMEL.sub(" ", token).split()
    if len(parts) > 1:
        # Inside an identifier, Api and Url are acronyms: getApiUrl -> get Eh P I U R L.
        return " ".join(spell(p) if p.lower() in LOWER_ACRONYMS else word(p) for p in parts)
    lower = token.lower()
    if token.islower() and lower in LOWER_TERMS:
        return LOWER_TERMS[lower]  # fastapi, pytorch, readme written in lower case
    if token.islower() and lower in LOWER_ACRONYMS:
        return spell(lower)
    split = compound(token)
    if split is not None:
        return split  # chatkit, duckdb, mysdk
    head = re.fullmatch(r"([a-z]+)(\d+)", token)
    if head:
        return f"{word(head.group(1))} {head.group(2)}"
    return token


def name(segment: str) -> str:
    """A file or directory name read as words: `test_config` -> `test config`."""
    pieces = [p for p in re.split(r"[_.\-@~]+", segment) if p]
    return joined([piece(p) for p in pieces])


def extension(ext: str) -> str:
    lower = ext.lower()
    if lower in EXTENSIONS:
        return EXTENSIONS[lower]
    return lower if re.search(r"[aeiou]", lower) and len(lower) > 2 else spell(lower)


def filename(segment: str) -> str:
    stem, dot, ext = segment.rpartition(".")
    if not dot or not stem or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,4}", ext):
        return name(segment)
    return f"{name(stem)} dot {extension(ext)}"


def line_suffix(token: str) -> tuple[str, str]:
    match = re.search(r":(\d+)$", token)
    if match is None:
        return token, ""
    return token[: match.start()], f", line {match.group(1)}"


def path(token: str) -> str:
    """`backend/app/services/inputs.py` -> `inputs dot pie in backend app services`."""
    stop = "." if token.endswith(".") else ""  # a sentence's full stop, not part of the path
    token, line = line_suffix(token.rstrip("."))
    parts = [p for p in token.strip("/").split("/") if p not in {"", ".", ".."}]
    if not parts:
        return "the root folder"
    last = parts[-1]
    if re.fullmatch(r"[^.]+(?:\.[^.]+)*\.[A-Za-z][A-Za-z0-9]{0,4}", last):
        folders = joined([name(p) for p in parts[:-1][-3:]])
        spoken = filename(last) + (f" in {folders}" if folders else "")
    else:
        spoken = joined([name(p) for p in parts[-4:]])
    return spoken + line + stop


def dotted(token: str) -> str:
    """`settings.port` -> `settings port`; a file name is read as a file."""
    if token.rsplit(".", 1)[-1].lower() in EXTENSIONS:
        return filename(token)
    return " ".join(word(part) for part in token.split("."))


def replace(match: re.Match[str]) -> str:
    kind, token = match.lastgroup, match.group(0)
    if kind == "url":
        return "a web link"
    if kind == "slashed":
        return SLASHED[token]
    if kind == "version":
        return version(token)
    if kind == "path":
        return path(token)
    if kind == "route":
        return "slash " + name(token[1:])
    if kind == "file":
        bare, line = line_suffix(token)
        return dotted(bare) + line  # settings.port is a name; README.md is a file
    if kind == "dotted":
        return dotted(token)
    return word(token)


def tokens(text: str) -> str:
    """Every token in its spoken form; two spelled names separated only by a space get a
    clause break, so "OpenAI API" is "Open Eh I, Eh P I", not one run of letters."""
    said: list[str] = []
    previous, end = "", 0
    for match in TOKEN.finditer(text):
        gap = text[end : match.start()]
        spoken = replace(match)
        if said and gap and not gap.strip() and SPELLED_END.search(previous):
            if SPELLED_START.match(spoken):
                gap = ", "
        said += [gap, spoken]
        previous, end = spoken, match.end()
    return "".join([*said, text[end:]])


def pace(text: str) -> str:
    """Clause breaks a listener can follow, without doubled or dangling punctuation."""
    text = re.sub(r"[`\"*_{}\[\]<>|#^~\\]", " ", text)
    text = re.sub(r"(?<![A-Za-z])'|'(?![A-Za-z])", " ", text)  # quotes, not apostrophes
    text = re.sub(r"\s*\(\s*", ", ", text)
    text = re.sub(r"\s*\)\s*", ", ", text)
    text = re.sub(r"\s*;\s*", ", ", text)
    text = re.sub(r"\s+-{1,2}\s+", ", ", text)
    text = re.sub(r"\.{2,}", ",", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.:!?])", r"\1", text)
    text = re.sub(r"([,:])(?:\s*[,:])+", r"\1", text)
    text = re.sub(r",\s*([.!?])", r"\1", text)
    text = re.sub(r"([.!?])(?:\s*[.,:])+", r"\1", text)
    # A space after a break, but never inside a number such as 10,000 or 1.5.
    text = re.sub(r"([,.:!?])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"(?<!\d)([,.:!?])(?=\d)", r"\1 ", text)
    text = re.sub(r"\b(version) version\b", r"\1", text, flags=re.IGNORECASE)
    text = text.strip(" ,:;")
    # A long clause with no break gets one before its first subordinate conjunction.
    paced = []
    for clause in re.split(r"(?<=[.!?])\s+", text):
        words = clause.split(" ")
        if len(words) > 24 and "," not in clause:
            for i in range(8, len(words) - 4):
                if words[i] in {"which", "while", "because", "so", "but", "where"}:
                    words[i - 1] += ","
                    break
        paced.append(" ".join(words))
    text = " ".join(paced)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def pronounce(text: str) -> str:
    """Spoken form of one approved narration sentence. Printable ASCII only."""
    text = "".join(c if 32 <= ord(c) < 127 else " " for c in text)
    # Undo the earlier spoken-form rewriting so a path is read once, as a path.
    text = re.sub(r"\s+slash\s+", "/", text)
    text = re.sub(r"(?<=\w) dot (?=(?:py|js|jsx|mjs|cjs|ts|tsx)\b)", ".", text)
    text = LINK.sub("a web link", text)  # before operators: a link's = or & is not said
    for pattern, replacement in ABBREVIATIONS + OPERATORS:
        text = pattern.sub(replacement, text)
    text = HASH.sub(" ", text)
    text = tokens(text)
    return pace(text)


__all__ = ["LIMIT", "pronounce"]
