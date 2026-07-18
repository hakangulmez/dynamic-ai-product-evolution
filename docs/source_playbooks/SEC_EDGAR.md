# SEC EDGAR Playbook


## Scope

Discover and retrieve annual, quarterly, and current reports plus relevant exhibits.

## Procedure

1. Resolve CIK and filing calendar.
2. Query submissions and filing index.
3. Select forms allowed by the source policy.
4. Download filing document, filing index, and relevant exhibits.
5. Record accession number, filing date, period of report, form, URL, content type, and hash.
6. Parse sections without discarding the original filing.

## Relevance filters

Prioritize Item 1, MD&A, risk factors, product exhibits, earnings releases, and investor presentations. Do not treat every 8-K as product evidence.

## Compliance

Use a descriptive SEC user agent and rate limits. Cache retrievals.


## Universe construction

Stage 00 begins from the historical annual-filer frame, not the current ticker list. Preserve CIK, accession, form, filing date, fiscal year end, SIC, amendments, and dated issuer/listing evidence. Apply deterministic non-operating issuer filters before LLM screening. Baseline universe packets use dated SEC evidence only; official product and web sources enter later corpus stages.
