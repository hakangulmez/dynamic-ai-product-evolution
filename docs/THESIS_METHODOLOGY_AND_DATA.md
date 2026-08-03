# Thesis Methodology and Data Blueprint

## Dynamic AI Product Evolution: A Longitudinal Product–Capability–Task Study of Software Firms

**Document status:** Comprehensive design blueprint; methodology is not yet frozen.  
**Repository:** `dynamic-ai-product-evolution`  
**Primary period:** approximately 2022–2026  
**Primary empirical domain:** publicly listed software and software-enabled technology firms  
**Primary unit of analysis:** `firm × observation date × product × capability × customer-facing task`

---

## 1. Purpose of this document

This document provides a single, detailed account of the proposed thesis methodology, data architecture, extraction design, longitudinal matching system, measurement framework, validation strategy, and empirical analysis plan.

It is intended to answer five questions in one place:

1. **What is the thesis trying to explain?**
2. **What data will be collected, from which sources, and at what level of granularity?**
3. **How will products, capabilities, and customer-facing tasks be extracted without allowing the eventual scores to bias the extraction process?**
4. **How will task-level frontier replicability, AI transformation depth, deployment scale, and defensibility be measured over time?**
5. **How will the resulting task-level panel be validated, aggregated, and linked to operational or financial outcomes?**

The document should be treated as the thesis-level methodological map. Detailed implementation contracts remain in the corresponding files under `specs/`, `schemas/`, `prompts/`, `skills/`, and `evals/`.

---

## 2. Research motivation

### 2.1 Why static AI-exposure measures are insufficient

Many studies of generative AI begin with a static exposure question:

> Could a language model perform a task that was previously supplied by a worker, a product, or a firm?

That question is useful, but incomplete for firm-level research. A firm is not a fixed bundle of tasks. It can redesign products, integrate frontier models, create new workflows, change pricing, acquire new capabilities, discontinue exposed offerings, or reposition itself toward new customer segments.

A pre-shock measure therefore captures only one part of the economic process. It may identify initial vulnerability, but it does not observe the endogenous response.

The frontier-LLM transition creates several distinct firm paths:

- a general-purpose model directly substitutes for the customer value supplied by the firm;
- the firm adds AI wording or a superficial assistant without materially changing the task;
- the firm integrates AI natively into a product workflow;
- the firm gives AI access to tools, records, permissions, and transactions;
- the firm develops agentic or orchestration capabilities;
- the firm creates new AI-native products or customer jobs;
- the firm pivots away from an exposed product category;
- the firm becomes a distribution, governance, workflow, or execution layer around frontier models.

The thesis is designed to observe these paths rather than infer them from a single pre-period score.

### 2.2 The central distinction: adoption is not advantage

The project rejects the assumption that deeper AI adoption is automatically beneficial.

A firm can integrate AI deeply while remaining highly substitutable. Consider a stylized academic-support task:

```text
Student question
  → general-purpose frontier model
  → explanation or answer
```

If the frontier model can provide the core deliverable at similar or better practical quality, and the customer can switch with little friction, a sophisticated AI assistant inside the incumbent product may still be economically commoditized.

Now consider a stylized enterprise workflow task:

```text
Customer goal
  → interpret enterprise context
  → retrieve records and policies
  → obtain permissions
  → call tools and APIs
  → update systems of record
  → execute approved actions
  → monitor outcomes and exceptions
```

Here, the language model may provide reasoning, classification, or generation, but the focal product can retain value through persistent workflow state, integrations, permissions, governance, transaction execution, and organizational embedding.

The thesis therefore separates four constructs:

1. **Frontier Task Replicability:** Can the dated frontier system satisfy the underlying customer need without the focal product?
2. **AI Transformation Depth:** How deeply has AI changed the way the product performs the task?
3. **Deployment Scale:** How broadly and commercially has that transformation been deployed?
4. **Task-Specific Defensibility:** Which economically necessary advantages remain after accounting for the frontier alternative?

These constructs are related, but they are not interchangeable.

---

## 3. Main research question and subquestions

### Main research question

> How did software firms redesign customer-facing products and tasks during the frontier-LLM transition, and which combinations of frontier replicability, AI transformation depth, deployment scale, and task-specific defensibility were associated with different strategic and economic trajectories?

### RQ1 — Product and task evolution

How did firms' product families, named products, concrete capabilities, and customer-facing tasks change between approximately 2022 and 2026?

Key observable transitions include:

- product entry and exit;
- capability additions and removals;
- task expansion or contraction;
- renaming and repackaging;
- movement from human-mediated delivery to AI assistance;
- generative transformation;
- native workflow integration;
- action execution and agentification;
- portfolio pivots, acquisitions, and divestitures.

### RQ2 — Dated frontier replicability

At each observation date, to what extent could the frontier general-purpose AI system then available satisfy the underlying customer need without the focal firm's product?

This is a dated counterfactual. A 2023 task must be assessed against the frontier system and access regime available by the 2023 observation cutoff, not against a model released in 2025 or 2026.

### RQ3 — AI transformation depth

How deeply was AI integrated into each customer-facing task?

The study distinguishes marketing claims from concrete functionality and separates:

- peripheral assistance;
- direct generation, classification, or recommendation;
- native use of product context or workflow state;
- multi-step execution through tools or APIs;
- goal-directed orchestration, monitoring, and exception handling.

### RQ4 — Deployment scale

Was the transformation only announced, available in beta, generally available, included in one feature, spread across multiple workflows, deployed across products, included in pricing, or supported by usage and revenue evidence?

### RQ5 — Task-specific defensibility

After accounting for the frontier alternative, what economically necessary differentiation remains?

Potential mechanisms include:

- persistent workflow state;
- access controls and permissions;
- customer-specific integrations;
- transaction execution;
- specialized production controls;
- regulated authority;
- licensed or proprietary assets that materially affect the customer outcome;
- physical or live-human requirements;
- migration and switching friction.

### RQ6 — Strategic archetypes

Which firm-year and task-year archetypes emerge?

Examples include:

- high replicability with shallow response;
- high replicability with deep but commoditized response;
- low or moderate replicability with deep differentiated transformation;
- protected but stagnant products;
- product destruction, discontinuation, or portfolio-pivot paths;
- platform, orchestration, and execution-layer expansion.

### RQ7 — Operational and financial associations

After the dataset and measurements are frozen, how are these task-level trajectories associated with outcomes such as:

- revenue and subscription growth;
- segment growth;
- gross and operating margins;
- R&D and sales intensity;
- customer or subscriber counts;
- employee productivity;
- restructuring or impairment;
- stock-market outcomes, where a defensible design is possible?

The repository does not precommit to a causal design before the data-generating process is validated.

---

## 4. Conceptual model

The project represents the economic process as a sequence:

```text
Customer need
  → focal firm's product and capability
  → customer-facing task and deliverable
  → frontier alternative at date t
  → firm's product transformation response
  → remaining differentiation and switching friction
  → deployment and commercialization
  → observed strategic and economic trajectory
```

For task `i`, firm `f`, and observation date `t`, the thesis records:

- what the customer is trying to accomplish;
- which product and capability support that objective;
- whether the task is core, major supporting, or peripheral;
- how the task was delivered at that date;
- what frontier system was available at that date;
- how fully the frontier system could replace the focal product for the underlying need;
- how deeply AI was integrated into the focal product task;
- how broadly the capability was deployed;
- what requirements remained difficult to substitute;
- how the task changed relative to the prior observation.

