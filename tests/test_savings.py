"""Savings categories ("is_savings") and the savings / savings-rate / living-expense definitions."""
import json
from pathlib import Path

import pytest

from app import messages
from app.services import backup, budget, categories, records, stats
from app.util import AppError
from conftest import cat_id

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
M = "2026-08"
SAV = "저축·투자"


def _settings_value(conn):
    r = conn.execute("SELECT value FROM settings WHERE key='savings_category_ids'").fetchone()
    return None if r is None else r["value"]


def _row(conn, name):
    return next(c for c in categories.list_categories(conn) if c["name"] == name)


def _rec(conn, kind, name, amount, month=M, **kw):
    return records.create_record(conn, {"kind": kind, "category_id": cat_id(conn, name), "amount": amount,
                                        "month": month, **kw})


def _base_month(conn, month=M):
    _rec(conn, "income", "급여", 1_000_000, month)
    _rec(conn, "expense", "식비", 300_000, month)
    _rec(conn, "expense", SAV, 500_000, month)


# ── categories: savings designation ──

def test_constants_exposed():
    assert categories.SAVINGS_KEY == "savings_category_ids"
    assert categories.SAVINGS_NAME_HINT.search("저축·투자")
    assert categories.SAVINGS_NAME_HINT.search("투자")
    assert not categories.SAVINGS_NAME_HINT.search("식비")


def test_seed_savings_by_name_hint(conn):
    assert categories.savings_category_ids(conn) == {cat_id(conn, SAV)}
    rows = categories.list_categories(conn)
    assert all("is_savings" in c for c in rows)
    assert _row(conn, SAV)["is_savings"] is True
    assert _row(conn, "식비")["is_savings"] is False
    assert _row(conn, "급여")["is_savings"] is False
    assert _settings_value(conn) is None


def test_get_category_has_is_savings(conn):
    assert categories.get_category(conn, cat_id(conn, SAV))["is_savings"] is True
    assert categories.get_category(conn, cat_id(conn, "식비"))["is_savings"] is False


def test_unset_savings_writes_empty_list_and_stops_name_hint(conn):
    sid = cat_id(conn, SAV)
    r = categories.update_category(conn, sid, {"is_savings": False})
    assert r["is_savings"] is False
    assert categories.savings_category_ids(conn) == set()
    assert _settings_value(conn) == "[]"
    categories.update_category(conn, sid, {"name": "저축과 투자"})
    assert categories.savings_category_ids(conn) == set()
    assert _row(conn, "저축과 투자")["is_savings"] is False


def test_create_with_is_savings(conn):
    c = categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": True})
    assert c["is_savings"] is True
    assert c["id"] in categories.savings_category_ids(conn)
    d = categories.create_category(conn, {"name": "비상금", "kind": "expense"})
    assert d["is_savings"] is False
    assert d["id"] not in categories.savings_category_ids(conn)


def test_settings_value_format_sorted_compact(conn):
    a = categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": True})["id"]
    categories.update_category(conn, cat_id(conn, "식비"), {"is_savings": True})
    v = _settings_value(conn)
    assert v is not None and " " not in v
    ids = json.loads(v)
    assert ids == sorted(ids)
    assert set(ids) == categories.savings_category_ids(conn)
    assert {a, cat_id(conn, "식비")} <= set(ids)


def test_plain_edit_does_not_create_settings_row(conn):
    food = cat_id(conn, "식비")
    categories.update_category(conn, food, {"name": "식비2", "color": "#123456", "memo": "메모"})
    assert _settings_value(conn) is None
    assert categories.savings_category_ids(conn) == {cat_id(conn, SAV)}


def test_savings_on_income_category_rejected(conn):
    with pytest.raises(AppError) as e:
        categories.update_category(conn, cat_id(conn, "급여"), {"is_savings": True})
    assert e.value.code == "category.savings_income_kind"


@pytest.mark.parametrize("bad", ["yes", None, 2])
def test_invalid_is_savings_value(conn, bad):
    with pytest.raises(AppError) as e:
        categories.update_category(conn, cat_id(conn, "식비"), {"is_savings": bad})
    assert e.value.code == "category.invalid_savings"


