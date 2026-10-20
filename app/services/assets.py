"""자산·계좌 관리와 자산 평가.

핵심 개념
- 계좌(account)는 현금 잔액과 보유 종목(holdings)을 가진다. 은행 계좌는 현금만, 증권 계좌는 둘 다.
- 계좌 평가액 = 현금 잔액 + 평가액 변동 누계 + Σ(보유 수량 × 기준일 가격)
- 외부 순유입(순투입원금) = 입금 - 출금 + 기타 조정 (+ 계좌 단위에서는 이체 입금 - 이체 출금)
    → 이체는 전체 자산 기준에서 서로 상쇄되어 수익·손실로 잡히지 않는다.
- 투자 손익 = 평가액 - 순투입원금
            = 실현손익 + 평가손익 + 배당 + 이자 - 수수료 + 평가액 변동  (항등식, 테스트로 검증)
- 자산 증감 = 기말 평가액 - 기초 평가액 = 순유입 + 투자 손익.  자산 증가 ≠ 투자 수익.
- 매수 수수료는 취득원가에 포함하고, 매도 시 평균단가(이동평균법)로 실현손익을 계산한다.
"""
import bisect
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ..util import (AppError, add_months, clean_text, dec_str, month_end, month_range, parse_amount,
                    parse_date, parse_decimal, rows)

TXN_KINDS = {
    "deposit": "입금", "withdrawal": "출금", "transfer": "이체", "buy": "매수", "sell": "매도",
    "dividend": "배당금", "interest": "이자", "fee": "수수료", "valuation": "평가액 변동", "adjustment": "기타 조정",
}
SIGNED_KINDS = {"valuation", "adjustment"}
LIQUIDITY_LABEL = {"cash": "현금성", "investment": "투자", "other": "기타"}


