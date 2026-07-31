"""The attempt-level receipt and its manual schema loader (ADR-037, ADR-038).

The loader is deliberately hand-written rather than ``jsonschema``-driven: that
package sits in the ``dev`` extra, not the base dependencies, and
``pyproject.toml`` is outside this increment's path set. What it validates is the
schema *document's* shape, which is all the attempt identity needs to bind.

**Two contracts, kept apart (ADR-038).** This file owns the frozen
``documentation_collection_receipt@0.1.0`` contract: its loader, its builder, its
schema and its terminal sequencing. It had also grown live-collector tests that
fed the collector ``SCHEMA`` and validated the result against it — an identity
the collector no longer publishes. Those two roles are now separated:

* ``SCHEMA`` stays bound to 0.1.0 and every pure contract test uses it, with its
  fixtures **built directly** rather than harvested from a collector run;
* ``V3_SCHEMA`` is what the collector is given, because the collector publishes
  ``documentation_collection_receipt@0.3.0``.

No 0.3.0 receipt is ever validated against the 0.1.0 schema here — the two
contracts reject each other by design, which
``tests/collection/test_documentation_receipt_v2.py`` and its v3 sibling prove.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from dynamic_ai_products.collection import documentation_policy as dp
from dynamic_ai_products.collection.documentation_receipt import (
    ENTRY_PROPERTIES,
    ENTRY_RECORDABLE_REASONS,
    FAILURE_REASONS,
    FROZEN_ENTRY_IDENTITIES,
    TERMINAL_SEQUENCES,
    ENTRY_STATUSES,
    RECEIPT_CONTRACT,
    RECEIPT_PROPERTIES,
    RECEIPT_SCHEMA_ID,
    SCHEMA_DIALECT,
    build_documentation_receipt,
    receipt_bytes,
    validate_receipt_schema_bytes,
)
from dynamic_ai_products.collection.errors import CollectionError
from dynamic_ai_products.collection.http_adapter import AdapterResponse

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "documentation_collection_receipt.schema.json"
SCHEMA = SCHEMA_PATH.read_bytes()
# What the collector is given: it publishes 0.3.0, never 0.1.0.
V3_SCHEMA_PATH = ROOT / "schemas" / "documentation_collection_receipt.v3.schema.json"
V3_SCHEMA = V3_SCHEMA_PATH.read_bytes()
BODY = b"<html><body>official claim</body></html>"
HTML = {"content-type": "text/html; charset=utf-8"}
COMMIT = "4bcbe2e059714f9a7592751a2a9d1d59d0293bfa"
STAMP = "2026-07-31T09:00:00Z"


def _happy(*, url, iterate_body, **kwargs):
    pair = next(
        e for e in dp.FROZEN_EVIDENCE_ENTRIES
        if url in (e["requested_url"], e["final_url"])
    )
    if url == pair["requested_url"]:
        return AdapterResponse(301, pair["final_url"], {}, url, None, 0)
    return AdapterResponse(200, None, HTML, url, BODY, len(BODY))


def _collect(monkeypatch, tmp_path: Path, *, send=_happy, clock=None):
    monkeypatch.setattr(dp, "_send_once", send)
    monkeypatch.setattr(dp, "_sleep", lambda s: None)
    return dp.collect_documentation_evidence(
        raw_root=tmp_path,
        receipt_schema_bytes=V3_SCHEMA,
        code_commit=COMMIT,
        run_created_at=STAMP,
        retrieval_clock=clock or (lambda: STAMP),
    )


def _mutated(**changes) -> bytes:
    """Apply dotted-path mutations, walking lists by integer index."""
    schema = json.loads(SCHEMA.decode("utf-8"))
    for path, value in changes.items():
        node = schema
        keys = path.split(".")
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node[key]
        last = keys[-1]
        if isinstance(node, list):
            node[int(last)] = value
        elif value is _DELETE:
            node.pop(last, None)
        else:
            node[last] = value
    return json.dumps(schema).encode("utf-8")


_DELETE = object()


# --- the committed schema -----------------------------------------------------


def test_the_committed_schema_passes_the_loader():
    digest = validate_receipt_schema_bytes(SCHEMA)
    assert len(digest) == 64 and digest == digest.lower()


def test_the_digest_is_derived_from_the_exact_bytes():
    from hashlib import sha256

    assert validate_receipt_schema_bytes(SCHEMA) == sha256(SCHEMA).hexdigest()


def test_the_schema_declares_the_locked_identity():
    schema = json.loads(SCHEMA.decode("utf-8"))
    assert schema["$schema"] == SCHEMA_DIALECT
    assert schema["$id"] == RECEIPT_SCHEMA_ID
    # The contract identity lives here, not in $id or title.
    assert schema["properties"]["contract"]["const"] == RECEIPT_CONTRACT
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert frozenset(schema["properties"]) == RECEIPT_PROPERTIES
    entries = schema["properties"]["entries"]
    # Positionally frozen: three prefixItems and no additional entries.
    assert entries["minItems"] == entries["maxItems"] == 3
    assert entries["items"] is False
    assert len(entries["prefixItems"]) == 3
    for item, frozen in zip(entries["prefixItems"], FROZEN_ENTRY_IDENTITIES):
        assert item["additionalProperties"] is False
        assert frozenset(item["properties"]) == ENTRY_PROPERTIES
        assert tuple(item["properties"]["entry_status"]["enum"]) == ENTRY_STATUSES
        for field, expected in frozen.items():
            assert item["properties"][field]["const"] == expected


# --- loader refusals ----------------------------------------------------------


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"$schema": "https://json-schema.org/draft-07/schema#"}, "receipt_schema_invalid"),
        ({"$id": "other.schema.json"}, "receipt_schema_invalid"),
        ({"type": "array"}, "receipt_schema_invalid"),
        ({"additionalProperties": True}, "receipt_schema_invalid"),
        (
            {"properties.contract": {"const": "something_else@0.1.0"}},
            "receipt_schema_contract_mismatch",
        ),
        ({"properties.schema_version": {"const": "0.2.0"}}, "receipt_schema_invalid"),
        (
            {"properties.retrieval_timestamp_mode": {"const": "other_mode"}},
            "receipt_schema_invalid",
        ),
        ({"required": ["contract"]}, "receipt_schema_invalid"),
        ({"properties.entries.minItems": 0}, "receipt_schema_invalid"),
        ({"properties.entries.maxItems": 4}, "receipt_schema_invalid"),
        ({"properties.entries.items": True}, "receipt_schema_invalid"),
        (
            {"properties.attempt_id": {"type": "string"}},
            "receipt_schema_invalid",
        ),
        (
            {"properties.run_created_at": {"type": "string"}},
            "receipt_schema_invalid",
        ),
        (
            {"properties.adapter_contract_sha256": {"type": "string"}},
            "receipt_schema_invalid",
        ),
        (
            {"properties.completion_status": {"enum": ["done"]}},
            "receipt_schema_invalid",
        ),
        ({"allOf": []}, "receipt_schema_invalid"),
    ],
    ids=[
        "dialect", "id", "type", "addprops", "contract-const", "schema-version-const",
        "timestamp-mode-const", "required-set", "min-entries", "max-entries",
        "extra-entries-allowed", "attempt-id-pattern", "run-created-at-pattern",
        "digest-pattern", "completion-enum", "completion-rules",
    ],
)
def test_each_locked_identity_check_is_individually_enforced(changes, code):
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**changes))
    assert excinfo.value.reason_code == code


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("field", ["evidence_kind", "requested_url", "final_url"])
def test_each_entry_pins_its_frozen_route_identity(index, field):
    """A free string here would let a foreign or reordered route pass.

    The code is ``receipt_schema_invalid``: only a foreign top-level
    ``properties.contract.const`` is a *contract* mismatch, and an entry
    identity change is a weakening of this contract rather than a different one.
    """
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(
            _mutated(**{
                f"properties.entries.prefixItems.{index}.properties.{field}": {
                    "const": "https://elsewhere.test/x"
                }
            })
        )
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "path,value",
    [
        ("allOf", [{}]),
        ("oneOf", [{}]),
        ("properties.entries.prefixItems.0.allOf.0", {}),
        ("properties.entries.prefixItems.0.properties.content_type", {"type": "string"}),
        ("properties.entries.prefixItems.0.properties.http_status",
         {"type": ["integer", "null"], "minimum": 100, "maximum": 999}),
        ("properties.entries.prefixItems.0.properties.redirect_chain",
         {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 9}),
        ("properties.entries.prefixItems.0.properties.object_disposition",
         {"enum": ["created", "reused", "borrowed", None]}),
        ("properties.entries.prefixItems.0.properties.retrieval_timestamp",
         {"type": ["string", "null"], "pattern": ".*"}),
        ("properties.code_commit", {"type": "string", "minLength": 0}),
    ],
    ids=[
        "top-allof-emptied", "oneof-emptied", "entry-allof-emptied",
        "content-type-nullability", "http-status-maximum", "redirect-chain-maxitems",
        "foreign-disposition", "timestamp-pattern-widened", "code-commit-minlength",
    ],
)
def test_semantic_weakening_anywhere_is_refused(path, value):
    """A hand-written checklist missed all of these; a deep comparison does not."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**{path: value}))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "path",
    [
        "properties.entries.prefixItems.0.additionalProperties",
        "properties.entries.prefixItems.1.additionalProperties",
    ],
)
def test_an_entry_that_permits_extra_properties_is_refused(path):
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**{path: True}))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "path,value",
    [
        ("properties.entries.prefixItems.0.properties.failure_reason", {"enum": ["oops"]}),
        ("properties.entries.prefixItems.0.properties.content_sha256", {"type": "string"}),
        ("properties.entries.prefixItems.0.properties.byte_count", {"type": "integer"}),
        ("properties.entries.prefixItems.0.properties.entry_status", {"enum": ["ok"]}),
        ("properties.entries.prefixItems.0.allOf", []),
    ],
    ids=["failure-vocab", "digest-pattern", "byte-minimum", "status-enum", "consistency"],
)
def test_entry_scalar_and_semantic_weakening_is_refused(path, value):
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**{path: value}))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


