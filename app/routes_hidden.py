"""숨긴 자산·지표 화면의 HTTP 라우트. server.create_app 이 같은 자리(통계 뒤, 백업 앞)에서 등록한다."""
from fastapi import Body, FastAPI

from .services import assets, indicators, settings
from .services.providers import ProviderError, ecos
from .util import AppError


def register_asset_routes(app: FastAPI, C) -> None:
    """자산 유형·계좌·종목·시세·자산 변동·자산 요약 라우트. C = 연결 의존성(Depends(get_conn))."""
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


def register_indicator_routes(app: FastAPI, C) -> None:
    """지표·지표 값·갱신·ECOS 항목 조회 라우트. C = 연결 의존성(Depends(get_conn))."""
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
