# API contracts

`openapi.json` is generated from FastAPI response/request schemas by `tools/phase1_contracts.py`. CI verifies drift without contacting a service. API version `v1`, release `0.1.0`; approved analysis artifact schema `2.1` stays under `docs/architecture`. Fixture objects are separate `trusted-fixture-v1` data, never real analysis output. Frontend types describe the public subset and contain no object keys or lease/session internals.
