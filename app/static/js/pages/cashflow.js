// 월 예산: 소득·지출 항목 전체를 표로 펼쳐 놓고 칸에 바로 입력한다.
// ① 소득(세부항목) → ② 계획(항목별, 실제는 ③ 합계) → ③ 지출(세부항목) → ④ 정산
import {
  html, useState, useEffect, useMemo, useRef, api, useApi, useApp, won, pct, monthLabel, dateLabel, thisMonth, today, addMonths,
  parseMoney, fmtMoneyInput, MoneyInput, MonthPicker, Modal, Empty, Loading, ErrorBox, toast, toastErr,
  setParams, confirmBox, useDataChange,
} from "../lib.js";
import { MoveDialog } from "./move.js";

// 기본 정산 대상(저축·투자 항목) 추정.
const SAVINGS_HINT = /저축|투자/;
// 응답(최신 예산)을 이미 화면에 반영한 칸 저장 요청 표시. 이것만으로 이뤄진 변경 신호에는 예산을 다시 부르지 않는다.
const SELF_APPLIED = "budget-applied";

export function CashflowPage({ params }) {
  const { categories } = useApp();
  const month = params.month || thisMonth();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [move, setMove] = useState(null);
  const [copying, setCopying] = useState(false);

  const load = () => api("/budget", { params: { month } }).then((x) => { setD(x); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => { setD(null); load(); }, [month]);
  // 다른 곳에서 바뀐 내용(항목 추가·삭제·이름·색 등)도 바로 반영
  useDataChange((tags) => { if (!tags.length || !tags.every(t => t === SELF_APPLIED)) load(); });
  // 칸 저장: 서버가 돌려준 최신 예산으로 바로 갱신
  const save = async (path, body) => {
    try { setD(await api(path, { method: "PUT", body: { month, ...body }, tag: SELF_APPLIED })); return true; }
    catch (e) { toastErr(e); return false; }
  };

  const expenseCats = categories.filter(c => c.kind === "expense");
  const stashId = useMemo(() => (expenseCats.find(c => c.is_active && SAVINGS_HINT.test(c.name)) || {}).id, [categories]);
  const ctx = { month, d, categories, expenseCats, stashId, save, openMove: setMove };

  return html`<div class="page">
    <div class="page-head">
      <h1>월 예산</h1>
      <${MonthPicker} value=${month} onChange=${(m) => setParams({ month: m })} />
      ${d && html`<button class="btn sm" onClick=${() => setCopying(true)}>지난달 불러오기</button>`}
      <div class="spacer"></div>
      ${d && html`<${StepBar} d=${d} />`}
    </div>
    ${error && html`<${ErrorBox} error=${error} onRetry=${load} />`}
    ${!d ? (!error && html`<${Loading} />`) : html`
      <div class="budget-grid2">
        <div>
          <${ItemSheet} ctx=${ctx} kind="income" />
          <${ExpenseTable} ctx=${ctx} />
          <${ItemSheet} ctx=${ctx} kind="expense" />
        </div>
        <div class="budget-side">
          <${AllocationCard} ctx=${ctx} />
          <${SettleCard} ctx=${ctx} />
          <div class="muted small" style="padding:4px 2px;line-height:1.6">칸을 벗어나면 자동 저장되고, Enter를 누르면 아래 칸으로 이동합니다.</div>
        </div>
      </div>`}
    ${copying && html`<${CopyMonthModal} month=${month} onClose=${() => setCopying(false)} onDone=${() => setCopying(false)} />`}
    ${move && html`<${MoveModal} ctx=${ctx} target=${move} onClose=${() => setMove(null)} onSaved=${() => setMove(null)} />`}
  </div>`;
}

// ───────── 단계 표시 ─────────
function StepBar({ d }) {
  const s1 = d.income_total > 0 ? "done" : "todo";
  const s2 = d.income_total === 0 ? "todo" : d.unallocated === 0 ? "done" : d.unallocated < 0 ? "bad" : "warn";
  const s3 = d.over_total > 0 ? "warn" : d.spent_total > 0 ? "active" : "todo";
  const s4 = d.settled && d.balanced ? "done" : d.settled ? "warn" : d.is_past ? "warn" : "todo";
  return html`<div class="steps">
    <span class="step ${s1}">① 소득 <b>${won(d.income_total)}</b></span>
    <span class="step ${s2}">② 배분 <b>${d.unallocated === 0 ? "완료" : d.unallocated > 0 ? `${won(d.unallocated)} 남음` : `${won(-d.unallocated)} 초과`}</b></span>
    <span class="step ${s3}">③ 지출 <b>${d.plan_total ? pct(d.spent_total / d.plan_total * 100) : "–"}</b></span>
    <span class="step ${s4}">④ 정산 <b>${d.settled ? (d.balanced ? "완료" : "다시 필요") : d.is_past ? "필요" : "월말"}</b></span>
  </div>`;
}

// ───────── 격자 입력 칸 ─────────
// 항상 보이는 입력 칸. 포커스 시 전체 선택, Enter 는 같은 열의 다음 칸으로, Esc 는 되돌리기, 벗어나면 저장.
function GridMoney({ value, col, onCommit, placeholder = "0", disabled }) {
  const fmt = (v) => (v ? fmtMoneyInput(String(v)) : "");
  const [text, setText] = useState(fmt(value));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(fmt(value)); }, [value]);
  const commit = async () => {
    const raw = parseMoney(text);
    const n = raw === "" || raw === "-" ? 0 : Number(raw);
    if (Number.isNaN(n)) { toast("숫자를 입력하세요.", "err"); setText(fmt(value)); return; }
    if (n !== (value || 0)) { const ok = await onCommit(n); if (!ok) setText(fmt(value)); }
  };
  return html`<input type="text" inputmode="numeric" class="cell amount" data-col=${col} value=${text} placeholder=${placeholder} disabled=${disabled}
    onFocus=${(e) => { focused.current = true; e.target.select(); }}
    onBlur=${() => { focused.current = false; commit(); }}
    onInput=${(e) => setText(fmtMoneyInput(e.target.value))}
    onKeyDown=${(e) => {
      if (e.key === "Escape") { setText(fmt(value)); e.target.blur(); }
      if (e.key === "Enter") {
        e.preventDefault();
        const all = [...document.querySelectorAll(`input[data-col="${col}"]:not([disabled])`)];
        const next = all[all.indexOf(e.target) + (e.shiftKey ? -1 : 1)];
        next ? next.focus() : e.target.blur();
      }
    }} />`;
}

