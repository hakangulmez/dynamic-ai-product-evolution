# Measurement, Outcomes, and Econometrics Plan

## Proposal status

Nothing in this file fixes a final score weight, frontier release set, causal
estimand, shock date, outcome, sample, or estimator. These decisions occur only
after the source/extraction/matching system is frozen without looking at outcome
results to tune it.

## Candidate task-level constructs

| Construct | Candidate question |
|---|---|
| Frontier task replicability | Could the frontier general-purpose system available at the observation date meet the customer need without the focal product at comparable practical quality? |
| AI transformation depth | How deeply has AI changed how the product performs the task? |
| Deployment scale | How broadly and operationally is the relevant capability deployed? |
| Task-specific defensibility | What assets, workflow embedding, data, trust, regulation, or switching friction limit substitution? |
| Economic importance | How central is the task to the product’s customer value and commercial role? |

Replicability is dynamic by frontier release and observation date. AI
transformation is also dynamic: it is a dated product-task response, not a
pre-period firm trait. A vertical product may face high raw model replicability
yet retain defensibility through data, workflow, integration, trust, or a
specific customer job.

## Evidence and aggregation discipline

Each component score needs dated, task-specific evidence and an explicit
unknown/not-observed state. Product and firm aggregates remain decomposable to
task observations and declared role/product weights. No financial result may be
used to select, repair, or weight upstream evidence.

## Outcome panel

Financial and operating data enter only after upstream measurement freezes.
Candidate outcomes include revenue growth, gross margin, operating margin, R&D
intensity, sales efficiency, retention proxies, market valuation/event outcomes,
and employment/productivity proxies where valid timing and coverage exist.

The outcome panel preserves source date, fiscal period, availability date,
corporate-lineage rule, and missingness. It does not backfill information that
was unavailable at the product-task observation cutoff.

## Empirical hierarchy

1. Descriptive trajectories and decompositions are mandatory.
2. Association models may relate predeclared task/firm metrics to later
   outcomes, with transparent controls and sensitivity analysis.
3. A pre-shock exposure × post-shock design is a candidate only if pre-period
   exposure can be measured without post-treatment contamination and parallel
   trends are credible.
4. Staggered verified AI-native deployment and release/event-study designs are
   alternatives, not automatic causal claims.

Before reading outcome results, lock the observation window, release set,
primary outcomes, sample/lineage treatment, missingness rules, aggregations,
main specification, and robustness package. Interpret any estimate as causal
only to the degree its identification assumptions survive diagnostics.
