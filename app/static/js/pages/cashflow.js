// 월 예산: 소득·지출 항목 전체를 표로 펼쳐 놓고 칸에 바로 입력한다.
// ① 소득(세부항목) → ② 계획(항목별, 실제는 ③ 합계) → ③ 지출(세부항목) → ④ 정산
import {
  html, useState, useEffect, useMemo, useRef, api, useApi, useApp, won, pct, monthLabel, dateLabel, thisMonth, today, addMonths,
  parseMoney, fmtMoneyInput, MoneyInput, MonthPicker, Modal, Empty, Loading, ErrorBox, toast, toastErr,
  setParams, confirmBox, useDataChange, t,
} from "../lib.js";
import { MoveDialog } from "./move.js";

// 기본 정산 대상(저축·투자 항목) 추정. 한국어·영어 기본 항목 이름 모두에 맞춘다.
const SAVINGS_HINT = /저축|투자|saving|invest/i;   // i18n-ok

export function CashflowPage({ params }) {
  const { categories } = useApp();
  const month = params.month || thisMonth();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [move, setMove] = useState(null);
  const [copying, setCopying] = useState(false);

  const load = () => api("/budget", { params: { month } }).then((x) => { setD(x); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => { setD(null); load(); }, [month]);
  useDataChange(() => load());   // 다른 곳에서 바뀐 내용(항목 추가·삭제·이름·색 등)도 바로 반영
  // 칸 저장: 서버가 돌려준 최신 예산으로 바로 갱신
  const save = async (path, body) => {
    try { setD(await api(path, { method: "PUT", body: { month, ...body } })); return true; }
    catch (e) { toastErr(e); return false; }
  };

  const expenseCats = categories.filter(c => c.kind === "expense");
  const savingsId = useMemo(() => (expenseCats.find(c => c.is_active && SAVINGS_HINT.test(c.name)) || {}).id, [categories]);
  const ctx = { month, d, categories, expenseCats, savingsId, save, openMove: setMove };

  return html`<div class="page">
    <div class="page-head">
      <h1>${t("cashflow.title")}</h1>
      <${MonthPicker} value=${month} onChange=${(m) => setParams({ month: m })} />
      ${d && html`<button class="btn sm" onClick=${() => setCopying(true)}>${t("cashflow.copy_prev")}</button>`}
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
          <div class="muted small" style="padding:4px 2px;line-height:1.6">${t("cashflow.autosave_hint")}</div>
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
    <span class="step ${s1}">${t("cashflow.step.income")} <b>${won(d.income_total)}</b></span>
    <span class="step ${s2}">${t("cashflow.step.alloc")} <b>${d.unallocated === 0 ? t("cashflow.step.done") : d.unallocated > 0 ? t("cashflow.amount_left", { amount: won(d.unallocated) }) : t("cashflow.amount_over", { amount: won(-d.unallocated) })}</b></span>
    <span class="step ${s3}">${t("cashflow.step.spend")} <b>${d.plan_total ? pct(d.spent_total / d.plan_total * 100) : "–"}</b></span>
    <span class="step ${s4}">${t("cashflow.step.settle")} <b>${d.settled ? (d.balanced ? t("cashflow.step.done") : t("cashflow.step.again")) : d.is_past ? t("cashflow.step.needed") : t("cashflow.step.month_end")}</b></span>
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
    if (Number.isNaN(n)) { toast(t("cashflow.enter_number"), "err"); setText(fmt(value)); return; }
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
  return html`<span class="selbar"><b>${t("cashflow.n_selected", { n: sh.sel.size })}</b>
    ${onMove && html`<button class="btn sm" onClick=${onMove}>${t("cashflow.move_selected")}</button>`}
    <button class="btn sm danger" onClick=${() => sh.removeIds([...sh.sel], t("cashflow.confirm_delete_selected", { n: sh.sel.size }))}>${t("cashflow.delete_selected")}</button>
    <button class="btn sm" onClick=${sh.clearSel}>${t("cashflow.clear_selection")}</button></span>`;
}

// 처음 그려질 때 포커스를 받을 수 있는 텍스트 칸. Enter → 같은 줄의 다음 입력 칸으로.
function ItemName({ value, autofocus, onCommit, readOnly, hint }) {
  const ref = useRef();
  const [text, setText] = useState(value || "");
  useEffect(() => setText(value || ""), [value]);
  useEffect(() => { if (autofocus && ref.current) ref.current.focus(); }, [autofocus]);
  return html`<input ref=${ref} type="text" class="cell" value=${text} placeholder=${hint || t("cashflow.item_name")} readOnly=${readOnly}
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
    <button class="fold-btn" onClick=${() => sh.toggleCollapse(c.category_id)} title=${folded ? t("cashflow.expand") : t("cashflow.collapse")}>${folded ? "▸" : "▾"}</button>
    <span class="dot" style=${c.color ? `background:${c.color}` : ""}></span><span class="nm" title=${c.memo || ""}>${c.name}</span>
    ${c.count > 0 && html`<span class="muted small"> ${c.count}</span>`}
    ${c.is_active && html`<span class="row-tools"><button class="tool add" onClick=${onAdd} title=${t("cashflow.add_item_title")}>${t("cashflow.add_item")}</button></span>`}
  </td>`;
}

function ItemCells({ it, sh }) {
  const settle = it.tag === "settle";
  return html`<td class="namecell item">
    <input type="checkbox" class="selbox ${sh.sel.size ? "on" : ""}" checked=${sh.sel.has(it.id)} onChange=${() => sh.toggleSel(it.id)} title=${t("cashflow.select")} />
    ${settle ? html`<span class="muted">${it.item || t("cashflow.settle_item")} <span class="tag blue">${t("cashflow.settle_tag")}</span></span>`
      : html`<${ItemName} value=${it.item} hint=${it.memo} autofocus=${sh.focusId === it.id} onCommit=${(v) => sh.save(it.id, { item: v })} />`}
  </td>`;
}

function DelCell({ it, sh, colspan = 1 }) {
  return html`<td class="actions" colspan=${colspan}>${it.tag !== "settle" && html`<button class="btn link del-x" title=${t("cashflow.delete")}
    onClick=${() => sh.removeIds([it.id], t("cashflow.confirm_delete_item", { name: it.item || t("cashflow.unnamed"), amount: won(it.amount) }))}>✕</button>`}</td>`;
}

// ───────── ①③ 소득·지출 표 (항목 + 세부항목) ─────────
// 소득과 지출은 같은 표를 쓴다. 다른 점(어느 목록·합계·날짜 이름)만 SHEETS 에 둔다.
// 문구는 키로 두고 렌더할 때 t() 로 꺼낸다(언어를 바꾸면 바로 바뀌도록).
const SHEETS = {
  income: {
    title: "cashflow.income.title", hint: "cashflow.income.hint", dateLabel: "cashflow.income.date", dateTitle: "cashflow.income.date_title",
    groups: (d) => d.income_items, sum: (c) => c.total, emptyTitle: "cashflow.income.empty",
    footer: (d) => html`<td>${t("cashflow.income.total")}</td><td class="num">${won(d.income_total)}</td>
      <td colspan="2" class="small muted">${d.income_pending ? t("cashflow.income.pending_incl", { amount: won(d.income_pending) }) : ""}</td>`,
  },
  expense: {
    title: "cashflow.expense.title", hint: "cashflow.expense.hint", dateLabel: "cashflow.expense.date", dateTitle: "cashflow.expense.date_title",
    groups: (d) => d.envelopes, sum: (c) => c.spent, emptyTitle: "cashflow.expense.empty",
    footer: (d) => html`<td>${t("cashflow.expense.total")}</td><td class="num">${won(d.spent_total)}</td><td colspan="2"></td>`,
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
          <input type="date" class="cell" value=${it.txn_date || ""} title=${t(cfg.dateTitle)} onChange=${(e) => sh.save(it.id, { txn_date: e.target.value || null })} />
          ${kind === "income" && it.amount > 0 && !it.txn_date && html`<span class="tag amber">${t("cashflow.not_paid")}</span>`}`}</td>
        <${DelCell} it=${it} sh=${sh} />
      </tr>`);
    }
  }
  return html`<div class="panel">
    <div class="panel-head"><h2>${t(cfg.title)}</h2><span class="hint">${t(cfg.hint)}</span><div class="spacer"></div>
      <${SelectionBar} sh=${sh} onMove=${() => setMoveIds([...sh.sel])} /></div>
    ${moveIds && html`<${MoveDialog} kind=${kind} ids=${moveIds} fromId=${fromIdOf(moveIds)} onClose=${() => setMoveIds(null)} onMoved=${() => sh.clearSel()} />`}
    <div class="panel-body flush"><table class="t sheet">
      <thead><tr><th>${t("cashflow.col.category_item")}</th><th class="num" style="width:150px">${t("cashflow.col.amount")}</th><th style="width:190px">${t(cfg.dateLabel)}</th><th style="width:1%"></th></tr></thead>
      <tbody>${rows}
        ${groups.length === 0 && html`<tr><td colspan="4"><${Empty} title=${t(cfg.emptyTitle)}>${t("cashflow.empty_hint")}<//></td></tr>`}
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
    const left = used === null ? t("cashflow.plan.no_plan") : t("cashflow.plan.used", { pct: Math.round(used) });
    const right = e.remaining < 0 ? html`<span class="neg">${t("cashflow.amount_over", { amount: won(-e.remaining) })}</span>`
      : daysLeft > 0 && e.remaining > 0 ? t("cashflow.plan.per_day", { amount: won(Math.floor(e.remaining / daysLeft)) }) : "";
    const tip = used === null ? "" : t("cashflow.plan.tip_used", { pct: Math.round(used) })
      + (marker ? t("cashflow.plan.tip_today", { pct: Math.round(d.pace * 100) }) : "")
      + (daysLeft > 0 ? t("cashflow.plan.tip_days_left", { n: daysLeft }) : "");
    return html`<div class="pwrap" title=${tip}>
      <div class="pbar"><i class=${e.status} style="width:${fill}%"></i>${marker && html`<b style="left:${d.pace * 100}%"></b>`}</div>
      <div class="pcap"><span class=${e.status === "fast" ? "warn" : ""}>${left}${e.status === "fast" ? t("cashflow.plan.fast") : ""}</span><span>${right}</span></div>
    </div>`;
  };
  const rows = d.envelopes.map(e => html`<tr key=${"c" + e.category_id} class="${e.status === "over" || e.status === "unplanned" ? "over" : ""} ${e.is_active ? "" : "inactive"}">
      <td class="namecell"><span class="dot" style=${e.color ? `background:${e.color}` : ""}></span><span class="nm" title=${e.memo || ""}>${e.name}</span></td>
      <td class="num"><${GridMoney} col="plan" value=${e.plan} onCommit=${(n) => ctx.save("/budget/plan", { category_id: e.category_id, amount: n })}
        disabled=${!e.is_active && !e.plan} />${e.plan !== e.plan_base && html`<span class="adj" title=${t("cashflow.plan.adjusted", { amount: won(e.plan_base) })}>*</span>`}</td>
      <td class="num ${e.spent ? "" : "muted"}">${e.spent ? won(e.spent) : "–"}${e.items.some(i => i.tag === "settle") && html`<span class="adj" title=${t("cashflow.plan.settle_included")}>${t("cashflow.plan.settle_mark")}</span>`}</td>
      <td class="num ${e.remaining < 0 ? "neg" : e.status === "empty" || (e.remaining === 0 && e.plan > 0) ? "muted" : ""}"><b>${e.status === "empty" ? "–" : won(e.remaining)}</b></td>
      <td>${bar(e)}</td>
      <td class="actions">${e.remaining < 0 && html`<button class="btn sm" onClick=${() => ctx.openMove(e)} title=${t("cashflow.plan.fill_title")}>${t("cashflow.plan.fill")}</button>`}</td>
    </tr>`);
  return html`<div class="panel">
    <div class="panel-head"><h2>${t("cashflow.plan.title")}</h2>
      <span class="hint">${t("cashflow.plan.hint")}</span></div>
    <div class="panel-body flush"><table class="t sheet">
      <thead><tr><th>${t("cashflow.col.category")}</th><th class="num" style="width:130px">${t("cashflow.col.plan")}</th><th class="num" style="width:130px">${t("cashflow.col.actual")}</th>
        <th class="num" style="width:110px">${t("cashflow.col.left")}</th><th style="min-width:120px">${t("cashflow.col.progress")}</th><th style="width:1%"></th></tr></thead>
      <tbody>${rows}
        ${d.envelopes.length === 0 && html`<tr><td colspan="6"><${Empty} title=${t("cashflow.expense.empty")}>${t("cashflow.plan.empty_hint")}<//></td></tr>`}
      </tbody>
      <tfoot><tr><td>${t("cashflow.total")}</td><td class="num">${won(d.plan_total)}</td><td class="num">${won(d.spent_total)}</td>
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
  const tgt = target || ctx.savingsId || options[0]?.category_id;
  const tone = d.income_total === 0 ? "" : u === 0 ? "ok" : u > 0 ? "warn" : "bad";
  async function fill() {
    const e = d.envelopes.find(x => x.category_id === tgt);
    await ctx.save("/budget/plan", { category_id: tgt, amount: (e ? e.plan : 0) + u });
  }
  return html`<div class="panel">
    <div class="panel-head"><h2>${t("cashflow.alloc.title")}</h2><span class="hint">${t("cashflow.alloc.hint")}</span></div>
    <div class="panel-body">
      <div class="bignum ${tone}">
        <div class="small">${u === 0 && d.income_total ? t("cashflow.alloc.all_done") : u >= 0 ? t("cashflow.alloc.unallocated") : t("cashflow.alloc.over")}</div>
        <div class="v">${u === 0 && d.income_total ? `✓ ${won(0)}` : won(Math.abs(u))}</div>
      </div>
      <div class="muted small" style="margin-top:6px">${t("cashflow.alloc.formula", { income: won(d.income_total), plan: won(d.plan_total) })}</div>
      ${u > 0 && options.length > 0 && html`<div class="row" style="margin-top:8px;flex-wrap:nowrap">
        <select value=${tgt} onChange=${(e) => setTarget(Number(e.target.value))} style="flex:1;min-width:0">
          ${options.map(e => html`<option value=${e.category_id}>${e.full_name}</option>`)}</select>
        <button class="btn sm" onClick=${fill}>${t("cashflow.alloc.put_all")}</button></div>`}
      ${u < 0 && html`<div class="small" style="margin-top:6px;color:var(--neg)">${t("cashflow.alloc.reduce")}</div>`}
    </div>
  </div>`;
}

