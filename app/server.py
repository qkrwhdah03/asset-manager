"""로컬 HTTP API (FastAPI). 127.0.0.1 에서만 동작하며 UI(정적 파일)도 함께 제공한다."""
import mimetypes
import os
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, config, db
from .services import assets, backup, budget, categories, csvio, indicators, records, settings, stats
from .services.providers import ProviderError, ecos
from .util import AppError

# Windows 레지스트리에서 .js 가 text/plain 으로 등록된 PC가 있어 ES 모듈 로딩이 실패하는 것을 막는다.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def create_app(db_file: Path | None = None) -> FastAPI:
    db_file = Path(db_file) if db_file else config.db_path()
    init_conn = db.init_db(db_file)
    init_conn.close()

    app = FastAPI(title="개인 자산 관리", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # 변경 요청에는 커스텀 헤더를 요구한다 → 다른 웹사이트에서의 위조 요청(CSRF)을 브라우저가 차단.
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            if request.headers.get("x-requested-with") != "asset-manager":
                return JSONResponse({"detail": "허용되지 않은 요청입니다."}, status_code=403)
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            # 프로그램을 업데이트한 뒤 예전 화면 파일이 캐시에서 쓰이지 않도록 항상 다시 확인하게 한다.
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(AppError)
    async def app_error(_req, exc: AppError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(_req, exc):
        msg = str(exc)
        if "FOREIGN KEY" in msg:
            msg = "다른 기록이 참조하고 있어 처리할 수 없습니다."
        elif "UNIQUE" in msg:
            msg = "이미 같은 값이 존재합니다."
        else:
            msg = f"데이터 무결성 오류: {msg}"
        return JSONResponse({"detail": msg}, status_code=400)

    @app.exception_handler(sqlite3.OperationalError)
    async def op_error(_req, exc):
        return JSONResponse({"detail": f"데이터베이스 오류로 저장하지 못했습니다: {exc}"}, status_code=500)

    def get_conn():
        conn = db.connect(db_file)
        try:
            yield conn
        finally:
            conn.close()

    C = Depends(get_conn)

    def csv_response(data: bytes, name: str) -> Response:
        fname = f"{name}_{date.today().strftime('%Y%m%d')}.csv"
        return Response(data, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})

    def maybe_save(data: bytes, name: str, save: bool):
        if not save:
            return csv_response(data, name)
        out = config.data_dir() / "exports"
        out.mkdir(exist_ok=True)
        p = out / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        p.write_bytes(data)
        return {"saved": True, "path": str(p), "folder": str(out)}

    # ── 메타 / 설정 ──
    @app.get("/api/meta")
    def meta(conn=C):
        return {"version": __version__, "schema_version": db.get_version(conn), "data_dir": str(config.data_dir()),
                "db_path": str(db_file), "backup_dir": str(config.backup_dir()), "today": date.today().isoformat()}

    @app.get("/api/settings")
    def get_settings(conn=C):
        return settings.get_public(conn)

    @app.put("/api/settings")
    def put_settings(data: dict = Body(...), conn=C):
        return settings.set_many(conn, data)

    @app.post("/api/open-folder")
    def open_folder(data: dict = Body(default={})):
        which = data.get("which", "data")
        p = {"data": config.data_dir(), "backups": config.backup_dir(), "exports": config.data_dir() / "exports"}.get(which)
        if p is None:
            raise AppError("알 수 없는 폴더입니다.")
        p.mkdir(exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(p))  # noqa: S606 (로컬 탐색기 열기)
        return {"path": str(p)}

    # ── 항목 ──
    @app.get("/api/categories")
    def list_categories(active_only: bool = False, kind: str | None = None, conn=C):
        return categories.list_categories(conn, include_inactive=not active_only, kind=kind)

    def safety_backup(conn, column: str, ids: list) -> None:
        # 삭제 규칙(모든 삭제 공통): 0원이 아닌 기록이 하나라도 함께 지워지면 직전에 자동 백업을 남긴다.
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return  # 잘못된 목록은 삭제 함수가 오류로 알린다
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        if conn.execute(f"SELECT 1 FROM records WHERE {column} IN ({marks}) AND amount <> 0 LIMIT 1", ids).fetchone():
            backup.create_backup(conn, "pre_delete")
            backup.prune_backups("pre_delete", keep=backup.KEEP_AUTO_DELETE)

    @app.post("/api/categories/bulk-delete")
    def bulk_delete_categories(data: dict = Body(...), conn=C):
        safety_backup(conn, "category_id", data.get("ids") or [])
        return categories.bulk_delete(conn, data.get("ids") or [])

    @app.post("/api/categories/{cid}/reorder")
    def reorder_category(cid: int, data: dict = Body(...), conn=C):
        return categories.reorder(conn, cid, data.get("before_id"))

    @app.post("/api/categories")
    def create_category(data: dict = Body(...), conn=C):
        return categories.create_category(conn, data)

    @app.put("/api/categories/{cid}")
    def update_category(cid: int, data: dict = Body(...), conn=C):
        return categories.update_category(conn, cid, data)

    @app.delete("/api/categories/{cid}")
    def delete_category(cid: int, with_records: bool = False, conn=C):
        if with_records:
            safety_backup(conn, "category_id", [cid])
        return categories.delete_category(conn, cid, with_records)

    # ── 수입·지출 기록 ──
    @app.get("/api/records")
    def list_records(kind: str | None = None, month: str | None = None, basis: str = "budget",
                     start: str | None = None, end: str | None = None, category_id: int | None = None,
                     q: str | None = None, conn=C):
        return records.list_records(conn, kind, month, basis, start, end, category_id, q)

    @app.post("/api/records")
    def create_record(data: dict = Body(...), conn=C):
        return records.create_record(conn, data)

    @app.put("/api/records/{rid}")
    def update_record(rid: int, data: dict = Body(...), conn=C):
        return records.update_record(conn, rid, data)

    @app.post("/api/records/move")
    def move_records(data: dict = Body(...), conn=C):
        return records.move_records(conn, data.get("ids") or [], data.get("category_id"), data.get("new_category"))

    @app.post("/api/records/bulk-delete")
    def bulk_delete_records(data: dict = Body(...), conn=C):
        safety_backup(conn, "id", data.get("ids") or [])
        return records.bulk_delete_records(conn, data.get("ids") or [])

    @app.delete("/api/records/{rid}")
    def delete_record(rid: int, conn=C):
        safety_backup(conn, "id", [rid])
        records.delete_record(conn, rid)
        return {"ok": True}

    # ── 월 예산(봉투) ──
    @app.get("/api/budget")
    def get_budget(month: str, conn=C):
        return budget.get_budget(conn, month)

    @app.put("/api/budget/plan")
    def set_plan(data: dict = Body(...), conn=C):
        return budget.set_plan(conn, data.get("month"), data.get("category_id"), data.get("amount"))


    @app.post("/api/budget/move")
    def move_plan(data: dict = Body(...), conn=C):
        return budget.move_plan(conn, data.get("month"), data.get("from_category_id"), data.get("to_category_id"), data.get("amount"))

    @app.post("/api/budget/settle")
    def settle(data: dict = Body(...), conn=C):
        return budget.settle(conn, data.get("month"), data.get("category_id"))

    @app.delete("/api/budget/settle")
    def unsettle(month: str, conn=C):
        return budget.unsettle(conn, month)


    @app.get("/api/budget/copy-month")
    def copy_preview(from_: str = Query(..., alias="from"), to: str = Query(...), conn=C):
        return budget.copy_preview(conn, from_, to)

    @app.post("/api/budget/copy-month")
    def copy_month(data: dict = Body(...), conn=C):
        return budget.copy_month(conn, data.get("from"), data.get("to"), bool(data.get("items")), bool(data.get("amounts")))

    # ── 통계 ──
    @app.get("/api/stats/summary")
    def stats_summary(month: str, basis: str = "budget", conn=C):
        return stats.month_summary(conn, month, basis)

    @app.get("/api/stats/trend")
    def stats_trend(start: str, end: str, basis: str = "budget", conn=C):
        return stats.trend(conn, start, end, basis)

    @app.get("/api/stats/plan-vs-actual")
    def stats_pva(month: str, basis: str = "budget", conn=C):
        return stats.plan_vs_actual(conn, month, basis)

    @app.get("/api/stats/breakdown")
    def stats_breakdown(kind: str, start: str, end: str, basis: str = "budget", rollup: bool = False, conn=C):
        return stats.category_breakdown(conn, kind, start, end, basis, rollup)

    @app.get("/api/stats/annual")
    def stats_annual(year: int, basis: str = "budget", conn=C):
        return stats.annual(conn, year, basis)

    # ── 자산 ──
    @app.get("/api/asset-meta")
    def asset_meta():
        return {"txn_kinds": assets.TXN_KINDS, "liquidity": assets.LIQUIDITY_LABEL}

    @app.get("/api/asset-types")
    def list_asset_types(conn=C):
        return assets.list_asset_types(conn)

    @app.post("/api/asset-types")
    def create_asset_type(data: dict = Body(...), conn=C):
        return assets.save_asset_type(conn, data)

    @app.put("/api/asset-types/{tid}")
    def update_asset_type(tid: int, data: dict = Body(...), conn=C):
        return assets.save_asset_type(conn, data, tid)

    @app.delete("/api/asset-types/{tid}")
    def delete_asset_type(tid: int, conn=C):
        assets.delete_asset_type(conn, tid)
        return {"ok": True}

    @app.get("/api/accounts")
    def list_accounts(conn=C):
        return assets.list_accounts(conn)

    @app.post("/api/accounts")
    def create_account(data: dict = Body(...), conn=C):
        return assets.save_account(conn, data)

    @app.put("/api/accounts/{aid}")
    def update_account(aid: int, data: dict = Body(...), conn=C):
        return assets.save_account(conn, data, aid)

    @app.delete("/api/accounts/{aid}")
    def delete_account(aid: int, conn=C):
        return assets.delete_account(conn, aid)

    @app.get("/api/securities")
    def list_securities(conn=C):
        return assets.list_securities(conn)

    @app.post("/api/securities")
    def create_security(data: dict = Body(...), conn=C):
        return assets.save_security(conn, data)

    @app.put("/api/securities/{sid}")
    def update_security(sid: int, data: dict = Body(...), conn=C):
        return assets.save_security(conn, data, sid)

    @app.delete("/api/securities/{sid}")
    def delete_security(sid: int, conn=C):
        assets.delete_security(conn, sid)
        return {"ok": True}

    @app.get("/api/securities/{sid}/prices")
    def list_prices(sid: int, conn=C):
        return assets.list_prices(conn, sid)

    @app.post("/api/securities/{sid}/prices")
    def set_price(sid: int, data: dict = Body(...), conn=C):
        return assets.set_price(conn, sid, data.get("date"), data.get("price"))

    @app.delete("/api/securities/{sid}/prices")
    def delete_price(sid: int, date: str, conn=C):
        assets.delete_price(conn, sid, date)
        return {"ok": True}

    @app.get("/api/asset-txns")
    def list_txns(account_id: int | None = None, kind: str | None = None, start: str | None = None,
                  end: str | None = None, security_id: int | None = None, conn=C):
        return assets.list_txns(conn, account_id, kind, start, end, security_id)

    @app.post("/api/asset-txns")
    def create_txn(data: dict = Body(...), conn=C):
        return assets.create_txn(conn, data)

    @app.put("/api/asset-txns/{tid}")
    def update_txn(tid: int, data: dict = Body(...), conn=C):
        return assets.update_txn(conn, tid, data)

    @app.delete("/api/asset-txns/{tid}")
    def delete_txn(tid: int, conn=C):
        assets.delete_txn(conn, tid)
        return {"ok": True}

    @app.get("/api/assets/summary")
    def asset_summary(as_of: str | None = None, conn=C):
        return assets.summary(conn, as_of)

    @app.get("/api/assets/history")
    def asset_history(start: str | None = None, end: str | None = None, conn=C):
        return assets.history(conn, start, end)

    # ── 지표 ──
    @app.get("/api/indicators")
    def list_indicators(conn=C):
        return indicators.list_indicators(conn)

    @app.get("/api/indicators/presets")
    def list_presets():
        return indicators.PRESETS

    @app.post("/api/indicators/presets/{key}")
    def add_preset(key: str, conn=C):
        return indicators.add_preset(conn, key)

    @app.post("/api/indicators/refresh-all")
    def refresh_all(conn=C):
        return indicators.refresh_all(conn)

    @app.post("/api/indicators")
    def create_indicator(data: dict = Body(...), conn=C):
        return indicators.save_indicator(conn, data)

    @app.put("/api/indicators/{iid}")
    def update_indicator(iid: int, data: dict = Body(...), conn=C):
        return indicators.save_indicator(conn, data, iid)

    @app.delete("/api/indicators/{iid}")
    def delete_indicator(iid: int, conn=C):
        indicators.delete_indicator(conn, iid)
        return {"ok": True}

    @app.get("/api/indicators/{iid}/values")
    def list_values(iid: int, start: str | None = None, end: str | None = None, conn=C):
        return indicators.list_values(conn, iid, start, end)

    @app.post("/api/indicators/{iid}/values")
    def set_value(iid: int, data: dict = Body(...), conn=C):
        return indicators.set_value(conn, iid, data.get("date"), data.get("value"))

    @app.delete("/api/indicators/{iid}/values")
    def delete_value(iid: int, date: str, conn=C):
        indicators.delete_value(conn, iid, date)
        return {"ok": True}

    @app.post("/api/indicators/{iid}/refresh")
    def refresh(iid: int, full: bool = False, conn=C):
        return indicators.refresh(conn, iid, full)

    @app.get("/api/ecos/items")
    def ecos_items(stat_code: str, conn=C):
        try:
            return ecos.item_list(settings.get(conn, "ecos_api_key") or "", stat_code)
        except ProviderError as e:
            raise AppError(str(e)) from None

    # ── 백업 / 복원 ──
    @app.get("/api/backups")
    def list_backups():
        return backup.list_backups()

    @app.post("/api/backups")
    def create_backup(conn=C):
        return backup.create_backup(conn)

    @app.get("/api/backups/{name}/download")
    def download_backup(name: str):
        p = backup.backup_path(name)
        return FileResponse(p, filename=p.name, media_type="application/octet-stream")

    @app.delete("/api/backups/{name}")
    def delete_backup(name: str):
        backup.delete_backup(name)
        return {"ok": True}

    @app.post("/api/backups/{name}/restore")
    def restore_backup(name: str, conn=C):
        return backup.restore(conn, backup.backup_path(name))

    @app.post("/api/reset")
    def reset_data(data: dict = Body(...), conn=C):
        return backup.reset(conn, data.get("mode"))

    @app.post("/api/restore-upload")
    async def restore_upload(request: Request, conn=C):
        data = await request.body()
        if not data:
            raise AppError("파일이 비어 있습니다.")
        fd, tmp = tempfile.mkstemp(suffix=".db")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            return backup.restore(conn, Path(tmp))
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── CSV ──
    @app.get("/api/export/records")
    def export_records(kind: str | None = None, start: str | None = None, end: str | None = None,
                       save: bool = False, conn=C):
        return maybe_save(csvio.export_records(conn, kind, start, end), "수입지출기록", save)

    @app.get("/api/export/asset-txns")
    def export_txns(account_id: int | None = None, save: bool = False, conn=C):
        return maybe_save(csvio.export_asset_txns(conn, account_id), "자산변동", save)

    @app.get("/api/export/prices")
    def export_prices(save: bool = False, conn=C):
        return maybe_save(csvio.export_prices(conn), "종목시세", save)

    @app.get("/api/export/categories")
    def export_categories(save: bool = False, conn=C):
        return maybe_save(csvio.export_categories(conn), "항목", save)

    @app.get("/api/export/indicator/{iid}")
    def export_indicator(iid: int, save: bool = False, conn=C):
        return maybe_save(csvio.export_indicator_values(conn, iid), f"지표_{iid}", save)

    @app.get("/api/templates/{name}")
    def get_template(name: str, save: bool = False):
        return maybe_save(csvio.template(name), f"양식_{name}", save)

    @app.post("/api/import/records")
    async def import_records(request: Request, dry_run: bool = True, create_missing: bool = False, conn=C):
        return csvio.import_records(conn, await request.body(), dry_run, create_missing)

    @app.post("/api/import/asset-txns")
    async def import_txns(request: Request, dry_run: bool = True, conn=C):
        return csvio.import_asset_txns(conn, await request.body(), dry_run)

    @app.post("/api/import/prices")
    async def import_prices(request: Request, dry_run: bool = True, conn=C):
        return csvio.import_prices(conn, await request.body(), dry_run)

    @app.post("/api/import/indicator/{iid}")
    async def import_indicator(iid: int, request: Request, dry_run: bool = True, conn=C):
        return csvio.import_indicator_values(conn, iid, await request.body(), dry_run)

    # ── 정적 UI ──
    app.mount("/", StaticFiles(directory=str(config.static_dir()), html=True), name="static")
    return app
