import { html, render, useState, useEffect, api, Toasts, AppCtx, parseHash, toastErr, useDataChange } from "./lib.js";
import { DashboardPage } from "./pages/dashboard.js";
import { CashflowPage } from "./pages/cashflow.js";
import { SettingsPage } from "./pages/settings.js";

const PAGES = [
  ["dashboard", "대시보드", "▦", DashboardPage],
  ["cashflow", "월 예산 (수입·지출)", "₩", CashflowPage],
  // 자산 관리(pages/assets.js)·지표 추적(pages/indicators.js)은 추후 다시 추가할 예정이라 메뉴에서만 숨겨 둔다.
  ["settings", "설정 및 데이터", "⚙", SettingsPage],
];

function App() {
  const [route, setRoute] = useState(parseHash());
  const [categories, setCategories] = useState([]);
  const [settings, setSettings] = useState({});
  const [meta, setMeta] = useState(null);

  const reloadCategories = () => api("/categories").then(setCategories).catch(toastErr);
  const reloadSettings = () => api("/settings").then(setSettings).catch(toastErr);
  // 어느 화면에서든 데이터가 바뀌면 항목 목록(색·이름·메모·기록 수)을 바로 다시 불러온다.
  useDataChange(reloadCategories);

  useEffect(() => {
    const h = () => setRoute(parseHash());
    window.addEventListener("hashchange", h);
    window.addEventListener("paramschange", h);
    reloadCategories();
    reloadSettings();
    api("/meta").then(setMeta).catch(toastErr);
    return () => { window.removeEventListener("hashchange", h); window.removeEventListener("paramschange", h); };
  }, []);

  const entry = PAGES.find(p => p[0] === route.page) || PAGES[0];
  const Page = entry[3];
  const ctx = { categories, reloadCategories, settings, reloadSettings, meta };
  return html`<${AppCtx.Provider} value=${ctx}>
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">개인 자산 관리<small>월 예산 · 현금흐름</small></div>
        <nav>${PAGES.map(([key, label, ico]) =>
          html`<a href="#/${key}" class=${entry[0] === key ? "active" : ""}><span class="ico">${ico}</span>${label}</a>`)}</nav>
        <div class="foot">${meta ? html`v${meta.version} · DB v${meta.schema_version}` : ""}<br/>로컬 저장 · 오프라인 동작</div>
      </aside>
      <main class="main"><${Page} key=${entry[0]} params=${route.params} /></main>
    </div>
    <${Toasts} />
  </${AppCtx.Provider}>`;
}

render(html`<${App} />`, document.getElementById("app"));
