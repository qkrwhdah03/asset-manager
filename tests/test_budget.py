import sqlite3

import pytest

from app import db
from app.services import budget, records
from app.util import AppError
from conftest import cat_id

M = "2026-10"


def income(conn, amount, **kw):
    return records.create_record(conn, {"kind": "income", "category_id": cat_id(conn, "급여"), "amount": amount, **kw})


def spend(conn, name, amount, d="2026-10-10"):
    return records.create_record(conn, {"kind": "expense", "category_id": cat_id(conn, name), "amount": amount, "txn_date": d})


def test_budget_month_defaults_to_deposit_month(conn):
    r = income(conn, 3_000_000, month="2026-09", txn_date="2026-10-31")
    assert r["budget_month"] == "2026-10"
    pending = income(conn, 100, month="2026-10")
    assert pending["budget_month"] == "2026-10"
    chosen = income(conn, 200, month="2026-09", txn_date="2026-09-30", budget_month="2026-10")
    assert chosen["budget_month"] == "2026-10"
    b = budget.get_budget(conn, M)
    assert b["income_total"] == 3_000_300 and b["income_pending"] == 100
    assert budget.get_budget(conn, "2026-09")["income_total"] == 0


def test_allocation_and_spending(conn):
    income(conn, 1_000_000, month=M, txn_date="2026-10-01")
    budget.set_plan(conn, M, cat_id(conn, "식비"), 400_000)
    b = budget.set_plan(conn, M, cat_id(conn, "저축·투자"), 500_000)
    assert b["unallocated"] == 100_000
    spend(conn, "식비", 450_000)
    spend(conn, "취미", 30_000)  # 계획 외
    b = budget.get_budget(conn, M)
    env = {e["name"]: e for e in b["envelopes"]}
    assert env["식비"]["status"] == "over" and env["식비"]["remaining"] == -50_000
    assert env["취미"]["status"] == "unplanned" and env["취미"]["plan"] == 0
    assert env["저축·투자"]["remaining"] == 500_000
    assert b["leftover"] == 1_000_000 - 480_000
    assert env["교통비"]["status"] == "empty" and env["교통비"]["plan"] == 0  # 기록 없는 항목도 0원으로 표시


def test_set_plan_keeps_adjustments(conn):
    food, hobby = cat_id(conn, "식비"), cat_id(conn, "취미")
    budget.set_plan(conn, M, food, 300_000)
    budget.move_plan(conn, M, food, hobby, 50_000)
    b = budget.set_plan(conn, M, food, 280_000)  # 최종값 기준 편집
    env = {e["name"]: e for e in b["envelopes"]}
    assert env["식비"]["plan"] == 280_000 and env["식비"]["plan_base"] == 330_000
    assert env["취미"]["plan"] == 50_000


def test_move_plan_rules(conn):
    food, hobby = cat_id(conn, "식비"), cat_id(conn, "취미")
    budget.set_plan(conn, M, food, 100_000)
    with pytest.raises(AppError):
        budget.move_plan(conn, M, food, hobby, 200_000)
    with pytest.raises(AppError):
        budget.move_plan(conn, M, food, food, 1)
    with pytest.raises(AppError):  # 소득이 없으면 미배분도 없다(서버에서도 검사)
        budget.move_plan(conn, M, None, hobby, 10_000)
    income(conn, 110_000, month=M, txn_date="2026-10-01")
    with pytest.raises(AppError):
        budget.move_plan(conn, M, None, hobby, 10_001)
    b = budget.move_plan(conn, M, None, hobby, 10_000)  # 미배분에서
    assert {e["name"]: e["plan"] for e in b["envelopes"] if e["plan"]} == {"식비": 100_000, "취미": 10_000}


def test_settle_makes_income_equal_spending(conn):
    save = cat_id(conn, "저축·투자")
    income(conn, 1_000_000, month=M, txn_date="2026-10-01")
    budget.set_plan(conn, M, cat_id(conn, "식비"), 400_000)
    budget.set_plan(conn, M, cat_id(conn, "교통비"), 100_000)
    budget.set_plan(conn, M, save, 500_000)
    spend(conn, "식비", 350_000)
    spend(conn, "교통비", 120_000)
    records.create_record(conn, {"kind": "expense", "category_id": save, "amount": 500_000, "txn_date": "2026-10-02"})
    b = budget.settle(conn, M, save)
    assert b["settled"] and b["balanced"]
    assert b["income_total"] == b["plan_total"] == b["spent_total"] == 1_000_000
    env = {e["name"]: e for e in b["envelopes"]}
    assert env["식비"]["plan"] == 350_000 and env["식비"]["plan_base"] == 400_000  # 원래 계획 보존
    assert env["저축·투자"]["spent"] == 530_000  # 남은 30,000원이 저축으로
    assert all(e["remaining"] == 0 for e in b["envelopes"])
    again = budget.settle(conn, M)  # 다시 정산해도 결과가 같다(대상은 지난 정산 그대로)
    assert again["balanced"] and again["settle_target"] == save and again["spent_total"] == 1_000_000
    b = budget.unsettle(conn, M)
    assert not b["settled"] and b["spent_total"] == 970_000
    assert {e["name"]: e["plan"] for e in b["envelopes"]}["식비"] == 400_000


