"""Controlled rewriting of caption text into natural spoken narration.

The caption keeps the exact identifiers and code; this layer only changes how they are said.
Rules are fixed and ordered. They may rename an identifier to the role the Architecture IR
already assigned to it, expand a small set of code idioms, and split identifiers into words.
They never add a fact: every spoken sentence is a function of its caption and the IR.
"""

import re

from repovox.media.architecture import Architecture
from repovox.media.storyboard import speakable

# Spoken names for roles the IR assigns from evidence. Tensors keep their variable names,
# which are ordinary words and must not be rewritten wherever they appear.
ROLE_NAMES = {
    "generator": "the generator",
    "discriminator": "the discriminator",
    "loss_d": "the discriminator loss",
    "loss_g": "the generator loss",
    "opt_d": "the discriminator optimizer",
    "opt_g": "the generator optimizer",
    "model": "the model",
    "loss": "the loss",
    "optimizer": "the optimizer",
}
IDIOMS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(\w+)\.backward\(\) then (\w+)\.step\(\) update (\w+)\."),
        r"\1 is backpropagated, followed by an optimizer step that updates \3.",
    ),
    (re.compile(r"under torch\.no_grad\(\)"), "with gradient tracking disabled"),
    (re.compile(r"\blr=([0-9.e-]+)"), r"learning rate \1"),
    (re.compile(r"\bbetas=\(([0-9.]+), ([0-9.]+)\)"), r"betas \1 and \2"),
    (re.compile(r"\bmomentum=([0-9.]+)"), r"momentum \1"),
    (re.compile(r"(\w+) (\w+) -> (\w+)((?: [ksp]\d+)*)"), r"\1 from \2 to \3"),
    (re.compile(r"\b(\w+)\(\)"), r"\1"),
    (re.compile(r"\bnn\.(\w+)"), r"\1"),
    (re.compile(r"\bself\.(\w+)"), r"\1"),
]
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def humanize(identifier: str) -> str:
    """`build_prompt` -> `build prompt`, `VectorStore` -> `Vector Store`."""
    words = CAMEL.sub(" ", identifier.replace("_", " ").replace(".", " "))
    return re.sub(r"\s+", " ", words).strip()


def vocabulary(architecture: Architecture) -> dict[str, str]:
    """Label -> spoken name. A role name is used only when the label is a plain identifier."""
    names: dict[str, str] = {}
    for component in architecture.components:
        spoken = ROLE_NAMES.get(component.role) if not architecture.views else None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", component.label):
            names.setdefault(component.label, spoken or humanize(component.label))
    return names


def natural(text: str, names: dict[str, str]) -> str:
    for pattern, replacement in IDIOMS:
        text = pattern.sub(replacement, text)
    for label in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?<![\w.]){re.escape(label)}(?![\w(])", names[label], text)
    text = re.sub(r"\b([a-z]+(?:_[a-z0-9]+)+)\b", lambda m: m.group(1).replace("_", " "), text)
    text = re.sub(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b", lambda m: humanize(m.group(0)), text)
    spoken = speakable(text)
    # A sentence that starts with a role phrase starts with a capital letter when captioned.
    return (spoken[:1].upper() + spoken[1:])[:600]
