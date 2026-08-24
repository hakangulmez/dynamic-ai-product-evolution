"""Derive a tier from classifier axes, deterministically (ADR-126).

The model returns economic axes and nothing else. This module turns those axes
into a tier, and it is the only thing in the pipeline permitted to do so. The
separation is the point: a prompt revision changes what the model observes, and
a tier change requires an explicit, versioned edit to the pinned rule config.
Without that split, rewording a prompt could silently move firms between tiers
and no artifact would record why.

**Successor, not a widening.** ``universe/rules.py`` and
``configs/universe_sample_rules.yaml`` continue to govern the historical
sentinel path and are byte-unchanged. This engine reads its own config,
``configs/universe_classifier_tier_rules_v2_1.yaml``, and consumes the ADR-126
axes contract rather than the mock classification model.

**Market orientation is not an input.** ``customer_market_orientation`` is
descriptive metadata about who buys. Letting it reach the tier function would
quietly turn a description of the customer into a claim about the firm's
economic type, so the engine never reads that field and a test permutes all four
values to prove the tier is invariant.

**Every derivation is replayable.** The result carries the rule config's version
and digest plus the ordered trace of every rule considered, so a stored record
can be re-derived and checked years later without this code being re-run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "TIER_RULES_RELATIVE_PATH",
    "TIERS",
    "ClassifierTierRules",
    "TierDerivation",
    "derive_tier",
    "load_tier_rules",
]

TIER_RULES_RELATIVE_PATH = "configs/universe_classifier_tier_rules_v2_1.yaml"

#: The closed set of tiers this engine may produce.
TIERS: tuple[str, ...] = ("TIER_A", "TIER_B", "TIER_C", "EXCLUDED", "UNCERTAIN")

#: Axis fields a rule may condition on. ``customer_market_orientation`` is
#: deliberately absent: a rule naming it is refused when the config loads,
#: rather than silently ignored at evaluation time.
CONDITIONABLE: frozenset[str] = frozenset({
    "software_centrality",
    "firm_structure",
    "commercial_materiality",
    "customer_facing_functional_product",
    "economically_eligible",
    "data_eligible",
})

FORBIDDEN_CONDITION = "customer_market_orientation"


class TierRulesError(ValueError):
    """The rule config is unusable. Never repaired, never defaulted."""


@dataclass(frozen=True)
class ClassifierTierRules:
    version: str
    sha256: str
    rules: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class TierDerivation:
    tier: str
    trace: dict[str, Any]


def load_tier_rules(repo_root: str | Path) -> ClassifierTierRules:
    """Load and validate the pinned rule config."""
    path = Path(repo_root) / TIER_RULES_RELATIVE_PATH
    if not path.is_file():
        raise TierRulesError(f"Tier rule config not found: {path}")
    raw = path.read_bytes()
    config = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(config, dict):
        raise TierRulesError("The tier rule config is not a mapping.")
    version = config.get("tier_rules_version")
    if not isinstance(version, str) or not version:
        raise TierRulesError("The tier rule config declares no version.")
    rules = config.get("rules")
    if not isinstance(rules, list) or not rules:
        raise TierRulesError("The tier rule config declares no rules.")
    seen: set[str] = set()
    for position, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise TierRulesError(f"Rule {position} is not a mapping.")
        rule_id = rule.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            raise TierRulesError(f"Rule {position} declares no rule_id.")
        if rule_id in seen:
            raise TierRulesError(f"Rule id {rule_id!r} appears twice.")
        seen.add(rule_id)
        if rule.get("tier") not in TIERS:
            raise TierRulesError(
                f"Rule {rule_id!r} names tier {rule.get('tier')!r}, which is "
                f"outside the closed set {TIERS}."
            )
        for key in ("when", "when_any"):
            conditions = rule.get(key, {})
            if conditions is None:
                continue
            if not isinstance(conditions, dict):
                raise TierRulesError(f"Rule {rule_id!r} has a non-mapping {key}.")
            for field in conditions:
                if field == FORBIDDEN_CONDITION:
                    raise TierRulesError(
                        f"Rule {rule_id!r} conditions on {FORBIDDEN_CONDITION!r}. "
                        "Market orientation is descriptive metadata and is not an "
                        "input to the tier function."
                    )
                if field not in CONDITIONABLE:
                    raise TierRulesError(
                        f"Rule {rule_id!r} conditions on unknown axis {field!r}."
                    )
    last = rules[-1]
    if last.get("when") or last.get("when_any"):
        raise TierRulesError(
            "The final rule must be unconditional, so every axis combination "
            "reaches a decision rather than falling through undecided."
        )
    return ClassifierTierRules(version=version,
                              sha256=hashlib.sha256(raw).hexdigest(),
                              rules=tuple(rules))


def _matches(axes: dict[str, Any], conditions: dict[str, Any], *, any_of: bool) -> bool:
    if not conditions:
        return not any_of
    results = []
    for field, permitted in conditions.items():
        value = axes.get(field)
        results.append(value in permitted)
    return any(results) if any_of else all(results)


def derive_tier(axes: dict[str, Any], rules: ClassifierTierRules) -> TierDerivation:
    """Derive one tier from validated axes, recording every rule considered.

    The first rule whose conditions hold decides. The trace records the rules
    that did not fire as well as the one that did, so the derivation can be
    audited without re-running this function.
    """
    if not isinstance(axes, dict):
        raise TierRulesError("Axes must be a mapping.")
    entries: list[dict[str, Any]] = []
    for rule in rules.rules:
        when = rule.get("when") or {}
        when_any = rule.get("when_any") or {}
        fired = True
        if when:
            fired = fired and _matches(axes, when, any_of=False)
        if when_any:
            fired = fired and _matches(axes, when_any, any_of=True)
        if not when and not when_any:
            fired = True
        if fired:
            entries.append({"rule_id": rule["rule_id"], "result": "fired",
                            "detail": f"tier {rule['tier']}"})
            return TierDerivation(
                tier=rule["tier"],
                trace={"tier_rules_version": rules.version,
                       "tier_rules_sha256": rules.sha256,
                       "entries": entries})
        entries.append({"rule_id": rule["rule_id"], "result": "not_matched",
                        "detail": None})
    # load_tier_rules guarantees an unconditional final rule, so this is
    # unreachable; raising rather than defaulting keeps it that way.
    raise TierRulesError("No rule matched; the rule config is not exhaustive.")
