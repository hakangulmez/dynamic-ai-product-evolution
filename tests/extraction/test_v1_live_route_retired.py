"""The v1 provider route is closed, and the routes above it are unchanged.

ADR-045 (G2b). ``run_extraction_stage`` walked the three released governance
rings and then sent. It never bound a prompt qualification -- ADR-044 placed that
on the v2 route -- and it never measured the input before generating. A route
that validates a chain and still cannot say which prompt was qualified is not a
lesser route; it is a bypass that looks legitimate from the outside, and a
runbook cannot close it because a runbook is a human document.

The refusal sits after the non-run branch returns and before ``require_provider``,
the governance walk, the permit handshake, the meter, ``_require_absent_run_root``
and ``mkdir``. Four consequences are asserted here:

* the two refusal routes above it are untouched -- caller-supplied contract pin
  and every packet-build refusal still produce zero artifacts;
* the non-run route keeps its contract: two artifacts,
  ``zero_admissible_passages``, and no provider call;
* the retired route creates nothing and calls nothing;
* an existing run root is left exactly as it was found, and now reports
  ``v1_live_route_retired`` rather than ``run_root_exists`` -- a deliberate
  ordering consequence, because ``_require_absent_run_root`` sits far below the
  provider seam on that path.

Nothing here touches a network, an SDK, or ADC.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction import run_extraction as run_extraction_module
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.run_extraction import (
    NON_RUN_REFERENCE,
    PACKET_REFERENCE,
    run_extraction_stage,
    run_extraction_stage_v2,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
CODE_COMMIT = "be627003f3246b371c2b3ac13e813ef0bb112582"
RUN_CREATED_AT = "2026-07-29T00:00:00Z"
RETIRED = "v1_live_route_retired"


class _ExplodingProvider:
    """Every method is a tripwire. Reaching any of them is the failure."""

    def assert_run_permitted(self, **_kwargs):
        raise AssertionError("the retired route must not touch the provider")

    def revoke_run_permission(self):
        raise AssertionError("the retired route must not touch the provider")

    def client_contract(self):
        raise AssertionError("the retired route must not touch the provider")

    def complete(self, request):
        raise AssertionError("the retired route must not touch the provider")

    def count_tokens(self, request, *, sink):
        raise AssertionError("the retired route must not touch the provider")

    def complete_v8(self, request, *, admission, sink):
        raise AssertionError("the retired route must not touch the provider")


class _ExplodingMeter:
    def meter_identity(self):
        raise AssertionError("the retired route must not consult the meter")

    def assert_within_budget(self, **_kwargs):
        raise AssertionError("the retired route must not consult the meter")

    def admit(self, **_kwargs):
        raise AssertionError("the retired route must not consult the meter")


def _passage(passage_id="p-1", text="the product ships an assistant", source_id="sec-1"):
    return {
        "passage_id": passage_id,
        "source_id": source_id,
        "text": text,
        "start_offset": 0,
        "end_offset": len(text),
    }


def _write_identity(root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "company_id": COMPANY,
            "cik": COMPANY[3:].lstrip("0"),
            "legal_name": "HUBSPOT INC",
            "observation_cutoff_date": CUTOFF,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    (root / "pilot_universe_packet.json").write_bytes(payload)
    return {"reference": "pilot_universe_packet.json", "sha256": hashlib.sha256(payload).hexdigest()}


def _run(tmp_path: Path, **overrides):
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage()],
        "document_publication_dates": {"sec-1": "2024-02-14"},
        "coverage_artifact": {"reference": "coverage/c.json", "sha256": "d" * 64},
        "source_snapshot_manifest": {"reference": "snapshots/m.json", "sha256": "e" * 64},
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
        "extraction_run_id": "ext-0001",
        "prediction_run_id": "pred-0001",
        "schema_root": str(SCHEMAS),
        "provider": _ExplodingProvider(),
        "budget_meter": _ExplodingMeter(),
        "company_identity_root": tmp_path / "identity",
        "company_identity_pin": _write_identity(tmp_path / "identity"),
    }
    kwargs.update(overrides)
    return run_extraction_stage(**kwargs)


def _files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _digests(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


# --- the retired route ----------------------------------------------------------


def test_a_non_empty_v1_call_is_refused_as_retired(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == RETIRED
    assert "run_extraction_stage_v2" in str(excinfo.value)


def test_the_retired_route_creates_nothing_and_calls_nothing(tmp_path: Path, monkeypatch):
    counter = [0]
    original = Path.mkdir
    prefix = str(tmp_path / "run")

    def counting(self, *args, **kwargs):
        if str(self) == prefix or str(self).startswith(prefix + "/"):
            counter[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == RETIRED
    assert counter[0] == 0
    assert not (tmp_path / "run").exists()


def test_the_retired_route_needs_no_governance_root_to_refuse(tmp_path: Path):
    """The refusal precedes the governance walk, so an absent chain is irrelevant."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, governance_artifact_root=None, live_call_authorization_pin=None)
    assert excinfo.value.reason_code == RETIRED