def test_a_duplicated_required_declaration_is_refused():
    schema = json.loads(SCHEMA.decode("utf-8"))
    schema["required"] = schema["required"] + ["contract"]
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(json.dumps(schema).encode("utf-8"))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


# --- the schema itself, exercised with a real validator -----------------------


def _succeeded_entries() -> list[dict]:
    """Three succeeded v0.1.0 entries, built directly against the frozen shape.

    Built rather than harvested from a collector run: the collector publishes
    0.3.0 now, and validating that against this schema would be exactly the
    cross-contract confusion ADR-038 separated and ADR-039 preserved.
    """
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    entries = []
    for frozen in FROZEN_ENTRY_IDENTITIES:
        entry = {field: None for field in ENTRY_PROPERTIES}
        entry.update(frozen)
        entry["entry_status"] = "succeeded"
        entry["redirect_chain"] = [frozen["requested_url"], frozen["final_url"]]
        entry["http_status"] = 200
        entry["content_type"] = HTML["content-type"]
        entry["content_encoding"] = "identity"
        entry["byte_count"] = len(BODY)
        entry["content_sha256"] = digest
        entry["raw_reference"] = (
            f"{frozen['evidence_kind']}/sha256-{digest}/document.html"
        )
        entry["object_disposition"] = "created"
        entry["retrieval_timestamp"] = STAMP
        entries.append(entry)
    return entries