function SettleCard({ ctx }) {
  const { month, d } = ctx;
  const [target, setTarget] = useState(null);
  const options = ctx.expenseCats.filter(c => c.is_active);
  const tgt = target || ctx.savingsId || options[0]?.id;
  async function settle() {
    const name = options.find(c => c.id === tgt)?.name;
    const note = d.income_pending > 0 ? t("cashflow.settle.pending_note", { amount: won(d.income_pending) }) : "";
    if (!confirmBox(t("cashflow.settle.confirm", { amount: won(d.leftover), name, note }))) return;
    try { await api("/budget/settle", { method: "POST", body: { month, category_id: tgt } }); toast(t("cashflow.settle.done"), "ok"); }
    catch (e) { toastErr(e); }
  }
  async function resettle() {
    const name = options.find(c => c.id === d.settle_target)?.name || t("cashflow.settle.default_target");
    if (!confirmBox(t("cashflow.settle.confirm_again", { name }))) return;
    try { await api("/budget/settle", { method: "POST", body: { month, category_id: d.settle_target } }); toast(t("cashflow.settle.done_again"), "ok"); }
    catch (e) { toastErr(e); }
  }
  async function unsettle() {
    if (!confirmBox(t("cashflow.settle.confirm_cancel"))) return;
    try { await api("/budget/settle", { method: "DELETE", params: { month } }); } catch (e) { toastErr(e); }
  }
  const tone = d.leftover < 0 ? "bad" : d.settled && d.balanced ? "ok" : "";
  return html`<div class="panel">
    <div class="panel-head"><h2>${t("cashflow.settle.title")}</h2><span class="hint">${t("cashflow.settle.hint")}</span></div>
    <div class="panel-body">
      <div class="bignum ${tone}">
        <div class="small">${d.settled && d.balanced ? t("cashflow.settle.complete") : d.leftover < 0 ? t("cashflow.settle.overspent") : t("cashflow.settle.unspent")}</div>
        <div class="v">${d.settled && d.balanced ? `✓ ${won(0)}` : won(Math.abs(d.leftover))}</div>
      </div>
      ${d.settled ? html`
        ${!d.balanced && html`<div class="small" style="color:var(--warn);margin-top:6px">${t("cashflow.settle.changed")}</div>`}
        <div class="row" style="margin-top:8px">
          ${!d.balanced && html`<button class="btn sm primary" onClick=${resettle} disabled=${d.leftover_before_settle < 0}>${t("cashflow.settle.again")}</button>`}
          <button class="btn sm" onClick=${unsettle}>${t("cashflow.settle.cancel")}</button></div>
        ${!d.balanced && d.leftover_before_settle < 0 && html`<div class="small" style="color:var(--neg);margin-top:6px">${t("cashflow.settle.cannot_again")}</div>`}`
      : d.leftover < 0 ? html`<div class="small" style="color:var(--neg);margin-top:6px">${t("cashflow.settle.need_income")}</div>`
      : html`<div class="small muted" style="margin-top:6px">${d.is_past ? t("cashflow.settle.past") : t("cashflow.settle.future")}</div>
        <div class="row" style="margin-top:8px;flex-wrap:nowrap">
          <select value=${tgt} onChange=${(e) => setTarget(Number(e.target.value))} style="flex:1;min-width:0">
            ${options.map(c => html`<option value=${c.id}>${c.full_name}</option>`)}</select>
          <button class="btn sm ${d.is_past ? "primary" : ""}" onClick=${settle} disabled=${d.income_total === 0}>${t("cashflow.settle.button")}</button></div>`}
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
    if (amounts && v.plan_overwrite && !confirmBox(t("cashflow.copy.confirm_overwrite", { n: v.plan_overwrite }))) return;
    setBusy(true);
    try {
      const r = await api("/budget/copy-month", { method: "POST", body: { from, to: month, items, amounts } });
      const c = r.copied, parts = [];
      if (c.income_items) parts.push(t("cashflow.copy.income_items", { n: c.income_items }));
      if (c.plan_items) parts.push(t("cashflow.copy.plan_items", { n: c.plan_items }));
      toast(parts.length ? t("cashflow.copy.done", { parts: parts.join(", ") }) : t("cashflow.copy.nothing_new"), "ok");
      onDone();
    } catch (e) { toastErr(e); } finally { setBusy(false); }
  }

  return html`<${Modal} title=${t("cashflow.copy.title", { month: monthLabel(from) })} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>${t("common.cancel")}</button>
      <button class="btn primary" onClick=${apply} disabled=${busy || nothing || (!items && !amounts)}>${t("cashflow.copy.button")}</button>`}>
    ${p.loading && !v ? html`<${Loading} />` : p.error ? html`<${ErrorBox} error=${p.error} />` : html`
      <label class="checkline"><input type="checkbox" class="selbox" checked=${items} onChange=${() => setItems(!items)} />
        <b>${t("cashflow.copy.items")}</b><span class="muted small">${t("cashflow.copy.items_desc", { n: v.income_items })}</span></label>
      <label class="checkline"><input type="checkbox" class="selbox" checked=${amounts} onChange=${() => setAmounts(!amounts)} />
        <b>${t("cashflow.copy.amounts")}</b><span class="muted small">${items ? t("cashflow.copy.amounts_income", { amount: won(v.income_total) }) : ""}${t("cashflow.copy.amounts_plan", { n: v.plan_items, amount: won(v.plan_total) })}</span></label>
      ${items && !amounts && nIncome > 0 && html`<p class="small muted">${t("cashflow.copy.zero_note")}</p>`}
      ${amounts && v.plan_overwrite > 0 && html`<div class="notice warn" style="margin-top:10px">${t("cashflow.copy.overwrite_note", { n: v.plan_overwrite })}</div>`}
      ${nothing && (items || amounts) && html`<p class="small muted">${t("cashflow.copy.nothing")}</p>`}`}
  <//>`;
}

