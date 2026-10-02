"""Tests for operation/category classification."""
from services.parser.classification import (
    classify_instrument,
    classify_operation,
    detect_cdu_prefix,
)


def test_repo_classification():
    assert classify_operation("EBRP", "Разм") == "REPO_HEADER"
    assert classify_operation("EBRP", "К") == "REPO_OPEN"
    assert classify_operation("EBRP", "П") == "REPO_CLOSE"
    assert classify_operation("REPO", "Разм") == "REPO_HEADER"
    assert classify_operation("REPO", "К") == "REPO_OPEN"
    assert classify_operation("REPO", "П") == "REPO_CLOSE"
    assert classify_operation("EBWP", "S", type_code="G") == "REPO_HEADER"
    assert classify_operation("EBWP", "B", type_code="H") == "REPO_OPEN"
    assert classify_operation("EBWP", "S", type_code="h") == "REPO_CLOSE"


def test_outright_classification():
    assert classify_operation("DEFAULT", "К") == "BUY"
    assert classify_operation("DEFAULT", "П") == "SELL"
    assert classify_operation(None, None) == "OTHER"


def test_foreign_currency_bond_is_not_misclassified_as_fx():
    assert classify_operation(
        "TQOG", "К", instrument_code="US91282CJL63", currency_code="USD",
    ) == "BUY"
    assert classify_operation(
        "FXDE", "К", instrument_code="USDKZT_TOM", currency_code="KZT",
    ) == "FX_BUY"
    assert classify_operation(
        "DEFAULT", "П", instrument_code="EURKZT_TOD", currency_code="KZT",
    ) == "FX_SELL"


def test_category_resolution():
    assert classify_instrument("EBRP", "KFUSb47") == "REVERSE_REPO"
    assert classify_instrument("EBWP", "MUM180_0013") == "REVERSE_REPO"
    # Business process 6.2.2 D and the real Risk Report: KFUS (АО «КФУ») sits
    # on the «Агентские» sheet, EABR (ЕАБР) on the «МФО» sheet.
    assert classify_instrument("DEFAULT", "KFUSb47") == "AGENCY_BONDS"
    assert classify_instrument("DEFAULT", "MUM072_0016") == "GOV_BONDS"
    assert classify_instrument("DEFAULT", "NTK091_3053") == "GOV_BONDS"
    assert classify_instrument("DEFAULT", "EABRb40") == "MFO_BONDS"
    # KASE «MFO…» tickers are МИКРОфинансовые организации — not МФО.
    assert classify_instrument("DEFAULT", "MFOKb3") == "OTHER"
    assert classify_instrument("DEFAULT", "XS2027948582") == "FOREIGN_BONDS"
    assert classify_instrument("DEFAULT", "ZZZ") == "OTHER"


def test_detect_cdu():
    assert detect_cdu_prefix("HALFN0BT13", "trade.xlsx") == "HALFN"
    assert detect_cdu_prefix(None, "BCC_trade.xlsx") == "BCC"
    assert detect_cdu_prefix("TANSR_MAIN", "trade.xlsx") == "TANSR"
    assert detect_cdu_prefix(None, "Alatau City Invest trade.xlsx") == "ALATAU"
    assert detect_cdu_prefix(None, "report.xlsx") is None
    # BCC Invest trades under KASE code KIBAM; Halyk files carry the clearing
    # member «CENTR_K» which must not turn them into Centras.
    assert detect_cdu_prefix("KIBAM0BT11|KIBAM|I+1KINS00457", "11.09.2025 сделки.xlsx") == "KIBAM"
    assert detect_cdu_prefix("HALFN0BT13|HALFN", "trade.xlsx") == "HALFN"
    assert detect_cdu_prefix(None, "STUDY report.xlsx") is None
