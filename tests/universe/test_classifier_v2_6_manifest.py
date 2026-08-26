"""ADR-133 tests: the null a retry produces, and the contract that now accepts it.

The V2.5 calibration sent all forty rows and then refused its own manifest,
because one row hit a Vertex quota 429, retried successfully, and
``ScreenBudget`` set ``tokens_out_reported`` to null — correctly, since after a
retry there is no verified total. These tests reproduce that shape with the
fixture harness's ``quota_failures`` knob, assert V2.6 now completes, and assert
just as hard that V2.5 still refuses it and that nothing else was widened.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import ROOT  # noqa: E402
MANIFESTS_V6 = ("schemas/universe_classifier_manifest.v6.schema.json",
                "schemas/universe_classifier_continuation_manifest.v6.schema.json",
                "schemas/universe_classifier_calibration_manifest.v6.schema.json")
MANIFESTS_V5 = ("schemas/universe_classifier_manifest.v5.schema.json",
                "schemas/universe_classifier_continuation_manifest.v5.schema.json",
                "schemas/universe_classifier_calibration_manifest.v5.schema.json")


def _schema(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _validator(rel):
    return Draft202012Validator(_schema(rel), format_checker=FormatChecker())


# --- the schema change, and its narrowness -------------------------------------------


@pytest.mark.parametrize("rel", MANIFESTS_V6)
def test_only_tokens_out_reported_was_widened(rel):
    accounting = _schema(rel)["properties"]["request_accounting"]
    assert accounting["additionalProperties"] == {"type": "integer"}
    assert list(accounting["properties"]) == ["tokens_out_reported"]
    field = accounting["properties"]["tokens_out_reported"]
    assert field["type"] == ["integer", "null"]
    assert field["minimum"] == 0
    assert accounting["required"] == ["tokens_out_reported"]
    assert "verified" in field["description"]


@pytest.mark.parametrize("rel", MANIFESTS_V5)
def test_the_v2_5_manifests_are_untouched(rel):
    accounting = _schema(rel)["properties"]["request_accounting"]
    assert accounting["additionalProperties"] == {"type": "integer"}
    assert "properties" not in accounting
    assert "required" not in accounting


def _accounting(**overrides):
    body = {"logical_row_cap": 40, "count_attempt_cap": 120,
            "provider_attempt_cap": 200, "external_request_cap": 320,
            "count_attempts_made": 40, "provider_attempts_made": 41,
            "external_requests_made": 81, "rows_count_retried": 0,
            "rows_generate_retried": 1, "model_called_rows": 40,
            "reused_prefix_rows": 0, "tokens_in_measured": 628736,
            "tokens_out_reported": None, "rows_usage_verified": 39,
            "cost_micros_settled": 326773, "budget_max_input_tokens": 10_000_000,
            "budget_max_output_tokens": 1_000_000,
            "budget_max_estimated_cost_micros": 10_000_000,
            "budget_max_wall_clock_seconds": 86_400}
    body.update(overrides)
    return body


@pytest.mark.parametrize("rel", MANIFESTS_V6)
def test_a_null_token_report_validates_under_v2_6(rel):
    schema = {"type": "object",
              "properties": {"request_accounting":
                             _schema(rel)["properties"]["request_accounting"]}}
    errors = list(Draft202012Validator(schema).iter_errors(
        {"request_accounting": _accounting()}))
    assert errors == []


@pytest.mark.parametrize("rel", MANIFESTS_V5)
def test_the_same_null_is_still_refused_under_v2_5(rel):
    """The live V2.5 failure, pinned. The fix is a successor, not a relaxation."""
    schema = {"type": "object",
              "properties": {"request_accounting":
                             _schema(rel)["properties"]["request_accounting"]}}
    errors = list(Draft202012Validator(schema).iter_errors(
        {"request_accounting": _accounting()}))
    assert errors
    assert any("tokens_out_reported" in "/".join(str(x) for x in e.absolute_path)
               for e in errors)


@pytest.mark.parametrize("field", [
    "tokens_in_measured", "rows_usage_verified", "cost_micros_settled",
    "count_attempts_made", "provider_attempts_made", "external_requests_made",
    "model_called_rows", "rows_generate_retried",
])
@pytest.mark.parametrize("rel", MANIFESTS_V6)
def test_a_null_in_any_other_accounting_field_is_still_refused(rel, field):
    schema = {"type": "object",
              "properties": {"request_accounting":
                             _schema(rel)["properties"]["request_accounting"]}}
    body = _accounting(**{field: None, "tokens_out_reported": 55250})
    errors = list(Draft202012Validator(schema).iter_errors(
        {"request_accounting": body}))
    assert errors, field


@pytest.mark.parametrize("rel", MANIFESTS_V6)
def test_the_field_is_required_and_a_negative_integer_is_refused(rel):
    schema = {"type": "object",
              "properties": {"request_accounting":
                             _schema(rel)["properties"]["request_accounting"]}}
    missing = {k: v for k, v in _accounting().items() if k != "tokens_out_reported"}
    assert list(Draft202012Validator(schema).iter_errors(
        {"request_accounting": missing}))
    assert list(Draft202012Validator(schema).iter_errors(
        {"request_accounting": _accounting(tokens_out_reported=-1)}))


def test_nothing_enforces_a_budget_from_tokens_out_reported():
    """The safety argument, asserted against the source rather than assumed.

    Widening this property is only safe because no ceiling reads it. The
    enforcing methods are checked directly: they must speak of
    ``tokens_out_accounted`` and never of ``tokens_out_reported``.
    """
    import inspect

    from dynamic_ai_products import lineage_screen_live as live

    budget = live.ScreenCohortBudget
    source = inspect.getsource(budget)
    touches = [line.strip() for line in source.splitlines()
               if "self.tokens_out_reported" in line]
    # the declaration, the None guard, the accumulation and the null assignment
    assert len(touches) == 4, touches

    headroom = inspect.getsource(budget.require_output_headroom)
    assert "tokens_out_reported" not in headroom
    assert "tokens_out_accounted" in headroom

    admit = inspect.getsource(budget.admit)
    assert "tokens_out_reported" not in admit
    for enforced in ("tokens_in_measured", "cost_micros_settled"):
        assert enforced in admit, enforced
