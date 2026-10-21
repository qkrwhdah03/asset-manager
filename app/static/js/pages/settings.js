import {
  html, useState, useEffect, useApi, api, useApp, won, Empty, toast, toastErr, setParams, exportFile, pickFile, confirmBox, nextColor,
  t, monthLabel, dateLabel, dateTimeLabel, today, thisMonth,
} from "../lib.js";
import { MoveDialog } from "./move.js";

// [키, 탭 이름 문구 키(t)]
const TABS = [["categories", "settings.tab.categories"], ["data", "settings.tab.data"], ["csv", "settings.tab.csv"],
              ["display", "settings.tab.display"]];

export function SettingsPage({ params }) {
  const { reloadCategories } = useApp();
  useEffect(() => { reloadCategories(); }, []);
  const tab = TABS.some(([k]) => k === params.tab) ? params.tab : "categories";
  return html`<div class="page">
    <div class="page-head"><h1>${t("settings.title")}</h1></div>
    <div class="tabs">${TABS.map(([k, l]) => html`<button class=${tab === k ? "on" : ""} onClick=${() => setParams({ tab: k })}>${t(l)}</button>`)}</div>
    ${tab === "categories" && html`<div class="grid c2"><${CategoryList} kind="income" /><${CategoryList} kind="expense" /></div>`}
    ${tab === "data" && html`<${BackupView} />`}
    ${tab === "csv" && html`<${CsvView} />`}
    ${tab === "display" && html`<${DisplayView} />`}
  </div>`;
}

// 표시(D-17): 언어·날짜 표기·금액 단위. 선택지 라벨은 실제 예시 그대로 보여 준다(언어와 무관).
const DISPLAY_OPTIONS = {
  language: [["ko", "한국어"], ["en", "English"]],   // i18n-ok
  date_format: [["auto", null], ["iso", "2026-10-21"], ["dot", "2026.10.21"], ["ko", "2026년 10월 21일"], ["en", "Oct 21, 2026"]],   // i18n-ok
  currency_display: [["auto", null], ["won", "1,234,000원"], ["symbol", "₩1,234,000"], ["code", "KRW 1,234,000"]],   // i18n-ok
};

// 문구 안의 {code} 자리에 <code> 요소를 넣는다(자리표시자를 남긴 채 t() 로 꺼내 둘로 나눈다).
function withCode(key, code) {
  const [a, b = ""] = t(key).split("{code}");
  return html`${a}<code>${code}</code>${b}`;
}

function DisplayView() {
  const { settings, reloadSettings } = useApp();
  const [busy, setBusy] = useState(false);
  const change = async (key, value) => {
    setBusy(true);
    try {
      await api("/settings", { method: "PUT", body: { [key]: value } });
      await reloadSettings();
      toast(t("display.saved"), "ok");
    } catch (e) { toastErr(e); }
    finally { setBusy(false); }
  };
  const select = (key) => html`<select value=${settings[key] || DISPLAY_OPTIONS[key][0][0]} disabled=${busy}
      onChange=${(e) => change(key, e.target.value)}>
    ${DISPLAY_OPTIONS[key].map(([v, l]) => html`<option value=${v}>${l ?? t("display.auto")}</option>`)}</select>`;
  return html`<div class="panel display-settings"><div class="panel-head"><h2>${t("display.title")}</h2></div>
    <div class="panel-body">
      <div class="form-grid">
        <label>${t("display.language")}</label>${select("language")}
        <label>${t("display.date_format")}</label>${select("date_format")}
        <label>${t("display.currency")}</label>${select("currency_display")}
        <label>${t("display.preview")}</label>
        <div>${t("display.preview_line", { date: dateLabel(today()), month: monthLabel(thisMonth()), amount: won(1234000) })}</div>
      </div>
      <p class="muted small">${t("display.note")}</p>
    </div></div>`;
}