The conceptual model deliberately avoids defining an AI adopter as a winner. High AI transformation can represent offensive innovation, defensive adaptation, or commoditized imitation. The interpretation depends on frontier replicability, scale, and defensibility.

---

## 5. Scope and empirical population

### 5.1 Time period

The initial target period is approximately **2022–2026**. The pilot comparison of
observation conventions is complete (ADR-046).

Two conventions were compared:

1. **Filing-date observation:** the annual observation is anchored to the publication date of the annual filing.
2. **Fiscal-year observation:** the source packet is bounded by the filing date but assigned to the associated fiscal year.

**Both bound the source packet by the filing date.** They differ in the label
assigned to the observation, not in which sources are admissible. The comparison
therefore separates two ideas that the shorthand "filing-date versus fiscal-year"
had merged:

- the **source-admission (evidence-availability) cutoff** is the
  filing/publication date, and is what `observation_cutoff_date` means in the
  packet and authorization schemas;
- the **analytical period assignment** is the fiscal year, carried by
  `period_of_report`, `fiscal_year_end_date` and `observation_year`.

For the first HubSpot observation the source-admission cutoff is `2025-02-12` and
the analytical period assignment is FY2024. Using a fiscal-period-end date as a
source-admission cutoff is rejected, because an annual report is filed after the
period it reports on; that rejection concerns the admission boundary only and is
not a statement about fiscal-year panel assignment.

Both rules must be applied consistently throughout the released dataset, and
consistently with each other: the source-admission cutoff rule that decides which
sources are admissible, and the analytical-period-assignment rule that decides
which period an observation belongs to. Neither may vary per firm, per year, or
per source family, and satisfying one does not satisfy the other.

The analytical period assignment currently stops at the admission/ingestion
artifact: no schema carries it, and no extraction packet, authorization, or
prediction artifact yet carries a reproducible fiscal-year key. Panel construction
on a fiscal-year basis requires a successor increment that adds a hash-bound
carrier for that label.

### 5.2 Firm universe

The intended population is publicly listed software and software-enabled technology firms with sufficient official source coverage during the observation window.

The final inclusion criteria will be specified in `SPEC-001`, but the design anticipates rules covering:

- public listing and SEC filing availability;
- stable firm identity through CIK and ticker resolution;
- material software or digitally delivered product activity;
- sufficient source coverage for at least a minimum number of observation dates;
- transparent handling of mergers, acquisitions, spin-offs, bankruptcies, and delistings.

The final number of firms is not yet frozen. A broad universe may contain several hundred firms, but the feasible release size depends on source-discovery coverage, historical web availability, extraction accuracy, and validation cost.

### 5.3 Pilot and sentinel sample

Before scaling, the project will use a deliberately heterogeneous sentinel sample. Firms will be selected before inspecting final scores and will represent different mechanisms, including:

- direct consumer substitution;
- enterprise workflow software;
- creative and media production;
- cloud infrastructure and cybersecurity;
- proprietary-data businesses;
- human-service-heavy offerings;
- AI-native products;
- firms showing limited AI-related product change.

The sentinel set is used to develop and validate the ontology, not to establish the thesis result.

---

## 6. Unit of analysis

### 6.1 Primary observation

The primary unit is:

```text
firm × observation date × product × capability × customer-facing task
```

This level is chosen because a firm may contain heterogeneous products with very different exposure and transformation profiles. A document assistant, a creative production engine, a cloud platform, and a marketing application cannot be represented reliably by one undifferentiated firm-level label.

### 6.2 Longitudinal representation

Rows are not overwritten as products change. Each dated task is stored as a separate **task observation**. Adjacent observations are linked through explicit **transition records**.

This permits the dataset to distinguish:

- unchanged task continuation;
- renaming or repackaging;
- expansion or contraction;
- generative or workflow transformation;
- split and merge events;
- replacement, discontinuation, and entry.

### 6.3 Why capability is a separate layer

A capability is the function the product provides; a task is the customer's economic job.

One capability can support multiple tasks. For example, an image-generation capability may support concept development, advertising production, product visualization, and social-media creation.

Conversely, one task may rely on multiple capabilities. An enterprise incident-resolution task may combine retrieval, summarization, classification, workflow recommendation, approval routing, and action execution.

Keeping capability and task separate improves longitudinal matching and prevents feature names from being mistaken for economic tasks.

---

## 7. Product–Capability–Task ontology

The canonical hierarchy is:

```text
Company
  → Product family
    → Product
      → Capability
        → Customer-facing task
          → Underlying customer need
```

### 7.1 Product family

A stable commercial grouping used to organize related products. It may correspond to a suite, cloud, solution family, or reporting segment, but it is not automatically a product.

Examples include a creative suite, document cloud, security cloud, or customer-experience family.

### 7.2 Product

A product is an identifiable customer offering that can be purchased, licensed, subscribed to, deployed, or used.

A valid product generally has at least one of the following:

- a distinct name and customer-facing description;
- separate documentation or deployment;
- a distinct user experience;
- separate pricing, packaging, administration, or commercial boundary.

The extraction excludes generic labels such as “AI,” “innovation,” or “platform” unless the evidence establishes a distinct offering.

### 7.3 Bundle and plan

A bundle or plan is recorded separately from a product. It becomes a distinct product-like observation only when it creates a customer-facing workflow or commercial experience not represented by the constituent products alone.

This prevents packaging inflation from artificially increasing product counts.

### 7.4 Capability

A capability is a concrete customer-facing function.

Examples:

- generate images from text;
- answer questions about documents with citations;
- summarize and route a support incident;
- provision an employee account after approval;
- monitor infrastructure telemetry for anomalies.

Capability descriptions should be specific enough to distinguish functions but sufficiently implementation-neutral to compare across years.

### 7.5 Customer-facing task

A task is the economically meaningful job the customer uses the capability to accomplish.

The preferred syntax is:

```text
verb + object + intended outcome
```

Examples:

- Generate brand-consistent campaign assets for multichannel marketing.
- Obtain a step-by-step explanation of an academic problem to understand the solution.
- Resolve an IT incident by triaging it and initiating approved remediation.
- Retrieve reliable, cited information from a set of business documents.

A task is not:

- a product name;
- an interface click;
- a generic benefit such as “increase productivity”;
- an internal engineering activity;
- a separate row for every file format, industry, or delivery channel when the underlying economic job is unchanged.

### 7.6 Underlying customer need

The customer need is stated independently of the focal product. This is essential for the replicability counterfactual.

Example:

```text
Focal task:
Obtain cited answers from PDF documents using a document assistant.

Underlying customer need:
Understand and retrieve reliable information from documents.
```

The frontier model is assessed against the underlying need, not against the branded interface or proprietary feature name.

### 7.7 Task granularity

The governing rule is economic separability, not a fixed duration.

Tasks remain separate when:

- the customer can reasonably seek one outcome without the other;
- the deliverables differ materially;
- the purchase or use motivation differs;
- the tasks require meaningfully different product functions.

Tasks are merged when they are merely synonymous descriptions, delivery variants, or adjacent interface actions within one economic job.

### 7.8 Task role

Each validated task is classified in a separate pass:

