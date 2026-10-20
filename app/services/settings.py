"""로컬 설정(key-value). API 키는 로컬 DB 에만 저장하며 소스 코드에 넣지 않는다."""
from ..util import AppError

SECRET_KEYS = {"ecos_api_key", "fred_api_key"}
ALLOWED = {
    "ecos_api_key": None,
    "fred_api_key": None,
}


def get(conn, key: str, default: str | None = None) -> str | None:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def get_public(conn) -> dict:
    out = {}
    for k in ALLOWED:
        v = get(conn, k)
        if k in SECRET_KEYS:
            out[k + "_set"] = bool(v)
            out[k] = (v[:3] + "…" + v[-2:]) if v and len(v) > 6 else ("설정됨" if v else "")
        else:
            out[k] = v
    return out


def set_many(conn, data: dict) -> dict:
    with conn:
        for k, v in data.items():
            if k not in ALLOWED:
                raise AppError(f"알 수 없는 설정입니다: {k}")
            allowed = ALLOWED[k]
            v = (v or "").strip() if isinstance(v, str) or v is None else str(v)
            if allowed and v not in allowed:
                raise AppError(f"'{k}' 값이 올바르지 않습니다.")
            if v == "":
                conn.execute("DELETE FROM settings WHERE key=?", (k,))
            else:
                conn.execute("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (k, v))
    return get_public(conn)
