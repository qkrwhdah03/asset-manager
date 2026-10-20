"""경제·금융 지표 추적.

값은 (1) 수동 입력, (2) CSV 가져오기, (3) 공식 API(ECOS/FRED, 사용자 키 필요) 로만 들어온다.
임의로 생성한 값은 저장하지 않는다. 각 값에는 출처(source)가 함께 저장된다.
"""
import json
from datetime import date, datetime, timedelta

from ..util import AppError, clean_text, parse_date, rows
from . import settings
from .providers import ProviderError, ecos, fred

PROVIDERS = ("manual", "ecos", "fred")

# 프리셋은 '정의'만 만든다(값 없음). ECOS 코드는 설정의 '항목 조회'로 확인·수정할 수 있다.
PRESETS = [
    {"key": "kr_base_rate", "name": "한국 기준금리", "unit": "%", "frequency": "수시(금통위)", "decimals": 2,
     "source": "한국은행 ECOS", "source_url": "https://ecos.bok.or.kr", "provider": "ecos",
     "provider_config": {"stat_code": "722Y001", "cycle": "D", "item_code1": "0101000"}},
    {"key": "usdkrw", "name": "원/달러 환율", "unit": "원", "frequency": "일", "decimals": 1,
     "source": "한국은행 ECOS", "source_url": "https://ecos.bok.or.kr", "provider": "ecos",
     "provider_config": {"stat_code": "731Y001", "cycle": "D", "item_code1": "0000001"}},
    {"key": "kr_cpi", "name": "소비자물가지수", "unit": "2020=100", "frequency": "월", "decimals": 2,
     "source": "한국은행 ECOS(통계청)", "source_url": "https://ecos.bok.or.kr", "provider": "ecos",
     "provider_config": {"stat_code": "901Y009", "cycle": "M", "item_code1": "0"}},
    {"key": "kospi", "name": "KOSPI", "unit": "pt", "frequency": "일", "decimals": 2,
     "source": "한국은행 ECOS", "source_url": "https://ecos.bok.or.kr", "provider": "ecos",
     "provider_config": {"stat_code": "802Y001", "cycle": "D", "item_code1": "0001000"}},
    {"key": "kr_treasury_3y", "name": "국고채 3년 금리", "unit": "%", "frequency": "일", "decimals": 3,
     "source": "한국은행 ECOS", "source_url": "https://ecos.bok.or.kr", "provider": "ecos",
     "provider_config": {"stat_code": "817Y002", "cycle": "D", "item_code1": "010200000"}},
    {"key": "sp500", "name": "S&P 500", "unit": "pt", "frequency": "일", "decimals": 2,
     "source": "FRED (S&P Dow Jones Indices)", "source_url": "https://fred.stlouisfed.org/series/SP500",
     "provider": "fred", "provider_config": {"series_id": "SP500"}},
    {"key": "us_10y", "name": "미국 10년 국채 금리", "unit": "%", "frequency": "일", "decimals": 2,
     "source": "FRED", "source_url": "https://fred.stlouisfed.org/series/DGS10",
     "provider": "fred", "provider_config": {"series_id": "DGS10"}},
    {"key": "fed_funds", "name": "미국 연방기금금리(실효)", "unit": "%", "frequency": "일", "decimals": 2,
     "source": "FRED", "source_url": "https://fred.stlouisfed.org/series/DFF",
     "provider": "fred", "provider_config": {"series_id": "DFF"}},
    {"key": "us_cpi", "name": "미국 CPI", "unit": "1982-84=100", "frequency": "월", "decimals": 2,
     "source": "FRED (BLS)", "source_url": "https://fred.stlouisfed.org/series/CPIAUCSL",
     "provider": "fred", "provider_config": {"series_id": "CPIAUCSL"}},
]


def _decorate(ind: dict, conn) -> dict:
    ind["provider_config"] = json.loads(ind.get("provider_config") or "{}")
    ind["is_active"] = bool(ind["is_active"])
    last = conn.execute(
        "SELECT date, value, source, updated_at FROM indicator_values WHERE indicator_id=? ORDER BY date DESC LIMIT 2",
        (ind["id"],),
    ).fetchall()
    ind["current"] = dict(last[0]) if last else None
    ind["previous"] = dict(last[1]) if len(last) > 1 else None
    if len(last) > 1:
        ind["change"] = last[0]["value"] - last[1]["value"]
        ind["change_pct"] = (ind["change"] / last[1]["value"] * 100) if last[1]["value"] else None
    else:
        ind["change"] = ind["change_pct"] = None
    ind["value_count"] = conn.execute("SELECT COUNT(*) FROM indicator_values WHERE indicator_id=?", (ind["id"],)).fetchone()[0]
    ind["last_updated"] = conn.execute(
        "SELECT MAX(updated_at) FROM indicator_values WHERE indicator_id=?", (ind["id"],)).fetchone()[0]
    return ind


def list_indicators(conn) -> list[dict]:
    return [_decorate(r, conn) for r in rows(conn.execute("SELECT * FROM indicators ORDER BY sort_order, id"))]


def get_indicator(conn, iid: int) -> dict:
    r = conn.execute("SELECT * FROM indicators WHERE id=?", (iid,)).fetchone()
    if not r:
        raise AppError("지표를 찾을 수 없습니다.")
    return _decorate(dict(r), conn)


