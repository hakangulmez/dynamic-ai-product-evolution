"""Prompt qualification binding for the two-operation route (ADR-044, G2).

Everything here is offline. No provider is constructed, no credential is read,
no socket is opened: the integration cases drive ``run_extraction_stage_v2``
with an injected fake whose only job is to record whether its run permit was
revoked, and every one of them refuses before the first filesystem effect.

The unit cases exercise :func:`validate_prompt_qualification` directly, because
a refusal that can only be reached through a full run is a refusal whose
individual predicates are untested.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.routing_contract import (
    ROUTING_CONTRACT_ID,
    derive_routing_contract,
)
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_CONTRACT_ID,
    STAGE_OUTPUT_SCHEMA_SHA256,
)
from dynamic_ai_products.extraction.prompt_qualification import (
    BASIS_UNSUPPORTED,
    BOOTSTRAP_BASIS,
    DECLARED_NON_CLAIMS,
    EVALUATED_BASIS,
    GOVERNING_SPEC_REFERENCE,
    KNOWN_LIMITATION_CODES,
    PROMPT_QUALIFICATION_CONTRACT,
    PROMPT_QUALIFICATION_INVALID,
    PROMPT_QUALIFICATION_MISMATCH,
    PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP,
    REFERENCE_UNRESOLVABLE,
    validate_prompt_qualification,
)
from dynamic_ai_products.extraction.prompts import (
    EXTRACTION_PROMPTS,
    load_prompt,
    single_pass_prompt_plan,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import run_extraction_stage_v2
from dynamic_ai_products.providers.client_contract_v2 import (
    build_client_contract_v2,
    build_operation_endpoints,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "prompt_qualification_record.schema.json"
CHANGE_REQUEST_REFERENCE = (
    "evals/change_requests/CR-0001-product-discovery-recall-bootstrap-qualification.md"
)
STAGE = "product_extraction"
STAGE_SHA = STAGE_OUTPUT_SCHEMA_SHA256[STAGE]
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
PROJECT = "my-research-project"
CODE_COMMIT = "be627003f3246b371c2b3ac13e813ef0bb112582"
RUN_CREATED_AT = "2026-07-29T00:00:00Z"
ROUTING_SHA = derive_routing_contract(
    client_contract=build_client_contract_v2(vertex_project=PROJECT)
)["routing_contract_sha256"]
CLIENT_CONTRACT_SHA = sha256_bytes(
    canonical_json_bytes(build_client_contract_v2(vertex_project=PROJECT))
)

GOV_AUTH = "governance/live_call_authorization.json"
GOV_ENABLEMENT = "governance/adapter_enablement_record.json"
GOV_QUALIFICATION = "governance/adapter_qualification_record.json"
GOV_PROMPT_QUALIFICATION = "governance/prompt_qualification_record.json"


def _repo_digest(reference: str) -> str:
    return sha256_bytes((ROOT / reference).read_bytes())


def _prompt():
    return load_prompt(ROOT, "product_discovery_recall")


def record(**overrides) -> dict:
    """A bootstrap record that satisfies every predicate against this repository."""
    prompt = _prompt()
    payload = {
        "contract": PROMPT_QUALIFICATION_CONTRACT,
        "schema_version": "0.1.0",
        "qualification_id": "promptqual-0001",
        "qualification_basis": BOOTSTRAP_BASIS,
        "qualification_scope": "qualified_for_development",
        "qualification_status": "bootstrap_authorized_live_dev",
        "prompt_lifecycle_state": "candidate",
        "supersedes_qualification_id": None,
        "prompt_id": "product_discovery_recall",
        "prompt_registry_version": prompt["prompt_registry_version"],
        "prompt_reference": prompt["reference"],
        "prompt_artifact_sha256": prompt["prompt_hash"],
        "stage": STAGE,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
        "execution_contract_sha256": CLIENT_CONTRACT_SHA,
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": ROUTING_SHA,
        "governing_spec_reference": GOVERNING_SPEC_REFERENCE,
        "governing_spec_sha256": _repo_digest(GOVERNING_SPEC_REFERENCE),
        "change_request_reference": CHANGE_REQUEST_REFERENCE,
        "change_request_sha256": _repo_digest(CHANGE_REQUEST_REFERENCE),
        "declared_non_claims": list(DECLARED_NON_CLAIMS),
        "known_limitation_codes": ["single_pass_recall_only_not_consolidated"],
        "reviewer": "methodology-owner",
        "decided_at": "2026-07-28T00:00:00Z",
        "code_commit": CODE_COMMIT,
    }
    payload.update(overrides)
    return payload


def evaluated_record(**overrides) -> dict:
    """The successor shape: schema-valid, and deliberately unreachable in E-B."""
    payload = record()
    payload.pop("declared_non_claims")
    payload["qualification_basis"] = EVALUATED_BASIS
    payload["qualification_status"] = "qualified"
    payload["qualification_scope"] = "qualified_for_release"
    payload["prompt_lifecycle_state"] = "accepted"
    payload["review_decision"] = "accept_candidate"
    payload["supporting_evaluation_references"] = [
        {"evaluation_run_reference": "runs/eval-1/manifest.json", "evaluation_run_sha256": "a" * 64}
    ]
    payload.update(overrides)
    return payload


def call(**overrides):
    """Invoke the gate with the arguments the production call site supplies."""
    kwargs = {
        "record": record(),
        "enablement": {"rollout_state": "live_dev", "routing_contract_id": ROUTING_CONTRACT_ID,
                       "routing_contract_sha256": ROUTING_SHA},
        "authorization": {"rollout_state": "live_dev"},
        "qualification": {
            "execution_contract_id": "extraction_provider_client_contract@0.2.0",
            "execution_contract_sha256": CLIENT_CONTRACT_SHA,
        },
        "prompt": _prompt(),
        "prompt_plan": single_pass_prompt_plan(STAGE),
        "stage": STAGE,
        "stage_output_schema_sha256": STAGE_SHA,
        "client_contract_sha256": CLIENT_CONTRACT_SHA,
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
        "repo_root": ROOT,
    }
    kwargs.update(overrides)
    return validate_prompt_qualification(**kwargs)


def refuses(expected_code, **overrides):
    with pytest.raises(ExtractionError) as excinfo:
        call(**overrides)
    assert excinfo.value.reason_code == expected_code
    return excinfo.value


# --- identity, registry, and the four-way schema agreement --------------------


def test_the_reference_record_is_accepted_unchanged():
    assert call() == record()


def test_the_schema_file_manifest_key_contract_and_version_agree():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json").read_text(encoding="utf-8")
    )["schemas"]
    key = SCHEMA_PATH.name.removesuffix(".schema.json")
    assert schema["$id"] == SCHEMA_PATH.name
    assert manifest[key] == schema["properties"]["schema_version"]["const"]
    assert schema["properties"]["contract"]["const"] == f"{key}@{manifest[key]}"
    assert schema["properties"]["contract"]["const"] == PROMPT_QUALIFICATION_CONTRACT


def test_the_runtime_property_set_is_the_schema_bootstrap_shape():
    """The schema documents; the runtime enforces. They must not drift."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    always = set(schema["required"])
    assert PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP == always | {"declared_non_claims"}
    assert len(always) == 27
    assert len(PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP) == 28
    assert set(schema["properties"]) == always | {
        "declared_non_claims",
        "review_decision",
        "supporting_evaluation_references",
    }


