import pytest

from app import db
from app.services import categories, records, stats
from app.util import AppError, parse_amount
from conftest import cat_id


def test_schema_version_and_seed(conn):
    assert db.get_version(conn) == db.SCHEMA_VERSION
    names = [c["name"] for c in categories.list_categories(conn)]
    assert "급여" in names and "식비" in names


def test_migrate_is_idempotent(tmp_path):
    p = tmp_path / "x.db"
    c = db.init_db(p)
    c.close()
    c = db.init_db(p)
    assert db.get_version(c) == db.SCHEMA_VERSION
    assert c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == len(db.DEFAULT_CATEGORIES) + 1  # + 저축·투자(v2)
    c.close()


def test_parse_amount():
    assert parse_amount("1,234,000원") == 1234000
    assert parse_amount(" 500 ") == 500
    with pytest.raises(AppError):
        parse_amount("12.5")
    with pytest.raises(AppError):
        parse_amount("-1")
    assert parse_amount("-1", allow_negative=True) == -1


def test_expense_items_shared_by_plan_and_expense_only(conn):
    cid = categories.create_category(conn, {"name": "용돈", "kind": "expense"})["id"]
    for kind in ("plan", "expense"):
        records.create_record(conn, {"kind": kind, "category_id": cid, "amount": 1000, "month": "2026-09"})
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "income", "category_id": cid, "amount": 1000, "month": "2026-09"})
    inc = categories.create_category(conn, {"name": "용돈", "kind": "income"})  # 종류가 다르면 같은 이름 허용
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "expense", "category_id": inc["id"], "amount": 1, "month": "2026-09"})
    assert len(records.list_records(conn, month="2026-09")) == 2


def test_income_counts_in_budget_month_and_follows_deposit_date(conn):
    sal = cat_id(conn, "급여")
    # 10/31 에 받은 급여를 11월에 쓸 돈으로 넣는다
    r = records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 3_000_000,
                                     "txn_date": "2026-10-31", "budget_month": "2026-11"})
    assert r["month"] == "2026-10" and r["budget_month"] == "2026-11"
    assert stats.month_summary(conn, "2026-11")["income"] == 3_000_000   # 기본: 예산 월 기준
    assert stats.month_summary(conn, "2026-10")["income"] == 0
    assert stats.month_summary(conn, "2026-10", "cash")["income"] == 3_000_000  # 입금일 기준
    # 예산 월을 안 주면 입금 월이 예산 월
    r2 = records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 1, "txn_date": "2026-12-05"})
    assert r2["budget_month"] == "2026-12"
    # 입금일을 바꾸면 month 도 따라간다
    r3 = records.update_record(conn, r["id"], {"txn_date": "2026-11-02"})
    assert r3["month"] == "2026-11" and r3["budget_month"] == "2026-11"
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 1})  # 입금일·예산 월 모두 없음


def test_pending_income_excluded_in_cash_basis(conn):
    sal = cat_id(conn, "급여")
    records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 100, "budget_month": "2026-10"})
    assert stats.month_summary(conn, "2026-10")["income"] == 100
    assert stats.month_summary(conn, "2026-10", "cash")["income"] == 0
    assert stats.pending_income(conn)["total"] == 100


def test_expense_settle_date_basis(conn):
    food = cat_id(conn, "식비")
    r = records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 12000,
                                     "txn_date": "2026-10-05", "settle_date": "2026-11-15"})
    assert r["month"] == "2026-10"  # 월은 발생일에서 유도
    assert stats.month_summary(conn, "2026-10")["expense"] == 12000
    assert stats.month_summary(conn, "2026-11", "cash")["expense"] == 12000
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 1,
                                     "txn_date": "2026-10-05", "settle_date": "2026-10-01"})


def test_plan_vs_actual(conn):
    food, trans, sub, hobby = (cat_id(conn, n) for n in ("식비", "교통비", "구독료", "취미"))
    m = "2026-10"
    for cid, amt in ((food, 300000), (trans, 100000), (sub, 20000)):
        records.create_record(conn, {"kind": "plan", "category_id": cid, "amount": amt, "month": m})
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 200000, "month": m})
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 150000, "month": m})
    records.create_record(conn, {"kind": "expense", "category_id": trans, "amount": 80000, "month": m})
    records.create_record(conn, {"kind": "expense", "category_id": hobby, "amount": 30000, "month": m})
    p = stats.plan_vs_actual(conn, m)
    by = {i["category_name"]: i for i in p["items"]}
    assert by["식비"]["diff"] == 50000 and by["식비"]["status"] == "over"
    assert by["교통비"]["diff"] == -20000 and by["교통비"]["status"] == "ok" and by["교통비"]["rate"] == 80.0
    assert by["구독료"]["status"] == "no_actual" and by["구독료"]["actual"] == 0
    assert by["취미"]["status"] == "unplanned"
    assert p["total_plan"] == 420000 and p["total_actual"] == 460000
    assert p["total_diff"] == 40000 and p["remaining_budget"] == -40000
    assert p["unplanned_actual"] == 30000


