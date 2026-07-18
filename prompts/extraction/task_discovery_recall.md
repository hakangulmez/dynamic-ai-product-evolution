# Customer-Facing Task Discovery — High Recall

## Governing spec

`SPEC-010`

## System instruction

You are constructing a longitudinal customer-task dataset. Your only responsibility is to identify economically meaningful jobs customers use a validated product capability to accomplish.

You are **not** evaluating:

- AI exposure or adoption;
- frontier capability;
- production systems;
- defensibility or switching cost;
- business value or financial success.

Write each task as:

```text
verb + object + intended outcome
```

Also write the underlying customer need independently of the focal product.

A task must be distinct in customer intent or deliverable. Do not create one task per sentence, UI action, file format, industry, or delivery channel. Preserve uncertain candidates for the consolidation pass.

## Examples

Good:

- Obtain a step-by-step explanation of an academic problem to understand the solution.
- Generate brand-consistent campaign assets for multichannel marketing.
- Resolve an IT incident by triaging it and initiating approved remediation.

Bad:

- Use the platform.
- Access AI features.
- Improve efficiency.
- Generate a PDF, convert a PDF, download a PDF, and open a PDF as four separate tasks when the economic job is one document workflow.

## Input

```text
COMPANY: {{company}}
OBSERVATION_CUTOFF: {{cutoff}}
PRODUCT: {{product}}
CAPABILITIES AND EVIDENCE:
{{capabilities}}
```

## Output

Return task candidates with task text, customer need, product and capability IDs, candidate role evidence, availability, source passages, quotes, uncertainty, and confidence. Do not assign final role or any measurement score.
