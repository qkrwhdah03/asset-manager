// 공통 유틸리티: API 호출, 포맷, 토스트, 모달, 차트, 월 선택기
import { html, render, useState, useEffect, useRef, useCallback, useMemo, createContext, useContext } from "/vendor/preact-htm.module.js";
export { html, render, useState, useEffect, useRef, useCallback, useMemo, createContext, useContext };

// ───────── API ─────────
export class ApiError extends Error {}

// 데이터가 바뀌었다는 앱 전체 신호. 저장·추가·삭제 요청이 성공하면 보내고,
// 화면·표·항목 목록은 이 신호를 받으면 바로 다시 불러온다(짧은 시간에 여러 번 와도 한 번으로 합침).
const CHANGE_EVENT = "datachange";
let changeTimer = null;
function notifyDataChange() {
  clearTimeout(changeTimer);
  changeTimer = setTimeout(() => window.dispatchEvent(new Event(CHANGE_EVENT)), 30);
}
export function useDataChange(callback) {
  const ref = useRef(callback);
  ref.current = callback;
  useEffect(() => {
    const h = () => ref.current();
    window.addEventListener(CHANGE_EVENT, h);
    return () => window.removeEventListener(CHANGE_EVENT, h);
  }, []);
}

export async function api(path, { method = "GET", body, raw, params } = {}) {
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
  if (method !== "GET" && !path.startsWith("/open-folder")) notifyDataChange();
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

// ───────── 포맷 ─────────
const nf = new Intl.NumberFormat("ko-KR");
export const won = (n, { sign = false, unit = true } = {}) => {
  if (n === null || n === undefined || n === "") return "–";
  const v = Number(n);
  const s = nf.format(Math.round(v) + 0);
  return (sign && v > 0 ? "+" : "") + s + (unit ? "원" : "");
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
export const monthLabel = (m) => m ? `${m.slice(0, 4)}년 ${Number(m.slice(5, 7))}월` : "";
export const parseMoney = (s) => String(s ?? "").replace(/[,원\s]/g, "");
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

export function confirmBox(msg) { return window.confirm(msg); }

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
