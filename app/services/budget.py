"""월 예산.

흐름: ① 소득 기록 → ② 지출 계획으로 배분 → ③ 실제 지출 기록 → ④ 월말 정산

- 항목은 모든 달에 똑같이 표시된다(설정에서 관리). 기록이 없으면 0원.
- 각 달의 기록은 항목 아래 '세부항목'(records.item: 이름 + 금액 [+ 입금일])으로 자유롭게 남긴다.
- 지출 계획은 항목 단위다.
- 이 달 쓸 돈 = 예산 월(budget_month)이 이 달인 소득의 합
- 미배분 = 쓸 돈 - 계획 합계(목표 0원) / 남은 돈 = 쓸 돈 - 실제 지출 합계(정산 목표 0원)
- 계획 옮기기(tag='move'), 월말 정산(tag='settle')은 별도 행으로 남겨 원래 계획(tag 없음)을 보존한다.
"""
import calendar
from datetime import date

from ..db import transaction
from ..util import AppError, month_end, parse_amount, parse_month, rows


def _pace(month: str) -> float:
    today = date.today()
    cur = today.strftime("%Y-%m")
    if month < cur:
        return 1.0
    if month > cur:
        return 0.0
    days = calendar.monthrange(today.year, today.month)[1]
    return round(today.day / days, 4)


def _categories(conn) -> list[dict]:
    return rows(conn.execute(
        "SELECT id, name, kind, color, memo, is_active, sort_order FROM categories ORDER BY sort_order, id"))


def _item_view(r: dict) -> dict:
    return {"id": r["id"], "item": r["item"], "amount": r["amount"], "txn_date": r["txn_date"],
            "memo": r["memo"], "tag": r["tag"]}


def get_budget(conn, month: str) -> dict:
    month = parse_month(month)
    cats = _categories(conn)
    pace = _pace(month)

    # ── 소득: 항목별 세부항목 ──
    inc = {}
    for r in rows(conn.execute("SELECT * FROM records WHERE kind='income' AND budget_month=? ORDER BY id", (month,))):
        inc.setdefault(r["category_id"], []).append(_item_view(r))
    income_items = []
    for c in cats:
        items = inc.get(c["id"], [])
        if not items and not (c["kind"] == "income" and c["is_active"]):
            continue
        income_items.append({
            "category_id": c["id"], "name": c["name"], "full_name": c["name"], "color": c["color"], "memo": c["memo"],
            "is_active": bool(c["is_active"]), "items": items, "count": len(items),
            "total": sum(i["amount"] for i in items), "pending": sum(i["amount"] for i in items if not i["txn_date"]),
        })
    income_total = sum(i["total"] for i in income_items)
    income_pending = sum(i["pending"] for i in income_items)

    # ── 지출: 항목별 계획 + 세부항목 ──
    plan, plan_base = {}, {}
    for r in conn.execute(
        "SELECT category_id, tag, SUM(amount) AS amt FROM records WHERE kind='plan' AND month=? GROUP BY category_id, tag",
        (month,),
    ):
        plan[r["category_id"]] = plan.get(r["category_id"], 0) + r["amt"]
        if r["tag"] is None:
            plan_base[r["category_id"]] = r["amt"]
    exp = {}
    for r in rows(conn.execute("SELECT * FROM records WHERE kind='expense' AND month=? ORDER BY tag IS NOT NULL, id", (month,))):
        exp.setdefault(r["category_id"], []).append(_item_view(r))
    envelopes = []
    for c in cats:
        cid = c["id"]
        items = exp.get(cid, [])
        if cid not in plan and not items and not (c["kind"] == "expense" and c["is_active"]):
            continue
        p, s = plan.get(cid, 0), sum(i["amount"] for i in items)
        rate = s / p if p > 0 else None
        if p <= 0:
            status = "unplanned" if s > 0 else "empty"
        elif s > p:
            status = "over"
        elif s == p:
            status = "done"
        elif pace < 1 and rate > pace + 0.1:
            status = "fast"
        else:
            status = "ok"
        envelopes.append({
            "category_id": cid, "name": c["name"], "full_name": c["name"], "color": c["color"], "memo": c["memo"],
            "is_active": bool(c["is_active"]), "plan": p, "plan_base": plan_base.get(cid, 0), "spent": s,
            "remaining": p - s, "items": items, "count": len(items),
            "rate": round(rate * 100, 1) if rate is not None else None, "status": status,
        })

    plan_total = sum(plan.values())
    spent_total = sum(e["spent"] for e in envelopes)
    target = _settle_target(conn, month)
    settled = target is not None
    settle_spent = conn.execute("SELECT IFNULL(SUM(amount),0) FROM records WHERE tag='settle' AND kind='expense' AND month=?",
                                (month,)).fetchone()[0]
    unallocated = income_total - plan_total
    leftover = income_total - spent_total
    return {
        "month": month, "pace": pace, "is_past": pace >= 1.0,
        "income_items": income_items, "income_total": income_total, "income_pending": income_pending,
        "envelopes": envelopes, "plan_total": plan_total, "spent_total": spent_total,
        "unallocated": unallocated, "leftover": leftover,
        "over_total": sum(e["spent"] - e["plan"] for e in envelopes if e["spent"] > e["plan"]),
        "settled": settled, "settle_target": target,
        # 정산 기록을 뺀 남은 돈. 다시 정산할 수 있는지(≥ 0) 판단할 때 쓴다.
        "leftover_before_settle": leftover + settle_spent, "balanced": unallocated == 0 and leftover == 0 and income_total > 0,
    }


