"""SQLite 연결과 스키마 버전 관리.

- 스키마 버전은 PRAGMA user_version 으로 관리한다.
- MIGRATIONS[i] 는 버전 i -> i+1 로 올리는 SQL 이다. 새 스키마 변경은 리스트 끝에 추가만 한다.
- 기존 데이터가 있는 DB 를 마이그레이션하기 전에는 자동으로 백업을 남긴다.
- 금액은 원 단위 정수(INTEGER)로 저장한다. 주식 수량·단가는 소수 허용을 위해 TEXT(Decimal 문자열)로 저장한다.
"""
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import config, i18n

MIGRATIONS: list[str] = [
    # v0 -> v1 : 초기 스키마
    """
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE categories (
        id         INTEGER PRIMARY KEY,
        name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
        parent_id  INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
        color      TEXT,
        icon       TEXT,
        is_active  INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE UNIQUE INDEX ux_categories_parent_name ON categories (IFNULL(parent_id, 0), name);

    -- 수입 / 지출 계획 / 실제 지출 기록. 항목(categories)은 세 영역이 공유한다.
    --   month       : 월(YYYY-MM). 수입=입금 월(v3부터, 미입금이면 예산 월), 계획=계획 월, 지출=발생 월
    --   txn_date    : 수입=실제 입금일(NULL 이면 미입금), 지출=발생일, 계획=NULL
    --   settle_date : 지출의 결제일(카드 결제일 등, 선택)
    CREATE TABLE records (
        id          INTEGER PRIMARY KEY,
        kind        TEXT NOT NULL CHECK (kind IN ('income','plan','expense')),
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
        amount      INTEGER NOT NULL,
        month       TEXT NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
        txn_date    TEXT CHECK (txn_date IS NULL OR txn_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
        settle_date TEXT CHECK (settle_date IS NULL OR settle_date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
        memo        TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX ix_records_kind_month ON records (kind, month);
    CREATE INDEX ix_records_category ON records (category_id);
    CREATE INDEX ix_records_txn_date ON records (txn_date);

    CREATE TABLE asset_types (
        id         INTEGER PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE,
        valuation  TEXT NOT NULL DEFAULT 'balance' CHECK (valuation IN ('balance','holdings')),
        liquidity  TEXT NOT NULL DEFAULT 'cash' CHECK (liquidity IN ('cash','investment','other')),
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_builtin INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE accounts (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
        type_id     INTEGER NOT NULL REFERENCES asset_types(id) ON DELETE RESTRICT,
        institution TEXT NOT NULL DEFAULT '',
        memo        TEXT NOT NULL DEFAULT '',
        input_mode  TEXT NOT NULL DEFAULT 'manual' CHECK (input_mode IN ('manual','api','csv')),
        is_active   INTEGER NOT NULL DEFAULT 1,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE securities (
        id       INTEGER PRIMARY KEY,
        symbol   TEXT NOT NULL UNIQUE CHECK (length(trim(symbol)) > 0),
        name     TEXT NOT NULL,
        kind     TEXT NOT NULL DEFAULT 'stock' CHECK (kind IN ('stock','etf','fund','other')),
        currency TEXT NOT NULL DEFAULT 'KRW',
        memo     TEXT NOT NULL DEFAULT ''
    );

    -- 자산 변동. amount 는 원 단위 정수.
    --   deposit/withdrawal/transfer/dividend/interest/fee : amount > 0
    --   valuation(평가액 변동)/adjustment(기타 조정)         : amount 부호 있음
    --   buy/sell : quantity * price = 거래 금액(amount), fee = 수수료+세금
    CREATE TABLE asset_txns (
        id            INTEGER PRIMARY KEY,
        date          TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
        kind          TEXT NOT NULL CHECK (kind IN ('deposit','withdrawal','transfer','buy','sell',
                                                    'dividend','interest','fee','valuation','adjustment')),
        account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
        to_account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
        security_id   INTEGER REFERENCES securities(id) ON DELETE RESTRICT,
        quantity      TEXT,
        price         TEXT,
        amount        INTEGER NOT NULL DEFAULT 0,
        fee           INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
        memo          TEXT NOT NULL DEFAULT '',
        created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        CHECK (kind <> 'transfer' OR (to_account_id IS NOT NULL AND to_account_id <> account_id)),
        CHECK (kind NOT IN ('buy','sell') OR (security_id IS NOT NULL AND quantity IS NOT NULL AND price IS NOT NULL))
    );
    CREATE INDEX ix_asset_txns_date ON asset_txns (date, id);
    CREATE INDEX ix_asset_txns_account ON asset_txns (account_id);

    CREATE TABLE security_prices (
        security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
        date        TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
        price       TEXT NOT NULL,
        source      TEXT NOT NULL DEFAULT 'manual',
        PRIMARY KEY (security_id, date)
    );

    CREATE TABLE indicators (
        id              INTEGER PRIMARY KEY,
        name            TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
        unit            TEXT NOT NULL DEFAULT '',
        source          TEXT NOT NULL DEFAULT '',
        source_url      TEXT NOT NULL DEFAULT '',
        frequency       TEXT NOT NULL DEFAULT '',
        provider        TEXT NOT NULL DEFAULT 'manual' CHECK (provider IN ('manual','ecos','fred')),
        provider_config TEXT NOT NULL DEFAULT '{}',
        decimals        INTEGER NOT NULL DEFAULT 2,
        memo            TEXT NOT NULL DEFAULT '',
        is_active       INTEGER NOT NULL DEFAULT 1,
        sort_order      INTEGER NOT NULL DEFAULT 0,
        last_fetched_at TEXT,
        last_error      TEXT
    );

    CREATE TABLE indicator_values (
        indicator_id INTEGER NOT NULL REFERENCES indicators(id) ON DELETE CASCADE,
        date         TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
        value        REAL NOT NULL,
        source       TEXT NOT NULL DEFAULT 'manual',
        updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        PRIMARY KEY (indicator_id, date)
    );
    """,
    # v1 -> v2 : 예산(봉투) 방식
    #   budget_month : 수입이 '어느 달 예산(쓸 돈)'이 되는지. 기본값 = 입금 월
    #   tag          : 시스템이 만든 조정 기록 구분. NULL=사용자 기록, 'move'=계획 옮기기, 'settle'=월말 정산
    """
    ALTER TABLE records ADD COLUMN budget_month TEXT
        CHECK (budget_month IS NULL OR budget_month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]');
    ALTER TABLE records ADD COLUMN tag TEXT CHECK (tag IS NULL OR tag IN ('move','settle'));
    UPDATE records SET budget_month = COALESCE(substr(txn_date, 1, 7), month) WHERE kind = 'income';
    CREATE INDEX ix_records_budget ON records (kind, budget_month);
    INSERT OR IGNORE INTO categories (name, color, sort_order)
        VALUES ('저축·투자', '#0f766e', (SELECT IFNULL(MAX(sort_order), 0) + 1 FROM categories));
    """,
    # v2 -> v3 : 항목 종류 분리. income = 소득 항목, expense = 지출 항목(지출 계획·실제 지출 공용)
    #   기존 항목은 수입 기록만 있거나(지출·계획 기록 없음) 기본 소득 항목(급여·장학금)이면 income 으로 분류
    """
    ALTER TABLE categories ADD COLUMN kind TEXT NOT NULL DEFAULT 'expense' CHECK (kind IN ('income','expense'));
    UPDATE categories SET kind = 'income'
     WHERE NOT EXISTS (SELECT 1 FROM records r WHERE r.category_id = categories.id AND r.kind IN ('plan','expense'))
       AND (EXISTS (SELECT 1 FROM records r WHERE r.category_id = categories.id AND r.kind = 'income')
            OR (categories.parent_id IS NULL AND categories.name IN ('급여', '장학금')));
    UPDATE categories SET kind = (SELECT p.kind FROM categories p WHERE p.id = categories.parent_id)
     WHERE parent_id IS NOT NULL;
    DROP INDEX ux_categories_parent_name;
    CREATE UNIQUE INDEX ux_categories_kind_parent_name ON categories (kind, IFNULL(parent_id, 0), name);
    """,
    # v3 -> v4 : 항목(모든 달 공통) + 세부항목(달마다 자유로운 기록 이름)
    #   item : 기록의 세부항목 이름(예: 식비 > '마트', 장학금 > '국가장학금')
    #   기존 하위 분류는 상위 항목의 세부항목 기록으로 바꾸고 하위 분류는 지운다.
    #   (SQLite 의 UPDATE ... SET 은 바뀌기 전 값으로 계산하므로 두 하위 질의 모두 원래 category_id 를 본다)
    """
    ALTER TABLE records ADD COLUMN item TEXT NOT NULL DEFAULT '';
    UPDATE records
       SET item = (SELECT c.name FROM categories c WHERE c.id = records.category_id),
           category_id = (SELECT c.parent_id FROM categories c WHERE c.id = records.category_id)
     WHERE category_id IN (SELECT id FROM categories WHERE parent_id IS NOT NULL);
    DELETE FROM categories WHERE parent_id IS NOT NULL;
    """,
    # v4 -> v5 : 항목 메모(어떤 지출·소득을 넣는 항목인지 설명)
    """
    ALTER TABLE categories ADD COLUMN memo TEXT NOT NULL DEFAULT '';
    """,
    # v5 -> v6 : 쓰이지 않는 데이터 정리
    #  - 항목 비활성화는 더 이상 없다(삭제만 있다). 예전에 숨긴 항목은 다시 보이게 한다.
    #  - 예전 집계 기준 설정(income_basis/expense_basis)은 아무 데서도 쓰지 않으므로 지운다.
    """
    UPDATE categories SET is_active = 1 WHERE is_active = 0;
    DELETE FROM settings WHERE key IN ('income_basis', 'expense_basis');
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)

REQUIRED_TABLES = {
    "settings", "categories", "records", "asset_types", "accounts",
    "securities", "asset_txns", "security_prices", "indicators", "indicator_values",
}

DEFAULT_CATEGORIES = [
    # (이름, 상위 이름, 색상)
    ("급여", None, "#2563eb"),
    ("장학금", None, "#0891b2"),
    ("식비", None, "#ea580c"),
    ("교통비", None, "#65a30d"),
    ("주거·관리비", None, "#7c3aed"),
    ("통신비", None, "#0d9488"),
    ("구독료", None, "#db2777"),
    ("취미", None, "#ca8a04"),
    ("의료비", None, "#dc2626"),
    ("기타", None, "#64748b"),
]

DEFAULT_ASSET_TYPES = [
    # (이름, 평가방식, 성격)
    ("현금", "balance", "cash"),
    ("은행 예금·적금", "balance", "cash"),
    ("주식", "holdings", "investment"),
    ("ETF", "holdings", "investment"),
    ("기타 금융자산", "balance", "investment"),
    ("기타 자산", "balance", "other"),
]


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or config.db_path()), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """여러 문장을 한 트랜잭션으로 묶는다. 블록 안에서 예외가 나면 전부 되돌린다.

    블록 안에서는 `with conn:` 을 쓰지 않는다(중간에 커밋되어 버린다).
    """
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def get_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, db_file: Path | None = None, lang: str | None = None) -> int:
    """스키마를 최신 버전으로 올린다. 반환값: 마이그레이션 전 버전.

    새 DB(시작 버전 0)일 때만 lang(없으면 OS 언어)으로 기본 항목·자산 유형 이름과 언어 설정을 정한다.
    기존 DB 에서는 lang 을 무시한다(사용자 데이터 불변).
    """
    current = get_version(conn)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"데이터베이스 버전({current})이 프로그램이 지원하는 버전({SCHEMA_VERSION})보다 높습니다. "
            "프로그램을 최신 버전으로 업데이트하세요."
        )
    if current == SCHEMA_VERSION:
        return current

    if current > 0 and db_file is not None and db_file.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = config.backup_dir() / f"pre_migration_v{current}_{stamp}.db"
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        shutil.copy2(db_file, dst)

    for v in range(current, SCHEMA_VERSION):
        try:
            conn.execute("BEGIN")
            for stmt in _split_sql(MIGRATIONS[v]):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {v + 1}")
            if v == 0:
                _seed(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    if current == 0:
        # 이름 번역은 반드시 모든 마이그레이션 뒤에 한다(v2->v3 이 한국어 이름으로 소득 항목을 판정한다).
        try:
            conn.execute("BEGIN")
            _localize_defaults(conn, lang)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return current


def _localize_defaults(conn: sqlite3.Connection, lang: str | None) -> None:
    """새 DB 의 기본 이름을 언어에 맞추고 language 설정을 넣는다. 호출자가 트랜잭션을 연다."""
    lang = i18n.normalize(lang or config.system_language())
    if lang == "en":
        for ko, en in i18n.DEFAULT_CATEGORY_NAMES.items():
            conn.execute("UPDATE categories SET name=? WHERE name=?", (en, ko))
        for ko, en in i18n.DEFAULT_ASSET_TYPE_NAMES.items():
            conn.execute("UPDATE asset_types SET name=? WHERE name=?", (en, ko))
    conn.execute("INSERT INTO settings (key, value) VALUES ('language', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (lang,))


def _split_sql(script: str) -> list[str]:
    # executescript 는 자체 COMMIT 을 하므로 트랜잭션 제어를 위해 문장 단위로 나눠 실행한다.
    stmts, buf = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip()
            if sqlite3.complete_statement(stmt):
                stmts.append(stmt)
                buf = []
    if "".join(buf).strip():
        stmts.append("\n".join(buf))
    return stmts


def _seed(conn: sqlite3.Connection) -> None:
    for i, (name, _parent, color) in enumerate(DEFAULT_CATEGORIES):
        conn.execute(
            "INSERT INTO categories (name, color, sort_order) VALUES (?, ?, ?)", (name, color, i)
        )
    for i, (name, valuation, liquidity) in enumerate(DEFAULT_ASSET_TYPES):
        conn.execute(
            "INSERT INTO asset_types (name, valuation, liquidity, sort_order, is_builtin) VALUES (?,?,?,?,1)",
            (name, valuation, liquidity, i),
        )


def init_db(path: Path | str | None = None, lang: str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else config.db_path()
    conn = connect(p)
    migrate(conn, p, lang=lang)
    return conn
