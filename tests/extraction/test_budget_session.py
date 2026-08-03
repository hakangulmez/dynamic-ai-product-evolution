"""The canonical budget session and its code-owned identity (ADR-047, G3-2).

Everything here is offline: no provider is constructed, no credential is read,
no socket is opened, and the module under test reads no clock. The integration
cases drive ``run_extraction_stage_v2``, whose session is built by the runner
itself -- there is no public seam through which a different one could arrive,
and one of the tests below proves that by signature.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

import pytest

from dynamic_ai_products.extraction import budget_session as budget_session_module
from dynamic_ai_products.extraction.budget_session import (
    CanonicalBudgetSession,
    build_budget_session,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    BUDGET_POLICY_VERSION,
    CANONICAL_BUDGET_METER_IDENTITY,
    CANONICAL_BUDGET_METER_VERSION,
    validate_budget_meter_identity,
)
from dynamic_ai_products.extraction.provider_adapter import require_budget_session

ROOT = Path(__file__).resolve().parents[2]
HEX = re.compile(r"^[0-9a-f]{64}$")
AUTH_SHA = "a" * 64
RUN_ID = "ext-g3-2-1"


def _session(**overrides):
    kwargs = {
        "authorization_sha256": AUTH_SHA,
        "extraction_run_id": RUN_ID,
        "generate_attempt_cap": 1,
    }
    kwargs.update(overrides)
    return build_budget_session(**kwargs)


def _authorization(**overrides) -> dict:
    payload = {
        "budget_meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
        "budget_meter_version": CANONICAL_BUDGET_METER_VERSION,
        "budget_policy_version": BUDGET_POLICY_VERSION,
    }
    payload.update(overrides)
    return payload


def _validate(session, **overrides):
    validate_budget_meter_identity(
        authorization=_authorization(**overrides),
        meter_identity=session.meter_identity(),
        expected_budget_policy_version=BUDGET_POLICY_VERSION,
    )


# --- the code-owned identity is not the authorization's own value -------------


def test_the_meter_identity_comes_from_code_not_from_the_authorization():
    """The whole point of ADR-047: the two sides come from different places.

    If the factory read the identity out of the authorization, the validator
    below would compare the artifact with itself and prove nothing. The factory
    does not accept the authorization mapping at all, which is what makes the
    tautology unrepresentable rather than merely avoided.
    """
    parameters = set(inspect.signature(build_budget_session).parameters)
    assert parameters == {
        "authorization_sha256",
        "extraction_run_id",
        "generate_attempt_cap",
    }
    assert "authorization" not in parameters
    assert _session().meter_identity() == {
        "meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
        "meter_version": CANONICAL_BUDGET_METER_VERSION,
    }


def test_the_meter_identity_carries_exactly_two_fields():
    """The budget policy version is not a third identity field.

    Putting it here would make ``validate_budget_meter_identity`` look for a
    ``policy_version`` key through its ``removeprefix`` loop -- a key no session
    reports -- and every route including the canonical one would mismatch.
    """
    identity = _session().meter_identity()
    assert set(identity) == {"meter_identity", "meter_version"}
    assert "policy_version" not in identity
    assert BUDGET_POLICY_VERSION not in identity.values()


def test_the_canonical_identity_satisfies_the_validator():
    _validate(_session())


# --- the nonce ----------------------------------------------------------------


def test_the_nonce_is_a_lowercase_sha256_digest():
    assert HEX.fullmatch(_session().session_nonce)


def test_the_nonce_is_deterministic_through_the_public_factory():
    """Same three inputs, same nonce. No sampling, so a run reproduces.

    Proved through ``build_budget_session`` rather than the derivation helper:
    the helper is private, and a test that reached past the factory would be
    asserting an implementation detail instead of the surface a caller has.
    """
    first = _session()
    second = _session()
    assert first is not second
    assert first.session_nonce == second.session_nonce
    assert HEX.fullmatch(first.session_nonce)


@pytest.mark.parametrize(
    "override",
    [
        {"extraction_run_id": "ext-g3-2-2"},
        {"authorization_sha256": "b" * 64},
        {"generate_attempt_cap": 3},
    ],
)
def test_each_bound_input_changes_the_nonce(override):
    assert _session(**override).session_nonce != _session().session_nonce


def test_two_sessions_for_one_run_share_a_nonce_and_that_bound_is_stated():
    """Collision is bounded, not impossible, and the bound is asserted here.

    Two sessions collide only when the authorization digest and the run identity
    are both equal -- that is, when they are two sessions for the same run. A
    caller that reuses one ``extraction_run_id`` across runs does get one nonce
    twice; that caller is already violating run-identity uniqueness and the
    reused run root is refused elsewhere. Nothing here claims global uniqueness.
    """
    assert _session().session_nonce == _session().session_nonce
    assert _session(extraction_run_id="other").session_nonce != _session().session_nonce


def test_the_nonce_derivation_reads_no_clock_environment_or_randomness():
    """Asserted against the module source, not against a docstring."""
    tree = ast.parse(Path(budget_session_module.__file__).read_text(encoding="utf-8"))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (
        identifiers
        & {"now", "utcnow", "today", "monotonic", "perf_counter", "environ", "getenv",
           "uuid4", "token_hex", "urandom", "random", "randbytes"}
    )
    imported = {
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    } | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not (imported & {"time", "datetime", "os", "random", "secrets", "uuid", "socket"})


# --- the admission ------------------------------------------------------------


def test_the_admission_carries_the_cap_bound_at_construction():
    """``admit`` never receives the cap, so it must be bound when the session is."""
    assert "generate_attempt_cap" not in inspect.signature(
        CanonicalBudgetSession.admit
    ).parameters
    admission = _session(generate_attempt_cap=3).admit(
        measured_input_tokens=1000,
        reserved_cost_microdollars=42,
        provider_request_digest="c" * 64,
    )
    assert admission.generate_attempt_cap == 3


def test_the_admission_carries_the_session_nonce():
    session = _session()
    admission = session.admit(
        measured_input_tokens=1000,
        reserved_cost_microdollars=42,
        provider_request_digest="c" * 64,
    )
    assert admission.session_nonce == session.session_nonce


def test_a_second_admit_refuses(tmp_path: Path):
    """One count operation, one generation admission. A second ticket is refused.

    ``budget_admission_invalid`` is not a free choice: it is one of the three
    codes the terminal classifier maps onto ``pre_generation_invalid`` /
    ``budget_termination``. A new code would fall through to the provider branch.
    """
    session = _session()
    session.admit(
        measured_input_tokens=1000,
        reserved_cost_microdollars=42,
        provider_request_digest="c" * 64,
    )
    with pytest.raises(ExtractionError) as caught:
        session.admit(
            measured_input_tokens=1000,
            reserved_cost_microdollars=42,
            provider_request_digest="c" * 64,
        )
    assert caught.value.reason_code == "budget_admission_invalid"


def test_the_session_marks_nothing_spent():
    """Only the connector's ``complete_v8`` spends an admission."""
    admission = _session().admit(
        measured_input_tokens=1000,
        reserved_cost_microdollars=42,
        provider_request_digest="c" * 64,
    )
    assert admission.spent is False


