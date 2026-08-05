"""The canonical governance materializer (ADR-049, G4-1).

Three separable claims are proved here, and they are kept apart on purpose.

**The builder is deterministic and read-only.** Not pure -- it opens three files
under ``repo_root``, because the prompt, SPEC-024 and change-request digests are
bytes rather than derivations. What is asserted is the narrower and true thing:
nothing is written, no clock or environment is read, no socket is opened, and the
repository tree is byte-identical before and after.

**The bundle is sealed.** A caller that mutates what it passed in, or what it got
back, cannot change the bytes that reach disk.

**The writer is fail-closed on two different roots.** ``governance_artifact_root``
must already exist and be empty; a run root must not exist at all. This module
never accepts a run root, and the tests state the difference rather than assuming
a reader knows it.

Nothing here uses a real project ID, resolves ADC, builds a client, or performs a
provider or network call. The synthetic project below is the same one every other
extraction test uses.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from dynamic_ai_products.extraction import governance_materializer as gm
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.governance_materializer import (
    GOVERNANCE_REFERENCES,
    GovernanceBuild,
    build_governance_records,
    materialize_governance_records,
)
from dynamic_ai_products.extraction.manifests import (
    AUTHORIZATION_V2_PROPERTIES,
    ENABLEMENT_PROPERTIES,
    QUALIFICATION_PROPERTIES,
    wall_clock_floor_for_cap,
)
from dynamic_ai_products.extraction.prompt_qualification import (
    PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.routing_contract import (
    ROUTING_CONTRACT_ID,
    derive_routing_contract,
)
from dynamic_ai_products.providers.client_contract import build_client_contract
from dynamic_ai_products.providers.client_contract_v2 import build_client_contract_v2

_BUILD_NAMES = (
    "qualification",
    "prompt_qualification",
    "enablement",
    "authorization",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT = "my-research-project"
STAGE = "product_extraction"
COMPANY = "CIK0001404655"
CUTOFF = "2025-02-12"
CODE_COMMIT = "a5e2f3198554d9be48a8723b6a1b95cd22a0fe3f"
RUN_CREATED_AT = "2026-08-03T00:00:00Z"


def _contract():
    return build_client_contract_v2(vertex_project=PROJECT)


def _budget(**overrides):
    base = {
        "budget_max_records": 1,
        "budget_max_external_requests": 4,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": wall_clock_floor_for_cap(3),
    }
    base.update(overrides)
    return base


def _inputs(**overrides):
    base = {
        "client_contract": _contract(),
        "repo_root": REPO_ROOT,
        "stage": STAGE,
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "corpus_scope": "sec_only_partial",
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
        "rollout_state": "live_dev",
        "deployment_environment_id": "dev-local",
        "budget": _budget(),
        "circuit_breaker_max_consecutive_failures": 1,
        "identities": {
            "authorization_id": "auth-0001",
            "enablement_id": "enab-0001",
            "qualification_id": "qual-0001",
            "prompt_qualification_id": "pq-0001",
        },
        "people": {
            "authorized_by": "methodology-owner",
            "approver": "methodology-owner",
            "reviewer": "methodology-owner",
        },
        "window": {
            "authorization_effective_at": "2026-07-01T00:00:00Z",
            "authorization_expires_at": "2027-07-01T00:00:00Z",
            "enablement_effective_at": "2026-07-01T00:00:00Z",
            "enablement_expires_at": "2027-07-01T00:00:00Z",
        },
        "qualified_at": "2026-07-01T00:00:00Z",
        "decided_at": "2026-07-01T00:00:00Z",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini_v2",
        "adapter_version": "0.2.0",
    }
    base.update(overrides)
    return base


def _build(**overrides) -> GovernanceBuild:
    return build_governance_records(**_inputs(**overrides))


def _attempt_root(tmp_path: Path, name: str = "attempt-0001") -> Path:
    """Create the root the way the runbook does: explicitly, and empty."""
    root = tmp_path / "governance-container" / name
    root.mkdir(parents=True)
    return root


def _files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# --- the builder: deterministic, read-only ------------------------------------


def test_a_synthetic_project_produces_a_complete_four_record_build():
    build = _build()
    assert [name for name, _ in build.payloads] == [
        "qualification",
        "prompt_qualification",
        "enablement",
        "authorization",
    ]
    for name in GOVERNANCE_REFERENCES:
        assert len(build.digest(name)) == 64
        assert build.pin(name)["reference"] == GOVERNANCE_REFERENCES[name]


def test_the_builder_is_deterministic():
    first, second = _build(), _build()
    assert first.payloads == second.payloads


def test_the_builder_writes_nothing_and_leaves_the_repository_byte_identical():
    """Read-only, asserted by measurement rather than by docstring.

    The repository tree is hashed before and after. This is the honest form of
    the claim: the builder *does* read three files, and reading is all it does.
    """
    def snapshot() -> dict[str, str]:
        return {
            str(p.relative_to(REPO_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (REPO_ROOT / "prompts").rglob("*")
            if p.is_file()
        } | {
            str(p.relative_to(REPO_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (REPO_ROOT / "data").rglob("*")
            if p.is_file()
        }

    before = snapshot()
    _build()
    assert snapshot() == before


def test_the_builder_reaches_no_clock_network_environment_or_credential():
    """An AST sweep of the whole module: imports and attribute chains, not prose.

    A raw-text scan was tried first and was wrong twice over -- it matched the
    docstring's own promise not to open a socket, and it matched the legitimate
    field ``budget_max_external_requests``. Names are what matter, so names are
    what is examined.
    """
    tree = ast.parse(Path(gm.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
    assert imported.isdisjoint(
        {
            "socket",
            "urllib",
            "httpx",
            "requests",
            "google",
            "subprocess",
            "time",
            "random",
            "secrets",
            "uuid",
            "providers",
        }
    ), sorted(imported)
    assert attributes.isdisjoint({"now", "today", "environ", "getenv", "putenv", "urlopen"})


def test_the_module_never_binds_a_run_root():
    """``run_root`` is the other root, and this module has no concept of it.

    Checked as identifiers, not as text: the module's prose has to be able to
    explain the distinction between the two roots, and an earlier text-matching
    version of this test failed on its own docstring for saying so.
    """
    tree = ast.parse(Path(gm.__file__).read_text(encoding="utf-8"))
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name):
            bound.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg:
            bound.add(node.arg)
    assert "run_root" not in bound
    assert "run_root" not in inspect.signature(build_governance_records).parameters
    assert "run_root" not in inspect.signature(materialize_governance_records).parameters


@pytest.mark.parametrize(
    "reference",
    [
        "prompts/extraction/product_discovery_schema_v3.md",
        "specs/SPEC-024-run-versioning-and-comparison.md",
        "evals/change_requests/CR-0003-product-discovery-schema-v3-bootstrap-qualification.md",
    ],
)
def test_each_cited_document_actually_reaches_the_record(reference, tmp_path):
    """The three digests are bytes, so a changed byte must change the record.

    Proved by copying the repository's own file into a temporary tree with one
    byte appended, and building against that tree. The repository itself is never
    touched.
    """
    fake_root = tmp_path / "repo"
    for path in (
        REPO_ROOT / "prompts",
        REPO_ROOT / "specs",
        REPO_ROOT / "evals",
        REPO_ROOT / "schemas",
    ):
        target = fake_root / path.name
        target.mkdir(parents=True, exist_ok=True)
        for source in path.rglob("*"):
            if source.is_file():
                destination = target / source.relative_to(path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
    baseline = build_governance_records(**_inputs(repo_root=fake_root))
    altered = fake_root / reference
    altered.write_bytes(altered.read_bytes() + b"\n")
    changed = build_governance_records(**_inputs(repo_root=fake_root))
    assert changed.digest("prompt_qualification") != baseline.digest("prompt_qualification")


# --- record shape --------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("qualification", QUALIFICATION_PROPERTIES),
        ("enablement", ENABLEMENT_PROPERTIES),
        ("authorization", AUTHORIZATION_V2_PROPERTIES),
        ("prompt_qualification", PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP),
    ],
)
def test_each_record_carries_exactly_its_released_property_set(name, expected):
    assert set(_build().record(name)) == set(expected)


def test_the_pin_graph_is_the_one_the_runner_walks():
    """Authorization pins enablement; enablement pins the other two as siblings.

    The sibling relationship is the part that is easy to get wrong: the prompt
    qualification does not hang off the adapter qualification, and a chain that
    put it there would fail at F0 with nothing to explain why.
    """
    build = _build()
    authorization = build.record("authorization")
    enablement = build.record("enablement")
    assert authorization["adapter_enablement_record_reference"] == (
        GOVERNANCE_REFERENCES["enablement"]
    )
    assert authorization["adapter_enablement_record_sha256"] == build.digest("enablement")
    assert enablement["adapter_qualification_record_sha256"] == build.digest(
        "qualification"
    )
    assert enablement["prompt_qualification_sha256"] == build.digest(
        "prompt_qualification"
    )
    # The qualification pins nothing: it is a leaf.
    assert not [k for k in build.record("qualification") if k.endswith("_sha256")
                and k not in ("execution_contract_sha256", "stage_output_contract_sha256")]


def test_the_code_owned_fields_come_from_code_and_not_from_the_caller():
    """ADR-047's lesson: an authorization that echoed its author is no evidence."""
    build = _build()
    authorization = build.record("authorization")
    assert authorization["budget_meter_identity"] == (
        "dynamic_ai_products.extraction.budget_session"
    )
    assert authorization["budget_policy_version"] == "budget_policy_v1"
    assert build.record("enablement")["routing_contract_id"] == ROUTING_CONTRACT_ID
    assert build.record("enablement")["routing_contract_sha256"] == (
        derive_routing_contract(client_contract=_contract())["routing_contract_sha256"]
    )
    for field in ("budget_meter_identity", "budget_policy_version", "routing_contract_id"):
        with pytest.raises(ExtractionError) as caught:
            _build(**{field: "anything"})
        assert caught.value.reason_code == "governance_input_invalid"


