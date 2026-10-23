"""Dashboard flow (loop 2026-10-24-001): trend `leftover`, "저축 외 지출" wording, chart layout, annual summary box."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import budget, categories, records, stats
from conftest import cat_id

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
DASH = JS / "pages" / "dashboard.js"
CSS = ROOT / "app" / "static" / "css" / "app.css"
NODE = shutil.which("node")
M = "2026-08"
SAV = "저축·투자"

OLD_KEYS = ("month", "income", "expense", "plan", "savings", "savings_rate", "living_expense", "plan_diff")


def _rec(conn, kind, name, amount, month=M, **kw):
    return records.create_record(conn, {"kind": kind, "category_id": cat_id(conn, name), "amount": amount,
                                        "month": month, **kw})


def _base_month(conn, month=M):
    _rec(conn, "income", "급여", 1_000_000, month)
    _rec(conn, "expense", "식비", 300_000, month)
    _rec(conn, "expense", SAV, 500_000, month)


def _dash():
    return DASH.read_text(encoding="utf-8")


# ── server: trend leftover ──

def test_trend_rows_have_leftover_equal_income_minus_expense(conn):
    _base_month(conn, "2026-07")
    _rec(conn, "income", "급여", 2_000_000, M)
    _rec(conn, "expense", "식비", 400_000, M)
    rows = stats.trend(conn, "2026-06", "2026-09")
    assert len(rows) == 4
    for r in rows:
        assert "leftover" in r, r["month"]
        assert isinstance(r["leftover"], int) and not isinstance(r["leftover"], bool)
        assert r["leftover"] == r["income"] - r["expense"], r["month"]
    by = {r["month"]: r for r in rows}
    assert by["2026-07"]["leftover"] == 200_000
    assert by[M]["leftover"] == 1_600_000


def test_trend_default_basis_is_budget_leftover(conn):
    _base_month(conn)
    assert stats.trend(conn, M, M)[0]["leftover"] == stats.trend(conn, M, M, "budget")[0]["leftover"] == 200_000


def test_settled_month_leftover_zero(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 0
    assert t["income"] == t["expense"] == 1_000_000


def test_settled_to_non_savings_leftover_zero(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, "기타"))
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 0
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_overspent_month_leftover_negative(conn):
    _rec(conn, "income", "급여", 500_000)
    _rec(conn, "expense", "식비", 700_000)
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == -200_000
    assert t["leftover"] == t["income"] - t["expense"]


def test_zero_income_expense_only_leftover_negative_rate_none(conn):
    _rec(conn, "expense", "식비", 300_000)
    _rec(conn, "expense", SAV, 200_000)
    t = stats.trend(conn, M, M)[0]
    assert t["income"] == 0
    assert t["leftover"] == -500_000
    assert t["savings_rate"] is None


def test_empty_month_leftover_zero(conn):
    _base_month(conn, "2026-07")
    rows = {r["month"]: r for r in stats.trend(conn, "2026-07", "2026-09")}
    for m in (M, "2026-09"):
        assert rows[m]["leftover"] == 0
        assert rows[m]["income"] == rows[m]["expense"] == 0


def test_empty_db_trend_leftover_zero(conn):
    rows = stats.trend(conn, M, M)
    assert rows[0]["leftover"] == 0


def test_identity_before_settle(conn):
    _base_month(conn)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 500_000
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_identity_after_settle(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 700_000
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_identity_with_negative_savings_correction(conn):
    _base_month(conn)
    _rec(conn, "expense", SAV, -100_000)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 400_000
    assert t["leftover"] == 300_000
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_identity_with_negative_correction_after_settle(conn):
    _base_month(conn)
    _rec(conn, "expense", SAV, -100_000)
    budget.settle(conn, M, cat_id(conn, SAV))
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 0
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]


def test_settled_then_changed_month_leftover_follows_current_records(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    _rec(conn, "income", "급여", 100_000)
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == 100_000 == t["income"] - t["expense"]
    assert t["living_expense"] + t["savings"] + t["leftover"] == t["income"]
    _rec(conn, "expense", "식비", 250_000)
    t = stats.trend(conn, M, M)[0]
    assert t["leftover"] == -150_000 == t["income"] - t["expense"]


def test_no_savings_categories_leftover(conn):
    categories.update_category(conn, cat_id(conn, SAV), {"is_savings": False})
    _base_month(conn)
    t = stats.trend(conn, M, M)[0]
    assert t["savings"] == 0
    assert t["living_expense"] == t["expense"] == 800_000
    assert t["leftover"] == t["income"] - t["expense"] == 200_000


def test_cash_basis_leftover(conn):
    # income deposited in Sep, expenses paid across Aug/Sep/Oct
    _rec(conn, "income", "급여", 1_000_000, M, txn_date="2026-09-05")
    _rec(conn, "expense", SAV, 300_000, M, txn_date="2026-09-02")
    _rec(conn, "expense", "식비", 100_000, M, txn_date="2026-08-05", settle_date="2026-10-15")
    _rec(conn, "expense", "식비", 50_000, M)
    rows = stats.trend(conn, M, "2026-10", "cash")
    assert len(rows) == 3
    for r in rows:
        assert "leftover" in r, r["month"]
        assert r["leftover"] == r["income"] - r["expense"], r["month"]
    # the months differ from budget basis, so at least one row carries non-trivial numbers
    assert any(r["leftover"] != 0 for r in rows)


# ── server: existing keys unchanged ──

def test_trend_existing_keys_and_values_unchanged(conn):
    _base_month(conn)
    _rec(conn, "plan", "식비", 350_000)
    t = stats.trend(conn, M, M)[0]
    for k in OLD_KEYS:
        assert k in t, k
    assert t["month"] == M
    assert t["income"] == 1_000_000
    assert t["expense"] == 800_000
    assert t["plan"] == 350_000
    assert t["savings"] == 500_000
    assert t["savings_rate"] == 50.0
    assert t["living_expense"] == 300_000
    assert t["plan_diff"] is not None


def test_annual_months_have_leftover(conn):
    _base_month(conn, "2026-08")
    _rec(conn, "income", "급여", 1_000_000, "2026-09")
    _rec(conn, "expense", "식비", 1_200_000, "2026-09")
    a = stats.annual(conn, 2026)
    assert a["months"]
    for m in a["months"]:
        assert "leftover" in m, m["month"]
        assert m["leftover"] == m["income"] - m["expense"], m["month"]
    by = {m["month"]: m for m in a["months"]}
    assert by["2026-08"]["leftover"] == 200_000
    assert by["2026-09"]["leftover"] == -200_000


def test_annual_and_summary_top_level_keys_kept(conn):
    _base_month(conn, "2026-07")
    _base_month(conn)
    a = stats.annual(conn, 2026)
    for k in ("year", "basis", "months", "income", "expense", "plan", "savings", "savings_rate",
              "living_expense", "top_expenses", "top_incomes"):
        assert k in a, k
    s = stats.month_summary(conn, M)
    for k in ("income", "expense", "plan", "savings", "savings_rate", "prev_income", "prev_expense", "prev_savings",
              "plan_diff", "remaining_budget", "over_count", "pending_income", "basis", "basis_label", "month",
              "living_expense", "prev_living_expense", "savings_category_count"):
        assert k in s, k
    assert s["living_expense"] == 300_000 and s["prev_living_expense"] == 300_000


# ── API ──

def _api_records(client, rows):
    cats = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    for kind, name, amt, extra in rows:
        r = client.post("/api/records", json={"kind": kind, "category_id": cats[name], "amount": amt,
                                              "month": M, **extra})
        assert r.status_code == 200, r.text


def test_api_trend_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {}), ("expense", "식비", 300_000, {}),
                          ("expense", SAV, 500_000, {})])
    r = client.get("/api/stats/trend", params={"start": "2026-07", "end": M})
    assert r.status_code == 200
    rows = {x["month"]: x for x in r.json()}
    for x in rows.values():
        assert "leftover" in x
        assert x["leftover"] == x["income"] - x["expense"]
    assert rows[M]["leftover"] == 200_000
    assert rows["2026-07"]["leftover"] == 0


def test_api_trend_cash_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {"txn_date": "2026-09-03"}),
                          ("expense", "식비", 300_000, {"txn_date": "2026-08-10"}),
                          ("expense", SAV, 200_000, {"txn_date": "2026-09-20"})])
    r = client.get("/api/stats/trend", params={"start": M, "end": "2026-09", "basis": "cash"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    for x in rows:
        assert "leftover" in x
        assert x["leftover"] == x["income"] - x["expense"]


def test_api_annual_months_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {}), ("expense", "식비", 300_000, {})])
    a = client.get("/api/stats/annual", params={"year": 2026}).json()
    by = {m["month"]: m for m in a["months"]}
    assert by[M]["leftover"] == 700_000
    assert "living_expense" in a and "savings_rate" in a


# ── static checks: dashboard.js / app.css ──

REQUIRED = ("저축 외 지출", "월별 수입·지출·저축 추이", "막대는 월별 수입·저축·저축 외 지출이고, 클릭하면 해당 월로 이동합니다.",
            "저축률 = 저축액 ÷ 수입", "연간 저축 외 지출", "월평균 저축 외 지출", "연간 저축률", "living_expense",
            "저축액", "실제 지출")
FORBIDDEN = ("생활비 지출", 'label: "지출 계획"', "저축액 · 저축률", "y1", "지출 계획 대비", "(수입−지출)",
             "수입 − 실제 지출", "남은 돈")


@pytest.mark.parametrize("w", REQUIRED)
def test_dashboard_required_literal(w):
    assert w in _dash(), w


@pytest.mark.parametrize("w", FORBIDDEN)
def test_dashboard_forbidden_literal(w):
    assert w not in _dash(), w


def test_dashboard_old_trend_title_removed():
    src = _dash()
    # the new title "월별 수입·지출·저축 추이" does not contain "월별 수입·지출 추이"
    assert "월별 수입·지출 추이" not in src
    assert "월별 수입·지출·저축 추이" in src


def test_dashboard_rate_labels_plugin():
    src = _dash()
    assert "rateLabels" in src
    assert "afterDatasetsDraw" in src
    assert re.search(r"""id\s*:\s*["'`]rateLabels["'`]""", src)


def test_dashboard_annual_summary_boxed():
    src = _dash()
    assert 'class="kv boxed"' in src
    assert 'style="margin:0 0 10px"' not in src


def test_css_kv_boxed_rule():
    css = CSS.read_text(encoding="utf-8")
    assert ".kv.boxed" in css


@pytest.mark.skipif(NODE is None, reason="node 없음")
def test_dashboard_js_module_syntax():
    with open(DASH, "rb") as f:
        r = subprocess.run([NODE, "--check", "--input-type=module"], stdin=f, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-500:]


# ── loop 2026-10-24-002: grouped trend bars, month in plan panel title, lined top-items table ──

Q = "[\"'`]"


def _fn_body(src, name):
    """Slice `function <name>` up to the next `function ` definition. Fails (never skips) when missing."""
    m = re.search(r"function\s+" + re.escape(name) + r"\b", src)
    assert m, f"function {name} not found in dashboard.js"
    nxt = re.search(r"\bfunction\s+[A-Za-z_$]", src[m.end():])
    return src[m.start(): m.end() + nxt.start()] if nxt else src[m.start():]


def _trend():
    return _fn_body(_dash(), "TrendChart")


def _css_rule(css, selector):
    """Return the declaration block of the first rule whose selector list contains `selector` exactly."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sels = [x.strip() for x in m.group(1).split(",")]
        if selector in sels:
            return m.group(2)
    return None


def test_dashboard_no_stacking():
    src = _dash()
    assert "stacked" not in src
    assert "stack:" not in src
    assert not re.search(r"\bstack\s*:", src)


def test_dashboard_no_line_dataset():
    assert not re.search(r"type\s*:\s*" + Q + "line" + Q, _dash())


def _label_pos(body, text):
    m = re.search(r"label\s*:\s*" + Q + re.escape(text) + Q, body)
    assert m, f'label "{text}" not found in TrendChart'
    return m.start()


def test_trend_dataset_label_order():
    body = _trend()
    a = _label_pos(body, "수입")
    b = _label_pos(body, "저축")
    c = _label_pos(body, "저축 외 지출")
    assert a < b < c, (a, b, c)


def test_trend_dataset_data_fields():
    body = _trend()
    for f in ("income", "savings", "living_expense"):
        assert re.search(r"\bd\s*\.\s*" + f + r"\b", body), f"d.{f}"


@pytest.mark.parametrize("color", ("#2459d6", "#19a979", "#e8743b"))
def test_trend_dataset_colors(color):
    assert color.lower() in _trend().lower(), color


def test_trend_tooltip_filter_null_nan():
    body = _trend()
    assert "filter" in body
    assert re.search(r"!==?\s*null", body)
    assert "isNaN" in body


def test_trend_keeps_index_mode_and_navigate():
    body = _trend()
    assert re.search(r"mode\s*:\s*" + Q + "index" + Q, body)
    assert re.search(r"navigate\(\s*" + Q + "cashflow" + Q, body)


def test_panel_titles_without_month():
    # loop 2026-10-24-003: the month moved into the section heading; panel titles carry no month
    src = _dash()
    assert src.count("${monthLabel(month)}") == 1, src.count("${monthLabel(month)}")
    for w in ("${monthLabel(month)} 항목별 계획 대비 실제", "${monthLabel(month)} 항목별 지출 비중",
              "${monthLabel(month)} 수입"):
        assert w not in src, w
    assert "<h2>항목별 지출 비중</h2>" in src
    assert "<h2>항목별 계획 대비 실제</h2>" in src
    assert '<div class="label">수입</div>' in src


def test_annual_top_items_table_lined():
    src = _dash()
    assert '<table class="t lined">' in src
    assert 'class="kv boxed"' in src


def test_css_lined_table_rules():
    css = CSS.read_text(encoding="utf-8")
    td = _css_rule(css, "table.t.lined td")
    assert td is not None, "table.t.lined td rule missing"
    assert re.search(r"var\(--line\)", td), td
    th = _css_rule(css, "table.t.lined thead th")
    assert th is not None, "table.t.lined thead th rule missing"
    assert "border-bottom" in th
    base = _css_rule(css, "table.t td")
    assert base is not None and "var(--line-2)" in base
    assert _css_rule(css, "table.t th") == base


# ── loop 2026-10-24-003: month/flow sections, selected-month band ──

SEC_MONTH = '<section class="dash-section dash-month">'
SEC_FLOW = '<section class="dash-section dash-flow">'


def _sections(src):
    assert src.count(SEC_MONTH) == 1, src.count(SEC_MONTH)
    assert src.count(SEC_FLOW) == 1, src.count(SEC_FLOW)
    return src.index(SEC_MONTH), src.index(SEC_FLOW)


def _savings():
    return _fn_body(_dash(), "SavingsChart")


def _month_band_def(src):
    m = re.search(r"\bconst\s+monthBand\b", src)
    assert m, "const monthBand not found"
    # Cut at the next *top-level* definition (line start), not locals inside the plugin body.
    nxt = re.search(r"^(const|function)\s+[A-Za-z_$]", src[m.end():], re.M)
    return src[m.start(): m.end() + nxt.start()] if nxt else src[m.start():]


def test_sections_present_once_and_ordered():
    mpos, fpos = _sections(_dash())
    assert mpos < fpos, (mpos, fpos)


def test_section_headings():
    # loop 2026-10-24-004: the month heading stays; the "흐름" heading is gone
    src = _dash()
    assert '<h2 class="section-title">${monthLabel(month)}</h2>' in src
    assert "흐름" not in src
    assert src.count('class="section-title"') == 1, src.count('class="section-title"')
    mpos, fpos = _sections(src)
    assert mpos < src.index('<h2 class="section-title">${monthLabel(month)}</h2>') < fpos


def test_month_label_template_once():
    src = _dash()
    assert src.count("${monthLabel(month)}") == 1


def test_month_section_content_order():
    src = _dash()
    mpos, fpos = _sections(src)
    pos = mpos
    for w in ('class="cards"', "notice warn", "항목별 지출 비중", "항목별 계획 대비 실제"):
        assert w in src[pos:], f"{w} not found after previous item in month section"
        pos = src.index(w, pos)
        assert pos < fpos, f"{w} must be inside the month section (before dash-flow)"
    # every occurrence of these must be before dash-flow (not only the first one)
    for w in ('class="cards"', "notice warn", "항목별 지출 비중", "항목별 계획 대비 실제"):
        assert w not in src[fpos:], f"{w} appears after dash-flow"


def test_pending_notice_in_month_section():
    src = _dash()
    mpos, fpos = _sections(src)
    n = src.index("notice warn")
    assert mpos < n < fpos, (mpos, n, fpos)


def test_flow_section_content_order():
    src = _dash()
    _, fpos = _sections(src)
    pos = fpos
    for w in ("월별 수입·지출·저축 추이", "Segmented", "<h2>저축률</h2>", "연간 요약"):
        assert w in src[pos:], f"{w} not found after previous item in flow section"
        pos = src.index(w, pos)


def test_period_options_kept():
    src = _dash()
    assert '"최근 6개월"' in src
    assert '"최근 12개월"' in src


def test_month_band_plugin_defined():
    src = _dash()
    assert re.search(r"^const\s+monthBand\b", src, re.M), "top-level const monthBand missing"
    band = _month_band_def(src)
    assert re.search(r"id\s*:\s*[\"'`]monthBand[\"'`]", band), band[:200]
    assert "beforeDatasetsDraw" in band
    assert "rgba(36, 89, 214, 0.08)" in band


def test_month_band_guards_negative_index():
    band = _month_band_def(_dash())
    assert "index" in band
    assert re.search(r"index\s*(<|>=?)\s*0", band) or re.search(r"<\s*0", band), band[:300]


def test_chart_signatures_take_month():
    src = _dash()
    assert re.search(r"function\s+TrendChart\s*\(\s*\{\s*data\s*,\s*month\s*\}\s*\)", src)
    assert re.search(r"function\s+SavingsChart\s*\(\s*\{\s*data\s*,\s*month\s*\}\s*\)", src)


@pytest.mark.parametrize("name", ("TrendChart", "SavingsChart"))
def test_chart_body_selects_month_index(name):
    body = _fn_body(_dash(), name)
    assert "findIndex" in body, name
    assert re.search(r"\bd\s*\.\s*month\s*===\s*month\b", body), name
    assert "monthBand" in body, name
    assert re.search(r"monthBand\s*:\s*\{\s*index\s*:", body), name


def test_savings_chart_plugins_include_rate_labels_and_band():
    body = _savings()
    assert (re.search(r"plugins\s*:\s*\[[^\]]*rateLabels[^\]]*monthBand", body)
            or re.search(r"plugins\s*:\s*\[[^\]]*monthBand[^\]]*rateLabels", body)), body[-600:]


def test_trend_chart_plugins_include_band():
    assert re.search(r"plugins\s*:\s*\[[^\]]*monthBand", _trend())


def test_chart_call_sites_pass_month():
    src = _dash()
    for name in ("TrendChart", "SavingsChart"):
        pat = (r"<\$\{" + name + r"\}\s+data\s*=\s*\$\{\s*trend\.data\s*\}\s+month\s*=\s*\$\{\s*month\s*\}\s*/>")
        assert re.search(pat, src), name


def test_css_section_rules():
    css = CSS.read_text(encoding="utf-8")
    sec = _css_rule(css, ".dash-section")
    assert sec is not None, ".dash-section rule missing"
    assert "margin-bottom" in sec
    title = _css_rule(css, ".section-title")
    assert title is not None, ".section-title rule missing"
    assert "font-size" in title
    assert "var(--ink-2)" in title


def test_css_responsive_grid_kept():
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"@media\s*\(\s*max-width:\s*1100px\s*\)\s*\{(.*?)\}\s*\}", css, re.S)
    assert m, "@media (max-width: 1100px) missing"
    assert "grid.c2" in m.group(1)
    assert "minmax(0, 1fr)" in m.group(1) or "1fr" in m.group(1)


# ── loop 2026-10-24-004: leftover card, boxed sections without the "flow" heading ──

PREV = "2026-07"
LEFT_LABEL = '<div class="label">잔여액</div>'
LEFT_TITLE = "수입에서 실제 지출을 뺀 금액. 월말 정산하면 0원이 됩니다."
CARD_LABELS = ("수입", "저축 외 지출", "저축액", "잔여액")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def test_summary_has_leftover_keys_int(conn):
    _base_month(conn, PREV)
    _rec(conn, "income", "급여", 2_000_000)
    _rec(conn, "expense", "식비", 400_000)
    s = stats.month_summary(conn, M)
    assert "leftover" in s and "prev_leftover" in s
    assert _is_int(s["leftover"]), repr(s["leftover"])
    assert _is_int(s["prev_leftover"]), repr(s["prev_leftover"])
    assert s["leftover"] == s["income"] - s["expense"] == 1_600_000
    assert s["prev_leftover"] == s["prev_income"] - s["prev_expense"] == 200_000


def test_summary_leftover_before_settle(conn):
    _base_month(conn)
    s = stats.month_summary(conn, M)
    assert s["leftover"] == 200_000
    assert s["living_expense"] + s["savings"] + s["leftover"] == s["income"]


def test_summary_leftover_settled_to_savings(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    s = stats.month_summary(conn, M)
    assert s["leftover"] == 0
    assert s["living_expense"] + s["savings"] + s["leftover"] == s["income"]


def test_summary_leftover_settled_to_non_savings(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, "기타"))
    s = stats.month_summary(conn, M)
    assert s["leftover"] == 0
    assert s["living_expense"] + s["savings"] + s["leftover"] == s["income"]


def test_summary_leftover_negative_when_overspent(conn):
    _rec(conn, "income", "급여", 300_000)
    _rec(conn, "expense", "식비", 500_000)
    s = stats.month_summary(conn, M)
    assert s["leftover"] == -200_000


def test_summary_leftover_zero_income_expense_only(conn):
    _rec(conn, "expense", "식비", 300_000)
    _rec(conn, "expense", SAV, 200_000)
    s = stats.month_summary(conn, M)
    assert s["income"] == 0
    assert s["leftover"] == -500_000


def test_summary_empty_month_leftover_zero(conn):
    s = stats.month_summary(conn, M)
    assert s["leftover"] == 0
    assert s["prev_leftover"] == 0


def test_summary_prev_leftover_zero_without_prev_records(conn):
    _base_month(conn)
    s = stats.month_summary(conn, M)
    assert s["leftover"] == 200_000
    assert s["prev_leftover"] == 0


def test_summary_prev_leftover_across_year_boundary(conn):
    _rec(conn, "income", "급여", 900_000, "2025-12")
    _rec(conn, "expense", "식비", 650_000, "2025-12")
    _base_month(conn, "2026-01")
    s = stats.month_summary(conn, "2026-01")
    assert s["leftover"] == 200_000
    assert s["prev_leftover"] == 250_000


def test_summary_leftover_settled_then_changed(conn):
    _base_month(conn)
    budget.settle(conn, M, cat_id(conn, SAV))
    _rec(conn, "income", "급여", 100_000)
    s = stats.month_summary(conn, M)
    assert s["leftover"] == 100_000 == s["income"] - s["expense"]
    _rec(conn, "expense", "식비", 250_000)
    s = stats.month_summary(conn, M)
    assert s["leftover"] == -150_000 == s["income"] - s["expense"]


def test_summary_leftover_without_savings_categories(conn):
    categories.update_category(conn, cat_id(conn, SAV), {"is_savings": False})
    _base_month(conn)
    s = stats.month_summary(conn, M)
    assert s["savings"] == 0
    assert s["leftover"] == s["income"] - s["expense"] == 200_000


def test_summary_leftover_matches_trend_budget(conn):
    _base_month(conn, PREV)
    _rec(conn, "income", "급여", 1_500_000)
    _rec(conn, "expense", "식비", 900_000)
    s = stats.month_summary(conn, M)
    assert s["leftover"] == stats.trend(conn, M, M)[0]["leftover"]
    assert s["prev_leftover"] == stats.trend(conn, PREV, PREV)[0]["leftover"]


def test_summary_leftover_matches_trend_cash(conn):
    _rec(conn, "income", "급여", 1_000_000, PREV, txn_date="2026-08-05")
    _rec(conn, "expense", "식비", 120_000, PREV, txn_date="2026-07-10")
    _rec(conn, "income", "급여", 800_000, M, txn_date="2026-09-05")
    _rec(conn, "expense", SAV, 300_000, M, txn_date="2026-08-02")
    _rec(conn, "expense", "식비", 100_000, M, txn_date="2026-08-05", settle_date="2026-10-15")
    for month, prev in ((M, PREV), ("2026-09", M)):
        s = stats.month_summary(conn, month, basis="cash")
        assert s["leftover"] == stats.trend(conn, month, month, "cash")[0]["leftover"], month
        assert s["prev_leftover"] == stats.trend(conn, prev, prev, "cash")[0]["leftover"], month
        assert s["leftover"] == s["income"] - s["expense"], month


def test_summary_existing_keys_kept_with_leftover(conn):
    _base_month(conn, PREV)
    _base_month(conn)
    s = stats.month_summary(conn, M)
    for k in ("income", "expense", "plan", "savings", "savings_rate", "prev_income", "prev_expense", "prev_savings",
              "plan_diff", "remaining_budget", "over_count", "pending_income", "basis", "basis_label", "month",
              "living_expense", "prev_living_expense", "savings_category_count", "leftover", "prev_leftover"):
        assert k in s, k


def test_api_summary_leftover(client):
    _api_records(client, [("income", "급여", 1_000_000, {}), ("expense", "식비", 300_000, {}),
                          ("expense", SAV, 500_000, {})])
    r = client.get("/api/stats/summary", params={"month": M})
    assert r.status_code == 200, r.text
    s = r.json()
    assert "leftover" in s and "prev_leftover" in s
    assert s["leftover"] == 200_000 == s["income"] - s["expense"]
    assert s["prev_leftover"] == 0


def test_api_summary_leftover_negative(client):
    _api_records(client, [("income", "급여", 300_000, {}), ("expense", "식비", 500_000, {})])
    s = client.get("/api/stats/summary", params={"month": M}).json()
    assert s["leftover"] == -200_000


# static: dashboard.js

def test_leftover_card_label_once_and_placed():
    src = _dash()
    assert src.count(LEFT_LABEL) == 1, src.count(LEFT_LABEL)
    _, fpos = _sections(src)
    lpos = src.index(LEFT_LABEL)
    assert 'class="cards"' in src
    assert src.index('class="cards"') < lpos
    assert src.index('<div class="label">저축액</div>') < lpos < fpos


def test_card_label_order():
    src = _dash()
    poss = []
    for w in CARD_LABELS:
        tag = f'<div class="label">{w}</div>'
        assert tag in src, tag
        poss.append(src.index(tag))
    assert poss == sorted(poss), dict(zip(CARD_LABELS, poss))


def _leftover_card(src):
    i = src.index(LEFT_LABEL)
    return src[max(0, i - 300): i + 400]


@pytest.mark.parametrize("w", ("card clickable", "goCash()", "won(s.leftover)", "s.prev_leftover",
                               '"warn"', '"neg"', LEFT_TITLE))
def test_leftover_card_fragment(w):
    src = _dash()
    assert LEFT_LABEL in src, "잔여액 card missing"
    assert w in _leftover_card(src), w


def test_leftover_value_class_expression():
    pat = r's\.leftover\s*>\s*0\s*\?\s*"warn"\s*:\s*s\.leftover\s*<\s*0\s*\?\s*"neg"'
    assert re.search(pat, _dash())


@pytest.mark.parametrize("name", ("TrendChart", "SavingsChart"))
def test_leftover_not_in_charts(name):
    assert "leftover" not in _fn_body(_dash(), name), name


def test_leftover_only_before_flow_section():
    src = _dash()
    _, fpos = _sections(src)
    hits = [m.start() for m in re.finditer("leftover", src)]
    assert len(hits) >= 2, hits
    assert all(h < fpos for h in hits), (hits, fpos)


def test_sections_boxed_single_title_no_flow_word():
    src = _dash()
    mpos, fpos = _sections(src)
    assert mpos < fpos
    assert src.count('class="section-title"') == 1
    assert '<h2 class="section-title">${monthLabel(month)}</h2>' in src
    assert "흐름" not in src


# static: app.css

def test_css_dash_section_boxed():
    sec = _css_rule(CSS.read_text(encoding="utf-8"), ".dash-section")
    assert sec is not None, ".dash-section rule missing"
    for w in ("margin-bottom", "background", "border", "var(--line-2)"):
        assert w in sec, w


def test_css_dash_month_accent():
    rule = _css_rule(CSS.read_text(encoding="utf-8"), ".dash-month")
    assert rule is not None, ".dash-month rule missing"
    assert "var(--accent-soft)" in rule


def test_css_section_title_size_and_color():
    rule = _css_rule(CSS.read_text(encoding="utf-8"), ".section-title")
    assert rule is not None, ".section-title rule missing"
    assert re.search(r"font-size\s*:\s*15px", rule), rule
    assert "var(--ink-2)" in rule


def test_css_card_value_warn():
    rule = _css_rule(CSS.read_text(encoding="utf-8"), ".card .value.warn")
    assert rule is not None, ".card .value.warn rule missing"
    assert "var(--warn)" in rule
