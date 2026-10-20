// 화면 문구 번역(한국어/영어)과 현재 표시 설정. 아무것도 import 하지 않는다.
// 페이지는 이 파일을 직접 쓰지 않고 lib.js 를 통해 t / setLocale / getLocale 을 쓴다.
// 언어·표시 형식의 진실 원천은 서버 설정 DB 다(브라우저 저장소에 두지 않는다).

export const DICT = {
  ko: {
    "app.name": "개인 자산 관리",
    "app.subtitle": "월 예산 · 현금흐름",
    "app.foot": "로컬 저장 · 오프라인 동작",
    "nav.dashboard": "대시보드",
    "nav.cashflow": "월 예산 (수입·지출)",
    "nav.settings": "설정 및 데이터",

    "settings.title": "설정 및 데이터 관리",
    "settings.tab.categories": "항목",
    "settings.tab.data": "백업·복원",
    "settings.tab.csv": "CSV 가져오기·내보내기",
    "settings.tab.display": "표시",

    "display.title": "언어와 표시 형식",
    "display.language": "언어",
    "display.date_format": "날짜 표기",
    "display.currency": "금액 단위",
    "display.auto": "언어 따라",
    "display.preview": "미리보기",
    "display.preview_line": "오늘 {date} · 이번 달 {month} · {amount}",
    "display.note": "이미 만든 항목 이름은 바뀌지 않습니다. CSV는 두 언어 열 이름을 모두 읽습니다.",
    "display.saved": "표시 설정을 저장했습니다.",
  },
  en: {
    "app.name": "Asset Manager",
    "app.subtitle": "Monthly budget · Cash flow",
    "app.foot": "Stored locally · Works offline",
    "nav.dashboard": "Dashboard",
    "nav.cashflow": "Monthly budget",
    "nav.settings": "Settings & data",

    "settings.title": "Settings & data",
    "settings.tab.categories": "Categories",
    "settings.tab.data": "Backup & restore",
    "settings.tab.csv": "CSV import & export",
    "settings.tab.display": "Display",

    "display.title": "Language and formats",
    "display.language": "Language",
    "display.date_format": "Date format",
    "display.currency": "Currency",
    "display.auto": "Follow language",
    "display.preview": "Preview",
    "display.preview_line": "Today {date} · This month {month} · {amount}",
    "display.note": "Names of categories you already made do not change. CSV import reads column names in both languages.",
    "display.saved": "Display settings saved.",
  },
};

const LANGS = ["ko", "en"];
const DATE_FORMATS = ["auto", "iso", "dot", "ko", "en"];
const CURRENCIES = ["auto", "won", "symbol", "code"];

let current = { language: "ko", date_format: "auto", currency_display: "auto" };

export function setLocale(settings = {}) {
  const pick = (v, allowed, dflt) => (allowed.includes(v) ? v : dflt);
  current = {
    language: pick(String(settings.language || "").trim().toLowerCase(), LANGS, "ko"),
    date_format: pick(settings.date_format, DATE_FORMATS, "auto"),
    currency_display: pick(settings.currency_display, CURRENCIES, "auto"),
  };
}

// auto 를 풀어서 돌려준다: dateFormat auto -> 언어, currency auto -> ko: "won" / en: "symbol"
export function getLocale() {
  const language = current.language;
  const dateFormat = current.date_format === "auto" ? language : current.date_format;
  const currency = current.currency_display === "auto" ? (language === "en" ? "symbol" : "won") : current.currency_display;
  return { language, dateFormat, currency };
}

// 현재 언어 문구. 없으면 한국어, 그래도 없으면 key. {name} 자리표시자를 params 로 바꾼다.
export function t(key, params) {
  const s = DICT[current.language]?.[key] ?? DICT.ko[key] ?? key;
  if (!params) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m));
}