def test_the_endpoint_allowlist_is_the_two_operation_urls_in_a_fixed_order():
    endpoints = _contract()["operation_endpoints"]
    expected = [endpoints["count_tokens"], endpoints["generate_content"]]
    build = _build()
    assert build.record("authorization")["endpoint_allowlist"] == expected
    assert build.record("enablement")["endpoint_allowlist"] == expected


def test_a_different_synthetic_project_changes_the_contract_and_route_digests():
    other = build_client_contract_v2(vertex_project="another-real-project")
    a, b = _build(), _build(client_contract=other)
    assert a.digest("enablement") != b.digest("enablement")
    assert a.digest("authorization") != b.digest("authorization")


# --- input refusals ------------------------------------------------------------


def test_an_unknown_keyword_is_refused_rather_than_ignored():
    with pytest.raises(ExtractionError) as caught:
        _build(budgets=_budget())
    assert caught.value.reason_code == "governance_input_invalid"


@pytest.mark.parametrize(
    ("group", "mutate"),
    [
        pytest.param("budget", lambda d: d.pop("budget_max_records"), id="budget-missing"),
        pytest.param("budget", lambda d: d.update(extra=1), id="budget-extra"),
        pytest.param("identities", lambda d: d.pop("enablement_id"), id="identities-missing"),
        pytest.param("identities", lambda d: d.update(extra="x"), id="identities-extra"),
        pytest.param("people", lambda d: d.pop("reviewer"), id="people-missing"),
        pytest.param("window", lambda d: d.pop("enablement_expires_at"), id="window-missing"),
        pytest.param("window", lambda d: d.update(extra="x"), id="window-extra"),
    ],
)
def test_each_grouped_input_must_carry_exactly_its_keys(group, mutate):
    values = _inputs()[group]
    mutate(values)
    with pytest.raises(ExtractionError) as caught:
        _build(**{group: values})
    assert caught.value.reason_code == "governance_input_invalid"


