"""서버 번역 카탈로그(한국어/영어).

이 모듈은 app 패키지의 다른 모듈을 import 하지 않는다(의존성 최하위).
- MESSAGES : 오류 코드 -> {"ko": 템플릿, "en": 템플릿}. 템플릿은 str.format 자리표시자를 쓴다.
- FIELD_LABELS : util.parse_* 등에 넘기는 한국어 필드 라벨 -> 영어 라벨. tr(..., "en") 에서 field 파라미터만 바꾼다.
- DEFAULT_CATEGORY_NAMES / DEFAULT_ASSET_TYPE_NAMES : 새로 설치할 때 영어로 바꿀 기본 이름.
"""

LANGUAGES = ("ko", "en")
DEFAULT_LANGUAGE = "ko"

MESSAGES: dict[str, dict[str, str]] = {
    # ── 값 검증(util) ──
    "value.month_format": {"ko": "{field} 형식이 올바르지 않습니다(YYYY-MM): '{value}'",
                           "en": "{field} has an invalid format (YYYY-MM): '{value}'"},
    "value.month_invalid": {"ko": "{field} 값이 올바르지 않습니다: '{value}'",
                            "en": "{field} has an invalid value: '{value}'"},
    "value.required": {"ko": "{field}을(를) 입력하세요.",
                       "en": "Please enter {field}."},
    "value.date_format": {"ko": "{field} 형식이 올바르지 않습니다(YYYY-MM-DD): '{value}'",
                          "en": "{field} has an invalid format (YYYY-MM-DD): '{value}'"},
    "value.date_nonexistent": {"ko": "존재하지 않는 날짜입니다: '{value}'",
                               "en": "This date does not exist: '{value}'"},
    "value.invalid": {"ko": "{field} 값이 올바르지 않습니다.",
                      "en": "{field} has an invalid value."},
    "value.not_number": {"ko": "{field}은(는) 숫자여야 합니다: '{value}'",
                         "en": "{field} must be a number: '{value}'"},
    "value.not_integer_won": {"ko": "{field}은(는) 원 단위 정수여야 합니다: '{value}'",
                              "en": "{field} must be a whole number of won: '{value}'"},
    "value.negative": {"ko": "{field}은(는) 0 이상이어야 합니다.",
                       "en": "{field} must be 0 or more."},
    "value.zero": {"ko": "{field}은(는) 0이 될 수 없습니다.",
                   "en": "{field} cannot be 0."},
    "value.too_large": {"ko": "{field}이(가) 너무 큽니다.",
                        "en": "{field} is too large."},
    "value.not_positive": {"ko": "{field}은(는) 0보다 커야 합니다.",
                           "en": "{field} must be greater than 0."},
    "period.too_long": {"ko": "기간이 너무 깁니다.",
                        "en": "The period is too long."},
    "text.too_long": {"ko": "텍스트가 너무 깁니다(최대 {max_len}자).",
                      "en": "The text is too long (max {max_len} characters)."},

    # ── 기록(records) ──
    "record.invalid_kind": {"ko": "기록 구분이 올바르지 않습니다(income/plan/expense).",
                            "en": "Invalid record type (income/plan/expense)."},
    "record.invalid_kind_short": {"ko": "기록 구분이 올바르지 않습니다.",
                                  "en": "Invalid record type."},
    "record.category_missing": {"ko": "선택한 항목이 존재하지 않습니다.",
                                "en": "The selected category does not exist."},
    "record.kind_mismatch": {"ko": "수입은 소득 항목에, 지출 계획·실제 지출은 지출 항목에만 기록할 수 있습니다.",
                             "en": "Income can only go to income categories, and plans/expenses only to expense categories."},
    "record.income_month_required": {"ko": "입금일 또는 예산 월을 입력하세요.",
                                     "en": "Please enter the paid date or the budget month."},
    "record.expense_month_required": {"ko": "월 또는 발생일을 입력하세요.",
                                      "en": "Please enter the month or the date."},
    "record.settle_before_txn": {"ko": "결제일은 발생일보다 빠를 수 없습니다.",
                                 "en": "The settle date cannot be earlier than the date."},
    "record.not_found": {"ko": "기록을 찾을 수 없습니다.",
                         "en": "Record not found."},
    "record.move_invalid_ids": {"ko": "옮길 기록 목록이 올바르지 않습니다.",
                                "en": "The list of records to move is invalid."},
    "record.move_empty": {"ko": "옮길 기록을 하나 이상 고르세요.",
                          "en": "Select at least one record to move."},
    "record.move_mixed": {"ko": "소득 기록과 지출 기록은 함께 옮길 수 없습니다.",
                          "en": "Income records and expense records cannot be moved together."},
    "record.move_select_target": {"ko": "옮겨 갈 항목을 고르세요.",
                                  "en": "Select the category to move to."},
    "record.move_target_missing": {"ko": "옮겨 갈 항목이 존재하지 않습니다.",
                                   "en": "The target category does not exist."},
    "record.move_kind_mismatch": {"ko": "소득 기록은 소득 항목으로, 지출 기록은 지출 항목으로만 옮길 수 있습니다.",
                                  "en": "Income records can only move to income categories, and expense records to expense categories."},
    "record.delete_invalid_ids": {"ko": "삭제할 기록 목록이 올바르지 않습니다.",
                                  "en": "The list of records to delete is invalid."},

    # ── 항목(categories) ──
    "category.select": {"ko": "항목을 선택하세요.",
                        "en": "Please select a category."},
    "category.not_found": {"ko": "항목을 찾을 수 없습니다.",
                           "en": "Category not found."},
    "category.name_required": {"ko": "항목 이름을 입력하세요.",
                               "en": "Please enter a category name."},
    "category.invalid_kind": {"ko": "항목 종류는 소득(income) 또는 지출(expense)이어야 합니다.",
                              "en": "Category kind must be income or expense."},
    "category.kind_locked": {"ko": "기록이 있는 항목은 소득/지출 종류를 바꿀 수 없습니다.",
                             "en": "A category with records cannot switch between income and expense."},
    "category.invalid_color": {"ko": "색상은 #RRGGBB 형식이어야 합니다.",
                               "en": "Color must be in #RRGGBB format."},
    "category.duplicate_income": {"ko": "소득 항목에 '{name}'이(가) 이미 있습니다.",
                                  "en": "An income category named '{name}' already exists."},
    "category.duplicate_expense": {"ko": "지출 항목에 '{name}'이(가) 이미 있습니다.",
                                   "en": "An expense category named '{name}' already exists."},
    "category.has_records": {"ko": "이 항목에는 기록 {count}건이 있습니다. 기록과 함께 삭제하려면 다시 확인하세요.",
                             "en": "This category has {count} record(s). Confirm again to delete it together with its records."},
    "category.delete_invalid_ids": {"ko": "삭제할 항목 목록이 올바르지 않습니다.",
                                    "en": "The list of categories to delete is invalid."},

    # ── 월 예산(budget) ──
    "budget.category_missing": {"ko": "항목이 존재하지 않습니다.",
                                "en": "The category does not exist."},
    "budget.not_income_category": {"ko": "소득 항목이 아닙니다.",
                                   "en": "This is not an income category."},
    "budget.not_expense_category": {"ko": "지출 항목이 아닙니다.",
                                    "en": "This is not an expense category."},
    "budget.move_same": {"ko": "같은 항목으로는 옮길 수 없습니다.",
                         "en": "Cannot move to the same category."},
    "budget.move_over_unallocated": {"ko": "옮길 금액이 미배분 금액({amount:,}원)보다 큽니다.",
                                     "en": "The amount is larger than the unassigned money (₩{amount:,})."},
    "budget.move_over_plan": {"ko": "옮길 금액이 보내는 항목의 계획({amount:,}원)보다 큽니다.",
                              "en": "The amount is larger than the plan of the source category (₩{amount:,})."},
    "budget.settle_select_target": {"ko": "남은 돈을 보낼 항목을 고르세요.",
                                    "en": "Select the category to receive the leftover money."},
    "budget.settle_no_income": {"ko": "이 달 예산으로 잡힌 소득이 없습니다.",
                                "en": "There is no income budgeted for this month."},
    "budget.settle_overspent": {"ko": "소득보다 {amount:,}원 더 지출했습니다. 부족분을 소득으로 기록(예: 저축에서 인출)한 뒤 정산하세요.",
                                "en": "You spent ₩{amount:,} more than your income. Record the shortfall as income (e.g. a withdrawal from savings) and settle again."},
    "budget.copy_nothing_selected": {"ko": "불러올 것을 하나 이상 고르세요.",
                                     "en": "Select at least one thing to copy."},
    "budget.copy_empty": {"ko": "{month}에 불러올 내용이 없습니다.",
                          "en": "There is nothing to copy from {month}."},

    # ── 통계(stats) ──
    "stats.invalid_basis": {"ko": "집계 기준이 올바르지 않습니다(budget/cash).",
                            "en": "Invalid basis (budget/cash)."},
    "stats.invalid_year": {"ko": "연도가 올바르지 않습니다.",
                           "en": "Invalid year."},

    # ── 백업·초기화(backup) ──
    "backup.invalid_name": {"ko": "백업 파일 이름이 올바르지 않습니다.",
                            "en": "Invalid backup file name."},
    "backup.not_found": {"ko": "백업 파일을 찾을 수 없습니다.",
                         "en": "Backup file not found."},
    "backup.unreadable": {"ko": "백업 파일을 읽을 수 없습니다.",
                          "en": "Cannot read the backup file."},
    "backup.not_sqlite": {"ko": "SQLite 데이터베이스 파일이 아닙니다.",
                          "en": "This is not a SQLite database file."},
    "backup.cannot_open": {"ko": "백업 파일을 열 수 없습니다: {error}",
                           "en": "Cannot open the backup file: {error}"},
    "backup.corrupt": {"ko": "백업 파일이 손상되었습니다: {detail}",
                       "en": "The backup file is corrupted: {detail}"},
    "backup.newer_version": {"ko": "더 새로운 버전(v{version})의 프로그램에서 만든 백업입니다. 프로그램을 업데이트하세요.",
                             "en": "This backup was made by a newer version of the program (v{version}). Please update the program."},
    "backup.no_version": {"ko": "이 프로그램의 백업 파일이 아닙니다(스키마 버전 없음).",
                          "en": "This is not a backup file of this program (no schema version)."},
    "backup.missing_tables": {"ko": "필수 테이블이 없습니다: {tables}",
                              "en": "Required tables are missing: {tables}"},
    "backup.cannot_inspect": {"ko": "백업 파일을 검사할 수 없습니다: {error}",
                              "en": "Cannot check the backup file: {error}"},
    "backup.empty_upload": {"ko": "파일이 비어 있습니다.",
                            "en": "The file is empty."},
    "reset.invalid_mode": {"ko": "초기화 방식이 올바르지 않습니다.",
                           "en": "Invalid reset mode."},

    # ── CSV(csvio) ──
    "csv.too_large": {"ko": "파일이 너무 큽니다(최대 20MB).",
                      "en": "The file is too large (max 20MB)."},
    "csv.bad_encoding": {"ko": "파일 인코딩을 인식할 수 없습니다. UTF-8 또는 CP949(ANSI)로 저장하세요.",
                         "en": "Cannot detect the file encoding. Save it as UTF-8 or CP949 (ANSI)."},
    "csv.empty_file": {"ko": "빈 파일입니다.",
                       "en": "The file is empty."},
    "csv.missing_columns": {"ko": "필수 열이 없습니다: {columns}  (첫 행은 열 이름이어야 합니다)",
                            "en": "Required columns are missing: {columns}  (the first row must be column names)"},
    "csv.too_many_rows": {"ko": "행이 너무 많습니다(최대 {max_rows}행).",
                          "en": "Too many rows (max {max_rows})."},
    "csv.category_empty": {"ko": "항목이 비어 있습니다.",
                           "en": "Category is empty."},
    "csv.income_category_missing": {"ko": "소득 항목 '{name}'이(가) 없습니다. 설정에서 만들거나 '없는 항목 자동 생성'을 선택하세요.",
                                    "en": "Income category '{name}' does not exist. Create it in Settings or choose to create missing categories."},
    "csv.expense_category_missing": {"ko": "지출 항목 '{name}'이(가) 없습니다. 설정에서 만들거나 '없는 항목 자동 생성'을 선택하세요.",
                                     "en": "Expense category '{name}' does not exist. Create it in Settings or choose to create missing categories."},
    "csv.unknown_record_kind": {"ko": "구분 값 '{value}'을(를) 알 수 없습니다(수입/지출계획/실제지출).",
                                "en": "Unknown type '{value}' (Income/Plan/Expense)."},
    "csv.account_missing": {"ko": "{field} '{name}'이(가) 없습니다. 자산 관리에서 먼저 계좌를 만드세요.",
                            "en": "{field} '{name}' does not exist. Create the account in asset management first."},
    "csv.unknown_txn_kind": {"ko": "유형 '{value}'을(를) 알 수 없습니다.",
                             "en": "Unknown type '{value}'."},
    "csv.security_missing": {"ko": "종목 '{symbol}'이(가) 등록되어 있지 않습니다.",
                             "en": "Security '{symbol}' is not registered."},
    "csv.indicator_not_found": {"ko": "지표를 찾을 수 없습니다.",
                                "en": "Indicator not found."},
    "csv.value_not_number": {"ko": "값 '{value}'은(는) 숫자가 아닙니다.",
                             "en": "Value '{value}' is not a number."},
    "csv.unknown_template": {"ko": "알 수 없는 템플릿입니다.",
                             "en": "Unknown template."},

    # ── 설정(settings) ──
    "settings.unknown_key": {"ko": "알 수 없는 설정입니다: {key}",
                             "en": "Unknown setting: {key}"},
    "settings.invalid_value": {"ko": "'{key}' 값이 올바르지 않습니다.",
                               "en": "Invalid value for '{key}'."},

    # ── 서버(server) ──
    "server.unknown_folder": {"ko": "알 수 없는 폴더입니다.",
                              "en": "Unknown folder."},
    "db.foreign_key": {"ko": "다른 기록이 참조하고 있어 처리할 수 없습니다.",
                       "en": "Cannot do this because other records refer to it."},
    "db.unique": {"ko": "이미 같은 값이 존재합니다.",
                  "en": "The same value already exists."},
    "db.integrity": {"ko": "데이터 무결성 오류: {detail}",
                     "en": "Data integrity error: {detail}"},
    "db.operational": {"ko": "데이터베이스 오류로 저장하지 못했습니다: {detail}",
                       "en": "Could not save because of a database error: {detail}"},
}