def _int(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ───────────────────────── 자산 유형 ─────────────────────────

def list_asset_types(conn) -> list[dict]:
    return rows(conn.execute(
        """SELECT t.*, (SELECT COUNT(*) FROM accounts a WHERE a.type_id = t.id) AS account_count
           FROM asset_types t ORDER BY sort_order, id"""
    ))


def save_asset_type(conn, data: dict, tid: int | None = None) -> dict:
    name = clean_text(data.get("name"), 40)
    if not name:
        raise AppError("자산 유형 이름을 입력하세요.")
    valuation = data.get("valuation") or "balance"
    liquidity = data.get("liquidity") or "cash"
    if valuation not in ("balance", "holdings"):
        raise AppError("평가 방식이 올바르지 않습니다.")
    if liquidity not in LIQUIDITY_LABEL:
        raise AppError("자산 성격이 올바르지 않습니다.")
    if conn.execute("SELECT 1 FROM asset_types WHERE name=? AND id<>?", (name, tid or -1)).fetchone():
        raise AppError(f"'{name}' 자산 유형이 이미 있습니다.")
    with conn:
        if tid:
            conn.execute("UPDATE asset_types SET name=?, valuation=?, liquidity=? WHERE id=?",
                         (name, valuation, liquidity, tid))
        else:
            order = conn.execute("SELECT IFNULL(MAX(sort_order),0)+1 FROM asset_types").fetchone()[0]
            tid = conn.execute("INSERT INTO asset_types (name, valuation, liquidity, sort_order) VALUES (?,?,?,?)",
                               (name, valuation, liquidity, order)).lastrowid
    return dict(conn.execute("SELECT * FROM asset_types WHERE id=?", (tid,)).fetchone())


def delete_asset_type(conn, tid: int) -> None:
    if conn.execute("SELECT 1 FROM accounts WHERE type_id=?", (tid,)).fetchone():
        raise AppError("이 유형을 사용하는 계좌가 있어 삭제할 수 없습니다.")
    with conn:
        conn.execute("DELETE FROM asset_types WHERE id=?", (tid,))


# ───────────────────────── 계좌 ─────────────────────────

def list_accounts(conn, include_inactive: bool = True) -> list[dict]:
    sql = """SELECT a.*, t.name AS type_name, t.valuation, t.liquidity,
                    (SELECT COUNT(*) FROM asset_txns x WHERE x.account_id=a.id OR x.to_account_id=a.id) AS txn_count
             FROM accounts a JOIN asset_types t ON t.id = a.type_id"""
    if not include_inactive:
        sql += " WHERE a.is_active = 1"
    sql += " ORDER BY a.is_active DESC, t.sort_order, a.sort_order, a.id"
    out = rows(conn.execute(sql))
    for a in out:
        a["is_active"] = bool(a["is_active"])
    return out


def get_account(conn, aid: int) -> dict:
    r = conn.execute("SELECT a.*, t.name AS type_name FROM accounts a JOIN asset_types t ON t.id=a.type_id WHERE a.id=?",
                     (aid,)).fetchone()
    if not r:
        raise AppError("계좌를 찾을 수 없습니다.")
    return dict(r)


def save_account(conn, data: dict, aid: int | None = None) -> dict:
    current = get_account(conn, aid) if aid else {}
    d = {**current, **data}
    name = clean_text(d.get("name"), 60)
    if not name:
        raise AppError("자산(계좌) 이름을 입력하세요.")
    try:
        type_id = int(d.get("type_id"))
    except (TypeError, ValueError):
        raise AppError("자산 유형을 선택하세요.") from None
    if not conn.execute("SELECT 1 FROM asset_types WHERE id=?", (type_id,)).fetchone():
        raise AppError("자산 유형이 존재하지 않습니다.")
    input_mode = d.get("input_mode") or "manual"
    if input_mode not in ("manual", "api", "csv"):
        raise AppError("입력 방식이 올바르지 않습니다.")
    if conn.execute("SELECT 1 FROM accounts WHERE name=? AND id<>?", (name, aid or -1)).fetchone():
        raise AppError(f"'{name}' 이름의 계좌가 이미 있습니다.")
    vals = (name, type_id, clean_text(d.get("institution"), 60), clean_text(d.get("memo"), 500), input_mode,
            1 if d.get("is_active", True) else 0)
    with conn:
        if aid:
            conn.execute("UPDATE accounts SET name=?, type_id=?, institution=?, memo=?, input_mode=?, is_active=? WHERE id=?",
                         (*vals, aid))
        else:
            aid = conn.execute(
                "INSERT INTO accounts (name, type_id, institution, memo, input_mode, is_active) VALUES (?,?,?,?,?,?)",
                vals).lastrowid
    return get_account(conn, aid)


def delete_account(conn, aid: int) -> dict:
    get_account(conn, aid)
    used = conn.execute("SELECT COUNT(*) FROM asset_txns WHERE account_id=? OR to_account_id=?", (aid, aid)).fetchone()[0]
    with conn:
        if used:
            conn.execute("UPDATE accounts SET is_active=0 WHERE id=?", (aid,))
            return {"action": "deactivated", "txn_count": used}
        conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
        return {"action": "deleted", "txn_count": 0}


# ───────────────────────── 종목·가격 ─────────────────────────

def list_securities(conn) -> list[dict]:
    out = rows(conn.execute(
        """SELECT s.*,
                  (SELECT price FROM security_prices p WHERE p.security_id=s.id ORDER BY date DESC LIMIT 1) AS last_price,
                  (SELECT date FROM security_prices p WHERE p.security_id=s.id ORDER BY date DESC LIMIT 1) AS last_price_date,
                  (SELECT COUNT(*) FROM asset_txns x WHERE x.security_id=s.id) AS txn_count
           FROM securities s ORDER BY s.name"""
    ))
    return out


def save_security(conn, data: dict, sid: int | None = None) -> dict:
    symbol = clean_text(data.get("symbol"), 20).upper()
    name = clean_text(data.get("name"), 80) or symbol
    if not symbol:
        raise AppError("종목코드를 입력하세요.")
    kind = data.get("kind") or "stock"
    if kind not in ("stock", "etf", "fund", "other"):
        raise AppError("종목 구분이 올바르지 않습니다.")
    if conn.execute("SELECT 1 FROM securities WHERE symbol=? AND id<>?", (symbol, sid or -1)).fetchone():
        raise AppError(f"종목코드 '{symbol}'이(가) 이미 등록되어 있습니다.")
    with conn:
        if sid:
            conn.execute("UPDATE securities SET symbol=?, name=?, kind=?, memo=? WHERE id=?",
                         (symbol, name, kind, clean_text(data.get("memo"), 300), sid))
        else:
            sid = conn.execute("INSERT INTO securities (symbol, name, kind, memo) VALUES (?,?,?,?)",
                               (symbol, name, kind, clean_text(data.get("memo"), 300))).lastrowid
    return dict(conn.execute("SELECT * FROM securities WHERE id=?", (sid,)).fetchone())


def delete_security(conn, sid: int) -> None:
    if conn.execute("SELECT 1 FROM asset_txns WHERE security_id=?", (sid,)).fetchone():
        raise AppError("거래 기록이 있는 종목은 삭제할 수 없습니다.")
    with conn:
        conn.execute("DELETE FROM securities WHERE id=?", (sid,))


def set_price(conn, security_id: int, d: str, price, source: str = "manual") -> dict:
    if not conn.execute("SELECT 1 FROM securities WHERE id=?", (security_id,)).fetchone():
        raise AppError("종목을 찾을 수 없습니다.")
    d = parse_date(d, "기준일")
    p = parse_decimal(price, "가격")
    with conn:
        conn.execute("""INSERT INTO security_prices (security_id, date, price, source) VALUES (?,?,?,?)
                        ON CONFLICT(security_id, date) DO UPDATE SET price=excluded.price, source=excluded.source""",
                     (security_id, d, dec_str(p), source))
    return {"security_id": security_id, "date": d, "price": dec_str(p)}


def list_prices(conn, security_id: int) -> list[dict]:
    return rows(conn.execute("SELECT * FROM security_prices WHERE security_id=? ORDER BY date DESC", (security_id,)))


def delete_price(conn, security_id: int, d: str) -> None:
    with conn:
        conn.execute("DELETE FROM security_prices WHERE security_id=? AND date=?", (security_id, d))


# ───────────────────────── 자산 변동 기록 ─────────────────────────

def validate_txn(conn, data: dict) -> dict:
    kind = data.get("kind")
    if kind not in TXN_KINDS:
        raise AppError("변동 유형이 올바르지 않습니다.")
    d = parse_date(data.get("date"), "날짜")
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError):
        raise AppError("계좌를 선택하세요.") from None
    if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
        raise AppError("계좌가 존재하지 않습니다.")
    v = dict(kind=kind, date=d, account_id=account_id, to_account_id=None, security_id=None,
             quantity=None, price=None, amount=0, fee=0, memo=clean_text(data.get("memo"), 500))
    fee = data.get("fee")
    v["fee"] = parse_amount(fee, "수수료") if fee not in (None, "") else 0

    if kind == "transfer":
        try:
            to_id = int(data.get("to_account_id"))
        except (TypeError, ValueError):
            raise AppError("이체 받을 계좌를 선택하세요.") from None
        if to_id == account_id:
            raise AppError("같은 계좌로는 이체할 수 없습니다.")
        if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (to_id,)).fetchone():
            raise AppError("이체 받을 계좌가 존재하지 않습니다.")
        v["to_account_id"] = to_id

    if kind in ("buy", "sell", "dividend") and data.get("security_id") not in (None, ""):
        sid = int(data["security_id"])
        if not conn.execute("SELECT 1 FROM securities WHERE id=?", (sid,)).fetchone():
            raise AppError("종목이 존재하지 않습니다.")
        v["security_id"] = sid

    if kind in ("buy", "sell"):
        if not v["security_id"]:
            raise AppError("종목을 선택하세요.")
        q = parse_decimal(data.get("quantity"), "수량")
        p = parse_decimal(data.get("price"), "단가")
        v["quantity"], v["price"] = dec_str(q), dec_str(p)
        v["amount"] = _int(q * p)
    elif kind in SIGNED_KINDS:
        v["amount"] = parse_amount(data.get("amount"), allow_negative=True, allow_zero=False)
    else:
        v["amount"] = parse_amount(data.get("amount"), allow_zero=False)
    if v["fee"] and kind not in ("buy", "sell", "transfer"):
        raise AppError("수수료 칸은 매수·매도·이체에서만 사용합니다. 별도 수수료는 '수수료' 유형으로 기록하세요.")
    return v