@pytest.mark.parametrize("field", list(_budget()))
def test_a_non_positive_budget_ceiling_is_refused(field):
    with pytest.raises(ExtractionError) as caught:
        _build(budget=_budget(**{field: 0}))
    assert caught.value.reason_code == "governance_input_invalid"


def test_an_unknown_rollout_state_is_refused():
    with pytest.raises(ExtractionError) as caught:
        _build(rollout_state="whenever")
    assert caught.value.reason_code == "governance_input_invalid"


def test_a_v1_client_contract_is_refused_before_anything_is_built():
    with pytest.raises(ExtractionError) as caught:
        _build(client_contract=build_client_contract(vertex_project=PROJECT))
    assert caught.value.reason_code == "client_contract_invalid"


# --- the sealed bundle ---------------------------------------------------------


def test_the_bundle_is_frozen():
    build = _build()
    with pytest.raises(FrozenInstanceError):
        build.payloads = ()
    with pytest.raises(FrozenInstanceError):
        build.context.stage = "other"


def test_mutating_the_contract_after_building_cannot_change_what_is_written(tmp_path):
    """The seal, proved end to end.

    The caller keeps a handle on the mapping it passed in and mutates it after
    the build. If the bundle held that mapping instead of bytes, the digest the
    validators computed and the bytes on disk could disagree.
    """
    contract = _contract()
    build = _build(client_contract=contract)
    expected = build.digest("authorization")
    contract["retry_policy_version"] = "mutated_after_build"
    root = _attempt_root(tmp_path)
    pin = materialize_governance_records(build, attempt_root=root)
    assert pin["sha256"] == expected
    written = (root / GOVERNANCE_REFERENCES["authorization"]).read_bytes()
    assert sha256_bytes(written) == expected


