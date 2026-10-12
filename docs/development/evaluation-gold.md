# Independent gold contract and claim alignment

Correction of independent review R2-01/R2-02 at
`b35d93da16d129b079d0e1d5586135215fdbca78`.
[Preparation](evaluation-preparation.md) · [Gold JSON Schema](../ai/gold-evaluation.schema.json)
· [Corpus JSON Schema](../ai/evaluation-corpus.schema.json) · [ADR-0012](../adr/0012-independent-gold-contract.md)

## Versioned contracts

`GoldEvaluation` is canonical `gold-evaluation-1.0`. `Family` inherits that contract
and adds the existing rights, family, split, screening and review provenance fields.
Corpus schema `evaluation-corpus-2.0` explicitly requires the new fields. The empty
preparation manifest is `eval-v2-preparation`, still UNFROZEN, with no sources, rights
approvals or labels admitted. These are contract/preparation versions; approved
EVAL-ENTRY targets, future corpus selection and model strategy are unchanged.

Gold requires `gold_schema_version`, canonical repository identity, full commit SHA,
`annotation_scope` (`complete` or `partial`), `symbols`, `entrypoints`, `edges`, `claims`
and `safety_observations`. Arrays are required even when intentionally empty. Missing
symbols/entrypoints do not default to empty expectations. Unknown annotation fields,
coerced scalar types, duplicate IDs/facts and malformed ranges/hashes are rejected.
JSON Schema checks structural fields/types; Pydantic additionally checks relational
conditions such as end >= start, safe paths, uniqueness and cited fact support. Source
validation checks actual containment, file existence, SHA-256 and inclusive LF ranges.

- Symbol identity: original path/hash/inclusive lines, kind/name, language, extraction
  rule and parameters/import alias/imported name/binding/dispatch attributes. Attribute
  object is required; absent optional attributes normalize to null. Gold symbols also
  have independently chosen IDs, which do not participate in matching.
- Entrypoint: independent ID, path, candidate rule, optional declared target and required
  source citations. Comparison uses path/rule/target. A candidate is not runtime proof.
- Edge: independent ID, canonical source/target symbol identities, relationship,
  qualification classification, support identities, supported boolean and actual
  citations. Support cannot be duplicated; citations must cover its anchors.
- Claim: independent ID, display gloss, independently authored expected verdict,
  canonical atomic `fact` and required citations. Unsupported expectations also cite
  real contradictory/negative source; invented files/ranges/hashes are not permitted.
- Safety observations: explicitly authored string observations. Missing instrumentation
  or human observations are not implied passes; an empty object records no observations.

`fact` is a tagged union: `symbol_syntax` with a symbol identity, or
`static_relationship` with an edge identity. It expresses the complete assertion being
evaluated. The text is an author-facing gloss, not an additional semantic predicate.
Broader purpose/security/runtime/optimization claims need a separately reviewed contract
or human mapping workflow; they must not be relabelled as a supported syntax fact.

Old family annotations cannot silently acquire missing fields or trustworthy alignment.
Their preparer must author the required facts/structures and obtain independent review
again before a new freeze. Existing frozen versions must not be rewritten/rehashed as
if previously approved under 2.0. There is currently no official frozen corpus to migrate.

## Source-fact alignment 1.0

Gold is authored from source before predictions. No expected IDs, facts or verdicts
are produced by the analyzer. The independent scorer imports no analyzer/verifier
implementation. It validates a documented projection of the analysis 2.2 verified
bundle: repository, symbols, edges, candidates, candidate claims, evidence and ledger.
Additional analysis metadata is ignored, never treated as authority.

1. Validate gold and recheck its actual source. Resolve prediction-local IDs only within
   the submitted bundle. Reject duplicate IDs, missing references, unsupported ledger
   associations, missing evidence and mismatched verdict/claim content.
2. Recheck original prediction citation SHA/path/hash/lines and association to the cited
   symbol. A link, self-reported confidence, status or citation-validity flag is not proof.
3. Interpret only exact assertion grammar `symbol-fact-v1`/`edge-fact-v1`, documented
   below. Unknown rule/subject/text is unscored and requires human review. Extra semantic
   wording cannot retain a source-fact match merely by reusing a subject ID.
4. Compute canonical JSON identity from protocol `source-fact-1.0`, repository, pinned
   SHA and the complete typed fact. Normalize support ordering; preserve parameter
   ordering. Exclude gold/prediction IDs, verdict, confidence, prose and parser version.
   Source hash/ranges, extraction rules, attributes and edge classifications remain part
   of identity, so changed source or differently qualified facts cannot match silently.
