"""수입·지출 통계.

용어 정의
- 집계 기준(basis)
    budget : 월 예산과 같은 기준(기본). 소득은 예산 월(그 달에 쓸 돈으로 넣은 달), 계획·지출은 그 달.
    cash   : 입금·결제일 기준. 소득은 실제 입금일의 월(미입금 제외), 지출은 결제일(없으면 발생일)의 월.
- 저축 항목: 설정 > 항목에서 '저축'으로 지정한 지출 항목(categories.savings_category_ids).
- 저축액 = 그 달 저축 항목에 넣은 실제 지출 합계(정산 지출 줄 포함, 계획 제외, 지출과 같은 월 기준).
    자산 계좌 잔액의 실제 변화(자산 페이지의 '자산 증감')와는 다른 값이다.
- 저축률 = 저축액 / 수입 x 100 (수입이 0 이하이면 없음).
- 저축 외 지출(non-savings expense) = 실제 지출 합계 - 저축액 (API key: living_expense)
- 남은 돈(leftover) = 수입 - 실제 지출
- 계획 대비 차이 = 실제 지출 - 지출 계획. 양수 = 초과 지출, 음수 = 절약.
"""
import sqlite3

from ..util import AppError, add_months, month_range, parse_month
from .categories import savings_category_ids
from .records import month_expr

BASES = ("budget", "cash")
BASIS_LABEL = {"budget": "예산 월 기준", "cash": "입금·결제일 기준"}


def _check_basis(basis: str) -> str:
    if basis not in BASES:
        raise AppError.of("stats.invalid_basis")
    return basis


def totals_by_month(conn: sqlite3.Connection, kind: str, start: str, end: str, basis: str) -> dict[str, int]:
    mexpr = month_expr(kind, basis)
    cur = conn.execute(
        f"""SELECT {mexpr} AS m, SUM(r.amount) AS total FROM records r
            WHERE r.kind = ? AND {mexpr} BETWEEN ? AND ? GROUP BY m""",
        (kind, start, end),
    )
    return {r["m"]: r["total"] for r in cur.fetchall()}


def _savings_by_month(conn, start: str, end: str, basis: str) -> dict[str, int]:
    """저축 항목에 넣은 실제 지출의 월별 합계."""
    ids = sorted(savings_category_ids(conn))
    if not ids:
        return {}
    mexpr = month_expr("expense", basis)
    q = ",".join("?" * len(ids))
    cur = conn.execute(
        f"""SELECT {mexpr} AS m, SUM(r.amount) AS total FROM records r
            WHERE r.kind = 'expense' AND r.category_id IN ({q}) AND {mexpr} BETWEEN ? AND ? GROUP BY m""",
        (*ids, start, end),
    )
    return {r["m"]: r["total"] for r in cur.fetchall()}


def trend(conn, start: str, end: str, basis: str = "budget") -> list[dict]:
    start, end = parse_month(start), parse_month(end)
    _check_basis(basis)
    months = month_range(start, end)
    start, end = months[0], months[-1]
    inc = totals_by_month(conn, "income", start, end, basis)
    exp = totals_by_month(conn, "expense", start, end, basis)
    plan = totals_by_month(conn, "plan", start, end, basis)
    sav = _savings_by_month(conn, start, end, basis)
    out = []
    for m in months:
        i, e, p, s = inc.get(m, 0), exp.get(m, 0), plan.get(m, 0), sav.get(m, 0)
        out.append({
            "month": m, "income": i, "expense": e, "plan": p, "savings": s,
            "savings_rate": round(s / i * 100, 1) if i > 0 else None,
            "living_expense": e - s,
            "plan_diff": e - p if p else None,
            "leftover": i - e,
        })
    return out


def plan_vs_actual(conn, month: str, basis: str = "budget") -> dict:
    """항목별 지출 계획 대비 실제 지출. 계획은 항상 계획 월 기준, 실제는 선택한 기준."""
    month = parse_month(month)
    _check_basis(basis)
    mexpr = month_expr("expense", basis)
    plan_rows = conn.execute(
        "SELECT category_id, SUM(amount) AS amt, COUNT(*) AS n FROM records r WHERE kind='plan' AND month=? GROUP BY category_id",
        (month,),
    ).fetchall()
    actual_rows = conn.execute(
        f"SELECT category_id, SUM(amount) AS amt, COUNT(*) AS n FROM records r WHERE kind='expense' AND {mexpr}=? GROUP BY category_id",
        (month,),
    ).fetchall()
    plans = {r["category_id"]: r["amt"] for r in plan_rows}
    actuals = {r["category_id"]: (r["amt"], r["n"]) for r in actual_rows}
    ids = set(plans) | set(actuals)
    cats = {}
    if ids:
        q = ",".join("?" * len(ids))
        for r in conn.execute(
            f"SELECT c.id, c.name, c.color, c.sort_order FROM categories c WHERE c.id IN ({q})",
            list(ids),
        ):
            cats[r["id"]] = dict(r)
    items = []
    for cid in ids:
        c = cats[cid]
        plan = plans.get(cid, 0)
        actual, n = actuals.get(cid, (0, 0))
        diff = actual - plan
        status = "ok"
        if cid in plans and n == 0:
            status = "no_actual"
        elif cid not in plans:
            status = "unplanned"
        elif diff > 0:
            status = "over"
        items.append({
            "category_id": cid,
            "category_name": c["name"],
            "category_full_name": c["name"],
            "color": c["color"],
            "plan": plan, "actual": actual, "diff": diff,
            "rate": round(actual / plan * 100, 1) if plan > 0 else None,
            "status": status,
            "_sort": c["sort_order"],
        })
    items.sort(key=lambda x: x.pop("_sort"))
    total_plan = sum(plans.values())
    total_actual = sum(a for a, _ in actuals.values())
    planned_actual = sum(actuals.get(cid, (0, 0))[0] for cid in plans)
    return {
        "month": month, "basis": basis, "items": items,
        "total_plan": total_plan, "total_actual": total_actual,
        "total_diff": total_actual - total_plan,
        "remaining_budget": total_plan - total_actual,
        "planned_actual": planned_actual,
        "unplanned_actual": total_actual - planned_actual,
        "over_count": sum(1 for i in items if i["status"] == "over"),
        "no_actual_count": sum(1 for i in items if i["status"] == "no_actual"),
    }


