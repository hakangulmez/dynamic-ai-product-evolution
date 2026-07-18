# Model Routing

## Principles

Route by task difficulty and evaluation risk, not convenience.

## Suggested routes

- Source-type classification: inexpensive structured model or deterministic rules.
- Product and task high-recall discovery: capable structured-output model.
- Precision consolidation: stronger model with full evidence packet.
- Longitudinal matching: strongest available reasoning model for ambiguous cases.
- Measurement: strong model with dated frontier registry and rigid rubric.
- Adjudication: independent model or human review, blinded to first-pass reasoning.

## Run controls

Each run records:

- exact prompt file and hash;
- schema and spec version;
- model label/version;
- temperature and seed when available;
- tool permissions;
- context truncation;
- retries and fallback model;
- cost and latency.

## UI versus API

Chat UI research is permitted for prompt development and difficult adjudication only when the source packet and output are archived. Production extraction should use reproducible API runs with schema enforcement when available.
