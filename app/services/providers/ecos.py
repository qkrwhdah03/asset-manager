"""한국은행 ECOS Open API (https://ecos.bok.or.kr/api/).

- 인증키: ECOS 홈페이지에서 무료 발급(개인 가능). 설정 화면에서 입력.
- StatisticSearch: /api/StatisticSearch/{KEY}/json/kr/{시작}/{끝}/{통계표코드}/{주기}/{검색시작}/{검색끝}/{항목코드1}/...
- StatisticItemList: /api/StatisticItemList/{KEY}/json/kr/1/{N}/{통계표코드}  → 통계표의 항목코드·주기 확인용
주기(cycle): D(일) / M(월) / Q(분기) / A(연)
"""
from datetime import date, timedelta

from . import ProviderError, http_get_json, quote

BASE = "https://ecos.bok.or.kr/api"


def _fmt(d: date, cycle: str) -> str:
    if cycle == "D":
        return d.strftime("%Y%m%d")
    if cycle == "M":
        return d.strftime("%Y%m")
    if cycle == "Q":
        return f"{d.year}Q{(d.month - 1) // 3 + 1}"
    if cycle == "A":
        return str(d.year)
    raise ProviderError(f"지원하지 않는 주기입니다: {cycle}")


def parse_time(t: str, cycle: str) -> str:
    t = t.strip()
    if cycle == "D" and len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    if cycle == "M" and len(t) == 6:
        return f"{t[:4]}-{t[4:6]}-01"
    if cycle == "Q" and "Q" in t:
        y, q = t.split("Q")
        return f"{int(y):04d}-{(int(q) - 1) * 3 + 1:02d}-01"
    if cycle == "A" and len(t) == 4:
        return f"{t}-01-01"
    raise ProviderError(f"ECOS 시간 값을 해석할 수 없습니다: {t}")


def _check_result(data: dict) -> None:
    res = data.get("RESULT")
    if res:
        code, msg = res.get("CODE", ""), res.get("MESSAGE", "")
        if code == "INFO-200":  # 해당하는 데이터가 없음
            return
        raise ProviderError(f"ECOS 오류 {code}: {msg}")


def build_search_url(api_key: str, cfg: dict, start: date, end: date, count: int = 10000) -> str:
    stat = cfg.get("stat_code")
    cycle = (cfg.get("cycle") or "D").upper()
    if not stat:
        raise ProviderError("ECOS 통계표코드(stat_code)가 설정되지 않았습니다.")
    items = [cfg.get(f"item_code{i}") for i in (1, 2, 3)]
    items = [quote(x) for x in items if x]
    parts = [BASE, "StatisticSearch", quote(api_key), "json", "kr", "1", str(count), quote(stat), cycle,
             _fmt(start, cycle), _fmt(end, cycle), *items]
    return "/".join(parts)


def parse_search(data: dict, cycle: str) -> list[tuple[str, float]]:
    _check_result(data)
    body = data.get("StatisticSearch")
    if not body:
        return []
    _check_result(body)
    out = []
    for r in body.get("row", []):
        v = (r.get("DATA_VALUE") or "").replace(",", "").strip()
        if v in ("", "-", "."):
            continue
        try:
            out.append((parse_time(r["TIME"], cycle), float(v)))
        except (ValueError, KeyError):
            continue
    return out


def fetch(api_key: str, cfg: dict, since: date | None = None) -> list[tuple[str, float]]:
    if not api_key:
        raise ProviderError("ECOS API 키가 설정되지 않았습니다. 설정 페이지에서 입력하세요.")
    cycle = (cfg.get("cycle") or "D").upper()
    end = date.today()
    start = since or (end - timedelta(days=365 * 3))
    data = http_get_json(build_search_url(api_key, cfg, start, end))
    return parse_search(data, cycle)


def item_list(api_key: str, stat_code: str) -> list[dict]:
    if not api_key:
        raise ProviderError("ECOS API 키가 설정되지 않았습니다.")
    url = "/".join([BASE, "StatisticItemList", quote(api_key), "json", "kr", "1", "500", quote(stat_code)])
    data = http_get_json(url)
    _check_result(data)
    body = data.get("StatisticItemList") or {}
    return [{
        "item_code": r.get("ITEM_CODE"), "item_name": r.get("ITEM_NAME"), "cycle": r.get("CYCLE"),
        "start": r.get("START_TIME"), "end": r.get("END_TIME"), "unit": r.get("UNIT_NAME"),
        "stat_name": r.get("STAT_NAME"), "group": r.get("GRP_NAME"),
    } for r in body.get("row", [])]