def test_each_record_call_returns_an_independent_mapping():
    build = _build()
    first = build.record("authorization")
    first["stage"] = "mutated"
    assert build.record("authorization")["stage"] == STAGE


def test_the_bundle_payload_bytes_are_canonical():
    build = _build()
    for name in GOVERNANCE_REFERENCES:
        assert build.payload(name) == canonical_json_bytes(build.record(name))


def test_an_unknown_record_name_is_refused():
    with pytest.raises(ExtractionError) as caught:
        _build().payload("nonexistent")
    assert caught.value.reason_code == "governance_input_invalid"


def test_the_writer_takes_only_the_bundle_and_the_governance_root():
    """The drift gate.

    A third parameter would be a second place to pass ``stage`` or
    ``run_created_at``, and the value used to build a record could then differ
    from the value used to validate it. There is no such place.
    """
    parameters = inspect.signature(materialize_governance_records).parameters
    assert list(parameters) == ["build", "attempt_root"]


def test_the_writer_refuses_anything_that_is_not_a_sealed_build(tmp_path):
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(  # type: ignore[arg-type]
            {"authorization": {}}, attempt_root=_attempt_root(tmp_path)
        )
    assert caught.value.reason_code == "governance_input_invalid"


# --- the writer: the governance attempt root -----------------------------------


def test_a_conforming_attempt_root_receives_exactly_four_records(tmp_path):
    root = _attempt_root(tmp_path)
    build = _build()
    pin = materialize_governance_records(build, attempt_root=root)
    assert _files(root) == sorted(GOVERNANCE_REFERENCES.values())
    assert pin == build.pin("authorization")


def test_the_returned_pin_is_not_a_fifth_artifact(tmp_path):
    """It is a mapping handed to the run, not a file.

    Whatever the pin's reference names, only the four records exist on disk.
    """
    root = _attempt_root(tmp_path)
    pin = materialize_governance_records(_build(), attempt_root=root)
    assert set(pin) == {"reference", "sha256"}
    assert len(_files(root)) == 4


def test_a_nonexistent_attempt_root_is_refused_rather_than_created(tmp_path):
    """Creating the root is a runbook step (G4-0 R7), not a side effect.

    If materialization created it, "who made this root and under which
    container" would have no answer outside the filesystem's mtime.
    """
    missing = tmp_path / "container" / "never-created"
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=missing)
    assert caught.value.reason_code == "governance_root_invalid"
    # The message, not only the code. ``not is_dir()`` would also refuse a
    # missing path, so asserting the code alone would still pass with the
    # existence branch deleted and the operator would lose the one sentence that
    # says whose job creating the root is.
    assert "does not exist" in str(caught.value)
    assert "explicit runbook step" in str(caught.value)
    assert not missing.exists()


def test_a_file_as_attempt_root_is_refused(tmp_path):
    """The message matters here too.

    Without the directory branch, ``os.listdir`` on a file raises ``OSError`` and
    the unreadable-root branch produces the same reason code -- so asserting the
    code alone would still pass and the operator would be told the root is
    unreadable rather than that it is not a directory.
    """
    target = tmp_path / "not-a-directory"
    target.write_text("")
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=target)
    assert caught.value.reason_code == "governance_root_invalid"
    assert "must be a directory" in str(caught.value)


def test_a_symlinked_attempt_root_is_refused(tmp_path):
    real = _attempt_root(tmp_path)
    link = tmp_path / "link-root"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=link)
    assert caught.value.reason_code == "governance_root_invalid"
    assert _files(real) == []


def test_the_component_guard_refuses_a_symlink_between_the_root_and_a_target():
    """The guarantee ``_safe_target`` does not give, tested where it can fire.

    Measured on the shared loader: an intermediate directory symlink that stays
    inside the root passes both its symlink check and a real read, because only
    the final component is tested and ``resolve()`` silently follows the rest. A
    reader with pinned digests can live with that; a writer cannot, because the
    record would land somewhere other than where the pin says it is.

    The guard is exercised directly because it cannot fire through the public
    entry point: emptiness is checked first, and a pre-existing symlink inside
    the root makes the root non-empty. It stays as defence in depth over the
    ``mkdir`` that ``write_artifact`` performs afterwards.
    """
    import tempfile

    root = Path(tempfile.mkdtemp())
    (root / "real").mkdir()
    (root / "governance").symlink_to(root / "real", target_is_directory=True)
    with pytest.raises(ExtractionError) as caught:
        gm._require_no_symlink_component(
            root, GOVERNANCE_REFERENCES["authorization"]
        )
    assert caught.value.reason_code == "governance_root_invalid"


