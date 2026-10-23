"""Dashboard section order (loop 2026-10-24-005): drag handle, `dashboard_order` app setting, no section tint."""
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.services import backup
from app.services import settings as app_settings

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
DASH = JS / "pages" / "dashboard.js"
CSS = ROOT / "app" / "static" / "css" / "app.css"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node 없음")

SEC_MONTH = '<section class="dash-section dash-month">'
SEC_FLOW = '<section class="dash-section dash-flow">'
DEFAULT_ORDER = ["month", "flow"]
BAD_VALUES = ["flow", "month", "month,month", "flow, month", "month,flow,x", "x,y", "FLOW,MONTH"]


def _dash():
    return DASH.read_text(encoding="utf-8")


def _css():
    return CSS.read_text(encoding="utf-8")


def _fn_body(src, name):
    """Slice `function <name>` up to the next `function ` definition. Fails (never skips) when missing."""
    m = re.search(r"function\s+" + re.escape(name) + r"\b", src)
    assert m, f"function {name} not found in dashboard.js"
    nxt = re.search(r"\bfunction\s+[A-Za-z_$]", src[m.end():])
    return src[m.start(): m.end() + nxt.start()] if nxt else src[m.start():]


def _css_rule(css, selector):
    """Return the declaration block of the first rule whose selector list contains `selector` exactly."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sels = [x.strip() for x in m.group(1).split(",")]
        if selector in sels:
            return m.group(2)
    return None


def _sections(src):
    assert src.count(SEC_MONTH) == 1, src.count(SEC_MONTH)
    assert src.count(SEC_FLOW) == 1, src.count(SEC_FLOW)
    return src.index(SEC_MONTH), src.index(SEC_FLOW)


def put_raw_setting(path, key, value):
    c = sqlite3.connect(str(path))
    try:
        c.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))
        c.commit()
    finally:
        c.close()


def raw_setting(path, key):
    c = sqlite3.connect(str(path))
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else None
    finally:
        c.close()


# ── server: settings module ──

def test_dashboard_sections_constant():
    assert app_settings.DASHBOARD_SECTIONS == ("month", "flow")


def test_allowed_dashboard_order_tuple():
    v = app_settings.ALLOWED["dashboard_order"]
    assert isinstance(v, tuple), type(v)
    assert v == ("month,flow", "flow,month")


def test_defaults_unchanged_without_dashboard_order():
    assert "dashboard_order" not in app_settings.DEFAULTS
    assert app_settings.DEFAULTS == {"date_format": "ko", "currency_display": "won"}


def test_get_display_keys_unchanged(conn):
    app_settings.set_many(conn, {"dashboard_order": "flow,month"})
    d = app_settings.get_display(conn)
    assert set(d) == {"date_format", "currency_display"}, d


# ── server: API ──

def test_api_new_db_dashboard_order_null(client):
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    s = r.json()
    assert "dashboard_order" in s
    assert s["dashboard_order"] is None


@pytest.mark.parametrize("value", ["flow,month", "month,flow"])
def test_api_put_dashboard_order_saved(client, value):
    r = client.put("/api/settings", json={"dashboard_order": value})
    assert r.status_code == 200, r.text
    assert client.get("/api/settings").json()["dashboard_order"] == value


def test_api_put_dashboard_order_overwrite(client):
    assert client.put("/api/settings", json={"dashboard_order": "flow,month"}).status_code == 200
    assert client.put("/api/settings", json={"dashboard_order": "month,flow"}).status_code == 200
    assert client.get("/api/settings").json()["dashboard_order"] == "month,flow"


@pytest.mark.parametrize("value", BAD_VALUES)
def test_api_put_dashboard_order_invalid_rejected(client, value):
    assert client.put("/api/settings", json={"dashboard_order": "flow,month"}).status_code == 200
    r = client.put("/api/settings", json={"dashboard_order": value})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "settings.invalid_value"
    assert client.get("/api/settings").json()["dashboard_order"] == "flow,month"


@pytest.mark.parametrize("value", BAD_VALUES)
def test_api_put_dashboard_order_invalid_on_new_db_stays_null(client, tmp_path, value):
    r = client.put("/api/settings", json={"dashboard_order": value})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "settings.invalid_value"
    assert client.get("/api/settings").json()["dashboard_order"] is None
    assert raw_setting(tmp_path / "api.db", "dashboard_order") is None


def test_api_put_empty_deletes(client, tmp_path):
    assert client.put("/api/settings", json={"dashboard_order": "flow,month"}).status_code == 200
    r = client.put("/api/settings", json={"dashboard_order": ""})
    assert r.status_code == 200, r.text
    assert raw_setting(tmp_path / "api.db", "dashboard_order") is None
    assert client.get("/api/settings").json()["dashboard_order"] is None


@pytest.mark.parametrize("value", BAD_VALUES + ["", "   ", "garbage"])
def test_api_raw_invalid_row_reads_null(client, tmp_path, value):
    p = tmp_path / "api.db"
    put_raw_setting(p, "dashboard_order", value)
    put_raw_setting(p, "date_format", "xx")
    put_raw_setting(p, "currency_display", "usd")
    put_raw_setting(p, "ecos_api_key", "ABCDEFGH12345")
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["dashboard_order"] is None, s
    assert (s["date_format"], s["currency_display"]) == ("ko", "won")
    assert s["ecos_api_key_set"] is True
    assert s["ecos_api_key"] != "ABCDEFGH12345" and "ABCDEFGH12345" not in json.dumps(s)


def test_get_public_raw_invalid_row_null(conn):
    conn.execute("INSERT INTO settings (key, value) VALUES ('dashboard_order','x,y') "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    conn.commit()
    assert app_settings.get_public(conn)["dashboard_order"] is None


def test_get_public_valid_row(conn):
    app_settings.set_many(conn, {"dashboard_order": "flow,month"})
    assert app_settings.get_public(conn)["dashboard_order"] == "flow,month"


def test_api_put_together_with_date_format(client):
    r = client.put("/api/settings", json={"dashboard_order": "flow,month", "date_format": "dot"})
    assert r.status_code == 200, r.text
    s = client.get("/api/settings").json()
    assert (s["dashboard_order"], s["date_format"]) == ("flow,month", "dot")


# ── server: reset ──

def test_reset_records_keeps_dashboard_order(conn):
    app_settings.set_many(conn, {"dashboard_order": "flow,month"})
    backup.reset(conn, "records")
    assert app_settings.get_public(conn)["dashboard_order"] == "flow,month"


def test_reset_all_clears_dashboard_order_keeps_display(conn):
    app_settings.set_many(conn, {"dashboard_order": "flow,month", "date_format": "dot"})
    backup.reset(conn, "all")
    s = app_settings.get_public(conn)
    assert s["dashboard_order"] is None
    assert s["date_format"] == "dot"


def test_api_reset_all_clears_dashboard_order(client):
    assert client.put("/api/settings", json={"dashboard_order": "flow,month", "date_format": "dot"}).status_code == 200
    r = client.post("/api/reset", json={"mode": "all"})
    assert r.status_code == 200, r.text
    s = client.get("/api/settings").json()
    assert s["dashboard_order"] is None
    assert s["date_format"] == "dot"


def test_api_reset_records_keeps_dashboard_order(client):
    assert client.put("/api/settings", json={"dashboard_order": "flow,month"}).status_code == 200
    r = client.post("/api/reset", json={"mode": "records"})
    assert r.status_code == 200, r.text
    assert client.get("/api/settings").json()["dashboard_order"] == "flow,month"


# ── frontend: pure functions run in node ──

PREACT_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']/vendor/preact-htm\.module\.js[\"']")

PARSE_OK = [("flow,month", ["flow", "month"]), ("month,flow", ["month", "flow"])]
PARSE_BAD = [None, "__undefined__", "", "flow", "month,month", "flow, month", "x,y", "month,flow,x"]

MOVE_CASES = [
    (["month", "flow"], "flow", "month", "before", ["flow", "month"]),
    (["month", "flow"], "month", "flow", "after", ["flow", "month"]),
    (["flow", "month"], "month", "flow", "before", ["month", "flow"]),
    (["month", "flow"], "month", "flow", "before", ["month", "flow"]),
    # invalid -> copy of order
    (["month", "flow"], "month", "month", "before", ["month", "flow"]),
    (["flow", "month"], "month", "month", "after", ["flow", "month"]),
    (["month", "flow"], "x", "flow", "before", ["month", "flow"]),
    (["month", "flow"], "month", "x", "after", ["month", "flow"]),
    (["flow", "month"], "x", "month", "before", ["flow", "month"]),
    (["month", "flow"], "flow", "month", "middle", ["month", "flow"]),
    (["flow", "month"], "flow", "month", "middle", ["flow", "month"]),
]

RUNNER = r"""
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
const noop = () => {};
const el = () => ({ style: {}, setAttribute: noop, appendChild: noop, addEventListener: noop, click: noop, remove: noop });
globalThis.window = { addEventListener: noop, removeEventListener: noop, dispatchEvent: noop,
  location: { hash: "", href: "" }, localStorage: { getItem: () => null, setItem: noop } };
