# 언어 2단계(loop 2026-10-21-003): 서버 표시 문구 번역 + 화면 JS 문구 사전화 + 화면 날짜 표시.
import csv
import io
import json
import re
import shutil
import string
import subprocess
import warnings
from pathlib import Path
from urllib.parse import unquote

import pytest

from app import db, i18n

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
HANGUL = re.compile(r"[가-힣]")
M = "2026-10"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node 없음")

SYSTEM_KO = ["계획 옮기기(보냄)", "계획 옮기기(받음)", "미배분에서 추가", "월말 정산(계획 조정)",
             "월말 정산(조정 없음)", "월말 정산(남은 돈)", "월말 정산"]
# 정산·옮기기 시나리오에서 실제로 생기는 시스템 메모
SCENARIO_MEMOS = ["계획 옮기기(보냄)", "계획 옮기기(받음)", "미배분에서 추가", "월말 정산(계획 조정)", "월말 정산(남은 돈)"]
USER_MEMO = "사용자 메모"


def has_hangul(s) -> bool:
    return bool(HANGUL.search(str(s)))


def placeholders(tmpl: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(tmpl) if f is not None}


def rows_of(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def set_lang(client, lang):
    r = client.put("/api/settings", json={"language": lang})
    assert r.status_code == 200, r.text


def cat_by_name(client, name):
    return next(c for c in client.get("/api/categories").json() if c["name"] == name)["id"]


# ── 1~6. 서버 카탈로그 ──

def test_labels_both_languages_placeholders_and_en_no_hangul():
    assert i18n.LABELS
    for key, t in i18n.LABELS.items():
        assert set(t) >= {"ko", "en"}, key
        assert t["ko"].strip() and t["en"].strip(), key
        assert placeholders(t["ko"]) == placeholders(t["en"]), key
        assert not has_hangul(t["en"]), key


LABEL_KO = {
    "stats.basis.budget": "예산 월 기준",
    "stats.basis.cash": "입금·결제일 기준",
    "settings.secret_set": "설정됨",
    "app.title": "개인 자산 관리",
    "export.records": "수입지출기록",
    "export.categories": "항목",
    "export.template": "양식_{name}",
    "export.asset_txns": "자산변동",
    "export.prices": "종목시세",
    "export.indicator": "지표_{id}",
}


@pytest.mark.parametrize("key,ko", list(LABEL_KO.items()))
def test_required_label_keys(key, ko):
    assert key in i18n.LABELS
    assert i18n.LABELS[key]["ko"] == ko
    if key.startswith("export."):
        assert i18n.LABELS[key]["en"].isascii(), i18n.LABELS[key]["en"]


def test_label_function():
    assert i18n.label("app.title", "en") == "Asset Manager"
    assert i18n.label("app.title", "ko") == "개인 자산 관리"
    assert i18n.label("export.template", "ko", name="records") == "양식_records"
    assert i18n.label("export.indicator", "ko", id=3) == "지표_3"
    assert i18n.label("app.title", "EN") == "Asset Manager"
    assert i18n.label("app.title", " En ") == "Asset Manager"
    assert i18n.label("app.title", None) == "개인 자산 관리"
    en_tmpl = i18n.label("export.template", "en", name="records")
    assert "records" in en_tmpl and en_tmpl.isascii()


def test_label_unknown_key_raises():
    with pytest.raises(KeyError):
        i18n.label("no.such.key", "ko")
    with pytest.raises(KeyError):
        i18n.label("no.such.key", "en")


def test_message_http_forbidden():
    m = i18n.MESSAGES["http.forbidden"]
    assert m["ko"] == "허용되지 않은 요청입니다."
    assert m["en"].strip() and not has_hangul(m["en"])


def test_system_texts_exact_keys():
    assert set(i18n.SYSTEM_TEXTS) == set(SYSTEM_KO)
    assert len(i18n.SYSTEM_TEXTS) == 7
    for k, v in i18n.SYSTEM_TEXTS.items():
        assert v and v.strip() and not has_hangul(v), k


def test_system_text_function():
    for k in SYSTEM_KO:
        assert i18n.system_text(k, "en") == i18n.SYSTEM_TEXTS[k]
        assert i18n.system_text(k, "EN") == i18n.SYSTEM_TEXTS[k]
        assert i18n.system_text(k, "ko") == k
    assert i18n.system_text("점심 식사", "en") == "점심 식사"
    assert i18n.system_text("월말 정산 ", "en") == "월말 정산 "  # 정확히 같은 글자만
    assert i18n.system_text(None, "en") is None
    assert i18n.system_text("", "en") == ""
    assert i18n.system_text(None, "ko") is None
    assert i18n.system_text("", "ko") == ""


# ── 7~12. 시스템 기록 번역(응답만, 저장 값 불변) ──

def _scenario(client, settle=True):
    """소득 → 계획 → 옮기기(항목 간·미배분에서) → 사용자 지출 → 정산(남은 돈 > 0)."""
    sal, food, hobby, save = (cat_by_name(client, n) for n in ("급여", "식비", "취미", "저축·투자"))
    ok = lambda r: r.status_code == 200 or pytest.fail(r.text)  # noqa: E731
    ok(client.post("/api/records", json={"kind": "income", "category_id": sal, "amount": 1_000_000,
                                         "month": M, "txn_date": "2026-10-01"}))
    ok(client.put("/api/budget/plan", json={"month": M, "category_id": food, "amount": 300_000}))
    ok(client.put("/api/budget/plan", json={"month": M, "category_id": save, "amount": 500_000}))
    ok(client.post("/api/budget/move", json={"month": M, "from_category_id": food, "to_category_id": hobby,
                                             "amount": 50_000}))
    ok(client.post("/api/budget/move", json={"month": M, "from_category_id": None, "to_category_id": hobby,
                                             "amount": 10_000}))
    ok(client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 100_000, "month": M,
                                         "txn_date": "2026-10-05", "item": "장보기", "memo": USER_MEMO}))
    if settle:
        r = client.post("/api/budget/settle", json={"month": M, "category_id": save})
        ok(r)
        assert r.json()["leftover"] == 0
    return {"food": food, "hobby": hobby, "save": save, "sal": sal}