def test_a_symlink_inside_the_root_is_refused_by_the_emptiness_rule_first(tmp_path):
    """Two rules, one outcome, and the honest reason code.

    A symlink placed inside the attempt root beforehand is refused -- but as
    ``destination_exists``, because emptiness is the first gate. Asserting
    ``governance_root_invalid`` here would describe an ordering the code does
    not have.
    """
    root = _attempt_root(tmp_path)
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    (root / "governance").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=root)
    assert caught.value.reason_code == "destination_exists"
    assert _files(elsewhere) == []


def test_symlinks_above_the_attempt_root_are_the_runbooks_responsibility(tmp_path):
    """A declared limit, recorded rather than quietly left out.

    The materializer refuses a symlinked attempt root and symlinked components
    beneath it. It does **not** walk the root's ancestry, and refusing every
    symlinked ancestor would reject ordinary platform paths -- measured on this
    machine, ``/tmp`` is itself a symlink to ``private/tmp``. Choosing and
    creating the attempt root is G4-0 R7's explicit operator step, and that is
    where ancestry is accounted for.
    """
    assert Path("/tmp").is_symlink()
    container = tmp_path / "real-container"
    container.mkdir()
    root = container / "attempt-0001"
    root.mkdir()
    link = tmp_path / "linked-container"
    link.symlink_to(container, target_is_directory=True)
    # Reached through a symlinked ancestor, the root itself is not a symlink and
    # is accepted. This is the limit, and it is asserted so it cannot be
    # mistaken for a guarantee.
    assert materialize_governance_records(
        _build(), attempt_root=link / "attempt-0001"
    )["sha256"]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(".gitkeep", id="dotfile"),
        pytest.param("stray.json", id="regular-file"),
        pytest.param("governance/adapter_qualification_record.json", id="partial-attempt"),
    ],
)
def test_a_non_empty_attempt_root_is_refused(tmp_path, entry):
    """Emptiness is total, not "the four targets are absent".

    ``os.listdir`` never returns ``.`` or ``..`` and does return dotfiles, so a
    stray ``.gitkeep`` disqualifies a root -- which is why a tracked container
    keeps its ``.gitkeep`` beside the attempt roots and never inside one.
    """
    root = _attempt_root(tmp_path)
    target = root / entry
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}")
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=root)
    assert caught.value.reason_code == "destination_exists"
    assert os.listdir(root) != []


def test_a_second_materialization_into_the_same_root_is_refused(tmp_path):
    """Why a retry needs a new attempt root, stated as behaviour.

    The first attempt succeeded, so the root is populated; the second is refused
    before a single byte is written, and the first attempt's four records are
    untouched.
    """
    root = _attempt_root(tmp_path)
    first = materialize_governance_records(_build(), attempt_root=root)
    before = {name: (root / ref).read_bytes() for name, ref in GOVERNANCE_REFERENCES.items()}
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=root)
    assert caught.value.reason_code == "destination_exists"
    assert {name: (root / ref).read_bytes() for name, ref in GOVERNANCE_REFERENCES.items()} == before
    assert materialize_governance_records(_build(), attempt_root=_attempt_root(tmp_path, "attempt-0002")) == first


# --- partial-failure semantics --------------------------------------------------


@pytest.mark.parametrize(
    ("fail_on", "expected_remaining"),
    [
        pytest.param("qualification", 0, id="first-write-fails"),
        pytest.param("prompt_qualification", 1, id="second-write-fails"),
        pytest.param("enablement", 2, id="third-write-fails"),
        pytest.param("authorization", 3, id="fourth-write-fails"),
    ],
)
def test_a_failed_write_leaves_the_earlier_records_in_place(
    tmp_path, monkeypatch, fail_on, expected_remaining
):
    """``write_bytes_once`` is not a transaction, and this states what that means.

    Each earlier write already succeeded and stays. Nothing later is written, and
    no authorization pin is returned -- so a partial root can never be handed to
    a run.
    """
    root = _attempt_root(tmp_path)
    real = gm.write_artifact
    failing_reference = GOVERNANCE_REFERENCES[fail_on]

    def flaky(target_root, reference, data):
        if reference == failing_reference:
            raise ExtractionError("disk said no", reason_code="write_error")
        return real(target_root, reference, data)

    monkeypatch.setattr(gm, "write_artifact", flaky)
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=root)
    assert caught.value.reason_code == "write_error"
    assert len(_files(root)) == expected_remaining


