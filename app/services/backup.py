"""전체 데이터 백업·복원.

백업은 SQLite 온라인 백업 API 로 일관된 스냅숏을 만든다. 복원 전에는 파일을 검증하고,
현재 데이터를 자동으로 백업(pre_restore_*.db)한 뒤 덮어쓴다.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from .. import config, db
from ..util import AppError


def create_backup(conn: sqlite3.Connection, label: str = "manual", dest_dir: Path | None = None) -> dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_dir = dest_dir or config.backup_dir()
    path = dest_dir / f"{label}_{stamp}.db"
    i = 1
    while path.exists():
        path = dest_dir / f"{label}_{stamp}_{i}.db"
        i += 1
    dst = sqlite3.connect(str(path))
    try:
        conn.backup(dst)
    finally:
        dst.close()
    return _info(path)


KEEP_AUTO_DELETE = 30  # 삭제 전 자동 백업(pre_delete_*)은 최근 30개만 남긴다


def prune_backups(label: str, keep: int) -> int:
    """label 로 시작하는 자동 백업을 최근 keep 개만 남기고 지운다. 지운 개수를 돌려준다."""
    files = sorted(config.backup_dir().glob(f"{label}_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[keep:]:
        p.unlink(missing_ok=True)
    return max(len(files) - keep, 0)


def _info(p: Path) -> dict:
    st = p.stat()
    return {"name": p.name, "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}


def list_backups() -> list[dict]:
    files = sorted(config.backup_dir().glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [_info(p) for p in files]


def backup_path(name: str) -> Path:
    # 경로 조작 방지: 백업 폴더 안의 파일 이름만 허용
    if not name or "/" in name or "\\" in name or ".." in name or not name.endswith(".db"):
        raise AppError.of("backup.invalid_name")
    p = config.backup_dir() / name
    if not p.exists():
        raise AppError.of("backup.not_found")
    return p


def delete_backup(name: str) -> None:
    backup_path(name).unlink()


def validate_backup_file(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            header = f.read(16)
    except OSError:
        raise AppError.of("backup.unreadable") from None
    if header != b"SQLite format 3\x00":
        raise AppError.of("backup.not_sqlite")
    try:
        src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise AppError.of("backup.cannot_open", error=str(e)) from None
    try:
        ok = src.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise AppError.of("backup.corrupt", detail=ok)
        version = src.execute("PRAGMA user_version").fetchone()[0]
        if version > db.SCHEMA_VERSION:
            raise AppError.of("backup.newer_version", version=version)
        if version < 1:
            raise AppError.of("backup.no_version")
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = db.REQUIRED_TABLES - tables if version == db.SCHEMA_VERSION else set()
        if missing:
            raise AppError.of("backup.missing_tables", tables=", ".join(sorted(missing)))
        counts = {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("records", "categories", "accounts", "asset_txns", "indicators") if t in tables}
        return {"version": version, "counts": counts}
    except sqlite3.DatabaseError as e:
        raise AppError.of("backup.cannot_inspect", error=str(e)) from None
    finally:
        src.close()


def restore(conn: sqlite3.Connection, src_path: Path) -> dict:
    info = validate_backup_file(src_path)
    safety = create_backup(conn, "pre_restore")
    src = sqlite3.connect(f"file:{src_path.as_posix()}?mode=ro", uri=True)
    try:
        src.backup(conn)
    finally:
        src.close()
    db.migrate(conn)
    return {"restored": True, "safety_backup": safety["name"], **info}


RESET_MODES = ("records", "all")


def reset(conn: sqlite3.Connection, mode: str) -> dict:
    """데이터 초기화. 지우기 전에 현재 데이터를 자동 백업(pre_reset_*.db)한다.

    - records : 소득·계획·지출 기록만 모두 지우고 항목·설정은 둔다.
    - all     : 처음 설치한 상태(기본 항목만 있는 새 데이터)로 되돌린다. 항목·설정(API 키)·숨긴 자산·지표 데이터도 지운다.
    """
    if mode not in RESET_MODES:
        raise AppError.of("reset.invalid_mode")
    safety = create_backup(conn, "pre_reset")
    if mode == "records":
        with conn:
            n = conn.execute("DELETE FROM records").rowcount
        return {"reset": mode, "deleted_records": n, "safety_backup": safety["name"]}
    import tempfile
    from . import settings  # 표시 설정(날짜·금액 단위)은 전체 초기화 뒤에도 유지한다
    display = settings.get_display(conn)
    with tempfile.TemporaryDirectory() as tmp:
        fresh = db.init_db(Path(tmp) / "fresh.db")  # 새 DB 를 만들어(기본 항목 포함) 현재 DB 에 그대로 덮어쓴다
        try:
            fresh.backup(conn)
        finally:
            fresh.close()
    db.migrate(conn)
    keep = {k: v for k, v in display.items() if v != settings.DEFAULTS[k]}
    if keep:
        settings.set_many(conn, keep)
    return {"reset": mode, "safety_backup": safety["name"]}
