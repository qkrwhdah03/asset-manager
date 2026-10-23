"""Edge auto-scroll while dragging (lib.js, shared) and the "기간별 통계" flow heading (loop 2026-10-24-006)."""
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
SEC_MONTH = '<section class="dash-section dash-month">'
SEC_FLOW = '<section class="dash-section dash-flow">'
FLOW_BAR = '<div class="section-bar">${handle("flow")}<h2 class="section-title">기간별 통계</h2></div>'
MONTH_BAR = '<div class="section-bar">${handle("month")}<h2 class="section-title">${monthLabel(month)}</h2></div>'

# (args, expected). Special strings "NaN" / "null" / "undefined" are turned into the JS values by the runner.
SPEED_CASES = [
    # 1. default edge 60, max 24 in [0, 600]
    ([300, 0, 600], 0), ([60, 0, 600], 0), ([540, 0, 600], 0),
    ([59, 0, 600], -1), ([30, 0, 600], -12), ([0, 0, 600], -24), ([-50, 0, 600], -24),
    ([541, 0, 600], 1), ([570, 0, 600], 12), ([600, 0, 600], 24), ([700, 0, 600], 24),
    # 3. shifted container
    ([215, 200, 800], -18), ([785, 200, 800], 18),
    # 4. small container: zone shrinks to half the height
    ([25, 0, 100], -12), ([50, 0, 100], 0), ([75, 0, 100], 12),
    # 5. explicit edge / max
    ([10, 0, 600, 100, 50], -45),
    # 6. invalid input -> 0, never throws
    ([100, 100, 100], 0), ([50, 100, 0], 0),
    (["NaN", 0, 600], 0), (["null", 0, 600], 0), (["undefined", 0, 600], 0), ([30, "NaN", 600], 0),
]