def test_a_partial_root_cannot_be_reused_for_the_retry(tmp_path, monkeypatch):
    """The two rules meet here.

    A failed attempt leaves records behind; the emptiness rule then disqualifies
    that root. The retry must use a new one, and does succeed there.
    """
    first = _attempt_root(tmp_path, "attempt-0001")
    real = gm.write_artifact

    def flaky(target_root, reference, data):
        if reference == GOVERNANCE_REFERENCES["enablement"]:
            raise ExtractionError("disk said no", reason_code="write_error")
        return real(target_root, reference, data)

    monkeypatch.setattr(gm, "write_artifact", flaky)
    with pytest.raises(ExtractionError):
        materialize_governance_records(_build(), attempt_root=first)
    assert len(_files(first)) == 2

    monkeypatch.setattr(gm, "write_artifact", real)
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=first)
    assert caught.value.reason_code == "destination_exists"

    second = _attempt_root(tmp_path, "attempt-0002")
    assert materialize_governance_records(_build(), attempt_root=second)["sha256"]


# --- post-write validation ------------------------------------------------------


def test_the_written_chain_is_validated_from_disk_not_from_the_bundle(tmp_path):
    """What is checked is what was persisted.

    The four records are re-hydrated through the shared loader before any
    validator sees them, so a divergence between the bundle and the bytes would
    surface as a digest refusal rather than passing unnoticed.
    """
    root = _attempt_root(tmp_path)
    materialize_governance_records(_build(), attempt_root=root)
    for name, reference in GOVERNANCE_REFERENCES.items():
        on_disk = json.loads((root / reference).read_text())
        assert on_disk == _build().record(name)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param(
            {"decided_at": "2026-09-01T00:00:00Z"},
            "prompt_qualification_invalid",
            id="P14-decision-postdates-the-run",
        ),
        pytest.param(
            {"run_created_at": "2028-01-01T00:00:00Z"},
            "governance_record_not_effective",
            id="run-instant-outside-the-enablement-window",
        ),
        pytest.param(
            {"budget": _budget(budget_max_wall_clock_seconds=10)},
            "budget_insufficient",
            id="wall-clock-below-the-cap-floor",
        ),
        pytest.param(
            {"budget": _budget(budget_max_external_requests=1)},
            "budget_insufficient",
            id="external-requests-below-two",
        ),
        pytest.param(
            {"budget": _budget(budget_max_output_tokens=1)},
            "budget_insufficient",
            id="output-tokens-below-the-declared-maximum",
        ),
        pytest.param(
            {
                "window": {
                    "authorization_effective_at": "2026-06-01T00:00:00Z",
                    "authorization_expires_at": "2027-07-01T00:00:00Z",
                    "enablement_effective_at": "2026-07-01T00:00:00Z",
                    "enablement_expires_at": "2027-07-01T00:00:00Z",
                }
            },
            "governance_record_not_effective",
            id="authorization-outlives-its-enablement",
        ),
    ],
)
def test_a_chain_that_the_runner_would_refuse_is_refused_here(tmp_path, overrides, reason):
    """The post-write pass is the eight checks F0 and the pre-mkdir band run.

    Each case below fails a different one of them, which is how the suite proves
    that a single ``validate_governance_chain_v2`` call would not have been
    enough -- the first case is P14, which that validator never sees.
    """
    root = _attempt_root(tmp_path)
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(**overrides), attempt_root=root)
    assert caught.value.reason_code == reason


def test_a_run_instant_after_the_decision_is_accepted_because_nothing_pins_it(tmp_path):
    """The honest limit of ``run_created_at``.

    P14 checks ``decided_at <= run_created_at`` and nothing more; no record
    stores a materialization timestamp, so a later instant inside both windows
    passes. Keeping the same instant for G5 is a runbook rule, not something the
    runtime can enforce, and pretending otherwise would be a false claim.
    """
    build = _build(run_created_at="2026-12-01T00:00:00Z")
    assert materialize_governance_records(build, attempt_root=_attempt_root(tmp_path))


def test_the_meter_identity_is_not_taken_from_the_bundle(tmp_path):
    """ADR-047 again: the two sides of the comparison come from different places.

    The authorization's declared meter identity is code-owned, and the value it
    is checked against is read from the same constants rather than from anything
    the caller could reach -- so the check cannot become a comparison of the
    artifact with itself.
    """
    source = Path(gm.__file__).read_text(encoding="utf-8")
    assert "meter_identity=CANONICAL_BUDGET_METER_IDENTITY" not in source
    assert '"meter_identity": CANONICAL_BUDGET_METER_IDENTITY' in source
    assert "expected_budget_policy_version=BUDGET_POLICY_VERSION" in source