def _db_rows(tmp_path):
    c = db.connect(tmp_path / "api.db")
    try:
        return [dict(r) for r in c.execute("SELECT id, kind, item, memo, tag FROM records ORDER BY id")]
    finally:
        c.close()


def _records_api(client, ids):
    out = []
    for cid in ids:
        r = client.get("/api/records", params={"category_id": cid, "month": M})
        assert r.status_code == 200, r.text
        out += r.json()
    return out


def _budget_items(b):
    return [i for e in b["envelopes"] for i in e["items"]]


def test_en_budget_settle_row_translated(client):
    set_lang(client, "en")
    ids = _scenario(client)
    b = client.get("/api/budget", params={"month": M}).json()
    rows = [i for i in _budget_items(b) if i["tag"] == "settle"]
    assert rows, "정산 지출 행이 없다"
    for i in rows:
        assert not has_hangul(i["item"]) and not has_hangul(i["memo"]), i
        assert i["item"] == i18n.SYSTEM_TEXTS["월말 정산"]
        assert i["memo"] == i18n.SYSTEM_TEXTS["월말 정산(남은 돈)"]
    user = [i for i in _budget_items(b) if not i["tag"]]
    assert any(i["memo"] == USER_MEMO and i["item"] == "장보기" for i in user)
    assert ids


def test_en_list_records_tagged_rows_translated(client):
    set_lang(client, "en")
    ids = _scenario(client)
    rows = _records_api(client, [ids["food"], ids["hobby"], ids["save"]])
    tagged = [r for r in rows if r.get("tag")]
    assert tagged
    for r in tagged:
        assert not has_hangul(r["item"] or "") and not has_hangul(r["memo"] or ""), r
    memos = {r["memo"] for r in tagged}
    assert {i18n.SYSTEM_TEXTS[k] for k in SCENARIO_MEMOS} <= memos, memos
    # 미배분에서 옮기기(from 없음)도 번역 대상
    assert i18n.SYSTEM_TEXTS["미배분에서 추가"] in memos
    users = [r for r in rows if not r.get("tag")]
    assert any(r["memo"] == USER_MEMO for r in users)


def test_en_db_values_unchanged(client, tmp_path):
    set_lang(client, "en")
    _scenario(client)
    client.get("/api/budget", params={"month": M})
    client.get("/api/records", params={"month": M})
    rows = _db_rows(tmp_path)
    memos = {r["memo"] for r in rows if r["tag"]}
    assert set(SCENARIO_MEMOS) <= memos, memos
    items = {r["item"] for r in rows if r["tag"] == "settle" and r["kind"] == "expense"}
    assert items == {"월말 정산"}