def test_the_prompt_id_vocabulary_is_the_registry_and_not_a_second_list():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    declared = set(schema["properties"]["prompt_id"]["enum"])
    assert declared == {pid for ids in EXTRACTION_PROMPTS.values() for pid in ids}


def test_the_stage_sequence_still_puts_discovery_first():
    """A reordered registry would silently requalify a different prompt."""
    assert EXTRACTION_PROMPTS[STAGE][0] == "product_discovery_recall"
    assert single_pass_prompt_plan(STAGE)["prompt_id"] == "product_discovery_recall"


def test_the_pinned_prompt_digest_is_recomputed_from_the_repository_artifact():
    """If the frozen prompt is edited, this fails first and requalification is forced."""
    prompt = _prompt()
    on_disk = sha256_bytes((ROOT / prompt["reference"]).read_bytes())
    assert record()["prompt_artifact_sha256"] == on_disk == prompt["prompt_hash"]


# --- P0: only the bootstrap basis executes ------------------------------------


def test_an_evaluated_comparison_record_is_refused_even_though_it_is_schema_valid():
    payload = evaluated_record()
    assert Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).is_valid(payload)
    refuses(BASIS_UNSUPPORTED, record=payload)


def test_the_basis_is_checked_before_the_property_set_is_selected():
    """An evaluated record carries properties the bootstrap set forbids.

    If the order were reversed it would fail as a malformed bootstrap record,
    which would report the wrong cause and would leave the evaluated branch
    looking merely unimplemented rather than deliberately unreachable.
    """
    error = refuses(BASIS_UNSUPPORTED, record=evaluated_record())
    assert "evaluated_comparison" in str(error)