- `core`: a central reason customers buy or use the product;
- `major_supporting`: materially enables, completes, or differentiates the core workflow;
- `peripheral`: convenience, administration, or optional enhancement;
- `unknown`: evidence is insufficient.

Task role is not inferred from text length, novelty, technical complexity, or AI terminology.

### 7.9 Availability status

The product, capability, and task layers record availability explicitly:

- `announced`;
- `private_beta`;
- `public_beta`;
- `general_availability`;
- `broadly_deployed_or_default`;
- `deprecated`;
- `discontinued`;
- `unknown`.

Roadmap language therefore does not become an active deployed task.

---

## 8. Data sources

The canonical corpus is restricted primarily to SEC materials and dated official company sources. This improves comparability, provenance, and reproducibility.

### 8.1 Tier 1 — SEC EDGAR sources

Eligible SEC materials include:

- 10-K and 20-F annual filings;
- 10-Q and relevant 6-K reports;
- 8-K current reports;
- exhibits attached to 8-K filings;
- earnings-release exhibits;
- investor-presentation exhibits;
- registration filings for newly public firms when required;
- relevant sections of annual reports, including Item 1, MD&A, risk factors, segment notes, and product-related financial disclosures.

#### Main roles of SEC documents

| SEC source | Primary role in the thesis |
|---|---|
| Annual filing Item 1 | Annual product, capability, task, market, and strategy baseline |
| 10-Q / 6-K | Intra-year launches, product changes, acquisitions, and deployment updates |
| 8-K and exhibits | Material product announcements, acquisitions, earnings releases, and investor presentations |
| MD&A | Operating drivers, investment, restructuring, customer and revenue context |
| Risk factors | Explicitly stated disruption, model dependency, data, copyright, regulatory, or competitive risks |
| Segment and financial notes | Revenue composition, acquired businesses, impairments, and segment changes |

Item 1 remains a central backbone because it is standardized, recurring, and often contains a broad product description. It is not assumed to contain all required information.

### 8.2 Tier 2 — Official investor-relations materials

Eligible materials include:

- earnings releases;
- earnings presentations;
- investor-day presentations;
- prepared remarks;
- official financial supplements;
- archived investor presentations.

These sources are especially important for deployment scale, customer counts, usage metrics, monetization, management framing, and dated product launches.

### 8.3 Tier 3 — Official product sources

Eligible materials include:

- product pages;
- solution pages;
- pricing pages;
- product comparison pages;
- official release notes;
- feature availability pages.

These sources help identify concrete customer-facing actions and product packaging that may be described only generally in annual filings.

### 8.4 Tier 4 — Official technical sources

Eligible materials include:

- developer documentation;
- API documentation;
- administration documentation;
- implementation guides;
- architecture guides;
- security and governance documentation;
- model cards or technical reports published by the firm.

These sources are especially important for distinguishing a text-generating assistant from a system that can access workflow context, invoke tools, update records, execute transactions, or coordinate agents.

### 8.5 Tier 5 — Official newsroom and blog

These sources are used for:

- dated launches;
- beta or general-availability announcements;
- partnerships;
- model support;
- feature descriptions;
- product naming and rebranding.

They are treated cautiously because they may contain promotional language. A press release can establish launch timing, but it does not automatically establish broad deployment or economic materiality.

### 8.6 Tier 6 — Archived official web pages

Historical product pages are required when current pages have changed. A page retrieved in 2026 cannot reconstruct a 2023 product state unless a valid archived snapshot or dated official announcement establishes the earlier feature.

For each archived source, the project stores:

- original URL;
- archive URL;
- snapshot date;
- retrieval date;
- content hash;
- source type;
- temporal-validity status.

### 8.7 Excluded canonical sources

The canonical extraction corpus excludes unrestricted third-party sources such as:

- Wikipedia;
- general news coverage;
- analyst reports;
- review sites;
- unsourced search snippets;
- social-media posts;
- current product pages used retrospectively without valid historical evidence.

A later accepted spec may allow narrowly defined third-party sources for external validation, but they will not silently enter the canonical product-task extraction corpus.

---

## 9. Source discovery and web collection

### 9.1 Firm-year source packets

Each firm-date observation receives a source packet containing, where available:

- the annual filing and relevant sections;
- quarterly or current-report product events up to the cutoff;
- official investor materials;
- dated product pages;
- dated technical documentation;
- release notes and newsroom announcements;
- a coverage and exclusion manifest.

### 9.2 Automated discovery

The discovery layer is expected to combine:

- SEC submissions metadata and filing indexes;
- SEC filing and exhibit retrieval;
- official-domain allowlists;
- investor-relations link discovery;
- product and documentation sitemap crawling;
- targeted search over official domains;
- historical snapshot discovery for relevant URLs.

A web scraper or crawler is therefore likely required, but it must be source-policy-aware. The crawler should not indiscriminately scrape the open web.

### 9.3 Discovery manifest

For each source category and firm-date, the manifest records:

- searched category;
- candidate URL;
- source type;
- official-domain status;
- publication date;
- retrieval status;
- failure reason;
- temporal validity;
- duplicate status;
- robots or access restriction;
- content hash;
- snapshot provenance.

Coverage is not assumed to be complete merely because one document was found.

### 9.4 Source-role separation

Different sources answer different questions. A technical guide may support execution depth, but not customer adoption. An earnings release may support usage or pricing, but not the full annual product universe. A risk factor may establish perceived disruption, but not product existence.

The evidence layer therefore preserves which source supports each claim.

---

## 10. Temporal design and prevention of future leakage

Temporal validity is a non-negotiable feature of the study.

### 10.1 Core rule

A source can support an observation only if:

```text
source_publication_date <= observation_cutoff_date
```

### 10.2 Required dates

Every relevant record includes:

- document publication date;
- retrieval timestamp;
- snapshot timestamp, when relevant;
- observation cutoff date;
- frontier baseline date.

### 10.3 Historical web pages

A current product page cannot be used to infer past capabilities without dated evidence. The system must find either:

- an archived page available by the cutoff;
- a dated release note;
- a dated official launch announcement;
- an SEC or investor-relations document describing the capability.

### 10.4 Beta, roadmap, and launch timing

Announced, beta, general-availability, and broadly deployed states are kept separate. A future roadmap statement can be stored as an announced candidate, but it does not enter the active-task universe until availability is supported.

### 10.5 Acquisitions

An acquired product is not treated as fully integrated when the acquisition closes. The data store separately records:

- announcement date;
- close date;
- product continuity;
- first appearance in the acquirer's product portfolio;
- evidence of technical or commercial integration.

### 10.6 Frontier model assignment

Each task observation is paired with the latest eligible frontier baseline available by the observation date. The evaluator is not allowed to use later capabilities.

---

## 11. Corpus storage and document normalization

### 11.1 Data zones

The repository separates data into immutable and derived zones:

- `data/raw/`: original SEC files, HTML, text, and downloaded artifacts;
- `data/snapshots/`: dated and hashed web captures;
- `data/normalized/`: cleaned text and structured passages;
- `data/interim/`: extraction candidates, unresolved matches, model outputs;
- `data/processed/`: validated released observations;
- `data/manifests/`: source, run, schema, and provenance metadata.

### 11.2 Immutability

Raw and snapshot content is content-addressed. A changed page creates a new object. It does not overwrite the earlier source.

### 11.3 Normalization

Normalization may include:

