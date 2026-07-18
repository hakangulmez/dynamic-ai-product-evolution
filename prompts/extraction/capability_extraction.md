# Capability Extraction

## Governing spec

`SPEC-009`

## System instruction

For each validated product, extract concrete customer-facing functions. A capability describes what the product enables, not the customer's broader objective and not the underlying technical stack.

Good capability examples:

- generate images from text;
- answer document questions with citations;
- summarize and route support incidents;
- execute an approved user-provisioning workflow.

Reject:

- “AI-powered innovation”;
- “improve productivity”;
- internal model training with no customer-facing function;
- pricing and packaging alone.

AI terms receive no special status. Translate them into the concrete action described by evidence.

## Required fields

- product ID;
- capability name and normalized description;
- input and output types;
- availability status;
- source passages and quotes;
- ambiguity and confidence.

Return JSON conforming to `capability_observation.schema.json`.
