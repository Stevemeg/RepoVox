"""Architecture-agnostic graph extraction. No named pattern decides whether a graph exists.

Components are things the source itself defines or reaches: functions, classes and their
constructed parts, declared routes, external resources reached through an imported client
library, and source files. Relationships are static: a value returned by one component being
passed to another, an object handed to a constructor, a call site, a declared route, a resolved
import, or a path literal that matches a declared route. Nothing here asserts runtime behavior.

Python, JavaScript, TypeScript and TSX are read by two readers, one per syntax family, that
produce the same scopes, call sites and values. Everything after reading is shared.
"""

import re
from dataclasses import dataclass, field, replace
from typing import Any

from tree_sitter import Node

from repovox.media import jsflow
from repovox.media.architecture import (
    Architecture,
    Citation,
    Component,
    Connection,
    Context,
    Flow,
    Status,
    Step,
    Unresolved,
    View,
)
from repovox.media.diagram import automatic
from repovox.media.pyflow import (
    SourceFile,
    arguments,
    descendants,
    flat,
    line,
    parameter_names,
    parameter_positions,
    text,
)
from repovox.media.raster import LayoutError

# Client libraries whose calls reach something outside the repository. This types the far
# end of a call; it is not an architecture detector.
RESOURCES = {
    "sqlite3": "database",
    "psycopg": "database",
    "psycopg2": "database",
    "sqlalchemy": "database",
    "pymongo": "database",
    "redis": "cache",
    "boto3": "object_storage",
    "kafka": "message_broker",
    "pika": "message_broker",
    "requests": "http_client",
    "httpx": "http_client",
    "aiohttp": "http_client",
}
# The same, for packages a JavaScript or TypeScript file imports or requires.
SCRIPT_RESOURCES = {
    "pg": "database",
    "mysql": "database",
    "mysql2": "database",
    "mongodb": "database",
    "mongoose": "database",
    "sqlite3": "database",
    "better-sqlite3": "database",
    "@prisma/client": "database",
    "redis": "cache",
    "ioredis": "cache",
    "@aws-sdk/client-s3": "object_storage",
    "kafkajs": "message_broker",
    "amqplib": "message_broker",
    "axios": "http_client",
    "node-fetch": "http_client",
    "got": "http_client",
}
# The platform's global request function, when nothing in the file rebinds the name.
GLOBAL_FETCH = "fetch"
KINDS = {**RESOURCES, **SCRIPT_RESOURCES, GLOBAL_FETCH: "http_client"}
BUILTINS = set(
    "len range print str int float list dict set tuple enumerate zip sorted isinstance open min "
    "max sum any all super getattr hasattr type bool map filter repr format round abs iter next "
    "ValueError TypeError KeyError RuntimeError Exception reversed vars id".split()
)
SCRIPT_BUILTINS = set(
    "require parseInt parseFloat isNaN isFinite String Number Boolean Array Object Symbol BigInt "
    "Date Promise Error TypeError RangeError Map Set WeakMap WeakSet RegExp setTimeout "
    "setInterval clearTimeout clearInterval queueMicrotask structuredClone encodeURIComponent "
    "decodeURIComponent encodeURI decodeURI URL URLSearchParams Request Response Headers "
    "FormData Blob TextEncoder TextDecoder AbortController".split()
)
MUTATORS = {"append", "extend", "add", "update", "put", "send", "insert"}
SCRIPT_MUTATORS = {"push", "unshift", "add", "set", "append"}
ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
ROUTE = re.compile(r"""@(\w+)\.(get|post|put|patch|delete)\(\s*["']([^"']+)["']""")
# Python router objects, by the package that exports their constructor, and the keyword that
# gives the prefix every route declared on one starts with.
PY_ROUTERS = {"fastapi": {"APIRouter": "prefix"}, "flask": {"Blueprint": "url_prefix"}}
FLASK_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
URL = re.compile(r"""["'`](?:https?://[^/"'`\s]+)?(/[A-Za-z0-9_\-./]*)["'`]""")
MAX_NODES = 10
OVERVIEW_FILES = 9  # Files the file-level system overview can show.


@dataclass
class Definition:
    id: str
    path: str
    name: str
    kind: str  # function | class | method
    line: int
    node: Node
    parameters: list[str]
    owner: str | None = None
    # Line declaring each parameter: a signature can span lines after `def name(`.
    param_lines: dict[str, int] = field(default_factory=dict)
    anchor: str = ""  # Text on the declaring line that shows this definition.
    exported: bool = False
    default: bool = False
    inline: bool = False  # A function written in place, such as a route handler argument.


@dataclass(frozen=True)
class Producer:
    component: str
    name: str  # The token to find on the cited line: a variable or a callee.
    direct: bool
    instance: bool = False


@dataclass
class Site:
    target: str
    callee: str
    line: int
    uses: list[tuple[Producer, int]]


@dataclass(frozen=True)
class Route:
    """One declared route: the lines that together show it, and the handler it names.

    A route declared in one place (`app.get("/items", ...)`, a decorator) is cited on that
    line. A route on a mounted Express router is cited on its own line and on every mount
    line that adds a prefix, and anchored on each path part those lines show. A Next.js route
    handler is cited on the line exporting its method; its path is read from where the file
    is, as the App Router reads it.
    """

    method: str
    path: str
    cited: tuple[tuple[str, int], ...]
    anchors: tuple[str, ...]
    note: str = "declared route"
    # Whether a request path literal may be matched to it: not when a prefix is unknown.
    matchable: bool = True
    handler: str = ""  # The handler's definition id, once resolved.
    def_line: int = 0
    label: str = ""  # What the route card shows, when it differs from `method path`.


