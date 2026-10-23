import {
  html, useState, useEffect, useApi, api, useApp, won, Empty, toast, toastErr, setParams, exportFile, pickFile, confirmBox, nextColor,
  monthLabel, dateLabel, dateTimeLabel, today, thisMonth,
} from "../lib.js";
import { MoveDialog } from "./move.js";

// [키, 탭 이름]
const TABS = [["categories", "항목"], ["data", "백업·복원"], ["csv", "CSV 가져오기·내보내기"],
              ["display", "표시"]];

export function SettingsPage({ params }) {
  const { reloadCategories } = useApp();
  useEffect(() => { reloadCategories(); }, []);
  const tab = TABS.some(([k]) => k === params.tab) ? params.tab : "categories";
  return html`<div class="page">
    <div class="page-head"><h1>설정 및 데이터 관리</h1></div>
    <div class="tabs">${TABS.map(([k, l]) => html`<button class=${tab === k ? "on" : ""} onClick=${() => setParams({ tab: k })}>${l}</button>`)}</div>
    ${tab === "categories" && html`<div class="grid c2"><${CategoryList} kind="income" /><${CategoryList} kind="expense" /></div>`}
    ${tab === "data" && html`<${BackupView} />`}
    ${tab === "csv" && html`<${CsvView} />`}
    ${tab === "display" && html`<${DisplayView} />`}
  </div>`;
}

// 표시(D-17): 날짜 표기·금액 단위. 선택지 라벨은 실제 예시 그대로 보여 준다.
const DISPLAY_OPTIONS = {
  date_format: [["iso", "2026-10-21"], ["dot", "2026.10.21"], ["ko", "2026년 10월 21일"], ["en", "Oct 21, 2026"]],
  currency_display: [["won", "1,234,000원"], ["symbol", "₩1,234,000"], ["code", "KRW 1,234,000"]],
};
const DISPLAY_DEFAULTS = { date_format: "ko", currency_display: "won" };