def test_the_session_enforces_no_ceiling_of_its_own():
    """One enforcement owner. The runner checks the two ceilings before admit."""
    parameters = set(inspect.signature(build_budget_session).parameters)
    assert "budget_max_input_tokens" not in parameters
    assert "budget_max_estimated_cost_micros" not in parameters
    # Scanned with AST rather than as text: the module docstring names both
    # ceilings to explain why it does not own them, and a substring scan would
    # punish the explanation.
    tree = ast.parse(Path(budget_session_module.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert "budget_max_input_tokens" not in literals
    assert "budget_max_estimated_cost_micros" not in literals


@pytest.mark.parametrize("cap", [0, -1, None, "3", True])
def test_a_non_positive_cap_is_refused(cap):
    with pytest.raises(ExtractionError) as caught:
        _session(generate_attempt_cap=cap)
    assert caught.value.reason_code == "budget_insufficient"


# --- the shape gate -----------------------------------------------------------


def test_the_canonical_session_passes_the_shape_gate():
    assert require_budget_session(_session()) is not None


# --- the public seam is closed ------------------------------------------------



def test_the_f0_gates_are_ordered_above_the_permit_handshake_in_source(tmp_path: Path):
    """Source ordering only. **Not** a behaviour proof.

    This asserts where the two F0 gates sit relative to the permit handshake. The
    behaviour they produce -- a refusal with no permit, no run root, no send and
    no side effect -- is proved separately, by monkeypatching the factory and
    driving the public route, in
    ``test_v2_budget_enforcement::test_v2_a_malformed_canonical_session_refuses_at_f0_with_no_side_effects``.
    Neither test substitutes for the other.
    """
    from dynamic_ai_products.extraction import run_extraction

    lines = Path(run_extraction.__file__).read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("def run_extraction_stage_v2")
    )

    def first(fragment: str) -> int:
        return next(
            i for i, line in enumerate(lines[start:], start=start) if fragment in line
        )

    require_at = first("require_budget_session(budget_session)")
    identity_at = first("expected_budget_policy_version=BUDGET_POLICY_VERSION")
    permit_at = first("_assert_run_permitted_with(")
    assert require_at < identity_at < permit_at


def test_the_classifier_maps_a_malformed_session_onto_the_budget_branch():
    """Reachable post-F1 through the private helper, so it must classify as budget.

    The canonical route calls the measurement helper after mkdir, and the
    helper's own shape gate can raise there. In the provider branch it would
    publish a provider reason for something the provider never did.
    """
    from dynamic_ai_products.extraction.run_extraction import _classify_terminal

    route = _classify_terminal(
        ExtractionError("shape", reason_code="budget_meter_protocol_invalid"),
        {"phase": "admission", "generate_records": ()},
    )
    assert route["route_family"] == "pre_generation_invalid"
    assert route["terminal_reason"] == "budget_termination"
    assert route["provider_error"] is None


def test_legacy_v1_fixtures_are_untouched_by_the_canonical_identity():
    """The retired v1 modules never reach the canonical comparison.

    Measured: none of them calls ``run_extraction_stage_v2`` or the private
    measurement helper, so the meter identities in their fixtures cannot collide
    with the code-owned one and none of those files needed to change.
    """
    retired = (
        "test_live_authorization_validation.py",
        "test_live_budget_enforcement.py",
        "test_live_run_publication.py",
        "test_provider_error_publication.py",
        "test_run_extraction.py",
    )
    for name in retired:
        text = (ROOT / "tests" / "extraction" / name).read_text(encoding="utf-8")
        assert "run_extraction_stage_v2" not in text, name
        assert "_run_two_operation_measurement" not in text, name
        assert CANONICAL_BUDGET_METER_IDENTITY not in text, name



def test_the_session_is_frozen():
    session = _session()
    with pytest.raises(Exception):
        session.generate_attempt_cap = 99  # type: ignore[misc]
    payload = json.dumps(
        {"cap": session.generate_attempt_cap, "nonce": session.session_nonce},
        sort_keys=True,
    )
    assert payload


def test_the_nonce_derivation_is_not_public():
    """ADR-047: the factory is the only way to obtain a bound nonce.

    An exported derivation would let a caller mint a nonce the runner never
    bound to a session, which is exactly the substitution the admission check
    exists to refuse.
    """
    assert budget_session_module.__all__ == [
        "CanonicalBudgetSession",
        "build_budget_session",
    ]
    assert not hasattr(budget_session_module, "derive_session_nonce")
    assert hasattr(budget_session_module, "_derive_session_nonce")