// 항목: 모든 달에 똑같이 적용된다. 각 달에서는 항목 아래에 세부항목만 기록한다.
function CategoryList({ kind }) {
  const { categories, reloadCategories } = useApp();
  const list = categories.filter(c => c.kind === kind);
  const [name, setName] = useState("");
  const [drag, setDrag] = useState(null);
  const [hint, setHint] = useState(null);   // { id, pos }
  const [sel, setSel] = useState(new Set());
  const [moving, setMoving] = useState(null);   // 기록을 옮길 항목
  const toggleSel = (id) => { const n = new Set(sel); n.has(id) ? n.delete(id) : n.add(id); setSel(n); };
  const run = async (fn) => { try { await fn(); reloadCategories(); return true; } catch (e) { toastErr(e); return false; } };

  const add = async () => {
    const n = name.trim();
    // 새 항목에는 아직 쓰지 않은 색을 자동으로 지정한다(모두 쓰였으면 순환)
    const color = nextColor(categories);
    if (n && await run(() => api("/categories", { method: "POST", body: { name: n, kind, color } }))) setName("");
  };
  const recolor = (c, v) => { if (v && v !== c.color) run(() => api(`/categories/${c.id}`, { method: "PUT", body: { color: v } })); };
  const setMemo = (c, v) => { const m = v.trim(); if (m !== (c.memo || "")) run(() => api(`/categories/${c.id}`, { method: "PUT", body: { memo: m } })); };
  const rename = (c, v) => { const n = v.trim(); if (n && n !== c.name) run(() => api(`/categories/${c.id}`, { method: "PUT", body: { name: n } })); };
  // 삭제 직전에 서버에서 최신 기록 수를 다시 받아 확인창에 쓴다(다른 화면에서 방금 추가한 기록도 반영)
  const freshCounts = async (ids) => {
    const all = await api("/categories");
    return Object.fromEntries(all.filter(c => ids.includes(c.id)).map(c => [c.id, c.record_count]));
  };
  const linkedNote = (n, many) => n ? (many ? t("categories.linked_note_many", { n }) : t("categories.linked_note_one", { n })) : "";
  const remove = async (c) => {
    let n;
    try { n = (await freshCounts([c.id]))[c.id] || 0; } catch (e) { return toastErr(e); }
    if (confirmBox(t("categories.confirm_delete", { name: c.name, note: linkedNote(n, false) }))) {
      run(() => api(`/categories/${c.id}`, { method: "DELETE", params: { with_records: n ? true : undefined } }));
    }
  };
  const removeSelected = async () => {
    const picked = list.filter(c => sel.has(c.id));
    let counts;
    try { counts = await freshCounts(picked.map(c => c.id)); } catch (e) { return toastErr(e); }
    const n = picked.reduce((a, c) => a + (counts[c.id] || 0), 0);
    if (!confirmBox(t("categories.confirm_delete_many", { n: picked.length, names: picked.map(c => c.name).join(", "), note: linkedNote(n, true) }))) return;
    if (await run(() => api("/categories/bulk-delete", { method: "POST", body: { ids: [...sel] } }))) setSel(new Set());
  };
  const drop = (c) => {
    if (!drag || !hint || drag === c.id) return;
    const i = list.findIndex(x => x.id === c.id);
    const before = hint.pos === "before" ? c.id : list[i + 1]?.id ?? null;
    run(() => api(`/categories/${drag}/reorder`, { method: "POST", body: { before_id: before === drag ? null : before } }));
    setDrag(null); setHint(null);
  };

  return html`<div class="panel">
    <div class="panel-head"><h2>${kind === "income" ? t("categories.income_title") : t("categories.expense_title")}</h2>
      <span class="hint">${kind === "income" ? t("categories.income_hint") : t("categories.expense_hint")} ${t("categories.hint_tools")}</span>
      <div class="spacer"></div>
      ${sel.size > 0 && html`<span class="selbar"><b>${t("categories.n_selected", { n: sel.size })}</b>
        <button class="btn sm danger" onClick=${removeSelected}>${t("categories.delete_selected")}</button>
        <button class="btn sm" onClick=${() => setSel(new Set())}>${t("categories.clear_selection")}</button></span>`}</div>
    <div class="panel-body flush"><table class="t catlist"><tbody>
      ${list.map(c => html`<tr key=${c.id} class=${hint && hint.id === c.id ? `drop-${hint.pos}` : ""}
          onDragOver=${(e) => { if (!drag || drag === c.id) return; e.preventDefault(); const r = e.currentTarget.getBoundingClientRect();
            const pos = e.clientY < r.top + r.height / 2 ? "before" : "after"; if (!hint || hint.id !== c.id || hint.pos !== pos) setHint({ id: c.id, pos }); }}
          onDrop=${(e) => { e.preventDefault(); drop(c); }}>
        <td style="width:28px"><input type="checkbox" class="selbox ${sel.size ? "on" : ""}" checked=${sel.has(c.id)} onChange=${() => toggleSel(c.id)} title=${t("categories.select")} /></td>
        <td style="width:24px"><span class="handle" draggable="true" title=${t("categories.drag")}
          onDragStart=${(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(c.id)); setDrag(c.id); }}
          onDragEnd=${() => { setDrag(null); setHint(null); }}>⠿</span></td>
        <td class="nowrap"><input type="color" class="swatch" value=${c.color || "#94a3b8"} title=${t("categories.color")} onChange=${(e) => recolor(c, e.target.value)} />
          <input type="text" class="cell" value=${c.name} onBlur=${(e) => rename(c, e.target.value)} onKeyDown=${(e) => e.key === "Enter" && e.target.blur()} /></td>
        <td class="memocell"><input type="text" class="cell memo" value=${c.memo || ""} placeholder=${t("categories.memo")}
          onBlur=${(e) => setMemo(c, e.target.value)} onKeyDown=${(e) => e.key === "Enter" && e.target.blur()} /></td>
        <td class="actions nowrap"><button class="btn link move-x" onClick=${() => setMoving(c)} title=${t("categories.move_title")}>${t("categories.move")}</button>
          <button class="btn link del-x" onClick=${() => remove(c)} title=${t("categories.delete")}>✕</button></td>
      </tr>`)}
      ${list.length === 0 && html`<tr><td colspan="5"><${Empty} title=${t("categories.empty")}>${t("categories.empty_hint")}<//></td></tr>`}
    </tbody></table>
    <div class="row" style="padding:8px 10px;border-top:1px solid var(--line-2)">
      <input type="text" value=${name} placeholder=${kind === "income" ? t("categories.new_income_placeholder") : t("categories.new_expense_placeholder")} style="flex:1"
        onInput=${(e) => setName(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && add()} />
      <button class="btn primary sm" onClick=${add}>${t("categories.add")}</button></div>
    ${moving && html`<${MoveDialog} kind=${kind} fromId=${moving.id} fromName=${moving.name} onClose=${() => setMoving(null)}
      onMoved=${async (r) => {
        // 전부 옮겼으면(= 합치기) 비게 된 항목을 지울지 묻는다
        if (r.all && confirmBox(t("categories.confirm_delete_empty", { name: moving.name }))) {
          await run(() => api(`/categories/${moving.id}`, { method: "DELETE" }));
        }
      }} />`}
    </div>
  </div>`;
}

function BackupView() {
  const { meta } = useApp();
  const list = useApi("/backups");
  const [busy, setBusy] = useState(false);
  async function create() {
    setBusy(true);
    try { const r = await api("/backups", { method: "POST" }); toast(t("backup.created", { name: r.name }), "ok"); list.reload(); } catch (e) { toastErr(e); } finally { setBusy(false); }
  }
  async function restore(name) {
    if (!confirmBox(t("backup.confirm_restore", { name }))) return;
    try { const r = await api(`/backups/${encodeURIComponent(name)}/restore`, { method: "POST" }); toast(t("backup.restored", { file: r.safety_backup }), "ok"); setTimeout(() => location.reload(), 900); }
    catch (e) { toastErr(e); }
  }
  async function restoreFile() {
    const f = await pickFile(".db");
    if (!f) return;
    if (!confirmBox(t("backup.confirm_restore_file", { name: f.name }))) return;
    try { const r = await api("/restore-upload", { method: "POST", raw: await f.arrayBuffer() }); toast(t("backup.restored", { file: r.safety_backup }), "ok"); setTimeout(() => location.reload(), 900); }
    catch (e) { toastErr(e); }
  }
  async function del(name) {
    if (!confirmBox(t("backup.confirm_delete", { name }))) return;
    try { await api(`/backups/${encodeURIComponent(name)}`, { method: "DELETE" }); list.reload(); } catch (e) { toastErr(e); }
  }
  const openFolder = (which) => api("/open-folder", { method: "POST", body: { which } }).catch(toastErr);
  async function reset(mode) {
    const what = mode === "records" ? t("backup.reset_records_what") : t("backup.reset_all_what");
    if (!confirmBox(t("backup.confirm_reset", { what }))) return;
    if (!confirmBox(t("backup.confirm_reset_again"))) return;
    try { const r = await api("/reset", { method: "POST", body: { mode } }); toast(t("backup.reset_done", { file: r.safety_backup }), "ok"); setTimeout(() => location.reload(), 900); }
    catch (e) { toastErr(e); }
  }
  return html`<div class="grid c32">
    <div class="panel"><div class="panel-head"><h2>${t("backup.list_title")}</h2><div class="spacer"></div>
      <button class="btn" onClick=${() => openFolder("backups")}>${t("backup.open_folder")}</button>
      <button class="btn" onClick=${restoreFile}>${t("backup.restore_file")}</button>
      <button class="btn primary" onClick=${create} disabled=${busy}>${t("backup.backup_now")}</button></div>
      <div class="panel-body flush table-wrap"><table class="t">
        <thead><tr><th>${t("backup.col.file")}</th><th>${t("backup.col.created")}</th><th class="num">${t("backup.col.size")}</th><th></th></tr></thead>
        <tbody>${(list.data || []).map(b => html`<tr><td><code>${b.name}</code>
            ${b.name.startsWith("pre_") && html` <span class="tag amber">${t("backup.auto")}</span>`}</td>
          <td class="small nowrap">${dateTimeLabel(b.modified)}</td><td class="num">${(b.size / 1024).toFixed(0)} KB</td>
          <td class="actions"><a class="btn sm" href=${`/api/backups/${encodeURIComponent(b.name)}/download`} download>${t("backup.download")}</a>
            <button class="btn sm" onClick=${() => restore(b.name)}>${t("backup.restore")}</button>
            <button class="btn sm danger" onClick=${() => del(b.name)}>${t("backup.delete")}</button></td></tr>`)}
          ${list.data && list.data.length === 0 && html`<tr><td colspan="4"><${Empty} title=${t("backup.empty")}>${t("backup.empty_hint")}<//></td></tr>`}</tbody></table></div></div>
    <div>
    <div class="panel"><div class="panel-head"><h2>${t("backup.location_title")}</h2></div><div class="panel-body">
      ${meta && html`<dl class="kv" style="grid-template-columns:auto 1fr">
        <dt>${t("backup.data_folder")}</dt><dd style="text-align:left"><code>${meta.data_dir}</code></dd>
        <dt>${t("backup.db_file")}</dt><dd style="text-align:left"><code>${meta.db_path}</code></dd>
        <dt>${t("backup.schema_version")}</dt><dd style="text-align:left">v${meta.schema_version}</dd>
        <dt>${t("backup.app_version")}</dt><dd style="text-align:left">v${meta.version}</dd></dl>`}
      <div class="row" style="margin-top:10px"><button class="btn" onClick=${() => openFolder("data")}>${t("backup.open_data_folder")}</button></div>
      <p class="muted small">${t("backup.note_file")}<br/>
        ${withCode("backup.note_restore", "pre_restore_*.db")}<br/>
        ${withCode("backup.note_migration", "pre_migration_*.db")}<br/>
        ${t("backup.note_share")}</p>
    </div></div>
    <div class="panel"><div class="panel-head"><h2>${t("backup.reset_title")}</h2></div><div class="panel-body">
      <div class="row" style="gap:8px">
        <button class="btn danger" onClick=${() => reset("records")}>${t("backup.reset_records")}</button>
        <button class="btn danger" onClick=${() => reset("all")}>${t("backup.reset_all")}</button></div>
      <p class="muted small" style="margin-bottom:0">${withCode("backup.reset_note", "pre_reset_*.db")}</p>
    </div></div>
    </div>
  </div>`;
}

// label·help 는 문구 키다. 렌더할 때 t() 로 꺼낸다.
const IMPORT_TYPES = {
  records: { label: "csv.type.records", path: "/import/records", template: "records", help: "csv.type.records_help" },
};

function CsvView() {
  const { reloadCategories } = useApp();
  const [type, setType] = useState("records");
  const [createMissing, setCreateMissing] = useState(false);
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const cfg = IMPORT_TYPES[type];
  async function choose() {
    const f = await pickFile(".csv,text/csv");
    if (!f) return;
    const buf = await f.arrayBuffer();
    setFile({ name: f.name, buf });
    await run(buf, true);
  }
  async function run(buf, dry) {
    try {
      const r = await api(cfg.path, { method: "POST", raw: buf, params: { dry_run: dry, create_missing: type === "records" ? createMissing : undefined } });
      setResult(r);
      if (!dry && r.applied) { toast(t("csv.imported", { n: r.total }), "ok"); setFile(null); reloadCategories(); }
    } catch (e) { toastErr(e); setResult(null); }
  }
  return html`<div class="grid c2">
    <div class="panel"><div class="panel-head"><h2>${t("csv.import_title")}</h2><span class="hint">${t("csv.import_hint")}</span></div>
      <div class="panel-body">
        <div class="form-grid">
          <label>${t("csv.data_type")}</label><select value=${type} onChange=${(e) => { setType(e.target.value); setResult(null); setFile(null); }}>
            ${Object.entries(IMPORT_TYPES).map(([k, v]) => html`<option value=${k}>${t(v.label)}</option>`)}</select>
          <div class="field-help">${t(cfg.help)}</div>
          ${type === "records" && html`<label>${t("csv.options")}</label><label><input type="checkbox" checked=${createMissing} onChange=${(e) => { setCreateMissing(e.target.checked); setResult(null); }} /> ${t("csv.create_missing")}</label>`}
          <label>${t("csv.template")}</label><div><button class="btn sm" onClick=${() => exportFile(`/templates/${cfg.template}`)}>${t("csv.get_template")}</button></div>
          <label>${t("csv.file")}</label><div class="row"><button class="btn" onClick=${choose}>${t("csv.choose_file")}</button>${file && html`<code>${file.name}</code>`}</div>
        </div>
        <p class="muted small">${t("csv.encoding_note")}</p>
        ${result && html`<div style="margin-top:10px">
          ${result.ok ? html`<div class="notice">${result.applied ? t("csv.saved", { n: result.total }) : t("csv.validated", { n: result.total })}
              ${result.created.length > 0 && html`<br/>${t("csv.will_create", { names: result.created.join(", ") })}`}</div>
              ${!result.applied && html`<button class="btn primary" onClick=${() => run(file.buf, false)}>${t("csv.import_n", { n: result.total })}</button>`}`
            : html`<div class="notice err">${t("csv.errors", { n: result.errors.length })}</div>
              <div class="table-wrap" style="max-height:260px"><table class="t"><thead><tr><th style="width:60px">${t("csv.col.row")}</th><th>${t("csv.col.error")}</th></tr></thead>
                <tbody>${result.errors.map(e => html`<tr><td class="num">${e.row ?? "-"}</td><td>${e.message}</td></tr>`)}</tbody></table></div>`}
          ${result.preview.length > 0 && result.ok && !result.applied && html`<details style="margin-top:8px"><summary class="small">${t("csv.preview", { n: result.preview.length })}</summary>
            <table class="t small"><tbody>${result.preview.map(p => html`<tr>${Object.values(p).map(v => html`<td>${typeof v === "number" && v > 999 ? won(v, { unit: false }) : v ?? ""}</td>`)}</tr>`)}</tbody></table></details>`}
        </div>`}
      </div></div>
    <div class="panel"><div class="panel-head"><h2>${t("csv.export_title")}</h2><span class="hint">${t("csv.export_hint")}</span></div>
      <div class="panel-body"><table class="t"><tbody>
        <tr><td>${t("csv.export.all")}</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records")}>${t("csv.export_button")}</button></td></tr>
        <tr><td>${t("csv.export.income")}</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records", { kind: "income" })}>${t("csv.export_button")}</button></td></tr>
        <tr><td>${t("csv.export.plan")}</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records", { kind: "plan" })}>${t("csv.export_button")}</button></td></tr>
        <tr><td>${t("csv.export.expense")}</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records", { kind: "expense" })}>${t("csv.export_button")}</button></td></tr>
        <tr><td>${t("csv.export.categories")}</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/categories")}>${t("csv.export_button")}</button></td></tr>
      </tbody></table>
      <p class="muted small">${t("csv.export_note")}</p></div></div>
  </div>`;
}