// ───────── 항목(모든 달 공통) + 세부항목(그 달의 기록) ─────────
// 항목은 설정에서 관리하고, 여기서는 항목 아래에 그 달의 세부항목(이름·금액[·입금일])만 기록한다.

// 표 하나의 공통 상태: 접기(이 PC 에 기억), 세부항목 선택·일괄 삭제, 새 항목 추가
function useSheet(ctx, kind) {
  const storeKey = `am.collapsed.${kind}`;
  const [collapsed, setCollapsed] = useState(() => { try { return new Set(JSON.parse(localStorage.getItem(storeKey) || "[]")); } catch { return new Set(); } });
  const [sel, setSel] = useState(new Set());
  const [focusId, setFocusId] = useState(null);   // 방금 추가한 세부항목: 이름 칸에 포커스

  const toggleCollapse = (id) => {
    const next = new Set(collapsed);
    next.has(id) ? next.delete(id) : next.add(id);
    setCollapsed(next);
    try { localStorage.setItem(storeKey, JSON.stringify([...next])); } catch { /* ignore */ }   // 저장 못 해도 동작에는 문제 없음
  };
  const toggleSel = (id) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n); };
  const removeIds = async (ids, label) => {
    if (!ids.length || !confirmBox(label)) return;
    try {
      await api("/records/bulk-delete", { method: "POST", body: { ids } });
      const n = new Set(sel); ids.forEach(id => n.delete(id)); setSel(n);
    } catch (e) { toastErr(e); }
  };
  const addItem = async (categoryId) => {
    if (collapsed.has(categoryId)) toggleCollapse(categoryId);
    const body = kind === "income"
      ? { kind: "income", category_id: categoryId, budget_month: ctx.month, amount: 0, item: "" }
      : { kind: "expense", category_id: categoryId, month: ctx.month, amount: 0, item: "" };
    try { const r = await api("/records", { method: "POST", body }); setFocusId(r.id); } catch (e) { toastErr(e); }
  };
  const save = async (id, body) => {
    try { await api(`/records/${id}`, { method: "PUT", body }); return true; } catch (e) { toastErr(e); return false; }
  };
  return { collapsed, toggleCollapse, sel, toggleSel, clearSel: () => setSel(new Set()), removeIds, addItem, save, focusId };
}