def category_breakdown(conn, kind: str, start: str, end: str, basis: str = "budget",
                       rollup: bool = False) -> list[dict]:
    """기간 내 항목별 합계와 비중. rollup=True 면 하위 분류를 상위 분류로 합친다."""
    start, end = parse_month(start), parse_month(end)
    if start > end:
        start, end = end, start
    _check_basis(basis)
    mexpr = month_expr(kind, basis)
    group_id = "COALESCE(c.parent_id, c.id)" if rollup else "c.id"
    cur = conn.execute(
        f"""SELECT {group_id} AS gid, SUM(r.amount) AS total, COUNT(*) AS n
            FROM records r JOIN categories c ON c.id = r.category_id
            WHERE r.kind = ? AND {mexpr} BETWEEN ? AND ? GROUP BY gid""",
        (kind, start, end),
    )
    data = [dict(r) for r in cur.fetchall()]
    grand = sum(d["total"] for d in data)
    out = []
    for d in data:
        c = conn.execute(
            "SELECT c.name, c.color FROM categories c WHERE c.id=?",
            (d["gid"],),
        ).fetchone()
        out.append({
            "category_id": d["gid"],
            "category_name": c["name"],
            "category_full_name": c["name"],
            "color": c["color"],
            "total": d["total"], "count": d["n"],
            "share": round(d["total"] / grand * 100, 1) if grand > 0 else None,
        })
    out.sort(key=lambda x: -x["total"])
    return out


def pending_income(conn, month: str | None = None) -> dict:
    """입금일이 비어 있는(미입금) 수입. month 를 주면 그 달 예산으로 잡힌 것만 센다."""
    sql = "SELECT COUNT(*) AS n, IFNULL(SUM(amount),0) AS total FROM records WHERE kind='income' AND txn_date IS NULL"
    params = []
    if month:
        sql += " AND COALESCE(budget_month, month) = ?"
        params.append(parse_month(month))
    r = conn.execute(sql, params).fetchone()
    return {"count": r["n"], "total": r["total"]}


def month_summary(conn, month: str, basis: str = "budget") -> dict:
    month = parse_month(month)
    _check_basis(basis)
    t = trend(conn, month, month, basis)[0]
    prev = trend(conn, add_months(month, -1), add_months(month, -1), basis)[0]
    pva = plan_vs_actual(conn, month, basis)
    return {
        "month": month, "basis": basis, "basis_label": BASIS_LABEL[basis],
        **{k: t[k] for k in ("income", "expense", "plan", "savings", "savings_rate", "living_expense")},
        "prev_income": prev["income"], "prev_expense": prev["expense"], "prev_savings": prev["savings"],
        "prev_living_expense": prev["living_expense"],
        "savings_category_count": len(savings_category_ids(conn)),
        "plan_diff": pva["total_diff"] if pva["total_plan"] else None,
        "remaining_budget": pva["remaining_budget"] if pva["total_plan"] else None,
        "over_count": pva["over_count"],
        "pending_income": pending_income(conn, month),
    }


def annual(conn, year: int, basis: str = "budget") -> dict:
    if not (1900 <= int(year) <= 2999):
        raise AppError.of("stats.invalid_year")
    months = trend(conn, f"{year}-01", f"{year}-12", basis)
    inc = sum(m["income"] for m in months)
    exp = sum(m["expense"] for m in months)
    plan = sum(m["plan"] for m in months)
    sav = sum(m["savings"] for m in months)
    return {
        "year": int(year), "basis": basis, "months": months,
        "income": inc, "expense": exp, "plan": plan, "savings": sav,
        "savings_rate": round(sav / inc * 100, 1) if inc > 0 else None,
        "living_expense": exp - sav,
        "top_expenses": category_breakdown(conn, "expense", f"{year}-01", f"{year}-12", basis)[:10],
        "top_incomes": category_breakdown(conn, "income", f"{year}-01", f"{year}-12", basis)[:10],
    }