globalThis.document = { title: "", documentElement: { style: {} }, body: el(), createElement: el,
  getElementById: () => null, querySelector: () => null, addEventListener: noop };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
const m = await import(pathToFileURL(process.argv[2]).href);
const { parse, moves } = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const run = (f) => { try { return { v: f() }; } catch (e) { return { err: String(e) }; } };
const before = JSON.stringify(m.DASH_SECTIONS);
const out = {
  sections: run(() => m.DASH_SECTIONS),
  parse: parse.map((x) => run(() => {
    const arg = x === "__undefined__" ? undefined : x;
    const r = m.parseDashOrder(arg);
    const copy = Array.isArray(r) ? r.slice() : r;
    const alias = r === m.DASH_SECTIONS;
    if (Array.isArray(r)) { r.push("zz"); r[0] = "mutated"; }
    const constAfter = JSON.stringify(m.DASH_SECTIONS);
    return { result: copy, alias, constIntact: constAfter === before };
  })),
  moves: moves.map(([o, from, to, pos]) => run(() => {
    const input = o.slice();
    const r = m.moveSection(input, from, to, pos);
    return { result: Array.isArray(r) ? r.slice() : r, same: r === input, inputAfter: input };
  })),
};
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def dash_results(tmp_path_factory):
    if NODE is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("dashjs")
    src = (JS / "lib.js").read_text(encoding="utf-8")
    m = PREACT_IMPORT.search(src)
    if m:
        names = [x.strip().split(" as ")[0].strip() for x in m.group(1).split(",") if x.strip()]
        (d / "preact-stub.mjs").write_text(
            "".join(f"export const {nm} = (...a) => ({{}});\n" for nm in names), encoding="utf-8")
        src = src[:m.start()] + src[m.start():m.end()].replace("/vendor/preact-htm.module.js", "./preact-stub.mjs") \
            + src[m.end():]
    (d / "lib.mjs").write_text(src, encoding="utf-8")
    dash = _dash()
    assert 'from "../lib.js"' in dash, "dashboard.js must import from \"../lib.js\""
    (d / "dashboard.mjs").write_text(dash.replace('from "../lib.js"', 'from "./lib.mjs"'), encoding="utf-8")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")
    (d / "cases.json").write_text(json.dumps({
        "parse": [x for x, _ in PARSE_OK] + PARSE_BAD,
        "moves": [list(c[:4]) for c in MOVE_CASES],
    }), encoding="utf-8")
    r = subprocess.run([NODE, str(d / "run.mjs"), str(d / "dashboard.mjs"), str(d / "cases.json")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"dashboard.js 를 node 로 불러오지 못함: {r.stderr.strip()[-400:]}"
    return json.loads(r.stdout)


@needs_node
def test_js_dash_sections(dash_results):
    res = dash_results["sections"]
    assert "err" not in res, res
    assert res["v"] == DEFAULT_ORDER


@needs_node
@pytest.mark.parametrize("idx", range(len(PARSE_OK)), ids=[x for x, _ in PARSE_OK])
def test_js_parse_dash_order_valid(dash_results, idx):
    res = dash_results["parse"][idx]
    assert "err" not in res, res
    assert res["v"]["result"] == PARSE_OK[idx][1], res


@needs_node
@pytest.mark.parametrize("idx", range(len(PARSE_BAD)), ids=[repr(x) for x in PARSE_BAD])
def test_js_parse_dash_order_invalid_default_copy(dash_results, idx):
    res = dash_results["parse"][len(PARSE_OK) + idx]
    assert "err" not in res, res
    v = res["v"]
    assert v["result"] == DEFAULT_ORDER, (PARSE_BAD[idx], v)
    assert v["alias"] is False, "parseDashOrder returned DASH_SECTIONS itself"
    assert v["constIntact"] is True, "mutating the return value changed DASH_SECTIONS"


@needs_node
@pytest.mark.parametrize("idx", range(len(MOVE_CASES)),
                         ids=[f"{c[0]}-{c[1]}-{c[2]}-{c[3]}" for c in MOVE_CASES])
def test_js_move_section(dash_results, idx):
    o, frm, to, pos, expected = MOVE_CASES[idx]
    res = dash_results["moves"][idx]
    assert "err" not in res, res
    v = res["v"]
    assert v["result"] == expected, (o, frm, to, pos, v)
    assert v["same"] is False, "moveSection must return a new array"
    assert v["inputAfter"] == o, "moveSection mutated its input"


# ── frontend: static checks on dashboard.js ──

def test_section_bars_placement():
    src = _dash()
    mpos, fpos = _sections(src)
    assert mpos < fpos
    bar = 'class="section-bar"'
    assert src.count(bar) == 2, src.count(bar)
    first = src.index(bar)
    second = src.index(bar, first + 1)
    assert mpos < first < fpos, (mpos, first, fpos)
    assert second > fpos, (second, fpos)


def test_handles_in_sections():
    src = _dash()
    mpos, fpos = _sections(src)
    hm, hf = '${handle("month")}', '${handle("flow")}'
    assert src.count(hm) == 1, src.count(hm)
    assert src.count(hf) == 1, src.count(hf)
    assert mpos < src.index(hm) < fpos
    assert src.index(hf) > fpos


def test_handle_span_markup_and_events():
    src = _dash()
    for w in ('class="handle"', 'draggable="true"', 'title="끌어서 순서 변경"', "⠿",
              "onDragStart", "onDragEnd"):
        assert w in src, w
    # drop handling moved to lib.js startDragDrop (loop 2026-10-24-007)
    assert "onDragOver=" not in src
    assert "onDrop=" not in src


def test_month_section_bar_literal():
    src = _dash()
    lit = '<div class="section-bar">${handle("month")}<h2 class="section-title">${monthLabel(month)}</h2></div>'
    assert lit in src
    assert src.count("${monthLabel(month)}") == 1, src.count("${monthLabel(month)}")
    assert src.count('class="section-title"') == 2  # month + flow ("기간별 통계", loop 2026-10-24-006)
    assert "흐름" not in src


def test_slot_wrapper_and_drop_classes():
    src = _dash()
    for w in ("dash-slot", "key=${", "drop-", "dragging"):
        assert w in src, w


def test_dashboard_page_saves_order():
    body = _fn_body(_dash(), "DashboardPage")
    for w in ("dashboard_order", "reloadSettings", "useApp", "parseDashOrder(", "moveSection(", "toastErr"):
        assert w in body, w
    assert re.search(r"api\(\s*[\"']/settings[\"']\s*,\s*\{[^}]*method\s*:\s*[\"']PUT[\"']", body), \
        'api("/settings", { method: "PUT", ... }) not found in DashboardPage'


def test_dashboard_imports_only_lib():
    src = _dash()
    specs = re.findall(r"\bfrom\s*[\"']([^\"']+)[\"']", src)
    assert specs == ["../lib.js"], specs
    assert not re.search(r"\bimport\s*\(", src), "dynamic import found"
    m = re.search(r"import\s*\{([^}]*)\}\s*from\s*[\"']\.\./lib\.js[\"']", src)
    assert m
    names = {x.strip().split(" as ")[0].strip() for x in m.group(1).split(",") if x.strip()}
    for nm in ("useApp", "api", "toastErr"):
        assert nm in names, nm


# ── frontend: static checks on app.css ──

def test_css_dash_section_no_tint():
    rule = _css_rule(_css(), ".dash-section")
    assert rule is not None, ".dash-section rule missing"
    assert "border" in rule and "margin-bottom" in rule, rule
    assert "var(--line-2)" not in rule and "var(--accent-soft)" not in rule, rule
    for m in re.finditer(r"background(?:-color)?\s*:\s*([^;]+)", rule):
        assert m.group(1).strip() in ("transparent", "none"), m.group(0)


def test_css_no_dash_month_selector():
    assert not re.search(r"\.dash-month(?![\w-])", _css()), ".dash-month selector still present"


def test_css_section_bar_rules():
    css = _css()
    bar = _css_rule(css, ".section-bar")
    assert bar is not None, ".section-bar rule missing"
    assert re.search(r"display\s*:\s*flex\b", bar), bar
    title = _css_rule(css, ".section-bar .section-title")
    assert title is not None, ".section-bar .section-title rule missing"
    assert re.search(r"margin\s*:\s*0\s*(;|$)", title.strip() + ";"), title


def test_css_section_handle_visible():
    rule = _css_rule(_css(), ".dash-section .handle")
    assert rule is not None, ".dash-section .handle rule missing"
    assert re.search(r"visibility\s*:\s*visible", rule), rule


@pytest.mark.parametrize("selector,needle", [
    (".dash-slot.drop-before > .dash-section", "var(--accent)"),
    (".dash-slot.drop-after > .dash-section", "var(--accent)"),
    (".dash-slot.dragging > .dash-section", "opacity"),
])
def test_css_slot_drag_rules(selector, needle):
    rule = _css_rule(_css(), selector)
    assert rule is not None, f"{selector} rule missing"
    assert needle in rule, rule


def test_css_global_handle_and_title_unchanged():
    css = _css()
    h = _css_rule(css, ".handle")
    assert h is not None, ".handle rule missing"
    assert re.search(r"visibility\s*:\s*hidden", h), h
    t = _css_rule(css, ".section-title")
    assert t is not None, ".section-title rule missing"
    assert re.search(r"font-size\s*:\s*15px", t), t
    assert "var(--ink-2)" in t
