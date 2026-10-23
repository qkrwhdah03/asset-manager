"""항목 관리 (설정 화면).

항목은 모든 달에 똑같이 적용된다. 종류(kind):
- income  : 소득 항목 (급여, 장학금 …)
- expense : 지출 항목. 지출 계획은 항목 단위로 세운다.
각 달의 실제 기록은 항목 아래 '세부항목'(records.item)으로 자유롭게 남긴다.
항목을 지우면 그 항목의 기록도 함께 지운다(화면에서 기록 수를 보여 주고 확인받는다).
저축 항목 지정: 지출 항목 중 어느 것이 저축인지는 settings 의 SAVINGS_KEY 행에 항목 id 의
JSON 배열로 저장한다. 행이 없으면(지정 전) 이름이 SAVINGS_NAME_HINT 에 맞는 지출 항목을 쓴다.
"""
import json
import re
import sqlite3

from ..util import AppError, clean_text, rows

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
KINDS = {"income": "소득", "expense": "지출"}
RECORD_KIND_TO_CATEGORY = {"income": "income", "plan": "expense", "expense": "expense"}
SAVINGS_KEY = "savings_category_ids"
SAVINGS_NAME_HINT = re.compile(r"저축|투자")


def _stored_savings_ids(conn) -> list[int] | None:
    """SAVINGS_KEY 행의 id 목록. 행이 없거나 정수 JSON 배열이 아니면 None(지정 전)."""
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (SAVINGS_KEY,)).fetchone()
    if not r:
        return None
    try:
        ids = json.loads(r[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        return None
    return ids


def savings_category_ids(conn) -> set[int]:
    """저축 항목(지출 항목) id 집합."""
    expense = rows(conn.execute("SELECT id, name FROM categories WHERE kind = 'expense'"))
    ids = _stored_savings_ids(conn)
    if ids is None:
        return {c["id"] for c in expense if SAVINGS_NAME_HINT.search(c["name"] or "")}
    wanted = set(ids)
    return {c["id"] for c in expense if c["id"] in wanted}


def _write_savings_ids(conn, ids: set[int]) -> None:
    """with conn: 블록 안에서 부른다."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SAVINGS_KEY, json.dumps(sorted(ids), separators=(",", ":"))),
    )


def _drop_savings_id(conn, cid: int) -> None:
    """SAVINGS_KEY 행이 있으면 목록에서 cid 를 뺀다. with conn: 블록 안에서 부른다."""
    if conn.execute("SELECT 1 FROM settings WHERE key = ?", (SAVINGS_KEY,)).fetchone():
        _write_savings_ids(conn, savings_category_ids(conn) - {cid})


def _savings_flag(data: dict, kind: str) -> bool | None:
    """data 에 is_savings 가 있으면 검증한 bool, 없으면 None."""
    if "is_savings" not in data:
        return None
    flag = data["is_savings"]
    if not isinstance(flag, int) or flag not in (0, 1):
        raise AppError.of("category.invalid_savings")
    flag = bool(flag)
    if flag and kind == "income":
        raise AppError.of("category.savings_income_kind")
    return flag


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
    savings = savings_category_ids(conn)
    for c in out:
        c["is_active"] = bool(c["is_active"])
        c["full_name"] = c["name"]
        c["is_savings"] = c["kind"] == "expense" and c["id"] in savings
    return out


def get_category(conn, cid: int) -> dict:
    r = conn.execute("SELECT * FROM categories WHERE id = ?", (cid,)).fetchone()
    if not r:
        raise AppError.of("category.not_found")
    c = dict(r)
    c["is_savings"] = c["kind"] == "expense" and c["id"] in savings_category_ids(conn)
    return c


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
    if conn.execute("SELECT 1 FROM categories WHERE kind=? AND name=? AND id<>?",
                    (kind, name, cid or -1)).fetchone():
        raise AppError.of(f"category.duplicate_{kind}", name=name)
    return dict(name=name, kind=kind, color=color, icon=clean_text(data.get("icon"), 8) or None,
                memo=clean_text(data.get("memo"), 200),
                is_active=1, sort_order=int(data.get("sort_order") or 0))  # 비활성화 기능은 없앴다(v6). 항목은 삭제만 한다.


def create_category(conn, data: dict) -> dict:
    v = _validate(conn, data)
    flag = _savings_flag(data, v["kind"])
    if "sort_order" not in data:
        v["sort_order"] = conn.execute("SELECT IFNULL(MAX(sort_order),0)+1 FROM categories WHERE kind=?", (v["kind"],)).fetchone()[0]
    with conn:
        cur = conn.execute(
            "INSERT INTO categories (name, kind, color, icon, memo, is_active, sort_order) VALUES (?,?,?,?,?,?,?)",
            (v["name"], v["kind"], v["color"], v["icon"], v["memo"], v["is_active"], v["sort_order"]),
        )
        if flag is not None:
            ids = savings_category_ids(conn)
            _write_savings_ids(conn, ids | {cur.lastrowid} if flag else ids - {cur.lastrowid})
    return get_category(conn, cur.lastrowid)


def update_category(conn, cid: int, data: dict) -> dict:
    v = _validate(conn, {**get_category(conn, cid), **data}, cid)
    flag = _savings_flag(data, v["kind"])  # 원래 data 에 is_savings 가 있을 때만 저축 지정을 쓴다
    with conn:
        conn.execute(
            """UPDATE categories SET name=?, kind=?, color=?, icon=?, memo=?, is_active=?, sort_order=?,
               updated_at=datetime('now','localtime') WHERE id=?""",
            (v["name"], v["kind"], v["color"], v["icon"], v["memo"], v["is_active"], v["sort_order"], cid),
        )
        if flag is not None:
            ids = savings_category_ids(conn)
            _write_savings_ids(conn, ids | {cid} if flag else ids - {cid})
        elif v["kind"] == "income":
            _drop_savings_id(conn, cid)
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
        _drop_savings_id(conn, cid)
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