def create_txn(conn, data: dict) -> dict:
    v = validate_txn(conn, data)
    with conn:
        tid = conn.execute(
            """INSERT INTO asset_txns (date, kind, account_id, to_account_id, security_id, quantity, price, amount, fee, memo)
               VALUES (:date,:kind,:account_id,:to_account_id,:security_id,:quantity,:price,:amount,:fee,:memo)""", v
        ).lastrowid
        _check_ledger(conn)
    return get_txn(conn, tid)


def update_txn(conn, tid: int, data: dict) -> dict:
    existing = conn.execute("SELECT * FROM asset_txns WHERE id=?", (tid,)).fetchone()
    if not existing:
        raise AppError("자산 변동 기록을 찾을 수 없습니다.")
    v = validate_txn(conn, {**dict(existing), **data})
    with conn:
        conn.execute(
            """UPDATE asset_txns SET date=:date, kind=:kind, account_id=:account_id, to_account_id=:to_account_id,
               security_id=:security_id, quantity=:quantity, price=:price, amount=:amount, fee=:fee, memo=:memo
               WHERE id=:id""", {**v, "id": tid})
        _check_ledger(conn)
    return get_txn(conn, tid)


def delete_txn(conn, tid: int) -> None:
    with conn:
        cur = conn.execute("DELETE FROM asset_txns WHERE id=?", (tid,))
        if cur.rowcount == 0:
            raise AppError("자산 변동 기록을 찾을 수 없습니다.")
        _check_ledger(conn)