@pytest.mark.parametrize("basis", [None, "", "qualified", 1, True, ["bootstrap_pre_evaluation"]])
def test_any_other_basis_value_is_refused(basis):
    refuses(BASIS_UNSUPPORTED, record=record(qualification_basis=basis))


def test_a_non_mapping_record_is_refused():
    refuses(PROMPT_QUALIFICATION_INVALID, record=["not", "a", "mapping"])


# --- closed property set and credential prohibition ---------------------------


@pytest.mark.parametrize("field", sorted(PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP))
def test_every_declared_property_is_required(field):
    if field == "qualification_basis":
        pytest.skip("absence of the basis is refused earlier, by P0")
    payload = record()
    payload.pop(field)
    refuses(PROMPT_QUALIFICATION_INVALID, record=payload)


def test_an_undeclared_property_is_refused():
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(extra_field="x"))


def test_a_bootstrap_record_may_not_carry_a_review_decision():
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(review_decision="accept_candidate"))


def test_a_bootstrap_record_may_not_carry_supporting_evaluation_references():
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(supporting_evaluation_references=[]))


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "x"},
        {"client_secret": "x"},
        {"reviewer": "ya29.abc"},
        {"qualification_id": "AIzaSyExample"},
    ],
)
def test_credential_shaped_material_is_refused_at_any_depth(payload):
    refuses("credential_material_in_artifact", record=record(**payload))


def test_no_property_name_admits_free_text():
    for forbidden in ("message", "detail", "note", "comment", "error"):
        assert not any(
            forbidden in name for name in PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP
        ), forbidden


# --- constants, enums, and the bootstrap iff ----------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("contract", "prompt_qualification_record@0.2.0"),
        ("schema_version", "0.2.0"),
        ("prompt_registry_version", "extraction_prompt_registry_v2"),
        ("qualification_scope", "qualified_for_release"),
        ("qualification_status", "qualified"),
        ("prompt_lifecycle_state", "accepted"),
    ],
)
def test_each_const_is_enforced_at_runtime(field, value):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(**{field: value}))


@pytest.mark.parametrize("status", ["superseded", "revoked", "bootstrap_authorized_pilot"])
def test_a_bootstrap_record_holds_exactly_one_status(status):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(qualification_status=status))


@pytest.mark.parametrize("state", ["draft", "deprecated", "frozen"])
def test_a_bootstrap_record_holds_exactly_one_lifecycle_state(state):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(prompt_lifecycle_state=state))


@pytest.mark.parametrize("rollout", ["controlled_pilot", "release_or_research_production", "mock_only"])
def test_a_bootstrap_basis_authorizes_only_live_dev(rollout):
    refuses(
        PROMPT_QUALIFICATION_INVALID,
        enablement={
            "rollout_state": rollout,
            "routing_contract_id": ROUTING_CONTRACT_ID,
            "routing_contract_sha256": ROUTING_SHA,
        },
    )
    refuses(PROMPT_QUALIFICATION_INVALID, authorization={"rollout_state": rollout})


@pytest.mark.parametrize(
    "claims",
    [
        [],
        list(DECLARED_NON_CLAIMS)[:3],
        list(reversed(DECLARED_NON_CLAIMS)),
        [*DECLARED_NON_CLAIMS, "not_a_release_qualification"],
        [DECLARED_NON_CLAIMS[1], DECLARED_NON_CLAIMS[0], *DECLARED_NON_CLAIMS[2:]],
    ],
)
def test_the_four_non_claims_are_exact_and_ordered(claims):
    """A permuted tuple is a different statement, so membership is not enough."""
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(declared_non_claims=claims))