- HTML boilerplate removal;
- filing-section extraction;
- PDF text extraction when needed;
- table preservation or structured capture when material;
- whitespace and encoding normalization;
- heading hierarchy reconstruction;
- stable passage segmentation;
- duplicate and near-duplicate detection.

The normalized text must remain traceable to the raw source.

### 11.4 Passage IDs

Each normalized document is segmented into stable passages. A passage records:

- source ID;
- heading path;
- character offsets;
- source date;
- source type;
- passage text hash;
- URL and snapshot provenance.

Passage IDs should remain stable when unrelated portions of the document change.

### 11.5 Provenance chain

Every released task must be traceable through:

```text
task observation
  → capability observation
  → product observation
  → source passage
  → normalized document
  → raw or archived source
  → retrieval manifest
```

---

## 12. Extraction methodology

The extraction system is deliberately separated from the measurement system. Extraction describes what the company offered and what customers could do. It does not decide whether the task was replicable, defensible, successful, or beneficial.

### 12.1 Pass 0 — Source-packet validation

Before any product extraction:

- verify source dates;
- reject temporally invalid sources;
- classify source types;
- check minimum source coverage;
- resolve duplicate documents;
- record unavailable categories.

No extraction is performed from an invalid packet.

### 12.2 Pass 1 — Product discovery, high recall

The first product pass extracts all plausible customer-facing offerings, including uncertain candidates.

The objective is recall. The model is instructed not to resolve difficult bundle, family, or alias questions prematurely.

Each candidate includes:

- candidate name;
- normalized name;
- possible product family;
- entity type;
- target customers;
- availability status;
- evidence passage and quote;
- ambiguity;
- confidence.

### 12.3 Pass 2 — Product consolidation, high precision

The second product pass decides whether to:

- retain a distinct product;
- merge aliases or delivery variants;
- classify an entity as a product family;
- classify it as a bundle or plan;
- exclude it as strategy, capability, internal technology, or unsupported roadmap;
- leave it unresolved.

This two-pass design is intended to avoid both omission and product inflation.

### 12.4 Pass 3 — Capability extraction

For each validated product, the model extracts concrete customer-facing functions.

It ignores generic claims such as:

- “AI-powered innovation”;
- “improve productivity”;
- “industry-leading platform.”

Instead, it records the specific action supported by the evidence, such as:

- summarize a case;
- generate an image;
- answer a question with citations;
- classify a risk;
- update a record;
- execute an approved workflow.

The capability record can also include input types, output types, status, evidence, ambiguity, and confidence.

### 12.5 Pass 4 — Task discovery, high recall

Capabilities are translated into customer jobs.

The model is explicitly prohibited from evaluating:

- AI exposure;
- frontier capability;
- production systems;
- switching costs;
- defensibility;
- financial importance;
- business success.

Each candidate task includes:

- task text;
- underlying customer need;
- linked product and capability IDs;
- status;
- target customer;
- candidate role evidence;
- evidence passages and quotes;
- ambiguity and confidence.

### 12.6 Pass 5 — Task consolidation, high precision

The consolidation pass:

- merges semantic duplicates;
- splits over-broad combined jobs;
- removes capability labels presented as tasks;
- removes marketing abstractions;
- removes internal work;
- removes unsupported roadmap claims;
- resolves task granularity;
- chooses wording that can remain stable across years.

The key test is economic separability:

> Can the customer reasonably seek one outcome without the other, and are the deliverables or use motivations materially distinct?

### 12.7 Pass 6 — Task-role classification

Validated tasks are classified as core, major supporting, peripheral, or unknown.

The classifier must use product positioning and direct evidence. It cannot infer importance from:

- the number of mentions;
- technical sophistication;
- task novelty;
- AI terminology;
- the analyst's belief about future growth.

### 12.8 Pass 7 — Audit and adjudication

Before longitudinal matching, ambiguous boundaries are reviewed by:

- a human annotator;
- an independent model;
- or a formal disagreement-adjudication pass.

The audit focuses on:

- missing products;
- unsupported products;
- capability/task confusion;
- task duplication;
- over-splitting and under-splitting;
- evidence coverage;
- status and timing.

### 12.9 Structured outputs

Production runs return schema-constrained JSON. Unknown values remain unknown; they are not repaired by guessing.

The original model output, repair attempts, validation errors, and final accepted record are all preserved.

---

## 13. Longitudinal entity resolution and task transitions

### 13.1 Stable entity IDs

A dated product, capability, or task observation receives an observation ID. Stable IDs link economically continuous entities across years.

The system does not assume that identical names indicate continuity or that name changes indicate new entities.

### 13.2 Candidate predecessor generation

For each successor observation, the system creates predecessor candidates using deterministic signals such as:

- same firm;
- same or related product family;
- normalized name similarity;
- customer-need embedding similarity;
- capability overlap;
- action, object, and deliverable similarity;
- timing and product status;
- known acquisitions or rebranding.

Candidate generation favors recall and can produce many-to-many matches.

### 13.3 LLM or expert adjudication

A separate adjudicator examines predecessor and successor evidence and answers:

> Does the successor serve the same underlying customer need and deliverable, represent a transformation of that task, or create a distinct economic job?

### 13.4 Transition labels

The planned label set includes:

- `same_task_unchanged`;
- `renamed_or_repackaged`;
- `expanded_scope`;
- `contracted_scope`;
- `ai_assisted`;
- `generative_transformation`;
- `workflow_integrated`;
- `agentified_or_action_enabled`;
- `split_into_multiple_tasks`;
- `merged_from_multiple_tasks`;
- `replaced`;
- `discontinued`;
- `new_task`;
- `uncertain`.

### 13.5 Split and merge events

The transition table supports multiple predecessor and successor IDs. This avoids forcing one-to-one matching when:

- one broad task becomes several specialized tasks;
- multiple formerly separate functions become one integrated workflow;
- acquired products are consolidated;
- a suite creates a new cross-product task.

### 13.6 Discontinuation standard

Absence from a single annual filing is not sufficient to classify a task as discontinued. The system seeks corroboration from:

- later official pages;
- product-status announcements;
- deprecation documentation;
- portfolio descriptions;
- acquisition or divestiture evidence.

### 13.7 Transition confidence

- `high`: explicit continuity, replacement, or discontinuation evidence;
- `medium`: strong semantic and product continuity;
- `low`: plausible but source coverage incomplete;
- `unknown` or unresolved: alternatives are preserved.

---

## 14. Dated frontier baseline registry

Frontier replicability must be evaluated against a frozen, dated description of the best generally accessible system at the observation date.

### 14.1 Registry unit

A baseline is defined by date and access regime, not only by a model name.

The registry records:

- system name;
- release date;
- public-product and API availability dates;
- relevant access restrictions;
- supported modalities;
- context length;
- browsing or retrieval;
- code execution;
- tool and function calling;
- image, audio, or video generation;
- reliability and limitations;
- primary evidence sources.

### 14.2 Evidence policy

The baseline is constructed from primary sources such as:

- model documentation;
- technical reports;
- system cards;
- dated release announcements;
- official benchmark reports.

Benchmarks inform capability but do not automatically prove customer-task quality.

### 14.3 Assignment rule

For each task observation, the latest eligible baseline available by the observation cutoff is assigned. If availability was limited by pricing, geography, waitlist, or API access, the access assumption is recorded.

