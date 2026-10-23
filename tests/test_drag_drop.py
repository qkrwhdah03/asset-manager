"""Drop position from pointer height: shared `dropTarget` / `startDragDrop` / `stopDragDrop` in lib.js (loop 2026-10-24-007)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
LIB = JS / "lib.js"
DASH = JS / "pages" / "dashboard.js"
SETTINGS = JS / "pages" / "settings.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node 없음")

PREACT_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']/vendor/preact-htm\.module\.js[\"']")

KEYS = ["a", "b", "c", "d"]
RECTS = [{"top": 0, "bottom": 100}, {"top": 100, "bottom": 200}, {"top": 200, "bottom": 300}, {"top": 300, "bottom": 400}]
DKEYS = ["month", "flow"]
DRECTS = [{"top": 60, "bottom": 900}, {"top": 918, "bottom": 1800}]


def B(k):
    return {"key": k, "pos": "before"}


def A(k):
    return {"key": k, "pos": "after"}


# (id, [y, keys, rects, drag], expected). Strings "NaN" / "null" / "undefined" / "MISSING" are converted
# by the runner (deeply); "MISSING" as an object value removes that property; "STR:x" is the JS string "x".
DROP_CASES = [
    # 1. drag = "b"
    ("b_above_first", [-50, KEYS, RECTS, "b"], B("a")),
    ("b_49", [49, KEYS, RECTS, "b"], B("a")),
    ("b_50_center", [50, KEYS, RECTS, "b"], None),
    ("b_149", [149, KEYS, RECTS, "b"], None),
    ("b_150_center", [150, KEYS, RECTS, "b"], None),
    ("b_249", [249, KEYS, RECTS, "b"], None),
    ("b_250_center", [250, KEYS, RECTS, "b"], B("d")),
    ("b_349", [349, KEYS, RECTS, "b"], B("d")),
    ("b_350_center", [350, KEYS, RECTS, "b"], A("d")),
    ("b_below_last", [1000, KEYS, RECTS, "b"], A("d")),
    # 2. drag = "a"
    ("a_-50", [-50, KEYS, RECTS, "a"], None),
    ("a_60", [60, KEYS, RECTS, "a"], None),
    ("a_150", [150, KEYS, RECTS, "a"], B("c")),
    ("a_999", [999, KEYS, RECTS, "a"], A("d")),
    # 3. drag = "d"
    ("d_999", [999, KEYS, RECTS, "d"], None),
    ("d_350", [350, KEYS, RECTS, "d"], None),
    ("d_250", [250, KEYS, RECTS, "d"], None),
    ("d_249", [249, KEYS, RECTS, "d"], B("c")),
    ("d_-10", [-10, KEYS, RECTS, "d"], B("a")),
    # 4. dashboard shape
    ("dash_flow_10", [10, DKEYS, DRECTS, "flow"], B("month")),
    ("dash_flow_479", [479, DKEYS, DRECTS, "flow"], B("month")),
    ("dash_flow_480", [480, DKEYS, DRECTS, "flow"], None),
    ("dash_flow_2000", [2000, DKEYS, DRECTS, "flow"], None),
    ("dash_month_10", [10, DKEYS, DRECTS, "month"], None),
    ("dash_month_1358", [1358, DKEYS, DRECTS, "month"], None),
    ("dash_month_1359", [1359, DKEYS, DRECTS, "month"], A("flow")),
    # 5. numeric keys, strict comparison
    ("num_keys", [-1, [3, 1, 2], RECTS[:3], 2], {"key": 3, "pos": "before"}),
    ("num_keys_string_drag", [-1, [3, 1, 2], RECTS[:3], "STR:2"], None),
    # 6. invalid input -> null, never throws
    ("y_nan", ["NaN", KEYS, RECTS, "b"], None),
    ("y_null", ["null", KEYS, RECTS, "b"], None),
    ("y_undefined", ["undefined", KEYS, RECTS, "b"], None),
    ("y_string", ["STR:10", KEYS, RECTS, "b"], None),
    ("len_mismatch", [10, KEYS, RECTS[:3], "b"], None),
    ("both_empty", [10, [], [], "b"], None),
    ("keys_not_array", [10, "abcd", RECTS, "b"], None),
    ("keys_null", [10, "null", RECTS, "b"], None),
    ("drag_not_in_keys", [10, KEYS, RECTS, "z"], None),
    ("rect_top_nan", [10, KEYS, [RECTS[0], {"top": "NaN", "bottom": 200}, RECTS[2], RECTS[3]], "b"], None),
    ("rect_bottom_missing", [10, KEYS, [RECTS[0], RECTS[1], {"top": 200, "bottom": "MISSING"}, RECTS[3]], "b"], None),
]

RUNNER = r"""
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
const noop = () => {};
const el = () => ({ style: {}, setAttribute: noop, appendChild: noop, addEventListener: noop, click: noop, remove: noop });

