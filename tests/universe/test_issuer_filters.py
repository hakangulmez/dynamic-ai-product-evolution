from dynamic_ai_products.universe.issuer_filters import (
    deduplicate_by_cik,
    evaluate_form_scope,
    evaluate_issuer_flags,
    run_issuer_filters,
)
from universe_test_helpers import make_filer

FORM_SCOPE = ["10-K", "10-KT"]


def test_each_exclusion_family_has_reason_code_and_evidence() -> None:
    cases = {
        "investment_company": "FUND_OR_INVESTMENT_COMPANY",
        "asset_backed_issuer": "ASSET_BACKED_ISSUER",
        "non_operating_trust": "TRUST_WITHOUT_OPERATING_BUSINESS",
        "shell_company": "SHELL_OR_PRECOMBINATION_SPAC",
        "blank_check_precombination": "SHELL_OR_PRECOMBINATION_SPAC",
    }
    for flag, expected_code in cases.items():
        filer = make_filer(
            issuer_status_flags={
                "investment_company": False,
                "asset_backed_issuer": False,
                "non_operating_trust": False,
                "shell_company": False,
                "blank_check_precombination": False,
                flag: True,
            }
        )
        decision = evaluate_issuer_flags(filer)
        assert decision.decision == "exclude"
        assert expected_code in decision.reason_codes
        assert decision.evidence, f"exclusion for {flag} must carry evidence"
        assert decision.rule_ids


def test_unsupported_form_is_excluded_with_reason() -> None:
    decision = evaluate_form_scope(make_filer(form="N-CSR"), FORM_SCOPE)
    assert decision is not None
    assert decision.reason_codes == ["NO_ELIGIBLE_ANNUAL_OPERATING_FILING"]


def test_unresolved_flag_yields_unknown_not_exclusion() -> None:
    filer = make_filer(
        issuer_status_flags={
            "investment_company": False,
            "asset_backed_issuer": False,
            "non_operating_trust": False,
            "shell_company": None,
            "blank_check_precombination": False,
        }
    )
    decision = evaluate_issuer_flags(filer)
    assert decision.decision == "unknown"
    assert not decision.reason_codes


def test_duplicate_cik_keeps_latest_and_flags_rest() -> None:
    first = make_filer(accession_number="0001000001-22-000001", ticker="AAA")
    second = make_filer(accession_number="0001000001-22-000002", ticker="AAA.B")
    kept, duplicates = deduplicate_by_cik([first, second])
    assert len(kept) == 1
    assert kept[0].accession_number == "0001000001-22-000002"
    assert len(duplicates) == 1
    assert duplicates[0].reason_codes == ["DUPLICATE_ISSUER_RECORD"]


def test_run_issuer_filters_never_silently_drops_a_record() -> None:
    operating = make_filer()
    fund = make_filer(
        cik="2000002",
        accession_number="0002000002-22-000001",
        issuer_status_flags={
            "investment_company": True,
            "asset_backed_issuer": False,
            "non_operating_trust": False,
            "shell_company": False,
            "blank_check_precombination": False,
        },
    )
    passing, decisions = run_issuer_filters([operating, fund], FORM_SCOPE)
    assert [f.cik for f in passing] == ["0001000001"]
    assert {d.cik for d in decisions} == {"0001000001", "0002000002"}
