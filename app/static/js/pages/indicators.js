import {
  html, useState, useApi, api, useApp, num, today, Modal, Empty, Loading, ErrorBox, toast, toastErr, setParams, ChartView,
  exportFile, pickFile, confirmBox,
} from "../lib.js";

const PROVIDER_LABEL = { manual: "수동 입력", ecos: "한국은행 ECOS", fred: "FRED" };

export function IndicatorsPage({ params }) {
  const { settings } = useApp();
  const [version, setVersion] = useState(0);
  const bump = () => setVersion(v => v + 1);
  const list = useApi("/indicators", null, [version]);
  const [editing, setEditing] = useState(null);
  const [presetOpen, setPresetOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const inds = list.data || [];
  const selId = params.id ? Number(params.id) : inds[0]?.id;
  const sel = inds.find(i => i.id === selId);

  async function refreshAll() {
    setBusy(true);
    try {
      const r = await api("/indicators/refresh-all", { method: "POST" });
      if (!r.results.length) toast("자동 업데이트 대상(ECOS/FRED) 지표가 없습니다.");
      else toast(r.results.map(x => `${x.ok ? "✓" : "✕"} ${x.name}${x.ok ? ` (${x.fetched}건)` : `: ${x.error}`}`).join("\n"), r.results.every(x => x.ok) ? "ok" : "err");
      bump();
    } catch (e) { toastErr(e); } finally { setBusy(false); }
  }

  const needsEcos = inds.some(i => i.provider === "ecos") && !settings.ecos_api_key_set;
  const needsFred = inds.some(i => i.provider === "fred") && !settings.fred_api_key_set;

  return html`<div class="page">
    <div class="page-head"><h1>지표 추적</h1><div class="spacer"></div>
      <button class="btn" onClick=${refreshAll} disabled=${busy}>${busy ? "업데이트 중…" : "API 지표 전체 업데이트"}</button>
      <button class="btn" onClick=${() => setPresetOpen(true)}>프리셋에서 추가</button>
      <button class="btn primary" onClick=${() => setEditing({ provider: "manual", decimals: 2, provider_config: {} })}>+ 지표 직접 추가</button></div>
    ${(needsEcos || needsFred) && html`<div class="notice warn">
      ${needsEcos && "ECOS "}${needsEcos && needsFred && "· "}${needsFred && "FRED "}API 키가 설정되지 않아 자동 업데이트를 할 수 없습니다.
      <a href="#/settings">설정</a>에서 본인 키를 입력하거나, 값을 수동/CSV로 입력하세요.</div>`}
    ${list.error && html`<${ErrorBox} error=${list.error} onRetry=${list.reload} />`}
    ${list.loading && !list.data ? html`<${Loading} />` : inds.length === 0 ? html`<div class="panel"><${Empty} title="추적 중인 지표가 없습니다">
      '프리셋에서 추가'로 기준금리·환율·KOSPI 등을 추가하거나 직접 정의하세요. 값은 공식 API, CSV, 수동 입력으로만 채워지며 임의 데이터는 표시하지 않습니다.<//></div>` : html`
    <div class="panel"><div class="panel-body flush table-wrap" style="max-height:360px"><table class="t">
      <thead><tr><th>지표</th><th class="num">현재값</th><th class="num">이전값 대비</th><th>기준일</th><th>최근 업데이트</th><th>출처</th><th>주기</th><th>수집 방식</th></tr></thead>
      <tbody>${inds.map(i => html`<tr key=${i.id} style="cursor:pointer;${i.id === selId ? "background:#eef3ff" : ""}" onClick=${() => setParams({ id: i.id })}>
        <td><b>${i.name}</b> <span class="muted small">${i.unit}</span></td>
        <td class="num"><b>${i.current ? num(i.current.value, i.decimals) : "–"}</b></td>
        <td class="num ${i.change > 0 ? "pos" : i.change < 0 ? "neg" : ""}">${i.change !== null ? `${i.change > 0 ? "+" : ""}${num(i.change, i.decimals)}${i.change_pct !== null ? ` (${i.change_pct > 0 ? "+" : ""}${i.change_pct.toFixed(2)}%)` : ""}` : "–"}</td>
        <td class="small nowrap">${i.current?.date || "–"}</td>
        <td class="small nowrap">${i.last_updated || "–"}${i.last_error && html` <span class="tag red" title=${i.last_error}>실패</span>`}</td>
        <td class="small">${i.source_url ? html`<a href=${i.source_url} target="_blank" onClick=${(e) => e.stopPropagation()}>${i.source || "링크"}</a>` : i.source || html`<span class="muted">미기재</span>`}</td>
        <td class="small">${i.frequency || "–"}</td>
        <td><span class="tag ${i.provider === "manual" ? "" : "blue"}">${PROVIDER_LABEL[i.provider]}</span></td></tr>`)}</tbody></table></div></div>
    ${sel && html`<${Detail} key=${sel.id + ":" + version} ind=${sel} onChanged=${bump} onEdit=${() => setEditing(sel)} />`}`}
    ${editing && html`<${IndicatorModal} initial=${editing} onClose=${() => setEditing(null)} onSaved=${(r) => { setEditing(null); bump(); setParams({ id: r.id }); }} />`}
    ${presetOpen && html`<${PresetModal} existing=${inds.map(i => i.name)} onClose=${() => setPresetOpen(false)} onAdded=${(r) => { bump(); setParams({ id: r.id }); }} />`}
  </div>`;
}

function Detail({ ind, onChanged, onEdit }) {
  const [range, setRange] = useState("3y");
  const start = range === "all" ? null : (() => { const d = new Date(); d.setFullYear(d.getFullYear() - (range === "1y" ? 1 : range === "3y" ? 3 : 10)); return d.toISOString().slice(0, 10); })();
  const values = useApi(`/indicators/${ind.id}/values`, { start });
  const [d, setD] = useState(today());
  const [v, setV] = useState("");
  const [busy, setBusy] = useState(false);
  const vals = values.data || [];

  async function add() {
    try { await api(`/indicators/${ind.id}/values`, { method: "POST", body: { date: d, value: v } }); setV(""); onChanged(); toast("저장했습니다.", "ok"); }
    catch (e) { toastErr(e); }
  }
  async function del(date) { try { await api(`/indicators/${ind.id}/values`, { method: "DELETE", params: { date } }); onChanged(); } catch (e) { toastErr(e); } }
  async function refresh(full) {
    setBusy(true);
    try { const r = await api(`/indicators/${ind.id}/refresh`, { method: "POST", params: { full } }); toast(`${r.fetched}건을 가져왔습니다.`, "ok"); onChanged(); }
    catch (e) { toastErr(e); onChanged(); } finally { setBusy(false); }
  }
  async function importCsv() {
    const f = await pickFile(".csv,text/csv");
    if (!f) return;
    const buf = await f.arrayBuffer();
    try {
      const dry = await api(`/import/indicator/${ind.id}`, { method: "POST", raw: buf, params: { dry_run: true } });
      if (!dry.ok) return toast("가져오기 오류:\n" + dry.errors.slice(0, 8).map(e => `${e.row ?? ""}행: ${e.message}`).join("\n"), "err");
      if (!confirmBox(`${dry.total}개 값을 가져옵니다(같은 날짜는 덮어씀). 계속할까요?`)) return;
      await api(`/import/indicator/${ind.id}`, { method: "POST", raw: buf, params: { dry_run: false } });
      toast("가져왔습니다.", "ok"); onChanged();
    } catch (e) { toastErr(e); }
  }
  async function remove() {
    if (!confirmBox(`'${ind.name}' 지표와 모든 값을 삭제할까요?`)) return;
    try { await api(`/indicators/${ind.id}`, { method: "DELETE" }); setParams({ id: "" }); onChanged(); } catch (e) { toastErr(e); }
  }

  const config = {
    type: "line",
    data: { labels: vals.map(x => x.date), datasets: [{ label: ind.name, data: vals.map(x => x.value), borderColor: "#2459d6", backgroundColor: "rgba(36,89,214,.08)", fill: true, pointRadius: vals.length > 60 ? 0 : 2, borderWidth: 1.6, stepped: ind.frequency?.includes("수시"), fmt: (y) => `${num(y, ind.decimals)} ${ind.unit}` }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 10 }, grid: { display: false } }, y: { grid: { color: "#eef0f3" } } } },
  };

  return html`<div class="grid c32">
    <div class="panel">
      <div class="panel-head"><h2>${ind.name}</h2><span class="hint">${ind.unit} · ${PROVIDER_LABEL[ind.provider]}${ind.provider !== "manual" ? ` (${Object.values(ind.provider_config).join(" / ")})` : ""}</span>
        <div class="spacer"></div>
        <div class="btn-group">${[["1y", "1년"], ["3y", "3년"], ["10y", "10년"], ["all", "전체"]].map(([k, l]) => html`<button class="btn sm ${range === k ? "on" : ""}" onClick=${() => setRange(k)}>${l}</button>`)}</div></div>
      <div class="panel-body">
        ${ind.last_error && html`<div class="notice err">최근 자동 업데이트 실패 (${ind.last_fetched_at}): ${ind.last_error}</div>`}
        ${vals.length === 0 ? html`<${Empty} title="저장된 값이 없습니다">${ind.provider === "manual" ? "오른쪽에서 값을 입력하거나 CSV로 가져오세요." : "'API에서 가져오기'를 누르거나 수동/CSV로 입력하세요."}<//>`
          : html`<${ChartView} config=${config} className="chart-box tall" />`}
        <div class="row" style="margin-top:10px">
          ${ind.provider !== "manual" && html`<button class="btn" onClick=${() => refresh(false)} disabled=${busy}>API에서 가져오기</button>
            <button class="btn" onClick=${() => refresh(true)} disabled=${busy} title="최근 3년 전체 다시 받기">전체 다시 받기</button>`}
          <button class="btn" onClick=${importCsv}>CSV 가져오기</button>
          <button class="btn" onClick=${() => exportFile(`/export/indicator/${ind.id}`)}>CSV 내보내기</button>
          <div class="spacer" style="flex:1"></div>
          <button class="btn" onClick=${onEdit}>지표 설정</button>
          <button class="btn danger" onClick=${remove}>삭제</button>
        </div>
        ${ind.memo && html`<p class="muted small">${ind.memo}</p>`}
      </div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>값 입력·목록</h2><span class="hint">${ind.value_count}건</span></div>
      <div class="panel-body">
        <div class="row"><input type="date" value=${d} onInput=${(e) => setD(e.target.value)} />
          <input type="text" class="amount" placeholder="값" value=${v} onInput=${(e) => setV(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && add()} style="width:110px" />
          <button class="btn primary" onClick=${add}>저장</button></div>
      </div>
      <div class="panel-body flush table-wrap" style="max-height:330px"><table class="t">
        <thead><tr><th>날짜</th><th class="num">값</th><th>출처</th><th></th></tr></thead>
        <tbody>${[...vals].reverse().slice(0, 300).map(x => html`<tr><td>${x.date}</td><td class="num">${num(x.value, ind.decimals)}</td>
          <td class="small">${PROVIDER_LABEL[x.source] || x.source.toUpperCase()}</td>
          <td class="actions"><button class="btn sm danger" onClick=${() => del(x.date)}>삭제</button></td></tr>`)}</tbody></table></div>
    </div>
  </div>`;
}

function IndicatorModal({ initial, onClose, onSaved }) {
  const [f, setF] = useState({ name: "", unit: "", source: "", source_url: "", frequency: "", memo: "", ...initial,
                               provider_config: { ...(initial.provider_config || {}) } });
  const [items, setItems] = useState(null);
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const cfg = (k) => (e) => setF({ ...f, provider_config: { ...f.provider_config, [k]: e.target.value } });
  async function save() {
    try { const r = await api(initial.id ? `/indicators/${initial.id}` : "/indicators", { method: initial.id ? "PUT" : "POST", body: f }); onSaved(r); }
    catch (e) { toastErr(e); }
  }
  async function lookup() {
    try { setItems(await api("/ecos/items", { params: { stat_code: f.provider_config.stat_code } })); } catch (e) { toastErr(e); }
  }
  return html`<${Modal} wide title=${initial.id ? "지표 설정" : "지표 추가"} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button><button class="btn primary" onClick=${save}>저장</button>`}>
    <div class="form-grid">
      <label>지표명</label><input type="text" value=${f.name} onInput=${upd("name")} />
      <label>단위</label><input type="text" value=${f.unit} onInput=${upd("unit")} placeholder="%, 원, pt …" />
      <label>소수 자릿수</label><input type="number" min="0" max="6" value=${f.decimals} onInput=${upd("decimals")} style="width:80px" />
      <label>데이터 출처</label><input type="text" value=${f.source} onInput=${upd("source")} placeholder="예: 한국은행 ECOS" />
      <label>출처 URL</label><input type="text" value=${f.source_url} onInput=${upd("source_url")} />
      <label>업데이트 주기</label><input type="text" value=${f.frequency} onInput=${upd("frequency")} placeholder="일 / 월 / 분기 / 수시" />
      <label>수집 방식</label><select value=${f.provider} onChange=${upd("provider")}>
        <option value="manual">수동 입력 / CSV</option><option value="ecos">한국은행 ECOS API</option><option value="fred">FRED API</option></select>
      ${f.provider === "ecos" && html`
        <label>통계표코드</label><div class="row"><input type="text" value=${f.provider_config.stat_code || ""} onInput=${cfg("stat_code")} placeholder="예: 722Y001" style="width:140px" />
          <button class="btn sm" onClick=${lookup}>항목 조회</button></div>
        <label>주기</label><select value=${f.provider_config.cycle || "D"} onChange=${cfg("cycle")}><option value="D">D (일)</option><option value="M">M (월)</option><option value="Q">Q (분기)</option><option value="A">A (연)</option></select>
        <label>항목코드1</label><input type="text" value=${f.provider_config.item_code1 || ""} onInput=${cfg("item_code1")} />
        <label>항목코드2</label><input type="text" value=${f.provider_config.item_code2 || ""} onInput=${cfg("item_code2")} placeholder="(선택)" />
        <div class="field-help">통계표·항목코드는 ECOS 'Open API → 통계코드검색' 또는 위 '항목 조회'(API 키 필요)로 확인하세요.</div>
        ${items && html`<div style="grid-column:1/-1" class="table-wrap"><table class="t"><thead><tr><th>항목코드</th><th>항목명</th><th>주기</th><th>기간</th><th>단위</th><th></th></tr></thead>
          <tbody>${items.map(it => html`<tr><td><code>${it.item_code}</code></td><td>${it.item_name}</td><td>${it.cycle}</td><td class="small">${it.start}~${it.end}</td><td class="small">${it.unit}</td>
            <td><button class="btn sm" onClick=${() => setF({ ...f, provider_config: { ...f.provider_config, item_code1: it.item_code, cycle: it.cycle } })}>선택</button></td></tr>`)}</tbody></table></div>`}`}
      ${f.provider === "fred" && html`
        <label>시리즈 ID</label><input type="text" value=${f.provider_config.series_id || ""} onInput=${cfg("series_id")} placeholder="예: SP500, DGS10" />
        <div class="field-help">fred.stlouisfed.org 의 시리즈 페이지 주소 끝부분이 ID입니다.</div>`}
      <label>메모</label><input type="text" value=${f.memo} onInput=${upd("memo")} />
    </div><//>`;
}

