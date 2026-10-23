"""Dashboard flow (loop 2026-10-24-001): trend `leftover`, "저축 외 지출" wording, chart layout, annual summary box."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import budget, categories, records, stats
from conftest import cat_id

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
DASH = JS / "pages" / "dashboard.js"
CSS = ROOT / "app" / "static" / "css" / "app.css"
NODE = shutil.which("node")
M = "2026-08"
SAV = "저축·투자"

OLD_KEYS = ("month", "income", "expense", "plan", "savings", "savings_rate", "living_expense", "plan_diff")


def _rec(conn, kind, name, amount, month=M, **kw):
    return records.create_record(conn, {"kind": kind, "category_id": cat_id(conn, name), "amount": amount,
                                        "month": month, **kw})


def _base_month(conn, month=M):
    _rec(conn, "income", "급여", 1_000_000, month)
    _rec(conn, "expense", "식비", 300_000, month)
    _rec(conn, "expense", SAV, 500_000, month)


def _dash():
    return DASH.read_text(encoding="utf-8")


# ── server: trend leftover ──

def test_trend_rows_have_leftover_equal_income_minus_expense(conn):
    _base_month(conn, "2026-07")
    _rec(conn, "income", "급여", 2_000_000, M)
    _rec(conn, "expense", "식비", 400_000, M)
    rows = stats.trend(conn, "2026-06", "2026-09")
    assert len(rows) == 4
    for r in rows:
        assert "leftover" in r, r["month"]
        assert isinstance(r["leftover"], int) and not isinstance(r["leftover"], bool)
        assert r["leftover"] == r["income"] - r["expense"], r["month"]
    by = {r["month"]: r for r in rows}
    assert by["2026-07"]["leftover"] == 200_000
    assert by[M]["leftover"] == 1_600_000


def test_trend_default_basis_is_budget_leftover(conn):
    _base_month(conn)
    assert stats.trend(conn, M, M)[0]["leftover"] == stats.trend(conn, M, M, "budget")[0]["leftover"] == 200_000


def test_settled_month_leftover_zero(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 0
    assert t["income"] == t["expense"] == 1_000_000


def test_settled_to_non_savings_leftover_zero(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, "기타"))
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 0
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_overspent_month_leftover_negative(conn):
    _rec(conn, "income", "급여", 500_000)
    _rec(conn, "expense", "식비", 700_000)
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == -200_000
    assert t["leftover"] == t["income"] - t["expense"]


def test_zero_income_expense_only_leftover_negative_rate_none(conn):
    _rec(conn, "expense", "식비", 300_000)
    _rec(conn, "expense", SAV, 200_000)
    t = stats.trend(conn, M, M)[0]
    assert t["income"] == 0
    assert t["leftover"] == -500_000
    assert t["savings_rate"] is None


def test_empty_month_leftover_zero(conn):
    _base_month(conn, "2026-07")
    rows = {r["month"]: r for r in stats.trend(conn, "2026-07", "2026-09")}
    for m in (M, "2026-09"):
        assert rows[m]["leftover"] == 0
        assert rows[m]["income"] == rows[m]["expense"] == 0


def test_empty_db_trend_leftover_zero(conn):
    rows = stats.trend(conn, M, M)
    assert rows[0]["leftover"] == 0


def test_identity_before_settle(conn):
    _base_month(conn)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 500_000
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_identity_after_settle(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 700_000
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_identity_with_negative_savings_correction(conn):
    _base_month(conn)
    _rec(conn, "expense", SAV, -100_000)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 400_000
    assert t["leftover"] == 300_000
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_identity_with_negative_correction_after_settle(conn):
    _base_month(conn)
    _rec(conn, "expense", SAV, -100_000)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 0
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_settled_then_changed_month_leftover_follows_current_records(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    _rec(conn, "income", "급여", 100_000)
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 100_000 == t["income"] - t["expense"]
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]
    _rec(conn, "expense", "식비", 250_000)
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == -150_000 == t["income"] - t["expense"]


def test_no_savings_categories_leftover(conn):
    categories.update_category(conn, cat_id(conn, SAV), {"is_savings": False})
    _base_month(conn)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 0
    assert t["living_expense"] == t["expense"] == 800_000
    assert t["leftover"] == t["income"] - t["expense"] == 200_000


def test_cash_basis_leftover(conn):
    # income deposited in Sep, expenses paid across Aug/Sep/Oct
    _rec(conn, "income", "급여", 1_000_000, M, txn_date="2026-09-05")
    _rec(conn, "expense", SAV, 300_000, M, txn_date="2026-09-02")
    _rec(conn, "expense", "식비", 100_000, M, txn_date="2026-08-05", settle_date="2026-10-15")
    _rec(conn, "expense", "식비", 50_000, M)
    rows = stats.trend(conn, M, "2026-10", "cash")
    assert len(rows) == 3
    for r in rows:
        assert "leftover" in r, r["month"]
        assert r["leftover"] == r["income"] - r["expense"], r["month"]
    # the months differ from budget basis, so at least one row carries non-trivial numbers
    assert any(r["leftover"] != 0 for r in rows)


# ── server: existing keys unchanged ──

def test_trend_existing_keys_and_values_unchanged(conn):
    _base_month(conn)
    _rec(conn, "plan", "식비", 350_000)
    t = stats.trend(conn, M, M)[0]
    for k in OLD_KEYS:
        assert k in t, k
    assert t["month"] == M
    assert t["income"] == 1_000_000
    assert t["expense"] == 800_000
    assert t["plan"] == 350_000
    assert t["savings"] == 500_000
    assert t["savings_rate"] == 50.0
    assert t["living_expense"] == 300_000
    assert t["plan_diff"] is not None


def test_annual_months_have_leftover(conn):
    _base_month(conn, "2026-08")
    _rec(conn, "income", "급여", 1_000_000, "2026-09")
    _rec(conn, "expense", "식비", 1_200_000, "2026-09")
    a = stats.annual(conn, 2026)
    assert a["months"]
    for m in a["months"]:
        assert "leftover" in m, m["month"]
        assert m["leftover"] == m["income"] - m["expense"], m["month"]
    by = {m["month"]: m for m in a["months"]}
    assert by["2026-08"]["leftover"] == 200_000
    assert by["2026-09"]["leftover"] == -200_000


def test_annual_and_summary_top_level_keys_kept(conn):
    _base_month(conn, "2026-07")
    _base_month(conn)
    a = stats.annual(conn, 2026)
    for k in ("year", "basis", "months", "income", "expense", "plan", "savings", "savings_rate",
              "living_expense", "top_expenses", "top_incomes"):
        assert k in a, k
    s = stats.month_summary(conn, M)
    for k in ("income", "expense", "plan", "savings", "savings_rate", "prev_income", "prev_expense", "prev_savings",
              "plan_diff", "remaining_budget", "over_count", "pending_income", "basis", "basis_label", "month",
              "living_expense", "prev_living_expense", "savings_category_count"):
        assert k in s, k
    assert s["living_expense"] == 300_000 and s["prev_living_expense"] == 300_000


# ── API ──

def _api_records(client, rows):
    cats = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    for kind, name, amt, extra in rows:
        r = client.post("/api/records", json={"kind": kind, "category_id": cats[name], "amount": amt,
                                              "month": M, **extra})
        assert r.status_code == 200, r.text


def test_api_trend_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {}), ("expense", "식비", 300_000, {}),
                          ("expense", SAV, 500_000, {})])
    r = client.get("/api/stats/trend", params={"start": "2026-07", "end": M})
    assert r.status_code == 200
    rows = {x["month"]: x for x in r.json()}
    for x in rows.values():
        assert "leftover" in x
        assert x["leftover"] == x["income"] - x["expense"]
    assert rows[M]["leftover"] == 200_000
    assert rows["2026-07"]["leftover"] == 0


def test_api_trend_cash_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {"txn_date": "2026-09-03"}),
                          ("expense", "식비", 300_000, {"txn_date": "2026-08-10"}),
                          ("expense", SAV, 200_000, {"txn_date": "2026-09-20"})])
    r = client.get("/api/stats/trend", params={"start": M, "end": "2026-09", "basis": "cash"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    for x in rows:
        assert "leftover" in x
        assert x["leftover"] == x["income"] - x["expense"]


def test_api_annual_months_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {}), ("expense", "식비", 300_000, {})])
    a = client.get("/api/stats/annual", params={"year": 2026}).json()
    by = {m["month"]: m for m in a["months"]}
    assert by[M]["leftover"] == 700_000
    assert "living_expense" in a and "savings_rate" in a


# ── static checks: dashboard.js / app.css ──

REQUIRED = ("저축 외 지출", "월별 수입·지출·저축 추이", "남은 돈", "저축률 = 저축액 ÷ 수입", "연간 저축 외 지출",
            "월평균 저축 외 지출", "연간 저축률", "leftover", "living_expense", "저축액", "실제 지출")
FORBIDDEN = ("생활비 지출", 'label: "지출 계획"', "저축액 · 저축률", "y1", "지출 계획 대비", "(수입−지출)",
             "수입 − 실제 지출")


@pytest.mark.parametrize("w", REQUIRED)
def test_dashboard_required_literal(w):
    assert w in _dash(), w


@pytest.mark.parametrize("w", FORBIDDEN)
def test_dashboard_forbidden_literal(w):
    assert w not in _dash(), w


def test_dashboard_old_trend_title_removed():
    src = _dash()
    # the new title "월별 수입·지출·저축 추이" does not contain "월별 수입·지출 추이"
    assert "월별 수입·지출 추이" not in src
    assert "월별 수입·지출·저축 추이" in src


def test_dashboard_rate_labels_plugin():
    src = _dash()
    assert "rateLabels" in src
    assert "afterDatasetsDraw" in src
    assert re.search(r"""id\s*:\s*["'`]rateLabels["'`]""", src)


def test_dashboard_annual_summary_boxed():
    src = _dash()
    assert 'class="kv boxed"' in src
    assert 'style="margin:0 0 10px"' not in src


def test_css_kv_boxed_rule():
    css = CSS.read_text(encoding="utf-8")
    assert ".kv.boxed" in css


@pytest.mark.skipif(NODE is None, reason="node 없음")
def test_dashboard_js_module_syntax():
    with open(DASH, "rb") as f:
        r = subprocess.run([NODE, "--check", "--input-type=module"], stdin=f, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-500:]