def _valid_receipt() -> dict:
    """A completed v0.1.0 receipt, constructed directly."""
    return build_documentation_receipt(
        attempt_id="docattempt-" + "0" * 32,
        code_commit=COMMIT,
        run_created_at=STAMP,
        adapter_contract_sha256="1" * 64,
        policy_contract_sha256="2" * 64,
        receipt_schema_sha256="3" * 64,
        retrieval_timestamp_mode=dp.RETRIEVAL_TIMESTAMP_MODE,
        entries=_succeeded_entries(),
        completion_status="completed",
    )


def test_a_completed_v1_receipt_validates_against_the_committed_schema():
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA.decode("utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_valid_receipt())


def test_a_stopped_v1_receipt_validates_against_the_committed_schema():
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA.decode("utf-8"))
    Draft202012Validator(schema).validate(_valid_stopped_receipt())


@pytest.mark.parametrize("count", [0, 2, 4], ids=["zero", "two", "four"])
def test_the_schema_rejects_a_wrong_entry_count(count):
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    receipt = _valid_receipt()
    receipt["entries"] = (receipt["entries"] * 2)[:count]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


def test_the_schema_rejects_reordered_entry_identities():
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    receipt = _valid_receipt()
    receipt["entries"] = list(reversed(receipt["entries"]))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


def test_the_schema_rejects_a_foreign_url():
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    receipt = _valid_receipt()
    receipt["entries"][0]["final_url"] = "https://evil.test/x"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


def test_the_schema_rejects_an_unknown_failure_reason():
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    receipt = _valid_receipt()
    receipt["entries"][0]["entry_status"] = "failed"
    receipt["entries"][0]["failure_reason"] = "evidence_body_unusable"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["entries"][0].update(entry_status="failed"),
        lambda r: r["entries"][0].update(content_sha256=None),
        lambda r: r["entries"][0].update(object_disposition=None),
        lambda r: r.update(completion_status="stopped"),
    ],
    ids=["failed-with-payload", "succeeded-without-digest",
         "succeeded-without-disposition", "stopped-without-a-failure"],
)
def test_the_schema_rejects_contradictory_status_and_payload(mutate):
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    receipt = _valid_receipt()
    mutate(receipt)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


def test_the_two_contracts_stay_separated_in_this_file():
    """A 0.3.0 receipt is never validated against the 0.1.0 schema here."""
    assert RECEIPT_CONTRACT == "documentation_collection_receipt@0.1.0"
    assert _valid_receipt()["contract"] == RECEIPT_CONTRACT
    assert b"@0.3.0" in V3_SCHEMA and b"@0.3.0" not in SCHEMA


# --- canonical bytes ----------------------------------------------------------