def _check_ledger(conn) -> None:
    """보유 수량보다 많이 매도하는 등 시간 순서상 모순이 생기면 오류를 낸다(트랜잭션 롤백)."""
    Ledger.load(conn).run()


TXN_SELECT = """
    SELECT x.*, a.name AS account_name, ta.name AS to_account_name, s.symbol, s.name AS security_name
    FROM asset_txns x JOIN accounts a ON a.id = x.account_id
    LEFT JOIN accounts ta ON ta.id = x.to_account_id
    LEFT JOIN securities s ON s.id = x.security_id
"""


def get_txn(conn, tid: int) -> dict:
    r = conn.execute(TXN_SELECT + " WHERE x.id=?", (tid,)).fetchone()
    if not r:
        raise AppError("자산 변동 기록을 찾을 수 없습니다.")
    r = dict(r)
    r["kind_label"] = TXN_KINDS[r["kind"]]
    return r


def list_txns(conn, account_id: int | None = None, kind: str | None = None, start: str | None = None,
              end: str | None = None, security_id: int | None = None, limit: int = 1000) -> list[dict]:
    where, params = [], []
    if account_id:
        where.append("(x.account_id=? OR x.to_account_id=?)")
        params += [account_id, account_id]
    if kind:
        where.append("x.kind=?")
        params.append(kind)
    if security_id:
        where.append("x.security_id=?")
        params.append(security_id)
    if start:
        where.append("x.date>=?")
        params.append(parse_date(start))
    if end:
        where.append("x.date<=?")
        params.append(parse_date(end))
    sql = TXN_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY x.date DESC, x.id DESC LIMIT ?"
    out = rows(conn.execute(sql, params + [int(limit)]))
    for r in out:
        r["kind_label"] = TXN_KINDS[r["kind"]]
    return out


# ───────────────────────── 평가 엔진 ─────────────────────────