function DisplayView() {
  const { settings, reloadSettings } = useApp();
  const [busy, setBusy] = useState(false);
  const change = async (key, value) => {
    setBusy(true);
    try {
      await api("/settings", { method: "PUT", body: { [key]: value } });
      await reloadSettings();
      toast("표시 설정을 저장했습니다.", "ok");
    } catch (e) { toastErr(e); }
    finally { setBusy(false); }
  };
  const select = (key) => html`<select value=${settings[key] || DISPLAY_DEFAULTS[key]} disabled=${busy}
      onChange=${(e) => change(key, e.target.value)}>
    ${DISPLAY_OPTIONS[key].map(([v, l]) => html`<option value=${v}>${l}</option>`)}</select>`;
  return html`<div class="panel display-settings"><div class="panel-head"><h2>표시 형식</h2></div>
    <div class="panel-body">
      <div class="form-grid">
        <label>날짜 표기</label>${select("date_format")}
        <label>금액 단위</label>${select("currency_display")}
        <label>미리보기</label>
        <div>오늘 ${dateLabel(today())} · 이번 달 ${monthLabel(thisMonth())} · ${won(1234000)}</div>
      </div>
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
  const linkedNote = (n, many) => n ? (many ? `\n\n이 항목들에 연결된 기록(계획·지출 포함) ${n}건도 함께 삭제됩니다. 되돌리려면 백업에서 복원해야 합니다.` : `\n\n이 항목에 연결된 기록(계획·지출 포함) ${n}건도 함께 삭제됩니다. 되돌리려면 백업에서 복원해야 합니다.`) : "";
  const remove = async (c) => {
    let n;
    try { n = (await freshCounts([c.id]))[c.id] || 0; } catch (e) { return toastErr(e); }
    if (await confirmBox(`'${c.name}' 항목을 삭제할까요?${linkedNote(n, false)}`)) {
      run(() => api(`/categories/${c.id}`, { method: "DELETE", params: { with_records: n ? true : undefined } }));
    }
  };
  const removeSelected = async () => {
    const picked = list.filter(c => sel.has(c.id));
    let counts;
    try { counts = await freshCounts(picked.map(c => c.id)); } catch (e) { return toastErr(e); }
    const n = picked.reduce((a, c) => a + (counts[c.id] || 0), 0);
    if (!await confirmBox(`${picked.length}개 항목을 삭제할까요?\n${picked.map(c => c.name).join(", ")}${linkedNote(n, true)}`)) return;
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
    <div class="panel-head"><h2>${kind === "income" ? "소득 항목" : "지출 항목"}</h2>
      <span class="hint">${kind === "income" ? "추가한 항목은 매달 소득 표에 나타납니다." : "추가한 항목은 매달 지출 표에 나타납니다."} ⠿ 끌어서 순서 변경, ✕ 삭제.</span>
      <div class="spacer"></div>
      ${sel.size > 0 && html`<span class="selbar"><b>${sel.size}개 선택</b>
        <button class="btn sm danger" onClick=${removeSelected}>선택 삭제</button>
        <button class="btn sm" onClick=${() => setSel(new Set())}>선택 해제</button></span>`}</div>
    <div class="panel-body flush"><table class="t catlist"><tbody>
      ${list.map(c => html`<tr key=${c.id} class=${hint && hint.id === c.id ? `drop-${hint.pos}` : ""}
          onDragOver=${(e) => { if (!drag || drag === c.id) return; e.preventDefault(); const r = e.currentTarget.getBoundingClientRect();
            const pos = e.clientY < r.top + r.height / 2 ? "before" : "after"; if (!hint || hint.id !== c.id || hint.pos !== pos) setHint({ id: c.id, pos }); }}
          onDrop=${(e) => { e.preventDefault(); drop(c); }}>
        <td style="width:28px"><input type="checkbox" class="selbox ${sel.size ? "on" : ""}" checked=${sel.has(c.id)} onChange=${() => toggleSel(c.id)} title="선택" /></td>
        <td style="width:24px"><span class="handle" draggable="true" title="끌어서 순서 변경"
          onDragStart=${(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(c.id)); setDrag(c.id); }}
          onDragEnd=${() => { setDrag(null); setHint(null); }}>⠿</span></td>
        <td class="nowrap"><input type="color" class="swatch" value=${c.color || "#94a3b8"} title="색 변경" onChange=${(e) => recolor(c, e.target.value)} />
          <input type="text" class="cell" value=${c.name} onBlur=${(e) => rename(c, e.target.value)} onKeyDown=${(e) => e.key === "Enter" && e.target.blur()} /></td>
        <td class="memocell"><input type="text" class="cell memo" value=${c.memo || ""} placeholder="메모"
          onBlur=${(e) => setMemo(c, e.target.value)} onKeyDown=${(e) => e.key === "Enter" && e.target.blur()} /></td>
        <td class="actions nowrap"><button class="btn link move-x" onClick=${() => setMoving(c)} title="이 항목의 기록을 다른 항목으로 옮기기(합치기·나누기)">옮기기</button>
          <button class="btn link del-x" onClick=${() => remove(c)} title="삭제">✕</button></td>
      </tr>`)}
      ${list.length === 0 && html`<tr><td colspan="5"><${Empty} title="아직 항목이 없습니다">아래 칸에 이름을 쓰고 Enter를 누르세요.<//></td></tr>`}
    </tbody></table>
    <div class="row" style="padding:8px 10px;border-top:1px solid var(--line-2)">
      <input type="text" value=${name} placeholder=${kind === "income" ? "새 소득 항목 이름 (예: 급여)" : "새 지출 항목 이름 (예: 식비)"} style="flex:1"
        onInput=${(e) => setName(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && add()} />
      <button class="btn primary sm" onClick=${add}>+ 항목</button></div>
    ${moving && html`<${MoveDialog} kind=${kind} fromId=${moving.id} fromName=${moving.name} onClose=${() => setMoving(null)}
      onMoved=${async (r) => {
        // 전부 옮겼으면(= 합치기) 비게 된 항목을 지울지 묻는다
        if (r.all && await confirmBox(`'${moving.name}'의 기록을 모두 옮겼습니다. 비어 있는 '${moving.name}' 항목을 삭제할까요?`)) {
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
    try { const r = await api("/backups", { method: "POST" }); toast(`백업 완료: ${r.name}`, "ok"); list.reload(); } catch (e) { toastErr(e); } finally { setBusy(false); }
  }
  async function restore(name) {
    if (!await confirmBox(`'${name}'으로 복원하면 현재 데이터가 백업 시점으로 바뀝니다.\n(현재 데이터는 복원 직전에 자동 백업됩니다)\n계속할까요?`)) return;
    try { const r = await api(`/backups/${encodeURIComponent(name)}/restore`, { method: "POST" }); toast(`복원 완료. 안전 백업: ${r.safety_backup}`, "ok"); setTimeout(() => location.reload(), 900); }
    catch (e) { toastErr(e); }
  }
  async function restoreFile() {
    const f = await pickFile(".db");
    if (!f) return;
    if (!await confirmBox(`'${f.name}' 파일로 복원할까요? 현재 데이터는 자동 백업됩니다.`)) return;
    try { const r = await api("/restore-upload", { method: "POST", raw: await f.arrayBuffer() }); toast(`복원 완료. 안전 백업: ${r.safety_backup}`, "ok"); setTimeout(() => location.reload(), 900); }
    catch (e) { toastErr(e); }
  }
  async function del(name) {
    if (!await confirmBox(`백업 파일 '${name}'을 삭제할까요?`)) return;
    try { await api(`/backups/${encodeURIComponent(name)}`, { method: "DELETE" }); list.reload(); } catch (e) { toastErr(e); }
  }
  const openFolder = (which) => api("/open-folder", { method: "POST", body: { which } }).catch(toastErr);
  async function reset(mode) {
    const what = mode === "records" ? "모든 달의 소득·계획·지출 기록을 지웁니다. 항목은 그대로 남습니다." : "항목과 모든 기록을 지우고 처음 설치한 상태(기본 항목)로 되돌립니다.";
    if (!await confirmBox(`${what}\n지우기 전에 현재 데이터를 자동 백업합니다. 계속할까요?`)) return;
    if (!await confirmBox("정말 초기화할까요? 되돌리려면 백업 목록에서 pre_reset 백업을 복원해야 합니다.")) return;
    try { const r = await api("/reset", { method: "POST", body: { mode } }); toast(`초기화했습니다. 백업: ${r.safety_backup}`, "ok"); setTimeout(() => location.reload(), 900); }
    catch (e) { toastErr(e); }
  }
  return html`<div class="grid c32">
    <div class="panel"><div class="panel-head"><h2>백업 목록</h2><div class="spacer"></div>
      <button class="btn" onClick=${() => openFolder("backups")}>폴더 열기</button>
      <button class="btn" onClick=${restoreFile}>파일에서 복원…</button>
      <button class="btn primary" onClick=${create} disabled=${busy}>지금 백업</button></div>
      <div class="panel-body flush table-wrap"><table class="t">
        <thead><tr><th>파일</th><th>생성 시각</th><th class="num">크기</th><th></th></tr></thead>
        <tbody>${(list.data || []).map(b => html`<tr><td><code>${b.name}</code>
            ${b.name.startsWith("pre_") && html` <span class="tag amber">자동</span>`}</td>
          <td class="small nowrap">${dateTimeLabel(b.modified)}</td><td class="num">${(b.size / 1024).toFixed(0)} KB</td>
          <td class="actions"><a class="btn sm" href=${`/api/backups/${encodeURIComponent(b.name)}/download`} download>다운로드</a>
            <button class="btn sm" onClick=${() => restore(b.name)}>복원</button>
            <button class="btn sm danger" onClick=${() => del(b.name)}>삭제</button></td></tr>`)}
          ${list.data && list.data.length === 0 && html`<tr><td colspan="4"><${Empty} title="백업이 없습니다">'지금 백업'을 눌러 첫 백업을 만드세요.<//></td></tr>`}</tbody></table></div></div>
    <div>
    <div class="panel"><div class="panel-head"><h2>데이터 위치</h2></div><div class="panel-body">
      ${meta && html`<dl class="kv" style="grid-template-columns:auto 1fr">
        <dt>데이터 폴더</dt><dd style="text-align:left"><code>${meta.data_dir}</code></dd>
        <dt>DB 파일</dt><dd style="text-align:left"><code>${meta.db_path}</code></dd>
        <dt>스키마 버전</dt><dd style="text-align:left">v${meta.schema_version}</dd>
        <dt>프로그램 버전</dt><dd style="text-align:left">v${meta.version}</dd></dl>`}
      <div class="row" style="margin-top:10px"><button class="btn" onClick=${() => openFolder("data")}>데이터 폴더 열기</button></div>
      <p class="muted small">· 백업 파일(.db)은 전체 데이터(항목·기록·설정)를 담은 SQLite 파일입니다. 외장 드라이브나 클라우드 폴더에 복사해 두세요.<br/>
        · 복원 전에 파일 무결성·버전을 검사하며, 현재 데이터는 <code>pre_restore_*.db</code>로 자동 보관됩니다.<br/>
        · 스키마 업그레이드 시에도 <code>pre_migration_*.db</code>가 자동 생성됩니다.<br/>
        · 백업 파일에는 모든 기록이 포함됩니다. 공유 시 주의하세요.</p>
    </div></div>
    <div class="panel"><div class="panel-head"><h2>초기화</h2></div><div class="panel-body">
      <div class="row" style="gap:8px">
        <button class="btn danger" onClick=${() => reset("records")}>기록만 지우기</button>
        <button class="btn danger" onClick=${() => reset("all")}>처음 상태로</button></div>
      <p class="muted small" style="margin-bottom:0">'기록만 지우기'는 항목을 남기고 모든 기록을 지웁니다. '처음 상태로'는 항목까지 지우고 기본 항목으로 되돌립니다. 둘 다 지우기 전에 <code>pre_reset_*.db</code>로 자동 백업합니다.</p>
    </div></div>
    </div>
  </div>`;
}

const IMPORT_TYPES = {
  records: { label: "소득·지출 기록", path: "/import/records", template: "records", help: "열: 구분(수입/지출계획/실제지출), 항목, 세부항목, 금액, 월(지출계획의 월 / 날짜가 없을 때), 거래일(수입=입금일, 지출=발생일), 결제일, 예산월(수입을 쓸 달), 메모" },
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
      if (!dry && r.applied) { toast(`${r.total}건을 가져왔습니다.`, "ok"); setFile(null); reloadCategories(); }
    } catch (e) { toastErr(e); setResult(null); }
  }
  return html`<div class="grid c2">
    <div class="panel"><div class="panel-head"><h2>CSV 가져오기</h2><span class="hint">검증 후 저장 · 오류가 하나라도 있으면 아무것도 저장하지 않음</span></div>
      <div class="panel-body">
        <div class="form-grid">
          <label>데이터 종류</label><select value=${type} onChange=${(e) => { setType(e.target.value); setResult(null); setFile(null); }}>
            ${Object.entries(IMPORT_TYPES).map(([k, v]) => html`<option value=${k}>${v.label}</option>`)}</select>
          <div class="field-help">${cfg.help}</div>
          ${type === "records" && html`<label>옵션</label><label><input type="checkbox" checked=${createMissing} onChange=${(e) => { setCreateMissing(e.target.checked); setResult(null); }} /> 없는 항목 자동 생성</label>`}
          <label>양식</label><div><button class="btn sm" onClick=${() => exportFile(`/templates/${cfg.template}`)}>예시 양식 받기</button></div>
          <label>파일</label><div class="row"><button class="btn" onClick=${choose}>CSV 파일 선택…</button>${file && html`<code>${file.name}</code>`}</div>
        </div>
        <p class="muted small">UTF-8 / CP949(Excel 기본 저장) 모두 지원합니다. 금액의 쉼표·'원'은 자동 제거됩니다.</p>
        ${result && html`<div style="margin-top:10px">
          ${result.ok ? html`<div class="notice">${result.applied ? `✓ ${result.total}건 저장 완료` : `검증 통과: ${result.total}건을 가져올 수 있습니다.`}
              ${result.created.length > 0 && html`<br/>새로 생성될 항목/종목: ${result.created.join(", ")}`}</div>
              ${!result.applied && html`<button class="btn primary" onClick=${() => run(file.buf, false)}>${result.total}건 가져오기</button>`}`
            : html`<div class="notice err">오류 ${result.errors.length}건 — 파일을 수정한 뒤 다시 선택하세요. 아무것도 저장되지 않았습니다.</div>
              <div class="table-wrap" style="max-height:260px"><table class="t"><thead><tr><th style="width:60px">행</th><th>오류</th></tr></thead>
                <tbody>${result.errors.map(e => html`<tr><td class="num">${e.row ?? "-"}</td><td>${e.message}</td></tr>`)}</tbody></table></div>`}
          ${result.preview.length > 0 && result.ok && !result.applied && html`<details style="margin-top:8px"><summary class="small">미리보기 (처음 ${result.preview.length}행)</summary>
            <table class="t small"><tbody>${result.preview.map(p => html`<tr>${Object.values(p).map(v => html`<td>${typeof v === "number" && v > 999 ? won(v, { unit: false }) : v ?? ""}</td>`)}</tr>`)}</tbody></table></details>`}
        </div>`}
      </div></div>
    <div class="panel"><div class="panel-head"><h2>CSV 내보내기</h2><span class="hint">Excel에서 바로 열 수 있는 UTF-8(BOM)</span></div>
      <div class="panel-body"><table class="t"><tbody>
        <tr><td>수입·지출 전체 기록</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records")}>내보내기</button></td></tr>
        <tr><td>소득만</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records", { kind: "income" })}>내보내기</button></td></tr>
        <tr><td>지출 계획만</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records", { kind: "plan" })}>내보내기</button></td></tr>
        <tr><td>실제 지출만</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/records", { kind: "expense" })}>내보내기</button></td></tr>
        <tr><td>항목 목록</td><td class="actions"><button class="btn sm" onClick=${() => exportFile("/export/categories")}>내보내기</button></td></tr>
      </tbody></table>
      <p class="muted small">전체 데이터 보관은 '백업·복원'을 사용하세요.</p></div></div>
  </div>`;
}