def test_every_canonical_serializer_agrees_and_ends_with_one_newline():
    from dynamic_ai_products.collection.http_adapter import adapter_contract_bytes
    from dynamic_ai_products.collection.publication import canonical_json_bytes

    payload = {"b": 1, "a": {"d": 2, "c": [3, "x"]}}
    reference = canonical_json_bytes(payload)
    assert reference.endswith(b"\n") and not reference.endswith(b"\n\n")
    assert b": " not in reference and b", " not in reference

    contract = adapter_contract_bytes()
    assert contract.endswith(b"\n") and not contract.endswith(b"\n\n")
    assert contract == canonical_json_bytes(
        json.loads(contract.decode("utf-8"))
    )

    receipt = _valid_stopped_receipt()
    serialized = receipt_bytes(receipt)
    assert serialized.endswith(b"\n") and not serialized.endswith(b"\n\n")
    assert serialized == canonical_json_bytes(receipt)


@pytest.mark.parametrize("payload", [b"", b"not json", None, "text", 7])
def test_unusable_schema_bytes_are_refused(payload):
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(payload)
    assert excinfo.value.reason_code == "receipt_schema_invalid"


def test_the_loader_uses_no_jsonschema_runtime_import():
    source = (
        ROOT / "src" / "dynamic_ai_products" / "collection" / "documentation_receipt.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "jsonschema" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "jsonschema"


# --- the published receipt ----------------------------------------------------


def test_a_completed_attempt_publishes_one_write_once_receipt(
    monkeypatch, tmp_path: Path
):
    result = _collect(monkeypatch, tmp_path)
    assert result.completion_status == "completed"
    path = result.attempt_root / result.receipt_reference
    assert path.is_file()
    receipt = json.loads(path.read_text(encoding="utf-8"))
    # The collector publishes the 0.3.0 successor, not this module's contract.
    assert receipt["contract"] == "documentation_collection_receipt@0.3.0"
    assert receipt["contract"] != RECEIPT_CONTRACT
    assert receipt["schema_version"] == "0.3.0"
    assert receipt["attempt_id"] == result.attempt_id
    assert receipt["completion_status"] == "completed"
    assert len(receipt["entries"]) == 3
    assert all(e["entry_status"] == "succeeded" for e in receipt["entries"])


def test_the_receipt_lives_outside_any_digest_directory(monkeypatch, tmp_path: Path):
    """So it stays writable when entry one fails before any hash exists."""
    result = _collect(monkeypatch, tmp_path, clock=lambda: "bad")
    assert result.completion_status == "stopped"
    reference = str((result.attempt_root / result.receipt_reference).relative_to(tmp_path))
    assert reference.startswith("attempts/")
    assert "sha256-" not in reference
    receipt = json.loads(
        (result.attempt_root / result.receipt_reference).read_text(encoding="utf-8")
    )
    assert [e["entry_status"] for e in receipt["entries"]] == [
        "failed",
        "not_attempted",
        "not_attempted",
    ]


def test_a_partial_failure_preserves_prior_successes(monkeypatch, tmp_path: Path):
    calls: list[str] = []

    def send(*, url, iterate_body, **kwargs):
        calls.append(url)
        if len(calls) == 3:
            return AdapterResponse(500, None, {}, url, None, 0)
        return _happy(url=url, iterate_body=iterate_body, **kwargs)

    result = _collect(monkeypatch, tmp_path, send=send)
    assert [e["entry_status"] for e in result.entries] == [
        "succeeded",
        "failed",
        "not_attempted",
    ]
    assert result.entries[0]["content_sha256"] is not None
    assert result.entries[1]["failure_reason"] == "redirect_status_invalid"
    assert result.entries[2]["failure_reason"] is None
    # The first content object survives the stop.
    objects = [p for p in tmp_path.rglob("document.html")]
    assert len(objects) == 1


def _stopped_entries() -> list[dict]:
    """failed, not_attempted, not_attempted -- a truthful stopped sequence."""
    entries = []
    for index, frozen in enumerate(FROZEN_ENTRY_IDENTITIES):
        entry = {field: None for field in ENTRY_PROPERTIES}
        entry.update(frozen)
        entry["redirect_chain"] = []
        entry["entry_status"] = "failed" if index == 0 else "not_attempted"
        entry["failure_reason"] = "transport_failed" if index == 0 else None
        entries.append(entry)
    return entries


def _valid_stopped_receipt() -> dict:
    return build_documentation_receipt(
        attempt_id="docattempt-" + "0" * 32,
        code_commit=COMMIT,
        run_created_at=STAMP,
        adapter_contract_sha256="1" * 64,
        policy_contract_sha256="2" * 64,
        receipt_schema_sha256="3" * 64,
        retrieval_timestamp_mode=dp.RETRIEVAL_TIMESTAMP_MODE,
        entries=_stopped_entries(),
        completion_status="stopped",
    )


def test_the_receipt_is_deterministic_and_canonical():
    receipt = _valid_stopped_receipt()
    assert receipt_bytes(receipt) == receipt_bytes(receipt)
    assert b" " not in receipt_bytes(receipt)[:40]


def test_an_unknown_entry_or_completion_status_is_refused():
    with pytest.raises(CollectionError):
        build_documentation_receipt(
            attempt_id="docattempt-" + "0" * 32,
            code_commit=COMMIT,
            run_created_at=STAMP,
            adapter_contract_sha256="1" * 64,
            policy_contract_sha256="2" * 64,
            receipt_schema_sha256="3" * 64,
            retrieval_timestamp_mode=dp.RETRIEVAL_TIMESTAMP_MODE,
            entries=[],
            completion_status="mystery",
        )


# --- content-addressed disposition --------------------------------------------


def test_an_identical_object_is_reused_not_overwritten(monkeypatch, tmp_path: Path):
    """A later attempt fetching byte-identical bytes must verify and reuse."""
    first = _collect(monkeypatch, tmp_path)
    assert all(e["object_disposition"] == "created" for e in first.entries)

    # A second attempt with a different identity, same bytes.
    monkeypatch.setattr(dp, "_send_once", _happy)
    monkeypatch.setattr(dp, "_sleep", lambda s: None)
    second = dp.collect_documentation_evidence(
        raw_root=tmp_path,
        receipt_schema_bytes=V3_SCHEMA,
        code_commit="b" * 40,
        run_created_at=STAMP,
        retrieval_clock=lambda: STAMP,
    )
    assert second.attempt_id != first.attempt_id
    assert all(e["object_disposition"] == "reused" for e in second.entries)
    # Reuse never authorizes skipping the request: the bytes were fetched again.
    assert all(e["byte_count"] == len(BODY) for e in second.entries)


def test_an_existing_object_whose_bytes_do_not_match_its_path_is_refused(
    monkeypatch, tmp_path: Path
):
    from hashlib import sha256

    digest = sha256(BODY).hexdigest()
    corrupt = tmp_path / "gemini_thinking" / f"sha256-{digest}" / "document.html"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"<html>different</html>")

    result = _collect(monkeypatch, tmp_path)
    assert result.entries[0]["failure_reason"] == "content_object_corrupt"
    assert result.completion_status == "stopped"
    # The pre-existing object is never deleted by the refusal.
    assert corrupt.read_bytes() == b"<html>different</html>"


