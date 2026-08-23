"""ADR-125 tests: the human layer is bound as tightly as the model layer.

Everything is offline and every identity is obviously synthetic. No real
decision, quote, reviewer or label appears here or anywhere in the
implementation; the production ledger is supplied separately.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import human_review_overlay as hro
from dynamic_ai_products import lineage_screen_continuation_v5 as lc5
from dynamic_ai_products import lineage_screen_diagnostic as ld
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products import lineage_screen_release as lrel
from dynamic_ai_products import lineage_screen_repair as lr
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_live import PACKET_FIXTURES, ROOT, _fixture_doc  # noqa: E402
from test_lineage_screen_live_v3 import _v5_run  # noqa: E402

CLOCK = lambda: datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731

DECISION_SCHEMA = json.loads(
    (ROOT / hro.DECISION_SCHEMA).read_text(encoding="utf-8"))
OVERLAY_SCHEMA = json.loads(
    (ROOT / hro.MANIFEST_SCHEMA).read_text(encoding="utf-8"))

_GOOGLE_BASELINE: set[str] | None = None


def _google_modules() -> set[str]:
    return {n for n in sys.modules if n == "google" or n.startswith("google.")}


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the overlay path imported google: {sorted(added)}"


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


# --- a synthetic release with real packets behind it -------------------------------


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    """Four real fixture packets, so quotes resolve against genuine passages."""
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = []
    for index in range(4):
        cik = f"{8100000000 + index:010d}"
        docs.append((source, dict(template, cik=cik, accession=f"{cik}-22-000001")))
    built = _v5_run(tmp_path_factory.mktemp("adr125-cohort"), [docs])
    assert len(built.packets) == 4
    return built


def _release_row(packet, origin, *, status=None, base_reason=None,
                 repair_reason=None):
    """One release row in the committed release-record shape."""
    raw = f'{{"cik": "{packet["cik"]}"}}'
    base_chain = {"run_id": "synthetic-base-run",
                  "raw_response_id": f"base-{packet['cik']}",
                  "raw_response_sha256": _sha(raw.encode()),
                  "failure_reason_code": base_reason, "source_row_ordinal": 1}
    repair_chain = {"run_id": "synthetic-repair-run",
                    "raw_response_id": f"repair-{packet['cik']}",
                    "raw_response_sha256": _sha((raw + "r").encode()),
                    "failure_reason_code": repair_reason,
                    "source_row_ordinal": None}
    row = {
        "record_contract": lrel.RECORD_CONTRACT,
        "release_origin": origin,
        "record_kind": ("screened_packet" if status else
                        "model_evidence_unverified"),
        "cik": packet["cik"], "company_id": packet["company_id"],
        "accession": packet["accession"], "form": packet["form"],
        "baseline_filing_date": packet["baseline_filing_date"],
        "source_id": packet["source_id"], "packet_sha256": packet["packet_sha256"],
        "prompt_sha256": _sha(b"p"),
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "screen_status": status,
        "screen_output": {"screen_status": status} if status else None,
        "failure_reason_code": None if status else repair_reason,
        "failure_detail": None if status else "detail",
        "truncation_evidence": None,
        "release_provenance": {
            "base": base_chain,
            "repair": repair_chain if origin in ("repaired",
                                                 "unresolved_after_repair") else None},
    }
    if origin == "base_valid":
        row["release_provenance"]["base"]["failure_reason_code"] = None
    return row


@pytest.fixture
def release(cohort, tmp_path):
    """Two validated rows and two unresolved rows, over real packets."""
    packets = cohort.packets
    rows = [
        _release_row(packets[0], "base_valid", status="LIKELY_ELIGIBLE"),
        _release_row(packets[1], "unresolved_after_repair",
                     base_reason="quote_resolution_failure",
                     repair_reason="quote_resolution_failure"),
        _release_row(packets[2], "base_valid", status="LIKELY_INELIGIBLE"),
        _release_row(packets[3], "unresolved_after_repair",
                     base_reason="adapter_rejection",
                     repair_reason="quote_resolution_failure"),
    ]
    d = tmp_path / "release" / "synthetic-release"
    d.mkdir(parents=True, exist_ok=True)
    records = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                      for r in rows).encode()
    (d / lrel.RELEASE_RECORDS_FILENAME).write_bytes(records)
    # the base run the release names, carrying the packet chain
    base_dir = tmp_path / "base" / "synthetic-base-run"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_manifest = {
        "manifest_contract": "universe_screen_continuation_manifest@0.12.0",
        "run_id": "synthetic-base-run",
        "packet_manifest_path": str(cohort.manifest_path),
        "packet_manifest_sha256": _sha(Path(cohort.manifest_path).read_bytes()),
        # the digest lives in the packet manifest's output hashes; read it the
        # way the loader does rather than re-deriving a key name
        "packets_jsonl_sha256": ls.load_packet_run(
            ROOT, cohort.manifest_path).packets_jsonl_sha256,
    }
    base_path = base_dir / lc5.CONTINUATION_V5_MANIFEST_FILENAME
    base_path.write_bytes(
        (json.dumps(base_manifest, indent=2, sort_keys=True) + "\n").encode())
    manifest = {
        "manifest_contract": lrel.MANIFEST_CONTRACT,
        "release_id": "synthetic-release", "release_kind": "screen_release_v1",
        "counts": {
            "planned_rows": len(rows), "cohort_rows": len(rows),
            "base_valid": 2, "repaired": 0, "unresolved_after_repair": 2,
            "insufficient_evidence": 0, "model_output_truncated": 0,
            "valid_screened_rows": 2, "max_unresolved_after_repair": 211,
            "by_screen_status": {"LIKELY_ELIGIBLE": 1, "LIKELY_INELIGIBLE": 1,
                                 "BOUNDARY_OR_UNCERTAIN": 0}},
        "sources": {"base": {"run_id": "synthetic-base-run",
                             "manifest_path": str(base_path),
                             "manifest_sha256": _sha(base_path.read_bytes())}},
        "output_hashes": {lrel.RELEASE_RECORDS_FILENAME: _sha(records)},
    }
    path = d / lrel.RELEASE_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return SimpleNamespace(dir=d, path=path, manifest=manifest, rows=rows,
                           sha256=_sha(path.read_bytes()), base_path=base_path,
                           packets={(p["cik"], p["accession"]): p
                                    for p in cohort.packets})


def _quote(packet, ref="P001", length=40):
    """A genuine contiguous span from the packet's own passage body."""
    ordinal = int(ref[1:]) - 1
    return packet["passages"][ordinal]["text"][:length]


