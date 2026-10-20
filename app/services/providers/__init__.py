"""외부 공식 데이터 소스 연동.

모든 공급자는 사용자가 설정에서 입력한 본인 API 키를 사용한다. 키가 없거나 호출에 실패하면
예외(ProviderError)를 내고, 기존 데이터·수동 입력 기능에는 영향을 주지 않는다.
"""
import json
import urllib.error
import urllib.parse
import urllib.request


class ProviderError(Exception):
    pass


def http_get_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "AssetManager/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP 오류 {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ProviderError(f"네트워크 오류: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("응답을 해석할 수 없습니다(JSON 아님).") from None


def quote(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")
