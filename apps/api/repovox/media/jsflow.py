"""Static JavaScript and TypeScript syntax facts for architecture discovery.

Source is parsed with the same Tree-sitter grammars as the analyzer and never executed. These
helpers only name the syntax the generic extractor reads: top-level declarations, class
members, parameters (including destructured props), statements of one scope, call and `new`
expressions, JSX elements that use a component, CommonJS `module.exports` / `exports.name`
assignments, and Express router declarations, routes and mounts written at the top level of a
file. Anything else stays unknown rather than being guessed.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node

from repovox.media.pyflow import line, text

LANGUAGES = {"javascript", "typescript", "tsx"}
# The declaration node types the analyzer records as functions, methods and classes.
FUNCTIONS = {
    "function_declaration",
    "generator_function_declaration",
    "function_expression",
    "arrow_function",
    "method_definition",
}
CLASSES = {"class_declaration"}
# Never part of the scope that contains them: a nested function or class is its own scope.
NESTED = FUNCTIONS | CLASSES | {"function", "generator_function", "class"}
CALLS = {"call_expression", "new_expression"}
ELEMENTS = {"jsx_self_closing_element", "jsx_opening_element"}
MARKUP = {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
STATEMENTS = {"expression_statement", "return_statement", "lexical_declaration"}
STATEMENTS |= {"variable_declaration"}
WRAPPERS = {
    "await_expression",
    "parenthesized_expression",
    "as_expression",
    "satisfies_expression",
    "non_null_expression",
}
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
# Values a CommonJS export or a route handler can be written as in place.
WRITTEN = {"arrow_function", "function_expression", "function", "method_definition"}
# The HTTP methods an Express router or a Next.js route handler declares.
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
# Source files the Next.js App Router reads as route handlers.
ROUTE_FILE = re.compile(r"route\.(?:ts|tsx|js|jsx|mjs|cjs)")


@dataclass(frozen=True)
class Declared:
    node: Node  # The function or class node; its `body` field is the scope.
    name: Node
    kind: str  # function | class
    exported: bool
    default: bool


@dataclass(frozen=True)
class CommonExport:
    """One name a CommonJS module exports: `module.exports = {...}`, `exports.name = ...`.

    `name` is None for the module value itself (`module.exports = handler`). `value` is the
    identifier, function or class written there; `key` is the node that shows the exported
    name on the line it is cited on.
    """

    name: str | None
    value: Node
    key: Node


@dataclass(frozen=True)
class RouteCall:
    """`owner.<method>("/path", ..., handler)` or `owner.use("/prefix", ..., target)`."""

    owner: str
    method: str  # get | post | put | patch | delete | use
    path: str  # "" for a `use` without a path
    path_node: Node | None
    target: Node  # The last argument: the handler, or what is mounted.
    line: int


def unwrap(node: Node) -> Node:
    """`await x`, `(x)`, `x as T`, `x!` -> x. A type assertion `<T>x` keeps its last child."""
    while node.named_child_count:
        if node.type in WRAPPERS:
            node = node.named_children[0]
        elif node.type == "type_assertion":
            node = node.named_children[-1]
        else:
            break
    return node


def head(node: Node, body: bytes) -> str:
    """The first line of a node's text, which is always on the line the node starts on."""
    return text(node, body).split("\n", 1)[0].strip()


def declarations(root: Node) -> Iterator[Declared]:
    """Top-level function and class declarations, exported or not, in source order."""
    for child in root.named_children:
        node, exported = child, False
        if child.type == "export_statement":
            exported = True
            node = child.child_by_field_name("declaration") or child
        default = exported and any(c.type == "default" for c in child.children)
        if node.type in {"function_declaration", "generator_function_declaration"}:
            name = node.child_by_field_name("name")
            if name is not None:
                yield Declared(node, name, "function", exported, default)
        elif node.type in CLASSES:
            name = node.child_by_field_name("name")
            if name is not None:
                yield Declared(node, name, "class", exported, default)
        elif node.type in {"lexical_declaration", "variable_declaration"}:
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name = declarator.child_by_field_name("name")
                value = declarator.child_by_field_name("value")
                if (
                    name is not None
                    and value is not None
                    and name.type == "identifier"
                    and value.type in {"arrow_function", "function_expression"}
                ):
                    yield Declared(value, name, "function", exported, False)


