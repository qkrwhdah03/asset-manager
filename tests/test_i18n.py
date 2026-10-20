import ast
import csv
import io
import re
import shutil
import string
import subprocess
from pathlib import Path

import pytest

from app import config, db, i18n
from app.services import csvio, records
from app.services import settings as app_settings
from app.util import AppError
from conftest import cat_id

ROOT = Path(__file__).resolve().parent.parent
HANGUL = re.compile(r"[가-힣]")

KO_COLS = ["구분", "항목", "세부항목", "금액", "월", "거래일", "결제일", "예산월", "메모"]
EN_COLS = ["Type", "Category", "Item", "Amount", "Month", "Date", "Settle date", "Budget month", "Memo"]


def has_hangul(s) -> bool:
    return bool(HANGUL.search(str(s)))


def rows_of(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def set_lang(client, lang):
    r = client.put("/api/settings", json={"language": lang})
    assert r.status_code == 200, r.text


def cat_by_name(client, name):
    return next(c for c in client.get("/api/categories").json() if c["name"] == name)["id"]


def placeholders(tmpl: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(tmpl) if f is not None}


# ── i18n 카탈로그 ──

def test_messages_have_both_languages_nonempty():
    assert i18n.MESSAGES
    for code, t in i18n.MESSAGES.items():
        assert set(t) >= {"ko", "en"}, code
        assert t["ko"].strip() and t["en"].strip(), code


def test_messages_placeholders_match():
    for code, t in i18n.MESSAGES.items():
        assert placeholders(t["ko"]) == placeholders(t["en"]), code


def test_en_templates_have_no_hangul():
    bad = [code for code, t in i18n.MESSAGES.items() if has_hangul(t["en"])]
    assert bad == []


@pytest.mark.parametrize("raw,expected", [
    ("en", "en"), (" EN ", "en"), ("ko", "ko"), (None, "ko"), ("", "ko"), ("fr", "ko"),
])
def test_normalize(raw, expected):
    assert i18n.normalize(raw) == expected


def test_tr_unknown_code_raises_keyerror():
    with pytest.raises(KeyError):
        i18n.tr("없는코드", "ko")


def test_tr_translates_field_label_in_en():
    assert "금액" in i18n.FIELD_LABELS
    en_label = i18n.FIELD_LABELS["금액"]
    assert en_label and not has_hangul(en_label)
    codes = [c for c, t in i18n.MESSAGES.items() if "field" in placeholders(t["en"])]
    assert codes, "field 자리표시자를 쓰는 코드가 하나도 없다"
    for code in codes:
        params = {p: "1" for p in placeholders(i18n.MESSAGES[code]["en"])}
        params["field"] = "금액"
        out = i18n.tr(code, "en", **params)
        assert en_label in out and "금액" not in out, (code, out)


def test_fixed_codes_exist():
    for code in ["reset.invalid_mode", "settings.unknown_key", "settings.invalid_value", "csv.empty_file",
                 "csv.unknown_template", "db.foreign_key", "db.unique", "db.integrity", "db.operational"]:
        assert code in i18n.MESSAGES, code


def test_default_name_maps():
    assert set(i18n.DEFAULT_CATEGORY_NAMES) == {"급여", "장학금", "식비", "교통비", "주거·관리비", "통신비", "구독료",
                                                 "취미", "의료비", "기타", "저축·투자"}
    assert not any(has_hangul(v) for v in i18n.DEFAULT_CATEGORY_NAMES.values())
    assert set(i18n.DEFAULT_ASSET_TYPE_NAMES) == {"현금", "은행 예금·적금", "주식", "ETF", "기타 금융자산", "기타 자산"}
    assert not any(has_hangul(v) for v in i18n.DEFAULT_ASSET_TYPE_NAMES.values())


# ── AppError ──

def _some_code_with_params():
    code = "reset.invalid_mode"
    params = {p: "x1" for p in placeholders(i18n.MESSAGES[code]["ko"])}
    return code, params


def test_apperror_of_str_code_params():
    code, p = _some_code_with_params()
    e = AppError.of(code, **p)
    assert isinstance(e, ValueError)
    assert str(e) == i18n.tr(code, "ko", **p)
    assert e.code == code and e.params == p


def test_apperror_of_with_params_and_message_en():
    codes = [c for c, t in i18n.MESSAGES.items() if placeholders(t["ko"])]
    for code in codes[:5] or ["reset.invalid_mode"]:
        p = {k: "7" for k in placeholders(i18n.MESSAGES[code]["ko"])}
        e = AppError.of(code, **p)
        assert str(e) == i18n.tr(code, "ko", **p)
        assert e.message("en") == i18n.tr(code, "en", **p)
        assert e.params == p


def test_apperror_message_en():
    code, p = _some_code_with_params()
    assert AppError.of(code, **p).message("en") == i18n.tr(code, "en", **p)


def test_apperror_literal():
    e = AppError("문장")
    assert e.code is None and e.message("en") == "문장" and str(e) == "문장"


def test_parse_amount_error_still_korean():
    from app import util
    with pytest.raises(AppError) as ei:
        util.parse_amount("abc")
    assert has_hangul(str(ei.value))


STATIC_FILES = ["app/util.py", "app/server.py"] + [
    f"app/services/{n}.py" for n in ("records", "categories", "budget", "stats", "backup", "csvio", "settings")]


def test_no_literal_apperror_calls():
    offenders = []
    for rel in STATIC_FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            is_apperror = (isinstance(f, ast.Name) and f.id == "AppError") or \
                          (isinstance(f, ast.Attribute) and f.attr == "AppError")
            if not is_apperror or not node.args:
                continue
            a = node.args[0]
            if (isinstance(a, ast.Constant) and isinstance(a.value, str)) or isinstance(a, ast.JoinedStr):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


# ── 설정 ──

def test_settings_defaults_on_new_db(client):
    s = client.get("/api/settings").json()
    assert s["language"] == "ko" and s["date_format"] == "auto" and s["currency_display"] == "auto"


def test_settings_put_and_get(client):
    r = client.put("/api/settings", json={"language": "en", "date_format": "dot", "currency_display": "code"})
    assert r.status_code == 200, r.text
    s = client.get("/api/settings").json()
    assert (s["language"], s["date_format"], s["currency_display"]) == ("en", "dot", "code")


@pytest.mark.parametrize("body", [{"language": "fr"}, {"date_format": "xyz"}, {"currency_display": "usd"}])
def test_settings_invalid_value(client, body):
    r = client.put("/api/settings", json=body)
    assert r.status_code == 400
    assert r.json()["code"] == "settings.invalid_value"


def test_settings_unknown_key(client):
    r = client.put("/api/settings", json={"nope": "1"})
    assert r.status_code == 400
    assert r.json()["code"] == "settings.unknown_key"


def test_settings_uppercase_value_never_stored_out_of_range(client):
    client.put("/api/settings", json={"language": "EN"})
    assert client.get("/api/settings").json()["language"] in ("ko", "en")


def test_settings_empty_resets_to_default(client):
    client.put("/api/settings", json={"date_format": "dot"})
    client.put("/api/settings", json={"date_format": ""})
    assert client.get("/api/settings").json()["date_format"] == "auto"


def test_settings_service_language_and_display(conn):
    conn.execute("DELETE FROM settings WHERE key='language'"); conn.commit()
    assert app_settings.language(conn) == "ko"
    app_settings.set_many(conn, {"language": "en"})
    assert app_settings.language(conn) == "en"
    d = app_settings.get_display(conn)
    assert set(d) >= {"language", "date_format", "currency_display"}
    assert d["language"] == "en" and d["date_format"] == "auto" and d["currency_display"] == "auto"


# ── 서버 오류 응답 언어 ──

def test_error_ko_reset_invalid_mode(client):
    r = client.post("/api/reset", json={"mode": "x"})
    assert r.status_code == 400
    j = r.json()
    assert j["detail"] == "초기화 방식이 올바르지 않습니다." and j["code"] == "reset.invalid_mode"


def test_error_en_reset_invalid_mode(client):
    set_lang(client, "en")
    r = client.post("/api/reset", json={"mode": "x"})
    assert r.status_code == 400
    j = r.json()
    assert j["code"] == "reset.invalid_mode"
    assert j["detail"] and not has_hangul(j["detail"])


def test_error_en_bad_amount(client):
    food = cat_by_name(client, "식비")
    set_lang(client, "en")
    r = client.put("/api/budget/plan", json={"month": "2026-10", "category_id": food, "amount": "abc"})
    assert r.status_code == 400
    j = r.json()
    assert not has_hangul(j["detail"]) and isinstance(j["code"], str)
    r = client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": "abc", "month": "2026-10"})
    assert r.status_code == 400
    j = r.json()
    assert not has_hangul(j["detail"]) and isinstance(j["code"], str)


def test_error_en_bad_month(client):
    set_lang(client, "en")
    r = client.get("/api/budget", params={"month": "2026-13"})
    assert r.status_code == 400
    assert r.json()["detail"] and not has_hangul(r.json()["detail"])


def test_all_400_responses_have_code_key(client):
    food = cat_by_name(client, "식비")
    responses = [
        client.post("/api/reset", json={"mode": "x"}),
        client.put("/api/settings", json={"nope": "1"}),
        client.put("/api/settings", json={"language": "fr"}),
        client.get("/api/budget", params={"month": "2026-13"}),
        client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": "abc", "month": "2026-10"}),
        client.post("/api/restore-upload", content=b""),
        client.get("/api/templates/nope"),
        client.post("/api/import/records?dry_run=true", content=b""),
    ]
    set_lang(client, "en")
    responses += [client.post("/api/reset", json={"mode": "x"}), client.get("/api/templates/nope")]
    seen = 0
    for r in responses:
        if r.status_code == 400:
            seen += 1
            j = r.json()
            assert "code" in j and (j["code"] is None or isinstance(j["code"], str)), r.text
            assert isinstance(j["detail"], str)
    assert seen >= 6


# ── 새 DB 기본 항목 언어 ──

def _cats(c):
    return {r["name"]: r["kind"] for r in c.execute("SELECT name, kind FROM categories")}


def _setting(c, key):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def test_init_db_en_defaults(tmp_path):
    c = db.init_db(tmp_path / "en.db", lang="en")
    try:
        cats = _cats(c)
        assert set(cats) == set(i18n.DEFAULT_CATEGORY_NAMES.values())
        inc = {i18n.DEFAULT_CATEGORY_NAMES["급여"], i18n.DEFAULT_CATEGORY_NAMES["장학금"]}
        assert {"Salary", "Scholarship"} == inc
        for n, k in cats.items():
            assert k == ("income" if n in inc else "expense"), n
        assert sum(k == "expense" for k in cats.values()) == 9
        assert not any(has_hangul(n) for n in cats)
        types = [r[0] for r in c.execute("SELECT name FROM asset_types")]
        assert types and not any(has_hangul(n) for n in types)
        assert _setting(c, "language") == "en"
    finally:
        c.close()


def test_init_db_ko_defaults(tmp_path):
    c = db.init_db(tmp_path / "ko.db", lang="ko")
    try:
        cats = _cats(c)
        assert set(cats) == set(i18n.DEFAULT_CATEGORY_NAMES.keys())
        assert cats["급여"] == "income" and cats["장학금"] == "income"
        assert _setting(c, "language") == "ko"
    finally:
        c.close()


def test_init_db_follows_system_language(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_MANAGER_LANG", "en")
    c = db.init_db(tmp_path / "sys.db")
    try:
        assert set(_cats(c)) == set(i18n.DEFAULT_CATEGORY_NAMES.values())
    finally:
        c.close()


def test_init_db_existing_db_unchanged(tmp_path):
    p = tmp_path / "exist.db"
    c = db.init_db(p, lang="ko")
    before = _cats(c)
    c.close()
    c = db.init_db(p, lang="en")
    try:
        assert _cats(c) == before
        assert "식비" in _cats(c)
        assert _setting(c, "language") == "ko"
    finally:
        c.close()


def test_schema_version_unchanged():
    assert db.SCHEMA_VERSION == 6


def test_system_language(monkeypatch):
    monkeypatch.setenv("ASSET_MANAGER_LANG", "en")
    assert config.system_language() == "en"
    monkeypatch.setenv("ASSET_MANAGER_LANG", "ko")
    assert config.system_language() == "ko"
    monkeypatch.delenv("ASSET_MANAGER_LANG", raising=False)
    assert config.system_language() in ("ko", "en")


# ── 전체 초기화 ──

def test_reset_all_en_keeps_display_settings(client):
    r = client.put("/api/settings", json={"language": "en", "date_format": "dot", "currency_display": "code",
                                          "ecos_api_key": "ABCDEFGH12345"})
    assert r.status_code == 200, r.text
    assert client.get("/api/settings").json()["ecos_api_key_set"] is True
    client.post("/api/categories", json={"name": "MyCustom", "kind": "expense"})
    r = client.post("/api/reset", json={"mode": "all"})
    assert r.status_code == 200, r.text
    cats = [c for c in client.get("/api/categories").json() if not c.get("parent_id")]
    names = [c["name"] for c in cats]
    assert set(names) == set(i18n.DEFAULT_CATEGORY_NAMES.values()) and len(names) == 11
    s = client.get("/api/settings").json()
    assert (s["language"], s["date_format"], s["currency_display"]) == ("en", "dot", "code")
    assert s["ecos_api_key_set"] is False


def test_reset_all_ko_defaults(client):
    client.post("/api/categories", json={"name": "MyCustom", "kind": "expense"})
    assert client.post("/api/reset", json={"mode": "all"}).status_code == 200
    names = {c["name"] for c in client.get("/api/categories").json()}
    assert set(i18n.DEFAULT_CATEGORY_NAMES.keys()) <= names and "MyCustom" not in names
    assert client.get("/api/settings").json()["language"] == "ko"


# ── CSV ──

def test_record_columns():
    assert csvio.RECORD_COLUMNS["ko"] == KO_COLS
    assert csvio.RECORD_COLUMNS["en"] == EN_COLS


def _seed_three_kinds(client):
    sal = cat_by_name(client, "급여")
    food = cat_by_name(client, "식비")
    assert client.post("/api/records", json={"kind": "income", "category_id": sal, "amount": 3000000,
                                             "month": "2026-10", "txn_date": "2026-10-25"}).status_code == 200
    assert client.put("/api/budget/plan", json={"month": "2026-10", "category_id": food,
                                                "amount": 300000}).status_code == 200
    assert client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 12345,
                                             "month": "2026-10", "txn_date": "2026-10-03"}).status_code == 200