def save_indicator(conn, data: dict, iid: int | None = None) -> dict:
    current = dict(conn.execute("SELECT * FROM indicators WHERE id=?", (iid,)).fetchone() or {}) if iid else {}
    if iid and not current:
        raise AppError("지표를 찾을 수 없습니다.")
    d = {**current, **data}
    name = clean_text(d.get("name"), 60)
    if not name:
        raise AppError("지표명을 입력하세요.")
    provider = d.get("provider") or "manual"
    if provider not in PROVIDERS:
        raise AppError("데이터 공급자가 올바르지 않습니다.")
    cfg = d.get("provider_config") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg or "{}")
        except json.JSONDecodeError:
            raise AppError("공급자 설정(JSON)이 올바르지 않습니다.") from None
    if provider == "ecos" and not cfg.get("stat_code"):
        raise AppError("ECOS 지표는 통계표코드가 필요합니다.")
    if provider == "fred" and not cfg.get("series_id"):
        raise AppError("FRED 지표는 시리즈 ID가 필요합니다.")
    try:
        decimals = max(0, min(6, int(d.get("decimals") if d.get("decimals") not in (None, "") else 2)))
    except (TypeError, ValueError):
        raise AppError("소수 자릿수가 올바르지 않습니다.") from None
    if conn.execute("SELECT 1 FROM indicators WHERE name=? AND id<>?", (name, iid or -1)).fetchone():
        raise AppError(f"'{name}' 지표가 이미 있습니다.")
    vals = (name, clean_text(d.get("unit"), 20), clean_text(d.get("source"), 100), clean_text(d.get("source_url"), 300),
            clean_text(d.get("frequency"), 30), provider, json.dumps(cfg, ensure_ascii=False), decimals,
            clean_text(d.get("memo"), 500), 1 if d.get("is_active", True) else 0)
    with conn:
        if iid:
            conn.execute("""UPDATE indicators SET name=?, unit=?, source=?, source_url=?, frequency=?, provider=?,
                            provider_config=?, decimals=?, memo=?, is_active=? WHERE id=?""", (*vals, iid))
        else:
            order = conn.execute("SELECT IFNULL(MAX(sort_order),0)+1 FROM indicators").fetchone()[0]
            iid = conn.execute("""INSERT INTO indicators (name, unit, source, source_url, frequency, provider,
                                  provider_config, decimals, memo, is_active, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                               (*vals, order)).lastrowid
    return get_indicator(conn, iid)


def add_preset(conn, key: str) -> dict:
    p = next((p for p in PRESETS if p["key"] == key), None)
    if not p:
        raise AppError("알 수 없는 프리셋입니다.")
    return save_indicator(conn, {k: v for k, v in p.items() if k != "key"})


def delete_indicator(conn, iid: int) -> None:
    with conn:
        conn.execute("DELETE FROM indicators WHERE id=?", (iid,))


def list_values(conn, iid: int, start: str | None = None, end: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM indicator_values WHERE indicator_id=?", [iid]
    if start:
        sql += " AND date>=?"; params.append(parse_date(start))
    if end:
        sql += " AND date<=?"; params.append(parse_date(end))
    return rows(conn.execute(sql + " ORDER BY date", params))


def set_value(conn, iid: int, d: str, value, source: str = "manual") -> dict:
    get_indicator(conn, iid)
    d = parse_date(d, "날짜")
    try:
        v = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise AppError("값은 숫자여야 합니다.") from None
    if v != v or v in (float("inf"), float("-inf")):
        raise AppError("값이 올바르지 않습니다.")
    with conn:
        conn.execute("""INSERT INTO indicator_values (indicator_id, date, value, source) VALUES (?,?,?,?)
                        ON CONFLICT(indicator_id, date) DO UPDATE SET value=excluded.value, source=excluded.source,
                        updated_at=datetime('now','localtime')""", (iid, d, v, source))
    return {"indicator_id": iid, "date": d, "value": v, "source": source}


def delete_value(conn, iid: int, d: str) -> None:
    with conn:
        conn.execute("DELETE FROM indicator_values WHERE indicator_id=? AND date=?", (iid, d))


def _fetcher(provider: str):
    return {"ecos": (ecos.fetch, "ecos_api_key"), "fred": (fred.fetch, "fred_api_key")}[provider]


def refresh(conn, iid: int, full: bool = False) -> dict:
    """공식 API 에서 값을 가져와 저장한다. 실패해도 기존 값은 그대로 둔다."""
    ind = get_indicator(conn, iid)
    if ind["provider"] == "manual":
        raise AppError("수동 입력 지표는 자동 업데이트 대상이 아닙니다.")
    fn, key_name = _fetcher(ind["provider"])
    since = None
    if not full and ind["current"]:
        since = date.fromisoformat(ind["current"]["date"]) - timedelta(days=40)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        values = fn(settings.get(conn, key_name) or "", ind["provider_config"], since)
    except ProviderError as e:
        with conn:
            conn.execute("UPDATE indicators SET last_fetched_at=?, last_error=? WHERE id=?", (now, str(e), iid))
        raise AppError(f"'{ind['name']}' 업데이트 실패: {e}") from None
    with conn:
        for d, v in values:
            conn.execute("""INSERT INTO indicator_values (indicator_id, date, value, source) VALUES (?,?,?,?)
                            ON CONFLICT(indicator_id, date) DO UPDATE SET value=excluded.value, source=excluded.source,
                            updated_at=datetime('now','localtime')""", (iid, d, v, ind["provider"]))
        conn.execute("UPDATE indicators SET last_fetched_at=?, last_error=NULL WHERE id=?", (now, iid))
    return {"indicator_id": iid, "fetched": len(values)}


def refresh_all(conn) -> dict:
    results = []
    for ind in list_indicators(conn):
        if ind["provider"] == "manual" or not ind["is_active"]:
            continue
        try:
            r = refresh(conn, ind["id"])
            results.append({"id": ind["id"], "name": ind["name"], "ok": True, "fetched": r["fetched"]})
        except AppError as e:
            results.append({"id": ind["id"], "name": ind["name"], "ok": False, "error": str(e)})
    return {"results": results}