# --- exact terminal sequencing ------------------------------------------------


def _receipt_with(statuses, completion) -> dict:
    """Build a receipt payload directly, bypassing the builder's refusal."""
    entries = []
    for status, frozen in zip(statuses, FROZEN_ENTRY_IDENTITIES):
        entry = {field: None for field in ENTRY_PROPERTIES}
        entry.update(frozen)
        entry["entry_status"] = status
        if status == "succeeded":
            entry.update(
                redirect_chain=[frozen["requested_url"], frozen["final_url"]],
                http_status=200,
                content_type="text/html",
                content_encoding="identity",
                byte_count=10,
                content_sha256="a" * 64,
                raw_reference="x/sha256-" + "a" * 64 + "/document.html",
                object_disposition="created",
                retrieval_timestamp=STAMP,
            )
        else:
            entry["redirect_chain"] = []
            entry["failure_reason"] = "transport_failed" if status == "failed" else None
        entries.append(entry)
    return {
        "contract": RECEIPT_CONTRACT,
        "schema_version": "0.1.0",
        "attempt_id": "docattempt-" + "0" * 32,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "adapter_contract_sha256": "1" * 64,
        "policy_contract_sha256": "2" * 64,
        "receipt_schema_sha256": "3" * 64,
        "retrieval_timestamp_mode": dp.RETRIEVAL_TIMESTAMP_MODE,
        "entries": entries,
        "completion_status": completion,
    }


@pytest.mark.parametrize("completion,statuses", TERMINAL_SEQUENCES)
def test_every_permitted_terminal_sequence_validates(completion, statuses):
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA.decode("utf-8"))
    Draft202012Validator(schema).validate(_receipt_with(statuses, completion))


@pytest.mark.parametrize(
    "completion,statuses",
    [
        # A run that cannot have happened: the collector stops at the first failure.
        ("stopped", ("not_attempted", "failed", "succeeded")),
        ("stopped", ("failed", "succeeded", "not_attempted")),
        ("stopped", ("succeeded", "not_attempted", "failed")),
        ("stopped", ("not_attempted", "not_attempted", "not_attempted")),
        ("stopped", ("failed", "failed", "not_attempted")),
        ("stopped", ("succeeded", "succeeded", "succeeded")),
        ("completed", ("succeeded", "succeeded", "failed")),
        ("completed", ("succeeded", "not_attempted", "not_attempted")),
    ],
    ids=[
        "na-f-s", "f-s-na", "s-na-f", "no-failure", "two-failures",
        "stopped-all-succeeded", "completed-with-failure", "completed-with-na",
    ],
)
def test_every_impossible_sequence_is_rejected(completion, statuses):
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(_receipt_with(statuses, completion))