RUNNER = r"""
import { pathToFileURL } from "node:url";
import { readFileSync } from "node:fs";
const noop = () => {};
const el = () => ({ style: {}, setAttribute: noop, appendChild: noop, addEventListener: noop, click: noop, remove: noop });

// ── recording stubs ──
const rec = { add: [], remove: [], raf: [], cancel: [] };
let nextId = 1;
let pending = new Map();       // id -> cb (cancel does NOT delete: stale callbacks can still be run on purpose)
const allCbs = [];
globalThis.requestAnimationFrame = (cb) => { const id = nextId++; pending.set(id, cb); allCbs.push(cb); rec.raf.push(id); return id; };
globalThis.cancelAnimationFrame = (id) => { rec.cancel.push(id); };
const scrollingElement = { _ov: "visible", scrollHeight: 5000, clientHeight: 500, scrollTop: 100, isConnected: true,
  parentElement: null, getBoundingClientRect: () => ({ top: 999, bottom: 1000 }) };
const body = Object.assign(el(), { _ov: "visible", scrollHeight: 10, clientHeight: 10, parentElement: null });
globalThis.window = { addEventListener: noop, removeEventListener: noop, dispatchEvent: noop, innerHeight: 500,
  location: { hash: "", href: "" }, localStorage: { getItem: () => null, setItem: noop } };
globalThis.document = { title: "", documentElement: { style: {} }, body, createElement: el, scrollingElement,
  getElementById: () => null, querySelector: () => null,
  addEventListener: (type, fn, cap) => rec.add.push([type, fn, cap]),
  removeEventListener: (type, fn, cap) => rec.remove.push([type, fn, cap]) };
globalThis.getComputedStyle = (node) => ({ overflowY: (node && node._ov) || "visible", getPropertyValue: () => "" });

const lib = await import(pathToFileURL(process.argv[2]).href);
const { speed } = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const out = {};
out.import = { add: rec.add.length, raf: rec.raf.length };

const conv = (a) => a === "NaN" ? NaN : a === "null" ? null : a === "undefined" ? undefined : a;
const run = (f) => { try { return { v: f() }; } catch (e) { return { err: String(e) }; } };
out.speed = speed.map((args) => run(() => lib.autoScrollSpeed(...args.map(conv))));
out.mono = run(() => {
  const up = [], down = [];
  for (let y = 1; y < 60; y++) up.push(lib.autoScrollSpeed(y, 0, 600));
  for (let y = 541; y < 600; y++) down.push(lib.autoScrollSpeed(y, 0, 600));
  return { up, down };
});

// ── scrollParent ──
const node = (ov, sh, ch, parent) => ({ _ov: ov, scrollHeight: sh, clientHeight: ch, parentElement: parent || null });
out.sp = run(() => {
  const r = {};
  const self = node("auto", 900, 300, null);
  r.self = lib.scrollParent(self) === self;
  const scrollAnc = node("scroll", 900, 300, null);
  const flushAuto = node("auto", 300, 300, scrollAnc);        // overflow auto but not overflowing -> skip
  const leaf1 = node("visible", 50, 50, flushAuto);
  r.skipNonOverflowing = lib.scrollParent(leaf1) === scrollAnc;
  const autoAnc = node("auto", 900, 300, null);
  const hid = node("hidden", 900, 300, autoAnc);
  const vis = node("visible", 900, 300, hid);
  r.skipVisibleHidden = lib.scrollParent(vis) === autoAnc;
  const lone = node("visible", 50, 50, node("auto", 100, 100, null));
  r.fallbackNull = lib.scrollParent(lone) === scrollingElement;
  const toBody = node("visible", 50, 50, body);
  r.fallbackBody = lib.scrollParent(toBody) === scrollingElement;
  return r;
});

// ── drag auto-scroll ──
const reset = () => { rec.add.length = 0; rec.remove.length = 0; rec.raf.length = 0; rec.cancel.length = 0; pending = new Map(); };
const frame = () => { const cbs = [...pending.values()]; pending = new Map(); for (const cb of cbs) cb(performance.now()); };
const mk = () => {
  const container = { _ov: "auto", scrollHeight: 3000, clientHeight: 600, scrollTop: 300, isConnected: true,
    parentElement: null, getBoundingClientRect: () => ({ top: 0, bottom: 600, left: 0, right: 800, height: 600 }) };
  const handle = node("visible", 20, 20, node("visible", 100, 100, container));
  return { container, handle };
};
const L = (type) => { const a = rec.add.filter((x) => x[0] === type); return a.length ? a[a.length - 1][1] : null; };
const ev = (o) => Object.assign({ preventDefault: noop, stopPropagation: noop }, o);
const types = ["dragover", "dragleave", "drop"];
const removedSame = (added) => types.every((t) => {
  const a = added.find((x) => x[0] === t);
  return a && rec.remove.some((x) => x[0] === t && x[1] === a[1] && x[2] === true);
});

out.stopBeforeStart = run(() => { lib.stopDragAutoScroll(); lib.stopDragAutoScroll(); return true; });

// 8 + 9
out.s9 = run(() => {
  reset(); const { container, handle } = mk();
  lib.startDragAutoScroll(handle);
  const r = {};
  r.addTypes = rec.add.map((x) => x[0]).sort();
  r.addCapture = rec.add.map((x) => x[2]);
  r.addFns = rec.add.every((x) => typeof x[1] === "function");
  r.rafScheduled = rec.raf.length >= 1;
  L("dragover")(ev({ clientY: 0 })); frame();
  r.afterTop = container.scrollTop;
  r.rescheduled = pending.size >= 1;
  L("dragover")(ev({ clientY: 600 })); frame();
  r.afterBottom = container.scrollTop;
  L("dragover")(ev({ clientY: 300 })); frame();
  r.afterMiddle = container.scrollTop;
  lib.stopDragAutoScroll();
  return r;
});

// 10
out.s10 = run(() => {
  reset(); const { container, handle } = mk();
  lib.startDragAutoScroll(handle);
  const r = {};
  frame(); frame();
  r.beforeOver = container.scrollTop;
  L("dragover")(ev({ clientY: 0 }));
  L("dragleave")(ev({ relatedTarget: null, clientY: 0 }));
  frame(); frame();
  r.afterLeave = container.scrollTop;
  L("dragover")(ev({ clientY: 0 })); frame();
  r.resumed = container.scrollTop;
  lib.stopDragAutoScroll();
  return r;
});

// 11
out.s11 = run(() => {
  reset(); const { container, handle } = mk();
  lib.startDragAutoScroll(handle);
  L("dragover")(ev({ clientY: 0 })); frame();
  const added = rec.add.slice();
  const lastId = rec.raf[rec.raf.length - 1];
  const before = container.scrollTop;
  lib.stopDragAutoScroll();
  const r = {};
  r.cancelLast = rec.cancel.includes(lastId);
  r.removedSame = removedSame(added);
  for (const cb of allCbs.slice()) cb(performance.now());
  r.unchanged = container.scrollTop === before;
  lib.stopDragAutoScroll(); lib.stopDragAutoScroll();
  r.noThrow = true;
  return r;
});

// 12
out.s12 = run(() => {
  reset(); const { container, handle } = mk();
  lib.startDragAutoScroll(handle);
  L("dragover")(ev({ clientY: 0 })); frame();
  const added = rec.add.slice();
  const lastId = rec.raf[rec.raf.length - 1];
  const before = container.scrollTop;
  L("drop")(ev({ clientY: 0 }));
  const r = {};
  r.cancelLast = rec.cancel.includes(lastId);
  r.removedSame = removedSame(added);
  for (const cb of allCbs.slice()) cb(performance.now());
  r.unchanged = container.scrollTop === before;
  lib.stopDragAutoScroll();
  return r;
});

// 13
out.s13 = run(() => {
  reset(); const { container, handle } = mk();
  lib.startDragAutoScroll(handle);
  const first = rec.add.slice();
  lib.startDragAutoScroll(handle);
  const r = {};
  r.firstRemoved = removedSame(first);
  const active = rec.add.filter((a) => !rec.remove.some((x) => x[0] === a[0] && x[1] === a[1]));
  r.activeTypes = active.map((x) => x[0]).sort();
  L("dragover")(ev({ clientY: 0 })); frame();
  r.delta = container.scrollTop - 300;
  lib.stopDragAutoScroll();
  return r;
});

// 14
out.s14 = run(() => {
  reset(); const { container, handle } = mk();
  lib.startDragAutoScroll(handle);
  const added = rec.add.slice();
  L("dragover")(ev({ clientY: 0 }));
  container.isConnected = false;
  const rafBefore = rec.raf.length;
  frame();
  const r = {};
  r.removedSame = removedSame(added);
  r.noNewFrame = rec.raf.length === rafBefore;
  r.scrollTop = container.scrollTop;
  lib.stopDragAutoScroll();
  return r;
});

// document fallback container: rect is [0, window.innerHeight]
out.sDoc = run(() => {
  reset();
  const handle = node("visible", 20, 20, node("visible", 100, 100, null));
  scrollingElement.scrollTop = 100;
  lib.startDragAutoScroll(handle);
  L("dragover")(ev({ clientY: 500 })); frame();
  const r = { down: scrollingElement.scrollTop };
  L("dragover")(ev({ clientY: 0 })); frame();
  r.up = scrollingElement.scrollTop;
  lib.stopDragAutoScroll();
  return r;
});

process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def res(tmp_path_factory):
    if NODE is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("autoscroll")
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
    (d / "cases.json").write_text(json.dumps({"speed": [c[0] for c in SPEED_CASES]}), encoding="utf-8")
    r = subprocess.run([NODE, str(d / "run.mjs"), str(d / "lib.mjs"), str(d / "cases.json")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"lib.js 를 node 로 불러오지 못함: {r.stderr.strip()[-600:]}"
    return json.loads(r.stdout)


def _ok(res, key):
    v = res[key]
    assert "err" not in v, (key, v)
    return v["v"]


# ── autoScrollSpeed ──

@needs_node
@pytest.mark.parametrize("idx", range(len(SPEED_CASES)), ids=[json.dumps(c[0]) for c in SPEED_CASES])
def test_auto_scroll_speed(res, idx):
    args, expected = SPEED_CASES[idx]
    r = res["speed"][idx]
    assert "err" not in r, (args, r)
    assert r["v"] == expected, (args, r["v"])


@needs_node
def test_auto_scroll_speed_monotonic_up_and_down(res):
    v = _ok(res, "mono")
    up, down = v["up"], v["down"]            # up: y = 1..59, down: y = 541..599
    assert all(s < 0 for s in up), up
    assert all(s > 0 for s in down), down
    assert all(abs(up[i]) >= abs(up[i + 1]) for i in range(len(up) - 1)), up
    assert all(abs(down[i]) <= abs(down[i + 1]) for i in range(len(down) - 1)), down
    # symmetric: distance d from the top edge == distance d from the bottom edge
    assert [abs(s) for s in up] == [abs(s) for s in reversed(down)], (up, down)


# ── scrollParent ──

@needs_node
@pytest.mark.parametrize("case", ["self", "skipNonOverflowing", "skipVisibleHidden", "fallbackNull", "fallbackBody"])
def test_scroll_parent(res, case):
    v = _ok(res, "sp")
    assert v[case] is True, (case, v)


# ── start / stop ──

@needs_node
def test_import_has_no_side_effects(res):
    assert res["import"] == {"add": 0, "raf": 0}, res["import"]


@needs_node
def test_stop_before_start_no_throw(res):
    assert _ok(res, "stopBeforeStart") is True


@needs_node
def test_start_registers_capture_listeners_and_frame(res):
    v = _ok(res, "s9")
    assert v["addTypes"] == ["dragleave", "dragover", "drop"], v["addTypes"]
    assert v["addCapture"] == [True, True, True], v["addCapture"]
    assert v["addFns"] is True
    assert v["rafScheduled"] is True


@needs_node
def test_dragover_scrolls_per_frame(res):
    v = _ok(res, "s9")
    assert v["afterTop"] == 276, v
    assert v["rescheduled"] is True, v
    assert v["afterBottom"] == 300, v
    assert v["afterMiddle"] == 300, v


@needs_node
def test_no_scroll_before_dragover_and_after_window_leave(res):
    v = _ok(res, "s10")
    assert v["beforeOver"] == 300, v
    assert v["afterLeave"] == 300, v
    assert v["resumed"] == 276, v


@needs_node
def test_stop_cancels_and_removes(res):
    v = _ok(res, "s11")
    assert v["cancelLast"] is True, v
    assert v["removedSame"] is True, v
    assert v["unchanged"] is True, v
    assert v["noThrow"] is True, v


@needs_node
def test_drop_stops(res):
    v = _ok(res, "s12")
    assert v == {"cancelLast": True, "removedSame": True, "unchanged": True}, v


@needs_node
def test_double_start_single_active_set(res):
    v = _ok(res, "s13")
    assert v["firstRemoved"] is True, v
    assert v["activeTypes"] == ["dragleave", "dragover", "drop"], v
    assert v["delta"] == -24, v


@needs_node
def test_detached_container_stops(res):
    v = _ok(res, "s14")
    assert v["removedSame"] is True, v
    assert v["noNewFrame"] is True, v


@needs_node
def test_document_container_uses_window_height(res):
    v = _ok(res, "sDoc")
    assert v == {"down": 124, "up": 100}, v


def test_lib_exports_static():
    src = LIB.read_text(encoding="utf-8")
    for name in ("autoScrollSpeed", "scrollParent", "startDragAutoScroll", "stopDragAutoScroll"):
        assert re.search(rf"export\s+function\s+{name}\b", src), name


# ── static: dashboard.js ──

def _dash():
    return DASH.read_text(encoding="utf-8")


def _imports(src):
    return re.findall(r"import\s*\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']", src)


def _names(block):
    return {x.strip().split(" as ")[0].strip() for x in block.split(",") if x.strip()}


def _assert_drag_calls(seg_src, where):
    starts = [m.start() for m in re.finditer(r"onDragStart=", seg_src)]
    assert starts, f"no onDragStart in {where}"
    for s in starts:
        e = seg_src.index("onDragEnd=", s)
        h = seg_src.index("⠿", e)
        assert "startDragAutoScroll(e.currentTarget)" in seg_src[s:e], (where, seg_src[s:e])
        assert "stopDragAutoScroll()" in seg_src[e:h], (where, seg_src[e:h])


def test_flow_section_bar_literal():
    src = _dash()
    assert FLOW_BAR in src
    assert src.count(SEC_FLOW) == 1
    assert src.index(FLOW_BAR) > src.index(SEC_FLOW)


def test_section_titles_count_and_placement():
    src = _dash()
    assert src.count(SEC_MONTH) == 1 and src.count(SEC_FLOW) == 1
    mpos, fpos = src.index(SEC_MONTH), src.index(SEC_FLOW)
    pos = [m.start() for m in re.finditer(r'class="section-title"', src)]
    assert len(pos) == 2, pos
    assert mpos < pos[0] < fpos, (mpos, pos, fpos)
    assert pos[1] > fpos, (pos, fpos)
    assert MONTH_BAR in src
    assert src.count("${monthLabel(month)}") == 1
    assert "흐름" not in src
    assert src.count("기간별 통계") == 1


def test_dashboard_imports_drag_helpers():
    src = _dash()
    imps = _imports(src)
    assert [p for _, p in imps] == ["../lib.js"], imps
    assert len(re.findall(r"^\s*import\b", src, re.M)) == 1
    names = _names(imps[0][0])
    for n in ("startDragAutoScroll", "stopDragAutoScroll", "useApp", "api", "toastErr"):
        assert n in names, n


def test_dashboard_handle_calls_drag_helpers():
    src = _dash()
    i = src.index("const handle =")
    j = src.index("⠿", i)
    _assert_drag_calls(src[i:j + 1], "dashboard handle")


# ── static: settings.js ──

def test_settings_imports_and_handle_calls():
    src = SETTINGS.read_text(encoding="utf-8")
    lib_imps = [b for b, p in _imports(src) if p == "../lib.js"]
    assert len(lib_imps) == 1, lib_imps
    names = _names(lib_imps[0])
    assert "startDragAutoScroll" in names and "stopDragAutoScroll" in names, names
    _assert_drag_calls(src, "settings.js")
    assert re.search(r"/categories/\$\{\w+\}/reorder", src)