function SelectionBar({ sh, onMove }) {
  if (!sh.sel.size) return null;
  return html`<span class="selbar"><b>${sh.sel.size}개 선택</b>
    ${onMove && html`<button class="btn sm" onClick=${onMove}>선택 옮기기</button>`}
    <button class="btn sm danger" onClick=${() => sh.removeIds([...sh.sel], `선택한 세부항목 ${sh.sel.size}개를 삭제할까요?`)}>선택 삭제</button>
    <button class="btn sm" onClick=${sh.clearSel}>선택 해제</button></span>`;
}

// 처음 그려질 때 포커스를 받을 수 있는 텍스트 칸. Enter → 같은 줄의 다음 입력 칸으로.
function ItemName({ value, autofocus, onCommit, readOnly, hint }) {
  const ref = useRef();
  const [text, setText] = useState(value || "");
  useEffect(() => setText(value || ""), [value]);
  useEffect(() => { if (autofocus && ref.current) ref.current.focus(); }, [autofocus]);
  return html`<input ref=${ref} type="text" class="cell" value=${text} placeholder=${hint || "세부항목 이름"} readOnly=${readOnly}
    onInput=${(e) => setText(e.target.value)} onBlur=${() => text !== (value || "") && onCommit(text)}
    onKeyDown=${(e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const cells = [...e.target.closest("tr").querySelectorAll("input.cell:not([readonly])")];
      const next = cells[cells.indexOf(e.target) + 1];
      next ? next.focus() : e.target.blur();
    }} />`;
}

function CatName({ c, sh, onAdd }) {
  const folded = sh.collapsed.has(c.category_id);
  return html`<td class="namecell grp">
    <button class="fold-btn" onClick=${() => sh.toggleCollapse(c.category_id)} title=${folded ? "펼치기" : "접기"}>${folded ? "▸" : "▾"}</button>
    <span class="dot" style=${c.color ? `background:${c.color}` : ""}></span><span class="nm" title=${c.memo || ""}>${c.name}</span>
    ${c.count > 0 && html`<span class="muted small"> ${c.count}</span>`}
    ${c.is_active && html`<span class="row-tools"><button class="tool add" onClick=${onAdd} title="이 항목에 세부항목 추가">+ 세부항목</button></span>`}
  </td>`;
}

function ItemCells({ it, sh }) {
  const settle = it.tag === "settle";
  return html`<td class="namecell item">
    <input type="checkbox" class="selbox ${sh.sel.size ? "on" : ""}" checked=${sh.sel.has(it.id)} onChange=${() => sh.toggleSel(it.id)} title="선택" />
    ${settle ? html`<span class="muted">${it.item || "월말 정산"} <span class="tag blue">정산</span></span>`
      : html`<${ItemName} value=${it.item} hint=${it.memo} autofocus=${sh.focusId === it.id} onCommit=${(v) => sh.save(it.id, { item: v })} />`}
  </td>`;
}

function DelCell({ it, sh, colspan = 1 }) {
  return html`<td class="actions" colspan=${colspan}>${it.tag !== "settle" && html`<button class="btn link del-x" title="삭제"
    onClick=${() => sh.removeIds([it.id], `'${it.item || "이름 없는 항목"}' (${won(it.amount)})을(를) 삭제할까요?`)}>✕</button>`}</td>`;
}

