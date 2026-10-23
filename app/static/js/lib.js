// 공통 유틸리티: API 호출, 포맷, 토스트, 모달, 차트, 월 선택기
import { html, render, useState, useEffect, useRef, useCallback, useMemo, createContext, useContext } from "/vendor/preact-htm.module.js";
export { html, render, useState, useEffect, useRef, useCallback, useMemo, createContext, useContext };

// ───────── API ─────────
export class ApiError extends Error {}

// 데이터가 바뀌었다는 앱 전체 신호. 저장·추가·삭제 요청이 성공하면 보내고,
// 화면·표·항목 목록은 이 신호를 받으면 바로 다시 불러온다(짧은 시간에 여러 번 와도 한 번으로 합침).
// 합쳐진 요청들의 tag 목록을 함께 넘긴다(tag 없는 요청은 null). 응답을 이미 반영한 화면은 이를 보고 다시 부르기를 건너뛸 수 있다.
const CHANGE_EVENT = "datachange";
let changeTimer = null;
let changeTags = [];
function notifyDataChange(tag) {
  clearTimeout(changeTimer);
  changeTags.push(tag ?? null);
  changeTimer = setTimeout(() => {
    const tags = changeTags;
    changeTags = [];
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: tags }));
  }, 30);
}
export function useDataChange(callback) {
  const ref = useRef(callback);
  ref.current = callback;
  useEffect(() => {
    const h = (e) => ref.current((e && e.detail) || []);
    window.addEventListener(CHANGE_EVENT, h);
    return () => window.removeEventListener(CHANGE_EVENT, h);
  }, []);
}

export async function api(path, { method = "GET", body, raw, params, tag } = {}) {
  let url = "/api" + path;
  if (params) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
    const s = q.toString();
    if (s) url += (url.includes("?") ? "&" : "?") + s;
  }
  const headers = { "X-Requested-With": "asset-manager" };
  let payload;
  if (raw !== undefined) { payload = raw; headers["Content-Type"] = "application/octet-stream"; }
  else if (body !== undefined) { payload = JSON.stringify(body); headers["Content-Type"] = "application/json"; }
  let res;
  try {
    res = await fetch(url, { method, headers, body: payload });
  } catch (e) {
    throw new ApiError("서버와 통신할 수 없습니다. 프로그램이 실행 중인지 확인하세요.");
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = typeof data === "object" ? data.detail : data;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join(", ");
    throw new ApiError(msg || `요청 실패 (${res.status})`);
  }
  if (method !== "GET" && !path.startsWith("/open-folder")) notifyDataChange(tag);
  return data;
}

// 데이터 로딩 훅. deps 가 바뀌거나 reload() 호출 시 다시 불러온다.
export function useApi(path, params, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    if (!path) { setState({ data: null, error: null, loading: false }); return; }
    setState(s => ({ ...s, loading: true }));
    api(path, { params })
      .then(d => alive && setState({ data: d, error: null, loading: false }))
      .catch(e => alive && setState({ data: null, error: e.message, loading: false }));
    return () => { alive = false; };
  }, [path, JSON.stringify(params || {}), tick, ...deps]);
  useDataChange(() => setTick(t => t + 1));
  return { ...state, reload: () => setTick(t => t + 1) };
}

// ───────── 표시 설정 ─────────
// 날짜 표기·금액 단위. 진실 원천은 서버 설정 DB 다(브라우저 저장소에 두지 않는다). 앱이 렌더 전에 setDisplay 를 부른다.
const DATE_FORMATS = ["iso", "dot", "ko", "en"];
const CURRENCIES = ["won", "symbol", "code"];
let display = { dateFormat: "ko", currency: "won" };
export function setDisplay(settings = {}) {
  display = {
    dateFormat: DATE_FORMATS.includes(settings.date_format) ? settings.date_format : "ko",
    currency: CURRENCIES.includes(settings.currency_display) ? settings.currency_display : "won",
  };
}
export const getDisplay = () => ({ ...display });

// ───────── 포맷 ─────────
// 저장 값(금액=원 정수, 날짜=ISO)은 그대로 두고 표시만 현재 설정(getDisplay)에 맞춘다.
const nf = new Intl.NumberFormat("ko-KR");
export const won = (n, { sign = false, unit = true } = {}) => {
  if (n === null || n === undefined || n === "") return "–";
  const v = Math.round(Number(n)) + 0;
  const s = nf.format(Math.abs(v));
  const pre = v < 0 ? "-" : (sign && v > 0 ? "+" : "");
  if (!unit) return pre + s;
  const c = display.currency;
  if (c === "symbol") return pre + "₩" + s;
  if (c === "code") return pre + "KRW " + s;
  return pre + s + "원";
};
export const num = (n, d = 2) => (n === null || n === undefined || n === "") ? "–"
  : Number(n).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