def test_trend_savings_and_rate(conn):
    sal, food = cat_id(conn, "급여"), cat_id(conn, "식비")
    records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 2_000_000, "month": "2026-08"})
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 500_000, "month": "2026-08"})
    t = stats.trend(conn, "2026-07", "2026-09")
    assert [x["month"] for x in t] == ["2026-07", "2026-08", "2026-09"]
    aug = t[1]
    # savings = expenses in savings categories only (not income - expense)
    assert aug["savings"] == 0 and aug["savings_rate"] == 0.0 and aug["living_expense"] == 500_000
    assert t[0]["savings_rate"] is None
    records.create_record(conn, {"kind": "expense", "category_id": cat_id(conn, "저축·투자"), "amount": 600_000,
                                 "month": "2026-08"})
    aug = stats.trend(conn, "2026-07", "2026-09")[1]
    assert aug["savings"] == 600_000 and aug["savings_rate"] == 30.0
    assert aug["expense"] == 1_100_000 and aug["living_expense"] == 500_000


def test_record_update_and_validation(conn):
    food = cat_id(conn, "식비")
    r = records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 1000, "month": "2026-10"})
    r2 = records.update_record(conn, r["id"], {"amount": "2,500", "memo": "수정"})
    assert r2["amount"] == 2500 and r2["memo"] == "수정" and r2["kind"] == "expense"
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "income", "category_id": food, "amount": 1, "month": "2026-13"})
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "income", "category_id": food, "amount": 0, "month": "2026-10"})
    with pytest.raises(AppError):
        records.create_record(conn, {"kind": "income", "category_id": food, "amount": 1, "month": "2026-10",
                                     "txn_date": "2026-02-30"})
    records.delete_record(conn, r["id"])
    assert records.list_records(conn) == []


def test_search_filter(conn):
    food = cat_id(conn, "식비")
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 1000, "month": "2026-10", "memo": "점심"})
    records.create_record(conn, {"kind": "expense", "category_id": cat_id(conn, "교통비"), "amount": 1000, "month": "2026-10"})
    assert len(records.list_records(conn, q="점심")) == 1
    assert len(records.list_records(conn, q="식")) == 1
    assert len(records.list_records(conn, category_id=food)) == 1


def test_category_delete_needs_confirmation_when_used(conn):
    hobby = cat_id(conn, "취미")
    records.create_record(conn, {"kind": "expense", "category_id": hobby, "amount": 5000, "month": "2026-09", "item": "책"})
    with pytest.raises(AppError) as e:
        categories.delete_category(conn, hobby)
    assert "1건" in str(e.value)
    r = categories.delete_category(conn, hobby, with_records=True)
    assert r["records_deleted"] == 1
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert not conn.execute("SELECT 1 FROM categories WHERE id=?", (hobby,)).fetchone()
    unused = categories.create_category(conn, {"name": "임시", "kind": "expense"})["id"]
    assert categories.delete_category(conn, unused)["records_deleted"] == 0


def test_category_rename_keeps_records_and_kind_rules(conn):
    hobby = cat_id(conn, "취미")
    records.create_record(conn, {"kind": "expense", "category_id": hobby, "amount": 1, "month": "2026-10"})
    categories.update_category(conn, hobby, {"name": "취미·여가"})
    assert records.list_records(conn)[0]["category_name"] == "취미·여가"
    with pytest.raises(AppError):
        categories.update_category(conn, hobby, {"kind": "income"})
    with pytest.raises(AppError):
        categories.create_category(conn, {"name": "식비", "kind": "expense"})
    assert categories.create_category(conn, {"name": "식비", "kind": "income"})["kind"] == "income"


