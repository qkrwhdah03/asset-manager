# 영어·언어 설정 제거(loop 2026-10-21-004). 화면·서버 문구는 한국어 하나, 표시 설정은 날짜 표기·금액 단위만 남는다.
import ast
import csv
import importlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

from app import db
from app.services import csvio
from app.services import settings as app_settings
from app.util import AppError

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
JS = APP / "static" / "js"
HANGUL = re.compile(r"[가-힣]")
M = "2026-10"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node 없음")

KO_COLS = ["구분", "항목", "세부항목", "금액", "월", "거래일", "결제일", "예산월", "메모"]
DEFAULT_CATS = {"급여", "장학금", "식비", "교통비", "주거·관리비", "통신비", "구독료", "취미", "의료비", "기타", "저축·투자"}
DEFAULT_ASSET_TYPES = {"현금", "은행 예금·적금", "주식", "ETF", "기타 금융자산", "기타 자산"}
SCENARIO_MEMOS = ["계획 옮기기(보냄)", "계획 옮기기(받음)", "미배분에서 추가", "월말 정산(계획 조정)", "월말 정산(남은 돈)"]
USER_MEMO = "사용자 메모"


def has_hangul(s) -> bool:
    return bool(HANGUL.search(str(s)))


def rows_of(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def cat_by_name(client, name):
    return next(c for c in client.get("/api/categories").json() if c["name"] == name)["id"]


def put_raw_setting(path, key, value):
    """옛 DB 행을 흉내 낸다(앱을 거치지 않고 직접 넣음)."""
    c = sqlite3.connect(str(path))
    try:
        c.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))
        c.commit()
    finally:
        c.close()


def raw_setting(path_or_conn, key):
    if isinstance(path_or_conn, sqlite3.Connection):
        r = path_or_conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else None
    c = sqlite3.connect(str(path_or_conn))
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else None
    finally:
        c.close()


@pytest.fixture
def en_client(client, tmp_path):
    """옛 영어 설정 행(language='en')이 남아 있는 DB 의 client."""
    put_raw_setting(tmp_path / "api.db", "language", "en")
    return client


# ── 1~3. 서버 모듈 ──

def test_i18n_module_removed():
    assert not (APP / "i18n.py").exists()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.i18n")


def test_messages_values_are_str():
    from app import messages
    assert messages.MESSAGES
    for code, v in messages.MESSAGES.items():
        assert isinstance(v, str), code
        assert v.strip(), code


def test_messages_text_value_required():
    from app import messages
    assert messages.text("value.required", field="금액", value="") == "금액을(를) 입력하세요."


def test_messages_text_unknown_code_keyerror():
    from app import messages
    with pytest.raises(KeyError):
        messages.text("없는.코드")


def test_messages_fixed_codes_exist():
    from app import messages
    for code in ["reset.invalid_mode", "settings.unknown_key", "settings.invalid_value", "csv.empty_file",
                 "csv.unknown_template", "csv.missing_columns", "db.foreign_key", "db.unique", "db.integrity",
                 "db.operational", "http.forbidden", "value.month_format", "record.not_found"]:
        assert code in messages.MESSAGES, code
    assert messages.MESSAGES["http.forbidden"] == "허용되지 않은 요청입니다."


def test_apperror_of_record_not_found():
    e = AppError.of("record.not_found")
    assert isinstance(e, ValueError)
    assert str(e) == "기록을 찾을 수 없습니다."
    assert e.code == "record.not_found"
    assert e.params == {}


def test_apperror_of_params_match_messages_text():
    from app import messages
    e = AppError.of("value.required", field="금액")
    assert str(e) == messages.text("value.required", field="금액") == "금액을(를) 입력하세요."
    assert e.code == "value.required" and e.params == {"field": "금액"}


def test_apperror_has_no_message_method():
    assert not hasattr(AppError, "message")
    assert not callable(getattr(AppError.of("record.not_found"), "message", None))


def test_apperror_literal():
    e = AppError("문장")
    assert e.code is None and str(e) == "문장"


def test_parse_amount_error_korean():
    from app import util
    with pytest.raises(AppError) as ei:
        util.parse_amount("abc")
    assert has_hangul(str(ei.value))


# ── 4~8. 설정 ──