### 14.4 Frozen evaluation packet

The replicability evaluator receives a concise dated baseline summary. It must not use general current knowledge about later systems.

---

## 15. Task-level measurement framework

No single composite score is currently frozen. The initial design preserves component judgments so that construct validity and aggregation sensitivity can be tested.

### 15.1 Frontier Task Replicability

#### Construct question

> At the observation date, could the frontier general-purpose system satisfy the task's underlying customer need without the focal firm's product at comparable practical quality?

#### Candidate ordinal labels

- `none`: not meaningfully capable;
- `assistive_only`: helps a user but does not deliver the core outcome;
- `partial_substitute`: provides a meaningful portion of the outcome but remains incomplete;
- `near_substitute`: performs most of the task at practically comparable quality, with limited gaps or friction;
- `direct_substitute`: satisfies the core need end to end with low switching friction;
- `unknown`: insufficient evidence.

#### Component dimensions

The assessment considers separately:

1. **Core deliverable quality** — Can the model produce the required output at usable quality?
2. **Reasoning and domain adequacy** — Does the task require domain accuracy, complex reasoning, or specialized knowledge beyond the baseline?
3. **Modality support** — Can the baseline process and generate the necessary text, image, audio, video, code, or structured data?
4. **Tool and data requirements** — Does completion require browsing, proprietary databases, live systems, APIs, or physical execution?
5. **End-to-end completeness** — Can the model complete the customer job rather than only one substep?
6. **User effort** — How much prompting, verification, manual transfer, or assembly is required?
7. **Latency and cost** — Is the frontier alternative practically usable at the required frequency and scale?
8. **Firm-specific assets** — Are focal-firm assets genuinely necessary for the underlying need?
9. **Switching friction** — Can the customer move to the frontier alternative easily?

The evaluator is instructed not to lower replicability merely because the focal firm owns proprietary data. It must explain whether the data is materially necessary for the customer outcome.

### 15.2 AI Transformation Depth

#### Construct question

> What concrete role does AI play in performing this product task at the observation date?

#### Candidate ladder

| Level | Interpretation |
|---:|---|
| 0 | No concrete AI integration, or marketing-only language |
| 1 | Peripheral assistance: search, summary, drafting, autocomplete, suggestion |
| 2 | Direct output generation, classification, recommendation, prediction, or content transformation |
| 3 | Native workflow integration using product context, customer data, or persistent workflow state |
| 4 | Multi-step action execution through tools, APIs, records, approvals, or transactions |
| 5 | Goal-directed orchestration with planning, monitoring, adaptation, and exception handling |

The highest level is assigned only when fully supported by evidence.

#### Required supporting observations

Where available, the measurement records:

- concrete AI action;
- input and output;
- access to customer or product context;
- access to workflow state;
- use of tools or APIs;
- record or transaction updates;
- planning and monitoring;
- autonomy boundaries;
- human review, approval, or exception role.

AI branding alone receives no depth credit.

### 15.3 Deployment Scale

Scale is initially stored as separate components, because product breadth, customer adoption, and commercialization are different empirical concepts.

#### Components

1. **Availability**
   - announced;
   - private beta;
   - public beta;
   - general availability;
   - default or broadly deployed.

2. **Feature breadth**
   - one narrow feature;
   - multiple features supporting the task;
   - broad feature integration.

3. **Workflow breadth**
   - isolated step;
   - multiple steps in one workflow;
   - end-to-end workflow coverage.

4. **Product breadth**
   - one product;
   - multiple products;
   - cross-product or platform-wide layer.

5. **Customer deployment evidence**
   - named pilots;
   - customer examples;
   - customer counts;
   - attach rates;
   - installed-base penetration.

6. **Commercialization evidence**
   - included in an existing plan;
   - premium add-on;
   - usage credits;
   - consumption pricing;
   - separate subscription;
   - enterprise contract.

7. **Usage and revenue evidence**
   - generations, actions, or transactions;
   - monthly or daily active users;
   - bookings, ARR, revenue, or consumption;
   - subscriber or retention effects.

A broad strategy statement cannot fill these fields.

### 15.4 Task-Specific Defensibility

#### Construct question

> If the customer used the dated frontier alternative instead, which material task requirements would remain unmet, and are those requirements difficult enough to replace to sustain the focal product's value?

#### Candidate mechanisms

- workflow state;
- permissions and governance;
- customer-specific integrations;
- system-of-record access;
- execution and transaction completion;
- specialized production or quality controls;
- regulated authority or certification;
- licensed content or rights;
- proprietary data that materially improves the outcome;
- physical delivery or hardware;
- live-human network;
- collaboration and organizational embedding;
- migration and switching costs.

#### Counterfactual discipline

The existence of a proprietary asset is not sufficient. The evaluator must state:

1. what the frontier alternative can already do;
2. what remains unmet;
3. why the unmet requirement matters economically;
4. whether it can be reproduced with standard tools or ordinary integrations;
5. whether it creates real switching friction.

The system must not grant defensibility because the firm is large, reputable, secure, or technologically sophisticated in general.

### 15.5 Task economic importance

Task role is the initial importance measure:

- core;
- major supporting;
- peripheral;
- unknown.

Where product- or segment-level revenue is disclosed, revenue weights may later be used. Missing revenue weights will not be imputed from textual prominence.

### 15.6 Derived measures

Any later derived measure must:

- specify a theory;
- preserve the underlying components;
- treat unknown as missing rather than zero;
- report sensitivity to weighting and aggregation;
- avoid defining transformation as beneficial by construction;
- pass out-of-sample anchor and adversarial review.

Possible derived concepts may include frontier disruption pressure, adaptive transformation, or differentiated transformation. These remain provisional until the measurement pilot is complete.

---

## 16. Core data tables

The final research database is relational. The principal tables are described below.

### 16.1 Company registry

**Purpose:** stable firm identity and universe membership.

Likely fields:

- `company_id`;
- legal name;
- ticker;
- CIK;
- listing exchange;
- industry classification;
- fiscal year end;
- observation start and end;
- inclusion status;
- exclusion reason;
- predecessor or successor firm IDs;
- acquisition, merger, spin-off, or delisting flags.

### 16.2 Source document table

**Purpose:** one record per retrieved document or web snapshot.

Core fields include:

- `source_id`;
- `company_id`;
- source type;
- title;
- original and archive URL;
- publication date;
- retrieval and snapshot timestamps;
- content hash;
- MIME type;
- official-source status;
- temporal-validity status;
- access status;
- schema version.

### 16.3 Source passage table

**Purpose:** stable evidence units used by all later observations.

Fields include:

- `passage_id`;
- `source_id`;
- heading path;
- character offsets;
- normalized text;
- text hash;
- source date and type;
- page or section information when available.

### 16.4 Product observation table

**Purpose:** dated product universe.

Core fields include:

- `product_observation_id`;
- `stable_product_id`;
- `company_id`;
- observation cutoff;
- product family;
- product name and normalized name;
- entity type: product, family, bundle, plan, or candidate;
- target customers;
- availability status;
- commercialization description;
- evidence;
- ambiguity;
- confidence.

### 16.5 Capability observation table

**Purpose:** dated concrete customer-facing functions.

Core fields include:

- `capability_observation_id`;
- `stable_capability_id`;
- linked product observation;
- capability text and normalized capability;
- input types;
- output types;
- availability status;
- evidence;
- ambiguity;
- confidence.