@dataclass
class FlowScope:
    key: str
    path: str
    name: str
    line: int
    sites: list[Site] = field(default_factory=list)
    returns: list[tuple[Producer, int]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    param_lines: dict[str, int] = field(default_factory=dict)


Snapshot = tuple[dict[str, Component], dict[str, Connection], dict[str, str], dict[str, int]]


def titled(lead_text: str, path: str, limit: int = 50) -> str:
    """`lead_text` and as much of `path` as fits, keeping its end: never cut mid-word."""
    room = limit - len(lead_text)
    parts = path.split("/")
    while len(parts) > 1 and len("/".join(parts)) > room:
        parts = parts[1:]
    tail = "/".join(parts)
    if len(tail) > room:
        tail = "..." + tail[len(tail) - max(1, room - 3) :]
    return f"{lead_text}{tail}"


def whole(lead_text: str, names: list[str], limit: int = 40) -> str:
    """`lead_text` and as many whole names as fit; never a name cut short."""
    shown: list[str] = []
    for name in names:
        if len(lead_text + ", ".join([*shown, name])) > limit and shown:
            break
        shown.append(name)
    return (lead_text + ", ".join(shown))[:limit]


def takes(parameters: list[str]) -> str:
    return whole("takes ", parameters)


def route_words(component: Component) -> str:
    """A route card's full method and path; its label may be cut to fit the card."""
    path = component.anchors[0] if component.anchors else ""
    method = component.label.split(" ", 1)[0]
    whole_text = f"{method} {path}"
    if component.kind == "endpoint" and whole_text.startswith(component.label):
        return whole_text  # The label is this text cut to the card's 28 characters.
    return component.label


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "x"


def lead(callee: str) -> str:
    """The callee text before its first call, on its first line: what the call line shows."""
    return callee.split("(")[0].split("\n")[0].strip()


def shown(citations: list[Citation | None], anchors: tuple[str, ...]) -> bool:
    """The validator's rule: the cited lines together contain every name an element claims."""
    joined = " ".join(c.quote for c in citations if c is not None)
    return all(not anchor or anchor in joined for anchor in anchors)


def package(name: str) -> str:
    """The package a JavaScript module specifier names: `pg/lib/x` -> pg, `@a/b/c` -> @a/b."""
    parts = name.split("/")
    return "/".join(parts[:2]) if name.startswith("@") else parts[0]


class Repo:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.defs: dict[str, Definition] = {}
        self.bindings: dict[str, dict[str, str]] = {}
        self.aliases: dict[str, dict[str, str]] = {}
        self.externals: dict[str, dict[str, str]] = {}
        self.parts: dict[str, dict[str, tuple[str, str, int]]] = {}
        self.scopes: dict[str, FlowScope] = {}
        # Component keys whose binding the analyzer's stricter rules did not confirm.
        self.weak: set[str] = set()
        # JavaScript and TypeScript only: what each module exports (exported name -> local
        # definition), aliases bound by `require`, every name a file declares with a count,
        # functions written in place as route handlers, and the routes the analyzer found.
        self.exports: dict[str, dict[str, str]] = {}
        self.export_lines: dict[str, dict[str, int]] = {}
        self.required: set[tuple[str, str]] = set()
        self.declared: dict[str, dict[str, int]] = {}
        self.inline: dict[tuple[int, int], str] = {}
        self.spans: dict[str, set[tuple[int, int]]] = {}  # Byte ranges of top-level definitions.
        self.script_routes: dict[str, list[tuple[Route, Node | None]]] = {}
        # CommonJS: the names `module.exports` / `exports.name` give (exported -> local name),
        # and the local name `module.exports` itself is set to.
        self.commonjs: dict[str, dict[str, str]] = {}
        self.module_value: dict[str, str] = {}
        # What each JavaScript or TypeScript import binds: local -> (module, member, require).
        self.imported: dict[str, dict[str, tuple[str, str | None, bool]]] = {}
        # Express: application objects the analyzer bound to `express()`, routers constructed
        # through the imported `express` package (name -> line), routes declared on a router,
        # and `use(...)` mounts.
        self.apps: dict[str, set[str]] = {}
        self.routers: dict[str, dict[str, int]] = {}
        self.router_calls: dict[tuple[str, str], list[jsflow.RouteCall]] = {}
        self.mounts: list[tuple[str, jsflow.RouteCall]] = []
        # Module-level names bound once to a constructed instance or a client handle.
        self.module_instances: dict[str, dict[str, str]] = {}
        self.module_env: dict[str, dict[str, list[Producer]]] = {}
        symbols = ctx.all_symbols
        self.by_path: dict[str, list[dict[str, Any]]] = {}
        for item in symbols.values():
            self.by_path.setdefault(item["path"], []).append(item)
        for candidate in ctx.payload["knowledge"]["entrypoints"]["candidates"]:
            made = symbols[candidate["symbol_id"]]
            if candidate["rule"] == "framework-construction-v1" and made.get("binding"):
                self.apps.setdefault(candidate["path"], set()).add(made["binding"])
        # Resolved imports between files, to tell a cyclic `require` apart as the analyzer does.
        self.links: dict[str, set[str]] = {}
        for edge in ctx.payload["knowledge"]["edges"]:
            if edge["relationship"] == "imports" and edge["classification"] == "resolved_static":
                source, target = symbols[edge["source"]]["path"], symbols[edge["target"]]["path"]
                self.links.setdefault(source, set()).add(target)
        for path, file in ctx.files.items():
            if file.valid:
                (self.index if file.python else self.index_script)(path, file)
        for edge in ctx.payload["knowledge"]["edges"]:
            if edge["classification"] != "resolved_static":
                continue
            if edge["relationship"] == "imports_symbol":
                source, target = symbols[edge["source"]], symbols[edge["target"]]
                local = source["syntax"]["local_binding"] or source["syntax"]["imported_member"]
                found = f"{target['path']}::{target['name']}"
                if local and found in self.defs:
                    self.bindings.setdefault(source["path"], {})[local] = found
            elif edge["relationship"] == "imports":
                for support in edge["support_ids"]:
                    item = symbols[support]
                    if item["kind"] != "import" or item["syntax"]["imported_member"]:
                        continue
                    module = symbols[edge["target"]]["path"]
                    if self.script(item["path"]):
                        # `import * as m` or `const m = require(...)`: a plain local name only.
                        alias = item["syntax"]["local_binding"] or ""
                        if not jsflow.IDENTIFIER.fullmatch(alias):
                            continue
                        node = self.node(item)
                        if node is not None and node.type == "call_expression":
                            self.required.add((item["path"], alias))
                    else:
                        alias = item["syntax"]["local_binding"] or item["name"].split(".")[-1]
                    self.aliases.setdefault(item["path"], {})[alias] = module
        modules = {
            (symbols[e["support_ids"][0]]["path"], symbols[e["support_ids"][0]]["name"]): symbols[
                e["target"]
            ]["path"]
            for e in ctx.payload["knowledge"]["edges"]
            if e["relationship"] == "imports" and e["classification"] == "resolved_static"
        }
        self.modules = modules
        for item in symbols.values():
            if item["kind"] in {"function", "class"} and item["syntax"]["unsafe_binding"]:
                self.weak.add(f"{item['path']}::{item['name']}")
            if item["kind"] != "import" or item["path"] not in ctx.files:
                continue
            if self.script(item["path"]):
                self.script_import(item, modules.get((item["path"], item["name"])))
                continue
            syntax = item["syntax"]
            local = syntax["local_binding"] or syntax["imported_member"]
            root = item["name"].lstrip(".").split(".")[0]
            if root in RESOURCES:
                self.externals.setdefault(item["path"], {})[local or root] = root
                if syntax["unsafe_binding"]:
                    self.weak.add(f"resource::{root}")
            module = modules.get((item["path"], item["name"]))
            found = f"{module}::{syntax['imported_member']}" if module else ""
            if local and found in self.defs and local not in self.bindings.get(item["path"], {}):
                # Unique top-level definition in a resolved local module: a syntactic
                # binding the analyzer did not confirm, so everything through it is inferred.
                self.bindings.setdefault(item["path"], {})[local] = found
                self.weak.add(found)
        self.mount()
        for path, file in ctx.files.items():
            if file.valid:
                (self.classes if file.python else self.script_classes)(path, file)
        for path, file in ctx.files.items():
            if not file.valid:
                continue
            reader = Reader if file.python else ScriptReader
            module = reader(self, file, FlowScope(f"{path}::<module>", path, "<module>", 1))
            module.run(file.root)
            if not file.python:
                self.module_level(path, module)
            for definition in [d for d in self.defs.values() if d.path == path]:
                if definition.kind == "class":
                    continue
                body = definition.node.child_by_field_name("body")
                scope = FlowScope(
                    definition.id,
                    path,
                    definition.name,
                    definition.line,
                    param_lines=definition.param_lines,
                )
                if body is not None:
                    reader(self, file, scope, definition).run(body)

    def script(self, path: str) -> bool:
        file = self.ctx.files.get(path)
        return file is not None and not file.python

    def node(self, item: dict[str, Any]) -> Node | None:
        """The syntax node an analyzer symbol was recorded for, matched by exact byte range."""
        file = self.ctx.files.get(item["path"])
        if file is None:
            return None
        found = file.root.descendant_for_byte_range(item["start_byte"], item["end_byte"])
        if found is None or (found.start_byte, found.end_byte) != (
            item["start_byte"],
            item["end_byte"],
        ):
            return None
        return found

    def script_import(self, item: dict[str, Any], module: str | None) -> None:
        """Bindings one JavaScript or TypeScript import or `require` creates."""
        path, syntax = item["path"], item["syntax"]
        if syntax["type_only"]:
            return  # `import type`: erased at compile time, never called or constructed.
        local, member = syntax["local_binding"] or "", syntax["imported_member"]
        node = self.node(item)
        commonjs = node is not None and node.type == "call_expression"
        pairs: list[tuple[str, str | None]] = []
        if jsflow.IDENTIFIER.fullmatch(local):
            pairs = [(local, member)]
        elif node is not None and commonjs:
            # `const { a, b: c } = require(...)`: each destructured member is its own name.
            pairs = list(jsflow.destructured(node, self.ctx.files[path].body))
        root = package(item["name"])
        if not item["name"].startswith(".") and root in SCRIPT_RESOURCES:
            for name, _ in pairs:
                self.externals.setdefault(path, {})[name] = root
            if syntax["unsafe_binding"]:
                self.weak.add(f"resource::{root}")
            return
        if module is None or module not in self.exports:
            return
        for name, wanted in pairs:
            self.imported.setdefault(path, {})[name] = (module, wanted, commonjs)
            if name in self.bindings.get(path, {}):
                continue  # A binding the analyzer confirmed is kept.
            confirmed = False
            if commonjs:
                record = self.commonjs.get(module)
                if wanted is None:
                    # `const name = require(...)`: the module value. The analyzer counts the
                    # declaration as a write, so it never confirms this binding.
                    target = self.module_value.get(module, "")
                elif record is not None:
                    # `const { name } = require(...)` of a member `module.exports` names:
                    # confirmed when the analyzer confirms the destructuring binding, the
                    # import is not cyclic, and nothing else in this file assigns the name.
                    target = record.get(wanted, "")
                    confirmed = (
                        not syntax["unsafe_binding"]
                        and self.declared.get(path, {}).get(name) == 1
                        and not self.cyclic(path, module)
                    )
                else:
                    target = wanted  # No `module.exports` was read: a top-level name only.
            elif wanted is None:
                continue  # A namespace import is an alias, read member by member.
            else:
                target = self.exported(module, wanted)[0]
            found = f"{module}::{target}"
            if target and found in self.defs and self.defs[found].owner is None:
                # Exported in a resolved local module. Unless confirmed above, the analyzer's
                # stricter rules did not confirm the binding: inferred.
                self.bindings.setdefault(path, {})[name] = found
                if not confirmed:
                    self.weak.add(found)

    def exported(self, module: str, name: str) -> tuple[str, bool]:
        """The local name a module exports as `name`, and whether only CommonJS says so."""
        if name in self.exports.get(module, {}):
            return self.exports[module][name], False
        if name == "default" and module in self.module_value:
            return self.module_value[module], True  # `import x from` a CommonJS module.
        return self.commonjs.get(module, {}).get(name, ""), True

    def cyclic(self, source: str, target: str) -> bool:
        """Whether `target` reaches `source` again through resolved imports."""
        seen: set[str] = set()
        pending = [target]
        while pending:
            current = pending.pop()
            if current == source or len(seen) > 1024:
                return True
            if current not in seen:
                seen.add(current)
                pending.extend(self.links.get(current, set()) - seen)
        return False

    def member(self, path: str, alias: str, module: str, name: str) -> str | None:
        """The definition `alias.name` reaches through a namespace import or a `require`."""
        if (path, alias) in self.required:
            record = self.commonjs.get(module)
            target = record.get(name, "") if record is not None else name
            found = f"{module}::{target}"
            if target and found in self.defs and self.defs[found].owner is None:
                # Through a whole-module `require`, which the analyzer never confirms.
                self.weak.add(found)
                return found
            return None
        target, commonjs = self.exported(module, name)
        found = f"{module}::{target}"
        if not target or found not in self.defs:
            return None
        if commonjs:
            self.weak.add(found)  # A CommonJS member reached through an ESM namespace.
        return found

    def module_level(self, path: str, reader: "Reader") -> None:
        """Module names bound once to an instance or a client handle, visible to functions."""
        counts = self.declared.get(path, {})
        once = {name for name, count in counts.items() if count == 1}
        self.module_instances[path] = {
            name: component for name, component in reader.instances.items() if name in once
        }
        self.module_env[path] = {
            name: producers
            for name, producers in reader.env.items()
            if name in once
            and producers
            and all(p.direct and p.component.startswith("resource::") for p in producers)
        }

    def index(self, path: str, file: SourceFile) -> None:
        local: dict[str, str] = {}
        for child in file.root.named_children:
            node = (
                child.child_by_field_name("definition")
                if child.type == "decorated_definition"
                else child
            )
            if node is None or node.type not in {"function_definition", "class_definition"}:
                continue
            name = text(node.child_by_field_name("name"), file.body)
            kind = "function" if node.type == "function_definition" else "class"
            identity = f"{path}::{name}"
            if identity in self.defs:
                local.pop(name, None)  # Defined twice: not a unique binding.
                continue
            params = parameter_names(node, file.body) if kind == "function" else []
            self.defs[identity] = Definition(
                identity,
                path,
                name,
                kind,
                line(node),
                node,
                params,
                param_lines=parameter_positions(node, file.body) if kind == "function" else {},
                anchor=f"{'class' if kind == 'class' else 'def'} {name}",
            )
            local[name] = identity
            if kind == "class":
                block = node.child_by_field_name("body")
                for member in block.named_children if block is not None else []:
                    inner = (
                        member.child_by_field_name("definition")
                        if member.type == "decorated_definition"
                        else member
                    )
                    if inner is not None and inner.type == "function_definition":
                        method = text(inner.child_by_field_name("name"), file.body)
                        self.defs[f"{identity}.{method}"] = Definition(
                            f"{identity}.{method}",
                            path,
                            f"{name}.{method}",
                            "method",
                            line(inner),
                            inner,
                            parameter_names(inner, file.body)[1:],
                            identity,
                            parameter_positions(inner, file.body),
                            anchor=f"def {method}",
                        )
        self.bindings.setdefault(path, {}).update(local)

    def index_script(self, path: str, file: SourceFile) -> None:
        """Top-level functions, classes and their methods in one JavaScript or TypeScript file.

        A definition is cited on the line that names it, and anchored on text that line shows.
        """
        body = file.body
        local: dict[str, str] = {}
        exports: dict[str, str] = {}
        lines = self.export_lines.setdefault(path, {})
        self.declared[path] = jsflow.declared_names(file.root, body)
        for item in jsflow.declarations(file.root):
            name = text(item.name, body)
            identity = f"{path}::{name}"
            if item.exported:
                exports[name] = name
                lines.setdefault(name, line(item.name))
            if item.default:
                exports["default"] = name
            self.spans.setdefault(path, set()).add((item.node.start_byte, item.node.end_byte))
            if identity in self.defs:
                local.pop(name, None)  # Declared twice: not a unique binding.
                continue
            number = line(item.name)
            preferred = {
                "function_declaration": f"function {name}",
                "class_declaration": f"class {name}",
            }.get(item.node.type, f"{name} =")
            functional = item.kind == "function"
            self.defs[identity] = Definition(
                identity,
                path,
                name,
                item.kind,
                number,
                item.node,
                jsflow.parameter_names(item.node, body) if functional else [],
                param_lines=jsflow.parameter_positions(item.node, body) if functional else {},
                anchor=preferred if preferred in file.quote(number) else name,
                exported=item.exported,
                default=item.default,
            )
            local[name] = identity
            if item.kind == "class":
                self.methods(path, body, identity, name, item.node)
        for child in file.root.named_children:
            if child.type != "export_statement" or child.child_by_field_name("source"):
                continue
            for clause in (c for c in child.named_children if c.type == "export_clause"):
                for specifier in clause.named_children:
                    original = text(specifier.child_by_field_name("name"), body)
                    exported = text(specifier.child_by_field_name("alias"), body) or original
                    if original:
                        exports[exported] = original
                        lines.setdefault(exported, line(specifier))
            value = child.child_by_field_name("value")
            if value is not None and value.type == "identifier":
                exports["default"] = text(value, body)  # `export default name;`
        self.exports[path] = exports
        self.bindings.setdefault(path, {}).update(local)
        self.common(path, file)
        self.find_routers(path, file, exports)
        self.handlers(path, file)
        self.next_routes(path)

    def methods(self, path: str, body: bytes, identity: str, name: str, cls: Node) -> None:
        """The methods one JavaScript or TypeScript class declares, each its own definition."""
        for member, label in jsflow.methods(cls):
            method = text(label, body)
            key = f"{identity}.{method}"
            if key in self.defs:
                continue  # An accessor pair or a repeated name: the first is kept.
            self.defs[key] = Definition(
                key,
                path,
                f"{name}.{method}",
                "method",
                line(label),
                member,
                jsflow.parameter_names(member, body),
                identity,
                jsflow.parameter_positions(member, body),
                anchor=method,
            )

    def common(self, path: str, file: SourceFile) -> None:
        """What `module.exports` and `exports.name` give, read as declared syntax.

        A name exported through an identifier refers to the file's own declaration of it. A
        function or class written in place becomes its own definition, named after what it
        is exported as; the analyzer binds no declaration to it, so it is always inferred.
        A file that rebinds `module` or `exports`, or assigns `module.exports` twice, is not
        read: what it exports is then not settled by its syntax.
        """
        body, counts = file.body, self.declared[path]
        if counts.get("module") or counts.get("exports"):
            return
        found = jsflow.commonjs_exports(file.root, body)
        if not found:
            return
        record: dict[str, str] = {}
        for item in found:
            if item.value.type in {"identifier", "shorthand_property_identifier"}:
                target = text(item.value, body)
            else:
                target = self.placed(path, body, item)
            if not target:
                continue
            if item.name is None:
                self.module_value[path] = target
            else:
                record[item.name] = target
        self.commonjs[path] = record

    def placed(self, path: str, body: bytes, item: jsflow.CommonExport) -> str:
        """A definition for a function or class written in place as a CommonJS export."""
        value = item.value
        own = value.child_by_field_name("name") if value.type != "method_definition" else None
        name = item.name or (text(own, body) if own is not None else "")
        identity = f"{path}::{name}"
        if not jsflow.IDENTIFIER.fullmatch(name) or identity in self.defs:
            return ""  # Unnamed, or a second definition of a name: not a unique binding.
        kind = "class" if value.type == "class" else "function"
        functional = kind == "function"
        self.defs[identity] = Definition(
            identity,
            path,
            name,
            kind,
            line(item.key) if item.name else line(own or value),
            value,
            jsflow.parameter_names(value, body) if functional else [],
            param_lines=jsflow.parameter_positions(value, body) if functional else {},
            anchor=name,
            exported=True,
        )
        self.spans.setdefault(path, set()).add((value.start_byte, value.end_byte))
        self.weak.add(identity)
        if kind == "class":
            self.methods(path, body, identity, name, value)
        return name

    def find_routers(self, path: str, file: SourceFile, exports: dict[str, str]) -> None:
        """Express routers this file constructs, the routes declared on them, and its mounts.

        A router is a top-level name, declared once, set to `Router()` reached through the
        `express` package as the analyzer recorded its import: `express.Router()` for the
        module, or `Router()` imported or destructured from it. Only statements written
        directly in the file are read.
        """
        body = file.body
        factories: set[str] = set()
        for item in self.by_path.get(path, []):
            syntax = item.get("syntax", {})
            if item["kind"] != "import" or item["name"] != "express" or syntax["type_only"]:
                continue
            local, member = syntax["local_binding"] or "", syntax["imported_member"]
            node = self.node(item)
            if jsflow.IDENTIFIER.fullmatch(local) and member in {None, "default"}:
                factories.add(f"{local}.Router")
            elif jsflow.IDENTIFIER.fullmatch(local) and member == "Router":
                factories.add(local)
            elif node is not None and node.type == "call_expression":
                factories |= {n for n, m in jsflow.destructured(node, body) if m == "Router"}
        counts = self.declared[path]
        mine: dict[str, int] = {}
        for name, value, exported in jsflow.top_level_values(file.root) if factories else []:
            inner = jsflow.unwrap(value)
            made = jsflow.callee(inner) if inner.type in jsflow.CALLS else None
            label = text(name, body)
            if made is None or re.sub(r"\s+", "", text(made, body)) not in factories:
                continue
            if counts.get(label) == 1:
                mine[label] = line(name)
                if exported:
                    exports.setdefault(label, label)
                    self.export_lines[path].setdefault(label, line(name))
        self.routers[path] = mine
        for call in jsflow.top_level_calls(file.root):
            found = jsflow.route_call(call, body)
            if found is not None and found.method == "use":
                self.mounts.append((path, found))
            elif found is not None and found.owner in mine:
                self.router_calls.setdefault((path, found.owner), []).append(found)

    def handlers(self, path: str, file: SourceFile) -> None:
        """Route declarations the analyzer found here; functions written in place get a name.

        Only calls the analyzer recorded as framework routes count, matched by byte range, so
        the application object they are declared on is the one it bound. The analyzer also
        records a `Router()` imported from `express` as an application; a route on a router
        is read once, by `mount()`, with the prefixes its mounts add.
        """
        wanted = {
            (s["start_byte"], s["end_byte"])
            for c in self.ctx.payload["knowledge"]["entrypoints"]["candidates"]
            if c["rule"] == "framework-route-v1" and c["path"] == path
            for s in [self.ctx.all_symbols[c["symbol_id"]]]
        }
        body = file.body
        stack = [file.root]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.named_children))
            if node.type != "call_expression" or (node.start_byte, node.end_byte) not in wanted:
                continue
            function = node.child_by_field_name("function")
            if function is None or function.type != "member_expression":
                continue
            method = text(function.child_by_field_name("property"), body)
            values = jsflow.arguments(node)
            route = jsflow.string_value(values[0], body) if len(values) >= 2 else None
            if method not in ROUTE_METHODS or route is None or not route.startswith("/"):
                continue
            if text(function.child_by_field_name("object"), body) in self.routers.get(path, {}):
                continue
            handler = values[-1]  # Express runs any middleware first; the last is the handler.
            number = line(values[0])
            declared = Route(method.upper(), route, ((path, number),), (route,))
            self.script_routes.setdefault(path, []).append((declared, handler))
            self.written(path, body, handler, f"{method.upper()} {route} handler")

    def written(self, path: str, body: bytes, handler: Node, name: str) -> None:
        """A route handler written in place is its own definition, named after its route."""
        if handler.type not in {"arrow_function", "function_expression"}:
            return
        if (handler.start_byte, handler.end_byte) in self.inline:
            return  # One handler on a router mounted twice: named after its first route.
        identity = f"{path}::{name}"
        if identity in self.defs:
            identity += f" L{line(handler)}"
        first = jsflow.head(handler, body)
        self.defs[identity] = Definition(
            identity,
            path,
            name,
            "function",
            line(handler),
            handler,
            jsflow.parameter_names(handler, body),
            param_lines=jsflow.parameter_positions(handler, body),
            anchor="=>" if "=>" in first else first[:40],
            inline=True,
        )
        self.inline[(handler.start_byte, handler.end_byte)] = identity

    def next_routes(self, path: str) -> None:
        """Next.js App Router route handlers: `export async function GET(...)` in `route.ts`.

        The file must sit inside an `app` directory and the repository must show it is a
        Next.js application: the file imports `next`, or a `package.json` above it declares
        the `next` dependency. Its path is read from its location, as the App Router reads it.
        """
        route = jsflow.app_route(path)
        if route is None or not self.uses_next(path):
            return
        for method in jsflow.HTTP_METHODS:
            exported = method.upper()
            local = self.exports.get(path, {}).get(exported, "")
            identity = f"{path}::{local}"
            if not local or identity not in self.defs or self.defs[identity].kind != "function":
                continue
            number = self.export_lines[path].get(exported, self.defs[identity].line)
            declared = Route(
                exported,
                route,
                ((path, number),),
                (exported,),
                "file-system route",
                handler=identity,
            )
            self.script_routes.setdefault(path, []).append((declared, None))

    def uses_next(self, path: str) -> bool:
        for item in self.by_path.get(path, []):
            if item["kind"] == "import" and (
                item["name"] == "next" or item["name"].startswith("next/")
            ):
                return True
        for item in self.ctx.all_symbols.values():
            if (
                item["kind"] == "declared_dependency"
                and item["path"].endswith("package.json")
                and item.get("syntax", {}).get("qualified_name") == "dependencies.next"
            ):
                folder = item["path"].rpartition("/")[0]
                if not folder or path.startswith(folder + "/"):
                    return True
        return False

    def mount(self) -> None:
        """Routes declared on Express routers, with the prefix each chain of mounts adds.

        `app.use("/users", users)` mounts a router on the application object the analyzer
        bound; `router.use("/admin", admin)` mounts one router on another. The router mounted
        is a router of this file, or one a resolved import names: the module value of a
        `require`, a default or named export, or a member of a required module. A router no
        mount reaches keeps its own paths and is not matched to request literals.
        """
        Mount = tuple[str, jsflow.RouteCall]  # The file of a `use(...)` call, and the call.
        parents: dict[tuple[str, str], list[tuple[tuple[str, str] | None, Mount]]] = {}
        tests = {p for p, e in self.ctx.manifest.items() if e.get("classification") == "test"}
        for path, call in self.mounts:
            if path in tests:
                continue
            parent: tuple[str, str] | None
            if call.owner in self.routers.get(path, {}):
                parent = (path, call.owner)
            elif call.owner in self.apps.get(path, set()):
                parent = None
            else:
                continue
            target = self.router_ref(path, call.target)
            if target is not None and target != parent:
                parents.setdefault(target, []).append((parent, (path, call)))

        def chains(ref: tuple[str, str], seen: frozenset[tuple[str, str]]) -> list[list[Mount]]:
            """Mounts from the application down to `ref`, outermost first; at most four."""
            found: list[list[Mount]] = []
            for parent, mount in parents.get(ref, []):
                if parent is None:
                    found.append([mount])
                elif parent not in seen and len(seen) < 4:
                    found += [[*chain, mount] for chain in chains(parent, seen | {parent})]
            return found[:4]

        for (path, router), calls in self.router_calls.items():
            mounted = chains((path, router), frozenset({(path, router)}))
            for call in calls:
                for chain in mounted or [[]]:
                    full = jsflow.joined(*(c.path for _, c in chain), call.path)
                    declared = Route(
                        call.method.upper(),
                        full,
                        ((path, call.line), *((where, c.line) for where, c in chain)),
                        (call.path, *(c.path for _, c in chain if c.path)),
                        "mounted route" if chain else "router route",
                        matchable=bool(chain),
                    )
                    self.script_routes.setdefault(path, []).append((declared, call.target))
                    name = f"{call.method.upper()} {full} handler"
                    self.written(path, self.ctx.files[path].body, call.target, name)

    def router_ref(self, path: str, node: Node) -> tuple[str, str] | None:
        """The router (file, name) a mounted value names, if the source binds one."""
        body = self.ctx.files[path].body
        node = jsflow.unwrap(node)
        if node.type == "identifier":
            name = text(node, body)
            if name in self.routers.get(path, {}):
                return path, name
            found = self.imported.get(path, {}).get(name)
            if found is None:
                return None
            module, member, commonjs = found
            wanted = "default" if member is None and commonjs else member
            return self.exported_router(module, wanted) if wanted else None
        if node.type == "member_expression":
            owner = node.child_by_field_name("object")
            found = (
                self.imported.get(path, {}).get(text(owner, body))
                if owner is not None and owner.type == "identifier"
                else None
            )
            if found is None or found[1] is not None:
                return None  # Only a member of a whole module or a namespace.
            return self.exported_router(found[0], text(node.child_by_field_name("property"), body))
        if node.type == "call_expression":  # `require("./routes")` written in place.
            for item in self.by_path.get(path, []):
                if item["kind"] == "import" and (item["start_byte"], item["end_byte"]) == (
                    node.start_byte,
                    node.end_byte,
                ):
                    required = self.modules.get((path, item["name"]))
                    return self.exported_router(required, "default") if required else None
        return None

    def exported_router(self, module: str, name: str) -> tuple[str, str] | None:
        local = self.exported(module, name)[0]
        return (module, local) if local and local in self.routers.get(module, {}) else None

    def script_classes(self, path: str, file: SourceFile) -> None:
        """Parts a class constructs in its constructor: `this.x = new Something(...)`."""
        body = file.body
        for definition in [d for d in self.defs.values() if d.path == path and d.kind == "method"]:
            if not definition.name.endswith(".constructor") or definition.owner is None:
                continue
            block = definition.node.child_by_field_name("body")
            for statement in jsflow.flat(block) if block is not None else []:
                node = statement.named_children[0] if statement.named_child_count else None
                if node is None or node.type != "assignment_expression":
                    continue
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                right = jsflow.unwrap(right) if right is not None else None
                if left is None or right is None or left.type != "member_expression":
                    continue
                owner = left.child_by_field_name("object")
                made = jsflow.callee(right) if right.type in jsflow.CALLS else None
                if owner is None or owner.type != "this" or made is None:
                    continue
                attribute = text(left.child_by_field_name("property"), body)
                callee = text(made, body)
                bound = self.bindings.get(path, {}).get(callee)
                kind = self.defs[bound].name if bound else re.sub(r"\s+", "", callee)
                self.parts.setdefault(definition.owner, {})[attribute] = (
                    bound or "",
                    kind,
                    line(node),
                )

    def classes(self, path: str, file: SourceFile) -> None:
        """Parts a class constructs in __init__: `self.x = Something(...)`."""
        for definition in [d for d in self.defs.values() if d.path == path and d.kind == "method"]:
            if not definition.name.endswith(".__init__") or definition.owner is None:
                continue
            block = definition.node.child_by_field_name("body")
            for statement in flat(block) if block is not None else []:
                node = statement.named_children[0] if statement.named_child_count else None
                if node is None or node.type != "assignment":
                    continue
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                if (
                    left is None
                    or right is None
                    or left.type != "attribute"
                    or right.type != "call"
                ):
                    continue
                if text(left.child_by_field_name("object"), file.body) != "self":
                    continue
                attribute = text(left.child_by_field_name("attribute"), file.body)
                callee = text(right.child_by_field_name("function"), file.body)
                bound = self.bindings.get(path, {}).get(callee)
                kind = self.defs[bound].name if bound else callee
                self.parts.setdefault(definition.owner, {})[attribute] = (
                    bound or "",
                    kind,
                    line(node),
                )


