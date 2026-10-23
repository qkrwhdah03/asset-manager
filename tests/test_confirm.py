"""Confirm dialog: browser window.confirm replaced by the in-app confirmBox modal.

Static checks over app/static (no browser automation, see U-22) plus a node run of lib.js.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
JS = APP / "static" / "js"
CSS = APP / "static" / "css" / "app.css"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node 없음")

PREACT_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']/vendor/preact-htm\.module\.js[\"']")

# Bare calls: no identifier char, `$` or `.` right before the name (so confirmBox(, x.confirm(, ConfirmHost pass).
BARE = {name: re.compile(rf"(?<![\w$.]){name}\s*\(") for name in ("confirm", "alert", "prompt")}
WINDOW = {name: re.compile(rf"\bwindow\s*\.\s*{name}\b") for name in ("confirm", "alert", "prompt")}

CALL = re.compile(r"(?<![\w$.])confirmBox\s*\(")
AWAITED_CALL = re.compile(r"\bawait\s+confirmBox\s*\(")

PAGE_MIN_CALLS = {"cashflow.js": 5, "settings.js": 8, "assets.js": 2, "indicators.js": 2}


def app_js_files():
    return sorted(p for p in JS.rglob("*.js") if "vendor" not in p.relative_to(JS).parts)


def rel(p):
    return p.relative_to(JS).as_posix()


def line_of(src, pos):
    return src.count("\n", 0, pos) + 1


# ── 1. no window.confirm / bare confirm / alert / prompt ──

def test_js_files_found():
    files = [rel(p) for p in app_js_files()]
    assert "lib.js" in files and "app.js" in files
    for page in PAGE_MIN_CALLS:
        assert f"pages/{page}" in files, page


@pytest.mark.parametrize("name", ["confirm", "alert", "prompt"])
def test_no_window_dialog(name):
    offenders = []
    for p in app_js_files():
        src = p.read_text(encoding="utf-8")
        offenders += [f"{rel(p)}:{line_of(src, m.start())}" for m in WINDOW[name].finditer(src)]
    assert offenders == [], f"window.{name} 이 남아 있음: {offenders}"


@pytest.mark.parametrize("name", ["confirm", "alert", "prompt"])
def test_no_bare_dialog_call(name):
    offenders = []
    for p in app_js_files():
        src = p.read_text(encoding="utf-8")
        offenders += [f"{rel(p)}:{line_of(src, m.start())}" for m in BARE[name].finditer(src)]
    assert offenders == [], f"bare {name}( 호출이 남아 있음: {offenders}"


def test_bare_regex_boundaries():
    # The guard regexes must not flag the new names.
    ok = "confirmBox(x); a.confirm(y); ConfirmHost(); $confirm(z); my_confirm(1); x.alert(2); usePrompt(3);"
    for name in ("confirm", "alert", "prompt"):
        assert not BARE[name].search(ok), name
    assert BARE["confirm"].search("if (!confirm('x')) return;")
    assert BARE["confirm"].search("(confirm ('x'))")


# ── 2·3. lib.js exports ──

def lib_src():
    return (JS / "lib.js").read_text(encoding="utf-8")


def _exported(src, name):
    if re.search(rf"export\s+(async\s+)?function\s+{name}\b", src):
        return True
    if re.search(rf"export\s+(const|let)\s+{name}\b", src):
        return True
    return any(re.search(rf"(?<![\w$]){name}(?![\w$])", m.group(1))
               for m in re.finditer(r"export\s*\{([^}]*)\}(?!\s*from)", src))


def test_lib_exports_confirm_box():
    assert _exported(lib_src(), "confirmBox"), "lib.js 가 confirmBox 를 export 하지 않음"


def test_lib_exports_confirm_host():
    assert _exported(lib_src(), "ConfirmHost"), "lib.js 가 ConfirmHost 를 export 하지 않음"


def _definition_block(src, name):
    m = re.search(rf"^(export\s+)?((async\s+)?function\s+{name}\b|(const|let)\s+{name}\b)", src, re.M)
    assert m, f"{name} 정의를 찾지 못함"
    nxt = re.compile(r"^(export\s|function\s|async\s+function\s|const\s|let\s|class\s|if\s*\(|// ─)", re.M)
    end = nxt.search(src, m.end())
    return src[m.start():end.start() if end else len(src)]


def test_confirm_box_body_has_no_window_confirm():
    body = _definition_block(lib_src(), "confirmBox")
    assert not WINDOW["confirm"].search(body), "confirmBox 정의 안에 window.confirm 이 있음"
    assert not BARE["confirm"].search(body), "confirmBox 정의 안에 bare confirm( 호출이 있음"


# ── 4. app.js renders ConfirmHost ──

def test_app_imports_confirm_host_from_lib():
    src = (JS / "app.js").read_text(encoding="utf-8")
    imports = [m.group(1) for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*[\"']\./lib\.js[\"']", src)]
    assert any(re.search(r"(?<![\w$])ConfirmHost(?![\w$])", names) for names in imports), \
        "app.js 가 ./lib.js 에서 ConfirmHost 를 import 하지 않음"


def test_app_renders_confirm_host():
    src = (JS / "app.js").read_text(encoding="utf-8")
    assert re.search(r"<\$\{\s*ConfirmHost\s*\}", src), "app.js 에 <${ConfirmHost} 렌더가 없음"


# ── 5. every confirmBox( call in pages is awaited ──

@pytest.mark.parametrize("page", sorted(PAGE_MIN_CALLS))
def test_page_confirm_box_calls_awaited(page):
    src = (JS / "pages" / page).read_text(encoding="utf-8")
    calls = list(CALL.finditer(src))
    assert len(calls) >= PAGE_MIN_CALLS[page], f"{page}: confirmBox( 호출 {len(calls)}개 < {PAGE_MIN_CALLS[page]}"
    awaited = {m.end() for m in AWAITED_CALL.finditer(src)}
    not_awaited = [f"pages/{page}:{line_of(src, m.start())}" for m in calls if m.end() not in awaited]
    assert not_awaited == [], f"await 없는 confirmBox( 호출: {not_awaited}"


def test_all_pages_confirm_box_calls_awaited():
    # Pages outside the known list must not call confirmBox without await either.
    bad = []
    for p in sorted((JS / "pages").glob("*.js")):
        src = p.read_text(encoding="utf-8")
        awaited = {m.end() for m in AWAITED_CALL.finditer(src)}
        bad += [f"pages/{p.name}:{line_of(src, m.start())}" for m in CALL.finditer(src) if m.end() not in awaited]
    assert bad == [], bad


def test_await_regex_shapes():
    shapes = [
        "if (!await confirmBox(`x`)) return;",
        "if (!(await confirmBox('x'))) return;",
        "if (r.all && await confirmBox(`x`)) {",
        "if (await   confirmBox(\n  'x'\n)) {",
    ]
    for s in shapes:
        calls = list(CALL.finditer(s))
        awaited = {m.end() for m in AWAITED_CALL.finditer(s)}
        assert len(calls) == 1 and all(m.end() in awaited for m in calls), s
    imp = "import {\n  toast, confirmBox,\n} from \"../lib.js\";"
    assert not CALL.search(imp)
    assert CALL.search("if (!confirmBox('x')) return;") and not AWAITED_CALL.search("if (!confirmBox('x')) return;")


# ── 8. existing confirm messages kept ──

@pytest.mark.parametrize("page,text", [
    ("settings.js", "정말 초기화할까요? 되돌리려면 백업 목록에서 pre_reset 백업을 복원해야 합니다."),
    ("cashflow.js", "정산을 취소하고 정산 전 계획·지출로 되돌릴까요?"),
    ("settings.js", "지우기 전에 현재 데이터를 자동 백업합니다. 계속할까요?"),
    ("cashflow.js", "원래 계획은 기록으로 보존됩니다. 정산할까요?"),
    ("assets.js", "계좌를 삭제할까요? (기록이 있으면 비활성화됩니다)"),
    ("indicators.js", "지표와 모든 값을 삭제할까요?"),
])
def test_confirm_messages_kept(page, text):
    src = (JS / "pages" / page).read_text(encoding="utf-8")
    assert text in src, f"{page}: 확인 문구가 사라짐: {text}"


# ── 9. CSS keeps line breaks in the confirm message ──

def test_css_confirm_pre_wrap():
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    hits = [sel.strip() for sel, body in blocks
            if "confirm" in sel.lower() and re.search(r"white-space\s*:\s*pre-wrap", body)]
    assert hits, "confirm 이 들어간 선택자 중 white-space: pre-wrap 규칙이 없음"


# ── 6. node run of lib.js ──

RUNNER = r"""
import { pathToFileURL } from "node:url";
const noop = () => {};
const calls = { confirm: 0, alert: 0, prompt: 0 };
const el = () => ({ style: {}, setAttribute: noop, appendChild: noop, addEventListener: noop, click: noop, remove: noop });
globalThis.window = { addEventListener: noop, removeEventListener: noop, dispatchEvent: noop,
  location: { hash: "", href: "" }, localStorage: { getItem: () => null, setItem: noop },
  confirm: () => { calls.confirm++; return true; },
  alert: () => { calls.alert++; },
  prompt: () => { calls.prompt++; return null; } };