@pytest.mark.parametrize("bad", ["yes", None, 2])
def test_invalid_is_savings_value_on_create(conn, bad):
    with pytest.raises(AppError) as e:
        categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": bad})
    assert e.value.code == "category.invalid_savings"


def test_int_one_zero_accepted(conn):
    food = cat_id(conn, "식비")
    assert categories.update_category(conn, food, {"is_savings": 1})["is_savings"] is True
    assert food in categories.savings_category_ids(conn)
    assert categories.update_category(conn, food, {"is_savings": 0})["is_savings"] is False
    assert food not in categories.savings_category_ids(conn)


def test_deleted_savings_id_not_inherited(conn):
    c = categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": True})
    categories.delete_category(conn, c["id"])
    assert c["id"] not in json.loads(_settings_value(conn) or "[]")
    n = categories.create_category(conn, {"name": "새 항목", "kind": "expense"})
    assert n["is_savings"] is False
    assert n["id"] not in categories.savings_category_ids(conn)


def test_deleted_savings_id_not_inherited_bulk(conn):
    c = categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": True})
    categories.bulk_delete(conn, [c["id"]])
    assert c["id"] not in json.loads(_settings_value(conn) or "[]")
    n = categories.create_category(conn, {"name": "새 항목", "kind": "expense"})
    assert n["is_savings"] is False
    assert n["id"] not in categories.savings_category_ids(conn)


def test_delete_with_records_removes_from_list(conn):
    c = categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": True})
    records.create_record(conn, {"kind": "expense", "category_id": c["id"], "amount": 1000, "month": M})
    categories.delete_category(conn, c["id"], with_records=True)
    assert c["id"] not in json.loads(_settings_value(conn) or "[]")
    assert c["id"] not in categories.savings_category_ids(conn)


def test_kind_change_to_income_drops_from_list(conn):
    c = categories.create_category(conn, {"name": "적금", "kind": "expense", "is_savings": True})
    assert _settings_value(conn) is not None
    r = categories.update_category(conn, c["id"], {"kind": "income"})
    assert r["is_savings"] is False
    assert c["id"] not in categories.savings_category_ids(conn)
    assert _row(conn, "적금")["is_savings"] is False


@pytest.mark.parametrize("broken", ["abc", '["x"]', '{"a": 1}'])
def test_broken_settings_value_falls_back_to_name_hint(conn, broken):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('savings_category_ids', ?)", (broken,))
    assert categories.savings_category_ids(conn) == {cat_id(conn, SAV)}
    assert _row(conn, SAV)["is_savings"] is True
    stats.month_summary(conn, M)  # no error


def test_settings_list_ignores_nonexistent_ids(conn):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('savings_category_ids', ?)",
                     (json.dumps([cat_id(conn, "식비"), 99999], separators=(",", ":")),))
    assert categories.savings_category_ids(conn) == {cat_id(conn, "식비")}


def test_settings_list_ignores_income_ids(conn):
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('savings_category_ids', ?)",
                     (json.dumps([cat_id(conn, "급여")]),))
    assert categories.savings_category_ids(conn) == set()


def test_reset_all_restores_name_hint(conn):
    categories.update_category(conn, cat_id(conn, SAV), {"is_savings": False})
    assert categories.savings_category_ids(conn) == set()
    backup.reset(conn, "all")
    assert _settings_value(conn) is None
    assert categories.savings_category_ids(conn) == {cat_id(conn, SAV)}


def test_reset_records_keeps_designation(conn):
    categories.update_category(conn, cat_id(conn, SAV), {"is_savings": False})
    backup.reset(conn, "records")
    assert _settings_value(conn) == "[]"
    assert categories.savings_category_ids(conn) == set()


# ── settings API ──

def test_settings_api_rejects_savings_key(client):
    r = client.put("/api/settings", json={"savings_category_ids": "[1]"})
    assert r.status_code == 400
    assert r.json()["code"] == "settings.unknown_key"
    assert "savings_category_ids" not in client.get("/api/settings").json()


# ── categories API ──

def _api_cat(client, name):
    return next(c for c in client.get("/api/categories").json() if c["name"] == name)