// ── recording stubs ──
let seq = 0;
const rec = { add: [], remove: [], deContains: 0 };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = noop;
globalThis.window = { addEventListener: noop, removeEventListener: noop, dispatchEvent: noop, innerHeight: 500,
  location: { hash: "", href: "" }, localStorage: { getItem: () => null, setItem: noop } };
const documentElement = { style: {}, contains: (t) => { rec.deContains++; return !!(t && t.inside); } };
globalThis.document = { title: "", documentElement, body: el(), createElement: el, scrollingElement: null,
  getElementById: () => null, querySelector: () => null,
  addEventListener: (type, fn, cap) => rec.add.push([type, fn, cap, ++seq]),
  removeEventListener: (type, fn, cap) => rec.remove.push([type, fn, cap, ++seq]) };
globalThis.getComputedStyle = (node) => ({ overflowY: "visible", getPropertyValue: () => "" });

const lib = await import(pathToFileURL(process.argv[2]).href);
const { drop } = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const out = {};
out.import = { add: rec.add.length };

const conv = (a) => {
  if (a === "NaN") return NaN;
  if (a === "null") return null;
  if (a === "undefined") return undefined;
  if (typeof a === "string" && a.startsWith("STR:")) return a.slice(4);
  if (Array.isArray(a)) return a.map(conv);
  if (a && typeof a === "object") {
    const o = {};
    for (const [k, v] of Object.entries(a)) if (v !== "MISSING") o[k] = conv(v);
    return o;
  }
  return a;
};
const run = (f) => { try { const v = f(); return { v: v === undefined ? "__undefined__" : v }; } catch (e) { return { err: String(e) }; } };
out.drop = drop.map((args) => run(() => lib.dropTarget(...args.map(conv))));

// ── session helpers ──
const L_RECTS = [{ top: 0, bottom: 100 }, { top: 100, bottom: 200 }, { top: 200, bottom: 300 }, { top: 300, bottom: 400 }];
const L_KEYS = ["a", "b", "c", "d"];
const IN = { inside: true }, OUT = { inside: false };
const area = { contains: (t) => !!(t && t.inside) };
const reset = () => { rec.add.length = 0; rec.remove.length = 0; rec.deContains = 0; };
const mkSession = (withArea = true) => {
  const s = { hints: [], drops: [], itemsCalls: 0, rectCalls: 0 };
  const els = L_RECTS.map((r) => ({ getBoundingClientRect: () => { s.rectCalls++; return { ...r, left: 0, right: 800, height: r.bottom - r.top }; } }));
  s.opts = {
    drag: "b", keys: L_KEYS,
    items: () => { s.itemsCalls++; return els; },
    onHint: (h) => { s.hints.push([h, ++seq]); },
    onDrop: (t) => { s.drops.push([t, ++seq]); },
  };
  if (withArea) s.opts.area = area;
  return s;
};
const ev = (target, clientY) => {
  const e = { target, clientY, prevented: 0, dataTransfer: { dropEffect: "none" } };
  e.preventDefault = () => { e.prevented++; };
  return e;
};
const L = (type) => { const a = rec.add.filter((x) => x[0] === type); return a.length ? a[a.length - 1][1] : null; };
const types = ["dragover", "drop"];
const removedSame = (added) => types.every((t) => {
  const a = added.find((x) => x[0] === t);
  return !!a && rec.remove.some((x) => x[0] === t && x[1] === a[1] && x[2] === true);
});
const hintVals = (s) => s.hints.map((h) => h[0] === undefined ? "__undefined__" : h[0]);

// 14 (before any start)
out.stopBeforeStart = run(() => { lib.stopDragDrop(); lib.stopDragDrop(); return { removes: rec.remove.length }; });

