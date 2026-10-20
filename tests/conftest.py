import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_MANAGER_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def system_lang_ko(monkeypatch):
    # 기존 테스트가 한국어 기본 항목 이름(식비·급여·저축·투자)에 의존하므로 시스템 언어를 ko 로 고정한다.
    monkeypatch.setenv("ASSET_MANAGER_LANG", "ko")


@pytest.fixture
def conn(tmp_path):
    from app import db
    c = db.init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from app.server import create_app
    app = create_app(tmp_path / "api.db")
    with TestClient(app, headers={"X-Requested-With": "asset-manager"}) as c:
        yield c


def cat_id(conn, name):
    return conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]