def _entry(release, packet, decision, *, ref="P001", quote=None,
           reviewer="synthetic-reviewer-1", protocol="synthetic-protocol-v0",
           **overrides):
    row = next(r for r in release.rows
               if (r["cik"], r["accession"]) == (packet["cik"], packet["accession"]))
    entry = {
        "cik": packet["cik"], "accession": packet["accession"],
        "base_failure_reason_code":
            row["release_provenance"]["base"]["failure_reason_code"],
        "repair_failure_reason_code":
            row["release_provenance"]["repair"]["failure_reason_code"],
        "decision": decision,
        "evidence": [{"passage_ref": ref,
                      "quote": _quote(packet, ref) if quote is None else quote}],
        "review_protocol_version": protocol, "reviewer_id": reviewer,
        "decision_timestamp": "2026-08-23T11:00:00+00:00",
    }
    entry.update(overrides)
    return entry


def _ledger(tmp_path, entries, *, name="ledger.json", contract=None):
    path = tmp_path / name
    path.write_bytes((json.dumps({
        "ledger_contract": contract or hro.LEDGER_CONTRACT,
        "decisions": entries}, indent=2, sort_keys=True) + "\n").encode())
    return path


def _unresolved_packets(release):
    return [release.packets[(r["cik"], r["accession"])] for r in release.rows
            if r["release_origin"] == "unresolved_after_repair"]


def _build(release, ledger_path, tmp_path, *, overlay_id="overlay-fixture",
           dry_run=False, release_sha=None):
    return hro.build_human_review_overlay(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release_sha or release.sha256,
        ledger_path=ledger_path, output_dir=tmp_path / "overlays",
        overlay_id=overlay_id, clock=CLOCK, dry_run=dry_run)


@pytest.fixture
def complete_ledger(release, tmp_path):
    a, b = _unresolved_packets(release)
    return _ledger(tmp_path, [_entry(release, a, "LIKELY_ELIGIBLE"),
                              _entry(release, b, "LIKELY_INELIGIBLE")])


# --- the happy path ----------------------------------------------------------------