### 16.6 Task observation table

**Purpose:** primary task-year panel.

Core fields include:

- `task_observation_id`;
- `stable_task_id`;
- `company_id`;
- observation cutoff;
- linked product and capability IDs;
- task text;
- underlying customer need;
- task role;
- availability status;
- target customer;
- monetization model;
- optional task components;
- concrete AI action observed;
- evidence;
- ambiguity;
- confidence.

### 16.7 Task transition table

**Purpose:** link task observations across time.

Core fields include:

- `transition_id`;
- `company_id`;
- predecessor task IDs;
- successor task IDs;
- transition type;
- transition summary;
- evidence from both periods;
- alternative labels;
- confidence.

### 16.8 Frontier baseline table

**Purpose:** dated capability environment for counterfactual assessment.

Core fields include:

- `baseline_id`;
- eligible-from and eligible-to dates;
- system name;
- access regime;
- modalities;
- capability profile;
- limitations;
- primary evidence;
- schema version.

### 16.9 Task measurement table

**Purpose:** store construct-level judgments separately from extraction.

Core fields include:

- `measurement_id`;
- `task_observation_id`;
- `frontier_baseline_id`;
- replicability components and label;
- transformation-depth components and level;
- deployment-scale components;
- defensibility components and judgment;
- task importance;
- evidence;
- confidence.

### 16.10 Extraction and model-run manifest

**Purpose:** reproducibility of every LLM-assisted stage.

Core fields include:

- run ID and stage;
- start and completion timestamps;
- code commit;
- spec version;
- schema hash;
- prompt hash;
- source-manifest hash;
- model provider and model name;
- model parameters;
- fallbacks;
- status and error count.

### 16.11 Aggregated tables

The released data will include validated views at:

- task-date;
- capability-date;
- product-date;
- product-family-date;
- firm-date.

Task-level rows remain primary. Aggregation is a reporting layer, not a substitute for task-level validity.

---

## 17. Financial and operational outcome data

The product-task corpus is conceptually separate from the outcome panel. Financial outcomes are not used to tune extraction or measurement.

### 17.1 Potential outcome sources

Potential sources include:

- SEC XBRL company facts;
- annual and quarterly financial statements;
- segment disclosures;
- earnings-release exhibits;
- subscriber, customer, usage, and ARR disclosures;
- employee counts and restructuring disclosures;
- market-price data from a separately documented source, if included.

### 17.2 Candidate accounting and operating variables

Possible firm-quarter or firm-year variables include:

- revenue;
- subscription or recurring revenue;
- segment revenue;
- gross profit and gross margin;
- operating income and operating margin;
- R&D expense and intensity;
- sales and marketing expense and intensity;
- capital expenditures;
- cash flow;
- customer or subscriber count;
- net retention or remaining performance obligations, where disclosed;
- employee count;
- revenue per employee;
- restructuring expense;
- goodwill or asset impairment;
- acquisition and divestiture indicators.

### 17.3 Outcome separation

Outcome data will be joined only after:

- the source corpus is frozen;
- extraction is validated;
- longitudinal task matching is accepted;
- measurement rubrics are frozen;
- the gold set and evaluation report are complete.

This prevents the scoring system from being tuned to produce expected winners and losers.

---

## 18. Aggregation and decomposition

### 18.1 Why aggregation is difficult

A firm can appear more transformed simply because its documents list more tasks. Arbitrary task splitting can dominate an equal-task average. Product-heavy firms can also outweigh narrow firms for purely representational reasons.

### 18.2 Candidate aggregation methods

The pilot will compare:

1. **Task-weighted aggregation** — equal weight to validated tasks.
2. **Role-weighted aggregation** — different weights for core, major supporting, and peripheral tasks.
3. **Product-balanced aggregation** — equalize product contribution before firm aggregation.
4. **Product-family-balanced aggregation** — prevent one large product family from mechanically dominating.
5. **Revenue-weighted aggregation** — used only where disclosed and comparable.
6. **Multiple published versions** — report several aggregations rather than hide sensitivity.

### 18.3 Missingness

Unknown measurement values remain missing. They are not treated as zero.

Every aggregate will report:

- number of eligible tasks;
- number of measured tasks;
- weighted coverage;
- unknown rate;
- confidence distribution;
- source-coverage indicators.

### 18.4 Dynamic decomposition

Firm-level change will be decomposed into:

- within-task score changes;
- entry of new tasks;
- exit of tasks;
- task expansion or contraction;
- product-mix change;
- acquisitions and divestitures;
- role reclassification;
- changes in source coverage.

This distinguishes genuine product transformation from portfolio composition effects.

---

## 19. Validation and evaluation harness

The evaluation harness is a release gate, not a final quality check.

### 19.1 Gold-set protocol

Gold observations are created using:

- two independent annotators;
- the same date-bounded source packet;
- no access to financial outcomes;
- recorded annotator confidence;
- formal disagreement adjudication;
- versioned annotation guidelines.

### 19.2 E1 — Source discovery evaluation

Metrics include:

- official-domain precision;
- required-category recall;
- publication-date resolution;
- temporal-invalid rate;
- duplicate-source rate;
- source-coverage completeness.

### 19.3 E2 — Product extraction evaluation

Metrics include:

- product precision and recall;
- suite, bundle, and plan error rate;
- alias resolution;
- unsupported-roadmap false positives;
- evidence validity.

### 19.4 E3 — Capability extraction evaluation

Metrics include:

- concrete-action precision;
- marketing-abstraction false positives;
- product/capability boundary agreement;
- availability accuracy;
- evidence support.

### 19.5 E4 — Task extraction evaluation

Metrics include:

- economic-task precision and recall;
- duplicate rate;
- over-split and under-split rates;
- customer-need quality;
- evidence coverage;
- task-role agreement.

### 19.6 E5 — Longitudinal matching evaluation

Metrics include:

- predecessor-link precision and recall;
- transition-label macro F1;
- false-new rate;
- false-discontinued rate;
- split and merge accuracy;
- unresolved rate.

### 19.7 E6 — Measurement evaluation

Metrics include:

- rubric agreement;
- temporal leakage;
- marketing-only false positives;
- anchor-task ordering;
- calibration of unknown labels;
- component-to-final-label consistency;
- proprietary-data overclaim rate.

### 19.8 Adversarial fixtures

Required adversarial cases include:

- generic AI strategy language with no concrete action;
- an announced agent with no availability evidence;
- an “agent” that only drafts text;
- a product rename with no task change;
- the same mechanism serving distinct economic tasks;
- multiple features forming one integrated customer task;
- proprietary data that is not necessary for the underlying need;
- a current product page incorrectly used for an earlier observation;
- a missing product mistaken for discontinuation;
- a bundle mistaken for multiple products.

### 19.9 Ablation tests

The project will compare:

- Item 1 only versus the enriched official corpus;
- annual filing only versus annual plus intra-year sources;
- product pages with and without developer documentation;
- one-pass extraction versus recall-and-consolidation;
- strong-model versus production-model extraction;
- longitudinal matching with and without deterministic candidate generation.

These ablations will quantify the incremental value of each source and pipeline component.

### 19.10 Full-universe release gate

A full-scale run is blocked until:

