"""Stage 00B-S shell-company determination tests (ADR-094) — fully offline.

Every run reads locally supplied, hash-verified primary documents into a
temporary directory; nothing fetches, no model is called, and no other issuer
flag is read or set. These tests pin the transform-application contract, the
context-resolution rule, and the fail-closed multiplicity semantics.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.shell_company_determination import (
    DETERMINATIONS_FILENAME,
    MANIFEST_FILENAME,
    SUPPORTED_TRANSFORMS,
    ShellDeterminationError,
    determine_for_row,
    evaluate_fact,
    extract_contexts,
    extract_shell_facts,
    run_shell_company_determination,
)
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = ROOT / "evals" / "fixtures" / "shell_company"
DET_SCHEMA = ROOT / "schemas" / "shell_company_determination.schema.json"
MANIFEST_SCHEMA = (
    ROOT / "schemas" / "shell_company_determination_manifest.schema.json"
)
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(BUNDLE_DIR / "expected_determinations.json")

FIXED_CLOCK = lambda: datetime(2026, 8, 17, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _run(tmp_path: Path, run_id: str = "shell-test", bundle=None, **kwargs):
    return run_shell_company_determination(
        repo_root=ROOT,
        bundle_dir=bundle or BUNDLE_DIR,
        output_dir=tmp_path / "out",
        run_id=run_id,
        clock=FIXED_CLOCK,
        **kwargs,
    )


def _by_cik(result) -> dict[str, dict]:
    return {r["cik"]: r for r in result.determinations}


# --- gold round trip --------------------------------------------------------


def test_matches_gold(tmp_path):
    result = _run(tmp_path)
    assert result.counts == EXPECTED["counts"]
    got = [
        {"cik": r["cik"], "form": r["form"], "shell_company": r["shell_company"],
         "basis": r["basis"], "facts_in_document": r["facts_in_document"],
         "assignable_facts": r["assignable_facts"],
         "transform_observed": r["transform_observed"],
         "decoded_content_observed": r["decoded_content_observed"]}
        for r in result.determinations
    ]
    assert got == EXPECTED["determinations"]
    assert all(result.reconciliation.values())


def test_records_and_manifest_validate(tmp_path):
    result = _run(tmp_path)
    validator = Draft202012Validator(read_json(DET_SCHEMA))
    for record in result.determinations:
        assert not list(validator.iter_errors(record))
    manifest = read_json(result.manifest_path)
    assert not list(
        Draft202012Validator(read_json(MANIFEST_SCHEMA)).iter_errors(manifest)
    )
    assert (result.run_dir / DETERMINATIONS_FILENAME).is_file()
    assert manifest["output_hashes"][DETERMINATIONS_FILENAME] == sha256(
        (result.run_dir / DETERMINATIONS_FILENAME).read_bytes()
    ).hexdigest()


# --- transform application --------------------------------------------------


def test_ballotbox_yields_both_outcomes_under_one_transform(tmp_path):
    """The transform alone never decides: content does, under the transform."""
    rows = _by_cik(_run(tmp_path))
    assert rows["0009300001"]["shell_company"] == "false"
    assert rows["0009300002"]["shell_company"] == "true"
    assert (
        rows["0009300001"]["transform_observed"]
        == rows["0009300002"]["transform_observed"]
        == "ixt-sec:boolballotbox"
    )


def test_both_entity_encodings_of_the_empty_box_decode_alike(tmp_path):
    rows = _by_cik(_run(tmp_path))
    decimal, hexadecimal = rows["0009300001"], rows["0009300003"]
    assert decimal["decoded_content_observed"] == (
        hexadecimal["decoded_content_observed"]
    ) == "☐"
    assert decimal["shell_company"] == hexadecimal["shell_company"] == "false"


def test_boolean_false_and_fixed_false(tmp_path):
    rows = _by_cik(_run(tmp_path))
    assert rows["0009300004"]["shell_company"] == "false"
    assert rows["0009300004"]["transform_observed"] == "ixt:booleanfalse"
    assert rows["0009300005"]["shell_company"] == "false"
    assert rows["0009300005"]["transform_observed"] == "ixt:fixed-false"


def test_fixed_false_wins_over_contradicting_content(tmp_path):
    """A fixed transform ignores its glyph, even a crossed box."""
    row = _by_cik(_run(tmp_path))["0009300006"]
    assert row["decoded_content_observed"] == "☒"
    assert row["shell_company"] == "false"
    assert row["basis"] == "fixed_false_transform"


def test_only_observed_transforms_are_supported():
    assert SUPPORTED_TRANSFORMS == (
        "ixt-sec:boolballotbox", "ixt:booleanfalse", "ixt:fixed-false",
    )
    assert "ixt:booleantrue" not in SUPPORTED_TRANSFORMS
    assert "ixt:fixed-true" not in SUPPORTED_TRANSFORMS


def test_unsupported_and_absent_transforms_are_unknown(tmp_path):
    rows = _by_cik(_run(tmp_path))
    assert rows["0009300008"]["shell_company"] == "unknown"
    assert rows["0009300008"]["basis"] == "unsupported_transform"
    assert rows["0009300008"]["transform_observed"] == "ixt:booleantrue"
    assert rows["0009300009"]["shell_company"] == "unknown"
    assert rows["0009300009"]["basis"] == "absent_transform"


def test_unresolved_ballotbox_content_is_unknown():
    from dynamic_ai_products.ingestion.shell_company_determination import ShellFact

    fact = ShellFact(0, 10, "a" * 64, "c", "ixt-sec:boolballotbox", "maybe")
    assert evaluate_fact(fact) == ("unknown", "unresolved_ballotbox_content")


# --- absence and multiplicity ----------------------------------------------


def test_absent_fact_is_unknown_and_retained(tmp_path):
    row = _by_cik(_run(tmp_path))["0009300007"]
    assert row["shell_company"] == "unknown"
    assert row["basis"] == "no_shell_fact_in_document"
    assert row["facts_in_document"] == 0
    assert row["fact_element_sha256"] is None


def test_conflicting_duplicates_are_unknown(tmp_path):
    row = _by_cik(_run(tmp_path))["0009300010"]
    assert row["shell_company"] == "unknown"
    assert row["basis"] == "multiple_assignable_facts"
    assert row["assignable_facts"] == 2


def test_agreeing_duplicates_are_also_unknown(tmp_path):
    """v0.1 never collapses duplicates, even when they agree."""
    row = _by_cik(_run(tmp_path))["0009300011"]
    assert row["shell_company"] == "unknown"
    assert row["basis"] == "multiple_assignable_facts"
    assert "whether or not they agree" in row["detail"]


# --- context resolution -----------------------------------------------------


def test_multi_registrant_binds_only_the_unmembered_parent_context(tmp_path):
    rows = _by_cik(_run(tmp_path))
    parent, sub_one, sub_two = (
        rows["0009300012"], rows["0009300013"], rows["0009300014"]
    )
    assert parent["shell_company"] == "false"
    assert parent["assignable_facts"] == 1
    for sub in (sub_one, sub_two):
        assert sub["facts_in_document"] == 3
        assert sub["assignable_facts"] == 0
        assert sub["shell_company"] == "unknown"
        assert sub["basis"] == "no_fact_assignable_to_this_cik"
        assert "LegalEntityAxis" in sub["detail"]
        assert "does not map to a CIK" in sub["detail"]


def test_member_tokens_are_never_resolved_by_name(tmp_path):
    row = _by_cik(_run(tmp_path))["0009300013"]
    assert "SubsidiaryOneMember" in row["detail"]
    assert row["shell_company"] == "unknown"


def test_non_cik_identifier_scheme_does_not_bind(tmp_path):
    raw = (
        b'<html><body><div style="display:none">'
        b'<xbrli:context id="c1"><xbrli:entity>'
        b'<xbrli:identifier scheme="http://example.invalid/OTHER">0009300001'
        b"</xbrli:identifier></xbrli:entity></xbrli:context></div>"
        b'<ix:nonNumeric contextRef="c1" format="ixt-sec:boolballotbox" '
        b'name="dei:EntityShellCompany">&#9744;</ix:nonNumeric>'
        b"</body></html>"
    )
    entry = {"cik": "0009300001", "accession": "0009300001-22-000001",
             "form": "10-K", "baseline_filing_date": "2022-03-15",
             "source_sha256": "b" * 64}
    record = determine_for_row(entry, raw)
    assert record["shell_company"] == "unknown"
    assert record["basis"] == "no_fact_assignable_to_this_cik"
    assert "not the SEC CIK scheme" in record["detail"]


def test_context_reference_that_resolves_to_nothing_is_unknown():
    raw = (
        b'<ix:nonNumeric contextRef="missing" format="ixt-sec:boolballotbox" '
        b'name="dei:EntityShellCompany">&#9744;</ix:nonNumeric>'
    )
    entry = {"cik": "0009300001", "accession": "0009300001-22-000001",
             "form": "10-K", "baseline_filing_date": "2022-03-15",
             "source_sha256": "b" * 64}
    record = determine_for_row(entry, raw)
    assert record["shell_company"] == "unknown"
    assert "resolves to no context" in record["detail"]


def _one_context_document(members: bytes, cik: bytes = b"0009300099") -> bytes:
    """A document whose single crossed-ballot-box fact points at one context."""
    return (
        b'<html><body><div style="display:none">'
        b'<xbrli:context id="c1"><xbrli:entity>'
        b'<xbrli:identifier scheme="http://www.sec.gov/CIK">' + cik +
        b"</xbrli:identifier><xbrli:segment>" + members +
        b"</xbrli:segment></xbrli:entity></xbrli:context></div>"
        b'<ix:nonNumeric contextRef="c1" format="ixt-sec:boolballotbox" '
        b'name="dei:EntityShellCompany">&#9746;</ix:nonNumeric>'
        b"</body></html>"
    )


_ROW = {"cik": "0009300099", "accession": "0009300099-22-000001",
        "form": "10-K", "baseline_filing_date": "2022-03-15",
        "source_sha256": "b" * 64}


def test_legal_entity_member_after_another_member_still_blocks_assignment():
    """A LegalEntityAxis member is disqualifying at *any* position.

    Reading only a context's first ``explicitMember`` made a context whose
    legal-entity member sits behind a member on some other axis look
    unmembered. With a matching CIK and a crossed box it then emitted
    ``true`` — a hard exclusion drawn from a context the filing never maps to
    this registrant. ADR-094 forbids that assignment.
    """
    raw = _one_context_document(
        b'<xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">'
        b"us-gaap:CommonClassAMember</xbrldi:explicitMember>"
        b'<xbrldi:explicitMember dimension="dei:LegalEntityAxis">'
        b"sy:SubsidiaryMember</xbrldi:explicitMember>"
    )
    context = extract_contexts(raw)["c1"]
    assert [d for d, _ in context.members] == [
        "us-gaap:StatementClassOfStockAxis", "dei:LegalEntityAxis"
    ]
    assert context.legal_entity_members == ["sy:SubsidiaryMember"]
    assert context.is_membered

    # The CIK matches and the content alone would resolve to true...
    assert context.identifier_value == _ROW["cik"]
    facts = extract_shell_facts(raw)
    assert len(facts) == 1
    assert evaluate_fact(facts[0])[0] == "true"

    # ...yet nothing is assignable, so no exclusion can be drawn.
    record = determine_for_row(_ROW, raw)
    assert record["shell_company"] == "unknown"
    assert record["shell_company"] != "true"
    assert record["assignable_facts"] == 0
    assert record["facts_in_document"] == 1
    assert record["basis"] == "no_fact_assignable_to_this_cik"
    assert "LegalEntityAxis" in record["detail"]
    assert "sy:SubsidiaryMember" in record["detail"]


def test_legal_entity_axis_is_matched_case_insensitively():
    raw = _one_context_document(
        b'<xbrldi:explicitMember dimension="us-gaap:ProductOrServiceAxis">'
        b"us-gaap:SoftwareMember</xbrldi:explicitMember>"
        b'<xbrldi:explicitMember dimension="DEI:LegalEntityAXIS">'
        b"sy:SubsidiaryMember</xbrldi:explicitMember>"
    )
    assert extract_contexts(raw)["c1"].is_membered
    assert determine_for_row(_ROW, raw)["shell_company"] == "unknown"


def test_members_on_other_axes_alone_do_not_block_assignment():
    """The rule is legal-entity-specific, not "any member disqualifies"."""
    raw = _one_context_document(
        b'<xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">'
        b"us-gaap:CommonClassAMember</xbrldi:explicitMember>"
        b'<xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">'
        b"srt:SoftwareMember</xbrldi:explicitMember>"
    )
    context = extract_contexts(raw)["c1"]
    assert len(context.members) == 2
    assert context.legal_entity_members == []
    assert not context.is_membered
    record = determine_for_row(_ROW, raw)
    assert record["shell_company"] == "true"
    assert record["assignable_facts"] == 1


# --- raw-fact provenance ----------------------------------------------------


def test_byte_range_is_half_open_and_hashes_exactly_that_slice(tmp_path):
    raw = (BUNDLE_DIR / "shell_false_ballotbox_decimal.html").read_bytes()
    facts = extract_shell_facts(raw)
    assert len(facts) == 1
    fact = facts[0]
    sliced = raw[fact.byte_start:fact.byte_end]
    assert sha256(sliced).hexdigest() == fact.element_sha256
    assert sliced.startswith(b"<ix:nonNumeric")
    assert sliced.endswith(b"</ix:nonNumeric>")
    # Half-open: the end offset is exclusive.
    assert raw[fact.byte_end - 1:fact.byte_end] == b">"
    assert len(sliced) == fact.byte_end - fact.byte_start


def test_determinations_carry_full_provenance(tmp_path):
    result = _run(tmp_path)
    bundle = json.loads((BUNDLE_DIR / "bundle_manifest.json").read_text())
    by_cik = {d["cik"]: d for d in bundle["documents"]}
    for record in result.determinations:
        assert record["source_sha256"] == by_cik[record["cik"]]["source_sha256"]
        assert record["bundle_manifest_sha256"] == result.bundle_manifest_sha256
        assert set(record["carrier_provenance"]) == {
            "carrier_run_id", "carrier_manifest_sha256", "freeze_record_sha256"
        }
        if record["shell_company"] in ("true", "false"):
            assert record["fact_element_sha256"] is not None
            assert record["fact_byte_end"] > record["fact_byte_start"]


def test_extract_contexts_reads_identifier_and_member():
    raw = (BUNDLE_DIR / "shell_multi_registrant.html").read_bytes()
    contexts = extract_contexts(raw)
    assert len(contexts) == 3
    parent = contexts["d_2022"]
    assert parent.identifier_scheme == "http://www.sec.gov/CIK"
    assert parent.identifier_value == "0009300012"
    assert not parent.is_membered
    membered = contexts["d_2022_LegalEntityAxis-SubsidiaryOneMember"]
    assert membered.is_membered
    # Every context bears the same parent CIK; only the member differs.
    assert membered.identifier_value == "0009300012"


# --- the narrow boundary ----------------------------------------------------


def test_exactly_one_fact_is_set_and_no_other_flag_appears(tmp_path):
    result = _run(tmp_path)
    forbidden = ("investment_company", "asset_backed_issuer",
                 "non_operating_trust", "blank_check_precombination")
    for record in result.determinations:
        for name in forbidden:
            assert name not in record
            assert name not in json.dumps(record)


def test_module_does_not_import_issuer_filters_or_reach_a_network():
    import ast

    path = (
        ROOT / "src" / "dynamic_ai_products" / "ingestion"
        / "shell_company_determination.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("issuer_filters" in name for name in imported), sorted(imported)
    roots = {name.split(".")[0] for name in imported}
    assert not roots & {"httpx", "requests", "socket", "urllib"}


def test_true_is_the_only_exclusion_and_unknown_is_retained(tmp_path):
    result = _run(tmp_path)
    manifest = read_json(result.manifest_path)
    assert manifest["counts"]["firms_excluded"] == manifest["counts"]["shell_true"] == 1
    assert manifest["counts"]["shell_unknown"] == 7
    # Every row still has a determination: nothing is dropped.
    assert manifest["counts"]["determinations"] == manifest["counts"]["rows_considered"]


# --- bundle integrity, immutability, CLI ------------------------------------


def test_tampered_document_refuses_the_run(tmp_path):
    from dynamic_ai_products.ingestion.baseline_packet import PacketBundleError

    bundle = tmp_path / "bundle"
    shutil.copytree(BUNDLE_DIR, bundle)
    target = bundle / "shell_false_ballotbox_decimal.html"
    target.write_bytes(target.read_bytes() + b"<!-- tampered -->")
    with pytest.raises(PacketBundleError, match="mismatch"):
        _run(tmp_path, run_id="tampered", bundle=bundle)
    assert not (tmp_path / "out").exists()


def test_rerun_of_an_existing_run_id_is_refused(tmp_path):
    _run(tmp_path, run_id="immutable")
    before = sorted(p.name for p in (tmp_path / "out" / "immutable").iterdir())
    with pytest.raises(FileExistsError):
        _run(tmp_path, run_id="immutable")
    assert sorted(
        p.name for p in (tmp_path / "out" / "immutable").iterdir()
    ) == before


def test_dry_run_writes_nothing(tmp_path):
    result = _run(tmp_path, run_id="dry", dry_run=True)
    assert result.run_dir is None and result.manifest_path is None
    assert result.counts == EXPECTED["counts"]
    assert not (tmp_path / "out").exists()


def test_invalid_run_id_is_refused(tmp_path):
    with pytest.raises(ShellDeterminationError, match="Invalid run id"):
        _run(tmp_path, run_id="bad/id")


def test_cli_mode(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "determine-shell-company",
            "--bundle-dir", str(BUNDLE_DIR),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-shell",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["counts"] == EXPECTED["counts"]
    assert all(payload["reconciliation"].values())


def test_cli_rejects_cross_mode_flags(tmp_path):
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable, str(CLI),
            "--mode", "determine-shell-company",
            "--bundle-dir", str(BUNDLE_DIR),
            "--dera-dir", str(tmp_path),
            "--output-dir", str(tmp_path / "out"),
            "--run-id", "cli-shell-bad",
        ],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr


# --- the real combined filing, when it is present --------------------------


CANARY_BUNDLE = (
    ROOT / "data" / "runs" / "primary-document-canary"
    / "primary-document-canary-frame-v1-20260816"
)


@pytest.mark.skipif(
    not (CANARY_BUNDLE / "bundle_manifest.json").exists(),
    reason="local Canary B bundle absent; real-filing behaviour not checkable",
)
def test_real_combined_filing_splits_parent_from_subsidiaries(tmp_path):
    """Read-only: the measured Spire filing must behave as the fixture does."""
    result = _run(tmp_path, run_id="real-bundle", bundle=CANARY_BUNDLE)
    rows = _by_cik(result)
    parent = rows["0001126956"]
    assert parent["shell_company"] == "false"
    assert parent["facts_in_document"] == 3
    assert parent["assignable_facts"] == 1
    for cik in ("0000057183", "0000003146"):
        assert rows[cik]["shell_company"] == "unknown"
        assert rows[cik]["basis"] == "no_fact_assignable_to_this_cik"
    # Every other real filing resolves to false, and none is excluded.
    assert result.counts["shell_true"] == 0
    assert result.counts["firms_excluded"] == 0