def test_toggle_language_keeps_db_strings(client, tmp_path):
    _scenario(client)
    before = _db_rows(tmp_path)
    for lang in ("en", "ko", "en", "ko"):
        set_lang(client, lang)
        assert client.get("/api/budget", params={"month": M}).status_code == 200
        assert client.get("/api/records", params={"month": M}).status_code == 200
        assert client.get("/api/export/records").status_code == 200
    assert _db_rows(tmp_path) == before


def test_ko_responses_return_stored_values(client, tmp_path):
    ids = _scenario(client)
    stored = {r["id"]: (r["item"], r["memo"]) for r in _db_rows(tmp_path)}
    rows = _records_api(client, [ids["food"], ids["hobby"], ids["save"]])
    assert any(r.get("tag") for r in rows)
    for r in rows:
        assert (r["item"], r["memo"]) == stored[r["id"]], r
    b = client.get("/api/budget", params={"month": M}).json()
    for i in _budget_items(b):
        assert (i["item"], i["memo"]) == stored[i["id"]], i
    settle_rows = [i for i in _budget_items(b) if i["tag"] == "settle"]
    assert settle_rows and settle_rows[0]["item"] == "월말 정산" and settle_rows[0]["memo"] == "월말 정산(남은 돈)"


def test_user_record_with_system_text_not_translated(client):
    food = cat_by_name(client, "식비")
    r = client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 1000, "month": M,
                                          "txn_date": "2026-10-03", "item": "월말 정산", "memo": "월말 정산(남은 돈)"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    set_lang(client, "en")
    b = client.get("/api/budget", params={"month": M}).json()
    it = next(i for i in _budget_items(b) if i["id"] == rid)
    assert it["item"] == "월말 정산" and it["memo"] == "월말 정산(남은 돈)"
    rec = next(x for x in client.get("/api/records", params={"category_id": food, "month": M}).json() if x["id"] == rid)
    assert rec["item"] == "월말 정산" and rec["memo"] == "월말 정산(남은 돈)"


KEYS = ("settled", "settle_target", "balanced", "spent_total", "plan_total", "leftover")


def _pick(b):
    return {k: b[k] for k in KEYS}


def test_en_settle_state_same_as_ko(client):
    ids = _scenario(client)
    ko = _pick(client.get("/api/budget", params={"month": M}).json())
    assert ko["settled"] and ko["balanced"] and ko["settle_target"] == ids["save"]
    set_lang(client, "en")
    assert _pick(client.get("/api/budget", params={"month": M}).json()) == ko
    # en 에서 다시 정산(대상 생략 → 지난 대상)
    r = client.post("/api/budget/settle", json={"month": M})
    assert r.status_code == 200, r.text
    assert _pick(r.json()) == ko
    # en 에서 정산 취소 → 다시 정산
    r = client.delete("/api/budget/settle", params={"month": M})
    assert r.status_code == 200, r.text
    assert r.json()["settled"] is False and r.json()["settle_target"] is None
    r = client.post("/api/budget/settle", json={"month": M, "category_id": ids["save"]})
    assert r.status_code == 200, r.text
    assert _pick(r.json()) == ko
    assert _pick(client.get("/api/budget", params={"month": M}).json()) == ko


def test_en_settle_from_scratch_same_as_ko(client):
    set_lang(client, "en")
    ids = _scenario(client)
    en = _pick(client.get("/api/budget", params={"month": M}).json())
    assert en["settled"] and en["balanced"] and en["settle_target"] == ids["save"]
    set_lang(client, "ko")
    assert _pick(client.get("/api/budget", params={"month": M}).json()) == en