def test_settings_module_constants():
    assert app_settings.DEFAULTS == {"date_format": "ko", "currency_display": "won"}
    assert "language" not in app_settings.ALLOWED
    assert tuple(app_settings.ALLOWED["date_format"]) == ("iso", "dot", "ko", "en")
    assert tuple(app_settings.ALLOWED["currency_display"]) == ("won", "symbol", "code")


def test_settings_defaults_on_new_db(client):
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    s = r.json()
    assert "language" not in s
    assert s["date_format"] == "ko" and s["currency_display"] == "won"


def test_settings_put_language_rejected(client):
    r = client.put("/api/settings", json={"language": "en"})
    assert r.status_code == 400
    j = r.json()
    assert j["code"] == "settings.unknown_key"
    assert has_hangul(j["detail"])
    assert "language" not in client.get("/api/settings").json()


def test_settings_put_language_with_valid_key_rolls_back(client, tmp_path):
    r = client.put("/api/settings", json={"date_format": "dot", "language": "en"})
    assert r.status_code == 400
    assert r.json()["code"] == "settings.unknown_key"
    assert client.get("/api/settings").json()["date_format"] == "ko"
    assert raw_setting(tmp_path / "api.db", "language") is None


@pytest.mark.parametrize("body", [{"date_format": "auto"}, {"currency_display": "auto"},
                                  {"date_format": "xyz"}, {"currency_display": "usd"}])
def test_settings_auto_and_bad_values_rejected(client, body):
    r = client.put("/api/settings", json=body)
    assert r.status_code == 400
    j = r.json()
    assert j["code"] == "settings.invalid_value"
    assert has_hangul(j["detail"])


def test_settings_unknown_key(client):
    r = client.put("/api/settings", json={"nope": "1"})
    assert r.status_code == 400
    assert r.json()["code"] == "settings.unknown_key"


@pytest.mark.parametrize("key,value", [("date_format", v) for v in ("iso", "dot", "ko", "en")]
                         + [("currency_display", v) for v in ("won", "symbol", "code")])
def test_settings_valid_values_saved(client, key, value):
    r = client.put("/api/settings", json={key: value})
    assert r.status_code == 200, r.text
    assert client.get("/api/settings").json()[key] == value


@pytest.mark.parametrize("key,value,default", [("date_format", "dot", "ko"), ("currency_display", "code", "won")])
def test_settings_empty_resets_to_default(client, key, value, default):
    assert client.put("/api/settings", json={key: value}).status_code == 200
    assert client.put("/api/settings", json={key: ""}).status_code == 200
    assert client.get("/api/settings").json()[key] == default


@pytest.mark.parametrize("key,value", [("language", "en"), ("date_format", "auto"), ("currency_display", "auto"),
                                       ("date_format", "xx")])
def test_settings_old_rows_ignored(client, tmp_path, key, value):
    put_raw_setting(tmp_path / "api.db", key, value)
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    s = r.json()
    assert "language" not in s
    assert s["date_format"] == "ko" and s["currency_display"] == "won"


def test_settings_all_old_rows_together(client, tmp_path):
    p = tmp_path / "api.db"
    for k, v in (("language", "en"), ("date_format", "auto"), ("currency_display", "auto")):
        put_raw_setting(p, k, v)
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    s = r.json()
    assert "language" not in s and (s["date_format"], s["currency_display"]) == ("ko", "won")