def test_settle_rejects_overspending(conn):
    income(conn, 100, month=M, txn_date="2026-10-01")
    spend(conn, "식비", 150)
    with pytest.raises(AppError) as e:
        budget.settle(conn, M, cat_id(conn, "저축·투자"))
    assert "50원" in str(e.value)


def test_copy_month_excludes_settlement(conn):
    save = cat_id(conn, "저축·투자")
    income(conn, 1000, month="2026-09", txn_date="2026-09-01")
    budget.set_plan(conn, "2026-09", cat_id(conn, "식비"), 600)
    budget.set_plan(conn, "2026-09", save, 400)
    records.create_record(conn, {"kind": "expense", "category_id": cat_id(conn, "식비"), "amount": 500, "txn_date": "2026-09-05"})
    budget.settle(conn, "2026-09", save)
    b = budget.copy_month(conn, "2026-09", M, items=False, amounts=True)
    assert {e["name"]: e["plan"] for e in b["envelopes"] if e["plan"]} == {"식비": 600, "저축·투자": 400}  # 정산 조정 제외


def test_same_categories_every_month_items_differ(conn):
    a = budget.get_budget(conn, "2026-01")
    b = budget.get_budget(conn, "2030-12")
    assert [i["name"] for i in a["income_items"]] == [i["name"] for i in b["income_items"]] == ["급여", "장학금"]
    assert [e["name"] for e in a["envelopes"]] == [e["name"] for e in b["envelopes"]]
    food = cat_id(conn, "식비")
    records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-10", "item": "마트", "amount": 50000})
    records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-10", "item": "외식", "amount": 20000})
    records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-11", "item": "회식", "amount": 7000})
    oct_food = next(e for e in budget.get_budget(conn, M)["envelopes"] if e["name"] == "식비")
    nov_food = next(e for e in budget.get_budget(conn, "2026-11")["envelopes"] if e["name"] == "식비")
    assert [i["item"] for i in oct_food["items"]] == ["마트", "외식"] and oct_food["spent"] == 70000
    assert [i["item"] for i in nov_food["items"]] == ["회식"]


def test_income_items_with_deposit_dates(conn):
    sch = cat_id(conn, "장학금")
    records.create_record(conn, {"kind": "income", "category_id": sch, "budget_month": M, "item": "국가장학금",
                                 "amount": 1_000_000, "txn_date": "2026-10-02"})
    records.create_record(conn, {"kind": "income", "category_id": sch, "budget_month": M, "item": "교내장학금", "amount": 300_000})
    it = next(i for i in budget.get_budget(conn, M)["income_items"] if i["name"] == "장학금")
    assert it["total"] == 1_300_000 and it["pending"] == 300_000 and it["count"] == 2


def test_migration_v3_to_v4_converts_subcategories(tmp_path):
    p = tmp_path / "v3.db"
    c = sqlite3.connect(p)
    for v in range(3):
        for stmt in db._split_sql(db.MIGRATIONS[v]):
            c.execute(stmt)
    c.execute("INSERT INTO categories (id, name, kind) VALUES (100, '부수입', 'income')")
    c.execute("INSERT INTO categories (id, name, kind, parent_id) VALUES (101, '과외', 'income', 100)")
    c.execute("INSERT INTO records (kind, category_id, amount, month, budget_month) VALUES ('income', 101, 400000, '2026-10', '2026-10')")
    c.execute("PRAGMA user_version = 3")
    c.commit(); c.close()
    conn = db.init_db(p)
    r = conn.execute("SELECT category_id, item, amount FROM records").fetchone()
    assert (r[0], r[1], r[2]) == (100, "과외", 400000)
    assert not conn.execute("SELECT 1 FROM categories WHERE parent_id IS NOT NULL").fetchone()
    conn.close()


def test_migration_v1_to_v2_fills_budget_month(tmp_path):
    p = tmp_path / "v1.db"
    c = sqlite3.connect(p)
    for stmt in db._split_sql(db.MIGRATIONS[0]):
        c.execute(stmt)
    c.execute("INSERT INTO categories (id, name) VALUES (1, '급여')")
    c.execute("INSERT INTO records (kind, category_id, amount, month, txn_date) VALUES ('income', 1, 100, '2026-09', '2026-10-31')")
    c.execute("INSERT INTO records (kind, category_id, amount, month) VALUES ('income', 1, 50, '2026-09')")
    c.execute("PRAGMA user_version = 1")
    c.commit()
    c.close()
    conn = db.init_db(p)
    assert db.get_version(conn) == db.SCHEMA_VERSION
    got = [r[0] for r in conn.execute("SELECT budget_month FROM records ORDER BY id")]
    assert got == ["2026-10", "2026-09"]
    assert conn.execute("SELECT 1 FROM categories WHERE name='저축·투자'").fetchone()
    assert conn.execute("SELECT kind FROM categories WHERE name='급여'").fetchone()[0] == "income"
    assert conn.execute("SELECT kind FROM categories WHERE name='저축·투자'").fetchone()[0] == "expense"
    conn.close()