class Reader:
    """One scope, statements in source order. Unknown callees stay unknown."""

    def __init__(
        self, repo: Repo, file: SourceFile, scope: FlowScope, definition: Definition | None = None
    ) -> None:
        self.repo, self.file, self.scope, self.definition = repo, file, scope, definition
        self.env: dict[str, list[Producer]] = {}
        self.instances: dict[str, str] = {}
        self.resolved: dict[tuple[int, int], tuple[str, bool]] = {}
        for name in definition.parameters if definition else []:
            if name not in {"self", "cls"}:
                self.env[name] = [Producer(f"input::{name}", name, True)]
        repo.scopes[scope.key] = scope

    def run(self, block: Node) -> None:
        for statement in flat(block):
            if statement.type == "for_statement":
                left, right = (
                    statement.child_by_field_name("left"),
                    statement.child_by_field_name("right"),
                )
                if left is not None and right is not None:
                    self.calls(right)
                    found = self.producers(right)
                    for name_node in descendants(left):
                        if name_node.type == "identifier":
                            name = text(name_node, self.file.body)
                            self.bind(
                                name,
                                [Producer(p.component, name, False, p.instance) for p in found],
                            )
                continue
            if statement.type == "with_statement":
                for item in (
                    descendants(statement.named_children[0]) if statement.named_child_count else []
                ):
                    if item.type == "as_pattern" and item.named_child_count >= 2:
                        self.calls(item.named_children[0])
                        alias = [
                            n
                            for n in descendants(item.named_children[-1])
                            if n.type == "identifier"
                        ]
                        if alias:
                            self.assign(text(alias[0], self.file.body), item.named_children[0])
                continue
            node = statement.named_children[0] if statement.named_child_count else None
            if node is None:
                continue
            self.calls(node)
            if statement.type == "return_statement":
                # Only a returned name or a returned bound call is the value itself; anything
                # else (an unbound call, an expression) only derives from it.
                plain = node.type == "identifier" or (
                    node.type == "call" and (node.start_byte, node.end_byte) in self.resolved
                )
                for producer in self.producers(node):
                    used = (
                        producer
                        if plain
                        else Producer(producer.component, producer.name, False, producer.instance)
                    )
                    self.scope.returns.append((used, line(statement)))
            elif node.type == "assignment":
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                if left is not None and right is not None:
                    for name in (
                        [
                            text(n, self.file.body)
                            for n in descendants(left)
                            if n.type == "identifier"
                        ]
                        if left.type != "attribute"
                        else []
                    ):
                        self.assign(name, right)
            elif node.type == "call":
                function = node.child_by_field_name("function")
                if function is not None and function.type == "attribute":
                    owner = function.child_by_field_name("object")
                    name = text(function.child_by_field_name("attribute"), self.file.body)
                    if owner is not None and owner.type == "identifier" and name in MUTATORS:
                        positional, keywords = arguments(node)
                        target = text(owner, self.file.body)
                        added = [
                            Producer(p.component, target, False, p.instance)
                            for a in [*positional, *keywords.values()]
                            for p in self.producers(a)
                        ]
                        if added:
                            self.env[target] = [*self.env.get(target, []), *added]

    def bind(self, name: str, producers: list[Producer]) -> None:
        self.instances.pop(name, None)
        if producers:
            self.env[name] = list(dict.fromkeys(producers))
        else:
            self.env.pop(name, None)

    def assign(self, name: str, right: Node) -> None:
        while right.type in {"await", "parenthesized_expression"} and right.named_child_count == 1:
            right = right.named_children[0]
        found = (
            self.resolved.get((right.start_byte, right.end_byte)) if right.type == "call" else None
        )
        if found is not None:
            component, constructed = found
            self.bind(name, [Producer(component, name, True, constructed)])
            if constructed:
                self.instances[name] = component
            return
        self.bind(
            name, [Producer(p.component, name, False, p.instance) for p in self.producers(right)]
        )

    def target(self, function: Node) -> tuple[str, bool] | None:
        """Resolve a callee to a component id; None when the source does not bind it."""
        body, path = self.file.body, self.file.path
        callee = text(function, body)
        if function.type == "identifier":
            if callee in self.instances:
                return self.instances[callee], False
            if callee in self.env or (self.definition and callee in self.definition.parameters):
                return None  # A value or parameter being called: its definition is not bound.
            bound = self.repo.bindings.get(path, {}).get(callee)
            if bound:
                return bound, self.repo.defs[bound].kind == "class"
            if callee in self.repo.externals.get(path, {}):
                return f"resource::{self.repo.externals[path][callee]}", False
            if callee not in BUILTINS:
                self.scope.unresolved.append(callee)
            return None
        if function.type != "attribute":
            return None
        owner, name = (
            function.child_by_field_name("object"),
            text(function.child_by_field_name("attribute"), body),
        )
        if owner is None:
            return None
        base = text(owner, body)
        cls = self.definition.owner if self.definition else None
        if cls and base == "self" and name in self.repo.parts.get(cls, {}):
            return f"{cls}#{name}", False
        if (
            cls
            and owner.type == "attribute"
            and text(owner.child_by_field_name("object"), body) == "self"
        ):
            part = text(owner.child_by_field_name("attribute"), body)
            if part in self.repo.parts.get(cls, {}):
                return f"{cls}#{part}", False
        if owner.type != "identifier":
            return None
        if base in self.instances:
            return self.instances[base], False
        module = self.repo.aliases.get(path, {}).get(base)
        if module and f"{module}::{name}" in self.repo.defs:
            found = f"{module}::{name}"
            return found, self.repo.defs[found].kind == "class"
        if base in self.repo.externals.get(path, {}):
            return f"resource::{self.repo.externals[path][base]}", False
        held = [
            p for p in self.env.get(base, []) if p.component.startswith("resource::") and p.direct
        ]
        if held:
            return held[0].component, False  # A method on a handle returned by a client library.
        return None

    def calls(self, node: Node) -> None:
        for call in reversed(descendants(node)):
            function = call.child_by_field_name("function") if call.type == "call" else None
            found = self.target(function) if function is not None else None
            if found is None or function is None:
                continue
            self.resolved[(call.start_byte, call.end_byte)] = found
            positional, keywords = arguments(call)
            uses: list[tuple[Producer, int]] = []
            for argument in [*positional, *keywords.values()]:
                direct = argument.type in {"identifier", "call"}
                for producer in self.producers(argument):
                    used = (
                        producer
                        if direct
                        else Producer(producer.component, producer.name, False, producer.instance)
                    )
                    uses.append((used, self.where(argument, producer.name)))
            self.scope.sites.append(
                Site(found[0], text(function, self.file.body), line(call), uses)
            )

    def where(self, node: Node, token: str) -> int:
        for part in descendants(node):
            if part.type in {"identifier", "attribute", "call"} and text(
                part, self.file.body
            ).startswith(token):
                return line(part)
        return line(node)

    def producers(self, node: Node) -> list[Producer]:
        found: list[Producer] = []

        def visit(part: Node) -> None:
            key = (part.start_byte, part.end_byte)
            if part.type == "call" and key in self.resolved:
                component, constructed = self.resolved[key]
                callee = text(part.child_by_field_name("function"), self.file.body)
                found.append(Producer(component, callee, True, constructed))
                return
            if part.type == "identifier":
                found.extend(self.env.get(text(part, self.file.body), []))
                return
            if part.type == "attribute":
                owner = part.child_by_field_name("object")
                if owner is not None:
                    visit(owner)
                return
            if part.type == "keyword_argument":
                value = part.child_by_field_name("value")
                if value is not None:
                    visit(value)
                return
            for child in part.named_children:
                visit(child)

        visit(node)
        return list(dict.fromkeys(found))


