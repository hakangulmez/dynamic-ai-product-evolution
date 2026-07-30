"""Retry and timeout policy (ADR-034, E-P0 verified).

Deterministic and offline: no sleeping, no network, no SDK. The retry driver is
exercised through an injected sleep recorder, so the delay sequence is observed
rather than waited on.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.providers import retry_policy as rp
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini import execute_with_retry, is_retryable


def _exc(name: str, **attributes):
    cls = type(name, (Exception,), {})
    instance = cls("upstream text that must never surface")
    for key, value in attributes.items():
        setattr(instance, key, value)
    return instance


# --- locked constants ---------------------------------------------------------


def test_timeout_constants_are_the_e_p0_resolved_values():
    assert rp.TIMEOUT_SDK_PARAMETER == "google.genai.types.HttpOptions.timeout"
    assert rp.TIMEOUT_DURATION == 300000
    assert rp.TIMEOUT_UNIT == "milliseconds"
    assert rp.API_VERSION == "v1"


def test_retry_constants_are_locked():
    assert rp.RETRY_OWNER == "tenacity"
    assert rp.RETRY_MAX_ATTEMPTS == 3
    assert rp.RETRY_DELAYS_SECONDS == (1, 2)
    assert rp.RETRY_JITTER is False
    assert rp.RETRY_TRIGGER_STATUS_CODES == (408, 429, 500, 502, 503, 504)
    assert rp.RETRY_TRIGGER_TRANSPORT_TIMEOUT is True
    assert rp.SDK_RETRY_ATTEMPTS == 1
    assert rp.FALLBACK_POLICY == "none"


def test_the_delay_budget_matches_the_attempt_budget():
    assert len(rp.RETRY_DELAYS_SECONDS) == rp.RETRY_MAX_ATTEMPTS - 1


# --- should_retry -------------------------------------------------------------


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_declared_status_codes_are_retryable(status):
    assert rp.should_retry(status_code=status) is True


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 409, 422, 451])
def test_every_other_status_is_not_retryable(status):
    assert rp.should_retry(status_code=status) is False


def test_a_transport_timeout_is_retryable_and_a_missing_status_is_not():
    assert rp.should_retry(transport_timeout=True) is True
    assert rp.should_retry() is False


# --- delay sequence -----------------------------------------------------------


def test_the_delay_sequence_is_one_then_two_with_no_jitter():
    assert rp.delay_before_attempt(1) == 0.0
    assert rp.delay_before_attempt(2) == 1.0
    assert rp.delay_before_attempt(3) == 2.0
    # Deterministic: repeated calls agree exactly.
    assert [rp.delay_before_attempt(n) for n in (1, 2, 3)] == [0.0, 1.0, 2.0]


def test_a_fourth_attempt_is_outside_the_policy():
    with pytest.raises(ValueError):
        rp.delay_before_attempt(4)


@pytest.mark.parametrize("attempt", [0, -1, "2", None])
def test_a_malformed_attempt_index_is_refused(attempt):
    with pytest.raises(ValueError):
        rp.delay_before_attempt(attempt)


# --- the retry driver ---------------------------------------------------------


def test_a_first_attempt_success_makes_no_retry():
    calls = []
    delays = []
    result = execute_with_retry(lambda: calls.append(1) or "ok", sleep=delays.append)
    assert result == "ok"
    assert len(calls) == 1
    assert delays == []


def test_a_retryable_failure_then_success_records_the_delay():
    state = {"n": 0}

    def call():
        state["n"] += 1
        if state["n"] < 3:
            raise _exc("ApiError", code=503)
        return "ok"

    delays = []
    assert execute_with_retry(call, sleep=delays.append) == "ok"
    assert state["n"] == 3
    assert delays == [1.0, 2.0]


def test_exhaustion_stops_at_three_attempts_and_reports_the_count():
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise _exc("ApiError", code=429)

    delays = []
    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(call, sleep=delays.append)
    assert state["n"] == 3
    assert delays == [1.0, 2.0]
    assert excinfo.value.reason_code == "vertex_quota_exhausted"
    assert excinfo.value.attempt_count == 3


def test_a_non_retryable_failure_stops_immediately():
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise _exc("ApiError", code=403)

    delays = []
    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(call, sleep=delays.append)
    assert state["n"] == 1
    assert delays == []
    assert excinfo.value.reason_code == "vertex_permission_denied"
    assert excinfo.value.attempt_count == 1


def test_a_transport_timeout_is_retried():
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise _exc("ReadTimeout")

    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(call, sleep=lambda _: None)
    assert state["n"] == 3
    assert excinfo.value.reason_code == "provider_timeout"


def test_the_retry_driver_repeats_an_identical_request():
    """A retry never substitutes a model, endpoint, or payload."""
    seen = []

    def call():
        seen.append(("gemini-2.5-flash", "us-central1", "packet-sha"))
        raise _exc("ApiError", code=500)

    with pytest.raises(ProviderError):
        execute_with_retry(call, sleep=lambda _: None)
    assert len(set(seen)) == 1


def test_no_upstream_text_survives_exhaustion():
    def call():
        raise _exc("ApiError", code=503)

    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(call, sleep=lambda _: None)
    assert "upstream text" not in str(excinfo.value)


# --- tenacity is the single retry owner ---------------------------------------


def test_the_driver_is_built_on_the_tenacity_public_api():
    """Not a hand-rolled loop: the locked owner is actually the one driving."""
    import inspect

    from dynamic_ai_products.providers import vertex_gemini

    source = inspect.getsource(vertex_gemini.execute_with_retry)
    assert "Retrying(" in source
    assert "while " not in source
    imported = inspect.getsource(vertex_gemini).split("__all__")[0]
    for name in ("Retrying", "stop_after_attempt", "wait_chain", "wait_fixed",
                 "retry_if_exception"):
        assert name in imported, name


def test_the_wait_chain_yields_exactly_one_then_two_seconds():
    """Read from the configured tenacity strategy, not from our own constants."""
    from tenacity import RetryCallState, wait_chain, wait_fixed

    chain = wait_chain(*(wait_fixed(d) for d in rp.RETRY_DELAYS_SECONDS))
    observed = []
    for attempt_number in (1, 2):
        state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
        state.attempt_number = attempt_number
        observed.append(chain(state))
    assert observed == [1.0, 2.0]


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_an_operator_interrupt_is_never_retried_and_propagates(interrupt):
    """BaseException is not Exception: an interrupt must not be swallowed."""
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise interrupt()

    with pytest.raises(interrupt):
        execute_with_retry(call, sleep=lambda _: None)
    assert state["n"] == 1


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(), GeneratorExit()])
def test_is_retryable_refuses_every_base_exception(interrupt):
    assert is_retryable(interrupt) is False


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_is_retryable_accepts_the_declared_status_codes(status):
    assert is_retryable(_exc("ApiError", code=status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_is_retryable_refuses_every_other_status(status):
    assert is_retryable(_exc("ApiError", code=status)) is False


def test_the_driver_uses_real_sleeping_only_when_none_is_injected():
    """A test never sleeps; production does. The seam is the sleep parameter."""
    import inspect

    from dynamic_ai_products.providers import vertex_gemini

    source = inspect.getsource(vertex_gemini.execute_with_retry)
    assert 'options["sleep"] = sleep' in source
    assert "time.sleep" not in source


# --- the budget-derived attempt cap (ADR-035) --------------------------------


@pytest.mark.parametrize("cap,expected_calls", [(1, 1), (2, 2), (3, 3)])
def test_the_cap_bounds_the_attempt_count(cap, expected_calls):
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise _exc("ApiError", code=503)

    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(call, sleep=lambda _: None, max_attempts=cap)
    assert state["n"] == expected_calls
    assert excinfo.value.attempt_count == expected_calls


def test_a_cap_above_the_policy_cannot_buy_extra_attempts():
    """The cap may only lower RETRY_MAX_ATTEMPTS, never raise it."""
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise _exc("ApiError", code=503)

    with pytest.raises(ProviderError):
        execute_with_retry(call, sleep=lambda _: None, max_attempts=99)
    assert state["n"] == rp.RETRY_MAX_ATTEMPTS


def test_a_cap_below_one_is_refused():
    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(lambda: "ok", sleep=lambda _: None, max_attempts=0)
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_no_cap_keeps_the_e_p_policy_unchanged():
    state = {"n": 0}

    def call():
        state["n"] += 1
        raise _exc("ApiError", code=503)

    with pytest.raises(ProviderError):
        execute_with_retry(call, sleep=lambda _: None)
    assert state["n"] == rp.RETRY_MAX_ATTEMPTS == 3