def test_export_records_ko(client):
    _seed_three_kinds(client)
    rows = rows_of(client.get("/api/export/records").content)
    assert rows[0] == KO_COLS
    assert {r[0] for r in rows[1:]} == {"수입", "지출계획", "실제지출"}


def test_export_records_en(client):
    _seed_three_kinds(client)
    set_lang(client, "en")
    rows = rows_of(client.get("/api/export/records").content)
    assert rows[0] == EN_COLS
    body = rows[1:]
    assert {r[0] for r in body} == {"Income", "Plan", "Expense"}
    for r in body:
        assert re.fullmatch(r"-?\d+", r[3]), r
        assert re.fullmatch(r"\d{4}-\d{2}", r[4]), r
        for d in (r[5], r[6]):
            assert d == "" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", d), r
    assert any(r[5] == "2026-10-03" and r[3] == "12345" for r in body)


def test_export_categories_en(client):
    set_lang(client, "en")
    rows = rows_of(client.get("/api/export/categories").content)
    assert rows[0] == ["Kind", "Category"]
    assert {r[0] for r in rows[1:]} == {"Income", "Expense"}


def test_template_records_lang():
    en = rows_of(csvio.template("records", "en"))
    assert en[0] == EN_COLS
    assert len(en) > 1 and not any(has_hangul(c) for r in en[1:] for c in r)
    assert rows_of(csvio.template("records"))[0] == KO_COLS