class ScriptReader(Reader):
    """The same reading for JavaScript and TypeScript: one scope, statements in source order.

    A function written inline, such as a callback, is read as part of the scope that contains
    it, with its own parameters hiding outer names and without contributing returns; a route
    handler written inline is its own definition instead. JSX elements that use a component
    are call sites whose attribute values are the values passed.
    """

    def __init__(
        self,
        repo: Repo,
        file: SourceFile,
        scope: FlowScope,
        definition: Definition | None = None,
        outer: "ScriptReader | None" = None,
        hidden: tuple[str, ...] = (),
        arrow: bool = True,
    ) -> None:
        super().__init__(repo, file, scope, definition)
        self.returns = outer is None
        self.hidden = set(hidden)
        self.local: set[str] = set(hidden)
        self.owner = definition.owner if definition else None
        if outer is not None:
            self.env = {k: v for k, v in outer.env.items() if k not in self.hidden}
            self.instances = {k: v for k, v in outer.instances.items() if k not in self.hidden}
            self.local |= outer.local
            self.hidden |= outer.hidden - set(self.env)
            # Only an arrow function keeps the `this` of the method around it.
            self.owner = outer.owner if arrow else None
        elif definition is not None:
            mine = set(definition.parameters)
            path = file.path
            for name, component in repo.module_instances.get(path, {}).items():
                if name not in mine:
                    self.instances[name] = component
            for name, producers in repo.module_env.get(path, {}).items():
                if name not in mine:
                    self.env[name] = producers

    def run(self, block: Node) -> None:
        body = self.file.body
        if block.type not in {"statement_block", "program"}:
            # An expression body: the expression is the function's value.
            self.calls(block)
            parent = block.parent
            arrow = next((c for c in parent.children if c.type == "=>"), None) if parent else None
            if (
                self.returns
                and arrow is not None
                and arrow.start_point.row == block.start_point.row
            ):
                self.returned(block, line(block))
            return
        for statement in jsflow.flat(block):
            if statement.type == "for_in_statement":
                left, right = (
                    statement.child_by_field_name("left"),
                    statement.child_by_field_name("right"),
                )
                if left is not None and right is not None:
                    self.calls(right)
                    found = self.producers(right)
                    for ident in jsflow.pattern_names(left):
                        name = text(ident, body)
                        self.local.add(name)
                        self.bind(
                            name, [Producer(p.component, name, False, p.instance) for p in found]
                        )
                continue
            if statement.type in {"lexical_declaration", "variable_declaration"}:
                for declarator in statement.named_children:
                    if declarator.type == "variable_declarator":
                        self.declare(declarator)
                continue
            node = statement.named_children[0] if statement.named_child_count else None
            if node is None:
                continue
            self.calls(node)
            if statement.type == "return_statement":
                if self.returns:
                    self.returned(node, line(statement))
            elif node.type == "assignment_expression":
                left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
                if left is not None and right is not None and left.type != "member_expression":
                    self.destructure(left, right)
            else:
                self.mutation(jsflow.unwrap(node))

    def declare(self, declarator: Node) -> None:
        name, value = (
            declarator.child_by_field_name("name"),
            declarator.child_by_field_name("value"),
        )
        if name is None:
            return
        if value is not None and (value.start_byte, value.end_byte) in self.repo.spans.get(
            self.file.path, set()
        ):
            return  # A top-level definition, read as its own scope.
        inner = jsflow.unwrap(value) if value is not None else None
        function = inner.child_by_field_name("function") if inner is not None else None
        if (
            inner is not None
            and inner.type == "call_expression"
            and function is not None
            and text(function, self.file.body) == "require"
        ):
            return  # An import: what it binds is resolved from the analyzer's import facts.
        if value is None or value.type in jsflow.NESTED:
            for node in jsflow.pattern_names(name):
                self.local.add(text(node, self.file.body))
                self.bind(text(node, self.file.body), [])
            return
        self.calls(value)
        self.destructure(name, value)

    def destructure(self, left: Node, right: Node) -> None:
        body = self.file.body
        if left.type == "identifier":
            self.local.add(text(left, body))
            self.assign(text(left, body), right)
            return
        found = self.producers(right)  # Destructured: each name holds a part of the value.
        for node in jsflow.pattern_names(left):
            name = text(node, body)
            self.local.add(name)
            self.bind(name, [Producer(p.component, name, False, p.instance) for p in found])

    def mutation(self, node: Node) -> None:
        """`items.push(value)`: the collection now also holds what was added."""
        function = node.child_by_field_name("function") if node.type == "call_expression" else None
        if function is None or function.type != "member_expression":
            return
        owner = function.child_by_field_name("object")
        name = text(function.child_by_field_name("property"), self.file.body)
        if owner is None or owner.type != "identifier" or name not in SCRIPT_MUTATORS:
            return
        target = text(owner, self.file.body)
        added = [
            Producer(p.component, target, False, p.instance)
            for a in jsflow.arguments(node)
            for p in self.producers(a)
        ]
        if added:
            self.env[target] = [*self.env.get(target, []), *added]

    def returned(self, node: Node, number: int) -> None:
        inner = jsflow.unwrap(node)
        plain = inner.type == "identifier" or (
            inner.type in jsflow.CALLS and (inner.start_byte, inner.end_byte) in self.resolved
        )
        for producer in self.producers(node):
            used = (
                producer
                if plain
                else Producer(producer.component, producer.name, False, producer.instance)
            )
            self.scope.returns.append((used, number))

    def assign(self, name: str, right: Node) -> None:
        right = jsflow.unwrap(right)
        found = (
            self.resolved.get((right.start_byte, right.end_byte))
            if right.type in jsflow.CALLS
            else None
        )
        if found is not None:
            component, constructed = found
            self.bind(name, [Producer(component, name, True, constructed)])
            if constructed:
                self.instances[name] = component
            return
        self.bind(
            name, [Producer(p.component, name, False, p.instance) for p in self.producers(right)]
        )

    def bound(self, name: str) -> bool:
        """A name this scope binds to something, so a module-level definition is hidden."""
        return (
            name in self.env
            or name in self.local
            or name in self.hidden
            or (self.definition is not None and name in self.definition.parameters)
        )

    def target(self, function: Node) -> tuple[str, bool] | None:
        """Resolve a callee to a component id; None when the source does not bind it."""
        body, path, repo = self.file.body, self.file.path, self.repo
        if function.type == "identifier":
            callee = text(function, body)
            if callee in self.instances:
                return self.instances[callee], False
            if self.bound(callee):
                return None  # A value or parameter being called: its definition is not bound.
            found = repo.bindings.get(path, {}).get(callee)
            if found:
                return found, repo.defs[found].kind == "class"
            if callee in repo.externals.get(path, {}):
                return f"resource::{repo.externals[path][callee]}", False
            if callee == GLOBAL_FETCH and callee not in repo.declared.get(path, {}):
                return f"resource::{GLOBAL_FETCH}", False
            if callee not in SCRIPT_BUILTINS:
                self.scope.unresolved.append(callee)
            return None
        if function.type != "member_expression":
            return None
        owner = function.child_by_field_name("object")
        name = text(function.child_by_field_name("property"), body)
        if owner is None:
            return None
        parts = repo.parts.get(self.owner or "", {})
        if self.owner and owner.type == "this" and name in parts:
            return f"{self.owner}#{name}", False
        if self.owner and owner.type == "member_expression":
            inner = owner.child_by_field_name("object")
            part = text(owner.child_by_field_name("property"), body)
            if inner is not None and inner.type == "this" and part in parts:
                return f"{self.owner}#{part}", False
        if owner.type != "identifier":
            return None
        base = text(owner, body)
        if base in self.instances:
            return self.instances[base], False
        if self.bound(base):
            held = [
                p
                for p in self.env.get(base, [])
                if p.component.startswith("resource::") and p.direct
            ]
            # A method on a handle a client library returned, or else an unbound value.
            return (held[0].component, False) if held else None
        module = repo.aliases.get(path, {}).get(base)
        found = repo.member(path, base, module, name) if module else None
        if found:
            return found, repo.defs[found].kind == "class"
        if base in repo.externals.get(path, {}):
            return f"resource::{repo.externals[path][base]}", False
        return None

    def calls(self, node: Node) -> None:
        body = self.file.body
        for call in reversed(jsflow.reachable(node)):
            if call.type in jsflow.NESTED:
                self.nested(call)
                continue
            element = call.type in jsflow.ELEMENTS
            if call.type not in jsflow.CALLS and not (
                element and jsflow.component_element(call, body)
            ):
                continue
            function = jsflow.callee(call)
            found = self.target(function) if function is not None else None
            if found is None or function is None:
                continue
            if not element:  # A JSX element is a use of a component, not a value from it.
                self.resolved[(call.start_byte, call.end_byte)] = found
            uses: list[tuple[Producer, int]] = []
            for argument in jsflow.arguments(call):
                inner = jsflow.unwrap(argument)
                direct = inner.type == "identifier" or (
                    inner.type in jsflow.CALLS
                    and (inner.start_byte, inner.end_byte) in self.resolved
                )
                for producer in self.producers(argument):
                    used = (
                        producer
                        if direct
                        else Producer(producer.component, producer.name, False, producer.instance)
                    )
                    uses.append((used, self.where(argument, producer.name)))
            self.scope.sites.append(Site(found[0], text(function, body), line(call), uses))

    def nested(self, function: Node) -> None:
        key = (function.start_byte, function.end_byte)
        if key in self.repo.inline or key in self.repo.spans.get(self.file.path, set()):
            return  # A route handler or an export written in place is its own definition.
        if function.type not in {"arrow_function", "function_expression", "method_definition"}:
            return
        block = function.child_by_field_name("body")
        if block is None:
            return
        hidden = tuple(jsflow.parameter_names(function, self.file.body))
        ScriptReader(
            self.repo,
            self.file,
            self.scope,
            self.definition,
            self,
            hidden,
            function.type == "arrow_function",
        ).run(block)

    def where(self, node: Node, token: str) -> int:
        for part in jsflow.reachable(node):
            if part.type in {
                "identifier",
                "member_expression",
                "call_expression",
                "shorthand_property_identifier",
            } and text(part, self.file.body).startswith(token):
                return line(part)
        return line(node)

    def producers(self, node: Node) -> list[Producer]:
        """Components whose values an expression holds, in source order (iteratively)."""
        found: list[Producer] = []
        body = self.file.body
        stack = [node]
        while stack:
            part = stack.pop()
            if part.type in jsflow.NESTED or part.type in jsflow.MARKUP:
                # A function value, or a JSX tree that describes markup, is not a value any
                # component produced. What a JSX element passes is read from its attributes.
                continue
            key = (part.start_byte, part.end_byte)
            if part.type in jsflow.CALLS and key in self.resolved:
                component, constructed = self.resolved[key]
                made = jsflow.callee(part)
                name = jsflow.head(made, body) if made is not None else ""
                found.append(Producer(component, name, True, constructed))
            elif part.type in {"identifier", "shorthand_property_identifier"}:
                if text(part, body) not in self.hidden:
                    found.extend(self.env.get(text(part, body), []))
            elif part.type in {"member_expression", "pair"}:
                inner = part.child_by_field_name(
                    "object" if part.type == "member_expression" else "value"
                )
                if inner is not None:
                    stack.append(inner)
            else:
                stack.extend(reversed(part.named_children))
        return list(dict.fromkeys(found))