- source temporal tests pass;
- product and task gold thresholds are achieved;
- evidence validity is at least the accepted threshold, currently targeted at 0.98;
- no critical legacy-contamination failure exists;
- longitudinal matching reliability is accepted;
- blinded measurement review is complete.

---

## 20. Use of language models

### 20.1 Model roles

High-capability reasoning models are best suited for:

- ontology and schema review;
- difficult product consolidation;
- longitudinal matching adjudication;
- measurement counterfactuals;
- disagreement resolution;
- evaluation failure diagnosis;
- final audit.

Lower-cost schema-reliable models may be used for:

- bulk candidate extraction;
- source classification;
- repetitive document tagging;
- first-pass normalization support;
- structured candidate generation.

### 20.2 Model separation

Where feasible, extraction and evaluation should not be performed by the same model configuration. Independent-model review reduces correlated errors.

### 20.3 Run logging

Each model run records:

- provider;
- model and version or UI label;
- prompt hash;
- schema hash;
- governing spec version;
- source-manifest hash;
- temperature and relevant parameters;
- fallback models;
- timestamps;
- validation and repair history.

### 20.4 No silent repair

Schema-invalid output may undergo a logged repair pass, but the original response and repair instructions are preserved. Semantic claims cannot be silently invented during repair.

### 20.5 Unknown rather than guess

The model is explicitly permitted to return unknown, unresolved, or ambiguous. The system should prefer visible missingness over confident fabrication.

---

## 21. Illustrative task examples

The following examples demonstrate how the framework works. They are methodological illustrations, not frozen scores.

### 21.1 Direct-answer educational task

```text
Company: educational software provider
Product: academic support service
Capability: conversational step-by-step explanation
Task: obtain a step-by-step explanation of an academic problem
Customer need: understand and solve the problem
```

Potential interpretation:

- **Frontier replicability:** may rise sharply as dated frontier models become more accurate and multimodal.
- **AI transformation depth:** may be moderate or high if the product becomes conversational, personalized, and content-generating.
- **Deployment scale:** depends on availability, subscriber coverage, plan inclusion, and actual usage.
- **Defensibility:** remains low if proprietary content is not necessary for comparable practical quality and the customer can switch directly to a general-purpose model.

This example shows why high transformation is not automatically an economic advantage.

### 21.2 Brand-consistent creative production task

```text
Company: creative software provider
Product: generative creative platform
Capability: generation and editing using brand models and production controls
Task: generate and govern brand-consistent campaign assets at scale
Customer need: produce usable, compliant marketing assets efficiently
```

Potential interpretation:

- **Frontier replicability:** generic image generation may be high, while the complete branded production task may be only partially substitutable.
- **AI transformation depth:** can progress from generation to native editing, cross-product workflow integration, APIs, and orchestration.
- **Deployment scale:** can be observed through cross-product availability, credits, enterprise services, customer adoption, and usage.
- **Defensibility:** may remain through brand assets, production controls, collaboration, enterprise governance, workflow integration, and downstream activation.

### 21.3 Enterprise incident-resolution task

```text
Company: enterprise workflow software provider
Product: IT service-management platform
Capability: summarize, classify, route, and execute approved remediation
Task: resolve an IT incident by triaging it and initiating approved actions
Customer need: restore service reliably with appropriate controls
```

Potential interpretation:

- **Frontier replicability:** a model may explain or recommend actions but cannot necessarily access systems, permissions, records, and approvals end to end.
- **AI transformation depth:** can reach action execution or orchestration.
- **Deployment scale:** requires evidence across workflows, products, customers, pricing, and usage.
- **Defensibility:** may derive from system-of-record integration, permissions, workflow state, compliance, execution rights, and organizational switching costs.

---

## 22. Empirical analysis plan

The first empirical contribution is descriptive and measurement-oriented. Causal claims will be considered only after construct validation.

### 22.1 Descriptive product evolution

Planned outputs include:

- number of product families, products, capabilities, and tasks by firm-date;
- task entry and exit rates;
- distribution of task roles;
- transition matrices;
- prevalence of AI assistance, generation, workflow integration, execution, and orchestration;
- portfolio-pivot measures;
- firm and industry trajectories.

### 22.2 Frontier pressure trajectories

For each task and firm:

- replicability levels over time;
- within-task increases caused by frontier progress;
- exposure changes caused by product-mix shifts;
- differences between consumer and enterprise tasks;
- differences by modality and data requirements.

### 22.3 Transformation trajectories

Planned analyses include:

- first appearance of concrete AI integration;
- movement between transformation-depth levels;
- lag between frontier capability and firm response;
- transition from feature-level assistance to workflow execution;
- cross-product diffusion;
- commercialization timing.

### 22.4 Strategic archetypes

Firms and tasks may be grouped using the separate constructs rather than a predetermined winner/loser label.

Potential archetypes include:

- exposed and minimally transformed;
- exposed and deeply transformed but weakly defended;
- moderately exposed and strongly differentiated;
- low-exposure execution platforms;
- product-pivot and task-exit firms;
- AI-native task entrants.

Clustering, rule-based quadrants, or latent-class methods may be compared, but any typology must remain interpretable and evidence-linked.

### 22.5 Case studies

A small number of evidence-rich firms can be presented as longitudinal case studies. Every narrative statement will be traceable to dated task observations and source passages.

Case studies are used to illustrate mechanisms, not to substitute for the panel analysis.

### 22.6 Outcome associations

After measurement freeze, possible panel specifications may relate lagged task- or firm-level constructs to future operational outcomes.

A generic exploratory model may take the form:

```text
Outcome_f,t+h
  = firm fixed effects
  + time fixed effects
  + frontier replicability_f,t
  + transformation depth_f,t
  + deployment scale_f,t
  + defensibility_f,t
  + theoretically motivated interactions
  + controls
  + error
```

Important interaction terms may include:

- replicability × transformation depth;
- transformation depth × defensibility;
- replicability × defensibility;
- transformation depth × deployment scale.

These regressions will initially be interpreted as associations. Product transformation is endogenous, and post-shock adoption is itself a response to expected threat and opportunity.

### 22.7 Alternative empirical designs

Depending on data quality, the project may examine:

- event studies around dated AI-product launches;
- matched task-level comparisons;
- change-on-change models;
- product-level survival or discontinuation;
- portfolio-pivot analysis;
- revenue-segment case studies;
- timing of transformation relative to frontier releases.

No method will be selected solely because it produces statistically significant results.

---

## 23. Threats to validity and limitations

### 23.1 Disclosure bias

Public firms differ in how specifically they describe products. Some companies provide detailed technical documentation; others use broad marketing language. Source-coverage controls and uncertainty reporting are therefore necessary.

### 23.2 Marketing bias

Official sources are not neutral. They may exaggerate novelty or future importance. The design mitigates this by requiring concrete actions, dated availability, and separate scale evidence.

### 23.3 Historical web availability

Older product pages may be unavailable or incompletely archived. Missing historical documentation can create false task entry or exit. Coverage flags must remain visible.

### 23.4 Task granularity

Task definitions involve judgment. Over-splitting and under-splitting can change firm-level aggregates. The project addresses this through a formal ontology, consolidation pass, gold annotation, and aggregation sensitivity.

### 23.5 Frontier capability uncertainty

Benchmarks do not perfectly measure practical customer quality. Replicability assessments therefore use component judgments, evidence, confidence, and dated access assumptions.

### 23.6 Quality parity and switching behavior