# --- per-status payload invariants --------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(content_type=None),
        lambda e: e.update(content_encoding=None),
        lambda e: e.update(redirect_chain=[]),
        lambda e: e.update(redirect_chain=["https://evil.test/a", "https://evil.test/b"]),
        lambda e: e.update(http_status=201),
        lambda e: e.update(byte_count=0),
        lambda e: e.update(content_sha256="A" * 64),
        lambda e: e.update(raw_reference=""),
        lambda e: e.update(object_disposition="borrowed"),
        lambda e: e.update(retrieval_timestamp="2026-07-31T09:00:00+02:00"),
        lambda e: e.update(failure_reason="transport_failed"),
    ],
    ids=[
        "null-content-type", "null-encoding", "empty-chain", "foreign-chain",
        "non-200", "zero-bytes", "uppercase-digest", "blank-reference",
        "foreign-disposition", "non-utc-stamp", "reason-on-success",
    ],
)
def test_a_succeeded_entry_must_carry_its_full_payload(mutate):
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    receipt = _receipt_with(("succeeded",) * 3, "completed")
    mutate(receipt["entries"][0])
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


@pytest.mark.parametrize(
    "status,mutate",
    [
        ("failed", lambda e: e.update(content_sha256="a" * 64)),
        ("failed", lambda e: e.update(http_status=500)),
        ("failed", lambda e: e.update(redirect_chain=["https://a.test/x"])),
        ("failed", lambda e: e.update(failure_reason=None)),
        ("failed", lambda e: e.update(failure_reason="evidence_body_unusable")),
        ("failed", lambda e: e.update(failure_reason="receipt_publication_failed")),
        ("not_attempted", lambda e: e.update(failure_reason="transport_failed")),
        ("not_attempted", lambda e: e.update(retrieval_timestamp=STAMP)),
    ],
    ids=[
        "failed-with-digest", "failed-with-status", "failed-with-chain",
        "failed-without-reason", "failed-foreign-reason", "failed-non-entry-reason",
        "na-with-reason", "na-with-stamp",
    ],
)
def test_a_failed_or_not_attempted_entry_must_stay_empty(status, mutate):
    from jsonschema import Draft202012Validator, ValidationError

    schema = json.loads(SCHEMA.decode("utf-8"))
    statuses = ("failed", "not_attempted", "not_attempted")
    receipt = _receipt_with(statuses, "stopped")
    index = 0 if status == "failed" else 1
    mutate(receipt["entries"][index])
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


# --- the builder refuses what the schema would reject -------------------------


def _build(entries, completion="stopped"):
    return build_documentation_receipt(
        attempt_id="docattempt-" + "0" * 32,
        code_commit=COMMIT,
        run_created_at=STAMP,
        adapter_contract_sha256="1" * 64,
        policy_contract_sha256="2" * 64,
        receipt_schema_sha256="3" * 64,
        retrieval_timestamp_mode=dp.RETRIEVAL_TIMESTAMP_MODE,
        entries=entries,
        completion_status=completion,
    )


@pytest.mark.parametrize(
    "entries,completion",
    [
        ([], "stopped"),
        ([], "completed"),
        (None, "stopped"),
    ],
    ids=["empty-stopped", "empty-completed", "not-a-list"],
)
def test_the_builder_refuses_a_wrong_entry_count(entries, completion):
    with pytest.raises(CollectionError) as excinfo:
        _build(entries, completion)
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "statuses,completion",
    [
        (("not_attempted", "failed", "succeeded"), "stopped"),
        (("succeeded", "succeeded", "succeeded"), "stopped"),
        (("succeeded", "succeeded", "failed"), "completed"),
    ],
    ids=["impossible-order", "stopped-without-failure", "completed-with-failure"],
)
def test_the_builder_refuses_an_impossible_sequence(statuses, completion):
    entries = _receipt_with(statuses, completion)["entries"]
    with pytest.raises(CollectionError) as excinfo:
        _build(entries, completion)
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(content_sha256=None),
        lambda e: e.update(object_disposition=None),
        lambda e: e.update(content_type=None),
        lambda e: e.update(byte_count=0),
        lambda e: e.update(redirect_chain=[]),
        lambda e: e.update(evidence_kind="other_kind"),
    ],
    ids=["no-digest", "no-disposition", "no-content-type", "zero-bytes",
         "empty-chain", "foreign-identity"],
)
def test_the_builder_refuses_a_broken_succeeded_entry(mutate):
    entries = _receipt_with(("succeeded",) * 3, "completed")["entries"]
    mutate(entries[0])
    with pytest.raises(CollectionError) as excinfo:
        _build(entries, "completed")
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "not-an-attempt"),
        ("code_commit", ""),
        ("run_created_at", "2026-02-30T09:00:00Z"),
        ("adapter_contract_sha256", "A" * 64),
        ("retrieval_timestamp_mode", "other_mode"),
        ("completion_status", "mystery"),
    ],
)
def test_the_builder_refuses_broken_top_level_identity(field, value):
    kwargs = {
        "attempt_id": "docattempt-" + "0" * 32,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "adapter_contract_sha256": "1" * 64,
        "policy_contract_sha256": "2" * 64,
        "receipt_schema_sha256": "3" * 64,
        "retrieval_timestamp_mode": dp.RETRIEVAL_TIMESTAMP_MODE,
        "entries": _receipt_with(("failed", "not_attempted", "not_attempted"), "stopped")[
            "entries"
        ],
        "completion_status": "stopped",
    }
    kwargs[field] = value
    with pytest.raises(CollectionError) as excinfo:
        build_documentation_receipt(**kwargs)
    assert excinfo.value.reason_code == "receipt_schema_invalid"


