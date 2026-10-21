"""Reconciliation of our calculation with the managers' files «Сверка КФГД на дату»
(real files of 31.12.2025, business process 6.5)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from models.db_models import CDU, SourceDocument
from services.import_primary.recon_parser import ProtectedWorkbookError, parse_reconciliation_xlsx
from tests.test_requirements_20260929 import stand  # noqa: F401

EXAMPLES = next((p / "Примеры" for p in Path(__file__).resolve().parents[2:4] if (p / "Примеры").exists()),
                Path(__file__).resolve().parents[2] / "Примеры")
RECON_DIR = EXAMPLES / "Сверки ЧДУ 31.12.2025"
RR_3112 = EXAMPLES / "risk report_31122025_.xlsm"
needs_files = pytest.mark.skipif(not RECON_DIR.exists(), reason="файлы сверок 31.12.2025 недоступны")
needs_rr = pytest.mark.skipif(not RR_3112.exists(), reason="Risk Report 31.12.2025 недоступен")

HALYK = RECON_DIR / "Сверка КФГД за 31.12.2025 Halyk.xlsx"


@needs_files
@pytest.mark.parametrize("name, cdu, n_sec, n_repo, securities, repo, cash, total", [
    ("Сверка КФГД за 31.12.2025 Halyk.xlsx", "Halyk Finance", 15, 2,
     45_073_872_789.99, 12_439_558_695.87, 910_169.24, 57_514_341_655.10),
    ("Сверка КФГД за 31.12.2025 Centras.xlsx", "Centras Securities", 54, 4,
     26_995_793_517.14, 2_862_059_678.43, 147_121.26, 29_858_000_316.83),
    ("Приложение 3 Сверка_JI_31 12 2025.xlsx", "Jusan Invest", 19, 8,
     31_100_519_812.65, 3_476_497_591.03, 5_192_696.11, 34_582_210_099.79),
    ("Сверка КФГД за 31.12.25 UD.xlsx", "UD Capital", 17, 27,
     27_179_330_898.09, 2_328_023_151.30, 488_705.36, 29_507_842_754.75),
    ("Сверка за 31.12.2025 Tansar.xlsx", "Tansar Capital", 19, 9,
     18_238_081_114.48, 5_319_980_601.01, 864_513.97, 23_558_926_229.45),
])
def test_all_manager_layouts_are_parsed_line_by_line(name, cdu, n_sec, n_repo, securities, repo, cash, total):
    from services.calculator.constants import normalize_cdu_name
    r = parse_reconciliation_xlsx(RECON_DIR / name)
    assert normalize_cdu_name(r["cdu_name"]) == cdu
    assert r["report_date"].isoformat() == "2025-12-31"
    assert (len(r["securities"]), len(r["repos"])) == (n_sec, n_repo)
    t = r["totals"]
    assert t["securities"] == pytest.approx(securities, abs=0.01)
    assert t["repo"] == pytest.approx(repo, abs=0.01)
    assert t["cash"] == pytest.approx(cash, abs=0.01)
    assert t["total"] == pytest.approx(total, abs=0.01)
    assert r["warnings"] == []
    # every line has a real ISIN; value = nominal × dirty price (or clean price + accrued)
    for x in r["securities"]:
        assert x["isin"] and x["face_value"] and x["value"]
        by_dirty = x["face_value"] * x["dirty_price"] / 100
        by_clean = x["face_value"] * x["price"] / 100 + (x["accrued"] or 0)
        assert min(abs(by_dirty - x["value"]), abs(by_clean - x["value"])) <= 1e-4 * x["value"]


@needs_files
def test_layout_variants_nominal_per_unit_rates_as_fraction_and_closed_repos():
    tansar = parse_reconciliation_xlsx(RECON_DIR / "Сверка за 31.12.2025 Tansar.xlsx")
    first = tansar["securities"][0]          # «Номинальная стоимость» = 1000 per security
    assert (first["quantity"], first["face_value"]) == (2_011_007, 2_011_007_000)
    ji = parse_reconciliation_xlsx(RECON_DIR / "Приложение 3 Сверка_JI_31 12 2025.xlsx")
    assert ji["securities"][0]["rate_pct"] == pytest.approx(10.67)       # 0.1067 in the file
    ud = parse_reconciliation_xlsx(RECON_DIR / "Сверка КФГД за 31.12.25 UD.xlsx")
    closed = [x for x in ud["repos"] if x["closed"]]
    assert len(closed) == 24 and all(x["value_effective"] == 0 for x in closed)   # repaid on 31.12


@needs_files
def test_password_protected_file_gives_a_clear_message(stand):
    client, _, _ = stand
    path = RECON_DIR / "Сверка КФГД на 31 12 2025 BCC Invest.xlsx"
    with pytest.raises(ProtectedWorkbookError):
        parse_reconciliation_xlsx(path)
    r = client.post("/api/primary-data/upload", files={"file": (path.name, path.read_bytes())}).json()
    assert r["status"] == "FAILED" and "паролем" in r["message"]


def _rr(Session):
    from services.import_rr.risk_report_importer import import_risk_report
    with Session() as db:
        res = import_risk_report(db, RR_3112, skip_if_imported=False)
        assert res.error is None
        db.commit()


@needs_files
@needs_rr
def test_our_calculation_matches_manager_files_and_differences_are_explained(stand, tmp_path):
    client, Session, _ = stand
    _rr(Session)
    ok = client.post("/api/primary-data/upload", files={"file": (HALYK.name, HALYK.read_bytes())}).json()
    assert ok["status"] == "DONE" and "расхождений нет" in ok["message"]

    # the manager reports another quantity and price for one issue, misses a REPO and adds a bond
    wb = load_workbook(HALYK)
    ws = wb["Лист1"]
    assert ws["C7"].value == "KZKD00000535"
    ws["D7"] = 6_200_000
    ws["E7"] = 6_200_000_000
    ws["J7"] = 88.20
    ws["M7"] = 5_723_428_000
    ws["C28"] = None                          # first REPO line removed
    ws["B28"] = None
    ws["F28"] = None
    ws["J28"] = None
    buf = io.BytesIO()
    wb.save(buf)
    changed = client.post("/api/primary-data/upload",
                          files={"file": ("Сверка КФГД за 31.12.2025 Halyk v2.xlsx", buf.getvalue())}).json()
    assert changed["status"] == "DONE" and "есть расхождения" in changed["message"]

    with Session() as db:
        halyk = db.query(CDU).filter_by(short_name="Halyk").one()
    ov = client.get("/api/reconciliation/overview", params={"recon_date": "2025-12-31"}).json()
    row = next(r for r in ov["rows"] if r["cdu_id"] == halyk.id)
    assert row["file"]["file_name"].endswith("v2.xlsx")
    res = row["results"]["rr_vs_holdings"]
    assert res["status"] == "MISMATCH"
    d = client.get(f"/api/reconciliation/result/{res['id']}").json()["details"]
    line = next(s for s in d["securities"] if s["isin"] == "KZKD00000535")
    assert line["status"] == "DIFF" and {"quantity", "price"} <= set(line["fields"])
    assert any("Количество: у ЧДУ 6 200 000, у нас 6 250 000" in r for r in line["reasons"])
    assert sum(1 for s in d["securities"] if s["status"] == "OK") == 12
    only_ours = [r for r in d["repos"] if r["status"] == "ONLY_OURS"]
    assert len(only_ours) == 1 and only_ours[0]["ours"]["open_amount"] == pytest.approx(72_026_395.34)
    summary = {s["key"]: s for s in d["summary"]}
    assert summary["cash"]["status"] == "OK" and summary["securities"]["status"] == "DIFF"

    x = client.get(f"/api/reconciliation/result/{res['id']}/export")
    assert x.status_code == 200
    wb2 = load_workbook(io.BytesIO(x.content))
    assert wb2.sheetnames == ["Итоги", "Ценные бумаги", "Обратное РЕПО"]


@needs_files
def test_file_without_manager_is_listed_and_bound_manually(stand):
    client, Session, _ = stand
    data = HALYK.read_bytes()
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Лист1"]
    ws["C1"] = None                                   # no manager name in the file
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/primary-data/upload", files={"file": ("Сверка за 31.12.2025.xlsx", buf.getvalue())}).json()
    assert "ЧДУ не определён" in r["message"]
    ov = client.get("/api/reconciliation/overview", params={"recon_date": "2025-12-31"}).json()
    assert len(ov["unbound_files"]) == 1
    doc_id = ov["unbound_files"][0]["doc_id"]
    with Session() as db:
        halyk = db.query(CDU).filter_by(short_name="Halyk").one()
    b = client.put(f"/api/primary-data/documents/{doc_id}", json={"cdu_id": halyk.id}).json()
    assert b["ok"] and b["message"]                     # reconciliation ran right after binding
    with Session() as db:
        assert db.get(SourceDocument, doc_id).cdu_id == halyk.id
