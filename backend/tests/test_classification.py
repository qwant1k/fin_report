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


def test_category_resolution():
    assert classify_instrument("EBRP", "KFUSb47") == "REVERSE_REPO"
    assert classify_instrument("EBWP", "MUM180_0013") == "REVERSE_REPO"
    assert classify_instrument("DEFAULT", "KFUSb47") == "GOV_BONDS"
    assert classify_instrument("DEFAULT", "EABRb40") == "AGENCY_BONDS"
    assert classify_instrument("DEFAULT", "MFOXX") == "MFO_BONDS"
    assert classify_instrument("DEFAULT", "ZZZ") == "OTHER"


def test_detect_cdu():
    assert detect_cdu_prefix("HALFN0BT13", "trade.xlsx") == "HALFN"
    assert detect_cdu_prefix(None, "BCC_trade.xlsx") == "BCC"
    assert detect_cdu_prefix("TANSR_MAIN", "trade.xlsx") == "TANSR"
    assert detect_cdu_prefix(None, "Alatau City Invest trade.xlsx") == "ALATAU"
    assert detect_cdu_prefix(None, "report.xlsx") is None