// ───────── ①③ 소득·지출 표 (항목 + 세부항목) ─────────
// 소득과 지출은 같은 표를 쓴다. 다른 점(어느 목록·합계·날짜 이름)만 SHEETS 에 둔다.
const SHEETS = {
  income: {
    title: "① 소득", hint: "항목 줄의 [+ 세부항목]으로 받은 돈을 기록합니다.", dateLabel: "입금일", dateTitle: "입금일 (비우면 미입금)",
    groups: (d) => d.income_items, sum: (c) => c.total, emptyTitle: "소득 항목이 없습니다",
    footer: (d) => html`<td>이번 달 쓸 돈</td><td class="num">${won(d.income_total)}</td>
      <td colspan="2" class="small muted">${d.income_pending ? `미입금 ${won(d.income_pending)} 포함` : ""}</td>`,
  },
  expense: {
    title: "③ 지출", hint: "항목 줄의 [+ 세부항목]으로 쓴 돈을 기록합니다.", dateLabel: "지출일", dateTitle: "지출일",
    groups: (d) => d.envelopes, sum: (c) => c.spent, emptyTitle: "지출 항목이 없습니다",
    footer: (d) => html`<td>이번 달 지출</td><td class="num">${won(d.spent_total)}</td><td colspan="2"></td>`,
  },
};

