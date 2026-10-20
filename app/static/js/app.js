import { html, render, useState, useEffect, api, Toasts, AppCtx, parseHash, toastErr, useDataChange, t, setLocale } from "./lib.js";
import { DashboardPage } from "./pages/dashboard.js";
import { CashflowPage } from "./pages/cashflow.js";
import { SettingsPage } from "./pages/settings.js";

// [키, 메뉴 문구 키(t), 아이콘, 페이지]
const PAGES = [
  ["dashboard", "nav.dashboard", "▦", DashboardPage],
  ["cashflow", "nav.cashflow", "₩", CashflowPage],
  // 자산 관리(pages/assets.js)·지표 추적(pages/indicators.js)은 추후 다시 추가할 예정이라 메뉴에서만 숨겨 둔다.
  ["settings", "nav.settings", "⚙", SettingsPage],
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

  // 표시 설정(언어·날짜·금액 단위)을 자식보다 먼저 적용한다. 설정이 바뀌면(reloadSettings) 앱 전체가 다시 그려진다.
  setLocale(settings);
  const lang = settings.language === "en" ? "en" : "ko";
  if (document.documentElement.lang !== lang) document.documentElement.lang = lang;

  const entry = PAGES.find(p => p[0] === route.page) || PAGES[0];
  const Page = entry[3];
  const ctx = { categories, reloadCategories, settings, reloadSettings, meta };
  return html`<${AppCtx.Provider} value=${ctx}>
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">${t("app.name")}<small>${t("app.subtitle")}</small></div>
        <nav>${PAGES.map(([key, label, ico]) =>
          html`<a href="#/${key}" class=${entry[0] === key ? "active" : ""}><span class="ico">${ico}</span>${t(label)}</a>`)}</nav>
        <div class="foot">${meta ? html`v${meta.version} · DB v${meta.schema_version}` : ""}<br/>${t("app.foot")}</div>
      </aside>
      <main class="main"><${Page} key=${entry[0]} params=${route.params} /></main>
    </div>
    <${Toasts} />
  </${AppCtx.Provider}>`;
}

render(html`<${App} />`, document.getElementById("app"));