def test_settings_service_get_display(conn):
    conn.execute("INSERT INTO settings (key, value) VALUES ('language','en') "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    conn.commit()
    d = app_settings.get_display(conn)
    assert "language" not in d
    assert d["date_format"] == "ko" and d["currency_display"] == "won"
    app_settings.set_many(conn, {"date_format": "iso", "currency_display": "symbol"})
    d = app_settings.get_display(conn)
    assert (d["date_format"], d["currency_display"]) == ("iso", "symbol")
    assert "language" not in app_settings.get_public(conn)


# ── 9~13. 옛 language='en' 행이 있어도 한국어 ──

def test_en_row_month_format_error_korean(en_client):
    r = en_client.get("/api/budget", params={"month": "abc"})
    assert r.status_code == 400
    j = r.json()
    assert j["code"] == "value.month_format"
    assert "형식이 올바르지 않습니다" in j["detail"]


def test_en_row_month_invalid_error_korean(en_client):
    r = en_client.get("/api/budget", params={"month": "2026-13"})
    assert r.status_code == 400
    j = r.json()
    assert isinstance(j["code"], str) and j["code"].startswith("value.")
    assert has_hangul(j["detail"])


def test_en_row_other_errors_korean(en_client):
    food = cat_by_name(en_client, "식비")
    responses = [
        en_client.post("/api/reset", json={"mode": "x"}),
        en_client.put("/api/budget/plan", json={"month": M, "category_id": food, "amount": "abc"}),
        en_client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": "abc", "month": M}),
        en_client.get("/api/templates/nope"),
    ]
    for r in responses:
        assert r.status_code == 400, r.text
        j = r.json()
        assert isinstance(j["code"], str), r.text
        assert has_hangul(j["detail"]), r.text
    assert responses[0].json() == {"detail": "초기화 방식이 올바르지 않습니다.", "code": "reset.invalid_mode"}


def _raw_client(client):
    from fastapi.testclient import TestClient
    return TestClient(client.app)  # X-Requested-With 헤더 없음


def test_csrf_forbidden_korean(client):
    r = _raw_client(client).post("/api/reset", json={"mode": "x"})
    assert r.status_code == 403
    assert r.json() == {"detail": "허용되지 않은 요청입니다.", "code": "http.forbidden"}


def test_en_row_csrf_forbidden_korean(en_client):
    raw = _raw_client(en_client)
    for r in (raw.post("/api/reset", json={"mode": "x"}), raw.put("/api/settings", json={"date_format": "dot"})):
        assert r.status_code == 403
        assert r.json() == {"detail": "허용되지 않은 요청입니다.", "code": "http.forbidden"}
    assert en_client.get("/api/settings").json()["date_format"] == "ko"


def _scenario(client):
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
    ok(client.post("/api/budget/settle", json={"month": M, "category_id": save}))
    return {"food": food, "hobby": hobby, "save": save, "sal": sal}


def _db_rows(tmp_path):
    c = sqlite3.connect(str(tmp_path / "api.db"))
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute("SELECT id, kind, item, memo, tag FROM records ORDER BY id")]
    finally:
        c.close()


def _budget_items(b):
    return [i for e in b["envelopes"] for i in e["items"]]


def test_en_row_system_records_stored_korean(en_client, tmp_path):
    ids = _scenario(en_client)
    stored = {r["id"]: (r["item"], r["memo"]) for r in _db_rows(tmp_path)}
    assert set(SCENARIO_MEMOS) <= {m for _, m in stored.values()}
    rows = []
    for cid in (ids["food"], ids["hobby"], ids["save"]):
        r = en_client.get("/api/records", params={"category_id": cid, "month": M})
        assert r.status_code == 200, r.text
        rows += r.json()
    tagged = [r for r in rows if r.get("tag")]
    assert tagged
    for r in rows:
        assert (r["item"], r["memo"]) == stored[r["id"]], r
    assert set(SCENARIO_MEMOS) <= {r["memo"] for r in tagged}
    b = en_client.get("/api/budget", params={"month": M})
    assert b.status_code == 200, b.text
    items = _budget_items(b.json())
    for i in items:
        assert (i["item"], i["memo"]) == stored[i["id"]], i
    settle = [i for i in items if i["tag"] == "settle"]
    assert settle and settle[0]["item"] == "월말 정산" and settle[0]["memo"] == "월말 정산(남은 돈)"


@pytest.mark.parametrize("basis,label", [("budget", "예산 월 기준"), ("cash", "입금·결제일 기준")])
def test_en_row_stats_basis_label(en_client, basis, label):
    r = en_client.get("/api/stats/summary", params={"month": M, "basis": basis})
    assert r.status_code == 200, r.text
    assert r.json()["basis_label"] == label


def test_en_row_short_secret_display(en_client):
    r = en_client.put("/api/settings", json={"ecos_api_key": "abc123"})
    assert r.status_code == 200, r.text
    s = en_client.get("/api/settings").json()
    assert s["ecos_api_key"] == "설정됨" and s["ecos_api_key_set"] is True


def test_long_secret_display_unchanged(client):
    client.put("/api/settings", json={"ecos_api_key": "ABCDEFGH12345"})
    assert client.get("/api/settings").json()["ecos_api_key"] == "ABC…45"


# ── 14~16. 새 DB·초기화 ──

def _cat_names(c):
    return {r[0] for r in c.execute("SELECT name FROM categories")}