@pytest.mark.parametrize(
    "codes",
    [
        [],
        "single_pass_recall_only_not_consolidated",
        ["not_a_known_code"],
        ["sec_only_partial_corpus", "sec_only_partial_corpus"],
    ],
)
def test_known_limitation_codes_are_a_closed_distinct_non_empty_list(codes):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(known_limitation_codes=codes))


def test_every_known_limitation_code_is_individually_accepted():
    assert call(record=record(known_limitation_codes=list(KNOWN_LIMITATION_CODES)))


@pytest.mark.parametrize("value", ["", "   ", 7])
def test_supersedes_must_be_a_non_blank_string_or_null(value):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(supersedes_qualification_id=value))


def test_a_superseding_record_may_name_its_predecessor():
    assert call(record=record(supersedes_qualification_id="promptqual-0000"))


@pytest.mark.parametrize(
    "field", ["code_commit", "execution_contract_id", "qualification_id", "reviewer",
              "routing_contract_id", "stage_output_contract_id"]
)
def test_every_identifier_must_be_a_non_blank_string(field):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(**{field: "   "}))


@pytest.mark.parametrize(
    "field", ["change_request_sha256", "execution_contract_sha256", "governing_spec_sha256",
              "prompt_artifact_sha256", "routing_contract_sha256", "stage_output_contract_sha256"]
)
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, 1])
def test_every_digest_must_be_64_lowercase_hex(field, value):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(**{field: value}))


# --- the two roots ------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "governance/CR-0001-x.md",
        "/evals/change_requests/CR-0001-x.md",
        "evals/change_requests/../../etc/passwd",
        "evals/change_requests/CR-1-x.md",
        "evals/change_requests/CR-0001-x.txt",
        "C:/evals/change_requests/CR-0001-x.md",
        CHANGE_REQUEST_REFERENCE + "\n",
    ],
)
def test_a_change_request_reference_outside_its_directory_is_unrepresentable(reference):
    """The pattern is the containment, not a convention.

    A trailing newline is included deliberately: an ECMA-262 ``pattern`` whose
    ``$`` matches before a line terminator would admit it, so the schema carries
    a negative lookahead and the runtime uses ``re.fullmatch``.
    """
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(change_request_reference=reference))


@pytest.mark.parametrize(
    "reference",
    ["specs/SPEC-008-product-extraction.md", "governance/SPEC-024.md", "prompts/extraction/x.md"],
)
def test_the_governing_spec_is_spec_024_and_not_a_stage_spec(reference):
    """SPEC-008 is stage context for the change request, not qualification policy."""
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(governing_spec_reference=reference))


@pytest.mark.parametrize(
    "reference",
    ["prompts/extraction/product-discovery-recall.md", "src/x.md", "prompts/x.md"],
)
def test_a_prompt_reference_outside_the_frozen_prompt_directory_is_refused(reference):
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(prompt_reference=reference))


def test_a_repository_document_is_read_against_the_repo_root_not_the_governance_root(tmp_path):
    """Placing the change request in the governance root does not satisfy the pin.

    If the reference were ever resolved against ``governance_artifact_root``, a
    governance root could supply its own change request and the tracked,
    reviewable document would stop being the thing that was reviewed.
    """
    governance = tmp_path / "governance-root"
    target = governance / CHANGE_REQUEST_REFERENCE
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / CHANGE_REQUEST_REFERENCE).read_bytes())
    refuses(REFERENCE_UNRESOLVABLE, repo_root=governance)


@pytest.mark.parametrize("field", ["change_request_sha256", "governing_spec_sha256"])
def test_a_cited_repository_document_must_hash_to_its_pin(field):
    refuses(REFERENCE_UNRESOLVABLE, record=record(**{field: "b" * 64}))


def test_a_change_request_that_does_not_exist_is_refused():
    refuses(
        REFERENCE_UNRESOLVABLE,
        record=record(
            change_request_reference="evals/change_requests/CR-9999-absent.md",
            change_request_sha256="c" * 64,
        ),
    )