def test_category_reorder(conn):
    food, trans, hobby = cat_id(conn, "식비"), cat_id(conn, "교통비"), cat_id(conn, "취미")
    categories.reorder(conn, hobby, food)
    names = [c["name"] for c in categories.list_categories(conn, kind="expense")]
    assert names.index("취미") == names.index("식비") - 1
    categories.reorder(conn, food, None)
    assert [c["name"] for c in categories.list_categories(conn, kind="expense")][-1] == "식비"


def test_items_and_bulk_delete(conn):
    food = cat_id(conn, "식비")
    a = records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-10", "item": "마트", "amount": 0})
    assert a["amount"] == 0 and a["item"] == "마트"
    b = records.update_record(conn, a["id"], {"amount": "12,000"})
    assert b["amount"] == 12000 and b["item"] == "마트"
    c = records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-10", "item": "외식", "amount": 30000})
    assert len(records.list_records(conn, q="외식")) == 1
    assert records.bulk_delete_records(conn, [a["id"], c["id"]])["deleted"] == 2
    assert records.list_records(conn) == []



def test_category_bulk_delete_with_records(conn):
    a = categories.create_category(conn, {"name": "A", "kind": "expense"})["id"]
    b = categories.create_category(conn, {"name": "B", "kind": "expense"})["id"]
    records.create_record(conn, {"kind": "expense", "category_id": a, "month": "2026-10", "item": "x", "amount": 1})
    records.create_record(conn, {"kind": "plan", "category_id": b, "month": "2026-10", "amount": 2})
    r = categories.bulk_delete(conn, [a, b])
    assert r == {"deleted": 2, "records_deleted": 2}
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def test_category_memo(conn):
    from app.services import budget
    c = categories.create_category(conn, {"name": "생활용품", "kind": "expense", "memo": "세제·휴지 등"})
    assert c["memo"] == "세제·휴지 등"
    categories.update_category(conn, c["id"], {"memo": "세제, 휴지, 주방용품"})
    assert categories.get_category(conn, c["id"])["memo"] == "세제, 휴지, 주방용품"
    env = next(e for e in budget.get_budget(conn, "2026-10")["envelopes"] if e["name"] == "생활용품")
    assert env["memo"] == "세제, 휴지, 주방용품"


def test_move_records_all_some_and_to_new_item(conn):
    from app.services import budget
    food, hobby = cat_id(conn, "식비"), cat_id(conn, "취미")
    a = records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-09", "amount": 100})
    b = records.create_record(conn, {"kind": "plan", "category_id": food, "month": "2026-10", "amount": 200})
    c = records.create_record(conn, {"kind": "expense", "category_id": food, "month": "2026-10", "amount": 300})
    before = budget.get_budget(conn, "2026-10")["spent_total"]
    # 일부 옮기기(= 나누기)
    assert records.move_records(conn, [c["id"]], hobby)["moved"] == 1
    assert budget.get_budget(conn, "2026-10")["spent_total"] == before  # 합계는 그대로
    # 새 항목을 만들면서 옮기기
    r = records.move_records(conn, [a["id"]], new_category={"name": "외식", "color": "#ff0000"})
    new = categories.get_category(conn, r["category_id"])
    assert new["name"] == "외식" and new["kind"] == "expense"
    # 전체 옮기기(= 합치기) 후 빈 항목 삭제
    records.move_records(conn, [b["id"]], hobby)
    assert categories.delete_category(conn, food)["records_deleted"] == 0
    # 규칙: 소득↔지출 섞기 금지, 새 항목 이름 중복이면 아무것도 바뀌지 않음
    sal = records.create_record(conn, {"kind": "income", "category_id": cat_id(conn, "급여"), "budget_month": "2026-10", "amount": 1})
    with pytest.raises(AppError):
        records.move_records(conn, [sal["id"]], hobby)
    with pytest.raises(AppError):
        records.move_records(conn, [c["id"]], new_category={"name": "취미"})
    assert conn.execute("SELECT category_id FROM records WHERE id=?", (c["id"],)).fetchone()[0] == hobby


def test_pending_income_by_month(conn):
    sal = cat_id(conn, "급여")
    records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 100, "budget_month": "2026-09"})
    records.create_record(conn, {"kind": "income", "category_id": sal, "amount": 200, "budget_month": "2026-10"})
    assert stats.pending_income(conn, "2026-10") == {"count": 1, "total": 200}
    assert stats.month_summary(conn, "2026-10")["pending_income"]["total"] == 200
    assert stats.pending_income(conn)["total"] == 300