class Graph:
    """Collects components and connections for one architecture; drops what cannot be cited."""

    def __init__(self, repo: Repo) -> None:
        self.repo, self.ctx = repo, repo.ctx
        self.components: dict[str, Component] = {}
        self.connections: dict[str, Connection] = {}
        self.ids: dict[str, str] = {}
        self.order: dict[str, int] = {}
        self.dropped = 0

    def identity(self, key: str, parent: str | None) -> str:
        return (parent + "__" if parent else "") + slug(key.split("::")[-1] if "::" in key else key)

    def quote(self, path: str, number: int) -> str:
        lines = self.ctx.lines.get(path, [])
        return lines[number - 1].strip()[:400] if 1 <= number <= len(lines) else ""

    def add(
        self, key: str, scope: FlowScope, at: int, parent: str | None = None, token: str = ""
    ) -> str | None:
        """Add the component a key names. Returns its id, or None if it has no verified citation.

        `token` is text the cited line shows when the component's own name is not on it, such
        as the local name a client class was imported as.
        """
        lookup = f"{parent}|{key}"
        if lookup in self.ids:
            return self.ids[lookup]
        repo, ctx = self.repo, self.ctx
        lines: tuple[str, ...] = ()
        if key.startswith("input::"):
            name = key.split("::")[1]
            kind, label, group = "input", name, scope.path
            # Cite the line that declares the parameter, which need not be the `def` line.
            citation = ctx.cite(scope.path, scope.param_lines.get(name, scope.line))
            anchor = name
        elif key == "output::":
            kind, label, group = "output", "result", scope.path
            key = "output::result"
            citation = ctx.cite(scope.path, at)
            # An expression-bodied arrow function returns without the keyword.
            anchor = "return" if "return" in self.quote(scope.path, at) else "=>"
        elif key.startswith("resource::"):
            root = key.split("::")[1]
            kind, label, group = KINDS[root], root, "external"
            citation = ctx.cite(scope.path, at)
            anchor = root if root in self.quote(scope.path, at) or not token else token
            lines = ("built-in function",) if root == GLOBAL_FETCH else ("client library",)
        elif "#" in key:
            owner, attribute = key.split("#")
            bound, made, number = repo.parts[owner][attribute]
            kind, label, group = "part", attribute, repo.defs[owner].path
            receiver = "self" if ctx.files[repo.defs[owner].path].python else "this"
            citation = ctx.cite(repo.defs[owner].path, number)
            anchor = f"{receiver}.{attribute}"
            lines = (made[:40],)
        else:
            definition = repo.defs[key]
            kind, label, group = definition.kind, definition.name, definition.path
            citation = ctx.cite(definition.path, definition.line)
            anchor = definition.anchor
            if kind == "function" and definition.parameters:
                lines = (takes(definition.parameters),)
            elif kind == "class":
                methods = sorted(
                    (
                        d.name.split(".")[-1]
                        for d in repo.defs.values()
                        if d.owner == key
                        and not d.name.endswith("__")
                        and not d.name.endswith(".constructor")
                    ),
                    key=lambda name: (name.startswith("_"), name),
                )
                lines = (whole("methods ", methods),) if methods else ()
        if citation is None or (anchor and anchor not in citation.quote):
            # The validator requires the cited line to show the element: never emit one
            # that it would reject.
            self.dropped += 1
            return None
        identity = self.identity(key, parent)
        while identity in self.components:
            identity += "_"
        self.components[identity] = Component(
            id=identity,
            role=kind,
            kind=kind,
            label=label[:28],
            lines=lines,
            status="INFERRED" if key in self.repo.weak else "VERIFIED",
            anchors=(anchor,),
            citations=(citation,),
            parent=parent,
            group=group[:60],
        )
        self.ids[lookup] = identity
        return identity

    def link(
        self,
        source: str,
        target: str,
        kind: str,
        label: str,
        basis: Any,
        status: Status,
        cited: list[tuple[str, int]],
        anchors: tuple[str, ...],
    ) -> str | None:
        if source == target:
            return None
        citations = [self.ctx.cite(path, number) for path, number in dict.fromkeys(cited)]
        if any(c is None for c in citations) or not citations or not shown(citations, anchors):
            self.dropped += 1
            return None
        if "INFERRED" in (self.components[source].status, self.components[target].status):
            status = "INFERRED"  # No stronger than the bindings it depends on.
        identity = f"{source}-{kind}-{target}"
        existing = self.connections.get(identity)
        if existing is not None:
            merged = tuple(dict.fromkeys([*existing.citations, *[c for c in citations if c]]))[:6]
            together = tuple(dict.fromkeys([*existing.anchors, *anchors]))
            if not shown(list(merged), together):
                return identity  # The extra site would not stay cited; keep what is shown.
            status = "VERIFIED" if "VERIFIED" in (existing.status, status) else status
            self.connections[identity] = existing.model_copy(
                update={"citations": merged, "status": status, "anchors": together}
            )
            return identity
        self.connections[identity] = Connection(
            id=identity,
            source=source,
            target=target,
            kind=kind,
            label=label[:40],
            phase="structure",
            basis=basis,
            status=status,
            anchors=anchors,
            citations=tuple(c for c in citations if c),
        )
        self.order[identity] = cited[0][1]
        return identity

    def position(self, connection: Connection) -> tuple[str, int, str]:
        """Narration and drawing order of a connection."""
        parent = self.components[connection.source].parent or ""
        return parent, self.order.get(connection.id, 0), connection.id

    def snapshot(self) -> Snapshot:
        return dict(self.components), dict(self.connections), dict(self.ids), dict(self.order)

    def fits(self, parent: str | None, before: Snapshot) -> bool:
        """Keep what was added since `before` only if its view can still be drawn.

        The view is laid out exactly as the diagram renderer will lay it out. When it no longer
        fits, everything added since `before` is undone and counted as left out, so a graph is
        never handed to the renderer with more than the diagram can place.
        """
        if self.drawable(parent):
            return True
        self.components, self.connections, self.ids, self.order = before
        self.dropped += 1
        return False

    def drawable(self, parent: str | None = None) -> bool:
        """Whether one view lays out exactly as the diagram renderer will lay it out."""
        members = [c for c in self.components.values() if c.parent == parent]
        inside = {c.id for c in members}
        links = sorted(
            (c for c in self.connections.values() if {c.source, c.target} <= inside),
            key=self.position,
        )
        try:
            automatic(members, links)
        except LayoutError:
            return False
        return True

    def remove(self, identity: str) -> None:
        """Take one component, and every connection touching it, out of the graph."""
        self.components.pop(identity, None)
        for key in [k for k, c in self.connections.items() if identity in (c.source, c.target)]:
            del self.connections[key]
            self.order.pop(key, None)
        self.ids = {k: v for k, v in self.ids.items() if v != identity}
        self.dropped += 1

    def flow(self, scope: FlowScope, parent: str | None = None, limit: int = MAX_NODES) -> None:
        """Components called in one scope and the values passed between them."""
        for site in scope.sites:
            if (
                len({c for c in self.components.values() if c.parent == parent}) >= limit
                and f"{parent}|{site.target}" not in self.ids
            ):
                self.dropped += 1
                continue
            before = self.snapshot()
            head = lead(site.callee)
            target = self.add(site.target, scope, site.line, parent, head.split(".")[0])
            if target is None:
                continue
            for producer, where in site.uses:
                step = self.snapshot()
                source = self.add(producer.component, scope, where, parent, producer.name)
                if source is None:
                    continue
                wires = producer.instance
                self.link(
                    source,
                    target,
                    "wires" if wires else "data",
                    "object passed" if wires else "value passed",
                    "static_data_flow",
                    "VERIFIED" if producer.direct else "INFERRED",
                    [(scope.path, site.line), (scope.path, where)],
                    (head, producer.name),
                )
                self.fits(parent, step)
            self.fits(parent, before)
        for producer, where in scope.returns:
            source = self.ids.get(f"{parent}|{producer.component}")
            if source is None or producer.component.startswith("input::"):
                continue
            before = self.snapshot()
            target = self.add("output::", scope, where, parent)
            keyword = "return" if "return" in self.quote(scope.path, where) else "=>"
            if target:
                self.link(
                    source,
                    target,
                    "data",
                    "returned",
                    "static_data_flow",
                    "VERIFIED" if producer.direct else "INFERRED",
                    [(scope.path, where)],
                    (keyword, producer.name),
                )
                self.fits(parent, before)

    def uses(self, key: str, identity: str, parent: str | None = None) -> None:
        """External resources reached from inside a function or any method of a class."""
        scopes = [s for k, s in self.repo.scopes.items() if k == key or k.startswith(key + ".")]
        for scope in scopes:
            for site in scope.sites:
                if site.target.startswith("resource::") and len(self.components) < MAX_NODES + 3:
                    before = self.snapshot()
                    token = lead(site.callee).split(".")[0]
                    target = self.add(site.target, scope, site.line, parent, token)
                    if target:
                        self.link(
                            identity,
                            target,
                            "uses",
                            "calls client",
                            "static_structure",
                            "VERIFIED",
                            [(scope.path, site.line)],
                            (token,),
                        )
                        self.fits(parent, before)

    def zoom(self, key: str, identity: str, wanted: set[str]) -> View | None:
        """A detail view: what one function, or one method of a class, wires together inside."""
        definition = self.repo.defs.get(key)
        if definition is None:
            return None
        candidates = [
            s
            for k, s in self.repo.scopes.items()
            if k == key
            or (k.startswith(key + ".") and not k.endswith(("__init__", ".constructor")))
        ]
        candidates.sort(
            key=lambda s: (
                s.name.split(".")[-1] not in wanted,
                -len({x.target for x in s.sites}),
                s.line,
            )
        )
        for scope in candidates:
            if len({s.target for s in scope.sites}) < 2 or not any(s.uses for s in scope.sites):
                continue
            before, links = set(self.components), set(self.connections)
            self.flow(scope, identity, 8)
            added = [c for c in self.components if c not in before]
            new = [c for c in self.connections if c not in links]
            if len(added) >= 2 and new:
                return View(
                    id=f"inside-{identity}",
                    title=f"Inside {scope.name}"[:50],
                    parent=identity,
                    component_ids=tuple(added),
                    connection_ids=tuple(new),
                )
            for item in added:
                del self.components[item]
                self.ids = {k: v for k, v in self.ids.items() if v != item}
            for item in new:
                del self.connections[item]
        return None

    def architecture(
        self,
        identity: str,
        kind: str,
        title: str,
        views: list[View],
        unresolved: list[Unresolved],
        inputs: tuple[str, ...] = (),
        outputs: tuple[str, ...] = (),
    ) -> Architecture | None:
        top = [c for c in self.components.values() if c.parent is None]
        links = [
            c
            for c in self.connections.values()
            if self.components[c.source].parent is None and self.components[c.target].parent is None
        ]
        if len(top) < 3 or len(links) < 2:
            return None
        ordered = sorted(self.connections.values(), key=self.position)
        steps = tuple(
            Step(
                order=i + 1,
                text=sentence(c, self.components),
                component_ids=(c.source, c.target),
                connection_ids=(c.id,),
                status=c.status,
                citations=c.citations[:1],
            )
            for i, c in enumerate(c for c in ordered if self.components[c.source].parent is None)
        )
        if any(c.status == "INFERRED" and c.kind != "endpoint" for c in self.components.values()):
            unresolved.append(
                Unresolved(
                    topic="binding strength",
                    reason=(
                        "Some names are bound only by a unique top-level definition; the "
                        "analyzer's stricter binding check did not confirm them. Components "
                        "and connections that depend on them are marked inferred."
                    ),
                )
            )
        if self.dropped:
            unresolved.append(
                Unresolved(
                    topic="not drawn",
                    reason=(
                        f"{self.dropped} further component or connection was left out: "
                        f"no verified citation, or beyond the diagram limit."
                    ),
                )
            )
        unresolved.append(
            Unresolved(
                topic="runtime behavior",
                reason=(
                    "Every connection is a static source relationship. Which paths execute, "
                    "in what order and with what data is not established."
                ),
            )
        )
        overview = View(
            id="overview",
            title=title[:50],
            component_ids=tuple(c.id for c in top),
            connection_ids=tuple(c.id for c in links),
        )
        return Architecture(
            id=identity,
            type=kind,
            level="system",
            title=title[:60],
            scope=tuple(sorted({c.citations[0].path for c in self.components.values()})),
            status="VERIFIED" if all(c.status == "VERIFIED" for c in links) else "INFERRED",
            components=tuple(self.components.values()),
            connections=tuple(ordered),
            flows=(Flow(name="source order", steps=steps),),
            inputs=tuple(i for i in inputs if i in self.components),
            outputs=tuple(o for o in outputs if o in self.components),
            unresolved=tuple(unresolved),
            views=(overview, *views),
        )


