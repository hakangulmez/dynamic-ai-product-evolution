"""ADR-105 asset-backed-issuer determination tests — fully offline.

Every lineage is synthesized under a temporary root that symlinks the real
schemas/ directory. These pin the two-condition rule (both halves required,
either alone unknown, never false), the evidence obligations of a true
record, the aggregate-only authority boundary, and the byte identity of the
sibling shell-determination predecessors this module deliberately does not
touch.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.asset_backed_determination import (
    BASIS_BOTH_CONDITIONS,
    BASIS_J_ONLY,
    BASIS_NO_EVIDENCE,
    BASIS_REG_AB_ONLY,
    DETERMINATIONS_FILENAME,
    MANIFEST_FILENAME,
    REASON_CODE,
    AssetBackedDeterminationError,
    determine_for_row,
    run_asset_backed_determination,
)
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
PACKET_FIXTURES = ROOT / "evals" / "fixtures" / "baseline_packets"
RECORD_SCHEMA = ROOT / "schemas" / "asset_backed_issuer_determination.schema.json"
MANIFEST_SCHEMA = (
    ROOT / "schemas" / "asset_backed_issuer_determination_manifest.schema.json"
)
SHELL_MANIFEST_V3_SCHEMA = (
    ROOT / "schemas" / "shell_company_determination_manifest.v3.schema.json"
)
ACQ_MANIFEST_FILENAME = "primary_document_acquisition_manifest.json"
BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"

FIXED_CLOCK = lambda: datetime(2026, 8, 19, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

PROVENANCE = {
    "carrier_run_id": "synthetic-fixture-carrier",
    "carrier_manifest_sha256": "0" * 64,
    "freeze_record_sha256": "0" * 64,
}
ROUTE_VALIDATION = {
    "probe_run_id": "synthetic-fixture-probe",
    "probe_manifest_sha256": "0" * 64,
    "covered_accessions": 3,
    "note": "URL-route grammar only; never selection evidence.",
}

#: The canonical positive: an explicit General Instruction J omission AND a
#: Regulation AB item heading, in one filing.
ABS_DOC = (
    b"<html><p>Item 1. Business.</p>"
    b"<p>Omitted pursuant to General Instruction J of Form 10-K.</p>"
    b"<p>Item 1122. Compliance with Applicable Servicing Criteria</p>"
    b"<p>The servicer has complied with the applicable servicing criteria "
    b"set forth in Item 1122(d) of Regulation AB.</p>"
    b"<p>Item 1119. Affiliations and Certain Relationships</p></html>"
)
J_ONLY_DOC = (
    b"<html><p>Item 1. Business.</p>"
    b"<p>Omitted pursuant to General Instruction J of Form 10-K.</p>"
    b"<p>Nothing further is disclosed here.</p></html>"
)
REG_AB_ONLY_DOC = (
    b"<html><p>Item 1. Business</p><p>We service receivables.</p>"
    b"<p>Item 1122. Compliance with Applicable Servicing Criteria</p></html>"
)
OPERATING_DOC = (
    b"<html><p>Item 1. Business</p>"
    b"<p>Our trust subsidiaries issue asset-backed securities under "
    b"Regulation AB, and our securitization program is described in the "
    b"notes. We operate stores in forty states.</p>"
    b"<p>Item 1A. Risk Factors</p></html>"
)
SHORT_DOC = b"<html><p>Item 1. Business</p><p>Tiny.</p></html>"


def _synth_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "schemas").symlink_to(ROOT / "schemas")
    return root


def _doc_entry(root: Path, name: str, cik: str, accession: str,
               raw: bytes) -> tuple[Path, dict]:
    source = root / name
    source.write_bytes(raw)
    template = read_json(PACKET_FIXTURES / BUNDLE_MANIFEST_FILENAME)
    entry = dict(template["documents"][0])
    entry.update(representation="html", admission=None, document_blocks=None,
                 declared_type=None, declared_filename=None,
                 cik=cik, accession=accession, local_filename=name,
                 selected_document=name,
                 source_sha256=sha256(raw).hexdigest(),
                 source_byte_length=len(raw))
    return source, entry


def _write_shard(root: Path, name: str,
                 documents: list[tuple[Path, dict]]) -> Path:
    run_dir = root / "shards" / name
    run_dir.mkdir(parents=True)
    manifest = {
        "bundle_contract": "baseline_primary_document_bundle@0.2.0",
        "description": "Synthesized ADR-105 fixture shard.",
        "provenance": dict(PROVENANCE),
        "route_validation": dict(ROUTE_VALIDATION),
        "documents": [entry for _, entry in documents],
    }
    (run_dir / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for source, entry in documents:
        shutil.copyfile(source, run_dir / entry["local_filename"])
    (run_dir / ACQ_MANIFEST_FILENAME).write_text(
        json.dumps({"stub_for": name}, indent=2) + "\n", encoding="utf-8")
    return run_dir


def _aggregate(root: Path, shards: list[Path],
               run_ids=("ra",), name="aggregate.json") -> Path:
    records = []
    for index, run_dir in enumerate(shards):
        rows = len(read_json(run_dir / BUNDLE_MANIFEST_FILENAME)["documents"])
        records.append({
            "shard_index": index, "run_id": run_dir.name,
            "run_dir": str(run_dir.relative_to(root)),
            "shard_plan_sha256": f"{index:064d}",
            "acquisition_manifest_sha256": sha256(
                (run_dir / ACQ_MANIFEST_FILENAME).read_bytes()).hexdigest(),
            "bundle_manifest_sha256": sha256(
                (run_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()).hexdigest(),
            "accessions": rows, "carrier_rows": rows, "bundle_entries": rows,
            "total_requests": 2 * rows, "retained_bytes_total": 1,
        })
    rows = sum(r["carrier_rows"] for r in records)
    payload = {
        "aggregate_manifest_contract":
            "acquisition_queue_aggregate_manifest@0.2.0",
        "run_id": "synthetic-aggregate", "queue_id": "synthetic-queue",
        "queue_definition_sha256": "a" * 64,
        "execution_run_ids": list(run_ids),
        "coverage_complete": True,
        "coverage_statement":
            f"{len(records)} of {len(records)} shard(s) are authoritative.",
        "shards_authoritative": records,
        "shards_not_authoritative": [], "superseded_directories": [],
        "counts": {
            "shards_in_queue": len(records),
            "shards_authoritative": len(records),
            "shards_not_authoritative": 0,
            "accessions_covered": rows, "carrier_rows_covered": rows,
            "bundle_entries": rows, "total_requests": 2 * rows,
            "retained_bytes_total": len(records),
            "superseded_directories": 0, "retained_bytes_superseded": 0,
        },
        "run_timestamp": "2026-08-19T09:00:00+00:00",
        "limitations": ["Synthetic fixture aggregate."],
    }
    path = root / name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _lineage(tmp_path: Path):
    root = _synth_root(tmp_path)
    shard = _write_shard(root, "ra-shard-0000", [
        _doc_entry(root, "abs_10k.htm", "0009700001",
                   "0009700001-22-000001", ABS_DOC),
        _doc_entry(root, "j_only.htm", "0009700002",
                   "0009700002-22-000001", J_ONLY_DOC),
        _doc_entry(root, "reg_ab_only.htm", "0009700003",
                   "0009700003-22-000001", REG_AB_ONLY_DOC),
        _doc_entry(root, "operating.htm", "0009700004",
                   "0009700004-22-000001", OPERATING_DOC),
        _doc_entry(root, "short.htm", "0009700005",
                   "0009700005-22-000001", SHORT_DOC),
    ])
    aggregate = _aggregate(root, [shard])
    return root, aggregate, shard


def _run(root: Path, aggregate: Path, tmp_path: Path, run_id: str = "abs"):
    return run_asset_backed_determination(
        repo_root=root, aggregate_manifest_path=aggregate,
        output_dir=tmp_path / "out", run_id=run_id, clock=FIXED_CLOCK)


# --- the rule -----------------------------------------------------------------


def test_canonical_positive_carries_both_conditions_and_evidence(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    result = _run(root, aggregate, tmp_path)
    by_cik = {r["cik"]: r for r in result.determinations}
    record = by_cik["0009700001"]
    assert record["asset_backed_issuer"] == "true"
    assert record["basis"] == BASIS_BOTH_CONDITIONS
    assert record["reason_code"] == REASON_CODE == "ASSET_BACKED_ISSUER"
    assert "general instruction j" in record["instruction_j_quote"].lower()
    assert "omitted" in record["instruction_j_quote"].lower()
    assert record["reg_ab_items"] == ["1119", "1122"]
    assert "item 1122" in record["reg_ab_quote"].lower()
    # the offsets address the raw document: the slices contain the phrases
    raw = ABS_DOC
    j_slice = raw[record["instruction_j_byte_start"]:
                  record["instruction_j_byte_end"]]
    assert b"General Instruction J" in j_slice
    ab_slice = raw[record["reg_ab_byte_start"]:record["reg_ab_byte_end"]]
    assert b"1122" in ab_slice
    assert record["source_sha256"] == sha256(raw).hexdigest()
    schema = Draft202012Validator(read_json(RECORD_SCHEMA))
    assert not list(schema.iter_errors(record))


@pytest.mark.parametrize("cik, expected_basis", [
    ("0009700002", BASIS_J_ONLY),
    ("0009700003", BASIS_REG_AB_ONLY),
    ("0009700004", BASIS_NO_EVIDENCE),
    ("0009700005", BASIS_NO_EVIDENCE),
])
def test_half_conditions_and_lookalikes_stay_unknown(tmp_path, cik,
                                                     expected_basis):
    root, aggregate, _ = _lineage(tmp_path)
    result = _run(root, aggregate, tmp_path)
    record = {r["cik"]: r for r in result.determinations}[cik]
    assert record["asset_backed_issuer"] == "unknown"
    assert record["basis"] == expected_basis
    assert record["reason_code"] is None
    assert record["instruction_j_quote"] is None
    assert record["reg_ab_items"] is None
    schema = Draft202012Validator(read_json(RECORD_SCHEMA))
    assert not list(schema.iter_errors(record))


def test_false_is_never_emitted_and_counts_partition(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    result = _run(root, aggregate, tmp_path)
    outcomes = {r["asset_backed_issuer"] for r in result.determinations}
    assert outcomes == {"true", "unknown"}
    assert result.counts["asset_backed_true"] == 1
    assert result.counts["asset_backed_unknown"] == 4
    assert result.counts["by_basis"] == {
        BASIS_BOTH_CONDITIONS: 1, BASIS_J_ONLY: 1, BASIS_REG_AB_ONLY: 1,
        BASIS_NO_EVIDENCE: 2,
    }
    assert all(result.reconciliation.values())


def test_no_length_or_ratio_heuristic_exists():
    """The determination of a tiny document and a huge one differ only by
    their signatures, never by size."""
    entry = {"cik": "0009700009", "accession": "0009700009-22-000001",
             "form": "10-K", "baseline_filing_date": "2022-03-01",
             "source_sha256": "0" * 64, "representation": "html"}
    tiny = determine_for_row(dict(entry, source_sha256=sha256(
        SHORT_DOC).hexdigest()), SHORT_DOC)
    padded = SHORT_DOC + b"<p>" + b"padding " * 100_000 + b"</p>"
    huge = determine_for_row(dict(entry, source_sha256=sha256(
        padded).hexdigest()), padded)
    assert tiny["asset_backed_issuer"] == huge["asset_backed_issuer"] \
        == "unknown"
    assert tiny["basis"] == huge["basis"] == BASIS_NO_EVIDENCE


# --- authority and integrity --------------------------------------------------


def test_a_tampered_bundle_manifest_is_refused_before_output(tmp_path):
    root, aggregate, shard = _lineage(tmp_path)
    manifest = read_json(shard / BUNDLE_MANIFEST_FILENAME)
    manifest["description"] = "edited after aggregation"
    (shard / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(AssetBackedDeterminationError, match="hashes to"):
        _run(root, aggregate, tmp_path)
    assert not (tmp_path / "out").exists()


def test_a_tampered_primary_document_is_refused_before_output(tmp_path):
    from dynamic_ai_products.ingestion.baseline_packet import PacketBundleError

    root, aggregate, shard = _lineage(tmp_path)
    (shard / "abs_10k.htm").write_bytes(b"<html>edited</html>")
    with pytest.raises(PacketBundleError):
        _run(root, aggregate, tmp_path)
    assert not (tmp_path / "out").exists()


def test_a_malformed_aggregate_is_refused_before_output(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    payload = json.loads(aggregate.read_text(encoding="utf-8"))
    payload["coverage_complete"] = False
    aggregate.write_text(json.dumps(payload, indent=2) + "\n",
                         encoding="utf-8")
    with pytest.raises(AssetBackedDeterminationError,
                       match="coverage is partial"):
        _run(root, aggregate, tmp_path)
    assert not (tmp_path / "out").exists()


def test_an_unenumerated_shard_is_invisible(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    before = _run(root, aggregate, tmp_path, run_id="before")
    intruder = _write_shard(root, "rz-shard-0001", [
        _doc_entry(root, "intruder_abs.htm", "0009700099",
                   "0009700099-22-000001", ABS_DOC),
    ])
    os.chmod(intruder, 0o000)
    try:
        after = _run(root, aggregate, tmp_path, run_id="after")
        assert after.determinations == before.determinations
        assert (after.run_dir / DETERMINATIONS_FILENAME).read_bytes() == \
            (before.run_dir / DETERMINATIONS_FILENAME).read_bytes()
        assert "rz-shard-0001" not in json.dumps(
            read_json(after.manifest_path))
    finally:
        os.chmod(intruder, 0o755)


def test_write_once_and_determinism(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    first = _run(root, aggregate, tmp_path, run_id="one")
    with pytest.raises(FileExistsError):
        _run(root, aggregate, tmp_path, run_id="one")
    second = _run(root, aggregate, tmp_path, run_id="two")
    assert (first.run_dir / DETERMINATIONS_FILENAME).read_bytes() == \
        (second.run_dir / DETERMINATIONS_FILENAME).read_bytes()
    first_manifest = read_json(first.manifest_path)
    second_manifest = read_json(second.manifest_path)
    assert first_manifest["output_hashes"] == second_manifest["output_hashes"]


# --- schemas and predecessors -------------------------------------------------


def test_the_manifest_validates_and_rejects_the_shell_generation(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    result = _run(root, aggregate, tmp_path)
    manifest = read_json(result.manifest_path)
    own = Draft202012Validator(read_json(MANIFEST_SCHEMA))
    shell = Draft202012Validator(read_json(SHELL_MANIFEST_V3_SCHEMA))
    assert not list(own.iter_errors(manifest))
    assert list(shell.iter_errors(manifest)), \
        "the asset-backed manifest is not a shell manifest"
    # and the shell fixture manifest shape is not an asset-backed one: the
    # asset-backed schema requires the rule block no shell manifest carries.
    assert "rule" in manifest and manifest["rule"]["reason_code"] == \
        "ASSET_BACKED_ISSUER"


def test_record_schema_enforces_the_evidence_conditionals(tmp_path):
    root, aggregate, _ = _lineage(tmp_path)
    result = _run(root, aggregate, tmp_path)
    schema = Draft202012Validator(read_json(RECORD_SCHEMA))
    true_record = next(r for r in result.determinations
                       if r["asset_backed_issuer"] == "true")
    unknown_record = next(r for r in result.determinations
                          if r["asset_backed_issuer"] == "unknown")
    forged = dict(true_record, instruction_j_quote=None)
    assert list(schema.iter_errors(forged)), "true without evidence refused"
    forged = dict(true_record, asset_backed_issuer="false")
    assert list(schema.iter_errors(forged)), "false is not an outcome"
    forged = dict(unknown_record, reason_code="ASSET_BACKED_ISSUER")
    assert list(schema.iter_errors(forged)), \
        "the exclusion code never rides on unknown"


def test_shell_predecessors_are_byte_identical():
    """This increment must not touch the sibling shell determination."""
    pins = {
        "src/dynamic_ai_products/ingestion/shell_company_determination.py":
            None,  # asserted via git blob below
    }
    import subprocess
    for path in (
        "src/dynamic_ai_products/ingestion/shell_company_determination.py",
        "schemas/shell_company_determination.schema.json",
        "schemas/shell_company_determination.v2.schema.json",
        "schemas/shell_company_determination_manifest.schema.json",
        "schemas/shell_company_determination_manifest.v2.schema.json",
        "schemas/shell_company_determination_manifest.v3.schema.json",
    ):
        head = subprocess.run(["git", "rev-parse", f"HEAD:{path}"],
                              capture_output=True, text=True, cwd=ROOT)
        disk = subprocess.run(["git", "hash-object", path],
                              capture_output=True, text=True, cwd=ROOT)
        assert head.stdout.strip() == disk.stdout.strip(), path
    del pins


_SHELL_ARTIFACT = (ROOT / "data" / "runs" / "shell-company-determination"
                   / "shell-company-determination-domestic-text-lineage-v3-20260818"
                   / "shell_company_determination_manifest.json")


@pytest.mark.skipif(not _SHELL_ARTIFACT.is_file(),
                    reason="live shell artifact not present")
def test_the_live_shell_artifact_is_untouched():
    assert sha256(_SHELL_ARTIFACT.read_bytes()).hexdigest() == \
        "12f76902d30ff4873537994c5cbc313d9c0992c751653835777a77bbcd1605f5"


# --- ADR-105 correction: structural tie, block-opening headings ---------------
#
# The first detector accepted "pursuant to" as an omission token in a 400-byte
# window and any textual Item 11xx mention, which returned true for the
# operating-company prose below. These regressions pin the corrected rule.

FALSE_POSITIVE_DOC = (
    b"<html><p>We provide this disclosure pursuant to General Instruction J "
    b"for administrative reasons, but no Item 1 section is omitted. Our "
    b"securitization note refers investors to Item 1122 of Regulation AB."
    b"</p></html>"
)
J_OMISSION_INLINE_AB_DOC = (
    b"<html><p>Item 1. Business.</p>"
    b"<p>Omitted pursuant to General Instruction J of Form 10-K.</p>"
    b"<p>Our servicing agreement refers to Item 1122 of Regulation AB in "
    b"passing, within this sentence only.</p></html>"
)
BARE_PURSUANT_DOC = (
    b"<html><p>Item 1. Business</p>"
    b"<p>This annual report is filed pursuant to General Instruction J of "
    b"Form 10-K.</p>"
    b"<p>Item 1122. Compliance with Applicable Servicing Criteria</p></html>"
)
NEGATED_OMISSION_DOC = (
    b"<html><p>Item 1. Business</p>"
    b"<p>No items have been omitted pursuant to General Instruction J.</p>"
    b"<p>Item 1122. Compliance with Applicable Servicing Criteria</p></html>"
)


def _row(raw: bytes, cik: str = "0009700050") -> dict:
    return {"cik": cik, "accession": f"{cik}-22-000001", "form": "10-K",
            "baseline_filing_date": "2022-03-01",
            "source_sha256": sha256(raw).hexdigest(),
            "representation": "html"}


def test_the_demonstrated_false_positive_is_unknown():
    record = determine_for_row(_row(FALSE_POSITIVE_DOC), FALSE_POSITIVE_DOC)
    assert record["asset_backed_issuer"] == "unknown"
    assert record["basis"] == BASIS_NO_EVIDENCE
    assert record["reason_code"] is None


def test_genuine_omission_with_only_inline_reg_ab_prose_is_unknown():
    record = determine_for_row(_row(J_OMISSION_INLINE_AB_DOC),
                               J_OMISSION_INLINE_AB_DOC)
    assert record["asset_backed_issuer"] == "unknown"
    assert record["basis"] == BASIS_J_ONLY, \
        "the inline Item 1122 citation must not count as a heading"


def test_bare_pursuant_to_instruction_j_is_not_an_omission():
    record = determine_for_row(_row(BARE_PURSUANT_DOC), BARE_PURSUANT_DOC)
    assert record["asset_backed_issuer"] == "unknown"
    assert record["basis"] == BASIS_REG_AB_ONLY, \
        "the heading counts; the bare citation does not"


def test_a_negated_omission_construction_is_refused():
    record = determine_for_row(_row(NEGATED_OMISSION_DOC),
                               NEGATED_OMISSION_DOC)
    assert record["asset_backed_issuer"] == "unknown"
    assert record["basis"] == BASIS_REG_AB_ONLY


def test_canonical_evidence_spans_are_minimal(tmp_path):
    """The stored quotes are the matched constructions, not windows."""
    root, aggregate, _ = _lineage(tmp_path)
    result = _run(root, aggregate, tmp_path)
    record = {r["cik"]: r for r in result.determinations}["0009700001"]
    assert record["asset_backed_issuer"] == "true"
    quote = record["instruction_j_quote"]
    assert quote == "Omitted pursuant to General Instruction J"
    assert "Business" not in quote and "Form 10-K" not in quote
    assert record["reg_ab_quote"] == "Item 1122"
    raw = ABS_DOC
    j_slice = raw[record["instruction_j_byte_start"]:
                  record["instruction_j_byte_end"]]
    assert j_slice == b"Omitted pursuant to General Instruction J"
    ab_slice = raw[record["reg_ab_byte_start"]:record["reg_ab_byte_end"]]
    assert ab_slice == b"Item 1122"


# --- ADR-105 evidence contract: offsets authoritative, quotes normalized ------

ENTITY_ABS_DOC = (
    b"<html><p>Item 1. Business.</p>"
    b"<p>Omitted&#160;pursuant to General Instruction J.</p>"
    b"<p>Item&nbsp;1122. Compliance with Applicable Servicing Criteria</p>"
    b"</html>"
)


def test_entity_encoded_evidence_offsets_are_authoritative():
    """Raw offsets recover the entity-containing bytes; the stored quote is
    the normalized rendering; normalization reconciles them exactly."""
    import re

    record = determine_for_row(_row(ENTITY_ABS_DOC), ENTITY_ABS_DOC)
    assert record["asset_backed_issuer"] == "true"
    assert record["basis"] == BASIS_BOTH_CONDITIONS

    # The stored quotes are normalized renderings.
    assert record["instruction_j_quote"] == \
        "Omitted pursuant to General Instruction J"
    assert record["reg_ab_quote"] == "Item 1122"
    assert record["reg_ab_items"] == ["1122"]

    # The raw slices contain the entities the quotes do not.
    j_slice = ENTITY_ABS_DOC[record["instruction_j_byte_start"]:
                             record["instruction_j_byte_end"]]
    ab_slice = ENTITY_ABS_DOC[record["reg_ab_byte_start"]:
                              record["reg_ab_byte_end"]]
    assert j_slice == b"Omitted&#160;pursuant to General Instruction J"
    assert ab_slice == b"Item&nbsp;1122"

    # Normalizing each slice through the same entity collapse reconciles it
    # with the stored quote byte-for-byte.
    entity = re.compile(rb"&[#a-zA-Z0-9]{1,8};")

    def normalize(raw_slice: bytes) -> str:
        return " ".join(entity.sub(b" ", raw_slice)
                        .decode("utf-8", "replace").split())

    assert normalize(j_slice) == record["instruction_j_quote"]
    assert normalize(ab_slice) == record["reg_ab_quote"]
