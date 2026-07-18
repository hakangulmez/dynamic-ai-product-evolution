# Corpus Architecture

## Firm-year source packet

Each firm-year packet contains:

- annual filing Item 1 and relevant sections;
- quarterly or current-report product events up to cutoff;
- official investor materials;
- dated product pages;
- dated documentation or release notes;
- exclusion manifest.

## Passage indexing

Normalized documents are segmented into stable passages. Each passage records:

- heading path;
- character offsets;
- source date;
- source type;
- text hash;
- URL and snapshot provenance.

Passage IDs must remain stable when unrelated parts of a document change.

## Corpus completeness flags

For each firm-year and source category:

- `available_and_retrieved`
- `available_but_failed`
- `not_found`
- `not_applicable`
- `temporally_invalid`
- `duplicate`
- `robots_or_access_blocked`

Unknown source coverage must remain visible in analysis.