def _asset_type_names(c):
    return {r[0] for r in c.execute("SELECT name FROM asset_types")}


@pytest.mark.parametrize("env", ["en", "xx", "ko", None])
def test_new_db_korean_defaults_regardless_of_env(tmp_path, monkeypatch, env):
    if env is None:
        monkeypatch.delenv("ASSET_MANAGER_LANG", raising=False)
    else:
        monkeypatch.setenv("ASSET_MANAGER_LANG", env)
    c = db.init_db(tmp_path / "new.db")
    try:
        assert _cat_names(c) == DEFAULT_CATS
        kinds = {r[0]: r[1] for r in c.execute("SELECT name, kind FROM categories")}
        assert kinds["급여"] == "income" and kinds["장학금"] == "income" and kinds["식비"] == "expense"
        assert _asset_type_names(c) == DEFAULT_ASSET_TYPES
        assert raw_setting(c, "language") is None
    finally:
        c.close()


def test_new_db_via_app_with_env_en(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_MANAGER_LANG", "en")
    from fastapi.testclient import TestClient
    from app.server import create_app
    with TestClient(create_app(tmp_path / "envapp.db"), headers={"X-Requested-With": "asset-manager"}) as c:
        names = {x["name"] for x in c.get("/api/categories").json()}
        assert DEFAULT_CATS <= names
        s = c.get("/api/settings").json()
        assert "language" not in s and (s["date_format"], s["currency_display"]) == ("ko", "won")
    assert raw_setting(tmp_path / "envapp.db", "language") is None


def test_init_db_rejects_lang_kwarg(tmp_path):
    with pytest.raises(TypeError):
        db.init_db(tmp_path / "x.db", lang="en")


def test_migrate_rejects_lang_kwarg(tmp_path):
    p = tmp_path / "m.db"
    c = db.init_db(p)
    try:
        assert db.migrate(c, p) == db.get_version(c)
        with pytest.raises(TypeError):
            db.migrate(c, p, lang="en")
    finally:
        c.close()


def test_migrate_without_lang_on_fresh_connection(tmp_path):
    p = tmp_path / "fresh.db"
    c = db.connect(p)
    try:
        db.migrate(c, p)
        assert DEFAULT_CATS <= _cat_names(c)
        assert raw_setting(c, "language") is None
    finally:
        c.close()


def test_existing_english_default_names_untouched(tmp_path):
    p = tmp_path / "old_en.db"
    c = db.init_db(p)
    c.execute("UPDATE categories SET name='Salary' WHERE name='급여'")
    c.execute("UPDATE categories SET name='Food' WHERE name='식비'")
    c.execute("UPDATE asset_types SET name='Cash' WHERE name='현금'")
    c.execute("INSERT INTO settings (key, value) VALUES ('language','en')")
    c.commit()
    before = (_cat_names(c), _asset_type_names(c))
    c.close()
    c = db.init_db(p)
    try:
        db.migrate(c, p)
        assert (_cat_names(c), _asset_type_names(c)) == before
        assert {"Salary", "Food"} <= _cat_names(c) and "Cash" in _asset_type_names(c)
        assert raw_setting(c, "language") == "en"  # 옛 행은 지우지 않는다
    finally:
        c.close()
    from fastapi.testclient import TestClient
    from app.server import create_app
    with TestClient(create_app(p), headers={"X-Requested-With": "asset-manager"}) as cl:
        names = {x["name"] for x in cl.get("/api/categories").json()}
        assert {"Salary", "Food"} <= names and "급여" not in names
        assert "language" not in cl.get("/api/settings").json()


def test_reset_all_keeps_display_settings(client, tmp_path):
    r = client.put("/api/settings", json={"date_format": "dot", "currency_display": "code",
                                          "ecos_api_key": "ABCDEFGH12345"})
    assert r.status_code == 200, r.text
    client.post("/api/categories", json={"name": "MyCustom", "kind": "expense"})
    r = client.post("/api/reset", json={"mode": "all"})
    assert r.status_code == 200, r.text
    cats = [c for c in client.get("/api/categories").json() if not c.get("parent_id")]
    names = {c["name"] for c in cats}
    assert names == DEFAULT_CATS and len(cats) == 11
    s = client.get("/api/settings").json()
    assert "language" not in s
    assert (s["date_format"], s["currency_display"]) == ("dot", "code")
    assert s["ecos_api_key_set"] is False
    assert raw_setting(tmp_path / "api.db", "language") is None


def test_reset_all_with_env_en(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_MANAGER_LANG", "en")
    assert client.post("/api/reset", json={"mode": "all"}).status_code == 200
    names = {c["name"] for c in client.get("/api/categories").json()}
    assert DEFAULT_CATS <= names
    assert raw_setting(tmp_path / "api.db", "language") is None


# ── 17~22. CSV ──

def test_record_columns_constant():
    assert csvio.RECORD_COLUMNS == KO_COLS


def _seed_three_kinds(client):
    sal = cat_by_name(client, "급여")
    food = cat_by_name(client, "식비")
    assert client.post("/api/records", json={"kind": "income", "category_id": sal, "amount": 3000000,
                                             "month": M, "txn_date": "2026-10-25"}).status_code == 200
    assert client.put("/api/budget/plan", json={"month": M, "category_id": food,
                                                "amount": 300000}).status_code == 200
    assert client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 12345,
                                             "month": M, "txn_date": "2026-10-03"}).status_code == 200