def test_template_api_en(client):
    set_lang(client, "en")
    r = client.get("/api/templates/records")
    assert r.status_code == 200
    assert rows_of(r.content)[0] == EN_COLS


def test_template_unknown_code():
    with pytest.raises(AppError) as ei:
        csvio.template("nope")
    assert ei.value.code == "csv.unknown_template"


def test_import_en_csv_into_ko_db(conn):
    text = ("Type,Category,Item,Amount,Month\n"
            "Income,Salary,,1000,2026-10\nPlan,Food,,500,2026-10\nExpense,Food,Mart,200,2026-10\n")
    res = csvio.import_records(conn, text.encode("utf-8"), dry_run=False, create_missing=True)
    assert res["ok"], res
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3


def test_import_en_header_case_insensitive(conn):
    text = "TYPE,category,AMOUNT,month\nIncome,Salary,1000,2026-10\n"
    res = csvio.import_records(conn, text.encode("utf-8"), dry_run=False, create_missing=True)
    assert res["ok"], res
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_import_ko_csv_into_en_db(tmp_path):
    c = db.init_db(tmp_path / "en.db", lang="en")
    try:
        text = "구분,항목,금액,월\n수입,급여,1000,2026-10\n실제지출,식비,500,2026-10\n"
        res = csvio.import_records(c, text.encode("utf-8"), dry_run=False, create_missing=True)
        assert res["ok"], res
        assert c.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2
    finally:
        c.close()


