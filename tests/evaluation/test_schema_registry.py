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
    # Rebaselined by ADR-068: manifest_version 0.19.0 -> 0.20.0, 49 -> 50
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
    "c8ad9e3532ee72283672367056514e9324e82ef89b2ff7521c95c038da640f97"
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