def _check_category(conn, cid, kind: str | None = None) -> int:
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        raise AppError.of("category.select") from None
    r = conn.execute("SELECT kind FROM categories WHERE id=?", (cid,)).fetchone()
    if not r:
        raise AppError.of("budget.category_missing")
    if kind and r["kind"] != kind:
        raise AppError.of("budget.not_income_category" if kind == "income" else "budget.not_expense_category")
    return cid


def _settle_target(conn, month: str):
    """그 달 정산의 대상 항목(정산 전이면 None). 남은 돈 지출 행 > 조정 없음 표식 > 첫 정산 행 순으로 찾는다."""
    r = conn.execute("""SELECT category_id FROM records WHERE tag='settle' AND month=?
                        ORDER BY (kind='expense') DESC, (memo='월말 정산(조정 없음)') DESC, id LIMIT 1""", (month,)).fetchone()
    return r["category_id"] if r else None


def _set_plan_total(conn, month: str, cid: int, amount: int) -> None:
    """항목의 그 달 계획 합계가 amount 가 되게 맞춘다. 옮기기·정산 조정(tag)은 두고 사용자 계획을 한 행으로 바꾼다.
    트랜잭션은 호출하는 쪽에서 연다."""
    tagged = conn.execute("SELECT IFNULL(SUM(amount),0) FROM records WHERE kind='plan' AND month=? AND category_id=? AND tag IS NOT NULL",
                          (month, cid)).fetchone()[0]
    conn.execute("DELETE FROM records WHERE kind='plan' AND month=? AND category_id=? AND tag IS NULL", (month, cid))
    if amount - tagged:
        conn.execute("INSERT INTO records (kind, category_id, amount, month) VALUES ('plan', ?, ?, ?)", (cid, amount - tagged, month))


def set_plan(conn, month: str, category_id, amount) -> dict:
    """지출 항목의 계획 금액(옮기기·정산 조정 포함 최종값)을 amount 로 맞춘다."""
    month = parse_month(month)
    cid = _check_category(conn, category_id, "expense")
    amount = parse_amount(amount if amount not in (None, "") else 0, "계획 금액")
    with transaction(conn):
        _set_plan_total(conn, month, cid, amount)
    return get_budget(conn, month)