function ItemSheet({ ctx, kind }) {
  const { d } = ctx;
  const cfg = SHEETS[kind];
  const groups = cfg.groups(d);
  const sh = useSheet(ctx, kind);
  const [moveIds, setMoveIds] = useState(null);
  // 고른 세부항목이 모두 한 항목에 있으면 그 항목은 옮길 곳 목록에서 뺀다
  const fromIdOf = (ids) => { const cats = new Set(groups.filter(c => c.items.some(i => ids.includes(i.id))).map(c => c.category_id)); return cats.size === 1 ? [...cats][0] : null; };
  const rows = [];
  for (const c of groups) {
    rows.push(html`<tr key=${"c" + c.category_id} class="grouprow ${c.is_active ? "" : "inactive"}">
      <${CatName} c=${c} sh=${sh} onAdd=${() => sh.addItem(c.category_id)} />
      <td class="num"><b>${c.count ? won(cfg.sum(c)) : html`<span class="muted">–</span>`}</b></td><td></td><td></td></tr>`);
    if (sh.collapsed.has(c.category_id)) continue;
    for (const it of c.items) {
      const settle = it.tag === "settle";   // 월말 정산 행은 화면에서 고치지 않는다
      rows.push(html`<tr key=${it.id} class="childrow">
        <${ItemCells} it=${it} sh=${sh} />
        <td class="num">${settle ? won(it.amount) : html`<${GridMoney} col=${kind} value=${it.amount} onCommit=${(n) => sh.save(it.id, { amount: n })} />`}</td>
        <td class="nowrap">${settle ? html`<span class="muted small">${dateLabel(it.txn_date)}</span>` : html`
          <input type="date" class="cell" value=${it.txn_date || ""} title=${cfg.dateTitle} onChange=${(e) => sh.save(it.id, { txn_date: e.target.value || null })} />
          ${kind === "income" && it.amount > 0 && !it.txn_date && html`<span class="tag amber">미입금</span>`}`}</td>
        <${DelCell} it=${it} sh=${sh} />
      </tr>`);
    }
  }
  return html`<div class="panel">
    <div class="panel-head"><h2>${cfg.title}</h2><span class="hint">${cfg.hint}</span><div class="spacer"></div>
      <${SelectionBar} sh=${sh} onMove=${() => setMoveIds([...sh.sel])} /></div>
    ${moveIds && html`<${MoveDialog} kind=${kind} ids=${moveIds} fromId=${fromIdOf(moveIds)} onClose=${() => setMoveIds(null)} onMoved=${() => sh.clearSel()} />`}
    <div class="panel-body flush"><table class="t sheet">
      <thead><tr><th>항목 / 세부항목</th><th class="num" style="width:150px">금액</th><th style="width:190px">${cfg.dateLabel}</th><th style="width:1%"></th></tr></thead>
      <tbody>${rows}
        ${groups.length === 0 && html`<tr><td colspan="4"><${Empty} title=${cfg.emptyTitle}>설정 → 항목에서 항목을 추가하세요.<//></td></tr>`}
      </tbody>
      <tfoot><tr>${cfg.footer(d)}</tr></tfoot>
    </table></div>
  </div>`;
}

// ───────── ② 계획 (항목별 계획 · 실제는 ③ 지출 합계) ─────────
function ExpenseTable({ ctx }) {
  const { d } = ctx;
  // 이번 달이면 남은 날 수(오늘 포함)로 '하루에 쓸 수 있는 돈'을 보여 준다
  const [y, m] = ctx.month.split("-").map(Number);
  const daysLeft = d.pace > 0 && d.pace < 1 ? new Date(y, m, 0).getDate() - Number(today().slice(8, 10)) + 1 : 0;
  const bar = (e) => {
    if (e.status === "empty") return "";
    const used = e.plan > 0 ? e.spent / e.plan * 100 : null;
    const fill = used !== null ? Math.min(100, Math.max(0, used)) : (e.spent > 0 ? 100 : 0);
    const marker = daysLeft > 0 && e.plan > 0;
    const left = used === null ? "계획 없음" : `${Math.round(used)}% 사용`;
    const right = e.remaining < 0 ? html`<span class="neg">${won(-e.remaining)} 초과</span>`
      : daysLeft > 0 && e.remaining > 0 ? `하루 ${won(Math.floor(e.remaining / daysLeft))}` : "";
    const tip = used === null ? "" : `계획의 ${Math.round(used)}% 사용`
      + (marker ? ` · 오늘은 이달의 ${Math.round(d.pace * 100)}%` : "")
      + (daysLeft > 0 ? ` · 남은 ${daysLeft}일` : "");
    return html`<div class="pwrap" title=${tip}>
      <div class="pbar"><i class=${e.status} style="width:${fill}%"></i>${marker && html`<b style="left:${d.pace * 100}%"></b>`}</div>
      <div class="pcap"><span class=${e.status === "fast" ? "warn" : ""}>${left}${e.status === "fast" ? " · 빠름" : ""}</span><span>${right}</span></div>
    </div>`;
  };
  const rows = d.envelopes.map(e => html`<tr key=${"c" + e.category_id} class="${e.status === "over" || e.status === "unplanned" ? "over" : ""} ${e.is_active ? "" : "inactive"}">
      <td class="namecell"><span class="dot" style=${e.color ? `background:${e.color}` : ""}></span><span class="nm" title=${e.memo || ""}>${e.name}</span></td>
      <td class="num"><${GridMoney} col="plan" value=${e.plan} onCommit=${(n) => ctx.save("/budget/plan", { category_id: e.category_id, amount: n })}
        disabled=${!e.is_active && !e.plan} />${e.plan !== e.plan_base && html`<span class="adj" title="원래 계획 ${won(e.plan_base)} (옮기기·정산으로 조정됨)">*</span>`}</td>
      <td class="num ${e.spent ? "" : "muted"}">${e.spent ? won(e.spent) : "–"}${e.items.some(i => i.tag === "settle") && html`<span class="adj" title="월말 정산 금액 포함">정</span>`}</td>
      <td class="num ${e.remaining < 0 ? "neg" : e.status === "empty" || (e.remaining === 0 && e.plan > 0) ? "muted" : ""}"><b>${e.status === "empty" ? "–" : won(e.remaining)}</b></td>
      <td>${bar(e)}</td>
      <td class="actions">${e.remaining < 0 && html`<button class="btn sm" onClick=${() => ctx.openMove(e)} title="다른 항목의 남은 계획을 옮겨 메우기">메우기</button>`}</td>
    </tr>`);
  return html`<div class="panel">
    <div class="panel-head"><h2>② 계획</h2>
      <span class="hint">항목마다 계획을 입력합니다. 실제는 ③ 지출의 합계이고, 막대의 세로선은 오늘입니다.</span></div>
    <div class="panel-body flush"><table class="t sheet">
      <thead><tr><th>항목</th><th class="num" style="width:130px">계획</th><th class="num" style="width:130px">실제</th>
        <th class="num" style="width:110px">남음</th><th style="min-width:120px">진행</th><th style="width:1%"></th></tr></thead>
      <tbody>${rows}
        ${d.envelopes.length === 0 && html`<tr><td colspan="6"><${Empty} title="지출 항목이 없습니다">설정 → 항목에서 지출 항목을 추가하세요.<//></td></tr>`}
      </tbody>
      <tfoot><tr><td>합계</td><td class="num">${won(d.plan_total)}</td><td class="num">${won(d.spent_total)}</td>
        <td class="num ${d.plan_total - d.spent_total < 0 ? "neg" : ""}">${won(d.plan_total - d.spent_total)}</td><td colspan="2"></td></tr></tfoot>
    </table></div>
  </div>`;
}

// ───────── 배분 / 정산 ─────────
function AllocationCard({ ctx }) {
  const { month, d } = ctx;
  const [target, setTarget] = useState(null);
  const u = d.unallocated;
  const options = d.envelopes.filter(e => e.is_active);
  const tgt = target || ctx.stashId || options[0]?.category_id;
  const tone = d.income_total === 0 ? "" : u === 0 ? "ok" : u > 0 ? "warn" : "bad";
  async function fill() {
    const e = d.envelopes.find(x => x.category_id === tgt);
    await ctx.save("/budget/plan", { category_id: tgt, amount: (e ? e.plan : 0) + u });
  }
  return html`<div class="panel">
    <div class="panel-head"><h2>② 배분</h2><span class="hint">쓸 돈 − 계획</span></div>
    <div class="panel-body">
      <div class="bignum ${tone}">
        <div class="small">${u === 0 && d.income_total ? "모두 배분됨" : u >= 0 ? "아직 배분 안 된 돈" : "소득보다 많이 계획함"}</div>
        <div class="v">${u === 0 && d.income_total ? `✓ ${won(0)}` : won(Math.abs(u))}</div>
      </div>
      <div class="muted small" style="margin-top:6px">${won(d.income_total)} − 계획 ${won(d.plan_total)}</div>
      ${u > 0 && options.length > 0 && html`<div class="row" style="margin-top:8px;flex-wrap:nowrap">
        <select value=${tgt} onChange=${(e) => setTarget(Number(e.target.value))} style="flex:1;min-width:0">
          ${options.map(e => html`<option value=${e.category_id}>${e.full_name}</option>`)}</select>
        <button class="btn sm" onClick=${fill}>에 모두 넣기</button></div>`}
      ${u < 0 && html`<div class="small" style="margin-top:6px;color:var(--neg)">계획 금액을 줄여 0원으로 맞추세요.</div>`}
    </div>
  </div>`;
}

function SettleCard({ ctx }) {
  const { month, d } = ctx;
  const [target, setTarget] = useState(null);
  const options = ctx.expenseCats.filter(c => c.is_active);
  const tgt = target || ctx.stashId || options[0]?.id;
  async function settle() {
    const name = options.find(c => c.id === tgt)?.name;
    const note = d.income_pending > 0 ? `\n\n주의: 아직 입금되지 않은 소득 ${won(d.income_pending)}이 포함되어 있습니다.` : "";
    if (!confirmBox(`남은 ${won(d.leftover)}을 '${name}'(으)로 보내고, 각 항목의 계획을 실제 지출에 맞춥니다.\n원래 계획은 기록으로 보존됩니다. 정산할까요?${note}`)) return;
    try { await api("/budget/settle", { method: "POST", body: { month, category_id: tgt } }); toast("정산했습니다. 소득 = 지출", "ok"); }
    catch (e) { toastErr(e); }
  }
  async function resettle() {
    const name = options.find(c => c.id === d.settle_target)?.name || "정산 항목";
    if (!confirmBox(`지난 정산을 지우고 지금 기록으로 다시 정산합니다.\n남은 돈은 '${name}'(으)로 보냅니다. 진행할까요?`)) return;
    try { await api("/budget/settle", { method: "POST", body: { month, category_id: d.settle_target } }); toast("다시 정산했습니다. 소득 = 지출", "ok"); }
    catch (e) { toastErr(e); }
  }
  async function unsettle() {
    if (!confirmBox("정산을 취소하고 정산 전 계획·지출로 되돌릴까요?")) return;
    try { await api("/budget/settle", { method: "DELETE", params: { month } }); } catch (e) { toastErr(e); }
  }
  const tone = d.leftover < 0 ? "bad" : d.settled && d.balanced ? "ok" : "";
  return html`<div class="panel">
    <div class="panel-head"><h2>④ 정산</h2><span class="hint">쓸 돈 − 지출 = 0</span></div>
    <div class="panel-body">
      <div class="bignum ${tone}">
        <div class="small">${d.settled && d.balanced ? "정산 완료 · 소득 = 지출" : d.leftover < 0 ? "소득보다 더 쓴 돈" : "아직 쓰지 않은 돈"}</div>
        <div class="v">${d.settled && d.balanced ? `✓ ${won(0)}` : won(Math.abs(d.leftover))}</div>
      </div>
      ${d.settled ? html`
        ${!d.balanced && html`<div class="small" style="color:var(--warn);margin-top:6px">정산 후 기록이 바뀌었습니다. 다시 정산하면 지금 기록에 맞춰집니다.</div>`}
        <div class="row" style="margin-top:8px">
          ${!d.balanced && html`<button class="btn sm primary" onClick=${resettle} disabled=${d.leftover_before_settle < 0}>다시 정산</button>`}
          <button class="btn sm" onClick=${unsettle}>정산 취소</button></div>
        ${!d.balanced && d.leftover_before_settle < 0 && html`<div class="small" style="color:var(--neg);margin-top:6px">소득보다 더 써서 다시 정산할 수 없습니다. 부족분을 소득으로 기록하세요.</div>`}`
      : d.leftover < 0 ? html`<div class="small" style="color:var(--neg);margin-top:6px">부족분을 소득(예: 저축에서 인출)으로 기록해야 정산할 수 있습니다.</div>`
      : html`<div class="small muted" style="margin-top:6px">${d.is_past ? "지난 달입니다. 남은 돈을 정리하세요." : "월말에 남은 돈을 한 항목으로 보내 마감합니다."}</div>
        <div class="row" style="margin-top:8px;flex-wrap:nowrap">
          <select value=${tgt} onChange=${(e) => setTarget(Number(e.target.value))} style="flex:1;min-width:0">
            ${options.map(c => html`<option value=${c.id}>${c.full_name}</option>`)}</select>
          <button class="btn sm ${d.is_past ? "primary" : ""}" onClick=${settle} disabled=${d.income_total === 0}>정산</button></div>`}
    </div>
  </div>`;
}

// 지난달 불러오기: [항목] 소득 세부항목 이름, [금액] 소득 세부항목 금액 + 지출 계획 금액
function CopyMonthModal({ month, onClose, onDone }) {
  const from = addMonths(month, -1);
  const p = useApi("/budget/copy-month", { from, to: month });
  const [items, setItems] = useState(true);
  const [amounts, setAmounts] = useState(true);
  const [busy, setBusy] = useState(false);
  const v = p.data;
  const nIncome = v ? (amounts ? v.income_all : v.income_items) : 0;
  const nPlan = v && amounts ? v.plan_items : 0;
  const nothing = !v || (!(items && nIncome) && !nPlan);

  async function apply() {
    if (amounts && v.plan_overwrite && !confirmBox(`이번 달에 이미 계획이 있는 항목 ${v.plan_overwrite}개는 지난달 금액으로 바뀝니다. 계속할까요?`)) return;
    setBusy(true);
    try {
      const r = await api("/budget/copy-month", { method: "POST", body: { from, to: month, items, amounts } });
      const c = r.copied, parts = [];
      if (c.income_items) parts.push(`소득 세부항목 ${c.income_items}개`);
      if (c.plan_items) parts.push(`지출 계획 ${c.plan_items}개 항목`);
      toast(parts.length ? `${parts.join(", ")}을(를) 불러왔습니다.` : "새로 불러올 내용이 없었습니다.", "ok");
      onDone();
    } catch (e) { toastErr(e); } finally { setBusy(false); }
  }

  return html`<${Modal} title="${monthLabel(from)} 불러오기" onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button>
      <button class="btn primary" onClick=${apply} disabled=${busy || nothing || (!items && !amounts)}>불러오기</button>`}>
    ${p.loading && !v ? html`<${Loading} />` : p.error ? html`<${ErrorBox} error=${p.error} />` : html`
      <label class="checkline"><input type="checkbox" class="selbox" checked=${items} onChange=${() => setItems(!items)} />
        <b>항목</b><span class="muted small">소득 세부항목 이름 ${v.income_items}개</span></label>
      <label class="checkline"><input type="checkbox" class="selbox" checked=${amounts} onChange=${() => setAmounts(!amounts)} />
        <b>금액</b><span class="muted small">${items ? `소득 ${won(v.income_total)} · ` : ""}지출 계획 ${v.plan_items}개 항목 ${won(v.plan_total)}</span></label>
      ${items && !amounts && nIncome > 0 && html`<p class="small muted">세부항목은 0원으로 만들어지고, 지출 계획은 그대로 둡니다.</p>`}
      ${amounts && v.plan_overwrite > 0 && html`<div class="notice warn" style="margin-top:10px">이번 달에 이미 계획이 있는 항목 ${v.plan_overwrite}개는 지난달 금액으로 바뀝니다.</div>`}
      ${nothing && (items || amounts) && html`<p class="small muted">불러올 내용이 없습니다.</p>`}`}
  <//>`;
}