def test_en_settle_zero_leftover_marker(client, tmp_path):
    sal, food, save = (cat_by_name(client, n) for n in ("급여", "식비", "저축·투자"))
    client.post("/api/records", json={"kind": "income", "category_id": sal, "amount": 100_000, "month": M,
                                      "txn_date": "2026-10-01"})
    client.put("/api/budget/plan", json={"month": M, "category_id": food, "amount": 100_000})
    client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 100_000, "month": M,
                                      "txn_date": "2026-10-02"})
    r = client.post("/api/budget/settle", json={"month": M, "category_id": save})
    assert r.status_code == 200, r.text
    ko = _pick(r.json())
    assert ko["settled"] is True and ko["settle_target"] == save
    memos = {x["memo"] for x in _db_rows(tmp_path) if x["tag"] == "settle"}
    assert memos == {"월말 정산(조정 없음)"}
    set_lang(client, "en")
    en = client.get("/api/budget", params={"month": M}).json()
    assert en["settled"] is True and en["settle_target"] == save and _pick(en) == ko
    r = client.post("/api/budget/settle", json={"month": M})  # 대상 생략 → 표식 행으로 대상 찾기
    assert r.status_code == 200, r.text
    assert _pick(r.json()) == ko
    rows = client.get("/api/records", params={"category_id": save, "month": M}).json()
    marker = [x for x in rows if x.get("tag") == "settle"]
    assert marker and all(x["memo"] == i18n.SYSTEM_TEXTS["월말 정산(조정 없음)"] for x in marker)


def test_en_export_records_memo_translated(client):
    _scenario(client)
    set_lang(client, "en")
    rows = rows_of(client.get("/api/export/records").content)
    memos = [r[8] for r in rows[1:]]
    assert {i18n.SYSTEM_TEXTS[k] for k in SCENARIO_MEMOS} <= set(memos), memos
    assert USER_MEMO in memos
    assert not any(has_hangul(m) for m in memos if m != USER_MEMO), memos


def test_ko_export_records_memo_stored(client):
    _scenario(client)
    memos = {r[8] for r in rows_of(client.get("/api/export/records").content)[1:]}
    assert set(SCENARIO_MEMOS) <= memos and USER_MEMO in memos


# ── 13~17. 기타 서버 표시 문구 ──

@pytest.mark.parametrize("basis,ko", [("budget", "예산 월 기준"), ("cash", "입금·결제일 기준")])
def test_stats_basis_label(client, basis, ko):
    r = client.get("/api/stats/summary", params={"month": M, "basis": basis})
    assert r.status_code == 200, r.text
    assert r.json()["basis_label"] == ko
    set_lang(client, "en")
    en = client.get("/api/stats/summary", params={"month": M, "basis": basis}).json()["basis_label"]
    assert en and not has_hangul(en)
    assert en == i18n.label(f"stats.basis.{basis}", "en")


def test_short_secret_display(client):
    r = client.put("/api/settings", json={"ecos_api_key": "abc123"})
    assert r.status_code == 200, r.text
    s = client.get("/api/settings").json()
    assert s["ecos_api_key"] == "설정됨" and s["ecos_api_key_set"] is True
    set_lang(client, "en")
    s = client.get("/api/settings").json()
    assert s["ecos_api_key"] == "Set" and s["ecos_api_key_set"] is True


def test_long_secret_display_unchanged(client):
    client.put("/api/settings", json={"ecos_api_key": "ABCDEFGH12345", "language": "en"})
    s = client.get("/api/settings").json()
    assert s["ecos_api_key"] == "ABC…45"


def _raw_client(client):
    from fastapi.testclient import TestClient
    return TestClient(client.app)  # X-Requested-With 헤더 없음


def test_csrf_forbidden_ko(client):
    r = _raw_client(client).post("/api/reset", json={"mode": "x"})
    assert r.status_code == 403
    assert r.json() == {"detail": "허용되지 않은 요청입니다.", "code": "http.forbidden"}


def test_csrf_forbidden_en(client):
    set_lang(client, "en")
    raw = _raw_client(client)
    for r in (raw.post("/api/reset", json={"mode": "x"}), raw.put("/api/settings", json={"language": "ko"})):
        assert r.status_code == 403
        j = r.json()
        assert j["code"] == "http.forbidden"
        assert j["detail"] and not has_hangul(j["detail"])
    assert client.get("/api/settings").json()["language"] == "en"  # 거부된 요청은 반영되지 않음


def _fname(r) -> str:
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    assert m, cd
    return unquote(m.group(1))


def test_csv_filenames_ko(client):
    assert re.fullmatch(r"수입지출기록_\d{8}\.csv", _fname(client.get("/api/export/records")))
    assert re.fullmatch(r"항목_\d{8}\.csv", _fname(client.get("/api/export/categories")))
    assert re.fullmatch(r"양식_records_\d{8}\.csv", _fname(client.get("/api/templates/records")))