def test_a_symlinked_repository_document_is_refused(tmp_path):
    fake_root = tmp_path / "repo"
    (fake_root / "evals" / "change_requests").mkdir(parents=True)
    (fake_root / "specs").mkdir(parents=True)
    (fake_root / GOVERNING_SPEC_REFERENCE).write_bytes(
        (ROOT / GOVERNING_SPEC_REFERENCE).read_bytes()
    )
    (fake_root / CHANGE_REQUEST_REFERENCE).symlink_to(ROOT / CHANGE_REQUEST_REFERENCE)
    refuses(REFERENCE_UNRESOLVABLE, repo_root=fake_root)


# --- the equality predicates --------------------------------------------------


def test_a_record_qualifying_a_different_prompt_is_refused():
    refuses(PROMPT_QUALIFICATION_MISMATCH, record=record(prompt_id="task_discovery_recall"))


def test_a_record_carrying_a_stale_prompt_digest_is_refused():
    refuses(PROMPT_QUALIFICATION_MISMATCH, record=record(prompt_artifact_sha256="d" * 64))


def test_a_record_naming_another_frozen_prompt_file_is_refused():
    refuses(
        PROMPT_QUALIFICATION_MISMATCH,
        record=record(prompt_reference="prompts/extraction/task_discovery_recall.md"),
    )


def test_a_record_qualifying_another_stage_is_refused():
    refuses(PROMPT_QUALIFICATION_MISMATCH, record=record(stage="task_extraction"))


def test_a_record_naming_another_stage_output_contract_is_refused():
    refuses(
        PROMPT_QUALIFICATION_MISMATCH,
        record=record(stage_output_contract_id="task_observation@0.1.0"),
    )


def test_a_record_pinning_a_different_stage_output_schema_is_refused():
    refuses(PROMPT_QUALIFICATION_MISMATCH, stage_output_schema_sha256="e" * 64)


def test_a_record_disagreeing_with_the_adapter_qualification_contract_is_refused():
    refuses(
        PROMPT_QUALIFICATION_MISMATCH,
        qualification={
            "execution_contract_id": "extraction_provider_client_contract@0.1.0",
            "execution_contract_sha256": CLIENT_CONTRACT_SHA,
        },
    )


def test_a_record_agreeing_with_the_qualification_but_not_the_executing_contract_is_refused():
    """Both equalities are asserted, so agreement between two records is not enough."""
    other = "f" * 64
    refuses(
        PROMPT_QUALIFICATION_MISMATCH,
        record=record(execution_contract_sha256=other),
        qualification={
            "execution_contract_id": "extraction_provider_client_contract@0.2.0",
            "execution_contract_sha256": other,
        },
    )


@pytest.mark.parametrize(
    "field, value",
    [("routing_contract_id", "vertex_gemini_route@0.1.0"), ("routing_contract_sha256", "9" * 64)],
)
def test_a_record_declaring_another_route_than_the_enablement_is_refused(field, value):
    refuses(PROMPT_QUALIFICATION_MISMATCH, record=record(**{field: value}))


def test_a_record_from_another_build_is_refused():
    refuses(PROMPT_QUALIFICATION_MISMATCH, record=record(code_commit="0" * 40))


def test_a_registry_version_the_route_did_not_resolve_is_refused():
    prompt = dict(_prompt())
    prompt["prompt_registry_version"] = "extraction_prompt_registry_v1"
    assert call(prompt=prompt) == record()


# --- the decision instant -----------------------------------------------------


@pytest.mark.parametrize("value", ["2026-07-28T00:00:00", "not-a-timestamp", "", 1])
def test_a_decision_instant_without_a_zone_is_refused(value):
    """A naive timestamp is refused rather than assumed to be UTC."""
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(decided_at=value))


def test_a_decision_that_postdates_the_run_is_refused():
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(decided_at="2026-07-30T00:00:00Z"))


def test_the_instant_comparison_is_chronological_and_not_lexicographic():
    """``2026-07-29T02:00:00+02:00`` is the run instant itself, spelled differently."""
    assert call(record=record(decided_at="2026-07-29T02:00:00+02:00"))
    refuses(PROMPT_QUALIFICATION_INVALID, record=record(decided_at="2026-07-29T02:00:00-02:00"))


# --- the schema file agrees with the runtime on both branches -----------------


def _schema_validator():
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_the_reference_bootstrap_and_evaluated_records_are_both_schema_valid():
    assert _schema_validator().is_valid(record())
    assert _schema_validator().is_valid(evaluated_record())