def test_every_builder_output_validates_against_the_committed_schema():
    """The collector can never publish bytes its own schema rejects."""
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA.decode("utf-8"))
    for completion, statuses in TERMINAL_SEQUENCES:
        entries = _receipt_with(statuses, completion)["entries"]
        Draft202012Validator(schema).validate(_build(entries, completion))


# --- reason vocabulary synchronization ----------------------------------------


def test_the_entry_recordable_subset_is_the_policy_vocabulary_minus_the_impossible():
    """Bound to the policy vocabulary, so the two cannot drift apart."""
    non_entry = {
        "receipt_schema_claim_forbidden",
        "receipt_schema_invalid",
        "receipt_schema_contract_mismatch",
        "attempt_identity_invalid",
        "attempt_root_exists",
        "attempt_root_unsafe",
        "receipt_publication_failed",
    }
    assert set(FAILURE_REASONS) == set(dp.DOCUMENTATION_REASON_CODES)
    assert set(ENTRY_RECORDABLE_REASONS) == set(FAILURE_REASONS) - non_entry
    # Preflight reasons cannot be entry failures: no attempt root exists yet.
    for reason in ("receipt_schema_claim_forbidden", "attempt_root_exists"):
        assert reason not in ENTRY_RECORDABLE_REASONS
    # A publication failure cannot appear inside a successfully published receipt.
    assert "receipt_publication_failed" not in ENTRY_RECORDABLE_REASONS
    # A keylog appearing between sends genuinely is an entry failure.
    assert "tls_keylog_environment_present" in ENTRY_RECORDABLE_REASONS


def test_every_reason_the_collector_can_record_is_entry_recordable(
    monkeypatch, tmp_path: Path
):
    result = _collect(monkeypatch, tmp_path, clock=lambda: "bad")
    for entry in result.entries:
        reason = entry["failure_reason"]
        assert reason is None or reason in ENTRY_RECORDABLE_REASONS


# --- JSON-type-exact comparison and duplicate members -------------------------
#
# Python deep equality is not JSON-type-exact: True == 1 and False == 0, so a
# plain ``!=`` accepted minLength/minimum weakened to ``true`` and
# additionalProperties/items weakened to ``0``. json.loads also resolves a
# repeated member name silently. Both are closed here.


