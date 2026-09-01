"""Slice 1A: evaluation-only schema-registry tests.

Tamper scenarios copy schemas into ``tmp_path``; repository schema files are
never modified.
"""

import ast
import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import compat as compat_mod
from dynamic_ai_products.evaluation import parent_observation_snapshot as pos_mod
from dynamic_ai_products.evaluation import schemas as registry
from dynamic_ai_products.evaluation import validator_parameters as vp_mod
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import ContractStampedModel
from dynamic_ai_products.evaluation.schemas import (
    EVALUATION_SCHEMA_CONTRACTS,
    RELEASED_EVALUATION_CONTRACTS,
    ReadOnlyContractError,
    ReleasedContractBinding,
    SchemaContract,
    SchemaFileInvalidError,
    SchemaFileMissingError,
    SchemaHashMismatchError,
    SchemaMetaValidationError,
    UnknownContractError,
    load_schema,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]


def _tmp_repo(tmp_path: Path) -> Path:
    """A minimal repo copy WITHOUT the active schema-version manifest."""
    (tmp_path / "schemas").mkdir()
    for contract in EVALUATION_SCHEMA_CONTRACTS:
        shutil.copy(ROOT / contract.relative_path, tmp_path / contract.relative_path)
    return tmp_path


def test_loads_both_read_write_schemas() -> None:
    case_schema = load_schema("evaluation_case", "0.1.0", purpose="write")
    result_schema = load_schema("evaluation_result", "0.2.0", purpose="write")
    assert case_schema["$id"] == "evaluation_case.schema.json"
    assert result_schema["$id"] == "evaluation_result.v2.schema.json"


def test_compatibility_read_of_universe_manifest_v2() -> None:
    schema = load_schema("universe_run_manifest", "0.2.0", purpose="read")
    assert schema["$id"] == "universe_run_manifest.v2.schema.json"


def test_unknown_contract_id_fails_closed() -> None:
    with pytest.raises(UnknownContractError):
        load_schema("unknown_contract", "0.1.0")


def test_unknown_contract_version_fails_closed() -> None:
    with pytest.raises(UnknownContractError):
        load_schema("evaluation_case", "9.9.9")


def test_write_against_compat_read_only_fails_closed() -> None:
    with pytest.raises(ReadOnlyContractError):
        load_schema("universe_run_manifest", "0.2.0", purpose="write")


def test_missing_schema_file_fails_closed(tmp_path: Path) -> None:
    repo = _tmp_repo(tmp_path)
    (repo / "schemas" / "evaluation_case.schema.json").unlink()
    with pytest.raises(SchemaFileMissingError):
        load_schema("evaluation_case", "0.1.0", repo_root=repo)


def test_tampered_schema_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    repo = _tmp_repo(tmp_path)
    target = repo / "schemas" / "evaluation_case.schema.json"
    tampered = json.loads(target.read_text())
    tampered["properties"]["injected_field"] = {"type": "string"}
    target.write_text(json.dumps(tampered))
    with pytest.raises(SchemaHashMismatchError):
        load_schema("evaluation_case", "0.1.0", repo_root=repo)


def _patched_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes) -> Path:
    """Register a synthetic contract whose reviewed hash matches ``raw``."""
    (tmp_path / "schemas").mkdir(exist_ok=True)
    path = tmp_path / "schemas" / "synthetic.schema.json"
    path.write_bytes(raw)
    contract = SchemaContract(
        contract_id="synthetic",
        contract_version="0.0.1",
        relative_path="schemas/synthetic.schema.json",
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        mode="read_write",
    )
    monkeypatch.setattr(
        registry, "EVALUATION_SCHEMA_CONTRACTS", (*EVALUATION_SCHEMA_CONTRACTS, contract)
    )
    return tmp_path


def test_malformed_json_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _patched_contract(monkeypatch, tmp_path, b"{not valid json")
    with pytest.raises(SchemaFileInvalidError):
        load_schema("synthetic", "0.0.1", repo_root=repo)


def test_meta_validation_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid_schema = json.dumps({"type": 12345}).encode("utf-8")
    repo = _patched_contract(monkeypatch, tmp_path, invalid_schema)
    with pytest.raises(SchemaMetaValidationError):
        load_schema("synthetic", "0.0.1", repo_root=repo)


def test_registry_never_consults_active_schema_version_manifest(tmp_path: Path) -> None:
    repo = _tmp_repo(tmp_path)
    assert not (repo / "schemas" / "schema_version_manifest.json").exists()
    for contract in EVALUATION_SCHEMA_CONTRACTS:
        schema = load_schema(contract.contract_id, contract.contract_version, repo_root=repo)
        assert schema["$id"]


def test_loaded_schema_is_immutable() -> None:
    schema = load_schema("evaluation_case", "0.1.0")
    with pytest.raises(TypeError):
        schema["injected"] = True  # type: ignore[index]