def test_categories_api_is_savings(client):
    rows = client.get("/api/categories").json()
    assert rows and all("is_savings" in c for c in rows)
    assert _api_cat(client, SAV)["is_savings"] is True
    food = _api_cat(client, "식비")
    assert food["is_savings"] is False
    r = client.put(f"/api/categories/{food['id']}", json={"is_savings": True})
    assert r.status_code == 200
    assert r.json()["is_savings"] is True
    assert _api_cat(client, "식비")["is_savings"] is True


def test_categories_api_income_rejected(client):
    sal = _api_cat(client, "급여")
    r = client.put(f"/api/categories/{sal['id']}", json={"is_savings": True})
    assert r.status_code == 400
    assert r.json()["code"] == "category.savings_income_kind"


def test_categories_api_invalid_value(client):
    food = _api_cat(client, "식비")
    r = client.put(f"/api/categories/{food['id']}", json={"is_savings": "yes"})
    assert r.status_code == 400
    assert r.json()["code"] == "category.invalid_savings"


def test_categories_api_create_with_savings(client):
    r = client.post("/api/categories", json={"name": "적금", "kind": "expense", "is_savings": True})
    assert r.status_code == 200
    assert r.json()["is_savings"] is True
    assert _api_cat(client, "적금")["is_savings"] is True


# ── stats ──

def test_trend_new_definitions(conn):
    _base_month(conn)
    t = stats.trend(conn, M, M)[0]
    assert t["income"] == 1_000_000
    assert t["expense"] == 800_000
    assert t["savings"] == 500_000
    assert t["savings_rate"] == 50.0
    assert t["living_expense"] == 300_000
    for k in ("month", "plan", "plan_diff"):
        assert k in t


def test_settle_counts_as_savings(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 700_000
    assert t["savings_rate"] == 70.0
    assert t["living_expense"] == 300_000
    assert t["expense"] == 1_000_000


def test_unsettle_and_resettle_change_savings(conn):
    _base_month(conn)
    sav = cat_id(conn, SAV)
    budget.settle(conn, M, sav)
    budget.unsettle(conn, M)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 500_000 and t["expense"] == 800_000
    budget.settle(conn, M, sav)
    _rec(conn, "income", "급여", 100_000)
    budget.settle(conn, M, sav)  # re-settle: leftover now 300,000
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 800_000
    assert t["living_expense"] == 300_000
    assert t["expense"] == 1_100_000


def test_settle_to_non_savings_category_not_savings(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, "기타"))
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 500_000
    assert t["living_expense"] == 500_000


def test_plan_is_not_savings(conn):
    _rec(conn, "income", "급여", 1_000_000)
    _rec(conn, "plan", SAV, 400_000)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 0
    assert t["savings_rate"] == 0.0
    assert t["plan"] == 400_000


def test_negative_correction_on_savings_added(conn):
    _base_month(conn)
    _rec(conn, "expense", SAV, -100_000)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 400_000
    assert t["expense"] == 700_000
    assert t["living_expense"] == 300_000


def test_no_savings_categories(conn):
    categories.update_category(conn, cat_id(conn, SAV), {"is_savings": False})
    _base_month(conn)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 0
    assert t["savings_rate"] == 0.0
    assert t["living_expense"] == t["expense"] == 800_000
    s = stats.month_summary(conn, M)
    assert s["savings_category_count"] == 0
    assert s["savings"] == 0
    a = stats.annual(conn, 2026)
    assert a["savings"] == 0 and a["living_expense"] == a["expense"]
    assert stats.trend(conn, M, M, "cash")[0]["savings"] == 0


def test_zero_income_rate_none(conn):
    _rec(conn, "expense", SAV, 500_000)
    t = stats.trend(conn, M, M)[0]
    assert t["income"] == 0
    assert t["savings"] == 500_000
    assert t["savings_rate"] is None
    assert stats.month_summary(conn, M)["savings_rate"] is None


def test_negative_income_rate_none(conn):
    _rec(conn, "income", "급여", -10_000)
    _rec(conn, "expense", SAV, 5_000)
    assert stats.trend(conn, M, M)[0]["savings_rate"] is None


