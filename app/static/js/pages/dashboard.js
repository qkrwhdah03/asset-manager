import {
  html, useApi, won, pct, cls, monthLabel, thisMonth, addMonths, MonthPicker, Segmented, ChartView, wonAxis,
  PALETTE, Empty, ErrorBox, navigate, setParams, monthShort, yearLabel, t,
} from "../lib.js";

export function DashboardPage({ params }) {
  const month = params.month || thisMonth();
  const period = params.period || "6";
  const year = Number(month.slice(0, 4));
  const start = period === "year" ? `${year}-01` : addMonths(month, -(Number(period) - 1));
  const end = period === "year" ? `${year}-12` : month;

  const summary = useApi("/stats/summary", { month });
  const trend = useApi("/stats/trend", { start, end });
  const breakdown = useApi("/stats/breakdown", { kind: "expense", start: month, end: month });
  const pva = useApi("/stats/plan-vs-actual", { month });
  const annual = useApi("/stats/annual", { year });

  const s = summary.data;
  const goCash = () => navigate("cashflow", { month });

  return html`<div class="page">
    <div class="page-head">
      <h1>${t("dashboard.title")}</h1>
      <${MonthPicker} value=${month} onChange=${(m) => setParams({ month: m })} />
    </div>
    ${summary.error && html`<${ErrorBox} error=${summary.error} onRetry=${summary.reload} />`}

    <div class="cards">
      <div class="card clickable" onClick=${() => goCash()}>
        <div class="label">${t("dashboard.card.income", { month: monthLabel(month) })}</div>
        <div class="value">${s ? won(s.income) : "–"}</div>
        <div class="sub">${s ? t("dashboard.card.prev", { amount: won(s.prev_income) }) : ""}</div></div>
      <div class="card clickable" onClick=${() => goCash()}>
        <div class="label">${t("dashboard.card.expense")}</div>
        <div class="value">${s ? won(s.expense) : "–"}</div>
        <div class="sub">${s ? t("dashboard.card.prev", { amount: won(s.prev_expense) }) : ""}</div></div>
      <div class="card" title=${t("dashboard.card.savings_title")}>
        <div class="label">${t("dashboard.card.savings")} <span class="muted small">${t("dashboard.card.savings_formula")}</span></div>
        <div class="value ${s ? cls(s.savings) : ""}">${s ? won(s.savings) : "–"}</div>
        <div class="sub">${t("dashboard.card.savings_rate", { rate: s ? pct(s.savings_rate) : "–" })}</div></div>
      <div class="card clickable" onClick=${() => goCash()}>
        <div class="label">${t("dashboard.card.vs_plan")}</div>
        <div class="value ${s && s.plan_diff !== null ? cls(s.plan_diff, true) : ""}">
          ${s && s.plan_diff !== null ? (s.plan_diff > 0 ? t("dashboard.card.over", { amount: won(s.plan_diff) }) : s.plan_diff < 0 ? t("dashboard.card.saved", { amount: won(-s.plan_diff) }) : t("dashboard.card.on_plan")) : "–"}</div>
        <div class="sub">${s && s.plan_diff !== null ? t("dashboard.card.plan_sub", { amount: won(s.plan), n: s.over_count }) : t("dashboard.card.no_plan")}</div></div>
    </div>
    ${s && s.pending_income.count > 0 && html`<div class="notice warn">${t("dashboard.pending_notice", { n: s.pending_income.count, amount: won(s.pending_income.total) })}</div>`}

    <div class="panel">
      <div class="panel-head"><h2>${t("dashboard.trend.title")}</h2><span class="hint">${t("dashboard.trend.hint")}</span>
        <div class="spacer"></div>
        <${Segmented} value=${period} onChange=${(p) => setParams({ period: p })} options=${[["6", t("dashboard.period.6")], ["12", t("dashboard.period.12")], ["year", t("dashboard.period.year", { year: yearLabel(year) })]]} /></div>
      <div class="panel-body">${trend.data ? html`<${TrendChart} data=${trend.data} />` : trend.error ? html`<${ErrorBox} error=${trend.error} />` : ""}</div>
    </div>

    <div class="grid c2">
      <div class="panel">
        <div class="panel-head"><h2>${t("dashboard.savings.title")}</h2><span class="hint">${t("dashboard.savings.hint")}</span></div>
        <div class="panel-body">${trend.data && html`<${SavingsChart} data=${trend.data} />`}</div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>${t("dashboard.share.title", { month: monthLabel(month) })}</h2><span class="hint">${t("dashboard.share.hint")}</span></div>
        <div class="panel-body">${breakdown.data && (breakdown.data.length === 0
          ? html`<${Empty} title=${t("dashboard.share.empty")} />`
          : html`<${ShareChart} data=${breakdown.data} onPick=${() => goCash()} />`)}</div>
      </div>
    </div>

    <div class="grid c2">
      <div class="panel">
        <div class="panel-head"><h2>${t("dashboard.pva.title")}</h2><span class="hint">${t("dashboard.pva.hint")}</span></div>
        <div class="panel-body">${pva.data && (pva.data.items.length === 0
          ? html`<${Empty} title=${t("dashboard.pva.empty")}>${t("dashboard.pva.empty_hint")}<//>`
          : html`<${PlanChart} data=${pva.data} onPick=${() => goCash()} />`)}</div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>${t("dashboard.annual.title", { year: yearLabel(year) })}</h2></div>
        <div class="panel-body">${annual.data && html`<${AnnualSummary} d=${annual.data} />`}</div>
      </div>
    </div>
  </div>`;
}

function TrendChart({ data }) {
  const labels = data.map(d => monthShort(d.month));
  const config = {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: t("dashboard.series.income"), data: data.map(d => d.income), backgroundColor: "#2459d6", order: 2 },
        { label: t("dashboard.series.expense"), data: data.map(d => d.expense), backgroundColor: "#e8743b", order: 2 },
        { label: t("dashboard.series.plan"), data: data.map(d => d.plan || null), type: "line", borderColor: "#9aa3b2", borderDash: [4, 3], pointRadius: 2, backgroundColor: "#9aa3b2", order: 1 },
      ],
    },
    options: {
      scales: { y: wonAxis, x: { grid: { display: false } } },
      onClick: (_e, els) => { if (els.length) navigate("cashflow", { month: data[els[0].index].month }); },
      plugins: { tooltip: { callbacks: { title: (items) => monthLabel(data[items[0].dataIndex].month) } } },
    },
  };
  const hasAny = data.some(d => d.income || d.expense || d.plan);
  return hasAny ? html`<${ChartView} config=${config} className="chart-box tall" />` : html`<${Empty} title=${t("dashboard.trend.empty")}>${t("dashboard.trend.empty_hint")}<//>`;
}