def test_schema_loads_are_isolated_from_caller_mutation() -> None:
    """Fresh parsing on each load guarantees isolation.

    The top-level ``MappingProxyType`` does not itself provide deep
    immutability: nested dictionaries and lists inside a returned schema
    remain mutable. Isolation is guaranteed instead by parsing a fresh,
    independent object on every ``load_schema`` call, with no shared mutable
    schema cache.
    """
    contract = next(
        c for c in EVALUATION_SCHEMA_CONTRACTS if c.contract_id == "evaluation_case"
    )
    expected_hash_before = contract.expected_sha256

    first = load_schema("evaluation_case", "0.1.0")
    first["required"].append("injected_required_field")
    first["properties"]["stage_context"]["injected"] = {"type": "string"}

    second = load_schema("evaluation_case", "0.1.0")
    assert "injected_required_field" not in second["required"]
    assert "injected" not in second["properties"]["stage_context"]

    third = load_schema("evaluation_case", "0.1.0")
    assert "injected_required_field" not in third["required"]

    assert contract.expected_sha256 == expected_hash_before
    assert EVALUATION_SCHEMA_CONTRACTS == registry.EVALUATION_SCHEMA_CONTRACTS


# --- Slice 14: released-contract binding (RELEASED_EVALUATION_CONTRACTS) ----