@dataclass
class Holding:
    qty: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)        # 남은 수량의 취득원가(수수료 포함)
    realized: Decimal = Decimal(0)
    dividends: int = 0


@dataclass
class AccountState:
    cash: int = 0
    valuation: int = 0                # 평가액 변동 누계(잔액형 자산의 시가 반영)
    contrib: int = 0                  # 계좌 단위 순유입(이체 포함)
    external: int = 0                 # 외부 순유입(이체 제외)
    dividends: int = 0
    interest: int = 0
    fees: int = 0
    holdings: dict = field(default_factory=lambda: defaultdict(Holding))

    @property
    def realized(self) -> Decimal:
        return sum((h.realized for h in self.holdings.values()), Decimal(0))


class PriceBook:
    """종목별 기준일 가격. 등록된 시세(security_prices)를 우선하고, 없으면 그 날짜 이전 마지막 거래 단가를 쓴다."""

    def __init__(self, conn):
        self.series: dict[int, tuple[list[str], list[tuple[Decimal, str]]]] = {}
        data = defaultdict(dict)
        for r in conn.execute("SELECT security_id, date, price FROM asset_txns WHERE kind IN ('buy','sell') ORDER BY date, id"):
            data[r["security_id"]][r["date"]] = (Decimal(r["price"]), "trade")
        for r in conn.execute("SELECT security_id, date, price FROM security_prices ORDER BY date"):
            data[r["security_id"]][r["date"]] = (Decimal(r["price"]), "quote")
        for sid, by_date in data.items():
            dates = sorted(by_date)
            self.series[sid] = (dates, [by_date[d] for d in dates])

    def at(self, sid: int, d: str) -> tuple[Decimal | None, str | None, str | None]:
        if sid not in self.series:
            return None, None, None
        dates, vals = self.series[sid]
        i = bisect.bisect_right(dates, d) - 1
        if i < 0:
            return None, None, None
        return vals[i][0], dates[i], vals[i][1]