def sentence(connection: Connection, components: dict[str, Component]) -> str:
    """Wording is about the source text, never about what happens when it runs."""
    source, target = components[connection.source], components[connection.target]
    token = connection.anchors[-1]
    how = "" if connection.status == "VERIFIED" else " through an intermediate expression"
    if connection.kind == "data" and source.kind == "input":
        return f"The parameter {source.label} is passed to {target.label}{how}."
    if connection.kind == "data" and target.kind == "output":
        return f"The value from {source.label} is what the function returns{how}."
    if connection.kind == "data":
        return f"The value from {source.label}, held in {token}, is passed to {target.label}{how}."
    if connection.kind == "wires":
        return f"The {source.label} object is handed to {target.label}{how}."
    if connection.kind == "uses":
        what = (
            f"the {target.label} client library"
            if "client library" in target.lines
            else f"the built-in {target.label} function"
        )
        return (
            f"{source.label} calls {what}, a {target.kind.replace('_', ' ')} interaction. "
            f"Whether it succeeds at runtime is not established."
        )
    if connection.kind == "calls":
        return f"The source of {source.label} contains a call to {target.label}."
    if connection.kind == "routes":
        return (
            f"The route {route_words(source)} is declared on {target.label}. Which handler "
            f"serves a request at runtime is not verified."
        )
    if connection.kind == "imports":
        return f"{source.label} imports {target.label}."
    if connection.kind == "http_request":
        return (
            f"{source.label} contains a request path that matches a route declared in "
            f"{target.label}. Whether a request reaches it at runtime is not established."
        )
    return f"{source.label} is connected to {target.label} ({connection.kind})."


def unknown_callees(scope: FlowScope) -> list[Unresolved]:
    names = list(dict.fromkeys(scope.unresolved))
    if not names:
        return []
    return [
        Unresolved(
            topic="unbound calls",
            reason=(
                f"{len(names)} called names in {scope.name} are not defined in this snapshot "
                f"and are not drawn: {', '.join(names[:4])}."
            ),
        )
    ]


