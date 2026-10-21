"""서버 사용자 문구 카탈로그(한국어).

이 모듈은 app 패키지의 다른 모듈을 import 하지 않는다(의존성 최하위).
- MESSAGES : 오류 코드("영역.내용") -> 한국어 템플릿. 템플릿은 str.format 자리표시자를 쓴다.
"""

MESSAGES: dict[str, str] = {
    # ── 값 검증(util) ──
    "value.month_format": "{field} 형식이 올바르지 않습니다(YYYY-MM): '{value}'",
    "value.month_invalid": "{field} 값이 올바르지 않습니다: '{value}'",
    "value.required": "{field}을(를) 입력하세요.",
    "value.date_format": "{field} 형식이 올바르지 않습니다(YYYY-MM-DD): '{value}'",
    "value.date_nonexistent": "존재하지 않는 날짜입니다: '{value}'",
    "value.invalid": "{field} 값이 올바르지 않습니다.",
    "value.not_number": "{field}은(는) 숫자여야 합니다: '{value}'",
    "value.not_integer_won": "{field}은(는) 원 단위 정수여야 합니다: '{value}'",
    "value.negative": "{field}은(는) 0 이상이어야 합니다.",
    "value.zero": "{field}은(는) 0이 될 수 없습니다.",
    "value.too_large": "{field}이(가) 너무 큽니다.",
    "value.not_positive": "{field}은(는) 0보다 커야 합니다.",
    "period.too_long": "기간이 너무 깁니다.",
    "text.too_long": "텍스트가 너무 깁니다(최대 {max_len}자).",

    # ── 기록(records) ──
    "record.invalid_kind": "기록 구분이 올바르지 않습니다(income/plan/expense).",
    "record.invalid_kind_short": "기록 구분이 올바르지 않습니다.",
    "record.category_missing": "선택한 항목이 존재하지 않습니다.",
    "record.kind_mismatch": "수입은 소득 항목에, 지출 계획·실제 지출은 지출 항목에만 기록할 수 있습니다.",
    "record.income_month_required": "입금일 또는 예산 월을 입력하세요.",
    "record.expense_month_required": "월 또는 발생일을 입력하세요.",
    "record.settle_before_txn": "결제일은 발생일보다 빠를 수 없습니다.",
    "record.not_found": "기록을 찾을 수 없습니다.",
    "record.move_invalid_ids": "옮길 기록 목록이 올바르지 않습니다.",
    "record.move_empty": "옮길 기록을 하나 이상 고르세요.",
    "record.move_mixed": "소득 기록과 지출 기록은 함께 옮길 수 없습니다.",
    "record.move_select_target": "옮겨 갈 항목을 고르세요.",
    "record.move_target_missing": "옮겨 갈 항목이 존재하지 않습니다.",
    "record.move_kind_mismatch": "소득 기록은 소득 항목으로, 지출 기록은 지출 항목으로만 옮길 수 있습니다.",
    "record.delete_invalid_ids": "삭제할 기록 목록이 올바르지 않습니다.",

    # ── 항목(categories) ──
    "category.select": "항목을 선택하세요.",
    "category.not_found": "항목을 찾을 수 없습니다.",
    "category.name_required": "항목 이름을 입력하세요.",
    "category.invalid_kind": "항목 종류는 소득(income) 또는 지출(expense)이어야 합니다.",
    "category.kind_locked": "기록이 있는 항목은 소득/지출 종류를 바꿀 수 없습니다.",
    "category.invalid_color": "색상은 #RRGGBB 형식이어야 합니다.",
    "category.duplicate_income": "소득 항목에 '{name}'이(가) 이미 있습니다.",
    "category.duplicate_expense": "지출 항목에 '{name}'이(가) 이미 있습니다.",
    "category.has_records": "이 항목에는 기록 {count}건이 있습니다. 기록과 함께 삭제하려면 다시 확인하세요.",
    "category.delete_invalid_ids": "삭제할 항목 목록이 올바르지 않습니다.",

    # ── 월 예산(budget) ──
    "budget.category_missing": "항목이 존재하지 않습니다.",
    "budget.not_income_category": "소득 항목이 아닙니다.",
    "budget.not_expense_category": "지출 항목이 아닙니다.",
    "budget.move_same": "같은 항목으로는 옮길 수 없습니다.",
    "budget.move_over_unallocated": "옮길 금액이 미배분 금액({amount:,}원)보다 큽니다.",
    "budget.move_over_plan": "옮길 금액이 보내는 항목의 계획({amount:,}원)보다 큽니다.",
    "budget.settle_select_target": "남은 돈을 보낼 항목을 고르세요.",
    "budget.settle_no_income": "이 달 예산으로 잡힌 소득이 없습니다.",
    "budget.settle_overspent": "소득보다 {amount:,}원 더 지출했습니다. 부족분을 소득으로 기록(예: 저축에서 인출)한 뒤 정산하세요.",
    "budget.copy_nothing_selected": "불러올 것을 하나 이상 고르세요.",
    "budget.copy_empty": "{month}에 불러올 내용이 없습니다.",

    # ── 통계(stats) ──
    "stats.invalid_basis": "집계 기준이 올바르지 않습니다(budget/cash).",
    "stats.invalid_year": "연도가 올바르지 않습니다.",

    # ── 백업·초기화(backup) ──
    "backup.invalid_name": "백업 파일 이름이 올바르지 않습니다.",
    "backup.not_found": "백업 파일을 찾을 수 없습니다.",
    "backup.unreadable": "백업 파일을 읽을 수 없습니다.",
    "backup.not_sqlite": "SQLite 데이터베이스 파일이 아닙니다.",
    "backup.cannot_open": "백업 파일을 열 수 없습니다: {error}",
    "backup.corrupt": "백업 파일이 손상되었습니다: {detail}",
    "backup.newer_version": "더 새로운 버전(v{version})의 프로그램에서 만든 백업입니다. 프로그램을 업데이트하세요.",
    "backup.no_version": "이 프로그램의 백업 파일이 아닙니다(스키마 버전 없음).",
    "backup.missing_tables": "필수 테이블이 없습니다: {tables}",
    "backup.cannot_inspect": "백업 파일을 검사할 수 없습니다: {error}",
    "backup.empty_upload": "파일이 비어 있습니다.",
    "reset.invalid_mode": "초기화 방식이 올바르지 않습니다.",

    # ── CSV(csvio) ──
    "csv.too_large": "파일이 너무 큽니다(최대 20MB).",
    "csv.bad_encoding": "파일 인코딩을 인식할 수 없습니다. UTF-8 또는 CP949(ANSI)로 저장하세요.",
    "csv.empty_file": "빈 파일입니다.",
    "csv.missing_columns": "필수 열이 없습니다: {columns}  (첫 행은 열 이름이어야 합니다)",
    "csv.too_many_rows": "행이 너무 많습니다(최대 {max_rows}행).",
    "csv.category_empty": "항목이 비어 있습니다.",
    "csv.income_category_missing": "소득 항목 '{name}'이(가) 없습니다. 설정에서 만들거나 '없는 항목 자동 생성'을 선택하세요.",
    "csv.expense_category_missing": "지출 항목 '{name}'이(가) 없습니다. 설정에서 만들거나 '없는 항목 자동 생성'을 선택하세요.",
    "csv.unknown_record_kind": "구분 값 '{value}'을(를) 알 수 없습니다(수입/지출계획/실제지출).",
    "csv.account_missing": "{field} '{name}'이(가) 없습니다. 자산 관리에서 먼저 계좌를 만드세요.",
    "csv.unknown_txn_kind": "유형 '{value}'을(를) 알 수 없습니다.",
    "csv.security_missing": "종목 '{symbol}'이(가) 등록되어 있지 않습니다.",
    "csv.indicator_not_found": "지표를 찾을 수 없습니다.",
    "csv.value_not_number": "값 '{value}'은(는) 숫자가 아닙니다.",
    "csv.unknown_template": "알 수 없는 템플릿입니다.",

    # ── 설정(settings) ──
    "settings.unknown_key": "알 수 없는 설정입니다: {key}",
    "settings.invalid_value": "'{key}' 값이 올바르지 않습니다.",

    # ── 서버(server) ──
    "http.forbidden": "허용되지 않은 요청입니다.",
    "server.unknown_folder": "알 수 없는 폴더입니다.",
    "db.foreign_key": "다른 기록이 참조하고 있어 처리할 수 없습니다.",
    "db.unique": "이미 같은 값이 존재합니다.",
    "db.integrity": "데이터 무결성 오류: {detail}",
    "db.operational": "데이터베이스 오류로 저장하지 못했습니다: {detail}",
}


def text(code: str, **params) -> str:
    """오류 코드를 한국어 문장으로 만든다. 모르는 code 는 KeyError."""
    return MESSAGES[code].format(**params)
