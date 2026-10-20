"""항목 관리 (설정 화면).

항목은 모든 달에 똑같이 적용된다. 종류(kind):
- income  : 소득 항목 (급여, 장학금 …)
- expense : 지출 항목. 지출 계획은 항목 단위로 세운다.
각 달의 실제 기록은 항목 아래 '세부항목'(records.item)으로 자유롭게 남긴다.
항목을 지우면 그 항목의 기록도 함께 지운다(화면에서 기록 수를 보여 주고 확인받는다).
"""
import re
import sqlite3

from ..util import AppError, clean_text, rows

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
KINDS = {"income": "소득", "expense": "지출"}
RECORD_KIND_TO_CATEGORY = {"income": "income", "plan": "expense", "expense": "expense"}


def list_categories(conn: sqlite3.Connection, include_inactive: bool = True, kind: str | None = None) -> list[dict]:
    sql = """
        SELECT c.*, (SELECT COUNT(*) FROM records r WHERE r.category_id = c.id) AS record_count
        FROM categories c
    """
    where, params = [], []
    if not include_inactive:
        where.append("c.is_active = 1")
    if kind:
        where.append("c.kind = ?")
        params.append(kind)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.kind = 'expense', c.sort_order, c.id"
    out = rows(conn.execute(sql, params))
    for c in out:
        c["is_active"] = bool(c["is_active"])
        c["full_name"] = c["name"]
    return out


def get_category(conn, cid: int) -> dict:
    r = conn.execute("SELECT * FROM categories WHERE id = ?", (cid,)).fetchone()
    if not r:
        raise AppError.of("category.not_found")
    return dict(r)


def _validate(conn, data: dict, cid: int | None = None) -> dict:
    name = clean_text(data.get("name"), 50)
    if not name:
        raise AppError.of("category.name_required")
    kind = data.get("kind") or "expense"
    if kind not in KINDS:
        raise AppError.of("category.invalid_kind")
    if cid is not None and get_category(conn, cid)["kind"] != kind:
        wrong = ("income",) if kind == "expense" else ("plan", "expense")
        marks = ",".join("?" * len(wrong))
        if conn.execute(f"SELECT 1 FROM records WHERE category_id=? AND kind IN ({marks})", (cid, *wrong)).fetchone():
            raise AppError.of("category.kind_locked")
    color = clean_text(data.get("color"), 7) or None
    if color and not COLOR_RE.match(color):
        raise AppError.of("category.invalid_color")
    if conn.execute("SELECT 1 FROM categories WHERE kind=? AND parent_id IS NULL AND name=? AND id<>?",
                    (kind, name, cid or -1)).fetchone():
        raise AppError.of(f"category.duplicate_{kind}", name=name)
    return dict(name=name, kind=kind, color=color, icon=clean_text(data.get("icon"), 8) or None,
                memo=clean_text(data.get("memo"), 200),
                is_active=1, sort_order=int(data.get("sort_order") or 0))  # 비활성화 기능은 없앴다(v6). 항목은 삭제만 한다.


def create_category(conn, data: dict) -> dict:
    v = _validate(conn, data)
    if "sort_order" not in data:
        v["sort_order"] = conn.execute("SELECT IFNULL(MAX(sort_order),0)+1 FROM categories WHERE kind=?", (v["kind"],)).fetchone()[0]
    with conn:
        cur = conn.execute(
            "INSERT INTO categories (name, kind, color, icon, memo, is_active, sort_order) VALUES (?,?,?,?,?,?,?)",
            (v["name"], v["kind"], v["color"], v["icon"], v["memo"], v["is_active"], v["sort_order"]),
        )
    return get_category(conn, cur.lastrowid)


def update_category(conn, cid: int, data: dict) -> dict:
    v = _validate(conn, {**get_category(conn, cid), **data}, cid)
    with conn:
        conn.execute(
            """UPDATE categories SET name=?, kind=?, color=?, icon=?, memo=?, is_active=?, sort_order=?,
               updated_at=datetime('now','localtime') WHERE id=?""",
            (v["name"], v["kind"], v["color"], v["icon"], v["memo"], v["is_active"], v["sort_order"], cid),
        )
    return get_category(conn, cid)


def reorder(conn, cid: int, before_id) -> list[dict]:
    """드래그로 옮기기: cid 를 같은 종류 안에서 before_id 바로 앞(None 이면 맨 끝)에 둔다."""
    c = get_category(conn, cid)
    before_id = int(before_id) if before_id not in (None, "", 0) else None
    sibs = [r["id"] for r in conn.execute(
        "SELECT id FROM categories WHERE kind=? AND id<>? ORDER BY sort_order, id", (c["kind"], cid))]
    sibs.insert(sibs.index(before_id) if before_id in sibs else len(sibs), cid)
    with conn:
        for order, sid in enumerate(sibs):
            conn.execute("UPDATE categories SET sort_order=? WHERE id=?", (order, sid))
    return list_categories(conn)


def delete_category(conn, cid: int, with_records: bool = False) -> dict:
    """항목을 지운다. 기록이 있으면 with_records=True 일 때만 기록과 함께 지운다."""
    get_category(conn, cid)
    n = conn.execute("SELECT COUNT(*) FROM records WHERE category_id = ?", (cid,)).fetchone()[0]
    if n and not with_records:
        raise AppError.of("category.has_records", count=n)
    with conn:
        conn.execute("DELETE FROM records WHERE category_id = ?", (cid,))
        conn.execute("DELETE FROM categories WHERE id = ?", (cid,))
    return {"deleted": True, "records_deleted": n}


def bulk_delete(conn, ids: list) -> dict:
    """여러 항목을 기록과 함께 지운다."""
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise AppError.of("category.delete_invalid_ids") from None
    deleted = records_deleted = 0
    for cid in ids:
        if conn.execute("SELECT 1 FROM categories WHERE id=?", (cid,)).fetchone():
            records_deleted += delete_category(conn, cid, with_records=True)["records_deleted"]
            deleted += 1
    return {"deleted": deleted, "records_deleted": records_deleted}
