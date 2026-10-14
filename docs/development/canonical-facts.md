# Canonical source-fact 2.0 specification

This proposed contract is implemented in `repovox.analysis.facts`. It is separate
from the accepted v1 evaluator. Its [schema](../architecture/source-fact-2.0.schema.json)
is published alongside [analysis 2.3](../architecture/analysis-2.3.schema.json).
The [historical 2.2 schema](../architecture/analysis.schema.json) is unchanged.

## Identity and provenance

`identity(CanonicalFact)` returns compact, key-sorted, ASCII-escaped JSON.
The contract version is part of identity. Fields with omitted optional values
receive the schema's explicit defaults. `parser_rules` is retained as provenance
but excluded from equality. `support` is a set of unique original citations,
sorted deterministically during identity serialization; all other lists retain
order. No other canonical field is dropped, inferred, case-folded or synonym-mapped.
Extractor-local symbol IDs, scope lookup offsets and cached binding IDs live in
`Syntax` metadata; the projection replaces those references with complete semantic
endpoints and original source anchors. They are not portable fact identities.

| Field | Meaning and identity rule |
| --- | --- |
| `repository`, `commit_sha` | Canonical owner/name and immutable full 40-character SHA; both exact |
| `category` | `syntax`, `relationship`, or `entrypoint`; never interchanged |
| `subject`, `target` | Fully qualified original source symbols; target required only for relationships |
| `path`, `file_sha256` | Relative POSIX path and SHA-256 of complete original file bytes |
| `start_line`, `end_line` | One-based inclusive original lines; no excerpt-relative numbering |
| `start_byte`, `end_byte` | Zero-based UTF-8 byte offsets, end-exclusive; distinguish same-line constructs |
| symbol `category`, `language` | Syntax kind and parser language, including explicit module/member import distinction |
| `source_name`, `qualified_name` | Declared spelling and enclosing declaration names; repeated scopes remain distinguished by source offsets |
| `import_module`, `imported_member` | Separate module spelling and selected member; relative dots retained |
| `alias`, `local_binding` | Effective local import binding; explicit redundant alias and implicit identical binding are equivalent only within the same original anchor |
| `parameters`, `binding`, `dispatch` | Ordered declared parameters, assignment target and named/dynamic call syntax |
| `type_only`, `constructor`, `exported`, `default_export` | Distinct syntax attributes; never collapsed |
| `relationship` | `contains`, `imports`, `call_expression`, `imports_symbol`, `inherits`, `calls_lexically`, or `instantiates` |
| `classification` | `declared`, `resolved_static`, `unresolved`, or `inferred`; no runtime-success classification |
| `support` | Exact original file/hash/inclusive-line anchors, including both relationship endpoints |
| `entrypoint_category`, `entrypoint_target` | Candidate category and literal declared target; absence of execution proof is preserved |
| `parser_rules` | Extractor implementation provenance; required, but not semantic identity |

Symbol categories currently emitted are module, class, function, method, import
module/member, call, base reference, export, decorator, main guard, documentation
mention, declared dependency, configuration entry and plugin registration.
Unrecognized syntax is not silently assigned a known semantic category.

`semantic_symbol` derives import identity from explicit parsed module/member and
binding fields. It never guesses qualified members by splitting prose or old
reference labels. For instance, a parser's legacy `name` may contain the module
while another extractor's display name contains the full member; when both
explicitly supply the same module, member, effective binding and original anchor,
their canonical semantic fields can agree. Parser-rule names may differ.

Changing a member, alias, snapshot, range, dispatch, relation or resolution status
changes identity. Two identical calls on the same line have different byte ranges.
Moving source changes the file checksum and location. Neither is normalized away.
The implementation does not translate historical gold into this contract.

## Synthetic examples

Python `from .engine import Vessel as Boat` records module `.engine`, member
`Vessel`, binding/alias `Boat`, source name `Vessel`, qualified import name
`.engine.Vessel`. `import engine as Boat` is a different `import_module` fact.
Both declarations retain their complete multiline import statement range when
the syntax spans several lines. Class bases have separate exact base-expression
anchors supporting `inherits` edges.