function PresetModal({ existing, onClose, onAdded }) {
  const presets = useApi("/indicators/presets");
  const [added, setAdded] = useState([]);
  async function add(p) {
    try { const r = await api(`/indicators/presets/${p.key}`, { method: "POST" }); setAdded([...added, p.name]); onAdded(r); toast(`'${p.name}' 추가`, "ok"); }
    catch (e) { toastErr(e); }
  }
  return html`<${Modal} wide title="프리셋에서 지표 추가" onClose=${onClose} footer=${html`<button class="btn" onClick=${onClose}>닫기</button>`}>
    <div class="notice">프리셋은 지표 '정의'만 추가합니다(값 없음). 값은 설정에서 본인 API 키를 입력한 뒤 'API에서 가져오기'로 받거나, 수동/CSV로 입력하세요.
      ECOS 코드는 공식 문서로 재확인할 수 있도록 지표 설정에서 수정 가능합니다.</div>
    <table class="t"><thead><tr><th>지표</th><th>출처</th><th>코드</th><th>주기</th><th></th></tr></thead>
      <tbody>${(presets.data || []).map(p => { const has = existing.includes(p.name) || added.includes(p.name); return html`<tr>
        <td><b>${p.name}</b> <span class="muted small">${p.unit}</span></td><td class="small">${p.source}</td>
        <td class="small"><code>${Object.values(p.provider_config).join(" / ")}</code></td><td class="small">${p.frequency}</td>
        <td class="actions">${has ? html`<span class="tag green">추가됨</span>` : html`<button class="btn sm primary" onClick=${() => add(p)}>추가</button>`}</td></tr>`; })}</tbody></table>
  <//>`;
}
