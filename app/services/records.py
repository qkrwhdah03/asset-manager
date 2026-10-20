"""수입 / 지출 계획 / 실제 지출 기록 CRUD."""
import sqlite3

from ..db import transaction
from ..util import AppError, clean_text, month_of, parse_amount, parse_date, parse_month, rows
from .categories import RECORD_KIND_TO_CATEGORY

KINDS = ("income", "plan", "expense")
KIND_LABEL = {"income": "수입", "plan": "지출 계획", "expense": "실제 지출"}


def validate_record(conn: sqlite3.Connection, data: dict, existing: dict | None = None) -> dict:
    merged = {**(existing or {}), **data}
    kind = merged.get("kind")
    if kind not in KINDS:
        raise AppError("기록 구분이 올바르지 않습니다(income/plan/expense).")
    try:
        category_id = int(merged.get("category_id"))
    except (TypeError, ValueError):
        raise AppError("항목을 선택하세요.") from None
    cat = conn.execute("SELECT id, is_active, kind FROM categories WHERE id = ?", (category_id,)).fetchone()
    if not cat:
        raise AppError("선택한 항목이 존재하지 않습니다.")
    new_link = existing is None or existing.get("category_id") != category_id
    # 소득 기록은 소득 항목에, 계획·지출 기록은 지출 항목에만 연결한다(예전 데이터의 기존 연결은 유지).
    if new_link and cat["kind"] != RECORD_KIND_TO_CATEGORY[kind]:
        raise AppError("수입은 소득 항목에, 지출 계획·실제 지출은 지출 항목에만 기록할 수 있습니다.")

    # 금액: 환불·정정을 위해 음수 허용. 막 추가한 세부항목은 0원일 수 있다.
    amount = parse_amount(merged.get("amount") if merged.get("amount") not in (None, "") else 0, allow_negative=True)
    memo = clean_text(merged.get("memo"), 500)
    item = clean_text(merged.get("item"), 60)
    txn_date = settle_date = budget_month = None

    if kind == "income":
        # 소득은 입금일과 예산 월(어느 달에 쓸 돈인지)만 의미가 있다. month 는 입금일의 달(미입금이면 예산 월)로 맞춘다.
        txn_date = parse_date(merged.get("txn_date"), "입금일", required=False)
        bm, m = merged.get("budget_month"), merged.get("month")
        budget_month = (parse_month(bm, "예산 월") if bm
                        else month_of(txn_date) or (parse_month(m, "월") if m else None))
        if not budget_month:
            raise AppError("입금일 또는 예산 월을 입력하세요.")
        month = month_of(txn_date) or budget_month
    elif kind == "plan":
        month = parse_month(merged.get("month"), "계획 월")
    else:
        txn_date = parse_date(merged.get("txn_date"), "발생일", required=False)
        settle_date = parse_date(merged.get("settle_date"), "결제일", required=False)
        m = merged.get("month")
        month = parse_month(m, "월") if m else month_of(txn_date)
        if not month:
            raise AppError("월 또는 발생일을 입력하세요.")
        if settle_date and txn_date and settle_date < txn_date:
            raise AppError("결제일은 발생일보다 빠를 수 없습니다.")
    return dict(kind=kind, category_id=category_id, amount=amount, month=month,
                txn_date=txn_date, settle_date=settle_date, budget_month=budget_month, memo=memo, item=item)


def get_record(conn, rid: int) -> dict:
    r = conn.execute(
        """SELECT r.*, c.name AS category_name, p.name AS parent_name, c.color AS category_color,
                  c.is_active AS category_active
           FROM records r JOIN categories c ON c.id = r.category_id
           LEFT JOIN categories p ON p.id = c.parent_id WHERE r.id = ?""",
        (rid,),
    ).fetchone()
    if not r:
        raise AppError("기록을 찾을 수 없습니다.")
    return _decorate(dict(r))


def _decorate(r: dict) -> dict:
    r["category_full_name"] = f"{r['parent_name']} > {r['category_name']}" if r.get("parent_name") else r["category_name"]
    return r


def create_record(conn, data: dict) -> dict:
    v = validate_record(conn, data)
    with conn:
        cur = conn.execute(
            """INSERT INTO records (kind, category_id, amount, month, txn_date, settle_date, budget_month, memo, item)
               VALUES (:kind, :category_id, :amount, :month, :txn_date, :settle_date, :budget_month, :memo, :item)""",
            v,
        )
    return get_record(conn, cur.lastrowid)


def update_record(conn, rid: int, data: dict) -> dict:
    existing = dict(conn.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone() or {})
    if not existing:
        raise AppError("기록을 찾을 수 없습니다.")
    data = {k: v for k, v in data.items() if k != "kind"}  # 구분 변경은 허용하지 않는다
    v = validate_record(conn, data, existing)
    with conn:
        conn.execute(
            """UPDATE records SET category_id=:category_id, amount=:amount, month=:month, txn_date=:txn_date,
               settle_date=:settle_date, budget_month=:budget_month, memo=:memo, item=:item, updated_at=datetime('now','localtime') WHERE id=:id""",
            {**v, "id": rid},
        )
    return get_record(conn, rid)


