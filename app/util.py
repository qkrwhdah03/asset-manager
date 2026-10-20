"""공통 검증·변환 유틸리티."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation


class AppError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 검증 오류."""


MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_month(value, field: str = "월") -> str:
    s = str(value or "").strip().replace(".", "-").replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if not m:
        raise AppError(f"{field} 형식이 올바르지 않습니다(YYYY-MM): '{value}'")
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12) or not (1900 <= y <= 2999):
        raise AppError(f"{field} 값이 올바르지 않습니다: '{value}'")
    return f"{y:04d}-{mo:02d}"


def parse_date(value, field: str = "날짜", required: bool = True) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            raise AppError(f"{field}을(를) 입력하세요.")
        return None
    s = str(value).strip().replace(".", "-").replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if not m:
        raise AppError(f"{field} 형식이 올바르지 않습니다(YYYY-MM-DD): '{value}'")
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise AppError(f"존재하지 않는 날짜입니다: '{value}'") from None
    return d.isoformat()


def parse_amount(value, field: str = "금액", allow_negative: bool = False, allow_zero: bool = True) -> int:
    """원화 금액을 정수로 변환한다. '1,234원', ' 1234 ' 등을 허용한다. 소수는 거부한다."""
    if isinstance(value, bool):
        raise AppError(f"{field} 값이 올바르지 않습니다.")
    if isinstance(value, int):
        n = value
    else:
        s = str(value if value is not None else "").strip().replace(",", "").replace("원", "").replace(" ", "")
        if s == "":
            raise AppError(f"{field}을(를) 입력하세요.")
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise AppError(f"{field}은(는) 숫자여야 합니다: '{value}'") from None
        if d != d.to_integral_value():
            raise AppError(f"{field}은(는) 원 단위 정수여야 합니다: '{value}'")
        n = int(d)
    if not allow_negative and n < 0:
        raise AppError(f"{field}은(는) 0 이상이어야 합니다.")
    if not allow_zero and n == 0:
        raise AppError(f"{field}은(는) 0이 될 수 없습니다.")
    if abs(n) > 10**15:
        raise AppError(f"{field}이(가) 너무 큽니다.")
    return n


def parse_decimal(value, field: str, positive: bool = True) -> Decimal:
    s = str(value if value is not None else "").strip().replace(",", "")
    if s == "":
        raise AppError(f"{field}을(를) 입력하세요.")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise AppError(f"{field}은(는) 숫자여야 합니다: '{value}'") from None
    if not d.is_finite():
        raise AppError(f"{field} 값이 올바르지 않습니다.")
    if positive and d <= 0:
        raise AppError(f"{field}은(는) 0보다 커야 합니다.")
    return d


def dec_str(d: Decimal) -> str:
    """Decimal 을 지수 표기 없이 정규화된 문자열로."""
    s = format(d.normalize(), "f")
    return s


def month_of(d: str | None) -> str | None:
    return d[:7] if d else None


def add_months(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    if start > end:
        start, end = end, start
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
        if len(out) > 1200:
            raise AppError("기간이 너무 깁니다.")
    return out


def month_end(month: str) -> str:
    nxt = add_months(month, 1)
    y, m = int(nxt[:4]), int(nxt[5:7])
    from datetime import timedelta
    return (date(y, m, 1) - timedelta(days=1)).isoformat()


def clean_text(value, max_len: int = 500) -> str:
    s = str(value or "").strip()
    if len(s) > max_len:
        raise AppError(f"텍스트가 너무 깁니다(최대 {max_len}자).")
    return s


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