@pytest.mark.parametrize(
    "payload",
    [
        record(review_decision="accept_candidate"),
        record(supporting_evaluation_references=[]),
        evaluated_record(declared_non_claims=list(DECLARED_NON_CLAIMS)),
        evaluated_record(qualification_status="bootstrap_authorized_live_dev"),
    ],
)
def test_the_schema_refuses_a_branch_carrying_the_other_branchs_properties(payload):
    assert not _schema_validator().is_valid(payload)


def test_the_schema_refuses_a_permuted_non_claims_tuple():
    assert not _schema_validator().is_valid(
        record(declared_non_claims=list(reversed(DECLARED_NON_CLAIMS)))
    )


# --- the production route: refusal placement and permit revocation ------------


class PermitProvider:
    """Records permit lifecycle only. It has no client, no ADC, and no socket."""

    def __init__(self) -> None:
        self.permitted = 0
        self.revoked = 0

    def assert_run_permitted(self, *, authorization_sha256=None, endpoint_allowlist=None,
                             enablement_endpoint_allowlist=None):
        self.permitted += 1

    def revoke_run_permission(self):
        self.revoked += 1

    def client_contract(self):
        return build_client_contract_v2(vertex_project=PROJECT)

    def count_tokens(self, request, *, sink):  # pragma: no cover - never reached
        raise AssertionError("a refused route must not send")

    def complete_v8(self, request, *, admission, sink):  # pragma: no cover - never reached
        raise AssertionError("a refused route must not send")


class PermitSession:
    def __init__(self) -> None:
        self.admissions = 0

    def meter_identity(self):
        return {"meter_identity": "dynamic_ai_products.extraction.budget_session", "meter_version": "0.1.0"}

    def admit(self, **kwargs):  # pragma: no cover - never reached
        self.admissions += 1
        raise AssertionError("a refused route must not reach the meter")


def _write_chain(root: Path, prompt_qualification: dict | None, *, pin_override=None):
    (root / "governance").mkdir(parents=True, exist_ok=True)
    endpoints = build_operation_endpoints(vertex_project=PROJECT)
    allowlist = [endpoints["count_tokens"], endpoints["generate_content"]]

    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-g2",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini_v2",
        "adapter_version": "0.2.0",
        "adapter_family": "model_execution",
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
        "execution_contract_sha256": CLIENT_CONTRACT_SHA,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "qualification_scope": "live_dev",
        "qualification_status": "qualified",
        "qualified_at": "2026-07-01T00:00:00Z",
    }
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION).write_bytes(qual_bytes)

    if prompt_qualification is None:
        pq_pin = pin_override or {"reference": GOV_PROMPT_QUALIFICATION, "sha256": "3" * 64}
    else:
        pq_bytes = canonical_json_bytes(prompt_qualification)
        (root / GOV_PROMPT_QUALIFICATION).write_bytes(pq_bytes)
        pq_pin = pin_override or {
            "reference": GOV_PROMPT_QUALIFICATION,
            "sha256": sha256_bytes(pq_bytes),
        }

    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-g2",
        "adapter_qualification_record_reference": GOV_QUALIFICATION,
        "adapter_qualification_record_sha256": sha256_bytes(qual_bytes),
        "prompt_qualification_reference": pq_pin["reference"],
        "prompt_qualification_sha256": pq_pin["sha256"],
        "stage": STAGE,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": ROUTING_SHA,
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "endpoint_allowlist": list(allowlist),
        "enablement_status": "enabled_live_dev",
        "approver": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    enab_bytes = canonical_json_bytes(enablement)
    (root / GOV_ENABLEMENT).write_bytes(enab_bytes)

    auth = {
        "contract": "live_call_authorization@0.2.0",
        "schema_version": "0.2.0",
        "authorization_id": "auth-g2",
        "authorized_by": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "adapter_enablement_record_reference": GOV_ENABLEMENT,
        "adapter_enablement_record_sha256": sha256_bytes(enab_bytes),
        "provider_client_contract_reference": "inputs/provider_client_contract.json",
        "provider_client_contract_sha256": CLIENT_CONTRACT_SHA,
        "budget_meter_identity": "dynamic_ai_products.extraction.budget_session",
        "budget_meter_version": "0.1.0",
        "stage": STAGE,
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "corpus_scope": "sec_only_partial",
        "budget_max_records": 1,
        "budget_max_external_requests": 4,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": 1203,
        "budget_policy_version": "budget_policy_v1",
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "endpoint_allowlist": list(allowlist),
        "circuit_breaker_max_consecutive_failures": 1,
        "provider_called": True,
        "harness_run": False,
    }
    auth_bytes = canonical_json_bytes(auth)
    (root / GOV_AUTH).write_bytes(auth_bytes)
    return {"reference": GOV_AUTH, "sha256": sha256_bytes(auth_bytes)}


