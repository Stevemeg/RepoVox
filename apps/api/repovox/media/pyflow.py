"""Static Python flow facts for architecture discovery. Source is parsed, never executed.

Only simple, checkable patterns are recognised: class layer declarations, single-assignment
variable bindings, direct module calls and optimizer/loss statements in source order. Anything
else stays unknown rather than being guessed.
"""

from dataclasses import dataclass, field, replace
from typing import Any

from tree_sitter import Node, Parser

from repovox.analysis.parser import language

DEFINITIONS = {"function_definition", "class_definition", "decorated_definition"}
PASSTHROUGH = {
    "detach",
    "to",
    "view",
    "reshape",
    "float",
    "cuda",
    "cpu",
    "clone",
    "squeeze",
    "unsqueeze",
    "flatten",
    "train",
    "eval",
}
NOISE = {"randn", "rand", "randn_like", "rand_like", "normal"}
LOSS_FUNCTIONS = {"binary_cross_entropy", "binary_cross_entropy_with_logits", "mse_loss"}
LOSS_FUNCTIONS |= {"cross_entropy", "nll_loss"}
MODULE_BASES = {"nn.Module", "torch.nn.Module", "Module"}


def text(node: Node | None, body: bytes) -> str:
    return "" if node is None else body[node.start_byte : node.end_byte].decode("utf-8", "replace")


def line(node: Node) -> int:
    return int(node.start_point.row) + 1


def descendants(node: Node) -> list[Node]:
    found = [node]
    for child in node.named_children:
        found.extend(descendants(child))
    return found


def flat(node: Node) -> list[Node]:
    """Simple statements of one scope in source order; nested definitions are other scopes."""
    found: list[Node] = []
    for child in node.named_children:
        if child.type in DEFINITIONS:
            continue
        if child.type in {"expression_statement", "return_statement"}:
            found.append(child)
            continue
        if child.type in {"for_statement", "with_statement"}:
            found.append(child)
        found.extend(flat(child))
    return found


def arguments(call: Node) -> tuple[list[Node], dict[str, Node]]:
    positional: list[Node] = []
    keywords: dict[str, Node] = {}
    listing = call.child_by_field_name("arguments")
    for child in listing.named_children if listing is not None else []:
        if child.type == "keyword_argument":
            name, value = child.child_by_field_name("name"), child.child_by_field_name("value")
            if name is not None and value is not None and name.text is not None:
                keywords[name.text.decode()] = value
        elif child.type not in {"list_splat", "dictionary_splat", "comment"}:
            positional.append(child)
    return positional, keywords


def has_splat(call: Node) -> bool:
    listing = call.child_by_field_name("arguments")
    return listing is not None and any(
        c.type in {"list_splat", "dictionary_splat"} for c in listing.named_children
    )


def unwrap(node: Node, body: bytes) -> Node:
    """Model(...).to(device) -> Model(...); (expr) -> expr."""
    while True:
        if node.type == "parenthesized_expression" and node.named_child_count == 1:
            node = node.named_children[0]
            continue
        function = node.child_by_field_name("function") if node.type == "call" else None
        if function is not None and function.type == "attribute":
            inner = function.child_by_field_name("object")
            name = text(function.child_by_field_name("attribute"), body)
            if inner is not None and inner.type == "call" and name in PASSTHROUGH:
                node = inner
                continue
        return node


@dataclass(frozen=True)
class Tag:
    kind: str  # noise | batch | output | sampled_labels
    line: int
    cls: str = ""
    index: int = 0
    detached: bool = False
    inputs: tuple["Tag | None", ...] = ()
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Layer:
    attribute: str
    type: str
    arguments: tuple[str, ...]
    keywords: tuple[tuple[str, str], ...]
    resolved: bool
    line: int


@dataclass
class ModuleClass:
    path: str
    name: str
    line: int
    layers: list[Layer] = field(default_factory=list)
    forward_parameters: list[str] = field(default_factory=list)
    forward_line: int = 0
    dynamic: bool = False  # Layers built in a way this reader does not follow.


@dataclass(frozen=True)
class ModuleCall:
    variable: str
    cls: str
    line: int
    arguments: tuple[Tag | None, ...]
    names: tuple[str, ...]
    assigned: str


@dataclass(frozen=True)
class LossTerm:
    function: str
    score: Tag | None
    line: int