def test_export_records_korean(client):
    _seed_three_kinds(client)
    rows = rows_of(client.get("/api/export/records").content)
    assert rows[0] == KO_COLS
    assert {r[0] for r in rows[1:]} == {"수입", "지출계획", "실제지출"}


def test_en_row_export_records_korean(en_client):
    _seed_three_kinds(en_client)
    r = en_client.get("/api/export/records")
    assert r.status_code == 200, r.text
    rows = rows_of(r.content)
    assert rows[0] == KO_COLS
    assert {x[0] for x in rows[1:]} == {"수입", "지출계획", "실제지출"}


def test_en_row_export_memos_stored(en_client):
    _scenario(en_client)
    memos = {r[8] for r in rows_of(en_client.get("/api/export/records").content)[1:]}
    assert set(SCENARIO_MEMOS) <= memos and USER_MEMO in memos


@pytest.mark.parametrize("lang_row", [False, True])
def test_export_categories_korean(client, tmp_path, lang_row):
    if lang_row:
        put_raw_setting(tmp_path / "api.db", "language", "en")
    rows = rows_of(client.get("/api/export/categories").content)
    assert rows[0] == ["종류", "항목"]
    assert {r[0] for r in rows[1:]} == {"소득", "지출"}


def test_template_records_one_arg():
    rows = rows_of(csvio.template("records"))
    assert rows[0] == KO_COLS
    assert len(rows) > 1


def test_template_unknown_code():
    with pytest.raises(AppError) as ei:
        csvio.template("nope")
    assert ei.value.code == "csv.unknown_template"


@pytest.mark.parametrize("lang_row", [False, True])
def test_template_api_korean(client, tmp_path, lang_row):
    if lang_row:
        put_raw_setting(tmp_path / "api.db", "language", "en")
    r = client.get("/api/templates/records")
    assert r.status_code == 200, r.text
    assert rows_of(r.content)[0] == KO_COLS


def _fname(r) -> str:
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    assert m, cd
    return unquote(m.group(1))


@pytest.mark.parametrize("lang_row", [False, True])
def test_csv_download_filenames_korean(client, tmp_path, lang_row):
    if lang_row:
        put_raw_setting(tmp_path / "api.db", "language", "en")
    assert re.fullmatch(r"수입지출기록_\d{8}\.csv", _fname(client.get("/api/export/records")))
    assert re.fullmatch(r"항목_\d{8}\.csv", _fname(client.get("/api/export/categories")))
    assert re.fullmatch(r"양식_records_\d{8}\.csv", _fname(client.get("/api/templates/records")))


