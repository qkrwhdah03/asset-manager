import json

import pytest

from app import db
from app.services import backup, csvio, indicators, records
from app.services.providers import ProviderError, ecos, fred
from app.util import AppError
from conftest import cat_id


# ── CSV ──

def test_csv_records_roundtrip(conn):
    food = cat_id(conn, "식비")
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 12345, "month": "2026-10", "memo": "a,b"})
    data = csvio.export_records(conn)
    assert data.startswith("﻿".encode("utf-8"))
    conn.execute("DELETE FROM records"); conn.commit()
    res = csvio.import_records(conn, data, dry_run=False)
    assert res["ok"] and res["applied"]
    r = records.list_records(conn)[0]
    assert r["amount"] == 12345 and r["memo"] == "a,b"


def test_csv_import_is_atomic_and_reports_rows(conn):
    text = "구분,항목,금액,귀속월\n수입,급여,1000,2026-10\n실제지출,없는항목,500,2026-10\n지출계획,식비,abc,2026-10\n"
    res = csvio.import_records(conn, text.encode("utf-8"), dry_run=False)
    assert not res["ok"] and not res["applied"]
    assert [e["row"] for e in res["errors"]] == [3, 4]
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0


def test_csv_import_dry_run_and_create_missing(conn):
    text = "구분,항목,금액,귀속월\n실제지출,생활비 > 마트,500,2026-10\n"
    dry = csvio.import_records(conn, text.encode("utf-8"), dry_run=True, create_missing=True)
    assert dry["ok"] and not dry["applied"] and "생활비" in dry["created"]
    assert conn.execute("SELECT COUNT(*) FROM categories WHERE name='생활비'").fetchone()[0] == 0
    real = csvio.import_records(conn, text.encode("utf-8"), dry_run=False, create_missing=True)
    assert real["applied"]
    r = records.list_records(conn)[0]
    assert r["category_name"] == "생활비" and r["item"] == "마트"


def test_csv_cp949_and_missing_header(conn):
    text = "구분,항목,금액,귀속월\n수입,급여,1000,2026-10\n"
    assert csvio.import_records(conn, text.encode("cp949"), dry_run=True)["ok"]
    with pytest.raises(AppError):
        csvio.import_records(conn, "항목,금액\n급여,1\n".encode("utf-8"))


def test_csv_asset_txns_import_validates_ledger(conn):
    from app.services import assets
    tid = conn.execute("SELECT id FROM asset_types WHERE name='주식'").fetchone()[0]
    assets.save_account(conn, {"name": "증권", "type_id": tid})
    ok = ("날짜,유형,계좌,종목코드,종목명,수량,단가,금액\n"
          "2026-01-01,입금,증권,,,,,100000\n2026-01-02,매수,증권,005930,삼성전자,1,60000,\n")
    res = csvio.import_asset_txns(conn, ok.encode("utf-8"), dry_run=False)
    assert res["applied"], res
    bad = "날짜,유형,계좌,종목코드,수량,단가\n2026-01-03,매도,증권,005930,5,60000\n"
    res = csvio.import_asset_txns(conn, bad.encode("utf-8"), dry_run=False)
    assert not res["ok"] and "보유 수량" in res["errors"][0]["message"]
    assert conn.execute("SELECT COUNT(*) FROM asset_txns").fetchone()[0] == 2


# ── 백업 ──

def test_backup_and_restore(conn, tmp_path):
    food = cat_id(conn, "식비")
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 777, "month": "2026-10"})
    b = backup.create_backup(conn)
    records.create_record(conn, {"kind": "expense", "category_id": food, "amount": 1, "month": "2026-10"})
    res = backup.restore(conn, backup.backup_path(b["name"]))
    assert res["restored"]
    amounts = [r["amount"] for r in records.list_records(conn)]
    assert amounts == [777]
    assert any(x["name"].startswith("pre_restore") for x in backup.list_backups())