class Ledger:
    def __init__(self, txns: list[dict], accounts: dict[int, dict], securities: dict[int, dict], prices: PriceBook):
        self.txns = txns
        self.accounts = accounts
        self.securities = securities
        self.prices = prices
        self.state: dict[int, AccountState] = defaultdict(AccountState)
        self.pos = 0

    @classmethod
    def load(cls, conn) -> "Ledger":
        txns = rows(conn.execute("SELECT * FROM asset_txns ORDER BY date, id"))
        accounts = {r["id"]: r for r in rows(conn.execute(
            "SELECT a.*, t.name AS type_name, t.valuation, t.liquidity FROM accounts a JOIN asset_types t ON t.id=a.type_id"))}
        securities = {r["id"]: r for r in rows(conn.execute("SELECT * FROM securities"))}
        return cls(txns, accounts, securities, PriceBook(conn))

    def run(self, until: str | None = None) -> "Ledger":
        """until(포함) 날짜까지의 거래를 순서대로 반영한다. 여러 번 호출하면 이어서 진행한다."""
        while self.pos < len(self.txns) and (until is None or self.txns[self.pos]["date"] <= until):
            self._apply(self.txns[self.pos])
            self.pos += 1
        return self

    def _apply(self, t: dict) -> None:
        s = self.state[t["account_id"]]
        k, a, fee = t["kind"], t["amount"], t["fee"]
        if k == "deposit":
            s.cash += a; s.contrib += a; s.external += a
        elif k == "withdrawal":
            s.cash -= a; s.contrib -= a; s.external -= a
        elif k == "adjustment":
            s.cash += a; s.contrib += a; s.external += a
        elif k == "transfer":
            dst = self.state[t["to_account_id"]]
            s.cash -= a + fee; s.contrib -= a; s.fees += fee
            dst.cash += a; dst.contrib += a
        elif k == "buy":
            h = s.holdings[t["security_id"]]
            q = Decimal(t["quantity"])
            s.cash -= a + fee
            h.qty += q
            h.cost += Decimal(a + fee)
        elif k == "sell":
            h = s.holdings[t["security_id"]]
            q = Decimal(t["quantity"])
            if q > h.qty:
                sec = self.securities.get(t["security_id"], {})
                raise AppError(
                    f"{t['date']} 매도 수량({dec_str(q)})이 보유 수량({dec_str(h.qty)})보다 많습니다: "
                    f"{sec.get('name', '')} / {self.accounts.get(t['account_id'], {}).get('name', '')}"
                )
            cost_sold = h.cost * q / h.qty
            s.cash += a - fee
            h.realized += Decimal(a - fee) - cost_sold
            h.qty -= q
            h.cost -= cost_sold
            if h.qty == 0:
                h.cost = Decimal(0)
        elif k == "dividend":
            s.cash += a; s.dividends += a
            if t["security_id"]:
                s.holdings[t["security_id"]].dividends += a
        elif k == "interest":
            s.cash += a; s.interest += a
        elif k == "fee":
            s.cash -= a; s.fees += a
        elif k == "valuation":
            s.valuation += a

    def snapshot(self, as_of: str) -> dict:
        """현재까지 반영된 상태를 as_of 기준 가격으로 평가한다."""
        accounts_out, holdings_out = [], []
        for aid, acc in self.accounts.items():
            s = self.state.get(aid, AccountState())
            hv_total = Decimal(0)
            unrealized_total = Decimal(0)
            missing_price = False
            for sid, h in s.holdings.items():
                if h.qty == 0 and h.realized == 0 and h.dividends == 0:
                    continue
                price, pdate, psrc = self.prices.at(sid, as_of)
                if h.qty > 0 and price is None:
                    missing_price = True
                    value = h.cost
                else:
                    value = (h.qty * price) if h.qty > 0 else Decimal(0)
                unreal = value - h.cost
                hv_total += value
                unrealized_total += unreal
                sec = self.securities[sid]
                holdings_out.append({
                    "account_id": aid, "account_name": acc["name"], "security_id": sid,
                    "symbol": sec["symbol"], "security_name": sec["name"], "kind": sec["kind"],
                    "quantity": dec_str(h.qty), "avg_cost": dec_str((h.cost / h.qty).quantize(Decimal("0.01"))) if h.qty else None,
                    "cost": _int(h.cost), "price": dec_str(price) if price is not None else None,
                    "price_date": pdate, "price_source": psrc, "value": _int(value),
                    "unrealized": _int(unreal),
                    "unrealized_pct": round(float(unreal / h.cost * 100), 2) if h.cost > 0 else None,
                    "realized": _int(h.realized), "dividends": h.dividends,
                })
            value = s.cash + s.valuation + _int(hv_total)
            profit = value - s.contrib
            realized = _int(s.realized)
            unrealized = _int(unrealized_total)
            accounts_out.append({
                "account_id": aid, "name": acc["name"], "type_id": acc["type_id"], "type_name": acc["type_name"],
                "institution": acc["institution"], "liquidity": acc["liquidity"], "valuation_method": acc["valuation"],
                "is_active": bool(acc["is_active"]), "input_mode": acc["input_mode"],
                "cash": s.cash, "valuation_adj": s.valuation, "holdings_value": _int(hv_total), "value": value,
                "contrib": s.contrib, "external": s.external, "profit": profit,
                "return_pct": round(profit / s.contrib * 100, 2) if s.contrib > 0 else None,
                "realized": realized, "unrealized": unrealized,
                "dividends": s.dividends, "interest": s.interest, "fees": s.fees,
                "missing_price": missing_price,
            })
        return {"as_of": as_of, "accounts": accounts_out, "holdings": holdings_out}


