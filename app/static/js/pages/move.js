// 기록 옮기기 대화상자 — 합치기(전체 옮기기)·나누기(일부 옮기기)·새 항목으로 옮기기를 모두 이 하나로 한다.
// - ids 를 주면 그 기록들을 바로 옮긴다(월 예산에서 선택한 세부항목).
// - fromId 만 주면 그 항목의 모든 달 기록을 목록으로 보여 주고 고르게 한다(설정).
import { html, useState, useEffect, useApi, api, useApp, won, Modal, Empty, Loading, toast, toastErr, nextColor } from "../lib.js";

const LABEL = { income: "소득", plan: "계획", expense: "실제" };

export function MoveDialog({ kind, fromId, fromName, ids, onClose, onMoved }) {
  const { categories } = useApp();
  const list = useApi(ids ? null : "/records", { category_id: fromId });
  const rows = (list.data || []).filter(r => r.category_id === fromId)
    .sort((a, b) => (b.budget_month || b.month).localeCompare(a.budget_month || a.month) || a.kind.localeCompare(b.kind) || a.id - b.id);
  const [sel, setSel] = useState(new Set());
  const targets = categories.filter(c => c.kind === kind && c.id !== fromId);
  const [target, setTarget] = useState(targets[0] ? String(targets[0].id) : "new");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!targets.length) setTarget("new"); }, [targets.length]);

  const chosen = ids || [...sel];
  const allOn = rows.length > 0 && sel.size === rows.length;
  const toggle = (id) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n); };

  async function move() {
    if (!chosen.length) return toast("옮길 기록을 고르세요.", "err");
    const body = { ids: chosen };
    if (target === "new") {
      if (!newName.trim()) return toast("새 항목 이름을 입력하세요.", "err");
      body.new_category = { name: newName.trim(), color: nextColor(categories) };
    } else body.category_id = Number(target);
    setBusy(true);
    try {
      const r = await api("/records/move", { method: "POST", body });
      toast(`${r.moved}건을 옮겼습니다.`, "ok");
      onMoved && await onMoved({ ...r, all: !ids && chosen.length === rows.length });
      onClose();
    } catch (e) { toastErr(e); } finally { setBusy(false); }
  }

  return html`<${Modal} wide title=${ids ? `세부항목 ${ids.length}건 옮기기` : `'${fromName}' 기록 옮기기`} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button>
      <button class="btn primary" onClick=${move} disabled=${busy}>${chosen.length ? `${chosen.length}건 옮기기` : "옮기기"}</button>`}>
    ${!ids && html`
      <p class="small muted" style="margin-top:0">옮길 기록을 고르세요. 전부 옮기면 다른 항목과 합쳐지고, 일부만 옮기면 나눠집니다. 월별 합계는 바뀌지 않습니다.</p>
      ${list.loading && !list.data ? html`<${Loading} />` : rows.length === 0 ? html`<${Empty} title="옮길 기록이 없습니다" />` : html`
      <div class="table-wrap" style="max-height:300px"><table class="t small">
        <thead><tr><th style="width:28px"><input type="checkbox" checked=${allOn} onChange=${() => setSel(allOn ? new Set() : new Set(rows.map(r => r.id)))} title="전체 선택" /></th>
          <th>월</th><th>구분</th><th>세부항목</th><th class="num">금액</th></tr></thead>
        <tbody>${rows.map(r => html`<tr key=${r.id} class="clickrow" onClick=${() => toggle(r.id)}>
          <td><input type="checkbox" checked=${sel.has(r.id)} onClick=${(e) => e.stopPropagation()} onChange=${() => toggle(r.id)} /></td>
          <td class="nowrap">${r.budget_month || r.month}</td>
          <td>${r.tag === "settle" ? "월말 정산" : LABEL[r.kind]}</td>
          <td class="muted">${r.item || r.memo || ""}</td>
          <td class="num">${won(r.amount)}</td></tr>`)}</tbody></table></div>`}`}
    <div class="form-grid" style="margin-top:12px">
      <label>옮길 곳</label>
      <select value=${target} onChange=${(e) => setTarget(e.target.value)}>
        ${targets.map(c => html`<option value=${c.id}>${c.name}</option>`)}
        <option value="new">+ 새 항목 만들기…</option>
      </select>
      ${target === "new" && html`<label>새 항목 이름</label>
        <input type="text" value=${newName} placeholder=${kind === "income" ? "예: 부수입" : "예: 외식"} onInput=${(e) => setNewName(e.target.value)}
          onKeyDown=${(e) => e.key === "Enter" && move()} />`}
    </div>
  <//>`;
}