// 7 – 10
out.s7 = run(() => {
  reset(); const s = mkSession();
  lib.startDragDrop(s.opts);
  const r = {};
  r.addTypes = rec.add.map((x) => x[0]).sort();
  r.addCapture = rec.add.map((x) => x[2]);
  r.addFns = rec.add.every((x) => typeof x[1] === "function");
  r.hints = s.hints.length; r.drops = s.drops.length; r.itemsCalls = s.itemsCalls;

  const over = L("dragover");
  // 8
  let e = ev(IN, 10); over(e);
  r.e8 = { prevented: e.prevented > 0, dropEffect: e.dataTransfer.dropEffect, hints: hintVals(s), items: s.itemsCalls };
  e = ev(IN, 10); over(e);
  r.e8b = { prevented: e.prevented > 0, hints: hintVals(s), items: s.itemsCalls };
  // 9
  e = ev(IN, 150); over(e);
  r.e9 = { prevented: e.prevented > 0, hints: hintVals(s) };
  e = ev(IN, 300); over(e);
  r.e9b = { prevented: e.prevented > 0, hints: hintVals(s) };
  // 10
  e = ev(OUT, 10); over(e);
  r.e10 = { prevented: e.prevented > 0, hints: hintVals(s) };
  e = ev(OUT, 10); over(e);
  r.e10b = { prevented: e.prevented > 0, hints: hintVals(s) };
  r.drops10 = s.drops.length;
  lib.stopDragDrop();
  return r;
});

// 11
out.s11 = run(() => {
  reset(); const s = mkSession();
  lib.startDragDrop(s.opts);
  const added = rec.add.slice();
  const e = ev(IN, 10); L("drop")(e);
  const r = {};
  r.prevented = e.prevented > 0;
  r.removedSame = removedSame(added);
  r.drops = s.drops.map((d) => d[0]);
  const rmSeqs = rec.remove.map((x) => x[3]);
  r.removeBeforeDrop = s.drops.length === 1 && rmSeqs.length >= 2 && Math.max(...rmSeqs) < s.drops[0][1];
  lib.stopDragDrop();
  return r;
});

// 12
out.s12 = run(() => {
  reset(); const s = mkSession();
  lib.startDragDrop(s.opts);
  const added = rec.add.slice();
  const e = ev(IN, 150); L("drop")(e);
  const r = { prevented: e.prevented > 0, removedSame: removedSame(added), drops: s.drops.length };
  lib.stopDragDrop();
  return r;
});

// 13
out.s13 = run(() => {
  reset(); const s = mkSession();
  lib.startDragDrop(s.opts);
  const added = rec.add.slice();
  const e = ev(OUT, 10); added.find((x) => x[0] === "drop")[1](e);
  const r = { prevented: e.prevented > 0, removes: rec.remove.length, drops: s.drops.length };
  // session still alive: dragover still produces hints
  const e2 = ev(IN, 10); added.find((x) => x[0] === "dragover")[1](e2);
  r.alive = { prevented: e2.prevented > 0, hints: hintVals(s) };
  lib.stopDragDrop();
  return r;
});

// 14
out.s14 = run(() => {
  reset(); const s = mkSession();
  lib.startDragDrop(s.opts);
  const added = rec.add.slice();
  L("dragover")(ev(IN, 10));
  const hintsBefore = s.hints.length;
  lib.stopDragDrop();
  const r = { removedSame: removedSame(added), hintsAdded: s.hints.length - hintsBefore, drops: s.drops.length };
  lib.stopDragDrop();
  r.noThrow = true;
  return r;
});

// 15
out.s15 = run(() => {
  reset(); const s = mkSession();
  lib.startDragDrop(s.opts);
  const first = rec.add.slice();
  lib.startDragDrop(s.opts);
  const r = { firstRemoved: removedSame(first) };
  const active = rec.add.filter((a) => !rec.remove.some((x) => x[0] === a[0] && x[1] === a[1] && x[2] === a[2]));
  r.activeTypes = active.map((x) => x[0]).sort();
  lib.stopDragDrop();
  const stillActive = rec.add.filter((a) => !rec.remove.some((x) => x[0] === a[0] && x[1] === a[1] && x[2] === a[2]));
  r.afterStop = stillActive.length;
  return r;
});

// 16
out.s16 = run(() => {
  reset(); const s = mkSession(false);
  lib.startDragDrop(s.opts);
  const e = ev(IN, 10); L("dragover")(e);
  const r = { deContains: rec.deContains, prevented: e.prevented > 0, hints: hintVals(s) };
  lib.stopDragDrop();
  return r;
});