@pytest.mark.parametrize("provider", [None, object(), _ExplodingProvider()])
def test_the_retired_route_refuses_whatever_provider_is_injected(tmp_path: Path, provider):
    """v1 used to refuse a missing or non-conforming provider with its own codes.

    Those three cases now collapse into one: the route is closed, so what was
    injected no longer matters. This is the retirement-refusal successor of
    ``provider_required`` and ``provider_protocol_invalid``.
    """
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider)
    assert excinfo.value.reason_code == RETIRED


@pytest.mark.parametrize("meter", [None, object(), _ExplodingMeter()])
def test_the_retired_route_refuses_whatever_meter_is_injected(tmp_path: Path, meter):
    """The successor of ``budget_meter_unavailable`` on this route."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, budget_meter=meter)
    assert excinfo.value.reason_code == RETIRED


# --- R6: an existing run root is reported differently, and left alone -----------


def test_an_existing_run_root_now_reports_retirement_and_is_left_unchanged(tmp_path: Path):
    """The deliberate ordering consequence, recorded in ADR-045.

    ``_require_absent_run_root`` sits below the provider seam on this path, so it
    is no longer reached. What matters more than the code is that the refusal
    neither writes nor removes anything: the caller's directory is exactly as it
    was found.
    """
    root = tmp_path / "run"
    (root / "inputs").mkdir(parents=True)
    (root / "inputs" / "prior.json").write_bytes(b'{"kept": true}\n')
    before = _digests(root)

    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == RETIRED
    assert excinfo.value.reason_code != "run_root_exists"
    assert _digests(root) == before


def test_a_symlinked_run_root_is_also_left_untouched(tmp_path: Path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "prior.json").write_bytes(b'{"kept": true}\n')
    (tmp_path / "run").symlink_to(target)
    before = _digests(target)

    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == RETIRED
    assert (tmp_path / "run").is_symlink()
    assert _digests(target) == before


# --- the routes above the refusal are unchanged ---------------------------------


def test_the_caller_supplied_contract_pin_refusal_still_precedes_retirement(tmp_path: Path):
    """[A] sits above the route branch, so it still owns this refusal."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider_client_contract={"reference": "x", "sha256": "f" * 64})
    assert excinfo.value.reason_code == "contract_pin_forbidden"
    assert not (tmp_path / "run").exists()