@pytest.mark.parametrize(
    "path,value",
    [
        ("properties.code_commit.minLength", True),
        ("properties.entries.prefixItems.0.properties.byte_count.minimum", True),
        ("properties.entries.prefixItems.0.properties.content_type.minLength", True),
        ("additionalProperties", 0),
        ("properties.entries.items", 0),
        ("properties.entries.prefixItems.0.additionalProperties", 0),
        ("properties.entries.minItems", 3.0),
        ("properties.entries.maxItems", 3.0),
        ("properties.entries.prefixItems.0.properties.http_status.maximum", 599.0),
    ],
    ids=[
        "minlength-true", "minimum-true", "entry-minlength-true",
        "addprops-zero", "items-zero", "entry-addprops-zero",
        "minitems-float", "maxitems-float", "maximum-float",
    ],
)
def test_a_bool_or_float_substitution_is_refused(path, value):
    """`True == 1` and `3 == 3.0` in Python; the comparator is type-exact."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**{path: value}))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        b'{"$schema": "a", "$schema": "a"}',
        b'{"$schema": "a", "$schema": "b"}',
        b'{"properties": {"contract": {"const": "x"}, "contract": {"const": "x"}}}',
        b'{"properties": {"entries": {"type": "array", "type": "array"}}}',
    ],
    ids=["top-identical", "top-differing", "nested-identical", "deep-identical"],
)
def test_a_duplicate_member_name_is_refused_at_any_depth(payload):
    """Identical values still refuse: which definition governs is ambiguous."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(payload)
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"properties": "truthy-string"}).encode(),
        json.dumps({"properties": ["truthy", "list"]}).encode(),
        json.dumps({"properties": 7}).encode(),
        json.dumps({"required": "not-a-list"}).encode(),
        json.dumps({"required": {"a": 1}}).encode(),
        json.dumps({"required": [{}]}).encode(),
        json.dumps({"required": [["nested"]]}).encode(),
        json.dumps({"required": [None]}).encode(),
        json.dumps([1, 2, 3]).encode(),
        b'"a bare string"',
        b"123",
    ],
    ids=[
        "properties-string", "properties-list", "properties-int",
        "required-string", "required-dict", "required-object-member",
        "required-list-member", "required-null-member",
        "top-level-array", "top-level-string", "top-level-number",
    ],
)
def test_a_malformed_schema_shape_never_leaks_a_python_error(payload):
    """No AttributeError, TypeError, KeyError or parser error may escape."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(payload)
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "contract",
    [
        {},
        {"type": "string"},
        {"const": None},
        {"const": True},
        {"const": False},
        {"const": 123},
        {"const": 1.0},
        {"const": []},
        {"const": {}},
        {"const": ""},
        {"const": "   "},
        {"const": "\t\n"},
        "a bare string",
        ["a", "list"],
        7,
        None,
    ],
    ids=[
        "empty-dict", "no-const", "const-null", "const-true", "const-false",
        "const-int", "const-float", "const-list", "const-object", "const-empty",
        "const-spaces", "const-whitespace", "non-dict-string", "non-dict-list",
        "non-dict-int", "non-dict-null",
    ],
)
def test_a_contract_shape_that_names_nothing_is_a_weakening_not_a_mismatch(contract):
    """None of these identifies a foreign contract, so none earns that code."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**{"properties.contract": contract}))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "name",
    [
        "other_contract@0.1.0",
        "documentation_collection_receipt@0.2.0",
        "web_collection_receipt@0.1.0",
        "  padded_contract@0.1.0  ",
    ],
)
def test_a_readable_foreign_contract_keeps_its_distinct_code(name):
    """A non-blank string naming something else is genuinely a foreign contract."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(_mutated(**{"properties.contract": {"const": name}}))
    assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"


def test_the_correct_contract_string_continues_to_the_exact_comparison():
    """A right name plus a weakening is a weakening, not a mismatch."""
    with pytest.raises(CollectionError) as excinfo:
        validate_receipt_schema_bytes(
            _mutated(**{
                "properties.contract": {"const": RECEIPT_CONTRACT},
                "properties.code_commit": {"type": "string", "minLength": 0},
            })
        )
    assert excinfo.value.reason_code == "receipt_schema_invalid"


def test_the_correct_contract_string_alone_still_validates():
    """Restating the correct const changes nothing; the schema still passes."""
    assert validate_receipt_schema_bytes(
        _mutated(**{"properties.contract": {"const": RECEIPT_CONTRACT}})
    )


@pytest.mark.parametrize(
    "dumps_kwargs",
    [
        {"indent": 4, "sort_keys": True},
        {"indent": None, "separators": (",", ":")},
        {"indent": 2, "sort_keys": False},
    ],
    ids=["indent4-sorted", "compact", "indent2-unsorted"],
)
def test_alternate_formatting_is_accepted_with_its_own_byte_digest(dumps_kwargs):
    """Formatting is not part of the comparison; the digest is of these bytes."""
    from hashlib import sha256

    payload = json.dumps(json.loads(SCHEMA.decode("utf-8")), **dumps_kwargs).encode(
        "utf-8"
    )
    assert validate_receipt_schema_bytes(payload) == sha256(payload).hexdigest()
    if payload != SCHEMA:
        assert validate_receipt_schema_bytes(payload) != validate_receipt_schema_bytes(
            SCHEMA
        )


def test_the_comparator_separates_bool_int_and_float_directly():
    from dynamic_ai_products.collection.documentation_receipt import _json_exact_equal

    assert _json_exact_equal({"a": 1}, {"a": 1})
    assert not _json_exact_equal({"a": 1}, {"a": True})
    assert not _json_exact_equal({"a": False}, {"a": 0})
    assert not _json_exact_equal({"a": 3}, {"a": 3.0})
    assert not _json_exact_equal([1], [True])
    assert not _json_exact_equal({"a": 1}, {"a": 1, "b": 2})
    assert not _json_exact_equal([1, 2], [2, 1])