Official documents cannot objectively prove whether a frontier alternative is equal or superior in every task or whether customers will actually switch. Where important, independent benchmark tasks, product tests, or external validation may be required.

### 23.7 Defensibility inference

Workflow, data, and permissions can create value, but their economic necessity may be overstated. The explicit counterfactual and proprietary-data audit are designed to reduce this risk.

### 23.8 Outcome endogeneity

Firms adopt AI in response to anticipated demand, competition, resources, and management quality. Transformation depth is not randomly assigned. Causal claims require a separate identification strategy.

### 23.9 Survivorship and sample selection

Publicly listed firms with adequate documents may differ from private or failed firms. Mergers, delistings, and bankruptcies must be retained where possible rather than dropped silently.

### 23.10 Model dependence

LLM-assisted annotation can vary by model and prompt. Versioning, independent annotation, regression tests, and model-ablation studies are required.

---

## 24. Reproducibility and governance

### 24.1 Clean-room design

The repository is intentionally isolated from previous scoring projects. Legacy prompts, schemas, labels, and outputs are not imported into the new extraction system.

This prevents earlier assumptions from leaking into the new ontology and measurement design.

### 24.2 Versioning

The project independently versions:

- source corpus;
- normalization pipeline;
- schemas;
- extraction prompts;
- model routes;
- gold annotations;
- matching rules;
- measurement rubrics;
- aggregation methods;
- analysis code.

### 24.3 Decision log

Major changes require:

- an accepted spec;
- a decision-log entry;
- updated tests and evaluation fixtures;
- a migration plan for affected data;
- a new version identifier.

### 24.4 Reproducibility package

A formal release should include:

- source manifest with URLs, dates, and hashes;
- schema versions;
- prompt hashes;
- model-run manifests;
- code commit;
- error and exclusion logs;
- evaluation report;
- aggregation sensitivity tables;
- data dictionary;
- audit packets for selected examples.

### 24.5 No destructive updates

Corrections create superseding records. Historical raw files and prior released observations are not silently mutated.

---

## 25. Planned implementation sequence

### Phase 1 — Architecture and policy freeze

- finalize research questions;
- finalize source and temporal policies;
- define the firm universe pilot;
- freeze ontology version 0.1;
- finalize source, product, capability, and task schemas;
- create sentinel firms and gold protocol.

### Phase 2 — Source corpus construction

- build SEC discovery and ingestion;
- build official-web discovery;
- capture historical snapshots;
- normalize documents;
- produce coverage and failure reports;
- freeze pilot source packets.

### Phase 3 — Product and task extraction

- run high-recall product discovery;
- run high-precision product consolidation;
- extract capabilities;
- discover and consolidate tasks;
- classify task roles;
- perform audit and adjudication.

### Phase 4 — Longitudinal matching

- assign stable product and task IDs;
- generate predecessor candidates;
- classify transitions;
- review split, merge, acquisition, and discontinuation cases;
- evaluate matching reliability.

### Phase 5 — Measurement pilot

- build the frontier baseline registry;
- assess task replicability;
- assess AI transformation depth;
- assess deployment components;
- assess task-specific defensibility;
- run anchor, adversarial, and model-ablation tests.

### Phase 6 — Scale and freeze

- scale only after release gates pass;
- freeze source corpus version;
- freeze extraction version;
- freeze transition version;
- freeze measurement rubric;
- publish evaluation report.

### Phase 7 — Descriptive and outcome analysis

- construct task, product, and firm trajectories;
- produce transition and archetype tables;
- conduct case studies;
- join financial outcomes;
- estimate descriptive and, where defensible, causal models.

---

## 26. Expected final deliverables

The thesis project is expected to produce:

1. **A dated official-source corpus** for the eligible firm-period observations.
2. **A longitudinal product–capability–task database** with direct evidence.
3. **A task-transition panel** capturing continuity, AI transformation, entry, exit, splits, merges, and pivots.
4. **A dated frontier-model registry** aligned with each observation cutoff.
5. **Separate task-level measures** of frontier replicability, AI transformation depth, deployment scale, defensibility, and economic importance.
6. **Aggregated product- and firm-level views** with coverage and sensitivity reporting.
7. **A validation package** containing gold annotations, adversarial tests, ablations, and regression-eval reports.
8. **Descriptive empirical results** on how software product tasks evolved during the frontier-LLM transition.
9. **An outcome-ready panel** for later financial and operational analysis.
10. **Fully reproducible code, prompts, schemas, manifests, and audit records.**

---

## 27. Methodological principles to preserve

The project should preserve the following principles throughout implementation:

1. **Extraction and scoring remain separate.**
2. **AI wording is not evidence of deep adoption.**
3. **A concrete customer-facing action is required.**
4. **Task-level observations are primary.**
5. **The frontier counterfactual is dated.**
6. **Deep transformation is not defined as beneficial.**
7. **Scale, depth, replicability, and defensibility remain distinct.**
8. **Proprietary data creates defensibility only when it is necessary for the customer outcome.**
9. **Unknown is preferable to unsupported certainty.**
10. **Financial results are not used to tune the measurement system.**
11. **Every released claim is traceable to evidence.**
12. **Historical sources are immutable and temporally valid.**
13. **Task entry and exit are distinguished from disclosure changes.**
14. **Aggregation sensitivity is reported rather than hidden.**
15. **No full-universe run occurs before the evaluation gates pass.**

---

## 28. Current status and open decisions

The repository currently defines the architecture, source policy, ontology, extraction prompts, schemas, measurement families, and evaluation structure. The following decisions remain intentionally open until pilot evidence is available:

- final company-universe size and inclusion thresholds;
- a hash-bound carrier for the analytical period assignment, which today stops at the admission/ingestion artifact and therefore does not yet support a fiscal-year panel join (see ADR-046; the observation-convention comparison itself is closed);
- required minimum source coverage;
- final product, task, and matching acceptance thresholds;
- exact frontier baseline intervals and access assumptions;
- whether replicability and defensibility use ordinal labels only or calibrated numeric mappings;
- whether deployment components should be combined;
- task-role weights;
- product- versus family-balanced primary aggregation;
- primary operational and financial outcomes;
- causal identification strategy, if any.

These are not omissions. They are design choices that should be resolved using a blinded sentinel pilot rather than intuition or desired empirical results.

---

## 29. Summary

The thesis builds a new type of firm-level AI dataset from the bottom up. Instead of counting AI words or assigning one static exposure score to a company, it reconstructs what each firm sold, what concrete functions its products provided, what jobs customers used those functions to perform, how those jobs changed over time, and how the dated frontier alternative affected the economic position of each task.

The central empirical contribution is a longitudinal, evidence-grounded product–capability–task panel. The central conceptual contribution is the separation of:

- **frontier replicability**;
- **AI transformation depth**;
- **deployment scale**;
- **task-specific defensibility**.

This separation makes it possible to distinguish a firm that merely adds an AI wrapper to a directly substitutable task from a firm that integrates AI into a differentiated workflow, execution, governance, or orchestration layer. It also makes it possible to observe discontinuation, pivoting, new task creation, and portfolio change rather than treating the firm as a static pre-shock object.

The final methodology is intended to be transparent, date-bounded, source-grounded, auditable, and reproducible. The task-level data are created first; scores and outcome analyses are introduced only after extraction and measurement validity are demonstrated.
