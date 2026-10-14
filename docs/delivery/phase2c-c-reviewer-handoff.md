# Phase 2C-C independent engineering review handoff

Review the draft PR from `phase2/canonical-fact-remediation` to
`phase2/ai-audited-pilot`, based on `8b1674de8459725bba25646e3fdd223a57316150`.
Use the PR's exact head and checks, not a later moving branch or old CI result.

Start with [ADR-0015](../adr/0015-canonical-source-fact-semantics.md),
[canonical specification](../development/canonical-facts.md) and
[verification report](phase2c-c-verification.md). The public diff contains all
engineering source, schemas, synthetic fixtures and migration tests required for
this review. Private source packets and reference answers are unnecessary.

Please independently assess:

1. Whether v2 identity preserves snapshots, members, aliases, dispatch, resolution
   and original anchors while excluding only justified extractor provenance.
2. Whether lexical resolution remains conservative under parameters, writes,
   nested scopes, conditional definitions, imported bindings, cycles and type-only
   declarations. Check that no static edge claims successful execution.
3. Candidate categories/ranks, including library/type/build/plugin/packaging
   declarations; assess false positives from convention and object-shape detection.
4. JSON/TOML original-byte localization and rejection of duplicate keys, wrong
   source hashes, forged ranges and canonical metadata.
5. The exact legacy reader/schema and untouched v1 evaluator; no historical
   reference translation or silent change to partial-scope acceptance.
6. Migration 0003, authorized separately by the owner: unchanged legacy procedure,
   correct new metadata, no row rewrites, role grants, immutable rows, mixed-version
   rejection, startup compatibility and safe operational limitations.
7. The 42-case synthetic matrix and existing tests, including negative controls;
   final-head Linux integration, browser and security checks in GitHub CI.

The implementation assistant's tests are not independent acceptance. Do not
recompute or revise the original 84 facts, 34 semantic observations, prediction
packets or historical comparison. The 0/84 historical exact match result remains
an interoperability observation, not zero semantic accuracy. All three references
remain partial. No pilot rescore or new blind evaluation was performed.

Record defects against the public engineering commit, with a minimal independent
synthetic reproduction and expected source semantics. Any future reference
correction or versioned evaluator integration needs its own reviewed process.
Do not infer official corpus approval, production certification or Phase 3 authority.