export const qty = (s) => s === null || s === undefined ? "–" : Number(s).toLocaleString("ko-KR", { maximumFractionDigits: 6 });
export const pct = (n, sign = false) => (n === null || n === undefined) ? "–" : (sign && n > 0 ? "+" : "") + Number(n).toFixed(1) + "%";
export const cls = (n, invert = false) => (n === null || n === undefined || n === 0) ? "" : ((n > 0) !== invert ? "pos" : "neg");
// 억/만 단위 축약 (차트 축용)
export const shortWon = (v) => {
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(a >= 1e9 ? 0 : 1).replace(/\.0$/, "") + "억";
  if (a >= 1e4) return Math.round(v / 1e4).toLocaleString("ko-KR") + "만";
  return String(v);
};

export const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
export const thisMonth = () => today().slice(0, 7);
export function addMonths(m, n) {
  const [y, mo] = m.split("-").map(Number);
  const idx = y * 12 + (mo - 1) + n;
  return `${String(Math.floor(idx / 12)).padStart(4, "0")}-${String(idx % 12 + 1).padStart(2, "0")}`;
}
const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// 월(YYYY-MM) 표시: iso 2026-10 · dot 2026.10 · ko 2026년 10월 · en Oct 2026
export const monthLabel = (m) => {
  if (!m) return "";
  const y = m.slice(0, 4), mm = m.slice(5, 7), f = display.dateFormat;
  if (f === "iso") return `${y}-${mm}`;
  if (f === "dot") return `${y}.${mm}`;
  if (f === "en") return `${MONTHS_EN[Number(mm) - 1]} ${y}`;
  return `${y}년 ${Number(mm)}월`;
};
// 날짜(YYYY-MM-DD) 표시: iso 2026-10-21 · dot 2026.10.21 · ko 2026년 10월 21일 · en Oct 21, 2026
export const dateLabel = (d) => {
  if (!d) return "";
  const y = d.slice(0, 4), mm = d.slice(5, 7), dd = d.slice(8, 10), f = display.dateFormat;
  if (f === "iso") return `${y}-${mm}-${dd}`;
  if (f === "dot") return `${y}.${mm}.${dd}`;
  if (f === "en") return `${MONTHS_EN[Number(mm) - 1]} ${Number(dd)}, ${y}`;
  return `${y}년 ${Number(mm)}월 ${Number(dd)}일`;
};
// 차트 축용 짧은 월(YYYY-MM): en Oct · 그 밖(iso/dot/ko) 10월
export const monthShort = (m) => {
  if (!m) return "";
  const mm = Number(String(m).slice(5, 7));
  return display.dateFormat === "en" ? MONTHS_EN[mm - 1] : `${mm}월`;
};
// 연도 표시: ko 2026년 · 그 밖(iso/dot/en) 2026
export const yearLabel = (y) => {
  if (y === null || y === undefined || y === "") return "";
  return display.dateFormat === "ko" ? `${y}년` : String(y);
};
// 날짜·시각(YYYY-MM-DDTHH:MM[:SS]) 표시: 날짜는 dateLabel, 시각은 HH:MM
export const dateTimeLabel = (s) => {
  if (!s) return "";
  const str = String(s), time = str.slice(11, 16);
  return time ? `${dateLabel(str.slice(0, 10))} ${time}` : dateLabel(str.slice(0, 10));
};
export const parseMoney = (s) => String(s ?? "").replace(/KRW|[,원₩\s]/gi, "");
export const fmtMoneyInput = (s) => {
  const raw = parseMoney(s);
  if (raw === "" || raw === "-") return raw;
  if (!/^-?\d+$/.test(raw)) return s;
  const neg = raw.startsWith("-");
  return (neg ? "-" : "") + nf.format(Number(raw.replace("-", "")));
};


// ───────── 토스트 ─────────
let pushToast = () => {};
export const toast = (msg, type = "") => pushToast(msg, type);
export const toastErr = (e) => pushToast(e?.message || String(e), "err");
export function Toasts() {
  const [items, setItems] = useState([]);
  pushToast = (msg, type) => {
    const id = Math.random();
    setItems(xs => [...xs, { id, msg, type }]);
    setTimeout(() => setItems(xs => xs.filter(x => x.id !== id)), type === "err" ? 6500 : 3000);
  };
  return html`<div class="toasts">${items.map(t => html`<div class="toast ${t.type}" key=${t.id}>${t.msg}</div>`)}</div>`;
}