def test_a_complete_ledger_becomes_an_overlay(release, complete_ledger, tmp_path):
    result = _build(release, complete_ledger, tmp_path)
    assert result.status == "completed"
    decisions = [json.loads(x) for x in
                 (result.overlay_dir / hro.OVERLAY_DECISIONS_FILENAME)
                 .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(decisions) == 2
    validator = Draft202012Validator(DECISION_SCHEMA, format_checker=FormatChecker())
    for record in decisions:
        validator.validate(record)
        assert record["release_id"] == "synthetic-release"
        assert record["release_manifest_sha256"] == release.sha256
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(OVERLAY_SCHEMA, format_checker=FormatChecker()).validate(
        manifest)
    assert manifest["coverage"] == {"unresolved_rows_in_release": 2,
                                    "decisions_supplied": 2,
                                    "coverage_is_exact": True}
    assert manifest["counts"]["by_decision"] == {
        "LIKELY_ELIGIBLE": 1, "LIKELY_INELIGIBLE": 1, "BOUNDARY_OR_UNCERTAIN": 0}
    assert all(manifest["reconciliation"].values())
    assert len(manifest["reconciliation"]) >= 12
    _assert_no_google()


def test_the_overlay_binds_the_packet_chain(release, complete_ledger, tmp_path):
    """Human evidence must be provably tied to the immutable Item 1 bytes."""
    result = _build(release, complete_ledger, tmp_path)
    source = json.loads(result.manifest_path.read_text(encoding="utf-8"))["packet_source"]
    assert source["base_run_id"] == "synthetic-base-run"
    assert source["packet_manifest_sha256"] == \
        _sha(Path(source["packet_manifest_path"]).read_bytes())
    declared = ls.load_packet_run(
        ROOT, source["packet_manifest_path"]).packets_jsonl_sha256
    assert source["packets_jsonl_sha256"] == declared
    assert source["quotes_resolved_against_packet_bytes"] is True


def test_passage_refs_match_the_committed_renderer(cohort):
    """The reviewer's P001 and the model's P001 are the same passage."""
    prompt = (ROOT / "prompts/discovery/universe_high_recall_screen.v5.md").read_text(
        encoding="utf-8")
    for packet in cohort.packets:
        _, refs = ld.render_diagnostic_prompt_with_citation_refs(prompt, packet)
        assert hro.passage_refs(packet) == refs


def test_an_ineligible_decision_is_retained(release, complete_ledger, tmp_path):
    result = _build(release, complete_ledger, tmp_path)
    decisions = [json.loads(x) for x in
                 (result.overlay_dir / hro.OVERLAY_DECISIONS_FILENAME)
                 .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert "LIKELY_INELIGIBLE" in {d["decision"] for d in decisions}


# --- refusals ----------------------------------------------------------------------


def test_a_gap_in_coverage_is_refused(release, tmp_path):
    a, _ = _unresolved_packets(release)
    ledger = _ledger(tmp_path, [_entry(release, a, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="coverage must be exact"):
        _build(release, ledger, tmp_path)


def test_a_duplicate_decision_is_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    ledger = _ledger(tmp_path, [_entry(release, a, "LIKELY_ELIGIBLE"),
                                _entry(release, b, "LIKELY_ELIGIBLE"),
                                _entry(release, a, "BOUNDARY_OR_UNCERTAIN")])
    with pytest.raises(ls.ScreenInputError, match="a second time"):
        _build(release, ledger, tmp_path)


def test_a_foreign_row_is_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    foreign = _entry(release, a, "LIKELY_ELIGIBLE")
    foreign["cik"] = "9999999999"
    ledger = _ledger(tmp_path, [_entry(release, a, "LIKELY_ELIGIBLE"),
                                _entry(release, b, "LIKELY_ELIGIBLE"), foreign])
    with pytest.raises(ls.ScreenInputError, match="not a row of"):
        _build(release, ledger, tmp_path)


def test_reviewing_a_validated_row_is_refused(release, tmp_path):
    """Only an unresolved row may be reviewed."""
    a, b = _unresolved_packets(release)
    validated = release.packets[(release.rows[0]["cik"], release.rows[0]["accession"])]
    entry = _entry(release, a, "LIKELY_ELIGIBLE")
    entry.update(cik=validated["cik"], accession=validated["accession"])
    ledger = _ledger(tmp_path, [_entry(release, a, "LIKELY_ELIGIBLE"),
                                _entry(release, b, "LIKELY_ELIGIBLE"), entry])
    with pytest.raises(ls.ScreenInputError, match="did not leave"):
        _build(release, ledger, tmp_path)


def test_a_wrong_release_digest_is_refused(release, complete_ledger, tmp_path):
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        _build(release, complete_ledger, tmp_path, release_sha="0" * 64)


def test_a_drifted_release_records_file_is_refused(release, complete_ledger,
                                                   tmp_path):
    path = release.dir / lrel.RELEASE_RECORDS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        _build(release, complete_ledger, tmp_path)


def test_a_quote_that_does_not_resolve_is_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    ledger = _ledger(tmp_path, [
        _entry(release, a, "LIKELY_ELIGIBLE",
               quote="text that appears in no passage of this packet"),
        _entry(release, b, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="does not appear verbatim"):
        _build(release, ledger, tmp_path)


def test_a_reference_the_packet_does_not_display_is_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    ledger = _ledger(tmp_path, [
        _entry(release, a, "LIKELY_ELIGIBLE", ref="P999", quote="anything"),
        _entry(release, b, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="does not display"):
        _build(release, ledger, tmp_path)


def _two_passage_packets(release, monkeypatch):
    """Split each fixture packet's single passage into two displayed passages.

    Every committed packet fixture renders one passage, so the reference-vs-quote
    case — a span that exists in the packet but not under the reference cited —
    is unreachable through them. That case is the one 119 model rows failed on,
    so it is exercised here by widening the packet at the loader seam rather
    than left untested.
    """
    widened = []
    for packet in release.packets.values():
        text = packet["passages"][0]["text"]
        half = max(len(text) // 2, 40)
        first, second = text[:half], text[half:]
        assert second and second not in first, "the halves must be distinguishable"
        widened.append(dict(packet, passages=[
            dict(packet["passages"][0], passage_id="synthetic-passage-1",
                 text=first),
            dict(packet["passages"][0], passage_id="synthetic-passage-2",
                 text=second)]))
    declared = json.loads(release.base_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(hro, "load_packet_run", lambda root, path: SimpleNamespace(
        packets=widened, packets_jsonl_sha256=declared["packets_jsonl_sha256"]))
    return {(p["cik"], p["accession"]): p for p in widened}


def test_a_quote_from_the_wrong_displayed_passage_is_refused(release, tmp_path,
                                                             monkeypatch):
    """A span that exists in the packet, but not under the reference cited."""
    widened = _two_passage_packets(release, monkeypatch)
    a, b = _unresolved_packets(release)
    wide_a = widened[(a["cik"], a["accession"])]
    second = wide_a["passages"][1]["text"][:40]
    ledger = _ledger(tmp_path, [
        _entry(release, a, "LIKELY_ELIGIBLE", ref="P001", quote=second),
        _entry(release, b, "LIKELY_ELIGIBLE",
               quote=widened[(b["cik"], b["accession"])]["passages"][0]["text"][:40])])
    with pytest.raises(ls.ScreenInputError, match="does not appear verbatim"):
        _build(release, ledger, tmp_path)


def test_the_same_quote_resolves_under_its_own_reference(release, tmp_path,
                                                         monkeypatch):
    """The other direction: cited correctly, the identical span is accepted."""
    widened = _two_passage_packets(release, monkeypatch)
    a, b = _unresolved_packets(release)
    wide_a = widened[(a["cik"], a["accession"])]
    second = wide_a["passages"][1]["text"][:40]
    ledger = _ledger(tmp_path, [
        _entry(release, a, "LIKELY_ELIGIBLE", ref="P002", quote=second),
        _entry(release, b, "LIKELY_ELIGIBLE",
               quote=widened[(b["cik"], b["accession"])]["passages"][0]["text"][:40])])
    result = _build(release, ledger, tmp_path)
    assert result.status == "completed"
    assert result.counts["evidence_items"] == 2


@pytest.mark.parametrize("field", [
    "evidence", "reviewer_id", "review_protocol_version", "decision_timestamp",
    "decision", "base_failure_reason_code", "repair_failure_reason_code",
])
def test_an_incomplete_decision_is_refused(release, tmp_path, field):
    a, b = _unresolved_packets(release)
    entry = _entry(release, a, "LIKELY_ELIGIBLE")
    del entry[field]
    ledger = _ledger(tmp_path, [entry, _entry(release, b, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="violates"):
        _build(release, ledger, tmp_path)


def test_evidence_free_decisions_are_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    entry = _entry(release, a, "LIKELY_ELIGIBLE")
    entry["evidence"] = []
    ledger = _ledger(tmp_path, [entry, _entry(release, b, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="violates"):
        _build(release, ledger, tmp_path)


def test_a_decision_outside_the_vocabulary_is_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    ledger = _ledger(tmp_path, [_entry(release, a, "PROBABLY_FINE"),
                                _entry(release, b, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="violates"):
        _build(release, ledger, tmp_path)


def test_mismatched_prior_failure_reasons_are_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    entry = _entry(release, a, "LIKELY_ELIGIBLE",
                   base_failure_reason_code="invalid_model_json")
    ledger = _ledger(tmp_path, [entry, _entry(release, b, "LIKELY_ELIGIBLE")])
    with pytest.raises(ls.ScreenInputError, match="but the release row carries"):
        _build(release, ledger, tmp_path)


def test_a_foreign_ledger_contract_is_refused(release, tmp_path):
    a, b = _unresolved_packets(release)
    ledger = _ledger(tmp_path, [_entry(release, a, "LIKELY_ELIGIBLE"),
                                _entry(release, b, "LIKELY_ELIGIBLE")],
                     contract="some_other_ledger@9.9.9")
    with pytest.raises(ls.ScreenInputError, match="ingests"):
        _build(release, ledger, tmp_path)


def test_a_drifted_packet_manifest_is_refused(release, complete_ledger, tmp_path,
                                              monkeypatch):
    """The Item 1 bytes may not move beneath a review."""
    base = json.loads(release.base_path.read_text(encoding="utf-8"))
    base["packet_manifest_sha256"] = "0" * 64
    release.base_path.write_bytes(
        (json.dumps(base, indent=2, sort_keys=True) + "\n").encode())
    manifest = json.loads(release.path.read_text(encoding="utf-8"))
    manifest["sources"]["base"]["manifest_sha256"] = _sha(
        release.base_path.read_bytes())
    release.path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    with pytest.raises(ls.ScreenInputError, match="Item 1 bytes have moved"):
        _build(release, complete_ledger, tmp_path,
               release_sha=_sha(release.path.read_bytes()))


def test_the_release_is_never_modified(release, complete_ledger, tmp_path):
    before = {str(p.relative_to(release.dir)): _sha(p.read_bytes())
              for p in sorted(release.dir.rglob("*")) if p.is_file()}
    result = _build(release, complete_ledger, tmp_path)
    assert result.status == "completed"
    assert {str(p.relative_to(release.dir)): _sha(p.read_bytes())
            for p in sorted(release.dir.rglob("*")) if p.is_file()} == before


def test_dry_run_and_write_once(release, complete_ledger, tmp_path):
    dry = _build(release, complete_ledger, tmp_path, dry_run=True)
    assert dry.status == "dry_run" and dry.overlay_dir is None
    assert not (tmp_path / "overlays").exists()
    first = _build(release, complete_ledger, tmp_path)
    assert first.status == "completed"
    with pytest.raises(FileExistsError):
        _build(release, complete_ledger, tmp_path)


# --- loaders -----------------------------------------------------------------------


def test_every_other_loader_refuses_the_overlay(release, complete_ledger, tmp_path):
    result = _build(release, complete_ledger, tmp_path)
    for loader in (ls.require_authoritative_screen_run,
                   ll.require_promotable_screen_run,
                   lc5.require_continuation_v5_run, lr.require_repair_run,
                   lrel.require_screen_release):
        with pytest.raises(ls.ScreenInputError):
            loader(result.overlay_dir)
    assert hro.require_human_review_overlay(result.overlay_dir).name == \
        hro.OVERLAY_MANIFEST_FILENAME


def test_the_overlay_loader_refuses_a_release(release, complete_ledger, tmp_path):
    _build(release, complete_ledger, tmp_path)
    with pytest.raises(ls.ScreenInputError):
        hro.require_human_review_overlay(release.dir)


def test_the_overlay_loader_refuses_a_drifted_decisions_file(release,
                                                             complete_ledger,
                                                             tmp_path):
    result = _build(release, complete_ledger, tmp_path)
    path = result.overlay_dir / hro.OVERLAY_DECISIONS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        hro.require_human_review_overlay(result.overlay_dir)


def test_the_template_is_a_scaffold_and_carries_no_decision():
    """The shipped template must never contain a real decision."""
    path = ROOT / "docs/templates/human_review_decision_ledger.template.json"
    template = json.loads(path.read_text(encoding="utf-8"))
    assert template["ledger_contract"] == hro.LEDGER_CONTRACT
    assert len(template["decisions"]) == 1
    entry = template["decisions"][0]
    assert entry["cik"] == "0000000000"
    assert entry["decision"] == ""
    assert entry["reviewer_id"] == ""
    assert entry["evidence"][0]["quote"] == ""
    assert entry["evidence"][0]["passage_ref"] == "P001"