@pytest.mark.parametrize("lang_row", [False, True])
def test_csv_saved_filenames_korean(client, tmp_path, lang_row):
    if lang_row:
        put_raw_setting(tmp_path / "api.db", "language", "en")
    cases = [("/api/export/records", r"수입지출기록_.+\.csv"), ("/api/export/categories", r"항목_.+\.csv"),
             ("/api/templates/records", r"양식_records_.+\.csv")]
    for path, pat in cases:
        r = client.get(path, params={"save": "true"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["saved"] is True
        name = Path(j["path"]).name
        assert re.fullmatch(pat, name), name
        assert Path(j["path"]).exists()


def test_import_english_columns_rejected(client):
    text = "Type,Category,Item,Amount,Month\nIncome,Salary,,1000,2026-10\n"
    r = client.post("/api/import/records?dry_run=true&create_missing=true", content=text.encode("utf-8"))
    assert r.status_code == 400, r.text
    j = r.json()
    assert j["code"] == "csv.missing_columns"
    assert "구분" in j["detail"]


def test_import_english_columns_rejected_service(conn):
    text = "Type,Category,Item,Amount,Month\nIncome,Salary,,1000,2026-10\n"
    with pytest.raises(AppError) as ei:
        csvio.import_records(conn, text.encode("utf-8"), dry_run=False, create_missing=True)
    assert ei.value.code == "csv.missing_columns"
    assert "구분" in str(ei.value)
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def test_import_korean_csv_preview_and_apply(client):
    text = ("구분,항목,세부항목,금액,월\n"
            "수입,급여,,1000,2026-10\n지출계획,식비,,500,2026-10\n실제지출,식비,마트,200,2026-10\n")
    data = text.encode("utf-8")
    pre = client.post("/api/import/records?dry_run=true", content=data)
    assert pre.status_code == 200, pre.text
    pj = pre.json()
    assert pj["ok"] and pj["total"] == 3 and pj["applied"] is False
    app = client.post("/api/import/records?dry_run=false", content=data)
    assert app.status_code == 200, app.text
    aj = app.json()
    assert aj["ok"] and aj["applied"] is True
    recs = client.get("/api/records", params={"month": M}).json()
    assert {"income", "plan", "expense"} <= {r["kind"] for r in recs}


def test_csv_roundtrip_export_import(client, tmp_path):
    _seed_three_kinds(client)
    data = client.get("/api/export/records").content
    body = rows_of(data)[1:]
    c = db.init_db(tmp_path / "rt.db")
    try:
        res = csvio.import_records(c, data, dry_run=False, create_missing=True)
        assert res["ok"], res
        n, total = c.execute("SELECT COUNT(*), IFNULL(SUM(amount),0) FROM records WHERE amount <> 0").fetchone()
        assert n == len(body) and total == sum(int(r[3]) for r in body)
    finally:
        c.close()


@pytest.mark.parametrize("lang_row", [False, True])
def test_import_row_error_korean(conn, lang_row):
    if lang_row:
        conn.execute("INSERT INTO settings (key, value) VALUES ('language','en') "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        conn.commit()
    text = "구분,항목,금액,월\n실제지출,NoSuchCategory,500,2026-10\n"
    res = csvio.import_records(conn, text.encode("utf-8"), dry_run=True, create_missing=False)
    assert not res["ok"] and res["errors"]
    msg = res["errors"][0]["message"]
    assert "지출 항목 'NoSuchCategory'이(가) 없습니다" in msg


def test_import_empty_file_korean(client):
    r = client.post("/api/import/records?dry_run=true", content=b"")
    assert r.status_code == 400, r.text
    j = r.json()
    assert j["code"] == "csv.empty_file" and has_hangul(j["detail"])


# ── 23~27. 정적 검사(소스) ──

def _js_files():
    return sorted(p for p in JS.rglob("*.js") if "vendor" not in p.relative_to(JS).parts)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_i18n_js_removed():
    assert not (JS / "i18n.js").exists()


def test_js_files_found():
    rels = {p.relative_to(JS).as_posix() for p in _js_files()}
    assert {"lib.js", "app.js", "pages/settings.js", "pages/cashflow.js", "pages/dashboard.js",
            "pages/move.js"} <= rels


T_IMPORT = re.compile(r"(?:import|export)\s*\{([^}]*)\}\s*from\s*[\"'][^\"']+[\"']")
T_EXPORT = re.compile(r"export\s*\{([^}]*)\}\s*;")
T_KEY_CALL = re.compile(r"(?<![\w$.])t\(\s*[\"'`][a-z]+\.[\w.]+[\"'`]")


def _names(group: str) -> set[str]:
    out = set()
    for part in group.split(","):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(" as ")]
        out.update(bits)
    return out


@pytest.mark.parametrize("rel", [p.relative_to(JS).as_posix() for p in _js_files()] or ["lib.js"])
def test_js_no_i18n_traces(rel):
    src = (JS / rel).read_text(encoding="utf-8")
    assert "i18n" not in src, f"{rel}: 'i18n' 글자"
    assert "setLocale" not in src, rel
    assert "getLocale" not in src, rel
    for m in list(T_IMPORT.finditer(src)) + list(T_EXPORT.finditer(src)):
        assert "t" not in _names(m.group(1)), f"{rel}: t import/export — {m.group(0)[:80]}"
    bad = [m.group(0) for m in T_KEY_CALL.finditer(src)]
    assert bad == [], f"{rel}: t(\"키\") 호출 {bad[:5]}"


def test_py_no_i18n_traces():
    words = ("i18n", "system_language", "ASSET_MANAGER_LANG", "system_text")
    offenders = []
    for p in sorted(APP.rglob("*.py")):
        src = p.read_text(encoding="utf-8")
        for w in words:
            if w in src:
                offenders.append(f"{_rel(p)}: {w}")
    assert offenders == []


def test_settings_js_no_language_auto_english():
    src = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
    for w in ('"language"', "'language'", '"auto"', "'auto'", "English"):
        assert w not in src, w


def test_cashflow_js_no_saving_invest():
    src = (JS / "pages" / "cashflow.js").read_text(encoding="utf-8")
    assert "saving" not in src
    assert "invest" not in src


UI_LITERALS = [
    ("app.js", "개인 자산 관리"),
    ("app.js", "설정 및 데이터"),
    ("pages/cashflow.js", "지난달 불러오기"),
    ("pages/cashflow.js", "월말 정산"),
    ("pages/cashflow.js", "칸을 벗어나면 자동 저장되고"),
    ("pages/settings.js", "설정 및 데이터 관리"),
    ("pages/settings.js", "표시 설정을 저장했습니다."),
    ("pages/settings.js", "날짜 표기"),
    ("pages/settings.js", "금액 단위"),
    ("pages/dashboard.js", "저축액"),
    ("pages/dashboard.js", "실제 지출"),
    ("pages/move.js", "옮길 기록을 고르세요."),
    ("pages/move.js", "전체 선택"),
    ("lib.js", "불러오는 중…"),
]


@pytest.mark.parametrize("rel,text", UI_LITERALS, ids=[f"{r}:{t}" for r, t in UI_LITERALS])
def test_ui_korean_literals_present(rel, text):
    assert text in (JS / rel).read_text(encoding="utf-8")


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


@needs_node
@pytest.mark.parametrize("rel", ["lib.js", "app.js"] + sorted(f"pages/{p.name}" for p in (JS / "pages").glob("*.js")))
def test_js_syntax(rel):
    p = JS / rel
    assert p.exists(), rel
    r = subprocess.run([NODE, "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


# ── 29~33. lib.js 포맷(node 실행) ──

PREACT_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*[\"']/vendor/preact-htm\.module\.js[\"']")

DEFAULT_CASES = [
    ("monthLabel", ["2026-10"], "2026년 10월"),
    ("dateLabel", ["2026-10-21"], "2026년 10월 21일"),
    ("won", [1234000], "1,234,000원"),
    ("won", [-1234], "-1,234원"),
    ("yearLabel", [2026], "2026년"),
    ("monthShort", ["2026-10"], "10월"),
    ("shortWon", [150000000], "1.5억"),
    ("shortWon", [30000], "3만"),
    ("won", [0], "0원"),
    ("won", [None], "–"),
    ("monthLabel", [""], ""),
    ("dateLabel", [""], ""),
]

FORMAT_CASES = (
    [({}, fn, args, exp) for fn, args, exp in DEFAULT_CASES]
    + [({"date_format": "auto", "currency_display": "auto"}, fn, args, exp) for fn, args, exp in DEFAULT_CASES]
    + [
        ({"date_format": "iso"}, "monthLabel", ["2026-10"], "2026-10"),
        ({"date_format": "iso"}, "monthShort", ["2026-03"], "3월"),
        ({"date_format": "iso"}, "yearLabel", [2026], "2026"),
        ({"date_format": "dot"}, "dateLabel", ["2026-10-21"], "2026.10.21"),
        ({"date_format": "dot"}, "monthShort", ["2026-03"], "3월"),
        ({"date_format": "dot"}, "monthShort", ["2026-10"], "10월"),
        ({"date_format": "en"}, "dateLabel", ["2026-10-21"], "Oct 21, 2026"),
        ({"date_format": "en"}, "monthLabel", ["2026-10"], "Oct 2026"),
        ({"date_format": "en"}, "monthShort", ["2026-10"], "Oct"),
        ({"date_format": "en"}, "dateTimeLabel", ["2026-10-21T09:05:33"], "Oct 21, 2026 09:05"),
        ({"currency_display": "symbol"}, "won", [1234000], "₩1,234,000"),
        ({"currency_display": "symbol"}, "won", [-1234], "-₩1,234"),
        ({"currency_display": "code"}, "won", [1234000], "KRW 1,234,000"),
        ({"date_format": "xx", "currency_display": "usd"}, "monthLabel", ["2026-10"], "2026년 10월"),
        ({"date_format": "xx", "currency_display": "usd"}, "won", [1234000], "1,234,000원"),
        ({}, "parseMoney", ["₩1,234원 KRW"], "1234"),
    ]
    # 기본값이 아닌 설정 뒤에 setDisplay({}) 를 다시 부르면 기본값으로 돌아온다.
    + [({}, fn, args, exp) for fn, args, exp in DEFAULT_CASES[:3]]
)

DISPLAY_CASES = [
    ({}, {"dateFormat": "ko", "currency": "won"}),
    ({"date_format": "auto", "currency_display": "auto"}, {"dateFormat": "ko", "currency": "won"}),
    ({"date_format": "en", "currency_display": "symbol"}, {"dateFormat": "en", "currency": "symbol"}),
    ({"date_format": "iso", "currency_display": "code"}, {"dateFormat": "iso", "currency": "code"}),
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
const lib = await import(pathToFileURL(process.argv[2]).href);
const { formats, displays } = JSON.parse(readFileSync(process.argv[3], "utf-8"));
const run = (f) => { try { return { v: f() }; } catch (e) { return { err: String(e) }; } };
const out = {
  formats: formats.map(([s, fn, args]) => run(() => { lib.setDisplay(s); return lib[fn](...args); })),
  displays: displays.map((s) => run(() => { lib.setDisplay(s); return lib.getDisplay(); })),
};
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def lib_results(tmp_path_factory):
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
    (d / "lib.mjs").write_text(src, encoding="utf-8")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")
    (d / "cases.json").write_text(json.dumps({"formats": [[c[0], c[1], c[2]] for c in FORMAT_CASES],
                                              "displays": [c[0] for c in DISPLAY_CASES]}), encoding="utf-8")
    r = subprocess.run([NODE, str(d / "run.mjs"), str(d / "lib.mjs"), str(d / "cases.json")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"lib.js 를 node 로 불러오지 못함: {r.stderr.strip()[-400:]}"
    return json.loads(r.stdout)


@needs_node
@pytest.mark.parametrize("idx", range(len(FORMAT_CASES)),
                         ids=[f"{i}-{json.dumps(c[0])}-{c[1]}({c[2]!r})" for i, c in enumerate(FORMAT_CASES)])
def test_lib_format(lib_results, idx):
    s, fn, args, expected = FORMAT_CASES[idx]
    res = lib_results["formats"][idx]
    assert "err" not in res, (s, fn, args, res)
    assert res["v"] == expected, (s, fn, args, res["v"])


@needs_node
@pytest.mark.parametrize("idx", range(len(DISPLAY_CASES)), ids=[json.dumps(c[0]) for c in DISPLAY_CASES])
def test_lib_get_display(lib_results, idx):
    s, expected = DISPLAY_CASES[idx]
    res = lib_results["displays"][idx]
    assert "err" not in res, res
    d = res["v"]
    assert isinstance(d, dict), d
    assert "language" not in d
    assert d.get("dateFormat") == expected["dateFormat"] and d.get("currency") == expected["currency"], d


def test_lib_exports_static():
    src = (JS / "lib.js").read_text(encoding="utf-8")
    for name in ("setDisplay", "getDisplay", "won", "num", "qty", "shortWon", "wonAxis", "monthLabel", "dateLabel",
                 "monthShort", "yearLabel", "dateTimeLabel", "parseMoney", "fmtMoneyInput"):
        assert re.search(rf"export\s+(?:async\s+)?(?:const|function|let)\s+{name}\b", src), name
    assert not re.search(r"[\"']\./i18n\.js[\"']", src)