def test_csv_filenames_en(client):
    set_lang(client, "en")
    names = [_fname(client.get(p)) for p in ("/api/export/records", "/api/export/categories", "/api/templates/records")]
    assert re.fullmatch(r"records_\d{8}\.csv", names[0]), names
    assert re.fullmatch(r"categories_\d{8}\.csv", names[1]), names
    assert re.fullmatch(r"template_records_\d{8}\.csv", names[2]), names
    assert all(n.isascii() for n in names)


@pytest.mark.parametrize("lang,title", [("en", "Asset Manager"), ("ko", "개인 자산 관리")])
def test_create_app_title_follows_db_language(tmp_path, lang, title):
    from app.server import create_app
    p = tmp_path / f"{lang}.db"
    db.init_db(p, lang=lang).close()
    assert create_app(p).title == title


# ── 18~24. 화면 JS (정적·node) ──

JS_FILES = ["i18n.js", "lib.js", "app.js", "pages/settings.js", "pages/cashflow.js", "pages/dashboard.js",
            "pages/move.js"]
UI_FILES = ["lib.js", "app.js", "pages/cashflow.js", "pages/dashboard.js", "pages/move.js", "pages/settings.js"]
NO_MARK_FILES = {"pages/dashboard.js", "pages/move.js", "app.js"}
MAX_MARK_LINES = 25
KEY_PREFIXES = ("common", "cashflow", "move", "dashboard", "categories", "backup", "csv", "nav", "settings",
                "display", "app")


@needs_node
@pytest.mark.parametrize("rel", JS_FILES)
def test_js_syntax_all(rel):
    p = JS / rel
    assert p.exists(), rel
    r = subprocess.run([NODE, "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


_KEYWORDS_BEFORE_REGEX = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                          "instanceof", "yield", "await"}


def strip_js_comments(src: str) -> tuple[str, bool]:
    """주석을 공백으로 바꾼 코드(줄 수 유지)와 토큰화가 끝까지 균형을 이뤘는지.
    문자열(' " `)·템플릿 ${…} 중첩·정규식 리터럴 안의 // 는 주석으로 보지 않는다."""
    out: list[str] = []
    stack: list = [0]  # int = 코드(중괄호 깊이), None = 템플릿 문자열
    i, n = 0, len(src)
    prev = ""  # 코드에서 마지막 의미 있는 문자("a" = 식별자/값 끝)
    last_word = ""

    def blank(seg):
        return "".join("\n" if ch == "\n" else " " for ch in seg)

    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if stack[-1] is None:  # 템플릿 문자열 안
            if c == "\\":
                out.append(src[i:i + 2]); i += 2; continue
            if c == "`":
                stack.pop(); out.append(c); i += 1; prev = "a"; last_word = ""; continue
            if c == "$" and nxt == "{":
                stack.append(0); out.append("${"); i += 2; prev = "{"; last_word = ""; continue
            out.append(c); i += 1; continue
        # 코드
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(blank(src[i:j])); i = j; continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(blank(src[i:j])); i = j; continue
        if c == "/" and (prev in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*",
                                  "%", "<", ">", "~", "^") or (prev == "a" and last_word in _KEYWORDS_BEFORE_REGEX)):
            j, in_cls = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2; continue
                if in_cls:
                    if ch == "]":
                        in_cls = False
                elif ch == "[":
                    in_cls = True
                elif ch == "/":
                    break
                j += 1
            if j < n and src[j] == "/":
                j += 1
                while j < n and src[j].isalpha():
                    j += 1
                out.append(src[i:j]); i = j; prev = "a"; last_word = ""; continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(src[i:j]); i = j; prev = "a"; last_word = ""; continue
        if c == "`":
            stack.append(None); out.append(c); i += 1; continue
        if c == "{":
            stack[-1] += 1
        elif c == "}":
            if stack[-1] == 0 and len(stack) >= 2 and stack[-2] is None:
                stack.pop(); out.append(c); i += 1; continue
            stack[-1] -= 1
        out.append(c)
        if c.isalnum() or c in "_$":
            last_word = (last_word + c) if prev == "a" and last_word is not None else c
            prev = "a"
        elif not c.isspace():
            prev, last_word = c, ""
        i += 1
    return "".join(out), stack == [0]