def test_a_materialized_chain_is_accepted_by_the_v2_route_at_f0(tmp_path):
    """The handoff, proved rather than asserted.

    The two roots are distinct by construction: the governance root exists and is
    full, the run root does not exist at all. The run is driven far enough to
    prove F0 hydrated and accepted all four records, then stops on the first
    thing this increment does not provide -- a real packet input.
    """
    from dynamic_ai_products.extraction.run_extraction import run_extraction_stage_v2

    governance_root = _attempt_root(tmp_path)
    pin = materialize_governance_records(_build(), attempt_root=governance_root)
    run_root = tmp_path / "run"
    assert not run_root.exists()

    with pytest.raises(ExtractionError) as caught:
        run_extraction_stage_v2(
            run_root=run_root,
            repo_root=REPO_ROOT,
            stage=STAGE,
            company_id=COMPANY,
            observation_cutoff_date=CUTOFF,
            passages=[],
            document_publication_dates={},
            coverage_artifact={},
            source_snapshot_manifest={},
            code_commit=CODE_COMMIT,
            run_created_at=RUN_CREATED_AT,
            extraction_run_id="ext-0001",
            prediction_run_id="pred-0001",
            evidence_binding={},
            schema_root=str(REPO_ROOT / "schemas"),
            provider=object(),
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    # Whatever stops it, it is not a governance failure: the chain loaded.
    assert caught.value.reason_code not in {
        "authorization_chain_broken",
        "governance_record_not_effective",
        "authorization_scope_mismatch",
        "prompt_qualification_invalid",
        "prompt_qualification_mismatch",
        "routing_contract_mismatch",
        "retry_policy_version_mismatch",
        "rate_limit_policy_version_mismatch",
        "governance_root_required",
    }


def test_the_governance_root_and_a_run_root_are_never_the_same_path(tmp_path):
    """The two-root rule, as behaviour.

    Handing the populated governance root to a run as its output root is refused
    by ``_require_absent_run_root`` before any extraction artifact is written,
    and the four governance records survive untouched.
    """
    from dynamic_ai_products.extraction.run_extraction import _require_absent_run_root

    governance_root = _attempt_root(tmp_path)
    materialize_governance_records(_build(), attempt_root=governance_root)
    with pytest.raises(ExtractionError) as caught:
        _require_absent_run_root(governance_root)
    assert caught.value.reason_code == "run_root_exists"
    assert len(_files(governance_root)) == 4


def test_a_drifted_policy_version_from_the_builder_is_caught_after_writing(
    tmp_path, monkeypatch
):
    """Why ``validate_provider_policy_versions`` is in the post-write pass.

    A chain this module builds can never trip it on its own: both sides are read
    from one contract, so they agree by construction. The check exists for a
    regression in the builder, and that is what is simulated here -- the record
    is written with a policy version this build does not implement, and the
    post-write pass refuses it.
    """
    real = gm._authorization_record

    def drifted(**kwargs):
        record = real(**kwargs)
        record["retry_policy_version"] = "retry_policy_v9"
        return record

    monkeypatch.setattr(gm, "_authorization_record", drifted)
    build = _build()
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(build, attempt_root=_attempt_root(tmp_path))
    assert caught.value.reason_code == "retry_policy_version_mismatch"


def test_a_drifted_routing_digest_from_the_builder_is_caught_after_writing(
    tmp_path, monkeypatch
):
    """The same argument for ``validate_routing_contract``.

    Both records are drifted together on purpose. Changing only the enablement
    would be caught earlier by P10, which compares the prompt qualification with
    the enablement -- a true refusal, but not the one this test is about.
    """
    real_enablement = gm._enablement_record
    real_prompt = gm._prompt_qualification_record
    forged = {"routing_contract_id": ROUTING_CONTRACT_ID, "routing_contract_sha256": "b" * 64}

    def enablement(**kwargs):
        return real_enablement(**{**kwargs, "routing": forged})

    def prompt_qualification(**kwargs):
        return real_prompt(**{**kwargs, "routing": forged})

    monkeypatch.setattr(gm, "_enablement_record", enablement)
    monkeypatch.setattr(gm, "_prompt_qualification_record", prompt_qualification)
    build = _build()
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(build, attempt_root=_attempt_root(tmp_path))
    assert caught.value.reason_code == "routing_contract_mismatch"


# --- why the remaining post-write validators are there -------------------------
#
# A chain this module builds cannot trip these on its own: both sides of each
# comparison are derived from one set of inputs, so they agree by construction.
# Each check exists for a regression in the builder, and each test below
# simulates exactly that -- a record written with one field wrong, refused after
# it reaches disk and before any pin is returned.


def _materialize_with_broken_authorization(tmp_path, monkeypatch, **fields):
    real = gm._authorization_record

    def broken(**kwargs):
        record = real(**kwargs)
        record.update(fields)
        return record

    monkeypatch.setattr(gm, "_authorization_record", broken)
    with pytest.raises(ExtractionError) as caught:
        materialize_governance_records(_build(), attempt_root=_attempt_root(tmp_path))
    return caught.value


def test_a_broken_enablement_pin_from_the_builder_is_caught_after_writing(
    tmp_path, monkeypatch
):
    """``validate_governance_chain_v2`` -- the pin walk itself."""
    error = _materialize_with_broken_authorization(
        tmp_path, monkeypatch, adapter_enablement_record_sha256="c" * 64
    )
    assert error.reason_code == "authorization_chain_broken"


def test_a_drifted_scope_field_from_the_builder_is_caught_after_writing(
    tmp_path, monkeypatch
):
    """``validate_authorization_scope`` -- the run this authorization is for."""
    error = _materialize_with_broken_authorization(
        tmp_path, monkeypatch, company_id="CIK0000000000"
    )
    assert error.reason_code == "authorization_scope_mismatch"


def test_a_drifted_meter_identity_from_the_builder_is_caught_after_writing(
    tmp_path, monkeypatch
):
    """``validate_budget_meter_identity`` -- ADR-047's code-owned comparison.

    The expected side is read from the module's own constants, never from the
    bundle, so a record that declared a different meter is refused rather than
    validated against its own claim.
    """
    error = _materialize_with_broken_authorization(
        tmp_path, monkeypatch, budget_meter_identity="somebody_elses.meter"
    )
    assert error.reason_code == "budget_meter_identity_mismatch"


def test_a_drifted_budget_policy_version_from_the_builder_is_caught_after_writing(
    tmp_path, monkeypatch
):
    error = _materialize_with_broken_authorization(
        tmp_path, monkeypatch, budget_policy_version="budget_policy_v9"
    )
    assert error.reason_code == "budget_policy_version_mismatch"


# --- the canonical references are not caller-controlled -------------------------
#
# A public mutable dict was shipped first and was a real defect: assigning into
# it changed both the pins a build returned and the references embedded inside
# the written records, which made ADR-049's "no caller-controlled reference"
# false. These four tests are the ones that would have caught it.

_CANONICAL_PATHS = frozenset(
    {
        "governance/adapter_qualification_record.json",
        "governance/prompt_qualification_record.json",
        "governance/adapter_enablement_record.json",
        "governance/live_call_authorization.json",
    }
)


def test_the_public_reference_view_rejects_item_assignment():
    with pytest.raises(TypeError):
        gm.GOVERNANCE_REFERENCES["authorization"] = "caller-controlled/x.json"
    with pytest.raises(TypeError):
        del gm.GOVERNANCE_REFERENCES["authorization"]
    assert set(gm.GOVERNANCE_REFERENCES.values()) == _CANONICAL_PATHS


def test_rebinding_the_public_view_cannot_reach_the_production_lookup(monkeypatch):
    """The stronger form: even replacing the module attribute changes nothing.

    Item assignment being refused is not enough on its own -- a caller can always
    rebind a module attribute. What matters is that no production path reads it.
    """
    monkeypatch.setattr(
        gm,
        "GOVERNANCE_REFERENCES",
        {
            "qualification": "caller-controlled/q.json",
            "prompt_qualification": "caller-controlled/p.json",
            "enablement": "caller-controlled/e.json",
            "authorization": "caller-controlled/a.json",
        },
        raising=True,
    )
    build = _build()
    assert build.pin("authorization")["reference"] == (
        "governance/live_call_authorization.json"
    )
    # The embedded pins too: this is the half the first version of the defect
    # report did not mention, and it is the half that reaches disk.
    assert build.record("authorization")["adapter_enablement_record_reference"] == (
        "governance/adapter_enablement_record.json"
    )
    assert build.record("enablement")["adapter_qualification_record_reference"] == (
        "governance/adapter_qualification_record.json"
    )
    assert build.record("enablement")["prompt_qualification_reference"] == (
        "governance/prompt_qualification_record.json"
    )


def test_every_pin_a_build_returns_is_one_of_the_four_canonical_paths():
    build = _build()
    references = {build.pin(name)["reference"] for name in _BUILD_NAMES}
    assert references == _CANONICAL_PATHS


def test_the_written_paths_survive_a_rebound_public_view(tmp_path, monkeypatch):
    """End to end: what lands on disk is the canonical set, whatever a caller did."""
    monkeypatch.setattr(
        gm, "GOVERNANCE_REFERENCES", {"authorization": "caller-controlled/a.json"}
    )
    root = _attempt_root(tmp_path)
    pin = materialize_governance_records(_build(), attempt_root=root)
    assert set(_files(root)) == _CANONICAL_PATHS
    assert pin["reference"] == "governance/live_call_authorization.json"