FIELD_LABELS: dict[str, str] = {
    "월": "Month",
    "금액": "Amount",
    "날짜": "Date",
    "입금일": "Paid date",
    "지출일": "Spent date",
    "발생일": "Date",
    "결제일": "Settle date",
    "예산월": "Budget month",
    "예산 월": "Budget month",
    "계획 월": "Plan month",
    "항목": "Category",
    "세부항목": "Item",
    "메모": "Memo",
    "이름": "Name",
    "옮길 금액": "Amount to move",
    "계획 금액": "Plan amount",
    "가격": "Price",
    "기준일": "As-of date",
    "수수료": "Fee",
    "수량": "Quantity",
    "단가": "Unit price",
    "값": "Value",
    "계좌": "Account",
    "상대계좌": "Counter account",
}

DEFAULT_CATEGORY_NAMES: dict[str, str] = {
    "급여": "Salary",
    "장학금": "Scholarship",
    "식비": "Food",
    "교통비": "Transportation",
    "주거·관리비": "Housing & Utilities",
    "통신비": "Phone & Internet",
    "구독료": "Subscriptions",
    "취미": "Hobbies",
    "의료비": "Medical",
    "기타": "Other",
    "저축·투자": "Savings & Investment",
}

DEFAULT_ASSET_TYPE_NAMES: dict[str, str] = {
    "현금": "Cash",
    "은행 예금·적금": "Bank deposits",
    "주식": "Stocks",
    "ETF": "ETF",
    "기타 금융자산": "Other financial assets",
    "기타 자산": "Other assets",
}


def normalize(lang: str | None) -> str:
    """'EN ' -> 'en'. 지원하지 않는 값(None·빈 값·'fr' 등)은 기본 언어(ko)."""
    s = str(lang or "").strip().lower()
    return s if s in LANGUAGES else DEFAULT_LANGUAGE


def tr(code: str, lang: str, **params) -> str:
    """오류 코드를 lang 언어 문장으로 만든다. 모르는 code 는 KeyError."""
    templates = MESSAGES[code]
    lang = normalize(lang)
    if lang == "en" and "field" in params:
        params = {**params, "field": FIELD_LABELS.get(params["field"], params["field"])}
    return templates.get(lang, templates[DEFAULT_LANGUAGE]).format(**params)