def orchestrations(
    repo: Repo, claimed: set[tuple[str, str]], classes: set[str], start: int
) -> list[Architecture]:
    """Scopes that wire several components together, largest first, without overlap.

    Scopes in test files are not the repository's architecture: they neither become one nor,
    by calling production code, turn it into an inner scope.
    """
    production = [
        scope
        for scope in repo.scopes.values()
        if repo.ctx.manifest.get(scope.path, {}).get("classification") != "test"
    ]
    called = {site.target for scope in production for site in scope.sites}
    called |= {bound for parts in repo.parts.values() for bound, _, _ in parts.values() if bound}
    ranked = []
    for scope in production:
        nodes = {s.target for s in scope.sites}
        edges = sum(len(s.uses) for s in scope.sites)
        definition = repo.defs.get(scope.key)
        owner = definition.owner if definition else None
        root = scope.key not in called and owner not in called
        owned = scope.name.split(".")[0] in classes and "." in scope.name
        if len(nodes) >= 3 and edges >= 2 and (scope.path, scope.name) not in claimed and not owned:
            ranked.append((not root, -len(nodes), -edges, scope.key, scope, nodes))
    found: list[Architecture] = []
    covered: set[str] = set()
    if any(not r[0] for r in ranked):
        ranked = [r for r in ranked if not r[0]]  # Inner scopes become zoom views.
    for _, _, _, _, scope, nodes in sorted(ranked, key=lambda r: r[:4]):
        if nodes <= covered or len(found) >= 2:
            continue
        graph = Graph(repo)
        graph.flow(scope)
        top = dict(graph.ids)
        for lookup, identity in top.items():
            key = lookup.split("|", 1)[1]
            if key in repo.defs:
                graph.uses(key, identity)
        wanted = {s.callee.split(".")[-1] for s in scope.sites}
        views: list[View] = []
        zoomed: set[str] = set()
        for lookup, identity in top.items():
            key = lookup.split("|", 1)[1]
            names = wanted
            if "#" in key:  # A constructed part: zoom into the class it is built from.
                owner, attribute = key.split("#")
                key, names = repo.parts[owner][attribute][0], {"forward", "__call__"}
            if not key or key in zoomed or len(views) >= 2:
                continue
            view = graph.zoom(key, identity, names)
            if view:
                views.append(view)
                zoomed.add(key)
        name = "module level" if scope.name == "<module>" else f"{scope.name}()"
        built = graph.architecture(
            f"graph-{start + len(found)}",
            "component_graph",
            titled(f"{name} in "[:40], scope.path),
            views,
            unknown_callees(scope),
            tuple(i for k, i in top.items() if k.split("|", 1)[1].startswith("input::")),
            tuple(i for k, i in graph.ids.items() if k == "None|output::"),
        )
        if built is not None:
            found.append(built)
            covered |= nodes
    return found


def handler_of(repo: Repo, path: str, node: Node) -> str | None:
    """The function definition a route declaration names as its handler, if the source binds it."""
    body = repo.ctx.files[path].body
    found: str | None = None
    if (node.start_byte, node.end_byte) in repo.inline:
        found = repo.inline[(node.start_byte, node.end_byte)]
    elif node.type == "identifier":
        found = repo.bindings.get(path, {}).get(text(node, body))
    elif node.type == "member_expression":
        owner = node.child_by_field_name("object")
        alias = text(owner, body) if owner is not None and owner.type == "identifier" else ""
        module = repo.aliases.get(path, {}).get(alias)
        name = text(node.child_by_field_name("property"), body)
        found = repo.member(path, alias, module, name) if module else None
    if found is None or repo.defs[found].kind != "function" or found not in repo.scopes:
        return None
    return found


def py_string(node: Node | None, body: bytes) -> str | None:
    """A plain Python string literal's value: never an f-string, bytes or a concatenation."""
    if node is None or node.type != "string":
        return None
    if any(c.type == "interpolation" for c in node.named_children):
        return None
    raw = text(node, body)
    found = re.fullmatch(r"""[rRuU]?("|')([^"'\\\n]*)\1""", raw)
    return found.group(2) if found else None


@dataclass(frozen=True)
class PyRouter:
    """A module-level name bound once to `APIRouter(...)` or `Blueprint(...)`."""

    line: int
    prefix: str  # The literal prefix, without a trailing slash; "" when none is given.
    prefix_line: int  # 0 when no prefix keyword is written.
    known: bool  # False when a prefix keyword is written but is not a plain literal.


def python_routers(repo: Repo, path: str, file: SourceFile) -> dict[str, PyRouter]:
    """Router objects one Python file constructs from the constructor `fastapi` or `flask`
    exports, as the analyzer recorded that import. A name assigned more than once at module
    level is not a router: which object it holds is not settled by its syntax."""
    factories: dict[str, str] = {}
    for item in repo.by_path.get(path, []):
        if item["kind"] != "import" or item["name"] not in PY_ROUTERS:
            continue
        syntax = item.get("syntax", {})
        member = syntax.get("imported_member")
        offered = PY_ROUTERS[item["name"]]
        if member in offered:
            factories[syntax.get("local_binding") or member] = member
        elif not member:
            alias = syntax.get("local_binding") or item["name"]
            factories.update({f"{alias}.{name}": name for name in offered})
    if not factories:
        return {}
    found: dict[str, PyRouter] = {}
    counts: dict[str, int] = {}
    body = file.body
    for statement in file.root.named_children:
        node = statement.named_children[0] if statement.named_child_count else None
        if statement.type != "expression_statement" or node is None or node.type != "assignment":
            continue
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or left.type != "identifier":
            continue
        name = text(left, body)
        counts[name] = counts.get(name, 0) + 1
        function = right.child_by_field_name("function") if right is not None else None
        made = factories.get(re.sub(r"\s+", "", text(function, body)))
        if right is None or right.type != "call" or made is None:
            continue
        keyword = next(v for k, v in PY_ROUTERS.items() if made in v)[made]
        value = arguments(right)[1].get(keyword)
        prefix = py_string(value, body)
        found[name] = PyRouter(
            line(node),
            (prefix or "").rstrip("/"),
            line(value) if value is not None and prefix else 0,
            value is None or prefix is not None,
        )
    return {name: item for name, item in found.items() if counts.get(name) == 1}


def python_router_routes(
    repo: Repo, path: str, file: SourceFile, routers: dict[str, PyRouter]
) -> list[Route]:
    """`@router.get("/x")` (FastAPI) and `@bp.route("/x", methods=[...])` (Flask) on top-level
    functions, on a router this file constructs. Each route is cited on its decorator, on the
    line its path is written on, and on the prefix its router declares."""
    body = file.body
    found: list[Route] = []
    for child in file.root.named_children:
        node = (
            child.child_by_field_name("definition")
            if child.type == "decorated_definition"
            else None
        )
        if node is None or node.type != "function_definition":
            continue
        handler = f"{path}::{text(node.child_by_field_name('name'), body)}"
        if handler not in repo.defs:
            continue
        for decorator in (c for c in child.named_children if c.type == "decorator"):
            call = decorator.named_children[0] if decorator.named_child_count else None
            function = call.child_by_field_name("function") if call is not None else None
            if call is None or call.type != "call" or function is None:
                continue
            if function.type != "attribute":
                continue
            owner = text(function.child_by_field_name("object"), body)
            method = text(function.child_by_field_name("attribute"), body)
            router = routers.get(owner)
            positional, keywords = arguments(call)
            if router is None:
                continue
            if method in ROUTE_METHODS:
                verb = method.upper()
            elif method == "route":
                listed = keywords.get("methods")
                named = [py_string(c, body) for c in (listed.named_children if listed else []) if c]
                verb = next((m.upper() for m in named if m and m.upper() in FLASK_METHODS), "GET")
            else:
                continue
            written = positional[0] if positional else keywords.get("path")
            own = py_string(written, body)
            if own is None or (own and not own.startswith("/")) or (not own and not router.prefix):
                continue
            full = (router.prefix + own) if own != "/" or not router.prefix else router.prefix
            cited = [(path, line(decorator))]
            if written is not None and line(written) != line(decorator):
                cited.append((path, line(written)))
            if router.prefix_line:
                cited.append((path, router.prefix_line))
            found.append(
                Route(
                    verb,
                    full,
                    tuple(cited),
                    tuple(a for a in (own, router.prefix) if a),
                    "declared router route",
                    matchable=router.known,
                    handler=handler,
                    def_line=line(node),
                    label=f"{verb} {own or '/'}",
                )
            )
            break  # One route per handler, as for application decorators.
    return found


def routes(repo: Repo) -> dict[str, list[Route]]:
    """Declared routes per file, each with its handler's definition id and line.

    Python routes are decorators: on the application object the analyzer recorded, or on an
    `APIRouter` or `Blueprint` the file constructs from the package the analyzer recorded it
    being imported from, with the router's literal prefix. JavaScript and TypeScript routes are
    calls such as `app.get("/items", handler)` on the application object the analyzer bound,
    routes on an Express router with the prefixes its mounts add, and Next.js route handlers.
    Routes in test files are not the repository's service.
    """
    allowed = {
        c["path"]
        for c in repo.ctx.payload["knowledge"]["entrypoints"]["candidates"]
        if c["rule"] == "framework-route-v1"
    }
    found: dict[str, list[Route]] = {}
    for path, file in repo.ctx.files.items():
        if not file.valid or repo.ctx.manifest.get(path, {}).get("classification") == "test":
            continue
        if not file.python:
            # Each kind of route was gated where it was read: analyzer-recorded application
            # routes, routers constructed from `express`, and Next.js route files.
            for declared, written in repo.script_routes.get(path, []):
                handler = declared.handler or (
                    handler_of(repo, path, written) if written is not None else None
                )
                if handler is not None and handler in repo.scopes:
                    found.setdefault(path, []).append(
                        replace(declared, handler=handler, def_line=repo.defs[handler].line)
                    )
            continue
        if path not in allowed:
            routers = python_routers(repo, path, file)
            if routers:
                found.setdefault(path, []).extend(python_router_routes(repo, path, file, routers))
                if not found[path]:
                    del found[path]
            continue
        for child in file.root.named_children:
            node = (
                child.child_by_field_name("definition")
                if child.type == "decorated_definition"
                else None
            )
            if node is None or node.type != "function_definition":
                continue
            match = ROUTE.search(text(child, file.body).split("def ", 1)[0])
            handler = f"{path}::{text(node.child_by_field_name('name'), file.body)}"
            if match and handler in repo.defs:
                number = line(child) + text(child, file.body)[: match.start()].count("\n")
                found.setdefault(path, []).append(
                    Route(
                        match.group(2).upper(),
                        match.group(3),
                        ((path, number),),
                        (match.group(3),),
                        handler=handler,
                        def_line=line(node),
                    )
                )
    return found


def services(repo: Repo, declared: dict[str, list[Route]], start: int) -> list[Architecture]:
    found: list[Architecture] = []
    for path, items in sorted(declared.items()):
        graph = Graph(repo)
        unresolved: list[Unresolved] = []
        unmounted = False
        for route in items[:4]:
            handler, def_line = route.handler, route.def_line
            citations = [repo.ctx.cite(where, number) for where, number in route.cited]
            scope = repo.scopes[handler]
            before = graph.snapshot()
            target = graph.add(handler, scope, def_line)
            if target is None or not all(citations) or not shown(citations, route.anchors):
                graph.components, graph.connections, graph.ids, graph.order = before
                continue
            endpoint = slug(f"{route.method} {route.path}") or "route"
            graph.components[endpoint] = Component(
                id=endpoint,
                role="endpoint",
                kind="endpoint",
                label=(route.label or f"{route.method} {route.path}")[:28],
                lines=(route.note,),
                status="INFERRED",
                anchors=route.anchors,
                citations=tuple(c for c in citations if c is not None),
                group=path[:60],
            )
            graph.link(
                endpoint,
                target,
                "routes",
                "declared on",
                "declared_route",
                "INFERRED",
                [*route.cited, (repo.defs[handler].path, def_line)],
                (*route.anchors, repo.defs[handler].anchor),
            )
            if not graph.fits(None, before):
                continue
            unmounted |= route.note == "router route"
            for site in scope.sites:
                # Bounded before adding, as in Graph.flow: a callee past the limit is never
                # added, so no unlinked component is left behind.
                if (
                    len(graph.components) >= MAX_NODES + 2
                    and f"None|{site.target}" not in graph.ids
                ):
                    graph.dropped += 1
                    continue
                before = graph.snapshot()
                head = lead(site.callee)
                callee = graph.add(site.target, scope, site.line, None, head.split(".")[0])
                if callee is None:
                    continue
                kind = "uses" if site.target.startswith("resource::") else "calls"
                graph.link(
                    target,
                    callee,
                    kind,
                    "call site",
                    "static_structure",
                    "VERIFIED",
                    [(scope.path, site.line)],
                    (head,),
                )
                if graph.fits(None, before) and site.target in repo.defs:
                    graph.uses(site.target, callee)
                    deeper(repo, graph, scope, site, callee)
            unresolved += unknown_callees(scope)
        if unmounted:
            unresolved.append(
                Unresolved(
                    topic="router mount",
                    reason=(
                        "No mount of a router declared here was found, so its routes are shown "
                        "with their own paths. The prefix a mount would add is not known."
                    ),
                )
            )
        unresolved.append(
            Unresolved(
                topic="request handling",
                reason=(
                    "Routes are declarations found in source. Which handler serves a request, "
                    "and whether any request arrives, is not executed or verified."
                ),
            )
        )
        built = graph.architecture(
            f"service-{start + len(found)}",
            "service",
            titled("HTTP service in ", path),
            [],
            unresolved[-3:],
        )
        if built is not None:
            found.append(built)
    return found


