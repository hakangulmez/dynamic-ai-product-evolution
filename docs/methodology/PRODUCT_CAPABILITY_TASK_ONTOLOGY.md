# Product–Capability–Task Ontology

## Hierarchy

```text
Company
  → Product family
    → Product
      → Capability
        → Customer-facing task
```

## Product family

A stable commercial grouping used to organize related products. It may correspond to a segment, cloud, suite, or solution family, but it is not automatically a product.

## Product

An identifiable customer offering that can be purchased, subscribed to, licensed, deployed, or used. A product must have at least one of:

- distinct name and product description;
- separate plan, deployment, or documentation;
- separately identifiable user experience;
- distinct commercial or administrative boundary.

Do not treat as products:

- generic strategy labels;
- “AI” or “platform” without an offering;
- bundles that merely repackage already represented products, unless the bundle creates a distinct cross-product workflow;
- internal technologies not exposed to customers.

## Capability

A concrete function the product provides. Examples:

- generate images from text;
- summarize a support case;
- provision a user account;
- query a document with citations;
- monitor infrastructure telemetry.

Capabilities should be implementation-neutral enough to compare over time, while specific enough to distinguish different functions.

## Customer-facing task

The economically meaningful job the customer uses the capability to accomplish.

Write as:

```text
verb + object + intended outcome
```

Good:

- Generate brand-consistent campaign assets for multichannel marketing.
- Resolve IT incidents by triaging, recommending, and initiating approved actions.
- Obtain a step-by-step explanation of an academic problem.

Bad:

- Use AI.
- Access the platform.
- Improve productivity.
- Firefly.

## Customer need

The task's underlying objective, phrased independently of the focal product. This field is essential for frontier-replicability assessment.

Example:

```text
Product task: obtain cited answers from PDFs using Acrobat AI Assistant
Customer need: understand and retrieve reliable information from documents
```

## Task granularity

A task should be:

- distinct in customer intent or deliverable;
- stable enough to match across years;
- not merely a UI click;
- not an entire product family;
- not split only by industry, file format, or delivery channel unless the economic job differs.

Do not use a fixed duration threshold. Enterprise tasks may span seconds or weeks. Economic separability and distinct deliverables are the governing criteria.

## Role classification

- `core`: central reason customers buy or use the product.
- `major_supporting`: materially supports the core workflow or differentiates the product.
- `peripheral`: convenience, administration, or optional enhancement.

Role classification is a separate pass, not embedded in discovery.

## Availability status

- announced
- private_beta
- public_beta
- general_availability
- broadly_deployed_or_default
- deprecated
- discontinued
- unknown

## Evidence rule

Each entity must include direct passages. Product existence cannot be inferred solely from a competitor list or risk factor.