5. Pair only one gold fact with exactly one predicted fact. Multiple predictions for the
   same atom are ambiguous/unscored. No arbitrary choice, fuzzy prose match, ID equality
   fallback or implementation-based creation of gold is allowed.
6. Compare the independently stored expected verdict with the paired prediction ledger
   verdict. The prediction never modifies a gold verdict.

Identical anonymous facts on the same line may be ambiguous in this version. Such
cases require a reviewed richer location/identity contract, not arbitrary pairing.

## Supported prediction assertion grammar

`{path}`, `{name}`, `{language}` and `{kind}` come from the cited symbol; their full
canonical identity still includes the original hash/range/rule/attributes. Exact strings:

| Symbol | Assertion |
| --- | --- |
| module | `{path} is a successfully parsed {language} source file.` |
| import | `{path} contains an import of {name}.` |
| call | `{path} contains the call expression {name}; runtime execution is unknown.` |
| main guard | `{path} contains a Python __main__ guard.` |
| documentation | `{path} mentions {name}; this is documentation-only.` |
| declared dependency | `{path} declares dependency constraint {name}; no locked version is asserted.` |
| config entry | `{path} declares entry target {name}; it has not been executed.` |
| anonymous function | `{path} contains anonymous function syntax.` |
| unnamed export | `{path} contains export syntax.` |
| other named syntax | `{path} contains {kind} syntax named {name}.` |

An edge claim must use `edge-fact-v1` and `graph-syntax-v1`:
`Static {relationship} relationship {source-local-id} -> {target-local-id} has classification {classification}; runtime execution is unknown.`
Those local IDs resolve to canonical source identities; they are never gold IDs.
Claims must cite exactly their subject/support symbols. This grammar is a versioned
assertion adapter, not semantic entailment or a second repository-understanding engine.

## Reports and denominators

Per-repository `evaluation-score-1.0` and aggregate `evaluation-aggregate-1.0` report:

- `gold_count`, `prediction_count`, `matched_count`, unmatched counts and ID lists;
- gold matching coverage = matched / all gold, prediction matching coverage = matched /
  all predictions; zero denominator is null, zero matches with nonzero counts is zero;
- verdict accuracy = correct labels / matched pairs;
- reviewed verified precision = correctly verified pairs / matched verified predictions;
- verified recall = correctly verified pairs / all independently verified gold claims;
- false verified predictions = paired verified predictions whose expected verdict differs;
  false verification rate uses matched verified predictions as denominator;
- unmatched verified predictions remain unknown, counted separately as
  `unscored_verified_predictions`, never assumed false or correct;
- unsupported rejection recall = paired correctly rejected unsupported facts / all
  independently unsupported gold facts; missing predictions receive no rejection credit;
- unscored predictions requiring human review, graph/import/symbol/entry precision/recall,
  original citation validity, observed parse coverage/errors and explicit safety observations.

Graph comparison includes qualified relationships; import graph separately selects
resolved static import relationships. Classification remains in the key. Aggregate
micro metrics derive from summed counts rather than averaging percentages. Empty or
incomplete repository reports cannot become a complete aggregate.

Completeness requires **100% pairing on both sides**, at least one pair, complete gold
scope and valid original prediction source evidence. Zero matches, missing predictions,
unannotated predictions, duplicate-fact ambiguity and partial scope mark both pairing
and acceptance INCOMPLETE. No threshold can silently reduce this policy.
Known false verification marks a fully paired report REJECTED. Otherwise acceptance
remains REVIEW_REQUIRED: complete pairing does not establish human review, EVAL-ENTRY,
semantic correctness beyond the independently labelled atom, or a benchmark PASS.

## Load and score

The scorer accepts validated `Family`/`GoldEvaluation` objects, their JSON-loaded
dictionaries, and the analysis 2.2 **payload** (not its outer owner/artifact envelope).
It revalidates annotations even when supplied as a model. The public boundary is:

```python
family = Family.model_validate_json(annotation_bytes)
validate_labels(family, original_source_directory)
report = score(family, verified_payload, original_source_directory)
```

Standalone gold uses `GoldEvaluation.model_validate_json`. Schema generation/checking
uses `uv run python tools/phase2_contracts.py [--check]`. The deterministic full-path test
is `uv run pytest tests/unit/test_evaluation_path.py -q`: manual facts precede actual
Tree-sitter analysis, corpus intake, JSON Schema/Pydantic validation, serialization,
load, pairing, scoring and aggregate serialization. No repository code executes.

These are explicitly synthetic engineering annotations. They do not appoint a human,
grant rights, create official gold, provision hidden fixtures or freeze the corpus.
The existing preparation/reviewer/rights/protected-access gates remain mandatory.