function MoveModal({ ctx, target, onClose, onSaved }) {
  const { d, month } = ctx;
  const sources = d.envelopes.filter(e => e.category_id !== target.category_id && e.remaining > 0).sort((a, b) => b.remaining - a.remaining);
  const [from, setFrom] = useState(d.unallocated > 0 ? "" : (sources[0]?.category_id ?? ""));
  const [amount, setAmount] = useState(fmtMoneyInput(String(Math.max(0, -target.remaining))));
  async function save() {
    if (from === "" && Number(parseMoney(amount)) > d.unallocated) return toast("미배분 금액보다 많이 가져올 수 없습니다.", "err");
    try {
      await api("/budget/move", { method: "POST", body: { month, from_category_id: from || null, to_category_id: target.category_id, amount: parseMoney(amount) } });
      toast("계획을 옮겼습니다.", "ok"); onSaved();
    } catch (e) { toastErr(e); }
  }
  return html`<${Modal} title="'${target.name}' 초과분 메우기" onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button><button class="btn primary" onClick=${save}>옮기기</button>`}>
    <p class="small muted" style="margin-top:0">다른 항목의 남은 계획을 '${target.name}'(으)로 옮깁니다. 계획 합계(= 소득)는 그대로입니다.</p>
    <div class="form-grid">
      <label>가져올 항목</label>
      <select value=${from} onChange=${(e) => setFrom(e.target.value ? Number(e.target.value) : "")}>
        ${d.unallocated > 0 && html`<option value="">미배분 (${won(d.unallocated)})</option>`}
        ${sources.map(e => html`<option value=${e.category_id}>${e.name} (남음 ${won(e.remaining)})</option>`)}
      </select>
      <label>금액</label><${MoneyInput} value=${amount} onInput=${setAmount} />
    </div>
    ${sources.length === 0 && d.unallocated <= 0 && html`<div class="notice warn" style="margin-top:10px">남은 계획이 있는 항목이 없습니다. 소득을 추가하거나 다른 항목의 계획을 줄이세요.</div>`}
  <//>`;
}