function SavingsChart({ data }) {
  if (!data.some(d => d.income || d.expense)) return html`<${Empty} title=${t("dashboard.trend.empty")} />`;
  const config = {
    type: "bar",
    data: {
      labels: data.map(d => monthShort(d.month)),
      datasets: [
        // order 가 작을수록 위에 그려진다 → 저축률 선을 막대 위에
        { label: t("dashboard.series.savings"), data: data.map(d => d.savings), backgroundColor: data.map(d => d.savings >= 0 ? "#19a979" : "#d64545"), yAxisID: "y", order: 2 },
        { label: t("dashboard.series.savings_rate"), data: data.map(d => d.savings_rate), type: "line", borderColor: "#7c3aed", backgroundColor: "#fff",
          pointBorderColor: "#7c3aed", pointBorderWidth: 2, pointRadius: 4, borderWidth: 2.5, yAxisID: "y1", order: 1,
          fmt: (v) => pct(v), spanGaps: true },
      ],
    },
    options: {
      scales: { y: wonAxis, y1: { position: "right", grid: { display: false }, ticks: { callback: (v) => v + "%" } }, x: { grid: { display: false } } },
      plugins: { legend: { labels: { generateLabels: () => [
        { text: t("dashboard.series.savings"), fillStyle: "#19a979", strokeStyle: "#19a979", datasetIndex: 0 },
        { text: t("dashboard.series.savings_rate"), fillStyle: "#7c3aed", strokeStyle: "#7c3aed", datasetIndex: 1 },
      ] } } },
    },
  };
  return html`<${ChartView} config=${config} />`;
}

