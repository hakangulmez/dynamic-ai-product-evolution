"""Stage 00H seeded, stratified negative-audit sampling.

The sample is drawn from first-pass negatives (screen LIKELY_INELIGIBLE and
deterministic exclusions) so that false-negative risk can be estimated. The
same seed and input always produce the same sample.
"""

from __future__ import annotations

import random
from typing import Any


def stratum_key(record: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Stable stratum for one negative record.

    Strata: SIC group (2-digit family), size bucket (placeholder until firm
    size data exists), archetype signal from the screen, exclusion reason,
    and confidence bucket.
    """
    sic = str(record.get("sic") or "")
    sic_group = sic[:2] if len(sic) >= 2 else "unknown"
    size_bucket = str(record.get("size_bucket") or "unknown")
    archetypes = record.get("candidate_customer_value_archetypes") or []
    archetype_signal = archetypes[0] if archetypes else "none"
    exclusion_reason = str(record.get("exclusion_reason") or "screen_likely_ineligible")
    confidence = str(record.get("confidence") or "unknown")
    return (sic_group, size_bucket, archetype_signal, exclusion_reason, confidence)


def draw_negative_audit_sample(
    negatives: list[dict[str, Any]],
    seed: int,
    per_stratum: int = 1,
) -> list[dict[str, Any]]:
    """Deterministic stratified sample: `per_stratum` records per stratum.

    Records are grouped by `stratum_key`, ordered stably by CIK inside each
    stratum, and sampled with a stratum-scoped generator derived from the
    seed so the draw is reproducible record-for-record.
    """
    if per_stratum < 1:
        raise ValueError("per_stratum must be >= 1")
    strata: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for record in negatives:
        strata.setdefault(stratum_key(record), []).append(record)

    sample: list[dict[str, Any]] = []
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda r: str(r.get("cik", "")))
        rng = random.Random((seed, key).__repr__())
        count = min(per_stratum, len(members))
        chosen = rng.sample(members, count)
        for record in sorted(chosen, key=lambda r: str(r.get("cik", ""))):
            sample.append({**record, "stratum": list(key), "audit_seed": seed})
    return sample