globalThis.confirm = window.confirm;
globalThis.alert = window.alert;
globalThis.prompt = window.prompt;
globalThis.document = { title: "", documentElement: { style: {} }, body: el(), createElement: el,
  getElementById: () => null, querySelector: () => null, addEventListener: noop, removeEventListener: noop };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
const out = {};
let lib;
try {
  lib = await import(pathToFileURL(process.argv[2]).href);
  out.import = { ok: true };
} catch (e) {
  out.import = { ok: false, err: String(e && e.stack || e) };
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
}
out.types = { confirmBox: typeof lib.confirmBox, ConfirmHost: typeof lib.ConfirmHost };
const isPromise = (r) => r instanceof Promise || (r != null && typeof r.then === "function");
const race = (p) => Promise.race([
  Promise.resolve(p).then(() => "resolved", () => "rejected"),
  new Promise((r) => setTimeout(() => r("pending"), 50)),
]);
const probe = async (f) => {
  try {
    const r = f();
    return { ok: true, promise: isPromise(r), state: isPromise(r) ? await race(r) : String(r) };
  } catch (e) {
    return { ok: false, err: String(e && e.stack || e) };
  }
};
out.plain = await probe(() => lib.confirmBox("메시지"));
out.options = await probe(() => lib.confirmBox("m", { title: "삭제", ok: "삭제", cancel: "닫기" }));
out.calls = calls;
process.stdout.write(JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def confirm_results(tmp_path_factory):
    if NODE is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("confirmjs")
    src = lib_src()
    m = PREACT_IMPORT.search(src)
    if m:
        names = [x.strip().split(" as ")[0].strip() for x in m.group(1).split(",") if x.strip()]
        (d / "preact-stub.mjs").write_text(
            "".join(f"export const {nm} = (...a) => ({{}});\n" for nm in names), encoding="utf-8")
        src = src[:m.start()] + src[m.start():m.end()].replace("/vendor/preact-htm.module.js", "./preact-stub.mjs") \
            + src[m.end():]
    (d / "lib.mjs").write_text(src, encoding="utf-8")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")
    r = subprocess.run([NODE, str(d / "run.mjs"), str(d / "lib.mjs")],
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, f"node 실행 실패: {r.stderr.strip()[-400:]}"
    return json.loads(r.stdout)


@needs_node
def test_node_lib_imports(confirm_results):
    assert confirm_results["import"]["ok"], confirm_results["import"].get("err", "")[-400:]


@needs_node
def test_node_exports_are_functions(confirm_results):
    assert confirm_results["import"]["ok"]
    assert confirm_results["types"] == {"confirmBox": "function", "ConfirmHost": "function"}


@needs_node
def test_node_confirm_box_returns_promise(confirm_results):
    res = confirm_results.get("plain")
    assert res and res["ok"], res
    assert res["promise"] is True, res


@needs_node
def test_node_confirm_box_pending_without_host(confirm_results):
    res = confirm_results.get("plain")
    assert res and res["ok"], res
    assert res["state"] == "pending", res


@needs_node
def test_node_confirm_box_with_options(confirm_results):
    res = confirm_results.get("options")
    assert res and res["ok"], res
    assert res["promise"] is True, res
    assert res["state"] == "pending", res


@needs_node
def test_node_window_confirm_never_called(confirm_results):
    assert confirm_results["import"]["ok"]
    assert confirm_results["calls"] == {"confirm": 0, "alert": 0, "prompt": 0}, confirm_results["calls"]