@dataclass
class Scope:
    path: str
    name: str
    line: int
    no_grad: bool = False
    parameters: list[str] = field(default_factory=list)
    instances: dict[str, tuple[str, int]] = field(default_factory=dict)
    tags: dict[str, Tag] = field(default_factory=dict)
    calls: list[ModuleCall] = field(default_factory=list)
    criteria: dict[str, tuple[str, int]] = field(default_factory=dict)
    optimizers: dict[str, dict[str, Any]] = field(default_factory=dict)
    steps: list[tuple[str, int]] = field(default_factory=list)
    backwards: list[tuple[str, int]] = field(default_factory=list)
    assignments: dict[str, list[tuple[Node, int]]] = field(default_factory=dict)
    loader_line: int = 0
    unbound: list[tuple[str, int]] = field(default_factory=list)


class SourceFile:
    def __init__(self, path: str, body: bytes) -> None:
        self.path, self.body = path, body
        self.tree = Parser(language("python")).parse(body)  # Keeps nodes alive.
        self.root: Node = self.tree.root_node
        self.valid = not self.root.has_error
        self.lines = body.decode("utf-8", "replace").split("\n")
        self.constants: dict[str, str] = {}
        if self.valid:
            for statement in self.root.named_children:
                node = statement.named_children[0] if statement.named_child_count else None
                if statement.type == "expression_statement" and node is not None:
                    left, right = (
                        node.child_by_field_name("left"),
                        node.child_by_field_name("right"),
                    )
                    if (
                        node.type == "assignment"
                        and left is not None
                        and right is not None
                        and left.type == "identifier"
                        and right.type in {"integer", "float"}
                    ):
                        name = text(left, body)
                        # A constant reassigned at module level is not a constant.
                        self.constants[name] = "" if name in self.constants else text(right, body)

    def quote(self, number: int) -> str:
        return self.lines[number - 1].strip() if 1 <= number <= len(self.lines) else ""

    def literal(self, node: Node, local: dict[str, str]) -> tuple[str, bool]:
        """Literal or module-constant value; otherwise the source text marked unresolved."""
        value = text(node, self.body)
        if node.type in {"integer", "float", "true", "false", "none", "string"}:
            return value, True
        if node.type == "tuple" and all(
            c.type in {"integer", "float"} for c in node.named_children
        ):
            return value, True
        if node.type == "unary_operator" and node.named_child_count == 1:
            inner, known = self.literal(node.named_children[0], local)
            return value if known else inner, known
        if node.type == "identifier":
            found = local.get(value) or self.constants.get(value)
            if found:
                return found, True
        return value, False

    def module_classes(self) -> list[ModuleClass]:
        classes: list[ModuleClass] = []
        for node in descendants(self.root) if self.valid else []:
            if node.type != "class_definition":
                continue
            bases = node.child_by_field_name("superclasses")
            names = (
                {text(b, self.body) for b in bases.named_children} if bases is not None else set()
            )
            if not names & MODULE_BASES:
                continue
            item = ModuleClass(
                self.path, text(node.child_by_field_name("name"), self.body), line(node)
            )
            block = node.child_by_field_name("body")
            for member in block.named_children if block is not None else []:
                definition = member
                if member.type == "decorated_definition":
                    definition = member.child_by_field_name("definition") or member
                if definition.type != "function_definition":
                    continue
                name = text(definition.child_by_field_name("name"), self.body)
                if name == "__init__":
                    self.layers(definition, item)
                elif name == "forward":
                    item.forward_line = line(definition)
                    item.forward_parameters = parameter_names(definition, self.body)[1:]
            classes.append(item)
        return classes

    def layers(self, definition: Node, item: ModuleClass) -> None:
        local: dict[str, str] = {}
        parameters = definition.child_by_field_name("parameters")
        for parameter in parameters.named_children if parameters is not None else []:
            value = parameter.child_by_field_name("value")
            name = parameter.child_by_field_name("name")
            if value is not None and name is not None:
                found, known = self.literal(value, {})
                if known:
                    local[text(name, self.body)] = found
        block = definition.child_by_field_name("body")
        for statement in flat(block) if block is not None else []:
            node = statement.named_children[0] if statement.named_child_count else None
            if node is None or node.type != "assignment":
                continue
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if left is None or right is None or left.type != "attribute" or right.type != "call":
                continue
            if text(left.child_by_field_name("object"), self.body) != "self":
                continue
            attribute = text(left.child_by_field_name("attribute"), self.body)
            callee = text(right.child_by_field_name("function"), self.body)
            if not callee.startswith(("nn.", "torch.nn.")):
                continue
            if callee.rsplit(".", 1)[-1] in {"Sequential", "ModuleList"}:
                positional, _ = arguments(right)
                if has_splat(right) or any(
                    c.type != "call"
                    or not text(c.child_by_field_name("function"), self.body).startswith(
                        ("nn.", "torch.nn.")
                    )
                    for c in positional
                ):
                    item.dynamic = True
                    continue
                for child in positional:
                    item.layers.append(self.layer(attribute, child, local))
            else:
                item.layers.append(self.layer(attribute, right, local))

    def layer(self, attribute: str, call: Node, local: dict[str, str]) -> Layer:
        positional, keywords = arguments(call)
        values = [self.literal(node, local) for node in positional]
        named = [(name, self.literal(node, local)) for name, node in keywords.items()]
        return Layer(
            attribute,
            text(call.child_by_field_name("function"), self.body).rsplit(".", 1)[-1],
            tuple(value for value, _ in values),
            tuple((name, value) for name, (value, _) in named),
            all(known for _, known in values) and all(known for _, (_, known) in named),
            line(call),
        )

    def scopes(self, classes: dict[str, ModuleClass]) -> list[Scope]:
        if not self.valid:
            return []
        top = Scope(self.path, "<module>", 1)
        self.read(self.root, top, classes)
        found = [top]
        for node in descendants(self.root):
            if node.type != "function_definition":
                continue
            parent = node.parent
            decorated = parent is not None and parent.type == "decorated_definition"
            scope = Scope(
                self.path,
                text(node.child_by_field_name("name"), self.body),
                line(node),
                no_grad=decorated and "no_grad" in text(parent, self.body).split("def ", 1)[0],
                parameters=parameter_names(node, self.body),
                instances=dict(top.instances),
                criteria=dict(top.criteria),
                optimizers=dict(top.optimizers),
            )
            block = node.child_by_field_name("body")
            if block is not None:
                self.read(block, scope, classes)
            found.append(scope)
        return found

    def tag(self, node: Node, scope: Scope) -> Tag | None:
        node = node.named_children[0] if node.type == "parenthesized_expression" else node
        if node.type == "identifier":
            return scope.tags.get(text(node, self.body))
        if node.type != "call":
            return None
        function = node.child_by_field_name("function")
        if function is None:
            return None
        callee = text(function, self.body)
        positional, _ = arguments(node)
        if function.type == "identifier" and callee in scope.instances:
            return Tag(
                "output",
                line(node),
                cls=scope.instances[callee][0],
                inputs=tuple(self.tag(a, scope) for a in positional),
                names=tuple(text(a, self.body) for a in positional),
            )
        if function.type == "attribute":
            name = text(function.child_by_field_name("attribute"), self.body)
            inner = function.child_by_field_name("object")
            if name in PASSTHROUGH and inner is not None:
                found = self.tag(inner, scope)
                return replace(found, detached=True) if found and name == "detach" else found
            if callee.startswith("torch.") and name in NOISE:
                return Tag("noise", line(node))
            if callee == "torch.randint":
                return Tag("sampled_labels", line(node))
        return None

    def read(self, block: Node, scope: Scope, classes: dict[str, ModuleClass]) -> None:
        for statement in flat(block):
            if statement.type == "with_statement":
                clause = statement.named_children[0] if statement.named_child_count else None
                if clause is not None and "no_grad" in text(clause, self.body):
                    scope.no_grad = True
                continue
            if statement.type == "for_statement":
                self.loop(statement, scope)
                continue
            node = statement.named_children[0] if statement.named_child_count else None
            if node is None:
                continue
            for call in descendants(node):
                function = call.child_by_field_name("function") if call.type == "call" else None
                if function is None:
                    continue
                callee = text(function, self.body)
                if function.type == "identifier" and callee in scope.instances:
                    positional, _ = arguments(call)
                    scope.calls.append(
                        ModuleCall(
                            callee,
                            scope.instances[callee][0],
                            line(call),
                            tuple(self.tag(a, scope) for a in positional),
                            tuple(text(a, self.body) for a in positional),
                            "",
                        )
                    )
                elif function.type == "identifier" and callee in scope.parameters:
                    # A model passed in as a parameter: called, but its class is unknown.
                    scope.unbound.append((callee, line(call)))
                elif function.type == "attribute":
                    owner = text(function.child_by_field_name("object"), self.body)
                    name = text(function.child_by_field_name("attribute"), self.body)
                    if name == "step" and owner in scope.optimizers:
                        scope.steps.append((owner, line(call)))
                    elif name == "backward":
                        scope.backwards.append((owner, line(call)))
            if node.type == "assignment":
                self.assign(node, scope, classes)

    def loop(self, statement: Node, scope: Scope) -> None:
        left, right = statement.child_by_field_name("left"), statement.child_by_field_name("right")
        if left is None or right is None:
            return
        names = [text(n, self.body) for n in descendants(left) if n.type == "identifier"]
        source = text(right, self.body)
        if source.startswith("enumerate("):
            names = names[1:]
        elif source.startswith("range("):
            return
        for index, name in enumerate(names[:2]):
            scope.tags[name] = Tag("batch", line(statement), index=index)
            scope.loader_line = scope.loader_line or line(statement)

    def assign(self, node: Node, scope: Scope, classes: dict[str, ModuleClass]) -> None:
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None:
            return
        if left.type != "identifier":
            for name in (text(n, self.body) for n in descendants(left) if n.type == "identifier"):
                scope.tags.pop(name, None)
            return
        name = text(left, self.body)
        scope.assignments.setdefault(name, []).append((right, line(node)))
        scope.instances.pop(name, None)
        inner = unwrap(right, self.body)
        callee = (
            text(inner.child_by_field_name("function"), self.body) if inner.type == "call" else ""
        )
        tail = callee.rsplit(".", 1)[-1]
        if inner.type == "call" and tail in classes and callee.count(".") <= 1:
            scope.instances[name] = (tail, line(node))
        elif callee.startswith(("nn.", "torch.nn.")) and tail.endswith("Loss"):
            scope.criteria[name] = (tail, line(node))
        elif inner.type == "call" and "optim." in callee:
            positional, keywords = arguments(inner)
            target = text(positional[0], self.body) if positional else ""
            owner = target.removesuffix(".parameters()")
            if target.endswith(".parameters()") and owner in scope.instances:
                scope.optimizers[name] = {
                    "type": tail,
                    "model": scope.instances[owner][0],
                    "line": line(node),
                    "settings": tuple(
                        (key, self.literal(value, {})[0])
                        for key, value in keywords.items()
                        if self.literal(value, {})[1]
                    ),
                }
        found = self.tag(right, scope)
        if found is None:
            scope.tags.pop(name, None)
        else:
            scope.tags[name] = found

    def loss_terms(self, scope: Scope, name: str, before: int, depth: int = 0) -> list[LossTerm]:
        """Loss-function calls feeding a loss variable, following at most two local names."""
        history = [item for item in scope.assignments.get(name, []) if item[1] <= before]
        if not history or depth > 2:
            return []
        node, number = history[-1]
        terms: list[LossTerm] = []
        for part in descendants(node):
            function = part.child_by_field_name("function") if part.type == "call" else None
            if function is None:
                continue
            callee = text(function, self.body)
            positional, _ = arguments(part)
            if callee in scope.criteria and positional:
                terms.append(
                    LossTerm(scope.criteria[callee][0], self.tag(positional[0], scope), number)
                )
            elif callee.rsplit(".", 1)[-1] in LOSS_FUNCTIONS and positional:
                terms.append(
                    LossTerm(callee.rsplit(".", 1)[-1], self.tag(positional[0], scope), number)
                )
        if terms:
            return terms
        for part in descendants(node):
            if part.type == "identifier" and text(part, self.body) in scope.assignments:
                other = text(part, self.body)
                if other != name:
                    terms.extend(self.loss_terms(scope, other, number, depth + 1))
        if not terms:
            # No named loss function: record module outputs used directly (e.g. mean of scores).
            for part in descendants(node):
                found = self.tag(part, scope) if part.type in {"call", "identifier"} else None
                if found is not None and found.kind == "output":
                    terms.append(LossTerm("expression", found, number))
        return terms


def parameter_names(definition: Node, body: bytes) -> list[str]:
    names: list[str] = []
    parameters = definition.child_by_field_name("parameters")
    for parameter in parameters.named_children if parameters is not None else []:
        if parameter.type == "identifier":
            names.append(text(parameter, body))
        else:
            name = parameter.child_by_field_name("name")
            first = name or (parameter.named_children[0] if parameter.named_child_count else None)
            if first is not None and first.type == "identifier":
                names.append(text(first, body))
    return names