def methods(cls: Node) -> Iterator[tuple[Node, Node]]:
    """(method node, name node) for each method a class body declares."""
    block = cls.child_by_field_name("body")
    for member in block.named_children if block is not None else []:
        name = member.child_by_field_name("name")
        if member.type == "method_definition" and name is not None:
            yield member, name


def pattern_names(node: Node | None) -> list[Node]:
    """Identifier nodes a parameter or destructuring pattern binds, in source order."""
    if node is None:
        return []
    if node.type in {"identifier", "shorthand_property_identifier_pattern"}:
        return [node]
    if node.type in {"required_parameter", "optional_parameter"}:
        return pattern_names(node.child_by_field_name("pattern"))
    if node.type in {"assignment_pattern", "object_assignment_pattern"}:
        return pattern_names(node.child_by_field_name("left"))
    if node.type == "pair_pattern":
        return pattern_names(node.child_by_field_name("value"))
    if node.type in {"object_pattern", "array_pattern", "rest_pattern"}:
        return [found for child in node.named_children for found in pattern_names(child)]
    return []


def parameter_identifiers(definition: Node) -> list[Node]:
    parameters = definition.child_by_field_name("parameters")
    if parameters is None:
        # `x => ...` declares its single parameter without parentheses.
        return pattern_names(definition.child_by_field_name("parameter"))
    return [found for child in parameters.named_children for found in pattern_names(child)]


def parameter_names(definition: Node, body: bytes) -> list[str]:
    return list(dict.fromkeys(text(node, body) for node in parameter_identifiers(definition)))


def parameter_positions(definition: Node, body: bytes) -> dict[str, int]:
    """1-based line declaring each parameter; a signature may span several lines."""
    positions: dict[str, int] = {}
    for node in parameter_identifiers(definition):
        positions.setdefault(text(node, body), line(node))
    return positions


def flat(node: Node) -> list[Node]:
    """Statements of one scope in source order; nested functions and classes are not.

    Iterative, so a long expression in a condition cannot exhaust the recursion limit.
    """
    found: list[Node] = []
    stack = list(reversed(node.named_children))
    while stack:
        child = stack.pop()
        if child.type in NESTED:
            continue
        if child.type in STATEMENTS:
            found.append(child)
            continue
        if child.type == "for_in_statement":
            found.append(child)
            loop = child.child_by_field_name("body")
            if loop is not None:
                stack.append(loop)  # A braced block or a single statement: read after the loop.
            continue
        stack.extend(reversed(child.named_children))
    return found


def reachable(node: Node) -> list[Node]:
    """`node` and its descendants in pre-order, not entering nested functions or classes.

    A nested function is listed itself, so a caller can read it as its own scope. Iterative,
    so a long expression chain cannot exhaust the interpreter's recursion limit.
    """
    found: list[Node] = []
    stack = [node]
    while stack:
        current = stack.pop()
        found.append(current)
        if current.type not in NESTED:
            stack.extend(reversed(current.named_children))
    return found


def callee(node: Node) -> Node | None:
    """What a call, `new` expression or JSX element names."""
    if node.type == "call_expression":
        return node.child_by_field_name("function")
    if node.type == "new_expression":
        return node.child_by_field_name("constructor")
    if node.type in ELEMENTS:
        return node.child_by_field_name("name")
    return None


def arguments(node: Node) -> list[Node]:
    """Argument expressions; for a JSX element, the expressions given to its attributes."""
    if node.type in ELEMENTS:
        values: list[Node] = []
        for attribute in node.named_children:
            if attribute.type != "jsx_attribute" or attribute.named_child_count < 2:
                continue
            value = attribute.named_children[-1]
            if value.type == "jsx_expression" and value.named_child_count:
                inner = value.named_children[0]
                if inner.type not in {"spread_element", "comment"}:
                    values.append(inner)
        return values
    listing = node.child_by_field_name("arguments")
    if listing is None or listing.type != "arguments":
        return []  # A tagged template passes no separable argument values.
    return [c for c in listing.named_children if c.type not in {"spread_element", "comment"}]


def component_element(node: Node, body: bytes) -> bool:
    """A JSX element that uses a component: a capitalised or dotted name, not an HTML tag."""
    name = node.child_by_field_name("name") if node.type in ELEMENTS else None
    value = text(name, body)
    return bool(value) and (value[0].isupper() or "." in value)