def deeper(repo: Repo, graph: Graph, scope: FlowScope, site: Site, callee: str) -> None:
    """One more hop from a handler's callee in another module: what that function, or the
    method of that class the handler's call names, calls in a third module. At most two
    callees, each cited on its own call site, so a route's view reaches past the first
    service it calls without growing past the diagram limit."""
    definition = repo.defs[site.target]
    if definition.path == scope.path:
        return
    keys = [site.target]
    if definition.kind == "class":
        # The methods the handler calls on what it constructs: `.name(` in its own source.
        handler = repo.defs.get(scope.key)
        body = repo.ctx.files[scope.path].body
        written = text(handler.node, body) if handler is not None else ""
        called = dict.fromkeys(re.findall(r"\.\s*([A-Za-z_]\w*)\s*\(", written))
        keys = [f"{site.target}.{name}" for name in called if f"{site.target}.{name}" in repo.defs]
    added = 0
    for key in keys:
        inner = repo.scopes.get(key)
        if inner is None:
            continue
        for found in inner.sites:
            target = repo.defs.get(found.target)
            if (
                added >= 2
                or target is None
                or target.path in {scope.path, definition.path}
                or len(graph.components) >= MAX_NODES + 2
            ):
                continue
            before = graph.snapshot()
            head = lead(found.callee)
            reached = graph.add(found.target, inner, found.line, None, head.split(".")[0])
            if reached is None or reached == callee:
                continue
            graph.link(
                callee,
                reached,
                "calls",
                "call site",
                "static_structure",
                "VERIFIED",
                [(inner.path, found.line)],
                (head,),
            )
            if graph.fits(None, before):
                added += 1


def overview(repo: Repo, declared: dict[str, list[Route]], subsystems: int) -> Architecture | None:
    """File-level system view: resolved imports, client-to-route path matches and resources.

    Test files are not the repository's system: as in `orchestrations()` and `routes()`, they
    contribute no file, import, request or resource to the view.
    """
    ctx = repo.ctx
    graph = Graph(repo)
    symbols = ctx.all_symbols
    tests = {path for path, entry in ctx.manifest.items() if entry.get("classification") == "test"}
    edges: list[tuple[str, str, str, list[tuple[str, int]], tuple[str, ...], Any, Status]] = []
    for edge in ctx.payload["knowledge"]["edges"]:
        if edge["relationship"] == "imports" and edge["classification"] == "resolved_static":
            support = symbols[edge["support_ids"][0]]
            module = support["name"]
            imported = symbols[edge["target"]]["path"]
            if support["path"] in tests or imported in tests:
                continue
            edges.append(
                (
                    support["path"],
                    imported,
                    "imports",
                    [(support["path"], support["start_line"])],
                    (module,),
                    "static_structure",
                    "VERIFIED",
                )
            )
    matched = 0
    scopes = [scope for scope in repo.scopes.values() if scope.path not in tests]
    clients: list[tuple[str, int]] = [
        (s["path"], s["start_line"])
        for s in symbols.values()
        if s["kind"] == "call"
        and s["name"].split(".")[0] in {"fetch", "axios"}
        and s["path"] not in tests
    ]
    for scope in scopes:
        clients += [
            (scope.path, site.line)
            for site in scope.sites
            if site.target.startswith("resource::")
            and KINDS[site.target.split("::")[1]] == "http_client"
        ]
    for path, number in sorted(set(clients)):
        literal = URL.search(ctx.lines.get(path, [""] * number)[number - 1])
        if not literal or literal.group(1) == "/":
            continue
        wanted = literal.group(1).rstrip("/")
        for target, items in declared.items():
            for route in items:
                if (
                    target != path
                    and route.matchable
                    and route.path != "/"
                    and wanted.endswith(route.path.rstrip("/"))
                ):
                    edges.append(
                        (
                            path,
                            target,
                            "http_request",
                            [(path, number), *route.cited],
                            (route.path.rstrip("/"),),
                            "literal_match",
                            "INFERRED",
                        )
                    )
                    matched += 1
    resources = [
        (scope.path, site)
        for scope in scopes
        for site in scope.sites
        if site.target.startswith("resource::")
    ]
    if subsystems < 2 and not matched:
        return None
    degree: dict[str, int] = {}
    for source, target, *_ in edges:
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1
    for path, _ in resources:
        degree[path] = degree.get(path, 0) + 1
    ranked = sorted(degree, key=lambda p: (-degree[p], p))[:OVERVIEW_FILES]
    keep = set(ranked)
    ids: dict[str, str] = {}
    for path in sorted(keep):
        text_lines = ctx.lines.get(path, [])
        number = next((i for i, value in enumerate(text_lines, 1) if value.strip()), 0)
        citation = ctx.cite(path, number) if number else None
        if citation is None:
            continue
        identity = slug(path)
        entry = ctx.manifest[path]
        count = sum(
            1 for d in repo.defs.values() if d.path == path and d.kind != "method" and not d.inline
        )
        graph.components[identity] = Component(
            id=identity,
            role="source_file",
            kind="source_file",
            label=path.split("/")[-1][:28],
            lines=(
                f"{entry['language']}, {count} definition{'' if count == 1 else 's'}"
                if count
                else entry["language"],
            ),
            status="VERIFIED",
            anchors=(citation.quote[:24],),
            citations=(citation,),
            group=(path.split("/")[0] if "/" in path else "(top level)")[:60],
        )
        ids[path] = identity
    for source, target, kind, cited, anchors, basis, status in edges:
        if source in ids and target in ids:
            graph.link(
                ids[source],
                ids[target],
                kind,
                kind.replace("_", " "),
                basis,
                status,
                cited,
                anchors,
            )
    external: list[str] = []
    for path, site in resources:
        if path in ids and len(graph.components) < MAX_NODES + 3:
            token = lead(site.callee).split(".")[0]
            reached = graph.add(site.target, FlowScope(path, path, path, 1), site.line, None, token)
            if reached:
                external.append(reached)
                graph.link(
                    ids[path],
                    reached,
                    "uses",
                    "calls client",
                    "static_structure",
                    "VERIFIED",
                    [(path, site.line)],
                    (token,),
                )
    # Several languages and boundaries can need more rows than the diagram has. Leave out
    # external resources first, then the least connected files, until the view lays out.
    for identity in [
        *reversed(dict.fromkeys(external)),
        *(ids[p] for p in reversed(ranked) if p in ids),
    ]:
        if graph.drawable():
            break
        graph.remove(identity)
    unresolved = [
        Unresolved(
            topic="integration",
            reason=(
                "Only resolved imports, client-library calls and matching path literals "
                "are drawn. Other integration between files is not established."
            ),
        )
    ]
    return graph.architecture(
        "system-overview", "system_overview", "System overview", [], unresolved
    )


def build(
    ctx: Context, claimed: set[tuple[str, str]], classes: set[str], existing: int
) -> list[Architecture]:
    repo = Repo(ctx)
    declared = routes(repo)
    found = services(repo, declared, 1)
    handlers = {
        (repo.defs[r.handler].path, repo.defs[r.handler].name)
        for items in declared.values()
        for r in items
    }
    found += orchestrations(repo, claimed | handlers, classes, 1)
    from repovox.media.system_view import build_system

    # The repository-wide subsystem map stands for the whole system when the repository has
    # one; otherwise the file-level overview does, as before.
    system = build_system(repo, declared)
    top = system or overview(repo, declared, existing + len(found))
    return ([top] if top else []) + ranked(found, system)


UI_PRIMITIVE = re.compile(r"^[a-z][a-z0-9]*$|^[A-Z][a-z]+$")  # `date`, `human`, `Section`


def directory_roles(system: Architecture | None) -> dict[str, str]:
    """Directory -> subsystem role (`ml`, `data`, ...) as the system map tiered it from code."""
    if system is None:
        return {}
    return {
        citation.path.rpartition("/")[0]: component.role
        for component in system.components
        if component.kind.endswith("_subsystem")
        for citation in component.citations
    }


def workflow_score(architecture: Architecture, roles: dict[str, str] | None = None) -> float:
    """How much of the system one workflow explains: tiers crossed, backend share, depth.

    A view drawn from a UI file whose callees are themselves client components (prop and
    formatting helpers such as `Facts`, `date` or `Section`) explains layout, not the system,
    and ranks below any backend workflow.
    """
    from repovox.media.diagram import classify

    overview = architecture.views[0] if architecture.views else None
    members = set(overview.component_ids) if overview else {c.id for c in architecture.components}
    top = [
        c for c in architecture.components if c.id in members and c.kind not in {"input", "output"}
    ]
    if not top:
        return 0.0
    tiers = [classify(c)[0] for c in top]
    backend = sum(t != "client" for t in tiers) / len(tiers)
    links = [c for c in architecture.connections if {c.source, c.target} <= members]
    outgoing: dict[str, list[str]] = {}
    for link in links:
        outgoing.setdefault(link.source, []).append(link.target)

    def depth(node: str, seen: frozenset[str]) -> int:
        return max(
            (1 + depth(n, seen | {n}) for n in outgoing.get(node, []) if n not in seen), default=0
        )

    longest = max((depth(c.id, frozenset({c.id})) for c in top), default=0)
    score = 3.0 * len(set(tiers)) + 4.0 * backend + 1.5 * min(longest, 5)
    score += 2.0 if architecture.type == "service" else 0.0
    score += 2.0 if "platform" in tiers else 0.0
    reached = {(roles or {}).get(c.citations[0].path.rpartition("/")[0], "") for c in top}
    score += 3.0 if "ml" in reached else 0.0  # Reaches model code the system map tiered.
    score += 1.0 if "data" in reached else 0.0
    client = [c for c, t in zip(top, tiers, strict=True) if t == "client"]
    primitives = sum(bool(UI_PRIMITIVE.match(c.label)) for c in client)
    if client and len(client) >= 0.6 * len(top) and primitives >= len(client) / 2:
        score -= 10.0  # A UI page passing props to layout and formatting helpers.
    return round(score, 6)


def ranked(found: list[Architecture], system: Architecture | None = None) -> list[Architecture]:
    """Deep workflows first, backend before UI; at most four route services are kept."""
    roles = directory_roles(system)
    scores = [workflow_score(a, roles) for a in found]
    order = sorted(range(len(found)), key=lambda i: (-scores[i], i))
    kept: list[Architecture] = []
    services_kept = 0
    for i in order:
        if found[i].type == "service":
            if services_kept >= 4:
                continue
            services_kept += 1
        kept.append(found[i])
    return kept


__all__ = ["Citation", "build", "sentence"]