def test_budget_api(client):
    cats = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    client.post("/api/records", json={"kind": "income", "category_id": cats["급여"], "amount": 1000, "month": M, "txn_date": "2026-10-01"})
    r = client.put("/api/budget/plan", json={"month": M, "category_id": cats["식비"], "amount": "1,000"})
    assert r.status_code == 200 and r.json()["unallocated"] == 0
    assert client.post("/api/budget/settle", json={"month": M, "category_id": cats["저축·투자"]}).json()["balanced"]


def test_resettle_after_edit(conn):
    save, food = cat_id(conn, "저축·투자"), cat_id(conn, "식비")
    income(conn, 1_000_000, month=M, txn_date="2026-10-01")
    budget.set_plan(conn, M, food, 400_000)
    budget.set_plan(conn, M, save, 600_000)
    meal = spend(conn, "식비", 300_000)
    b = budget.settle(conn, M, save)
    assert b["balanced"] and b["settle_target"] == save
    records.update_record(conn, meal["id"], {"amount": 350_000})  # 정산 후 지출이 바뀜
    b = budget.get_budget(conn, M)
    assert b["settled"] and not b["balanced"]
    assert b["leftover"] < 0 and b["leftover_before_settle"] == 650_000  # 정산분을 빼면 아직 남은 돈이 있다
    b = budget.settle(conn, M)
    assert b["balanced"] and b["spent_total"] == 1_000_000
    env = {e["name"]: e for e in b["envelopes"]}
    assert env["식비"]["plan"] == 350_000 and env["저축·투자"]["spent"] == 650_000
    assert conn.execute("SELECT COUNT(*) FROM records WHERE tag='settle' AND kind='expense'").fetchone()[0] == 1
    records.update_record(conn, meal["id"], {"amount": 2_000_000})  # 소득보다 더 쓰면 다시 정산이 거부되고 기존 정산은 유지된다
    with pytest.raises(AppError):
        budget.settle(conn, M)
    assert budget.get_budget(conn, M)["settled"]


def test_settle_needs_target_first_time(conn):
    income(conn, 100, month=M, txn_date="2026-10-01")
    with pytest.raises(AppError):
        budget.settle(conn, M)


def test_migration_v5_to_v6_cleans_unused_data(tmp_path):
    p = tmp_path / "old.db"
    c = db.connect(p)
    for v in range(5):
        for stmt in db._split_sql(db.MIGRATIONS[v]):
            c.execute(stmt)
    c.execute("PRAGMA user_version = 5")
    c.execute("INSERT INTO categories (name, kind, is_active) VALUES ('숨긴항목', 'expense', 0)")
    c.execute("INSERT INTO settings (key, value) VALUES ('income_basis', 'attribution')")
    c.commit()
    db.migrate(c, p)
    assert c.execute("SELECT is_active FROM categories WHERE name='숨긴항목'").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM settings WHERE key LIKE '%_basis'").fetchone()[0] == 0
    c.close()


def test_copy_month_items_and_amounts(conn):
    P = "2026-09"
    sal, food, hobby = cat_id(conn, "급여"), cat_id(conn, "식비"), cat_id(conn, "취미")
    records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 3_000_000, "budget_month": P, "item": "본봉"})
    records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 0, "budget_month": P, "item": ""})
    budget.set_plan(conn, P, food, 300_000)
    budget.set_plan(conn, P, hobby, 100_000)
    budget.move_plan(conn, P, hobby, food, 20_000)

    pv = budget.copy_preview(conn, P, M)
    assert (pv["income_items"], pv["income_all"], pv["plan_items"], pv["plan_total"]) == (1, 2, 2, 400_000)

    b = budget.copy_month(conn, P, M, items=True, amounts=False)  # 이름만
    assert b["copied"] == {"income_items": 1, "plan_items": 0}
    sal_items = next(i for i in b["income_items"] if i["category_id"] == sal)["items"]
    assert [(i["item"], i["amount"], i["txn_date"]) for i in sal_items] == [("본봉", 0, None)]
    assert b["plan_total"] == 0

    budget.set_plan(conn, M, food, 1)
    assert budget.copy_preview(conn, P, M)["plan_overwrite"] == 1
    b = budget.copy_month(conn, P, M, items=True, amounts=True)  # 같은 이름은 건너뛰고 계획 금액을 맞춘다
    env = {e["name"]: e["plan"] for e in b["envelopes"]}
    assert env["식비"] == 320_000 and env["취미"] == 80_000
    assert b["copied"]["income_items"] == 1  # 이름 없는 세부항목만 새로 추가
    with pytest.raises(AppError):
        budget.copy_month(conn, P, M, items=False, amounts=False)