// ───────── 모달 ─────────
export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return html`<div class="modal-back" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="modal ${wide ? "wide" : ""}" role="dialog">
      <div class="modal-head"><h3>${title}</h3><button class="btn link" onClick=${onClose} title="닫기">✕</button></div>
      <div class="modal-body">${children}</div>
      ${footer && html`<div class="modal-foot">${footer}</div>`}
    </div></div>`;
}

// ───────── 확인 창 ─────────
// 브라우저 기본 confirm 대신 앱 안에서 그리는 모달. 요청은 대기열에 쌓이고 ConfirmHost 가 맨 앞부터 하나씩 보여 준다.
// 호스트가 아직 없으면 요청은 대기열에 남는다(Promise 는 호스트가 마운트되어 답할 때까지 pending).
const confirmQueue = [];
let refreshConfirm = () => {};
export function confirmBox(message, { title = "확인", ok = "확인", cancel = "취소" } = {}) {
  return new Promise((resolve) => {
    confirmQueue.push({ id: Math.random(), message, title, ok, cancel, resolve, done: false, prev: undefined });
    refreshConfirm();
  });
}
export function ConfirmHost() {
  const [, setTick] = useState(0);
  const okRef = useRef();
  refreshConfirm = () => setTick(t => t + 1);
  useEffect(() => () => { refreshConfirm = () => {}; }, []);
  const cur = confirmQueue[0];
  const finish = (value) => {
    const req = confirmQueue[0];
    if (!req || req.done) return;
    req.done = true;
    confirmQueue.shift();
    req.resolve(value);
    const next = confirmQueue[0];
    if (next) { if (next.prev === undefined) next.prev = req.prev; }
    else if (req.prev && req.prev.focus && document.contains(req.prev)) req.prev.focus();
    setTick(t => t + 1);
  };
  useEffect(() => {
    if (!cur) return;
    if (cur.prev === undefined) cur.prev = document.activeElement;
    okRef.current?.focus();
    const h = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      e.preventDefault();
      finish(false);
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [cur && cur.id]);
  if (!cur) return null;
  return html`<div class="modal-back confirm" onMouseDown=${(e) => e.target === e.currentTarget && finish(false)}>
    <div class="modal" role="alertdialog" aria-modal="true">
      <div class="modal-head"><h3>${cur.title}</h3><button class="btn link" onClick=${() => finish(false)} title="닫기">✕</button></div>
      <div class="modal-body"><div class="confirm-msg">${cur.message}</div></div>
      <div class="modal-foot">
        <button class="btn" onClick=${() => finish(false)}>${cur.cancel}</button>
        <button class="btn primary" ref=${okRef} onClick=${() => finish(true)}>${cur.ok}</button>
      </div>
    </div></div>`;
}

// ───────── 입력 컴포넌트 ─────────
export function MoneyInput({ value, onInput, placeholder = "0", autofocus, onKeyDown, style }) {
  const ref = useRef();
  useEffect(() => { if (autofocus && ref.current) { ref.current.focus(); ref.current.select(); } }, []);
  return html`<input ref=${ref} type="text" inputmode="numeric" class="amount" value=${value} placeholder=${placeholder}
    style=${style} onKeyDown=${onKeyDown}
    onInput=${(e) => onInput(fmtMoneyInput(e.target.value))} />`;
}

export function MonthPicker({ value, onChange }) {
  return html`<div class="month-picker">
    <button class="btn" onClick=${() => onChange(addMonths(value, -1))} title="이전 달">◀</button>
    <input type="month" value=${value} onChange=${(e) => e.target.value && onChange(e.target.value)} />
    <button class="btn" onClick=${() => onChange(addMonths(value, 1))} title="다음 달">▶</button>
    <button class="btn" onClick=${() => onChange(thisMonth())}>이번 달</button>
  </div>`;
}

export function Segmented({ value, options, onChange }) {
  return html`<div class="btn-group">${options.map(([v, label]) =>
    html`<button class="btn ${value === v ? "on" : ""}" onClick=${() => onChange(v)}>${label}</button>`)}</div>`;
}

export function Empty({ title, children }) {
  return html`<div class="empty"><b>${title}</b>${children}</div>`;
}

export function Loading() { return html`<div class="empty">불러오는 중…</div>`; }
export function ErrorBox({ error, onRetry }) {
  return html`<div class="notice err">${error} ${onRetry && html`<button class="btn sm" onClick=${onRetry}>다시 시도</button>`}</div>`;
}

// ───────── 차트 ─────────
export const PALETTE = ["#2459d6", "#e8743b", "#19a979", "#945ecf", "#ed4a7b", "#13a4b4", "#c9a227", "#6c8893", "#d64545", "#4e79a7", "#9c755f", "#76b7b2"];
if (window.Chart) {
  Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue("--font");
  Chart.defaults.font.size = 11.5;
  Chart.defaults.color = "#4a5263";
  Chart.defaults.animation = false;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.tooltip.callbacks.label = (ctx) => {
    const v = ctx.parsed.y ?? ctx.parsed;
    const fmt = ctx.dataset.fmt || ((x) => won(x));
    return ` ${ctx.dataset.label || ctx.label}: ${fmt(v)}`;
  };
}

// 새 항목 색: 아직 쓰지 않은 색을 고르고, 모두 쓰였으면 순환한다.
export function nextColor(categories) {
  const used = new Set(categories.map(c => (c.color || "").toLowerCase()));
  return PALETTE.find(p => !used.has(p.toLowerCase())) || PALETTE[categories.length % PALETTE.length];
}

export function ChartView({ config, className = "chart-box", height }) {
  const ref = useRef();
  const chart = useRef();
  useEffect(() => {
    if (!window.Chart || !ref.current) return;
    chart.current?.destroy();
    chart.current = new Chart(ref.current, config);
    return () => { chart.current?.destroy(); chart.current = null; };
  }, [JSON.stringify(config, (k, v) => typeof v === "function" ? String(v) : v)]);
  if (!window.Chart) return html`<div class="notice warn">차트 라이브러리를 불러오지 못했습니다.</div>`;
  return html`<div class=${className} style=${height ? `height:${height}px` : ""}><canvas ref=${ref}></canvas></div>`;
}

export const wonAxis = { ticks: { callback: (v) => shortWon(v) }, grid: { color: "#eef0f3" } };

// 파일 선택 → ArrayBuffer
export function pickFile(accept) {
  return new Promise((resolve) => {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = accept;
    inp.onchange = () => resolve(inp.files[0] || null);
    inp.click();
  });
}

// 내보내기: 데스크톱 창(pywebview)에서는 파일을 데이터 폴더에 저장하고 폴더를 연다. 브라우저에서는 다운로드.
export async function exportFile(path, params = {}) {
  if (window.pywebview) {
    try {
      const r = await api(path, { params: { ...params, save: true } });
      toast(`저장했습니다:\n${r.path}`, "ok");
      await api("/open-folder", { method: "POST", body: { which: "exports" } });
    } catch (e) { toastErr(e); }
    return;
  }
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
  const a = document.createElement("a");
  a.href = "/api" + path + (q.toString() ? "?" + q : "");
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ───────── Drag auto-scroll (U-19) ─────────
// Pixels to scroll this frame: <0 up, >0 down, 0 none. Faster nearer the edge; max outside the container.
export function autoScrollSpeed(y, top, bottom, edge = 60, max = 24) {
  if (![y, top, bottom].every((v) => typeof v === "number" && Number.isFinite(v))) return 0;
  const e = Math.min(edge, (bottom - top) / 2);
  if (!(e > 0)) return 0;
  if (y < top + e) return -Math.max(1, Math.round(max * Math.min(1, (top + e - y) / e)));
  if (y > bottom - e) return Math.max(1, Math.round(max * Math.min(1, (y - (bottom - e)) / e)));
  return 0;
}

const isRootScroller = (node) => node === document.scrollingElement || node === document.documentElement || node === document.body;

// Nearest ancestor-or-self that actually scrolls vertically, else the document scroller.
export function scrollParent(el) {
  for (let node = el; node && !isRootScroller(node); node = node.parentElement) {
    const oy = getComputedStyle(node).overflowY;
    if ((oy === "auto" || oy === "scroll") && node.scrollHeight > node.clientHeight) return node;
  }
  return document.scrollingElement || document.documentElement;
}

let autoScroll = null;

// Scroll the container near its top/bottom edge while an HTML5 drag is in progress.
export function startDragAutoScroll(fromEl) {
  stopDragAutoScroll();
  const state = { container: scrollParent(fromEl), y: null, frame: null };
  state.onOver = (e) => { state.y = e.clientY; };
  state.onLeave = (e) => { if (e.relatedTarget == null) state.y = null; };
  state.onDrop = () => stopDragAutoScroll();
  const tick = () => {
    if (autoScroll !== state) return;
    state.frame = null;
    const c = state.container;
    if (!c || !c.isConnected) { stopDragAutoScroll(); return; }
    if (state.y !== null) {
      let top, bottom;
      if (isRootScroller(c)) { top = 0; bottom = window.innerHeight; }
      else { const r = c.getBoundingClientRect(); top = r.top; bottom = r.bottom; }
      const speed = autoScrollSpeed(state.y, top, bottom);
      if (speed !== 0) c.scrollTop += speed;
    }
    if (autoScroll === state) state.frame = requestAnimationFrame(tick);
  };
  autoScroll = state;
  document.addEventListener("dragover", state.onOver, true);
  document.addEventListener("dragleave", state.onLeave, true);
  document.addEventListener("drop", state.onDrop, true);
  state.frame = requestAnimationFrame(tick);
}

// Idempotent; safe to call before any start.
export function stopDragAutoScroll() {
  const state = autoScroll;
  if (!state) return;
  autoScroll = null;
  if (state.frame !== null) cancelAnimationFrame(state.frame);
  state.frame = null;
  document.removeEventListener("dragover", state.onOver, true);
  document.removeEventListener("dragleave", state.onLeave, true);
  document.removeEventListener("drop", state.onDrop, true);
}

// ───────── Drag drop target by pointer height ─────────
// Where to drop `drag` given pointer Y and item rects (same order as keys); null when the order would not change.
export function dropTarget(y, keys, rects, drag) {
  if (typeof y !== "number" || !Number.isFinite(y)) return null;
  if (!Array.isArray(keys) || !Array.isArray(rects) || keys.length !== rects.length || keys.length === 0) return null;
  const di = keys.indexOf(drag);
  if (di < 0) return null;
  const fin = (v) => typeof v === "number" && Number.isFinite(v);
  if (rects.some((r) => !r || !fin(r.top) || !fin(r.bottom))) return null;
  let ins = 0;
  for (const r of rects) if (y >= (r.top + r.bottom) / 2) ins++;
  if (ins === di || ins === di + 1) return null;
  return ins < keys.length ? { key: keys[ins], pos: "before" } : { key: keys[keys.length - 1], pos: "after" };
}

let dragDrop = null;

// Accept dragover/drop anywhere inside `area`, choosing the slot from the pointer Y.
export function startDragDrop({ area, drag, keys, items, onHint, onDrop }) {
  stopDragDrop();
  const root = area || document.documentElement;
  const state = { last: null };
  const compute = (e) => {
    if (!root.contains(e.target)) return null;
    const rects = items().map((el) => el.getBoundingClientRect());
    return dropTarget(e.clientY, keys, rects, drag);
  };
  state.onOver = (e) => {
    const t = compute(e);
    if (t) {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    }
    const l = state.last;
    const changed = (t === null) !== (l === null) || (t && l && (t.key !== l.key || t.pos !== l.pos));
    if (changed) { state.last = t; onHint(t); }
  };
  state.onDrop = (e) => {
    if (!root.contains(e.target)) return;
    e.preventDefault();
    const t = compute(e);
    stopDragDrop();
    if (t) onDrop(t);
  };
  dragDrop = state;
  document.addEventListener("dragover", state.onOver, true);
  document.addEventListener("drop", state.onDrop, true);
}

// Idempotent; safe to call before any start. Never calls onHint.
export function stopDragDrop() {
  const state = dragDrop;
  if (!state) return;
  dragDrop = null;
  document.removeEventListener("dragover", state.onOver, true);
  document.removeEventListener("drop", state.onDrop, true);
}

// ───────── 라우팅 ─────────
export function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  return { page: path || "dashboard", params: Object.fromEntries(new URLSearchParams(qs || "")) };
}
export function navigate(page, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
  location.hash = `#/${page}${q.toString() ? "?" + q : ""}`;
}
export function setParams(params) {
  const { page, params: cur } = parseHash();
  const next = { ...cur, ...params };
  const q = new URLSearchParams(Object.entries(next).filter(([, v]) => v !== undefined && v !== null && v !== ""));
  history.replaceState(null, "", `#/${page}${q.toString() ? "?" + q : ""}`);
  window.dispatchEvent(new Event("paramschange"));
}

// 공유 상태(항목 목록, 설정)
export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);