def move_records(conn, ids: list, category_id=None, new_category: dict | None = None) -> dict:
    """기록(세부항목)을 다른 항목으로 옮긴다. 합치기·나누기·분류 변경은 모두 이 기능의 조합이다.

    - category_id   : 옮겨 갈 기존 항목
    - new_category  : {"name", "kind", "color"} 를 주면 그 항목을 만들어서 옮긴다(생성과 이동을 한 트랜잭션으로).
    같은 종류(소득↔소득, 지출↔지출)끼리만 옮길 수 있다. 기록을 지우지 않으므로 월별 합계는 그대로다.
    """
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise AppError("옮길 기록 목록이 올바르지 않습니다.") from None
    if not ids:
        raise AppError("옮길 기록을 하나 이상 고르세요.")
    marks = ",".join("?" * len(ids))
    kinds = {RECORD_KIND_TO_CATEGORY[r["kind"]] for r in conn.execute(f"SELECT kind FROM records WHERE id IN ({marks})", ids)}
    if len(kinds) != 1:
        raise AppError("소득 기록과 지출 기록은 함께 옮길 수 없습니다.")
    want = kinds.pop()
    from . import categories as cats  # 순환 참조를 피하려고 함수 안에서 불러온다
    with transaction(conn):
        if new_category:
            v = cats._validate(conn, {**new_category, "kind": want})
            order = conn.execute("SELECT IFNULL(MAX(sort_order),0)+1 FROM categories WHERE kind=?", (want,)).fetchone()[0]
            cid = conn.execute("INSERT INTO categories (name, kind, color, memo, sort_order) VALUES (?,?,?,?,?)",
                               (v["name"], want, v["color"], v["memo"], order)).lastrowid
        else:
            try:
                cid = int(category_id)
            except (TypeError, ValueError):
                raise AppError("옮겨 갈 항목을 고르세요.") from None
            cat = conn.execute("SELECT kind FROM categories WHERE id=?", (cid,)).fetchone()
            if not cat:
                raise AppError("옮겨 갈 항목이 존재하지 않습니다.")
            if cat["kind"] != want:
                raise AppError("소득 기록은 소득 항목으로, 지출 기록은 지출 항목으로만 옮길 수 있습니다.")
        n = conn.execute(f"UPDATE records SET category_id=?, updated_at=datetime('now','localtime') WHERE id IN ({marks})",
                         (cid, *ids)).rowcount
    return {"moved": n, "category_id": cid}


def bulk_delete_records(conn, ids: list) -> dict:
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise AppError("삭제할 기록 목록이 올바르지 않습니다.") from None
    if not ids:
        return {"deleted": 0}
    with conn:
        n = conn.execute(f"DELETE FROM records WHERE id IN ({','.join('?' * len(ids))})", ids).rowcount
    return {"deleted": n}


def delete_record(conn, rid: int) -> None:
    with conn:
        cur = conn.execute("DELETE FROM records WHERE id = ?", (rid,))
    if cur.rowcount == 0:
        raise AppError("기록을 찾을 수 없습니다.")


def month_expr(kind: str, basis: str) -> str:
    """기록이 어느 달에 집계되는지 결정하는 SQL 식.

    basis='budget' : 월 예산과 같은 기준. 소득=예산 월, 계획·지출=그 달
    basis='cash'   : 소득=실제 입금일의 월(미입금은 집계 제외), 지출=결제일>발생일>월 순
    """
    if kind == "plan":
        return "r.month"
    if basis == "budget":
        return "COALESCE(r.budget_month, r.month)" if kind == "income" else "r.month"
    if kind == "income":
        return "substr(r.txn_date, 1, 7)"
    return "COALESCE(substr(r.settle_date, 1, 7), substr(r.txn_date, 1, 7), r.month)"


def list_records(conn, kind: str | None = None, month: str | None = None, basis: str = "budget",
                 start: str | None = None, end: str | None = None, category_id: int | None = None,
                 q: str | None = None) -> list[dict]:
    where, params = [], []
    if kind:
        if kind not in KINDS:
            raise AppError("기록 구분이 올바르지 않습니다.")
        where.append("r.kind = ?")
        params.append(kind)
        mexpr = month_expr(kind, basis)
    else:
        mexpr = "r.month"
    if month:
        where.append(f"{mexpr} = ?")
        params.append(parse_month(month))
    if start:
        where.append(f"{mexpr} >= ?")
        params.append(parse_month(start))
    if end:
        where.append(f"{mexpr} <= ?")
        params.append(parse_month(end))
    if category_id:
        where.append("r.category_id = ?")
        params.append(category_id)
    if q:
        where.append("(c.name LIKE ? OR r.item LIKE ? OR r.memo LIKE ?)")
        like = f"%{q.strip()}%"
        params += [like, like, like]
    sql = f"""
        SELECT r.*, c.name AS category_name, p.name AS parent_name, c.color AS category_color,
               c.is_active AS category_active, {mexpr} AS stat_month
        FROM records r JOIN categories c ON c.id = r.category_id
        LEFT JOIN categories p ON p.id = c.parent_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY r.month DESC, COALESCE(p.sort_order, c.sort_order), c.sort_order, r.id
    """
    return [_decorate(r) for r in rows(conn.execute(sql, params))]
