"""CSV 내보내기·가져오기.

- 내보내기는 Excel 호환을 위해 UTF-8(BOM) 으로 만든다.
- 가져오기는 UTF-8(BOM 유무)과 CP949(Excel 기본 저장)를 자동 인식한다.
- 가져오기는 '전부 아니면 전무'다. 한 행이라도 오류가 있으면 아무것도 저장하지 않고 행 번호와 오류를 돌려준다.
- dry_run=True 이면 검증만 하고 저장하지 않는다(미리보기).
"""
import csv
import io
import sqlite3

from ..util import AppError, clean_text, parse_date, parse_decimal, dec_str
from . import assets, records
from .assets import TXN_KINDS

MAX_ROWS = 50000

RECORD_KIND_ALIASES = {
    "income": "income", "수입": "income",
    "plan": "plan", "계획": "plan", "지출계획": "plan", "지출 계획": "plan",
    "expense": "expense", "지출": "expense", "실제지출": "expense", "실제 지출": "expense",
}
TXN_KIND_ALIASES = {**{k: k for k in TXN_KINDS}, **{v: k for k, v in TXN_KINDS.items()},
                    "배당": "dividend", "평가": "valuation", "조정": "adjustment", "평가액변동": "valuation",
                    "기타조정": "adjustment"}

RECORD_COLUMNS = ["구분", "항목", "세부항목", "금액", "월", "거래일", "결제일", "예산월", "메모"]
RECORD_ALIASES = {
    "kind": ["구분", "kind", "영역"],
    "category": ["항목", "카테고리", "category", "항목명"],
    "item": ["세부항목", "세부항목", "item"],
    "amount": ["금액", "amount"],
    "month": ["월", "귀속월", "귀속 월", "month"],
    "txn_date": ["거래일", "입금일", "실제입금일", "실제 입금일", "발생일", "날짜", "date", "txn_date"],
    "settle_date": ["결제일", "settle_date"],
    "budget_month": ["예산월", "예산 월", "budget_month"],
    "memo": ["메모", "memo", "비고"],
}
TXN_COLUMNS = ["날짜", "유형", "계좌", "상대계좌", "종목코드", "종목명", "수량", "단가", "금액", "수수료", "메모"]
TXN_ALIASES = {
    "date": ["날짜", "date", "거래일"],
    "kind": ["유형", "kind", "구분"],
    "account": ["계좌", "account", "자산"],
    "to_account": ["상대계좌", "받는계좌", "to_account"],
    "symbol": ["종목코드", "symbol", "티커"],
    "security_name": ["종목명", "security_name"],
    "quantity": ["수량", "quantity"],
    "price": ["단가", "가격", "price"],
    "amount": ["금액", "amount"],
    "fee": ["수수료", "fee"],
    "memo": ["메모", "memo", "비고"],
}


def decode(data: bytes) -> str:
    if len(data) > 20 * 1024 * 1024:
        raise AppError("파일이 너무 큽니다(최대 20MB).")
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise AppError("파일 인코딩을 인식할 수 없습니다. UTF-8 또는 CP949(ANSI)로 저장하세요.")


