# Longitudinal Panel and Matching Plan

## Status

This is a proposal for the post-`UNIVERSE_v1` phase. It records design
discipline, not a final estimator, source sample, or matching model.

## Identity layers

1. **Raw issuer/source layer:** `CIK × accession × carrier row`. Shared SEC
   accessions can legitimately serve distinct registrants and are never merged
   merely because source bytes match.
2. **Dated observation layer:** issuer context × observation date × product ×
   capability × customer-facing task. Each observation points to evidence that
   existed at its own cutoff.
3. **Economic-firm layer:** a later, evidence-backed parent/successor or
   controlled-subsidiary relation used only when an analytical outcome requires
   it. It never overwrites the source layer.

## Time and IDs

Every observation retains source publication/filing availability, fiscal-year
assignment when applicable, collection/snapshot date, and admissible cutoff.
Stable IDs identify observations; aliases preserve renamed products or tasks;
links record their own evidence, confidence, date range, and decision rule.

## Matching architecture

Candidate generation may use names, product hierarchy, lexical overlap,
customer need, and cited evidence. It is recall-oriented and not a match
decision. A final decision must classify a candidate link as accepted,
rejected, or unresolved and preserve the basis.

The system must distinguish: same task, renamed, expanded, contracted,
AI-assisted, workflow-integrated, agentified, split, merged, new, replaced,
and discontinued. A later name cannot rewrite a prior observation.

## No-forced-match rule

Absence, uncertain identity, incomplete evidence, or an ambiguous relation
remain explicit states. The panel need not be balanced. A balanced panel made by
guessing creates stronger bias than a transparent unbalanced one.

## Validation plan

- hold out rename, split/merge, discontinuation, and parent/subsidiary cases;
- measure false disappearance and false consolidation separately;
- audit links near high-weight products and tasks;
- retain candidate-generation output so final-match decisions are reproducible;
- report raw-issuer and economic-firm results separately when consolidation is
  needed for an outcome panel.