def _identity(root: Path) -> dict[str, str]:
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
    return {"reference": "pilot_universe_packet.json", "sha256": sha256_bytes(payload)}


def _drive(tmp_path: Path, prompt_qualification, *, pin_override=None):
    governance = tmp_path / "governance-root"
    pin = _write_chain(governance, prompt_qualification, pin_override=pin_override)
    provider = PermitProvider()
    passage_text = "the product ships an assistant"
    with pytest.raises(ExtractionError) as excinfo:
        run_extraction_stage_v2(
            run_root=tmp_path / "run",
            repo_root=ROOT,
            stage=STAGE,
            company_id=COMPANY,
            observation_cutoff_date=CUTOFF,
            passages=[
                {
                    "passage_id": "p-1",
                    "source_id": "sec-1",
                    "text": passage_text,
                    "start_offset": 0,
                    "end_offset": len(passage_text),
                }
            ],
            document_publication_dates={"sec-1": "2024-02-14"},
            coverage_artifact={"reference": "coverage/c.json", "sha256": "d" * 64},
            source_snapshot_manifest={"reference": "snapshots/m.json", "sha256": "e" * 64},
            code_commit=CODE_COMMIT,
            run_created_at=RUN_CREATED_AT,
            extraction_run_id="ext-g2-1",
            prediction_run_id="pred-g2-1",
            evidence_binding={},
            schema_root=str(ROOT / "schemas"),
            provider=provider,
            governance_artifact_root=governance,
            live_call_authorization_pin=pin,
            company_identity_root=tmp_path / "identity",
            company_identity_pin=_identity(tmp_path / "identity"),
        )
    return excinfo.value, provider, tmp_path / "run"


def test_a_pin_naming_a_file_that_does_not_exist_now_breaks_the_chain(tmp_path):
    """The pin used to be shape-checked only; sixty-four hex digits satisfied it."""
    error, provider, run_root = _drive(tmp_path, None)
    assert error.reason_code == "authorization_chain_broken"
    assert not run_root.exists()
    # F0: hydration precedes the handshake, so no permit was ever granted.
    assert (provider.permitted, provider.revoked) == (0, 0)


def test_a_pin_whose_digest_does_not_match_the_record_breaks_the_chain(tmp_path):
    error, provider, run_root = _drive(
        tmp_path,
        record(),
        pin_override={"reference": GOV_PROMPT_QUALIFICATION, "sha256": "7" * 64},
    )
    assert error.reason_code == "authorization_chain_broken"
    assert not run_root.exists()


def test_a_bound_but_wrong_record_refuses_before_any_artifact_and_revokes_the_permit(tmp_path):
    """The gate sits after the handshake, so the permit must be released.

    The refusal is raised inside the caller's ``try``/``finally``. Without that
    guarantee a governance refusal would leave a live permit standing on a client
    the run never used.
    """
    error, provider, run_root = _drive(tmp_path, record(prompt_artifact_sha256="d" * 64))
    assert error.reason_code == PROMPT_QUALIFICATION_MISMATCH
    assert not run_root.exists()
    assert (provider.permitted, provider.revoked) == (1, 1)


def test_an_evaluated_record_refuses_on_the_production_route(tmp_path):
    error, provider, run_root = _drive(tmp_path, evaluated_record())
    assert error.reason_code == BASIS_UNSUPPORTED
    assert not run_root.exists()
    assert provider.revoked == 1


def test_the_refusal_precedes_the_meter_the_run_root_and_every_send(tmp_path):
    """Nothing is spent: no admission, no directory, no attempt."""
    _, provider, run_root = _drive(tmp_path, record(code_commit="0" * 40))
    assert not run_root.exists()
    assert not (tmp_path / "run").exists()