SCHEMA_VERSION_MANIFEST_SHA256 = (
    # Rebaselined by ADR-145: manifest_version 0.84.0 -> 0.85.0, 231 -> 233
    # entries. The stricter consolidated-firm CORE pilot successor adds only
    # its authorization and manifest; no released evaluation contract moves.
    # Before it ADR-144: manifest_version 0.83.0 -> 0.84.0, 229 -> 231
    # entries. The named-batch route adds its authorization and manifest;
    # neither is a released evaluation contract or a model-call approval.
    # Before it ADR-143: manifest_version 0.81.0 -> 0.82.0, 226 -> 228
    # entries. The compact V5 pilot adds only its authorization and manifest
    # successors; no released evaluation contract changes.
    # Before it, ADR-142: manifest_version 0.80.0 -> 0.81.0, 222 -> 226
    # entries. The two-axis Item 1 gate adds its axes and record successors plus
    # its isolated V3 authorization and manifest; no released evaluation
    # contract changes.
    # Rebaselined by ADR-140: manifest_version 0.78.0 -> 0.79.0, 216 -> 218
    # entries, registering the annual-coverage-backed pilot authorization and
    # manifest. The V2 pilot is isolated from V1 by grant, manifest and
    # filename while retaining its Item 1 prompt and four-axis record contract.
    # It does not join
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-137 (the pilot's governed execution path):
    # manifest_version 0.75.0 -> 0.76.0, 210 -> 212 entries, registering the
    # pilot authorization and manifest contracts. Nothing else moved: the three
    # ADR-137 contracts registered by the previous entry -- the pilot axes,
    # record and selection schemas -- are byte-unchanged, and so is every V2.x
    # contract, prompt and config. The two new schemas are the pilot's own and
    # join neither EVALUATION_SCHEMA_CONTRACTS nor RELEASED_EVALUATION_CONTRACTS
    # below. What they deliberately omit is the point: no tier rules, no
    # taxonomy version, no strata or span-index binding and no bounded-outcome
    # tolerance, all refused structurally by additionalProperties: false.
    # Before it,
    # Rebaselined by ADR-130 (classifier V2.4, one bound and a prompt):
    # manifest_version 0.68.0 -> 0.69.0, 164 -> 172 entries, registering the
    # 0.3.0 axes and record contracts and the six V2.4 authorization and
    # manifest contracts. The V2.3 calibration stopped after three rows and
    # every one carried exactly one schema error: a supported_claim of 233,
    # 204 and 204 characters against a 200-character cap, while quote
    # lengths (972, 829, 994), evidence counts (12, 12, 8) and all 32 axis
    # labels sat inside 0.2.0. So supported_claim rises to 300 and nothing
    # else moves: evidence stays 12, quote stays 1200, the tier rules and
    # economics are untouched, and the record contract moves only because it
    # inlines the axes contract. Two of the three rows would still fail on
    # quote fidelity -- an ellipsis splice and a prepended, re-cased subject
    # -- which the V2.4 prompt addresses as instruction rather than bound.
    # Every 0.1.0 and 0.2.0 contract stays byte-unchanged and none of the
    # eight joins EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS
    # below.
    # Before it,
    # Rebaselined by ADR-129 (classifier V2.3, a prompt-discipline successor):
    # manifest_version 0.67.0 -> 0.68.0, 158 -> 164 entries, registering the six
    # V2.3 authorization and manifest contracts. Nothing else moved: the axes
    # and record contracts stay at 0.2.0, taxonomy_version stays
    # universe_classifier_axes_v2_2, the tier rules and economics are untouched,
    # and the evidence and quote ceilings stay 12 and 1200. The V2.2 calibration
    # stopped with three of four rows rejected and a wider bound would have
    # rescued one; the rest wrote quotes instead of copying them and used output
    # field names as evidence.axis labels, so the fix is instruction, not
    # contract. The six new contracts exist only because prompt_template_path is
    # a const. Every 0.1.0 and 0.2.0 contract stays byte-unchanged and none of
    # the six joins EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS
    # below.
    # Before it,
    # Rebaselined by ADR-128 (the V2.2 classifier contract set):
    # manifest_version 0.66.0 -> 0.67.0, 150 -> 158 entries, registering the
    # 0.2.0 axes and record contracts and the six V2.2 authorization and
    # manifest contracts. The first live calibration stopped after three rows,
    # all three valid JSON with valid axes and refused on output size alone:
    # evidence capped at 6 against a six-value axis vocabulary, and quote
    # capped at 300 against legitimate contiguous Item 1 spans reaching 972.
    # V2.2 raises those two ceilings to 12 and 1200 and nothing else -- every
    # axis, enum value and tier rule is byte-identical, and taxonomy_version
    # moves only to name the axes-contract identity. Every 0.1.0 contract stays
    # byte-unchanged so a V2.1 run's evidence remains interpretable under the
    # contract it ran under, and none of the eight joins
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-127 (a governed calibration route before the full
    # cohort run): manifest_version 0.65.0 -> 0.66.0, 146 -> 150 entries,
    # registering the calibration selection, authorization, manifest and review
    # contracts. The selection is a closed, seeded, stratified sample of the
    # classifier candidate cohort whose quotas live in a digest-pinned config;
    # the run is the ADR-126 classifier over that sample, bound to the identical
    # prompt and tier-rule bytes and structurally unable to be read as a full
    # run; the review is a qualitative human gate whose contract carries no
    # accuracy or pass/fail field at all. Every earlier contract is
    # byte-unchanged and none of the four joins EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-126 (the governed live Company-Universe Classifier
    # V2.1 and its continuation): manifest_version 0.64.0 -> 0.65.0, 140 -> 146
    # entries, registering the classifier axes and stored-record contracts,
    # both classifier authorizations and both classifier manifests. The axes
    # contract carries no tier field of any name: the model returns axes and a
    # versioned deterministic engine derives the tier, so a prompt revision
    # cannot move tier membership. The stored record keeps the axes, the full
    # rule trace and the admission origin that put the firm in the cohort,
    # marked non-authoritative. Every earlier contract is byte-unchanged and
    # none of the six joins EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-125 (a governed human-review layer and the
    # classifier-candidate cohort): manifest_version 0.63.0 -> 0.64.0, 136 ->
    # 140 entries, registering the human-review decision and overlay manifest
    # contracts and the classifier-candidate record and cohort manifest
    # contracts. The overlay reviews every unresolved SCREEN_v1 row exactly
    # once without editing the release; the cohort admits eligible and
    # boundary rows from either the screen or a reviewer and keeps the
    # admission origin on every row. Neither is a classifier and neither
    # calls a model. Every earlier contract is byte-unchanged and none of the
    # four joins EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS
    # below.
    # Before it,
    # Rebaselined by ADR-124 (the first reconciled SCREEN release):
    # manifest_version 0.62.0 -> 0.63.0, 134 -> 136 entries, registering the
    # release record and release manifest contracts. A release is a
    # derivation from two hash-bound completed runs with no model call and no
    # authorization; a repair output supersedes a base row only where that
    # repair validated, both provenance chains survive on every reconciled
    # row, and the residual tolerance is a const rather than an inherited
    # run-time breaker. Every earlier contract is byte-unchanged and neither
    # new contract joins EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-123 (an unverified row is re-asked, never
    # edited): manifest_version 0.61.0 -> 0.62.0, 130 -> 134 entries,
    # registering the v0.6 record and the three repair contracts. The v0.6
    # record adds row-level repair provenance so a later reconciliation can
    # tell an original observation from a re-asked one; the repair
    # selection, authorization and manifest govern a structurally
    # non-promotable measurement run that re-screens the rows a completed
    # screen could not verify. Every earlier contract is byte-unchanged,
    # the V5 screen prompt is byte-unchanged, and none of the four joins
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-122 (a row the model never finished is an
    # outcome, not a stop): manifest_version 0.60.0 -> 0.61.0, 127 -> 130
    # entries, registering the v0.5 record, the v0.5 continuation
    # authorization and the v0.12 continuation manifest. The v0.5 record
    # adds a fifth row kind, MODEL_OUTPUT_TRUNCATED, for a row whose
    # single candidate returned finishReason MAX_TOKENS; it carries the
    # digest of the envelope that proves it, is never re-sent, and is a
    # named review population, never a screen result. Every earlier
    # contract is byte-unchanged and none of the three joins
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-121 (one unresolvable row must not cost a
    # cohort): manifest_version 0.59.0 -> 0.60.0, 124 -> 127 entries,
    # registering the v0.4 record, the v0.4 continuation authorization and
    # the v0.11 continuation manifest. The v0.4 record adds a fourth row
    # kind, PROVIDER_UNRESOLVED, for a row whose provider path was spent;
    # it is a named review population, never a screen result. Every
    # earlier contract is byte-unchanged and none of the three joins
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-120 (the same absence, on the other operation):
    # manifest_version 0.58.0 -> 0.59.0, 122 -> 124 entries, registering
    # the v0.3 continuation authorization and the v0.10 continuation
    # manifest. ADR-119 closed the empty-body gap for generateContent and
    # left countTokens out of scope; the next run stopped on exactly that.
    # Every earlier contract, both connectors and both retry policies are
    # byte-unchanged, and neither new contract joins
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-119 (an empty successful response is an absence,
    # not an answer): manifest_version 0.57.0 -> 0.58.0, 120 -> 122
    # entries, registering the v0.2 continuation authorization and the
    # v0.9 continuation manifest. The V3/V4 connectors, both screen retry
    # policies, the v0.3 record and every earlier contract are
    # byte-unchanged, and neither new contract is added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-118 (a failed run's completed prefix is evidence, not
    # waste): manifest_version 0.56.0 -> 0.57.0, 117 -> 120 entries,
    # registering universe_screen_record_v3, which carries row provenance, and
    # the continuation authorization and manifest contracts. The V3 route, its
    # generate policy, its connector and every earlier screen contract are
    # byte-unchanged, and none of the three is added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-117 (the screen waits longer for a 429 without any
    # other route changing): manifest_version 0.55.0 -> 0.56.0, 115 -> 117
    # entries, registering universe_screen_live_authorization_v3 and
    # universe_screen_manifest_v7 -- the contracts of the long-backoff
    # authoritative successor, which pins five generate attempts per logical
    # packet at 15s/30s/60s/120s and one un-retried countTokens send. The
    # committed extraction retry policy, both shared connectors, the v0.1/v0.2
    # authorizations and the v0.5/v0.6 manifests are byte-unchanged, and
    # neither new contract is added to EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below. Before it,
    # Rebaselined by ADR-115 (a repair measurement re-screens exactly the
    # seven quote-resolution rejections of one completed diagnostic run,
    # and stays diagnostic forever): manifest_version 0.51.0 -> 0.52.0,
    # 109 -> 112 entries, registering the three diagnostic-repair
    # contracts - universe_screen_diagnostic_repair_selection,
    # universe_screen_diagnostic_repair_authorization and
    # universe_screen_diagnostic_repair_manifest. Every authoritative
    # screen contract, prompt and packet schema is byte-unchanged, and
    # none of the three is added to EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below. Before it,
    # Rebaselined by ADR-113: manifest_version 0.50.0 -> 0.51.0,
    # 108 -> 109 entries, registering universe_screen_manifest_v5.
    # The v5 successor pins the v4 short-reference prompt; every predecessor
    # schema remains byte-identical. Before it,
    # Rebaselined by ADR-112 (a diagnostic canary measures the
    # distribution, not the first defect): manifest_version 0.49.0 ->
    # 0.50.0, 105 -> 108 entries, registering the three diagnostic
    # contracts - universe_screen_diagnostic_record,
    # universe_screen_diagnostic_manifest and
    # universe_screen_diagnostic_authorization. Every authoritative
    # screen contract, prompt and packet schema is byte-unchanged, and
    # none of the three is added to EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below. This module and its four
    # siblings now also own the registry version and entry count
    # outright: ADR-112 removed the duplicate absolute assertions from
    # tests/universe/test_lineage_screen.py. Before it,
    # Rebaselined by ADR-111 (the screen prompt states how evidence is
    # identified and quoted): manifest_version 0.48.0 -> 0.49.0,
    # 104 -> 105 entries, registering universe_screen_manifest_v4 -- the
    # strict live-manifest successor whose prompt_template_path const
    # names the v3 screen prompt. The v1/v2 prompts, the v0.1-v0.3 screen
    # manifests and every packet schema stay byte-unchanged, and the
    # successor is not added to EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below. Before it,
    # Rebaselined by ADR-110 (the screen prompt names its own closed
    # vocabulary): manifest_version 0.47.0 -> 0.48.0, 103 -> 104 entries,
    # registering universe_screen_manifest_v3 -- the strict live-manifest
    # successor whose prompt_template_path const names the v2 screen
    # prompt. The v0.1/v0.2 screen manifests, the v1 prompt and every
    # packet schema stay byte-unchanged, and the successor is not added
    # to EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS
    # below. Before it,
    # Rebaselined by ADR-109 (governed Vertex/Gemini binding for the
    # lineage screen): manifest_version 0.46.0 -> 0.47.0, 99 -> 103
    # entries, registering universe_screen_selection,
    # universe_screen_adapter_enablement,
    # universe_screen_live_authorization and universe_screen_manifest_v2.
    # The v0.1 screen schemas, every packet schema and the provider
    # stack are byte-unchanged; none of the four is added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS
    # below. Before it,
    # Rebaselined by ADR-108 (production high-recall screen over the
    # lineage packet cohort): manifest_version 0.45.0 -> 0.46.0,
    # 97 -> 99 entries, registering universe_screen_record and
    # universe_screen_manifest, the lineage-bound screen record and run
    # manifest. Every packet, determination and aggregate schema is
    # byte-unchanged; neither new schema is added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS
    # below. Before it,
    # Rebaselined by ADR-107 (two-determination lineage packet successor):
    # manifest_version 0.44.0 -> 0.45.0, 96 -> 97 entries, registering
    # baseline_packet_manifest_v5, the shell- and asset-backed-filtered
    # packet-run manifest. The universe_baseline_packet@0.2.0 record contract
    # and the v0.1-v0.4 packet manifests are byte-unchanged; the successor is
    # not added to EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below. Before it,
    # Rebaselined by ADR-105 (deterministic asset-backed-issuer
    # determination): manifest_version 0.43.0 -> 0.44.0, 94 -> 96 entries,
    # registering asset_backed_issuer_determination and its lineage run
    # manifest. The shell-determination schemas, issuer_filters, and every
    # packet contract are byte-unchanged; neither new schema is added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-104 (Item 1 locator v3, combined-heading successor):
    # manifest_version 0.42.0 -> 0.43.0, 93 -> 94 entries, registering
    # baseline_packet_manifest_v4, the locator-declared packet-run manifest.
    # The universe_baseline_packet@0.2.0 record contract and its closed
    # end_boundary_kind enum do not move, and the v0.1/v0.2/v0.3 packet
    # manifests stay byte-unchanged. The successor is not added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-103 (full-cohort Item 1 packets from the lineage):
    # manifest_version 0.41.0 -> 0.42.0, 92 -> 93 entries, registering
    # baseline_packet_manifest_v3, the lineage-cohort packet-run manifest.
    # The universe_baseline_packet@0.2.0 record contract does not move at
    # all -- a row packetized through the lineage path and the single-bundle
    # path yields a byte-identical record -- and the v0.1/v0.2 packet
    # manifests stay byte-unchanged. The successor is not added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below.
    # Before it,
    # Rebaselined by ADR-102 (full-cohort shell determination from a lineage
    # aggregate): manifest_version 0.40.0 -> 0.41.0, 91 -> 92 entries,
    # registering shell_company_determination_manifest_v3. The v0.1 and v0.2
    # determination schemas and the v0.2 manifest are byte-unchanged, and the
    # v0.2 *record* contract does not move at all: a row determined through
    # either path yields an identical record. The successor is not added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below --
    # Stage 00B-S is not a production evaluation-harness contract. Before it,
    # Rebaselined by ADR-101 (lineage aggregation over enumerated execution
    # runs): manifest_version 0.39.0 -> 0.40.0, 90 -> 91 entries, registering
    # acquisition_queue_aggregate_manifest_v2. The v0.1 aggregate schema is
    # byte-unchanged (re-verified directly by
    # tests/universe/test_acquisition_queue.py, which validates a v0.1 payload
    # against it and asserts the two generations reject each other), and the
    # successor is not added to EVALUATION_SCHEMA_CONTRACTS or
    # RELEASED_EVALUATION_CONTRACTS below: the acquisition queue is not a
    # production evaluation-harness contract. Before it,
    # Rebaselined by ADR-099 (Dev30 v0.2 quote-derived-locator successor):
    # manifest_version 0.38.0 -> 0.39.0, 88 -> 90 entries, registering
    # pct_dev30_v0_model_output_v2 and pct_dev30_v0_persisted_candidates_v2.
    # v0.1's two schemas are byte-unchanged (re-verified directly by
    # tests/dev30/test_combined_candidate_adapter_v2.py against v0.1's own
    # pinned hashes, not by diffing git history); the new pair is not added
    # to EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below,
    # same as v0.1. Before it,
    # Rebaselined by ADR-098 (Dev30 combined-candidate contract, Round 2):
    # manifest_version 0.37.0 -> 0.38.0, 86 -> 88 entries, registering
    # pct_dev30_v0_model_output and pct_dev30_v0_persisted_candidates for the
    # two-stage Dev30 combined-candidate output contract
    # (src/dynamic_ai_products/dev30/combined_candidate_adapter.py). Every
    # predecessor schema is byte-unchanged; neither new schema is added to
    # EVALUATION_SCHEMA_CONTRACTS or RELEASED_EVALUATION_CONTRACTS below --
    # Dev30 is not a production evaluation-harness contract, and the adapter
    # loads and hash-pins both schema files itself, independent of this
    # registry. Before it,
    # Rebaselined by ADR-097 (plain-text primaries): manifest_version
    # 0.36.0 -> 0.37.0, 81 -> 86 entries, registering the bundle, packet,
    # packet-manifest and queue-definition v0.2 successors plus the v0.6
    # acquisition manifest. Every predecessor schema is byte-unchanged and
    # none of them admits a .txt document.
    # Before it,
    # Rebaselined by ADR-095 (W3 acquisition queue): manifest_version
    # 0.35.0 -> 0.36.0, 75 -> 81 entries, registering the four queue schemas
    # plus the two budgeted acquisition-manifest successors. The fixture
    # lineage gains v0.4 and the sec_live lineage v0.5; v0.1, v0.2 and v0.3
    # stay byte-unchanged, and no schema admits two histories.
    # Before it,
    # Rebaselined by the ADR-094 transform correction: manifest_version
    # 0.34.0 -> 0.35.0, 73 -> 75 entries, registering
    # shell_company_determination_v2 and its run manifest at 0.2.0 for
    # ixt:booleantrue and ixt:fixed-true on XBRL Transformation Registry
    # authority. The v0.1 entries stay at 0.1.0 and their schema files are
    # byte-unchanged: v0.1 artifacts validate only there, v0.2 only against
    # the successors, and neither validates the other.
    # Before it,
    # ADR-094: manifest_version 0.33.0 -> 0.34.0, 71 -> 73
    # entries, registering shell_company_determination and its run
    # manifest for the isolated Stage 00B-S shell-only determination.
    # Before it,
    # ADR-093: manifest_version 0.32.0 -> 0.33.0, 70 -> 71
    # entries, registering primary_document_acquisition_manifest_v3, the
    # observational sec_live successor that records each hop's parsed
    # Content-Length. v0.1 and v0.2 are unchanged. Before it,
    # ADR-092: manifest_version 0.31.0 -> 0.32.0, 68 -> 70
    # entries, registering primary_document_acquisition_manifest and its
    # v2 sec_live successor for two-hop primary-document acquisition.
    # Before it,
    # ADR-091: manifest_version 0.30.0 -> 0.31.0, 65 -> 68
    # entries, registering baseline_primary_document_bundle (the packet
    # builder's governed input), universe_baseline_packet, and
    # baseline_packet_manifest for W2-C-beta Stage 00C packets.
    # Before it,
    # ADR-090: manifest_version 0.29.0 -> 0.30.0, 63 -> 65
    # entries, registering filing_index_probe_manifest and its v2
    # sec_live successor for the W2-C filing-index metadata probe.
    # Before it,
    # ADR-089: manifest_version 0.28.0 -> 0.29.0, 61 -> 63
    # entries, registering baseline_document_acquisition_manifest and its v2
    # sec_live successor for W2-B baseline filing-document acquisition.
    # Before it,
    # ADR-088: manifest_version 0.27.0 -> 0.28.0, 60 -> 61
    # entries, registering universe_baseline_carrier_manifest for the Stage
    # 00B firm-level baseline carrier (W2-A). Before it,
    # ADR-082: manifest_version 0.26.0 -> 0.27.0, 58 -> 60
    # entries, registering dera_fsds_acquisition_manifest (fixture replay)
    # and its v2 sec_live successor for DERA archive acquisition. Before it,
    # ADR-081: manifest_version 0.25.0 -> 0.26.0, 57 -> 58
    # entries, registering frame_dera_validation_manifest for the DERA FSDS
    # validation artifact. Before it,
    # ADR-078: manifest_version 0.24.0 -> 0.25.0, 56 -> 57
    # entries, registering edgar_index_acquisition_manifest_v2, the sec_live
    # successor manifest for the post-W0 live binding. Before it,
    # ADR-076: manifest_version 0.23.0 -> 0.24.0, 55 -> 56
    # entries, registering edgar_index_acquisition_manifest for the
    # fixture-replay index acquisition. Before it,
    # ADR-075: manifest_version 0.22.0 -> 0.23.0, 54 -> 55
    # entries, registering filer_frame_manifest for the FRAME builder's run
    # manifest. Before it,
    # ADR-073 (CR-0009): manifest_version 0.21.0 -> 0.22.0,
    # 51 -> 54 entries, registering the consolidation output and universe
    # schemas and the extraction_input_packet successor that carries
    # candidate_context. Before it,
    # ADR-071: manifest_version 0.20.0 -> 0.21.0, 50 -> 51
    # entries, registering the extraction_validation_decision_set successor that
    # carries the task kind and the Snapshot B pin. Before it,
    # ADR-068: manifest_version 0.19.0 -> 0.20.0, 49 -> 50
    # entries, registering the task_observation successor that adds
    # normalized_task. Before it, ADR-067: 0.18.0 -> 0.19.0, 48 -> 49
    # entries, registering the extraction_provider_client_contract_v3 successor.
    # Before it, ADR-057: 0.17.0 -> 0.18.0, 47 -> 48 entries,
    # registering the extraction_validation_decision_set successor. Before it,
    # ADR-052 (G6-V): manifest_version 0.16.0 -> 0.17.0, 46 -> 47
    # entries, registering product_candidate_availability_vocabulary alongside
    # every unchanged entry. The previous ADR-044 rebaseline (0.15.0 -> 0.16.0,
    # 45 -> 46) registered prompt_qualification_record, and the ADR-043 one
    # (0.14.0 -> 0.15.0, 42 -> 45) the two E-M successor contracts and the
    # execution outcome. In every case the released @0.1.0 schemas are
    # byte-identical; only the registry grew.
    "abc2dc247b4fa2e7dbbb2e68238b17cd187773294a8829747ce9375ebe08cc71"
)


def _released(kind):
    return tuple(e for e in RELEASED_EVALUATION_CONTRACTS if e.kind == kind)


def _generated_model_classes():
    """Every committed contract-stamped identity -> its class, package-wide."""
    classes = {}
    for _, module_name, _ in pkgutil.iter_modules(evaluation_pkg.__path__):
        module = importlib.import_module(
            f"dynamic_ai_products.evaluation.{module_name}")
        for obj in vars(module).values():
            if (inspect.isclass(obj) and hasattr(obj, "_contract_id")
                    and hasattr(obj, "model_json_schema")):
                cid = getattr(obj, "_contract_id", None)
                ver = getattr(obj, "_contract_version", None)
                if isinstance(cid, str) and isinstance(ver, str):
                    classes.setdefault((cid, ver), obj)
    return classes


def _entry_payload(**over):
    payload = {
        "contract_id": "evaluation_case", "contract_version": "0.1.0",
        "kind": "static_schema",
        "relative_path": "schemas/evaluation_case.schema.json",
        "expected_sha256": "a" * 64,
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def test_release_registry_sorted_unique_and_counts():
    keys = [(e.contract_id, e.contract_version) for e in RELEASED_EVALUATION_CONTRACTS]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    assert len(_released("static_schema")) == 9
    assert len(_released("generated_model")) == 34
    assert len(RELEASED_EVALUATION_CONTRACTS) == 43


def test_release_static_entries_hash_to_the_committed_files():
    for entry in _released("static_schema"):
        assert entry.relative_path is not None
        assert entry.relative_path.startswith("schemas/")
        path = ROOT / entry.relative_path
        assert path.is_file(), entry.relative_path
        assert sha256_bytes(path.read_bytes()) == entry.expected_sha256, (
            entry.contract_id, entry.contract_version)


def test_release_generated_entries_match_the_committed_models_exactly():
    classes = _generated_model_classes()
    released = {(e.contract_id, e.contract_version): e.expected_sha256
                for e in _released("generated_model")}
    # Set equality in BOTH directions: no new contract identity, no omission.
    assert set(released) == set(classes)
    for (cid, ver), expected in released.items():
        assert model_contract_hash(classes[(cid, ver)], cid, ver) == expected, (cid, ver)


def test_release_registry_agrees_with_every_runtime_anchor_table():
    static = {(e.contract_id, e.contract_version): (e.relative_path, e.expected_sha256)
              for e in _released("static_schema")}
    anchored = set()
    for contract in EVALUATION_SCHEMA_CONTRACTS:
        key = (contract.contract_id, contract.contract_version)
        assert static[key] == (contract.relative_path, contract.expected_sha256), key
        anchored.add(key)
    for key, (path, sha) in compat_mod._HISTORICAL_ROUTES.items():
        assert static[key] == (path, sha), key
        anchored.add(key)
    for schema_id, path, sha in vp_mod._STAGE_STATIC_ANCHORS.values():
        key = (schema_id, "0.1.0")
        assert static[key] == (path, sha), key
        anchored.add(key)
    for path, sha, _owner in pos_mod._ROLE_SCHEMA.values():
        schema_id = path.rsplit("/", 1)[1].removesuffix(".schema.json")
        key = (schema_id, "0.1.0")
        assert static[key] == (path, sha), key
        anchored.add(key)
    # Reverse direction: every released static entry is anchored by at least
    # one runtime authority table — the registry never invents a binding.
    assert anchored == set(static)


def test_release_entry_static_discriminant_rules():
    ReleasedContractBinding.model_validate(_entry_payload())
    with pytest.raises(PydanticValidationError, match="requires relative_path"):
        ReleasedContractBinding.model_validate(_entry_payload(relative_path=...))
    for bad_path in ("", "  ", "docs/x.schema.json", "/schemas/x.schema.json",
                     "schemas/../x.schema.json", "schemas\\x.schema.json",
                     "schemas/"):
        with pytest.raises(PydanticValidationError):
            ReleasedContractBinding.model_validate(
                _entry_payload(relative_path=bad_path))


def test_release_entry_generated_discriminant_rules():
    ReleasedContractBinding.model_validate(
        _entry_payload(kind="generated_model", relative_path=...))
    with pytest.raises(PydanticValidationError, match="must omit relative_path"):
        ReleasedContractBinding.model_validate(
            _entry_payload(kind="generated_model"))
    with pytest.raises(PydanticValidationError, match="must not be explicit JSON null"):
        ReleasedContractBinding.model_validate(
            _entry_payload(kind="generated_model", relative_path=None))
    dumped = ReleasedContractBinding.model_validate(
        _entry_payload(kind="generated_model", relative_path=...)
    ).model_dump(mode="json", exclude_unset=True)
    assert "relative_path" not in dumped


@pytest.mark.parametrize("bad_sha", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, ""])
def test_release_entry_sha_must_be_64_lower_hex(bad_sha):
    with pytest.raises(PydanticValidationError):
        ReleasedContractBinding.model_validate(_entry_payload(expected_sha256=bad_sha))


def test_release_entry_model_is_never_contract_stamped():
    assert not issubclass(ReleasedContractBinding, ContractStampedModel)
    assert not hasattr(ReleasedContractBinding, "_contract_id")
    # No 35th generated identity: the binding model itself is absent from the
    # committed contract-stamped inventory and from the release tuple.
    assert ("released_contract_binding", "0.1.0") not in _generated_model_classes()
    assert all(e.contract_id != "released_contract_binding"
               for e in RELEASED_EVALUATION_CONTRACTS)


def test_release_hashes_are_reviewed_source_literals():
    source = Path(registry.__file__).read_text()
    tree = ast.parse(source)
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", None) == "RELEASED_EVALUATION_CONTRACTS")
    calls = [n for n in ast.walk(assignment.value) if isinstance(n, ast.Call)]
    sha_keywords = [kw for call in calls for kw in call.keywords
                    if kw.arg == "expected_sha256"]
    assert len(sha_keywords) == 43
    for keyword in sha_keywords:
        assert isinstance(keyword.value, ast.Constant), ast.dump(keyword.value)
        assert isinstance(keyword.value.value, str)
        assert len(keyword.value.value) == 64


def test_schema_version_manifest_untouched_by_release_binding():
    manifest_path = ROOT / "schemas" / "schema_version_manifest.json"
    assert sha256_bytes(manifest_path.read_bytes()) == SCHEMA_VERSION_MANIFEST_SHA256


def test_universe_manifest_v2_stays_compat_read_only():
    contract = next(
        c for c in EVALUATION_SCHEMA_CONTRACTS
        if (c.contract_id, c.contract_version) == ("universe_run_manifest", "0.2.0"))
    assert contract.mode == "compat_read"
    released = next(
        e for e in _released("static_schema")
        if (e.contract_id, e.contract_version) == ("universe_run_manifest", "0.2.0"))
    assert released.expected_sha256 == contract.expected_sha256
    with pytest.raises(ReadOnlyContractError):
        load_schema("universe_run_manifest", "0.2.0", purpose="write")


def test_release_binding_public_surface():
    for name in ("RELEASED_EVALUATION_CONTRACTS", "ReleasedContractBinding"):
        assert name in evaluation_pkg.__all__
        assert evaluation_pkg.__all__.count(name) == 1
        assert getattr(evaluation_pkg, name) is getattr(registry, name)
    assert len(evaluation_pkg.__all__) == 579
    assert evaluation_pkg.__all__ == sorted(evaluation_pkg.__all__)
    assert len(set(evaluation_pkg.__all__)) == len(evaluation_pkg.__all__)


# --- ADR-043 (E-M): the three new schemas agree with their registry entries ---
#
# Four facts have to line up for one contract, and each of them lives somewhere
# different: the file on disk, its key in schema_version_manifest.json, the
# ``contract`` const inside the file, and the ``schema_version`` const beside it.
# A disagreement between any two is invisible at the point of use -- a document
# validates against a schema that the registry believes is a different version,
# or a successor is registered under the identity of the contract it succeeds.
# So the agreement is asserted directly rather than assumed from the naming.
#
# The repository holds two spellings for a versioned successor file: the older
# ``name.vN.schema.json`` and the underscore ``name_vN.schema.json`` used here.
# Both derive the same manifest key, which is what the registry actually reads;
# the naming difference is informational and is deliberately not "fixed" by
# renaming a file that other artifacts already reference.

EM_SCHEMA_KEYS = (
    "extraction_provider_client_contract_v2",
    "live_call_authorization_v2",
    "extraction_execution_outcome",
    # ADR-044 (G2). Not a successor: the key carries no ``_vN`` suffix, so the
    # contract identity it must declare is the bare key at its registered
    # version. The same four-way agreement is asserted for it.
    "prompt_qualification_record",
)


def _schema_version_manifest() -> dict:
    return json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json").read_text(encoding="utf-8")
    )["schemas"]


@pytest.mark.parametrize("key", EM_SCHEMA_KEYS)
def test_each_new_schema_agrees_with_its_manifest_key_contract_and_version(key):
    path = ROOT / "schemas" / f"{key}.schema.json"
    assert path.exists(), f"the approved underscore filename is missing: {path.name}"

    schema = json.loads(path.read_text(encoding="utf-8"))
    manifest = _schema_version_manifest()

    # The key the registry reads is the filename stem.
    assert key in manifest, f"{key} is not registered in schema_version_manifest.json"
    assert schema["$id"] == path.name

    declared_version = schema["properties"]["schema_version"]["const"]
    declared_contract = schema["properties"]["contract"]["const"]
    registered_version = manifest[key]

    # 1. The registry's version is the schema's own version.
    assert registered_version == declared_version

    # 2. The contract identity is the un-suffixed key at that same version, so a
    #    successor can never register under the identity it succeeds.
    base = re.sub(r"_v\d+$", "", key)
    assert declared_contract == f"{base}@{registered_version}"


@pytest.mark.parametrize("key", EM_SCHEMA_KEYS)
def test_no_dot_versioned_duplicate_shadows_an_approved_underscore_file(key):
    """One file per contract. A second spelling would derive the same manifest
    key and leave two files racing for one registry entry."""
    base = re.sub(r"_v\d+$", "", key)
    suffix = key[len(base) :]
    if not suffix:
        return
    twin = ROOT / "schemas" / f"{base}.v{suffix.lstrip('_v')}.schema.json"
    assert not twin.exists(), f"a dot-versioned duplicate exists alongside {key}"


@pytest.mark.parametrize(
    "released, expected_contract",
    [
        ("extraction_provider_client_contract", "extraction_provider_client_contract@0.1.0"),
        ("live_call_authorization", "live_call_authorization@0.1.0"),
    ],
)
def test_the_released_predecessors_keep_their_own_identity_and_version(
    released, expected_contract
):
    """The successors sit beside them; nothing about @0.1.0 moves."""
    schema = json.loads(
        (ROOT / "schemas" / f"{released}.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["contract"]["const"] == expected_contract
    assert _schema_version_manifest()[released] == "0.1.0"
    assert schema["properties"]["schema_version"]["const"] == "0.1.0"


def test_every_manifest_key_still_resolves_to_exactly_one_schema_file():
    """Registry-wide, not just for the three new entries.

    Both filename spellings are accepted here, because that divergence predates
    this increment; what must hold is that each key resolves to one file and no
    key resolves to none.
    """
    manifest = _schema_version_manifest()
    for key in manifest:
        base = re.sub(r"_v(\d+)$", "", key)
        suffix = key[len(base) :]
        candidates = [ROOT / "schemas" / f"{key}.schema.json"]
        if suffix:
            candidates.append(ROOT / "schemas" / f"{base}.v{suffix[2:]}.schema.json")
        present = [candidate for candidate in candidates if candidate.exists()]
        assert len(present) == 1, f"{key} resolves to {len(present)} files: {present}"