def test_restore_rejects_invalid_files(tmp_path, conn):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database")
    with pytest.raises(AppError):
        backup.restore(conn, bad)
    import sqlite3
    other = tmp_path / "other.db"
    c = sqlite3.connect(other); c.execute("CREATE TABLE t(x)"); c.commit(); c.close()
    with pytest.raises(AppError):
        backup.restore(conn, other)
    with pytest.raises(AppError):
        backup.backup_path("../secret.db")


def test_newer_schema_rejected(tmp_path):
    import sqlite3
    p = tmp_path / "new.db"
    c = sqlite3.connect(p); c.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}"); c.commit(); c.close()
    with pytest.raises(RuntimeError):
        db.init_db(p)


# ── 지표 / 공급자 파싱 ──

def test_indicator_manual_values_and_change(conn):
    ind = indicators.save_indicator(conn, {"name": "기준금리(수동)", "unit": "%"})
    indicators.set_value(conn, ind["id"], "2026-08-01", "2.75")
    indicators.set_value(conn, ind["id"], "2026-10-01", "2.50")
    got = indicators.get_indicator(conn, ind["id"])
    assert got["current"]["value"] == 2.5 and got["previous"]["value"] == 2.75
    assert round(got["change"], 2) == -0.25
    with pytest.raises(AppError):
        indicators.refresh(conn, ind["id"])  # 수동 지표는 자동 업데이트 불가


def test_indicator_refresh_without_key_keeps_data(conn):
    ind = indicators.add_preset(conn, "kr_base_rate")
    indicators.set_value(conn, ind["id"], "2026-10-01", "2.5")
    with pytest.raises(AppError) as e:
        indicators.refresh(conn, ind["id"])
    assert "API 키" in str(e.value)
    got = indicators.get_indicator(conn, ind["id"])
    assert got["value_count"] == 1 and got["last_error"]


def test_ecos_parsing():
    sample = {"StatisticSearch": {"list_total_count": 2, "row": [
        {"TIME": "20261001", "DATA_VALUE": "2.50"}, {"TIME": "20261002", "DATA_VALUE": "1,234.5"}]}}
    assert ecos.parse_search(sample, "D") == [("2026-10-01", 2.5), ("2026-10-02", 1234.5)]
    assert ecos.parse_search({"StatisticSearch": {"row": [{"TIME": "202609", "DATA_VALUE": "115.2"}]}}, "M") == [("2026-09-01", 115.2)]
    assert ecos.parse_time("2026Q3", "Q") == "2026-07-01"
    assert ecos.parse_search({"RESULT": {"CODE": "INFO-200", "MESSAGE": "없음"}}, "D") == []
    with pytest.raises(ProviderError):
        ecos.parse_search({"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키가 유효하지 않습니다."}}, "D")
    from datetime import date
    url = ecos.build_search_url("KEY", {"stat_code": "722Y001", "cycle": "D", "item_code1": "0101000"},
                                date(2026, 1, 1), date(2026, 1, 31))
    assert url.endswith("/StatisticSearch/KEY/json/kr/1/10000/722Y001/D/20260101/20260131/0101000")


def test_fred_parsing():
    data = {"observations": [{"date": "2026-10-01", "value": "6000.5"}, {"date": "2026-10-02", "value": "."}]}
    assert fred.parse(data) == [("2026-10-01", 6000.5)]
    with pytest.raises(ProviderError):
        fred.parse({"error_message": "Bad API key"})


# ── API ──

def test_api_flow(client):
    cats = client.get("/api/categories").json()
    sal = next(c for c in cats if c["name"] == "급여")["id"]
    r = client.post("/api/records", json={"kind": "income", "category_id": sal, "amount": "3,000,000",
                                          "budget_month": "2026-11", "txn_date": "2026-10-31"})
    assert r.status_code == 200, r.text
    assert client.get("/api/stats/summary", params={"month": "2026-11"}).json()["income"] == 3_000_000
    assert client.get("/api/stats/summary", params={"month": "2026-10", "basis": "cash"}).json()["income"] == 3_000_000
    bad = client.post("/api/records", json={"kind": "income", "category_id": sal, "amount": "x", "budget_month": "2026-09"})
    assert bad.status_code == 400 and "숫자" in bad.json()["detail"]
    assert client.get("/").status_code == 200
    exp = client.get("/api/export/records")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    imp = client.post("/api/import/records?dry_run=true", content=exp.content)
    assert imp.json()["ok"]