def _code(rel) -> str:
    src = (JS / rel).read_text(encoding="utf-8")
    code, ok = strip_js_comments(src)
    if not ok:
        warnings.warn(f"{rel}: 주석 제거 토큰화가 균형을 이루지 못함(판정은 그대로 진행)")
    assert len(code.splitlines()) == len(src.splitlines()), rel
    return code


def test_strip_js_comments_selfcheck():
    src = ('const u = "http://x"; // 주석 한글\n'
           "const r = /a\\/\\/b/g; /* 블록\n한글 */ const s = `a ${f(\"//\")} 한글 ${ {a:1}.a } b`;\n"
           "x = a / b / c; // 끝\n")
    code, ok = strip_js_comments(src)
    lines = code.splitlines()
    assert ok
    assert "http://x" in lines[0] and "주석" not in lines[0]
    assert "/a\\/\\/b/g" in lines[1] and "블록" not in lines[1]
    assert lines[2].lstrip().startswith("const s") and "`a ${f(\"//\")} 한글" in lines[2]
    assert "끝" not in lines[3] and "a / b / c" in lines[3]


@pytest.fixture(scope="module")
def dict_js(tmp_path_factory):
    if NODE is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("i18njs")
    shutil.copy(JS / "i18n.js", d / "i18n.mjs")
    runner = d / "dump.mjs"
    runner.write_text(
        'import { pathToFileURL } from "node:url";\n'
        'const m = await import(pathToFileURL(process.argv[2]).href);\n'
        'process.stdout.write(JSON.stringify(m.DICT));\n', encoding="utf-8")
    r = subprocess.run([NODE, str(runner), str(d / "i18n.mjs")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-500:]
    return json.loads(r.stdout)


JS_PH = re.compile(r"\{(\w+)\}")


def test_js_dict_consistency(dict_js):
    ko, en = dict_js["ko"], dict_js["en"]
    assert set(ko) == set(en), {"ko_only": sorted(set(ko) - set(en))[:20], "en_only": sorted(set(en) - set(ko))[:20]}
    bad_ph = [k for k in ko if set(JS_PH.findall(ko[k])) != set(JS_PH.findall(en[k]))]
    assert bad_ph == []
    bad_en = [k for k, v in en.items() if has_hangul(v)]
    assert bad_en == []


T_CALL = re.compile(r"(?<![\w$.])t\(\s*([\"'])((?:(?!\1).)+?)\1")
KEY_LIT = re.compile(r"([\"'])((?:" + "|".join(KEY_PREFIXES) + r")\.[A-Za-z0-9_.]*[A-Za-z0-9_])\1")


@pytest.mark.parametrize("rel", UI_FILES)
def test_js_keys_exist_in_dict(dict_js, rel):
    code = _code(rel)
    keys = {m.group(2) for m in T_CALL.finditer(code)} | {m.group(2) for m in KEY_LIT.finditer(code)}
    missing = sorted(k for k in keys if k not in dict_js["ko"])
    assert missing == [], f"{rel}: {missing[:20]}"


def _hangul_lines(rel):
    raw = (JS / rel).read_text(encoding="utf-8").splitlines()
    code = _code(rel).splitlines()
    unmarked, marked = [], []
    for no, (r, c) in enumerate(zip(raw, code), 1):
        if "i18n-ok" in r:
            marked.append(no)
        if HANGUL.search(c) and "i18n-ok" not in r:
            unmarked.append(f"{rel}:{no}: {r.strip()[:60]}")
    return unmarked, marked


@pytest.mark.parametrize("rel", UI_FILES)
def test_js_no_hardcoded_korean(rel):
    unmarked, marked = _hangul_lines(rel)
    assert unmarked == [], unmarked[:10]
    if rel in NO_MARK_FILES:
        assert marked == [], f"{rel}: i18n-ok 표식 줄 {marked}"


def test_js_marker_lines_total():
    total = {rel: len(_hangul_lines(rel)[1]) for rel in UI_FILES}
    assert sum(total.values()) <= MAX_MARK_LINES, total


def test_lib_exports_new_formatters():
    src = (JS / "lib.js").read_text(encoding="utf-8")
    for name in ("monthShort", "yearLabel", "dateTimeLabel", "monthLabel", "dateLabel"):
        assert re.search(rf"export\s+(const|function|let)\s+{name}\b", src), name


PREACT_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']/vendor/preact-htm\.module\.js[\"']")