function ShareChart({ data, onPick }) {
  const top = data.slice(0, 9);
  const rest = data.slice(9).reduce((a, d) => a + d.total, 0);
  const labels = [...top.map(d => d.category_full_name), ...(rest ? [t("dashboard.share.other")] : [])];
  const values = [...top.map(d => d.total), ...(rest ? [rest] : [])];
  const colors = top.map((d, i) => d.color || PALETTE[i % PALETTE.length]);
  if (rest) colors.push("#c3c8d1");
  const config = {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 1 }] },
    options: {
      cutout: "58%",
      plugins: {
        legend: { position: "right", labels: { generateLabels: (ch) => labels.map((l, i) => ({ text: `${l}  ${won(values[i])} (${data[i]?.share ?? ""}%)`, fillStyle: colors[i], strokeStyle: colors[i], index: i })) } },
        tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${won(ctx.parsed)}` } },
      },
      onClick: (_e, els) => { if (els.length && els[0].index < top.length) onPick(top[els[0].index].category_id); },
    },
  };
  return html`<${ChartView} config=${config} />`;
}

function PlanChart({ data, onPick }) {
  const items = data.items.filter(i => i.plan || i.actual);
  const config = {
    type: "bar",
    data: {
      labels: items.map(i => i.category_full_name),
      datasets: [
        { label: t("dashboard.series.pva_plan"), data: items.map(i => i.plan), backgroundColor: "#c3cde6" },
        { label: t("dashboard.series.pva_actual"), data: items.map(i => i.actual), backgroundColor: items.map(i => i.status === "over" ? "#d64545" : "#2459d6") },
      ],
    },
    options: { indexAxis: "y", scales: { x: wonAxis, y: { grid: { display: false } } }, onClick: (_e, els) => els.length && onPick(),
      plugins: { tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${won(ctx.parsed.x)}` } } } },
  };
  return html`<${ChartView} config=${config} height=${Math.max(200, items.length * 30 + 60)} />`;
}

function AnnualSummary({ d }) {
  const months = d.months.filter(m => m.income || m.expense);
  return html`<div>
    <dl class="kv" style="margin:0 0 10px">
      <dt>${t("dashboard.annual.income")}</dt><dd><b>${won(d.income)}</b></dd>
      <dt>${t("dashboard.annual.expense")}</dt><dd><b>${won(d.expense)}</b></dd>
      <dt>${t("dashboard.annual.savings")}</dt><dd class=${cls(d.savings)}><b>${won(d.savings)}</b> (${pct(d.savings_rate)})</dd>
      <dt>${t("dashboard.annual.avg_expense")}</dt><dd>${months.length ? won(d.expense / months.length) : "–"} <span class="muted small">${t("dashboard.annual.months_with_records", { n: months.length })}</span></dd>
    </dl>
    ${d.top_expenses.length > 0 && html`<table class="t">
      <thead><tr><th>${t("dashboard.annual.top")}</th><th class="num">${t("dashboard.annual.amount")}</th><th class="num">${t("dashboard.annual.share")}</th></tr></thead>
      <tbody>${d.top_expenses.slice(0, 6).map(c => html`<tr><td><span class="dot" style=${c.color ? `background:${c.color}` : ""}></span>${c.category_full_name}</td>
        <td class="num">${won(c.total)}</td><td class="num">${pct(c.share)}</td></tr>`)}</tbody></table>`}
    ${d.income === 0 && d.expense === 0 && html`<${Empty} title=${t("dashboard.annual.empty")} />`}
  </div>`;
}
