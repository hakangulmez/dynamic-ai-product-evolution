"""The v0.4 acquisition policy (ADR-040, E-C-D3).

Offline throughout: the transport is the shared ordinal-only double reached only
through the module-private ``_send_once`` seam, spacing goes through ``_sleep``,
and every write lands under ``tmp_path``. Nothing here retrieves a real URL and
nothing touches ``data/``.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from documentation_v4_transport import (  # noqa: E402
    BODY,
    ExpectedCall,
    OrdinalTransport,
    hop,
    terminal,
)

from dynamic_ai_products.collection import documentation_policy_v4 as dp4  # noqa: E402
from dynamic_ai_products.collection import documentation_receipt_v4 as v4  # noqa: E402
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.v4.schema.json").read_bytes()
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.decode("utf-8")))
COMMIT = "c53233bba5e43702e8de93a623592351cc361d73"
STAMP = "2026-07-31T09:00:00Z"

E1, E2, E3 = dp4.FROZEN_EVIDENCE_ENTRIES_V4


def full_success_script() -> list[ExpectedCall]:
    """The complete authorized call sequence: 2 + 2 + 1 = five sends."""
    return [
        hop(1, E1["requested_url"], E1["final_url"]),
        terminal(2, E1["final_url"]),
        hop(3, E2["requested_url"], E2["final_url"]),
        terminal(4, E2["final_url"]),
        terminal(5, E3["requested_url"]),
    ]


def run(monkeypatch, tmp_path, script, *, clock=None, sleeps=None, **over):
    transport = OrdinalTransport(script)
    monkeypatch.setattr(dp4, "_send_once", transport)
    monkeypatch.setattr(
        dp4, "_sleep", (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    )
    kwargs = {
        "raw_root": tmp_path,
        "receipt_schema_bytes": SCHEMA,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "retrieval_clock": clock or (lambda: STAMP),
    }
    kwargs.update(over)
    return dp4.collect_documentation_evidence_v4(**kwargs), transport


def persisted(result) -> dict:
    return json.loads((result.attempt_root / result.receipt_reference).read_bytes())


def files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- public surface -----------------------------------------------------------


def test_the_public_signature_is_pinned():
    parameters = inspect.signature(dp4.collect_documentation_evidence_v4).parameters
    assert set(parameters) == {
        "raw_root", "receipt_schema_bytes", "code_commit", "run_created_at",
        "retrieval_clock", "receipt_schema_sha256",
    }
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    assert "url" not in parameters and "urls" not in parameters
    assert "transport_send" not in parameters and "sleep" not in parameters
    assert parameters["retrieval_clock"].default is inspect.Parameter.empty
    assert parameters["receipt_schema_sha256"].default is not inspect.Parameter.empty


def test_the_private_seams_are_not_exported():
    assert "_send_once" not in dp4.__all__
    assert "_sleep" not in dp4.__all__
    from dynamic_ai_products import collection

    assert "_send_once" not in collection.__all__
    assert "http_adapter" not in collection.__all__
    assert "collect_documentation_evidence_v4" in collection.__all__


def test_the_v4_entry_point_is_reachable_from_the_package():
    from dynamic_ai_products import collection

    assert collection.collect_documentation_evidence_v4 is (
        dp4.collect_documentation_evidence_v4
    )
    # The v0.3 entry point is preserved alongside it, not replaced.
    from dynamic_ai_products.collection import documentation_policy as dp3

    assert collection.collect_documentation_evidence is dp3.collect_documentation_evidence


def test_the_policy_contract_declares_the_v4_shape():
    contract = dp4.POLICY_CONTRACT_V4
    assert contract["contract"] == "documentation_acquisition_policy@0.4.0"
    assert contract["policy_version"] == "0.4.0"
    assert contract["route_kinds"] == ["direct", "redirect_once"]
    assert contract["max_sends_by_route_kind"] == {"direct": 1, "redirect_once": 2}
    assert contract["max_sends_per_attempt"] == 5
    assert contract["direct_route_redirect_followed"] is False
    assert contract["observed_location_followed"] is False
    assert contract["observed_location_truncated"] is False
    # No total wall-clock deadline exists at any layer, and none is claimed.
    assert contract["total_wall_clock_deadline"] is None


def test_the_v3_policy_is_preserved_and_still_publishes_v3():
    from dynamic_ai_products.collection import documentation_policy as dp3

    assert dp3.POLICY_CONTRACT["contract"] == "documentation_acquisition_policy@0.3.0"
    assert dp3.POLICY_CONTRACT is not dp4.POLICY_CONTRACT_V4


def test_the_reason_vocabulary_adds_exactly_one_code():
    from dynamic_ai_products.collection import documentation_policy as dp3

    added = dp4.DOCUMENTATION_REASON_CODES_V4 - dp3.DOCUMENTATION_REASON_CODES
    assert added == {"direct_redirect_not_permitted"}
    assert len(dp4.DOCUMENTATION_REASON_CODES_V4) == 28


# --- the sentinel -------------------------------------------------------------


@pytest.mark.parametrize(
    "claim", [None, "a" * 64, "not-a-digest", 7, object()],
    ids=["none", "valid-looking", "malformed", "int", "object"],
)
def test_any_supplied_schema_digest_is_refused(monkeypatch, tmp_path: Path, claim):
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [], receipt_schema_sha256=claim)
    assert excinfo.value.reason_code == "receipt_schema_claim_forbidden"
    assert files(tmp_path) == set(), "zero artifacts"


def test_a_foreign_schema_is_refused_before_any_send(monkeypatch, tmp_path: Path):
    v3 = (ROOT / "schemas" / "documentation_collection_receipt.v3.schema.json").read_bytes()
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [], receipt_schema_bytes=v3)
    assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"
    assert files(tmp_path) == set()


# --- ordered preflight --------------------------------------------------------


def test_a_configured_keylog_refuses_before_the_attempt_root(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keylog.txt"))
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [])
    assert excinfo.value.reason_code == "tls_keylog_environment_present"
    assert files(tmp_path) == set()


def test_a_duplicate_attempt_root_is_refused(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, full_success_script())
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, full_success_script())
    assert excinfo.value.reason_code == "attempt_root_exists"
    # The first attempt's receipt survives untouched.
    assert (result.attempt_root / result.receipt_reference).is_file()


@pytest.mark.parametrize("bad", ["", "   ", "not-an-instant", "2026-02-30T00:00:00Z"])
def test_an_unusable_run_created_at_is_refused(monkeypatch, tmp_path: Path, bad):
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [], run_created_at=bad)
    assert excinfo.value.reason_code == "attempt_identity_invalid"
    assert files(tmp_path) == set()


# --- the full authorized sequence ---------------------------------------------


def test_a_complete_attempt_issues_exactly_five_ordered_sends(monkeypatch, tmp_path: Path):
    result, transport = run(monkeypatch, tmp_path, full_success_script())
    assert result.completion_status == "completed"
    transport.assert_exhausted()
    assert transport.calls == [
        (1, E1["requested_url"], False),
        (2, E1["final_url"], True),
        (3, E2["requested_url"], False),
        (4, E2["final_url"], True),
        (5, E3["requested_url"], True),
    ]
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_complete_attempt_spaces_every_send_after_the_first(monkeypatch, tmp_path: Path):
    sleeps: list[float] = []
    result, transport = run(monkeypatch, tmp_path, full_success_script(), sleeps=sleeps)
    assert result.completion_status == "completed"
    # Five sends, so four delays. This is a spacing count, not a wall-clock bound.
    assert len(transport.calls) == 5
    assert sleeps == [dp4.SPACING_SECONDS] * 4


def test_a_complete_attempt_persists_one_object_per_entry(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, full_success_script())
    objects = sorted(p.name for p in tmp_path.rglob("document.html"))
    assert objects == ["document.html"] * 3
    for entry in result.entries:
        assert entry["entry_status"] == "succeeded"
        assert entry["object_disposition"] == "created"
        assert entry["byte_count"] == len(BODY)


def test_the_receipt_lives_outside_any_digest_directory(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, full_success_script())
    reference = str((result.attempt_root / result.receipt_reference).relative_to(tmp_path))
    assert reference.startswith("attempts/")
    assert "sha256-" not in reference


# --- persistence --------------------------------------------------------------


def test_an_object_whose_bytes_do_not_match_its_path_is_refused(monkeypatch, tmp_path: Path):
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    corrupt = tmp_path / E1["evidence_kind"] / f"sha256-{digest}" / "document.html"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"<html>different</html>")

    result, transport = run(monkeypatch, tmp_path, full_success_script()[:2])
    assert result.completion_status == "stopped"
    assert result.entries[0]["failure_reason"] == "content_object_corrupt"
    assert result.entries[0]["failure_phase"] == "persistence"
    assert corrupt.read_bytes() == b"<html>different</html>", "never deleted"
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_an_identical_object_is_reused_not_overwritten(monkeypatch, tmp_path: Path):
    first, _ = run(monkeypatch, tmp_path, full_success_script())
    assert all(e["object_disposition"] == "created" for e in first.entries)
    second, _ = run(
        monkeypatch, tmp_path, full_success_script(), code_commit="b" * 40
    )
    assert second.attempt_id != first.attempt_id
    assert all(e["object_disposition"] == "reused" for e in second.entries)
    # Reuse never authorizes skipping the request: the bytes were fetched again.
    assert all(e["byte_count"] == len(BODY) for e in second.entries)


# --- structural boundaries ----------------------------------------------------


def test_the_v4_policy_declares_no_route_url():
    import re

    source = (SRC / "documentation_policy_v4.py").read_text(encoding="utf-8")
    literals = re.findall(r'"(https?://[^"]*)"', source)
    assert literals == ["https://"], literals
    for entry in dp4.FROZEN_EVIDENCE_ENTRIES_V4:
        for field in ("requested_url", "final_url"):
            assert entry[field] not in source


def test_the_v4_policy_reads_no_clock_and_no_vcs():
    source = (SRC / "documentation_policy_v4.py").read_text(encoding="utf-8")
    for marker in ("datetime.now", "time.time", "utcnow", "subprocess", "rev-parse"):
        assert marker not in source, marker


def test_no_entry_refusal_carries_a_computed_value():
    """AST: no raise site may build its reason or phase from observed data.

    Both arguments may be a literal, a plain name, or an attribute read -- the
    reason is often ``exc.reason_code`` from a CollectionError, and the phase is
    sometimes a validated parameter threaded through a shared helper. What is
    forbidden is any *construction*: an f-string, concatenation, call or
    subscript could interpolate an observed URL or header. ``_EntryRefusal``
    re-validates both against the closed vocabularies at runtime, which a
    separate test exercises directly.
    """
    tree = ast.parse((SRC / "documentation_policy_v4.py").read_text(encoding="utf-8"))
    sites = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        if not (isinstance(func, ast.Name) and func.id == "_EntryRefusal"):
            continue
        sites += 1
        for argument in node.exc.args:
            assert isinstance(argument, (ast.Constant, ast.Name, ast.Attribute)), (
                ast.dump(argument)
            )
            if isinstance(argument, ast.Constant):
                assert isinstance(argument.value, str)
                assert (
                    argument.value in v4.ENTRY_RECORDABLE_REASONS_V4
                    or argument.value in v4.FAILURE_PHASES
                ), argument.value
    assert sites >= 12, sites


def test_no_exception_message_in_the_v4_policy_is_computed():
    """Sanitized constants only: a message is the one place a value could hide."""
    tree = ast.parse((SRC / "documentation_policy_v4.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        if not (isinstance(func, ast.Name) and func.id == "CollectionError"):
            continue
        assert node.exc.args, ast.dump(node.exc)
        message = node.exc.args[0]
        assert isinstance(message, ast.Constant) and isinstance(message.value, str)


def test_an_entry_refusal_rejects_an_undeclared_pair():
    with pytest.raises(ValueError):
        dp4._EntryRefusal("not_a_reason", "entry_preflight")
    with pytest.raises(ValueError):
        dp4._EntryRefusal("transport_failed", "not_a_phase")