def _aggregate(snap: dict) -> dict:
    accs = snap["accounts"]
    total = sum(a["value"] for a in accs)
    external = sum(a["external"] for a in accs)
    by_liq = {"cash": 0, "investment": 0, "other": 0}
    for a in accs:
        # 보유 종목은 투자자산, 증권계좌 예수금(현금)은 현금성으로 분류한다.
        by_liq["investment"] += a["holdings_value"]
        rest = a["cash"] + a["valuation_adj"]
        liq = "cash" if a["valuation_method"] == "holdings" else a["liquidity"]
        by_liq[liq] += rest
    return {
        "total": total, "external": external, "profit": total - external,
        "realized": sum(a["realized"] for a in accs), "unrealized": sum(a["unrealized"] for a in accs),
        "dividends": sum(a["dividends"] for a in accs), "interest": sum(a["interest"] for a in accs),
        "fees": sum(a["fees"] for a in accs), "valuation_adj": sum(a["valuation_adj"] for a in accs),
        "by_liquidity": by_liq,
    }


def summary(conn, as_of: str | None = None) -> dict:
    as_of = parse_date(as_of, required=False) or date.today().isoformat()
    ledger = Ledger.load(conn)
    prev_end = month_end(add_months(as_of[:7], -1))
    ledger.run(prev_end)
    prev = _aggregate(ledger.snapshot(prev_end))
    ledger.run(as_of)
    snap = ledger.snapshot(as_of)
    agg = _aggregate(snap)
    by_type = defaultdict(lambda: {"value": 0, "count": 0})
    for a in snap["accounts"]:
        by_type[(a["type_id"], a["type_name"])]["value"] += a["value"]
        by_type[(a["type_id"], a["type_name"])]["count"] += 1
    total = agg["total"]
    types = [{"type_id": k[0], "type_name": k[1], **v,
              "share": round(v["value"] / total * 100, 1) if total > 0 else None}
             for k, v in by_type.items()]
    types.sort(key=lambda x: -x["value"])
    change = total - prev["total"]
    flow = agg["external"] - prev["external"]
    return {
        "as_of": as_of, **agg,
        "return_pct": round(agg["profit"] / agg["external"] * 100, 2) if agg["external"] > 0 else None,
        "by_type": types,
        "accounts": snap["accounts"],
        "holdings": [h for h in snap["holdings"] if h["quantity"] != "0"],
        "closed_positions": [h for h in snap["holdings"] if h["quantity"] == "0"],
        "prev_month_end": prev_end, "prev_total": prev["total"],
        "change_vs_prev_month": change,
        "change_flow": flow,               # 이번 달 외부 순유입(저축·인출)
        "change_profit": change - flow,    # 이번 달 투자 손익
        "missing_price": any(a["missing_price"] for a in snap["accounts"]),
    }


def history(conn, start: str | None = None, end: str | None = None) -> dict:
    """월말 기준 총자산·계좌별 평가액과 월별 순유입·투자손익."""
    ledger = Ledger.load(conn)
    today = date.today().isoformat()
    first = ledger.txns[0]["date"][:7] if ledger.txns else today[:7]
    start = start or first
    end = end or today[:7]
    months = month_range(start, end)
    # 시작 전 달 말일 상태를 기준으로 삼는다.
    base_end = month_end(add_months(months[0], -1))
    ledger.run(base_end)
    prev = _aggregate(ledger.snapshot(base_end))
    out = []
    account_series = defaultdict(list)
    for m in months:
        d = month_end(m)
        if d > today:
            d = today
        ledger.run(d)
        snap = ledger.snapshot(d)
        agg = _aggregate(snap)
        flow = agg["external"] - prev["external"]
        change = agg["total"] - prev["total"]
        profit = change - flow
        denom = prev["total"] + flow / 2
        out.append({
            "month": m, "date": d, "total": agg["total"], "change": change, "flow": flow, "profit": profit,
            "return_pct": round(profit / denom * 100, 2) if denom > 0 else None,
            "by_liquidity": agg["by_liquidity"], "external": agg["external"], "cum_profit": agg["profit"],
        })
        for a in snap["accounts"]:
            account_series[a["account_id"]].append({"month": m, "value": a["value"], "profit": a["profit"]})
        prev = agg
    accounts = [{"account_id": aid, "name": ledger.accounts[aid]["name"], "series": series}
                for aid, series in account_series.items()]
    return {"months": out, "accounts": accounts}
