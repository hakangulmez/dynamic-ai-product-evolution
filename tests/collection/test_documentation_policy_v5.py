"""The v0.5 acquisition policy (ADR-041, E-C-D4).

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

from documentation_v5_transport import (  # noqa: E402
    BODY,
    ExpectedCall,
    OrdinalTransport,
    hop,
    terminal,
)

from dynamic_ai_products.collection import documentation_policy_v5 as dp5  # noqa: E402
from dynamic_ai_products.collection import documentation_receipt_v5 as v5  # noqa: E402
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
SCHEMA = (ROOT / "schemas" / "documentation_collection_receipt.v5.schema.json").read_bytes()
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.decode("utf-8")))
COMMIT = "fbdc13eadb9912872c23fa21149a68c65f59a00c"
STAMP = "2026-08-01T09:00:00Z"

E1, E2, E3 = dp5.FROZEN_EVIDENCE_ENTRIES_V5


def full_success_script() -> list[ExpectedCall]:
    """The complete authorized call sequence: 3 + 3 + 2 = eight sends."""
    return [
        hop(1, E1["requested_url"], E1["intermediate_url"]),
        hop(2, E1["intermediate_url"], E1["second_hop_location"]),
        terminal(3, E1["final_url"]),
        hop(4, E2["requested_url"], E2["intermediate_url"]),
        hop(5, E2["intermediate_url"], E2["second_hop_location"]),
        terminal(6, E2["final_url"]),
        hop(7, E3["requested_url"], E3["final_url"]),
        terminal(8, E3["final_url"]),
    ]


def run(monkeypatch, tmp_path, script, *, clock=None, sleeps=None, **over):
    transport = OrdinalTransport(script)
    monkeypatch.setattr(dp5, "_send_once", transport)
    monkeypatch.setattr(
        dp5, "_sleep", (lambda s: sleeps.append(s)) if sleeps is not None else (lambda s: None)
    )
    kwargs = {
        "raw_root": tmp_path,
        "receipt_schema_bytes": SCHEMA,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "retrieval_clock": clock or (lambda: STAMP),
    }
    kwargs.update(over)
    return dp5.collect_documentation_evidence_v5(**kwargs), transport


def persisted(result) -> dict:
    return json.loads((result.attempt_root / result.receipt_reference).read_bytes())


def first_failure(result) -> dict:
    entry = next(e for e in result.entries if e["entry_status"] == "failed")
    kind, reason, phase = entry["route_kind"], entry["failure_reason"], entry["failure_phase"]
    assert reason in v5.ROUTE_KIND_REASONS_V5[kind], (kind, reason)
    assert phase in v5.ROUTE_KIND_PHASES_V5[kind], (kind, phase)
    assert phase in v5.REASON_PHASES_V5[reason], (reason, phase)
    return entry


def files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}



# --- public surface -----------------------------------------------------------


def test_the_public_signature_is_pinned():
    parameters = inspect.signature(dp5.collect_documentation_evidence_v5).parameters
    assert set(parameters) == {
        "raw_root", "receipt_schema_bytes", "code_commit", "run_created_at",
        "retrieval_clock", "receipt_schema_sha256",
    }
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    assert "url" not in parameters and "urls" not in parameters
    assert "transport_send" not in parameters and "sleep" not in parameters


def test_all_three_entry_points_coexist():
    from dynamic_ai_products import collection
    from dynamic_ai_products.collection import documentation_policy as dp3
    from dynamic_ai_products.collection import documentation_policy_v4 as dp4

    assert len(collection.__all__) == 6
    assert collection.collect_documentation_evidence is dp3.collect_documentation_evidence
    assert collection.collect_documentation_evidence_v4 is dp4.collect_documentation_evidence_v4
    assert collection.collect_documentation_evidence_v5 is dp5.collect_documentation_evidence_v5
    assert "_send_once" not in collection.__all__
    assert "http_adapter" not in collection.__all__


def test_the_earlier_policies_are_preserved_and_publish_their_own_contracts():
    from dynamic_ai_products.collection import documentation_policy as dp3
    from dynamic_ai_products.collection import documentation_policy_v4 as dp4

    assert dp3.POLICY_CONTRACT["contract"] == "documentation_acquisition_policy@0.3.0"
    assert dp4.POLICY_CONTRACT_V4["contract"] == "documentation_acquisition_policy@0.4.0"
    assert dp5.POLICY_CONTRACT_V5["contract"] == "documentation_acquisition_policy@0.5.0"


def test_the_policy_contract_declares_the_v5_shape():
    contract = dp5.POLICY_CONTRACT_V5
    assert contract["policy_version"] == "0.5.0"
    assert contract["route_kinds"] == ["redirect_once", "redirect_twice_relative_path"]
    assert contract["sends_by_route_kind"] == {
        "redirect_once": 2, "redirect_twice_relative_path": 3
    }
    assert contract["max_sends_per_attempt"] == 8
    assert contract["second_hop_absolute_path_reference_only"] is True
    assert contract["relative_resolution_mode"] == "fixed_declared_base_concatenation_v1"
    assert contract["relative_resolution_base"] == "https://docs.cloud.google.com"
    assert contract["observed_location_followed"] is False
    assert contract["retry_policy"] == "none"
    # No total wall-clock deadline exists at any layer, and none is claimed.
    assert contract["total_wall_clock_deadline"] is None


def test_the_reason_vocabulary_movement_is_exact():
    from dynamic_ai_products.collection import documentation_policy_v4 as dp4

    added = dp5.DOCUMENTATION_REASON_CODES_V5 - dp4.DOCUMENTATION_REASON_CODES_V4
    removed = dp4.DOCUMENTATION_REASON_CODES_V4 - dp5.DOCUMENTATION_REASON_CODES_V5
    assert added == {
        "second_redirect_status_invalid", "second_location_missing",
        "second_location_not_relative_path", "second_location_mismatch",
        "resolved_final_mismatch",
    }
    assert removed == {"direct_redirect_not_permitted"}
    assert len(dp5.DOCUMENTATION_REASON_CODES_V5) == 32


# --- the sentinel and preflight -----------------------------------------------


@pytest.mark.parametrize("claim", [None, "a" * 64, "not-a-digest", 7, object()])
def test_any_supplied_schema_digest_is_refused(monkeypatch, tmp_path: Path, claim):
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [], receipt_schema_sha256=claim)
    assert excinfo.value.reason_code == "receipt_schema_claim_forbidden"
    assert files(tmp_path) == set()


def test_a_foreign_schema_is_refused_before_any_send(monkeypatch, tmp_path: Path):
    v4 = (ROOT / "schemas" / "documentation_collection_receipt.v4.schema.json").read_bytes()
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [], receipt_schema_bytes=v4)
    assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"
    assert files(tmp_path) == set()


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
    assert (result.attempt_root / result.receipt_reference).is_file()


@pytest.mark.parametrize("bad", ["", "   ", "not-an-instant", "2026-02-30T00:00:00Z"])
def test_an_unusable_run_created_at_is_refused(monkeypatch, tmp_path: Path, bad):
    with pytest.raises(CollectionError) as excinfo:
        run(monkeypatch, tmp_path, [], run_created_at=bad)
    assert excinfo.value.reason_code == "attempt_identity_invalid"
    assert files(tmp_path) == set()


# --- the full authorized sequence ---------------------------------------------


def test_a_complete_attempt_issues_exactly_eight_ordered_sends(monkeypatch, tmp_path: Path):
    result, transport = run(monkeypatch, tmp_path, full_success_script())
    assert result.completion_status == "completed"
    transport.assert_exhausted()
    assert transport.ordinals == [1, 2, 3, 4, 5, 6, 7, 8]
    assert transport.calls == [
        (1, E1["requested_url"], False),
        (2, E1["intermediate_url"], False),
        (3, E1["final_url"], True),
        (4, E2["requested_url"], False),
        (5, E2["intermediate_url"], False),
        (6, E2["final_url"], True),
        (7, E3["requested_url"], False),
        (8, E3["final_url"], True),
    ]
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_a_complete_attempt_spaces_every_send_after_the_first(monkeypatch, tmp_path: Path):
    sleeps: list[float] = []
    result, transport = run(monkeypatch, tmp_path, full_success_script(), sleeps=sleeps)
    assert result.completion_status == "completed"
    # Eight sends, so seven delays. A spacing count, not a wall-clock bound.
    assert len(transport.calls) == 8
    assert sleeps == [dp5.SPACING_SECONDS] * 7


def test_a_complete_attempt_persists_one_object_per_entry(monkeypatch, tmp_path: Path):
    result, _ = run(monkeypatch, tmp_path, full_success_script())
    assert sorted(p.name for p in tmp_path.rglob("document.html")) == ["document.html"] * 3
    for entry in result.entries:
        assert entry["entry_status"] == "succeeded"
        assert entry["object_disposition"] == "created"
        assert entry["byte_count"] == len(BODY)


# --- persistence --------------------------------------------------------------


def test_an_object_whose_bytes_do_not_match_its_path_is_refused(monkeypatch, tmp_path: Path):
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    corrupt = tmp_path / E1["evidence_kind"] / f"sha256-{digest}" / "document.html"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"<html>different</html>")

    result, _ = run(monkeypatch, tmp_path, full_success_script()[:3])
    assert result.completion_status == "stopped"
    entry = first_failure(result)
    assert entry["failure_reason"] == "content_object_corrupt"
    assert entry["failure_phase"] == "persistence"
    assert entry["content_sha256"] == digest
    assert entry["raw_reference"] is None
    assert corrupt.read_bytes() == b"<html>different</html>"
    assert not list(VALIDATOR.iter_errors(persisted(result)))


def test_an_identical_object_is_reused_not_overwritten(monkeypatch, tmp_path: Path):
    first, _ = run(monkeypatch, tmp_path, full_success_script())
    assert all(e["object_disposition"] == "created" for e in first.entries)
    second, _ = run(monkeypatch, tmp_path, full_success_script(), code_commit="b" * 40)
    assert second.attempt_id != first.attempt_id
    assert all(e["object_disposition"] == "reused" for e in second.entries)
    assert all(e["byte_count"] == len(BODY) for e in second.entries)


# --- structural boundaries ----------------------------------------------------


def test_the_v5_policy_declares_no_route_url():
    import re

    source = (SRC / "documentation_policy_v5.py").read_text(encoding="utf-8")
    literals = re.findall(r'"(https?://[^"]*)"', source)
    # One bare scheme prefix per hop-evaluation function -- both are the
    # absolute-Location syntax check, not a declared route. A guard that banned
    # the prefix outright would punish the code implementing the defence.
    assert set(literals) == {"https://"}, literals
    assert len(literals) == 2, literals
    assert "http://" not in source, "no scheme downgrade literal"
    for entry in dp5.FROZEN_EVIDENCE_ENTRIES_V5:
        for field in ("requested_url", "intermediate_url", "final_url"):
            if entry[field]:
                assert entry[field] not in source, field


def test_the_v5_policy_imports_no_httpx():
    """The repository-wide httpx importer allowlist stays at two modules."""
    source = (SRC / "documentation_policy_v5.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "httpx" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "httpx"


def test_the_v5_policy_reads_no_clock_and_no_vcs():
    source = (SRC / "documentation_policy_v5.py").read_text(encoding="utf-8")
    for marker in ("datetime.now", "time.time", "utcnow", "subprocess", "rev-parse"):
        assert marker not in source, marker


def test_no_entry_refusal_carries_a_computed_value():
    """No raise site may build its reason or phase from observed data."""
    tree = ast.parse((SRC / "documentation_policy_v5.py").read_text(encoding="utf-8"))
    sites = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        func = node.exc.func
        if not (isinstance(func, ast.Name) and func.id == "_EntryRefusal"):
            continue
        sites += 1
        for argument in node.exc.args:
            assert isinstance(argument, (ast.Constant, ast.Name, ast.Attribute)), ast.dump(argument)
            if isinstance(argument, ast.Constant):
                assert isinstance(argument.value, str)
                assert (
                    argument.value in v5.ENTRY_RECORDABLE_REASONS_V5
                    or argument.value in v5.FAILURE_PHASES_V5
                ), argument.value
    assert sites >= 18, sites


def test_no_exception_message_in_the_v5_policy_is_computed():
    tree = ast.parse((SRC / "documentation_policy_v5.py").read_text(encoding="utf-8"))
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
        dp5._EntryRefusal("not_a_reason", "entry_preflight")
    with pytest.raises(ValueError):
        dp5._EntryRefusal("transport_failed", "not_a_phase")