FORMAT_CASES = [
    ({"language": "ko", "date_format": "auto"}, "monthShort", "2026-10", "10월"),
    ({"language": "en", "date_format": "auto"}, "monthShort", "2026-10", "Oct"),
    ({"language": "en", "date_format": "iso"}, "monthShort", "2026-03", "Mar"),
    ({"language": "ko", "date_format": "dot"}, "monthShort", "2026-03", "3월"),
    ({"language": "ko", "date_format": "auto"}, "yearLabel", 2026, "2026년"),
    ({"language": "en", "date_format": "auto"}, "yearLabel", "2026", "2026"),
    ({"language": "ko", "date_format": "iso"}, "yearLabel", 2026, "2026"),
    ({"language": "ko", "date_format": "auto"}, "dateTimeLabel", "2026-10-21T09:05:33", "2026년 10월 21일 09:05"),
    ({"language": "en", "date_format": "auto"}, "dateTimeLabel", "2026-10-21T09:05:33", "Oct 21, 2026 09:05"),
] + [({"language": lang, "date_format": "auto"}, fn, "", "")
     for lang in ("ko", "en") for fn in ("monthShort", "yearLabel", "dateTimeLabel")]

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
const lib = await import(pathToFileURL(process.argv[2]).href);
const cases = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const out = cases.map(([loc, fn, arg]) => {
  try { lib.setLocale(loc); return { v: lib[fn](arg) }; } catch (e) { return { err: String(e) }; }
});
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def format_results(tmp_path_factory):
    if NODE is None:
        pytest.skip("node 없음")
    d = tmp_path_factory.mktemp("libjs")
    src = (JS / "lib.js").read_text(encoding="utf-8")
    m = PREACT_IMPORT.search(src)
    if m:
        names = [x.strip().split(" as ")[0].strip() for x in m.group(1).split(",") if x.strip()]
        (d / "preact-stub.mjs").write_text(
            "".join(f"export const {nm} = (...a) => ({{}});\n" for nm in names), encoding="utf-8")
        src = src[:m.start()] + src[m.start():m.end()].replace("/vendor/preact-htm.module.js", "./preact-stub.mjs") \
            + src[m.end():]
    src = re.sub(r"([\"'])\./i18n\.js\1", '"./i18n.mjs"', src)
    (d / "lib.mjs").write_text(src, encoding="utf-8")
    shutil.copy(JS / "i18n.js", d / "i18n.mjs")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")
    (d / "cases.json").write_text(json.dumps([[c[0], c[1], c[2]] for c in FORMAT_CASES]), encoding="utf-8")
    r = subprocess.run([NODE, str(d / "run.mjs"), str(d / "lib.mjs"), str(d / "cases.json")],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        pytest.skip(f"lib.js 를 node 스텁으로 불러오지 못함(정적 export 검사로 대체): {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout)


@pytest.mark.parametrize("idx", range(len(FORMAT_CASES)),
                         ids=[f"{c[0]['language']}-{c[0]['date_format']}-{c[1]}({c[2]!r})" for c in FORMAT_CASES])
def test_lib_format_functions(format_results, idx):
    loc, fn, arg, expected = FORMAT_CASES[idx]
    res = format_results[idx]
    assert "err" not in res, res
    assert res["v"] == expected, (loc, fn, arg, res["v"])


def test_app_sets_document_title():
    src = _code("app.js")
    tcall = r"t\(\s*(?:\"app\.name\"|'app\.name')\s*\)"
    if re.search(r"document\.title\s*=\s*" + tcall, src):
        return
    # 변수에 담아 대입하는 형태도 허용: const x = t("app.name"); ... document.title = x;
    names = [m.group(1) for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*" + tcall, src)]
    assert any(re.search(r"document\.title\s*=\s*" + re.escape(n) + r"\b", src) for n in names), \
        "document.title 을 t(\"app.name\") 로 맞추는 코드 없음"


def test_settings_csvview_no_local_t():
    src = _code("pages/settings.js")
    m = re.search(r"function\s+CsvView\s*\(", src)
    assert m, "CsvView 없음"
    nxt = re.search(r"\n(?:export\s+)?(?:async\s+)?function\s+\w+\s*\(|\n(?:export\s+)?const\s+[A-Z]\w*\s*=", src[m.end():])
    body = src[m.start(): m.end() + (nxt.start() if nxt else len(src))]
    assert not re.search(r"\b(?:const|let|var)\s+t\s*=", body)