def test_api_requires_csrf_header(tmp_path):
    from fastapi.testclient import TestClient
    from app.server import create_app
    with TestClient(create_app(tmp_path / "c.db")) as c:
        assert c.post("/api/categories", json={"name": "x"}).status_code == 403
        assert c.get("/api/categories").status_code == 200


def test_api_restore_upload(client):
    client.post("/api/categories", json={"name": "백업테스트"})
    b = client.post("/api/backups").json()
    data = client.get(f"/api/backups/{b['name']}/download").content
    client.delete(f"/api/categories/{next(c['id'] for c in client.get('/api/categories').json() if c['name']=='백업테스트')}")
    r = client.post("/api/restore-upload", content=data)
    assert r.status_code == 200, r.text
    assert any(c["name"] == "백업테스트" for c in client.get("/api/categories").json())


def test_delete_backup_rule_is_uniform(client, data_dir):
    def pre_delete():
        return sorted(p.name for p in (data_dir / "backups").glob("pre_delete_*.db"))
    cats = client.get("/api/categories").json()
    food = next(c for c in cats if c["name"] == "식비")["id"]
    empty = client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 0, "month": "2026-10"}).json()
    real = client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 5000, "month": "2026-10"}).json()
    assert client.delete(f"/api/records/{empty['id']}").status_code == 200
    assert pre_delete() == []  # 0원 기록만 지우면 백업하지 않는다
    assert client.post("/api/records/bulk-delete", json={"ids": [real["id"]]}).status_code == 200
    assert len(pre_delete()) == 1  # 금액 있는 기록이 지워지면 백업
    hobby = next(c for c in cats if c["name"] == "취미")["id"]
    assert client.post("/api/categories/bulk-delete", json={"ids": [hobby]}).status_code == 200
    assert len(pre_delete()) == 1  # 기록 없는 항목 삭제는 백업하지 않는다


def test_prune_auto_backups(conn):
    import os, time
    for i in range(5):
        b = backup.create_backup(conn, "pre_delete")
        p = backup.backup_path(b["name"])
        os.utime(p, (time.time() - 100 + i, time.time() - 100 + i))
    manual = backup.create_backup(conn)
    assert backup.prune_backups("pre_delete", keep=2) == 3
    names = [b["name"] for b in backup.list_backups()]
    assert sum(n.startswith("pre_delete") for n in names) == 2 and manual["name"] in names


def test_reset_records_and_all(client, data_dir):
    cats = client.get("/api/categories").json()
    food = next(c for c in cats if c["name"] == "식비")["id"]
    client.post("/api/categories", json={"name": "내항목", "kind": "expense"})
    client.post("/api/records", json={"kind": "expense", "category_id": food, "amount": 5000, "month": "2026-10"})
    assert client.post("/api/reset", json={"mode": "x"}).status_code == 400
    r = client.post("/api/reset", json={"mode": "records"}).json()
    assert r["deleted_records"] == 1 and r["safety_backup"].startswith("pre_reset")
    assert client.get("/api/records").json() == []
    assert any(c["name"] == "내항목" for c in client.get("/api/categories").json())  # 항목은 남는다
    r = client.post("/api/reset", json={"mode": "all"}).json()
    names = {c["name"] for c in client.get("/api/categories").json()}
    assert "내항목" not in names and {"급여", "식비", "저축·투자"} <= names  # 기본 항목으로
    assert client.get("/api/meta").json()["schema_version"] == db.SCHEMA_VERSION
    assert len(list((data_dir / "backups").glob("pre_reset_*.db"))) == 2