def string_value(node: Node, body: bytes) -> str | None:
    """A string literal, or a template literal without substitutions; else None."""
    if node.type == "string" or (
        node.type == "template_string"
        and not any(c.type == "template_substitution" for c in node.named_children)
    ):
        return text(node, body)[1:-1]
    return None


def declared_names(root: Node, body: bytes) -> dict[str, int]:
    """How often a file declares, assigns or receives each name as a parameter, at any depth."""
    found: list[Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.type in FUNCTIONS | CLASSES:
            found += parameter_identifiers(node)
            name = node.child_by_field_name("name")
            if name is not None and node.type != "method_definition":
                found.append(name)
        elif node.type == "variable_declarator":
            found += pattern_names(node.child_by_field_name("name"))
        elif node.type in {"assignment_expression", "augmented_assignment_expression"}:
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                found.append(left)
        elif node.type == "for_in_statement":
            found += pattern_names(node.child_by_field_name("left"))
        elif node.type == "import_specifier":
            local = node.child_by_field_name("alias") or node.child_by_field_name("name")
            found += [local] if local is not None else []
        elif node.type in {"namespace_import", "import_clause"}:
            found += [c for c in node.named_children if c.type == "identifier"]
    counts: dict[str, int] = {}
    for node in found:
        counts[text(node, body)] = counts.get(text(node, body), 0) + 1
    return counts


def destructured(node: Node, body: bytes) -> list[tuple[str, str]]:
    """(local name, member) pairs bound by `const { a, b: c } = require(...)`."""
    declarator = node.parent
    while declarator is not None and declarator.type in WRAPPERS:
        declarator = declarator.parent
    pattern = (
        declarator.child_by_field_name("name")
        if declarator is not None and declarator.type == "variable_declarator"
        else None
    )
    if pattern is None or pattern.type != "object_pattern":
        return []
    pairs: list[tuple[str, str]] = []
    for child in pattern.named_children:
        if child.type == "shorthand_property_identifier_pattern":
            pairs.append((text(child, body), text(child, body)))
        elif child.type == "pair_pattern":
            key, value = child.child_by_field_name("key"), child.child_by_field_name("value")
            if key is not None and value is not None and value.type == "identifier":
                pairs.append((text(value, body), text(key, body).strip("\"'")))
    return pairs


def top_level(root: Node) -> Iterator[tuple[Node, bool]]:
    """Statements written directly in the file, each with whether `export` wraps it."""
    for child in root.named_children:
        if child.type == "export_statement":
            inner = child.child_by_field_name("declaration")
            if inner is not None:
                yield inner, True
            continue
        yield child, False


def top_level_values(root: Node) -> Iterator[tuple[Node, Node, bool]]:
    """(name, value, exported) for each `const name = value` written directly in the file."""
    for statement, exported in top_level(root):
        if statement.type not in {"lexical_declaration", "variable_declaration"}:
            continue
        for declarator in statement.named_children:
            if declarator.type != "variable_declarator":
                continue
            name = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name is not None and value is not None and name.type == "identifier":
                yield name, value, exported


def top_level_calls(root: Node) -> Iterator[Node]:
    """Calls written as a statement directly in the file, such as `app.use(...)`."""
    for statement, _ in top_level(root):
        if statement.type == "expression_statement" and statement.named_child_count:
            node = unwrap(statement.named_children[0])
            if node.type == "call_expression":
                yield node


def route_call(node: Node, body: bytes) -> RouteCall | None:
    """`owner.get("/path", ..., handler)`, `owner.use("/prefix", ..., target)` or `owner.use(x)`.

    The owner must be a plain name and a path a literal starting with `/`. Any other shape,
    such as a chained `owner.route("/path").get(...)`, is not read.
    """
    function = node.child_by_field_name("function")
    if function is None or function.type != "member_expression":
        return None
    owner = function.child_by_field_name("object")
    method = text(function.child_by_field_name("property"), body)
    values = arguments(node)
    if owner is None or owner.type != "identifier" or not values:
        return None
    if method not in {*HTTP_METHODS, "use"}:
        return None
    first = string_value(values[0], body) if len(values) >= 2 else None
    if first is not None and not first.startswith("/"):
        return None
    if method != "use" and first is None:
        return None
    return RouteCall(
        text(owner, body),
        method,
        first or "",
        values[0] if first is not None else None,
        values[-1],
        line(values[0] if first is not None else node),
    )


def exports_target(left: Node, body: bytes) -> tuple[str, str | None, Node] | None:
    """`module.exports` -> (module, None, ..); `module.exports.x` or `exports.x` -> (.., x, ..).

    The node returned is what shows the exported name on the line it is cited on.
    """
    owner = left.child_by_field_name("object")
    prop = left.child_by_field_name("property")
    if owner is None or prop is None:
        return None
    if owner.type == "identifier" and text(owner, body) == "module":
        return ("module", None, left) if text(prop, body) == "exports" else None
    if owner.type == "identifier" and text(owner, body) == "exports":
        return "exports", text(prop, body), prop
    if owner.type == "member_expression":
        inner = exports_target(owner, body)
        if inner is not None and inner[:2] == ("module", None):
            return "module", text(prop, body), prop
    return None


def exported_value(node: Node) -> bool:
    """A value an export can name: an identifier, or a function or class written in place."""
    return node.type in {"identifier", "class"} | WRITTEN


def commonjs_exports(root: Node, body: bytes) -> list[CommonExport] | None:
    """What a module assigns to `module.exports` and `exports.name` at its top level.

    Only unconditional statements of the file itself are read, never assignments inside a
    function, a condition or a loop. None when `module.exports` is assigned more than once,
    because which assignment holds is then not settled by the syntax. A member assigned before
    `module.exports` is replaced, and `exports.name` after it, no longer reach the module
    value and are not read; a name assigned twice is not read either.
    """
    whole: list[tuple[int, Node, Node]] = []
    members: list[tuple[int, str, Node, Node, bool]] = []
    for order, child in enumerate(root.named_children):
        if child.type != "expression_statement" or not child.named_child_count:
            continue
        node = child.named_children[0]
        if node.type != "assignment_expression":
            continue
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None or left.type != "member_expression":
            continue
        found = exports_target(left, body)
        if found is None:
            continue
        via, name, key = found
        if name is None:
            whole.append((order, unwrap(right), left))
        else:
            members.append((order, name, unwrap(right), key, via == "module"))
    if len(whole) > 1:
        return None
    exported: list[CommonExport] = []
    start = whole[0][0] if whole else -1
    if whole:
        _, value, left = whole[0]
        if value.type == "object":
            exported += object_members(value, body)
        elif exported_value(value):
            exported.append(CommonExport(None, value, left))
    for order, name, value, key, via_module in members:
        if order < start or (whole and not via_module) or not exported_value(value):
            continue
        exported.append(CommonExport(name, value, key))
    names = [item.name for item in exported]
    return [item for item in exported if names.count(item.name) == 1]


def object_members(value: Node, body: bytes) -> list[CommonExport]:
    """`{ a, b: c, d: () => ..., e() {} }` -> one export per member naming something."""
    found: list[CommonExport] = []
    for prop in value.named_children:
        if prop.type == "shorthand_property_identifier":
            found.append(CommonExport(text(prop, body), prop, prop))
        elif prop.type == "pair":
            key, item = prop.child_by_field_name("key"), prop.child_by_field_name("value")
            if key is None or item is None or key.type not in {"property_identifier", "string"}:
                continue
            if exported_value(unwrap(item)):
                found.append(CommonExport(text(key, body).strip("\"'"), unwrap(item), key))
        elif prop.type == "method_definition":
            label = prop.child_by_field_name("name")
            if label is not None and label.type == "property_identifier":
                found.append(CommonExport(text(label, body), prop, label))
    return found


def app_route(path: str) -> str | None:
    """The URL path a Next.js App Router route handler file serves, read from where it is.

    `app/api/items/[id]/route.ts` -> `/api/items/[id]`. A route group `(name)` adds no
    segment. A file under a private `_folder`, a parallel `@slot` or an intercepting `(.)`
    segment is not read as a route. None for a file not named `route.*` inside `app/`.
    """
    parts = path.split("/")
    if not ROUTE_FILE.fullmatch(parts[-1]) or "app" not in parts[:-1]:
        return None
    kept: list[str] = []
    for segment in parts[parts.index("app") + 1 : -1]:
        if segment.startswith("(."):
            return None
        if segment.startswith("(") and segment.endswith(")"):
            continue
        if segment.startswith(("_", "@")):
            return None
        kept.append(segment)
    return "/" + "/".join(kept)


def joined(*parts: str) -> str:
    """Path prefixes and a route path joined as Express joins a mounted router's paths."""
    found = ""
    for part in parts:
        if part and part != "/":
            found = found.rstrip("/") + "/" + part.strip("/")
    return found or "/"