def _write(header: list[str], data: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(data)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _read(text: str, aliases: dict[str, list[str]], required: list[str]) -> list[tuple[int, dict]]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise AppError("빈 파일입니다.") from None
    norm = [h.strip().lstrip("﻿").lower() for h in header]
    index = {}
    for key, names in aliases.items():
        for n in names:
            if n.lower() in norm:
                index[key] = norm.index(n.lower())
                break
    missing = [aliases[k][0] for k in required if k not in index]
    if missing:
        raise AppError(f"필수 열이 없습니다: {', '.join(missing)}  (첫 행은 열 이름이어야 합니다)")
    out = []
    for lineno, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        out.append((lineno, {k: (row[i].strip() if i < len(row) else "") for k, i in index.items()}))
        if len(out) > MAX_ROWS:
            raise AppError(f"행이 너무 많습니다(최대 {MAX_ROWS}행).")
    return out


def _run_import(conn: sqlite3.Connection, parsed, handler, dry_run: bool, finalize=None) -> dict:
    errors, preview, created = [], [], []
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        for lineno, row in parsed:
            try:
                item = handler(row, created)
                if len(preview) < 20:
                    preview.append({"row": lineno, **item})
            except AppError as e:
                errors.append({"row": lineno, "message": str(e)})
                if len(errors) >= 200:
                    break
        if not errors and finalize:
            try:
                finalize()
            except AppError as e:
                errors.append({"row": None, "message": str(e)})
    except Exception:
        conn.rollback()
        raise
    if errors or dry_run:
        conn.rollback()
    else:
        conn.commit()
    return {"ok": not errors, "applied": not errors and not dry_run, "dry_run": dry_run,
            "total": len(parsed), "errors": errors, "preview": preview, "created": created}


# ───────────────────────── 수입·지출 기록 ─────────────────────────

def export_records(conn, kind: str | None = None, start: str | None = None, end: str | None = None) -> bytes:
    data = records.list_records(conn, kind=kind, start=start, end=end)
    label = {"income": "수입", "plan": "지출계획", "expense": "실제지출"}
    data = [r for r in data if r["amount"] != 0]  # 0원 봉투 표시용 행은 제외
    data.sort(key=lambda r: (r["month"], r["kind"], r["id"]))
    return _write(RECORD_COLUMNS, [[label[r["kind"]], r["category_name"], r["item"], r["amount"], r["month"],
                                    r["txn_date"] or "", r["settle_date"] or "", r["budget_month"] or "", r["memo"]] for r in data])


def _find_or_create_category(conn, label: str, ckind: str, create: bool, created: list) -> int:
    """ckind('income'/'expense') 종류에서 이름으로 항목을 찾는다(없으면 선택적으로 생성)."""
    name = label.strip()
    if not name:
        raise AppError("항목이 비어 있습니다.")
    r = conn.execute("SELECT id FROM categories WHERE kind=? AND parent_id IS NULL AND name=?", (ckind, name)).fetchone()
    if r:
        return r["id"]
    if not create:
        kind_label = "소득" if ckind == "income" else "지출"
        raise AppError(f"{kind_label} 항목 '{name}'이(가) 없습니다. 설정에서 만들거나 '없는 항목 자동 생성'을 선택하세요.")
    created.append(name)
    return conn.execute("INSERT INTO categories (name, kind, sort_order) VALUES (?, ?, (SELECT IFNULL(MAX(sort_order),0)+1 FROM categories))",
                        (name, ckind)).lastrowid


def import_records(conn, data: bytes, dry_run: bool = True, create_missing: bool = False) -> dict:
    parsed = _read(decode(data), RECORD_ALIASES, ["kind", "category", "amount"])

    def handle(row, created):
        kind = RECORD_KIND_ALIASES.get(row.get("kind", "").strip().lower()) or RECORD_KIND_ALIASES.get(row.get("kind", "").strip())
        if not kind:
            raise AppError(f"구분 값 '{row.get('kind')}'을(를) 알 수 없습니다(수입/지출계획/실제지출).")
        ckind = "income" if kind == "income" else "expense"
        label, item = row.get("category", ""), row.get("item", "")
        if ">" in label:  # 예전 형식 '항목 > 하위' 는 항목 + 세부항목으로 읽는다
            label, sub = [x.strip() for x in label.split(">", 1)]
            item = item or sub
        cid = _find_or_create_category(conn, label, ckind, create_missing, created)
        v = records.validate_record(conn, {
            "kind": kind, "category_id": cid, "amount": row.get("amount"), "month": row.get("month") or None,
            "txn_date": row.get("txn_date") or None, "settle_date": row.get("settle_date") or None,
            "budget_month": row.get("budget_month") or None, "memo": row.get("memo", ""), "item": item,
        })
        conn.execute("""INSERT INTO records (kind, category_id, amount, month, txn_date, settle_date, budget_month, memo, item)
                        VALUES (:kind,:category_id,:amount,:month,:txn_date,:settle_date,:budget_month,:memo,:item)""", v)
        return {"kind": kind, "category": row.get("category"), "amount": v["amount"], "month": v["month"],
                "txn_date": v["txn_date"]}

    return _run_import(conn, parsed, handle, dry_run)


# ───────────────────────── 자산 변동 ─────────────────────────

def export_asset_txns(conn, account_id: int | None = None) -> bytes:
    data = assets.list_txns(conn, account_id=account_id, limit=10**9)
    data.reverse()
    return _write(TXN_COLUMNS, [[t["date"], TXN_KINDS[t["kind"]], t["account_name"], t["to_account_name"] or "",
                                 t["symbol"] or "", t["security_name"] or "", t["quantity"] or "", t["price"] or "",
                                 "" if t["kind"] in ("buy", "sell") else t["amount"], t["fee"] or "", t["memo"]]
                                for t in data])


def import_asset_txns(conn, data: bytes, dry_run: bool = True, create_missing_securities: bool = True) -> dict:
    parsed = _read(decode(data), TXN_ALIASES, ["date", "kind", "account"])

    def account_id(name: str, field: str) -> int:
        r = conn.execute("SELECT id FROM accounts WHERE name=?", (name.strip(),)).fetchone()
        if not r:
            raise AppError(f"{field} '{name}'이(가) 없습니다. 자산 관리에서 먼저 계좌를 만드세요.")
        return r["id"]

    def handle(row, created):
        kind = TXN_KIND_ALIASES.get(row.get("kind", "").strip()) or TXN_KIND_ALIASES.get(row.get("kind", "").strip().lower())
        if not kind:
            raise AppError(f"유형 '{row.get('kind')}'을(를) 알 수 없습니다.")
        payload = {"kind": kind, "date": row.get("date"), "account_id": account_id(row.get("account", ""), "계좌"),
                   "quantity": row.get("quantity"), "price": row.get("price"), "amount": row.get("amount"),
                   "fee": row.get("fee") or 0, "memo": row.get("memo", "")}
        if kind == "transfer":
            payload["to_account_id"] = account_id(row.get("to_account", ""), "상대계좌")
        sym = (row.get("symbol") or "").strip().upper()
        if sym:
            s = conn.execute("SELECT id FROM securities WHERE symbol=?", (sym,)).fetchone()
            if not s:
                if not create_missing_securities:
                    raise AppError(f"종목 '{sym}'이(가) 등록되어 있지 않습니다.")
                sid = conn.execute("INSERT INTO securities (symbol, name) VALUES (?,?)",
                                   (sym, clean_text(row.get("security_name"), 80) or sym)).lastrowid
                created.append(sym)
            else:
                sid = s["id"]
            payload["security_id"] = sid
        v = assets.validate_txn(conn, payload)
        conn.execute("""INSERT INTO asset_txns (date, kind, account_id, to_account_id, security_id, quantity, price, amount, fee, memo)
                        VALUES (:date,:kind,:account_id,:to_account_id,:security_id,:quantity,:price,:amount,:fee,:memo)""", v)
        return {"date": v["date"], "kind": TXN_KINDS[kind], "account": row.get("account"), "amount": v["amount"]}

    return _run_import(conn, parsed, handle, dry_run, finalize=lambda: assets.Ledger.load(conn).run())


# ───────────────────────── 시세 / 지표 / 항목 ─────────────────────────

def export_prices(conn) -> bytes:
    data = conn.execute("""SELECT p.date, s.symbol, s.name, p.price, p.source FROM security_prices p
                           JOIN securities s ON s.id=p.security_id ORDER BY s.symbol, p.date""").fetchall()
    return _write(["날짜", "종목코드", "종목명", "가격", "출처"], [list(r) for r in data])


def import_prices(conn, data: bytes, dry_run: bool = True) -> dict:
    parsed = _read(decode(data), {"date": ["날짜", "date"], "symbol": ["종목코드", "symbol"], "price": ["가격", "종가", "price"]},
                   ["date", "symbol", "price"])

    def handle(row, created):
        s = conn.execute("SELECT id FROM securities WHERE symbol=?", (row["symbol"].strip().upper(),)).fetchone()
        if not s:
            raise AppError(f"종목 '{row['symbol']}'이(가) 등록되어 있지 않습니다.")
        d = parse_date(row["date"])
        p = dec_str(parse_decimal(row["price"], "가격"))
        conn.execute("""INSERT INTO security_prices (security_id, date, price, source) VALUES (?,?,?,'csv')
                        ON CONFLICT(security_id, date) DO UPDATE SET price=excluded.price, source='csv'""", (s["id"], d, p))
        return {"date": d, "symbol": row["symbol"], "price": p}

    return _run_import(conn, parsed, handle, dry_run)


def export_indicator_values(conn, iid: int) -> bytes:
    data = conn.execute("SELECT date, value, source FROM indicator_values WHERE indicator_id=? ORDER BY date", (iid,)).fetchall()
    return _write(["날짜", "값", "출처"], [list(r) for r in data])


def import_indicator_values(conn, iid: int, data: bytes, dry_run: bool = True) -> dict:
    if not conn.execute("SELECT 1 FROM indicators WHERE id=?", (iid,)).fetchone():
        raise AppError("지표를 찾을 수 없습니다.")
    parsed = _read(decode(data), {"date": ["날짜", "date"], "value": ["값", "value"]}, ["date", "value"])

    def handle(row, created):
        d = parse_date(row["date"])
        try:
            v = float(row["value"].replace(",", ""))
        except ValueError:
            raise AppError(f"값 '{row['value']}'은(는) 숫자가 아닙니다.") from None
        conn.execute("""INSERT INTO indicator_values (indicator_id, date, value, source) VALUES (?,?,?,'csv')
                        ON CONFLICT(indicator_id, date) DO UPDATE SET value=excluded.value, source='csv',
                        updated_at=datetime('now','localtime')""", (iid, d, v))
        return {"date": d, "value": v}

    return _run_import(conn, parsed, handle, dry_run)


def export_categories(conn) -> bytes:
    data = conn.execute("SELECT kind, name FROM categories ORDER BY kind='expense', sort_order, id").fetchall()
    return _write(["종류", "항목"], [["소득" if r[0] == "income" else "지출", r[1]] for r in data])


TEMPLATES = {
    "records": (RECORD_COLUMNS, [["수입", "급여", "월급", "3000000", "", "2026-10-31", "", "2026-11", "10/31 입금 → 11월에 쓸 돈"],
                                 ["지출계획", "식비", "", "300000", "2026-11", "", "", "", ""],
                                 ["실제지출", "식비", "마트", "12000", "2026-11", "", "", "", ""]]),
    "asset_txns": (TXN_COLUMNS, [["2026-10-01", "입금", "카카오페이증권", "", "", "", "", "", "1000000", "", "초기 입금"],
                                 ["2026-10-02", "매수", "카카오페이증권", "", "005930", "삼성전자", "10", "60000", "", "150", ""],
                                 ["2026-10-03", "이체", "생활비 통장", "카카오페이증권", "", "", "", "", "500000", "", ""]]),
    "prices": (["날짜", "종목코드", "가격"], [["2026-10-17", "005930", "61000"]]),
    "indicator_values": (["날짜", "값"], [["2026-10-01", "2.50"]]),
}


def template(name: str) -> bytes:
    if name not in TEMPLATES:
        raise AppError("알 수 없는 템플릿입니다.")
    header, data = TEMPLATES[name]
    return _write(header, data)
