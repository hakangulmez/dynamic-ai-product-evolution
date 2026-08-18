"""PCT_Dev30_v0 preparation package.

Dev30-corpus-specific tooling only. Nothing here reads, constructs, or
accepts a Stage 00C ``source_id`` (``sec-primary:<cik>:<accession>:
<selected_document>``); Dev30 rows carry ``legacy_source_id``
(``legacy-item1:dev30-v0:<source_text_hash>``) instead, and the two
namespaces are never interchangeable. This package performs no network
access, calls no model provider, and does not alter the current universe.
"""

DEV30_COHORT_VERSION = "PCT_Dev30_v0"