def test_month_summary_keys_and_prev(conn):
    prev = "2026-07"
    _rec(conn, "income", "급여", 2_000_000, prev)
    _rec(conn, "expense", "식비", 400_000, prev)
    _rec(conn, "expense", SAV, 600_000, prev)
    _base_month(conn)
    s = stats.month_summary(conn, M)
    for k in ("income", "expense", "plan", "savings", "savings_rate", "prev_income", "prev_expense", "prev_savings",
              "plan_diff", "remaining_budget", "over_count", "pending_income", "basis", "basis_label", "month",
              "living_expense", "prev_living_expense", "savings_category_count"):
        assert k in s, k
    assert s["savings_category_count"] == 1
    assert s["savings"] == 500_000 and s["savings_rate"] == 50.0
    assert s["living_expense"] == 300_000
    assert s["prev_savings"] == 600_000
    assert s["prev_living_expense"] == 400_000
    assert s["prev_expense"] == 1_000_000


def test_annual_new_definitions(conn):
    _base_month(conn, "2026-08")
    _rec(conn, "income", "급여", 1_000_000, "2026-09")
    _rec(conn, "expense", "식비", 200_000, "2026-09")
    _rec(conn, "expense", SAV, 100_000, "2026-09")
    a = stats.annual(conn, 2026)
    assert a["income"] == 2_000_000
    assert a["expense"] == 1_100_000
    assert a["savings"] == 600_000 == sum(m["savings"] for m in a["months"])
    assert a["savings_rate"] == 30.0
    assert a["living_expense"] == 500_000
    for k in ("year", "basis", "months", "plan", "top_expenses", "top_incomes"):
        assert k in a


def test_annual_rate_rounding(conn):
    _rec(conn, "income", "급여", 3_000_000)
    _rec(conn, "expense", SAV, 1_000_000)
    a = stats.annual(conn, 2026)
    assert a["savings_rate"] == 33.3
    assert stats.trend(conn, M, M)[0]["savings_rate"] == 33.3


def test_cash_basis_savings_month(conn):
    # income paid in Aug; savings expense recorded under Aug but dated in Sep
    _rec(conn, "income", "급여", 1_000_000, M, txn_date="2026-08-10")
    _rec(conn, "expense", SAV, 300_000, M, txn_date="2026-09-02")
    _rec(conn, "expense", SAV, 100_000, M, txn_date="2026-08-05", settle_date="2026-10-15")
    _rec(conn, "expense", SAV, 50_000, M)
    budget_t = stats.trend(conn, M, "2026-10")
    assert budget_t[0]["savings"] == 450_000 and budget_t[1]["savings"] == 0
    cash_t = {x["month"]: x for x in stats.trend(conn, M, "2026-10", "cash")}
    assert cash_t["2026-08"]["savings"] == 50_000
    assert cash_t["2026-09"]["savings"] == 300_000
    assert cash_t["2026-10"]["savings"] == 100_000
    for x in cash_t.values():
        assert x["living_expense"] == x["expense"] - x["savings"]


def test_stats_api_new_keys(client):
    cats = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    for kind, name, amt in (("income", "급여", 1_000_000), ("expense", "식비", 300_000), ("expense", SAV, 500_000)):
        r = client.post("/api/records", json={"kind": kind, "category_id": cats[name], "amount": amt, "month": M})
        assert r.status_code == 200, r.text
    s = client.get("/api/stats/summary", params={"month": M}).json()
    assert s["savings"] == 500_000 and s["living_expense"] == 300_000 and s["savings_category_count"] == 1
    t = client.get("/api/stats/trend", params={"start": M, "end": M}).json()[0]
    assert t["savings_rate"] == 50.0 and t["living_expense"] == 300_000
    a = client.get("/api/stats/annual", params={"year": 2026}).json()
    assert a["savings"] == 500_000 and a["living_expense"] == 300_000


# ── static UI checks ──

def test_dashboard_js_literals():
    src = (JS / "pages" / "dashboard.js").read_text(encoding="utf-8")
    for w in ("생활비 지출", "living_expense", "저축액", "실제 지출"):
        assert w in src, w
    for w in ("지출 계획 대비", "(수입−지출)", "수입 − 실제 지출"):
        assert w not in src, w


def test_settings_js_literals():
    src = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
    assert "is_savings" in src
    assert "저축에 체크한 항목은 대시보드에서 저축액으로 셉니다." in src


def test_savings_messages_korean():
    for code in ("category.invalid_savings", "category.savings_income_kind"):
        assert code in messages.MESSAGES, code
        assert any("가" <= ch <= "힣" for ch in messages.MESSAGES[code]), code
