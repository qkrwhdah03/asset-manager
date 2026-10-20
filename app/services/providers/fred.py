"""미국 세인트루이스 연준 FRED API (https://fred.stlouisfed.org/docs/api/fred/).

- API 키: FRED 계정에서 무료 발급. 설정 화면에서 입력.
- series/observations?series_id=SP500&api_key=...&file_type=json&observation_start=YYYY-MM-DD
- 값이 '.' 인 관측치는 결측이므로 건너뛴다.
"""
from datetime import date, timedelta
from urllib.parse import urlencode

from . import ProviderError, http_get_json

BASE = "https://api.stlouisfed.org/fred/series/observations"


def build_url(api_key: str, series_id: str, start: date) -> str:
    return BASE + "?" + urlencode({
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start.isoformat(),
    })


def parse(data: dict) -> list[tuple[str, float]]:
    if "error_message" in data:
        raise ProviderError(f"FRED 오류: {data['error_message']}")
    out = []
    for o in data.get("observations", []):
        v = (o.get("value") or "").strip()
        if v in ("", "."):
            continue
        try:
            out.append((o["date"], float(v)))
        except (ValueError, KeyError):
            continue
    return out


def fetch(api_key: str, cfg: dict, since: date | None = None) -> list[tuple[str, float]]:
    if not api_key:
        raise ProviderError("FRED API 키가 설정되지 않았습니다. 설정 페이지에서 입력하세요.")
    series = cfg.get("series_id")
    if not series:
        raise ProviderError("FRED 시리즈 ID(series_id)가 설정되지 않았습니다.")
    start = since or (date.today() - timedelta(days=365 * 3))
    return parse(http_get_json(build_url(api_key, series, start)))