def test_a_packet_build_refusal_still_precedes_retirement(tmp_path: Path):
    """[B] runs before the branch, so packet refusals keep their own codes."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, stage="not_a_stage")
    assert excinfo.value.reason_code == "packet_stage_invalid"
    assert excinfo.value.reason_code != RETIRED
    assert not (tmp_path / "run").exists()


def test_an_identity_free_packet_is_retired_rather_than_refused_for_its_pin(tmp_path: Path):
    """Supplying no company-identity pin is not a packet-build failure.

    ``build_extraction_input_packet`` still returns a valid ``@0.1.0`` packet in
    that case -- the pin is what upgrades it to ``@0.2.0``. v1 refused it later,
    inside the authorized stage, with ``company_identity_pin_required``; that
    check now sits below the retirement and is unreachable, so the honest v1
    outcome is the retirement itself.

    The invariant is not lost: the v2 route still owns
    ``company_identity_pin_required``, and it is covered there.
    """
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, company_identity_root=None, company_identity_pin=None)
    assert excinfo.value.reason_code == RETIRED
    assert not (tmp_path / "run").exists()


# --- the non-run route keeps its contract ---------------------------------------


def _non_run(tmp_path: Path, **overrides):
    """Every passage is filtered out, so the packet admits none."""
    kwargs = {
        "passages": [
            _passage("p-1", "late", source_id="sec-late"),
            _passage("p-2", "  "),
        ],
        "document_publication_dates": {"sec-late": "2025-06-01", "sec-1": "2024-02-14"},
    }
    kwargs.update(overrides)
    return _run(tmp_path, **kwargs)


def test_the_non_run_route_publishes_exactly_two_artifacts(tmp_path: Path):
    outcome = _non_run(tmp_path)
    assert outcome.verdict == "no_run"
    assert _files(outcome.run_root) == {PACKET_REFERENCE, NON_RUN_REFERENCE}
    assert NON_RUN_REFERENCE == "manifests/extraction_non_run_record.json"


def test_the_non_run_record_still_declares_zero_admissible_passages(tmp_path: Path):
    outcome = _non_run(tmp_path)
    record = json.loads((outcome.run_root / NON_RUN_REFERENCE).read_text(encoding="utf-8"))
    assert record["reason_code"] == "zero_admissible_passages"


def test_the_non_run_route_never_asks_the_provider_anything(tmp_path: Path):
    """The tripwire provider would raise AssertionError if it were touched."""
    outcome = _non_run(tmp_path, provider=_ExplodingProvider())
    assert outcome.verdict == "no_run"
    assert len(_files(outcome.run_root)) == 2


def test_the_non_run_route_needs_no_provider_at_all(tmp_path: Path):
    outcome = _non_run(tmp_path, provider=None, budget_meter=None)
    assert outcome.verdict == "no_run"


def test_the_non_run_route_creates_its_run_root(tmp_path: Path):
    """absent -> created, and only on this route."""
    assert not (tmp_path / "run").exists()
    outcome = _non_run(tmp_path)
    assert outcome.run_root.is_dir()


def test_the_non_run_route_still_refuses_an_existing_run_root(tmp_path: Path):
    """Its own guard is above the retirement, so it keeps ``run_root_exists``."""
    (tmp_path / "run").mkdir()
    with pytest.raises(ExtractionError) as excinfo:
        _non_run(tmp_path)
    assert excinfo.value.reason_code == "run_root_exists"


# --- the public surface ---------------------------------------------------------


def test_the_two_operation_measurement_helper_is_not_public():
    """ADR-045: it hydrates nothing and validates no chain, so it is not a route.

    The underscore is a boundary, not an enforcement -- an in-process caller can
    still reach it by name, and that is stated rather than implied. What actually
    refuses a send without a permit is the connector.
    """
    assert "run_two_operation_measurement" not in run_extraction_module.__all__
    assert "_run_two_operation_measurement" not in run_extraction_module.__all__
    assert hasattr(run_extraction_module, "_run_two_operation_measurement")
    assert not hasattr(run_extraction_module, "run_two_operation_measurement")


def test_both_entry_points_remain_exported():
    """v1 is not deleted, only closed: its non-run route is still a public route."""
    assert "run_extraction_stage" in run_extraction_module.__all__
    assert "run_extraction_stage_v2" in run_extraction_module.__all__


def test_only_the_v2_entry_point_can_reach_a_provider(tmp_path: Path):
    """The single-canonical-route invariant, asserted by outcome rather than prose."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == RETIRED
    # The v2 entry point still accepts a provider argument; v1's is now inert.
    import inspect

    assert "provider" in inspect.signature(run_extraction_stage_v2).parameters
    assert "provider" in inspect.signature(run_extraction_stage).parameters


def test_neither_public_route_accepts_an_injected_budget_session():
    """ADR-047 closed the v2 seam; v1 never had one and still does not.

    The two routes carry different budget parameters and neither is a session:
    v1 keeps its retired ``budget_meter``, v2 builds its own canonical session at
    F0. A public ``budget_session`` on either would be a way to hand the run a
    metering identity it did not derive.
    """
    import inspect

    v1 = inspect.signature(run_extraction_stage).parameters
    v2 = inspect.signature(run_extraction_stage_v2).parameters

    assert "budget_session" not in v1
    assert "budget_session" not in v2
    # v1's meter argument survives, inert, because the block below the retirement
    # refusal is left in place by ADR-045 rather than deleted.
    assert "budget_meter" in v1
    assert "budget_meter" not in v2

    with pytest.raises(TypeError):
        run_extraction_stage_v2(budget_session=object())
    with pytest.raises(TypeError):
        run_extraction_stage(budget_session=object())


def test_the_v1_route_refuses_before_its_inert_meter_argument_matters(tmp_path: Path):
    """Whatever is passed as ``budget_meter``, the route is closed first."""
    for meter in (None, object(), _ExplodingMeter()):
        with pytest.raises(ExtractionError) as excinfo:
            _run(tmp_path, budget_meter=meter)
        assert excinfo.value.reason_code == RETIRED
        assert not (tmp_path / "run").exists()