JavaScript `export function dock() { const launch = () => polish(); launch(); }`
records enclosing names `dock.launch` and local lexical call sites. Only a unique
visible, unmodified function binding can establish `calls_lexically`. A parameter
named `polish`, writes to the identifier, conditional declarations, `eval`,
external imports or `object.polish()` prevent that conclusion.

TypeScript `import {Motor as Drive} from './engine';` followed inside a function
by `new Drive(options)` can establish `instantiates` if a unique analyzed local
module exports class `Motor`. `import type` and per-member `type` declarations
never establish runtime constructor relationships. No external class body,
dependency installation, constructor success or activation is inferred.

## Graph rules and conservative limits

Legacy module `imports` edges establish literal module-path availability only.
Qualified `imports_symbol` edges additionally require an unambiguous top-level
local definition, eligible source, stable binding and (for JS/TS) direct export.
Import cycles, ambiguous extension/index paths and external implementations do
not produce qualified member edges. Namespace/property resolution, package
search paths, transitive re-exports and runtime monkey-patching are unsupported.

Lexical scopes distinguish nested functions and JS blocks. Parameters shadow
outer names. Writes conservatively disqualify same-named declaration bindings
throughout the file, even where control flow might prove a safe binding. Complex
parameter patterns and dynamic namespace operations suppress lexical resolution.
This sacrifices coverage rather than inventing a resolved target. Python class
namespaces are not function closures. Decorated definitions may be replaced and
are not used as definite callable/class targets. Conditional calls are retained
as syntax even when qualified relationships are suppressed.

The graph records observations of syntax. `resolved_static` is not a successful
call, initialized module, valid subclass at runtime or a behavioral guarantee.
Unresolved call-expression edges remain present alongside qualified relationships.

## Entrypoint categories

| Category | Evidence | Boundary |
| --- | --- | --- |
| `executable_application` | Python main guard | Guard syntax, not an executed program |
| `candidate_command` | Imported Click command/group decorator, project scripts, package bin, existing framework candidates | Wiring and launch remain unproven |
| `library_export` | Package main/module/exports, default JS/TS export | Declared target may be missing or generated |
| `type_declaration` | Package types/typings or export-map types condition | Not executable application source |
| `build_system` | pyproject build-system.build-backend | Backend declaration, not a build invocation |
| `packaging_hook` | Jupyter discovery-hook names, imported setuptools setup call | Convention or call syntax, not discovered/installed extensions |
| `plugin` | Object registration with id and activate, including default export of a unique const object | Structural candidate, not successful activation |

Named library functions are not all promoted to executable entrypoints. New
library, packaging and plugin candidates are below the selection threshold.
Configuration target existence is reported independently from declared target
syntax. An existing file does not prove successful execution.

## Evidence and compatibility

JSON properties are token-localized, including nested export maps and arrays.
Duplicate keys reject the configuration rather than choosing one silently.
TOML uses the standard declarative parser, then original assignment spans;
multiline arrays and inline tables use their enclosing assignment range where
individual-value precision is not supported. Comments and UTF-8 bytes are
retained. No byte offsets are reconstructed from reserialized configuration.

`validate_source` verifies snapshot binding, source containment, complete original
hashes, inclusive line bounds and byte/line consistency. It does not certify
semantic entailment or reviewer identity. Stage 9 separately re-extracts symbols,
graph and canonical projection from source and rejects candidate tampering.
Documentation claims remain documentation-only; arbitrary unsupported semantic
assertions cannot acquire verified status from a hash-valid range.

The historical scorer remains `source-fact-1.0`, with complete-scope and complete-
pairing requirements unchanged. A future evaluator for independent v2 references
needs separately reviewed versioned integration. Synthetic conformance does not
establish pilot accuracy, official corpus admission or production certification.