def test_csv_roundtrip_en_export_to_ko_db(client, tmp_path):
    _seed_three_kinds(client)
    set_lang(client, "en")
    data = client.get("/api/export/records").content
    body = rows_of(data)[1:]
    c = db.init_db(tmp_path / "ko_new.db", lang="ko")
    try:
        res = csvio.import_records(c, data, dry_run=False, create_missing=True)
        assert res["ok"], res
        n, total = c.execute("SELECT COUNT(*), IFNULL(SUM(amount),0) FROM records WHERE amount <> 0").fetchone()
        assert n == len(body) and total == sum(int(r[3]) for r in body)
    finally:
        c.close()


def test_import_row_error_language(conn):
    text = "Type,Category,Amount,Month\nExpense,NoSuchCategory,500,2026-10\n"
    ko = csvio.import_records(conn, text.encode("utf-8"), dry_run=True, create_missing=False)
    assert not ko["ok"] and has_hangul(ko["errors"][0]["message"])
    assert "지출 항목 'NoSuchCategory'이(가) 없습니다" in ko["errors"][0]["message"]
    app_settings.set_many(conn, {"language": "en"})
    en = csvio.import_records(conn, text.encode("utf-8"), dry_run=True, create_missing=False)
    assert not en["ok"] and en["errors"]
    assert all(not has_hangul(e["message"]) for e in en["errors"])


def test_import_empty_file_en(client):
    set_lang(client, "en")
    r = client.post("/api/import/records?dry_run=true", content=b"")
    if r.status_code == 400:
        j = r.json()
        assert j["code"] == "csv.empty_file" and not has_hangul(j["detail"])
    else:
        j = r.json()
        assert not j.get("ok") and "csv.empty_file" in r.text and not has_hangul(r.text)


# ── 프런트엔드 문법 ──

@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
@pytest.mark.parametrize("rel", ["app/static/js/i18n.js", "app/static/js/lib.js", "app/static/js/app.js",
                                 "app/static/js/pages/settings.js"])
def test_js_syntax(rel):
    p = ROOT / rel
    assert p.exists(), rel
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