def move_plan(conn, month: str, from_category_id, to_category_id, amount) -> dict:
    """from 항목의 계획을 to 항목으로 옮긴다. from 이 없으면 미배분 금액에서 가져온다."""
    month = parse_month(month)
    to_id = _check_category(conn, to_category_id, "expense")
    from_id = _check_category(conn, from_category_id, "expense") if from_category_id not in (None, "", 0) else None
    if from_id == to_id:
        raise AppError.of("budget.move_same")
    amount = parse_amount(amount, "옮길 금액", allow_zero=False)
    if not from_id:
        free = get_budget(conn, month)["unallocated"]
        if amount > free:
            raise AppError.of("budget.move_over_unallocated", amount=max(free, 0))
    with conn:
        if from_id:
            avail = conn.execute("SELECT IFNULL(SUM(amount),0) FROM records WHERE kind='plan' AND month=? AND category_id=?",
                                 (month, from_id)).fetchone()[0]
            if amount > avail:
                raise AppError.of("budget.move_over_plan", amount=avail)
            conn.execute("INSERT INTO records (kind, category_id, amount, month, memo, tag) VALUES ('plan', ?, ?, ?, ?, 'move')",
                         (from_id, -amount, month, "계획 옮기기(보냄)"))
        conn.execute("INSERT INTO records (kind, category_id, amount, month, memo, tag) VALUES ('plan', ?, ?, ?, ?, 'move')",
                     (to_id, amount, month, "계획 옮기기(받음)" if from_id else "미배분에서 추가"))
    return get_budget(conn, month)


def settle(conn, month: str, target_category_id=None) -> dict:
    """월말 정산: 남은 돈을 target 지출 항목(예: 저축·투자)으로 보내 수입 = 계획 = 지출로 맞춘다.

    이미 정산된 달이면 기존 정산 기록을 지우고 지금 기록 기준으로 다시 정산한다(한 트랜잭션).
    target 을 주지 않으면 지난 정산의 대상 항목을 그대로 쓴다.
    """
    month = parse_month(month)
    with transaction(conn):
        if target_category_id in (None, "", 0):
            target_category_id = _settle_target(conn, month)
            if target_category_id is None:
                raise AppError.of("budget.settle_select_target")
        target = _check_category(conn, target_category_id, "expense")
        conn.execute("DELETE FROM records WHERE tag='settle' AND month=?", (month,))
        b = get_budget(conn, month)
        if b["income_total"] <= 0:
            raise AppError.of("budget.settle_no_income")
        if b["leftover"] < 0:
            raise AppError.of("budget.settle_overspent", amount=-b["leftover"])
        env = {e["category_id"]: e for e in b["envelopes"]}
        env.setdefault(target, {"plan": 0, "spent": 0})
        for cid, e in env.items():
            diff = e["spent"] + (b["leftover"] if cid == target else 0) - e["plan"]
            if diff:
                conn.execute("INSERT INTO records (kind, category_id, amount, month, memo, tag) VALUES ('plan', ?, ?, ?, ?, 'settle')",
                             (cid, diff, month, "월말 정산(계획 조정)"))
        if b["leftover"] > 0:
            conn.execute("""INSERT INTO records (kind, category_id, amount, month, txn_date, memo, item, tag)
                            VALUES ('expense', ?, ?, ?, ?, '월말 정산(남은 돈)', '월말 정산', 'settle')""",
                         (target, b["leftover"], month, month_end(month)))
        if not conn.execute("SELECT 1 FROM records WHERE tag='settle' AND month=?", (month,)).fetchone():
            conn.execute("INSERT INTO records (kind, category_id, amount, month, memo, tag) VALUES ('plan', ?, 0, ?, '월말 정산(조정 없음)', 'settle')",
                         (target, month))
    return get_budget(conn, month)


def unsettle(conn, month: str) -> dict:
    month = parse_month(month)
    with conn:
        conn.execute("DELETE FROM records WHERE tag='settle' AND month=?", (month,))
    return get_budget(conn, month)


