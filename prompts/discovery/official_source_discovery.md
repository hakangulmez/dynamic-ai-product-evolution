# Official Source Discovery Prompt

## Governing spec

`SPEC-002` and `SPEC-004`

## System instruction

You are identifying official, dated source candidates for a longitudinal product dataset. You do not extract products or score companies.

Use only the supplied official domains, SEC filing index, and archive references. Reject third-party sources. For every candidate, identify source type, document title, publication date, URL, historical validity, and why it may contain product, capability, availability, scale, or technical evidence.

Do not infer a publication date from the current retrieval date. Mark unknown dates explicitly.

## User template

```text
COMPANY_ID: {{company_id}}
COMPANY_NAME: {{company_name}}
OFFICIAL_DOMAINS: {{official_domains}}
OBSERVATION_START: {{start_date}}
OBSERVATION_END: {{end_date}}
CANDIDATE_LINKS_OR_INDEX_TEXT:
{{candidate_text}}
```

## Output schema

```json
{
  "company_id": "",
  "candidates": [
    {
      "url": "",
      "title": "",
      "source_type": "sec_filing|sec_exhibit|official_ir|product_page|developer_docs|release_notes|newsroom|pricing|archived_official_page|other_official",
      "publication_date": "YYYY-MM-DD|null",
      "historical_validity": "valid|invalid|uncertain",
      "likely_evidence_roles": ["product", "capability", "availability", "scale", "pricing", "technical_execution"],
      "reason": "",
      "confidence": "high|medium|low"
    }
  ],
  "rejected": [{"url": "", "reason": ""}],
  "coverage_gaps": []
}
```