function MoveModal({ ctx, target, onClose, onSaved }) {
  const { d, month } = ctx;
  const sources = d.envelopes.filter(e => e.category_id !== target.category_id && e.remaining > 0).sort((a, b) => b.remaining - a.remaining);
  const [from, setFrom] = useState(d.unallocated > 0 ? "" : (sources[0]?.category_id ?? ""));
  const [amount, setAmount] = useState(fmtMoneyInput(String(Math.max(0, -target.remaining))));
  async function save() {
    if (from === "" && Number(parseMoney(amount)) > d.unallocated) return toast(t("cashflow.move.over_unallocated"), "err");
    try {
      await api("/budget/move", { method: "POST", body: { month, from_category_id: from || null, to_category_id: target.category_id, amount: parseMoney(amount) } });
      toast(t("cashflow.move.done"), "ok"); onSaved();
    } catch (e) { toastErr(e); }
  }
  return html`<${Modal} title=${t("cashflow.move.title", { name: target.name })} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>${t("common.cancel")}</button><button class="btn primary" onClick=${save}>${t("cashflow.move.button")}</button>`}>
    <p class="small muted" style="margin-top:0">${t("cashflow.move.desc", { name: target.name })}</p>
    <div class="form-grid">
      <label>${t("cashflow.move.from")}</label>
      <select value=${from} onChange=${(e) => setFrom(e.target.value ? Number(e.target.value) : "")}>
        ${d.unallocated > 0 && html`<option value="">${t("cashflow.move.unallocated_opt", { amount: won(d.unallocated) })}</option>`}
        ${sources.map(e => html`<option value=${e.category_id}>${t("cashflow.move.source_opt", { name: e.name, amount: won(e.remaining) })}</option>`)}
      </select>
      <label>${t("cashflow.col.amount")}</label><${MoneyInput} value=${amount} onInput=${setAmount} />
    </div>
    ${sources.length === 0 && d.unallocated <= 0 && html`<div class="notice warn" style="margin-top:10px">${t("cashflow.move.no_source")}</div>`}
  <//>`;
}