process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def res(tmp_path_factory):
    if NODE is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("dragdrop")
    src = LIB.read_text(encoding="utf-8")
    m = PREACT_IMPORT.search(src)
    if m:
        names = [x.strip().split(" as ")[0].strip() for x in m.group(1).split(",") if x.strip()]
        (d / "preact-stub.mjs").write_text(
            "".join(f"export const {nm} = (...a) => ({{}});\n" for nm in names), encoding="utf-8")
        src = src[:m.start()] + src[m.start():m.end()].replace("/vendor/preact-htm.module.js", "./preact-stub.mjs") \
            + src[m.end():]
    (d / "lib.mjs").write_text(src, encoding="utf-8")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")
    (d / "cases.json").write_text(json.dumps({"drop": [c[1] for c in DROP_CASES]}), encoding="utf-8")
    r = subprocess.run([NODE, str(d / "run.mjs"), str(d / "lib.mjs"), str(d / "cases.json")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"lib.js 를 node 로 불러오지 못함: {r.stderr.strip()[-600:]}"
    return json.loads(r.stdout)


def _ok(res, key):
    v = res[key]
    assert "err" not in v, (key, v)
    return v["v"]


# ── dropTarget (1-6) ──

@needs_node
@pytest.mark.parametrize("idx", range(len(DROP_CASES)), ids=[c[0] for c in DROP_CASES])
def test_drop_target(res, idx):
    name, args, expected = DROP_CASES[idx]
    r = res["drop"][idx]
    assert "err" not in r, (name, r)
    assert r["v"] == expected, (name, args, r["v"])


def test_lib_exports_static():
    src = LIB.read_text(encoding="utf-8")
    for name in ("dropTarget", "startDragDrop", "stopDragDrop"):
        assert re.search(rf"export\s+function\s+{name}\b", src), name


# ── startDragDrop / stopDragDrop (7-17) ──

@needs_node
def test_import_has_no_listener_side_effects(res):
    assert res["import"] == {"add": 0}, res["import"]


@needs_node
def test_start_registers_capture_listeners_only(res):
    v = _ok(res, "s7")
    assert v["addTypes"] == ["dragover", "drop"], v["addTypes"]
    assert v["addCapture"] == [True, True], v["addCapture"]
    assert v["addFns"] is True
    assert (v["hints"], v["drops"], v["itemsCalls"]) == (0, 0, 0), v


@needs_node
def test_dragover_inside_prevents_and_hints(res):
    v = _ok(res, "s7")
    e = v["e8"]
    assert e["prevented"] is True, e
    assert e["dropEffect"] == "move", e
    assert e["hints"] == [{"key": "a", "pos": "before"}], e
    assert e["items"] >= 1, e


@needs_node
def test_dragover_same_target_no_repeat_hint_but_items_reread(res):
    v = _ok(res, "s7")
    assert v["e8b"]["prevented"] is True, v["e8b"]
    assert v["e8b"]["hints"] == [{"key": "a", "pos": "before"}], v["e8b"]
    assert v["e8b"]["items"] > v["e8"]["items"], (v["e8"], v["e8b"])


@needs_node
def test_dragover_in_place_null_hint_then_new_target(res):
    v = _ok(res, "s7")
    assert v["e9"]["prevented"] is False, v["e9"]
    assert v["e9"]["hints"] == [{"key": "a", "pos": "before"}, None], v["e9"]
    assert v["e9b"]["prevented"] is True, v["e9b"]
    assert v["e9b"]["hints"] == [{"key": "a", "pos": "before"}, None, {"key": "d", "pos": "before"}], v["e9b"]


@needs_node
def test_dragover_outside_area_clears_hint(res):
    v = _ok(res, "s7")
    expected = [{"key": "a", "pos": "before"}, None, {"key": "d", "pos": "before"}, None]
    assert v["e10"]["prevented"] is False, v["e10"]
    assert v["e10"]["hints"] == expected, v["e10"]
    # already null -> no further notification
    assert v["e10b"]["prevented"] is False, v["e10b"]
    assert v["e10b"]["hints"] == expected, v["e10b"]
    assert v["drops10"] == 0, v


@needs_node
def test_drop_inside_stops_then_calls_on_drop(res):
    v = _ok(res, "s11")
    assert v["prevented"] is True, v
    assert v["removedSame"] is True, v
    assert v["drops"] == [{"key": "a", "pos": "before"}], v
    assert v["removeBeforeDrop"] is True, v


@needs_node
def test_drop_in_place_stops_without_on_drop(res):
    v = _ok(res, "s12")
    assert v == {"prevented": True, "removedSame": True, "drops": 0}, v


@needs_node
def test_drop_outside_ignored_session_kept(res):
    v = _ok(res, "s13")
    assert v["prevented"] is False, v
    assert v["removes"] == 0, v
    assert v["drops"] == 0, v
    assert v["alive"]["prevented"] is True, v
    assert v["alive"]["hints"] == [{"key": "a", "pos": "before"}], v


@needs_node
def test_stop_removes_same_listeners_without_hint(res):
    v = _ok(res, "s14")
    assert v["removedSame"] is True, v
    assert v["hintsAdded"] == 0, v
    assert v["drops"] == 0, v
    assert v["noThrow"] is True, v


@needs_node
def test_stop_before_start_no_throw(res):
    _ok(res, "stopBeforeStart")


@needs_node
def test_double_start_single_active_set(res):
    v = _ok(res, "s15")
    assert v["firstRemoved"] is True, v
    assert v["activeTypes"] == ["dragover", "drop"], v
    assert v["afterStop"] == 0, v


@needs_node
def test_default_area_is_document_element(res):
    v = _ok(res, "s16")
    assert v["deContains"] >= 1, v
    assert v["prevented"] is True, v
    assert v["hints"] == [{"key": "a", "pos": "before"}], v


# ── static: dashboard.js / settings.js (18-22) ──

def _imports(src):
    return re.findall(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']", src)


def _names(block):
    return {x.strip().split(" as ")[0].strip() for x in block.split(",") if x.strip()}


def _fn_body(src, name):
    m = re.search(r"function\s+" + re.escape(name) + r"\b", src)
    assert m, f"function {name} not found"
    nxt = re.search(r"\bfunction\s+[A-Za-z_$]", src[m.end():])
    return src[m.start(): m.end() + nxt.start()] if nxt else src[m.start():]


def _assert_handles(src, where):
    starts = [m.start() for m in re.finditer(r"onDragStart=", src)]
    assert starts, f"no onDragStart in {where}"
    for s in starts:
        e = src.index("onDragEnd=", s)
        h = src.index("⠿", e)
        seg_start, seg_end = src[s:e], src[e:h]
        assert "startDragDrop(" in seg_start, (where, seg_start)
        assert "startDragAutoScroll(e.currentTarget)" in seg_start, (where, seg_start)
        assert "stopDragDrop()" in seg_end, (where, seg_end)
        assert "stopDragAutoScroll()" in seg_end, (where, seg_end)


def test_dashboard_imports_drag_drop_from_lib_only():
    src = DASH.read_text(encoding="utf-8")
    imps = _imports(src)
    assert [p for _, p in imps] == ["../lib.js"], imps
    names = _names(imps[0][0])
    for n in ("startDragDrop", "stopDragDrop"):
        assert n in names, n


def test_settings_imports_drag_drop():
    src = SETTINGS.read_text(encoding="utf-8")
    lib_imps = [b for b, p in _imports(src) if p == "../lib.js"]
    assert len(lib_imps) == 1, lib_imps
    names = _names(lib_imps[0])
    for n in ("startDragDrop", "stopDragDrop"):
        assert n in names, n


@pytest.mark.parametrize("path", [DASH, SETTINGS], ids=["dashboard", "settings"])
def test_no_element_drag_over_or_drop_handlers(path):
    src = path.read_text(encoding="utf-8")
    assert "onDragOver=" not in src
    assert "onDrop=" not in src


@pytest.mark.parametrize("path", [DASH, SETTINGS], ids=["dashboard", "settings"])
def test_handles_start_and_stop_drag_drop(path):
    _assert_handles(path.read_text(encoding="utf-8"), path.name)


def test_dashboard_page_still_saves_order():
    body = _fn_body(DASH.read_text(encoding="utf-8"), "DashboardPage")
    for w in ("moveSection(", "dashboard_order", "reloadSettings", "toastErr"):
        assert w in body, w
    assert re.search(r"api\(\s*[\"']/settings[\"']\s*,\s*\{[^}]*method\s*:\s*[\"']PUT[\"']", body)


def test_settings_still_reorders_categories():
    src = SETTINGS.read_text(encoding="utf-8")
    assert re.search(r"/categories/\$\{\w+\}/reorder", src)


def test_dashboard_slot_strings_kept():
    src = DASH.read_text(encoding="utf-8")
    for w in ("dash-slot", "drop-", "dragging", "key=${"):
        assert w in src, w


@pytest.mark.skipif(NODE is None, reason="node 없음")
@pytest.mark.parametrize("path", [LIB, DASH, SETTINGS], ids=["lib", "dashboard", "settings"])
def test_module_syntax(path):
    with open(path, "rb") as f:
        r = subprocess.run([NODE, "--check", "--input-type=module"], stdin=f, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-500:]