def _plan_to_copy(conn, src: str) -> dict:
    """src 달 계획 중 다음 달로 불러올 금액: 옮기기 반영, 정산 조정 제외, 0보다 큰 활성 지출 항목."""
    return {r["category_id"]: r["amt"] for r in conn.execute(
        """SELECT r.category_id, SUM(r.amount) AS amt FROM records r JOIN categories c ON c.id = r.category_id
           WHERE r.kind='plan' AND r.month=? AND IFNULL(r.tag,'') <> 'settle' AND c.is_active=1 AND c.kind='expense'
           GROUP BY r.category_id HAVING SUM(r.amount) > 0""", (src,))}


def _income_to_copy(conn, src: str) -> list[dict]:
    """src 달 예산으로 잡힌 소득 세부항목(사용자 기록)."""
    return rows(conn.execute(
        """SELECT r.category_id, r.item, r.amount FROM records r JOIN categories c ON c.id = r.category_id
           WHERE r.kind='income' AND r.budget_month=? AND r.tag IS NULL AND c.is_active=1 AND c.kind='income'
           ORDER BY c.sort_order, r.id""", (src,)))


def copy_preview(conn, src: str, dst: str) -> dict:
    """지난달 불러오기 창에 보여 줄 요약."""
    src, dst = parse_month(src), parse_month(dst)
    plan, inc = _plan_to_copy(conn, src), _income_to_copy(conn, src)
    cur = {r[0] for r in conn.execute("SELECT category_id FROM records WHERE kind='plan' AND month=? GROUP BY category_id HAVING SUM(amount)<>0", (dst,))}
    named = [i for i in inc if i["item"]]
    return {"from": src, "to": dst,
            "income_items": len(named), "income_total": sum(i["amount"] for i in inc), "income_all": len(inc),
            "plan_items": len(plan), "plan_total": sum(plan.values()),
            "plan_overwrite": len(cur & set(plan))}


def copy_month(conn, src: str, dst: str, items: bool = True, amounts: bool = True) -> dict:
    """지난달(src) 내용을 이번 달(dst)로 불러온다. 한 트랜잭션.

    - items   : 소득 세부항목을 이번 달에 같은 이름으로 만든다(미입금). 이미 같은 이름이 있으면 건너뛴다.
    - amounts : 금액도 불러온다. 소득 세부항목은 그 금액으로, 지출 계획은 항목별 금액으로 맞춘다(기존 계획은 바뀐다).
    items 만 고르면 소득 세부항목 이름만 0원으로 만들고 지출 계획은 그대로 둔다.
    """
    src, dst = parse_month(src), parse_month(dst)
    if not items and not amounts:
        raise AppError.of("budget.copy_nothing_selected")
    plan = _plan_to_copy(conn, src) if amounts else {}
    inc = _income_to_copy(conn, src) if items else []
    if not amounts:
        inc = [i for i in inc if i["item"]]  # 이름 없는 세부항목은 금액 없이 불러올 의미가 없다
    if not plan and not inc:
        raise AppError.of("budget.copy_empty", month=src)
    have = {(r["category_id"], r["item"] or "") for r in conn.execute(
        "SELECT category_id, item FROM records WHERE kind='income' AND budget_month=?", (dst,))}
    added = 0
    with transaction(conn):
        for i in inc:
            key = (i["category_id"], i["item"] or "")
            if i["item"] and key in have:
                continue
            have.add(key)
            conn.execute("INSERT INTO records (kind, category_id, amount, month, budget_month, item) VALUES ('income', ?, ?, ?, ?, ?)",
                         (i["category_id"], i["amount"] if amounts else 0, dst, dst, i["item"]))
            added += 1
        if plan:
            conn.execute("DELETE FROM records WHERE kind='plan' AND month=? AND amount=0 AND tag IS NULL", (dst,))
        for cid, amount in plan.items():
            _set_plan_total(conn, dst, cid, amount)
    return {**get_budget(conn, dst), "copied": {"income_items": added, "plan_items": len(plan)}}

