import {
  html, useApi, won, pct, cls, monthLabel, thisMonth, addMonths, MonthPicker, Segmented, ChartView, wonAxis,
  PALETTE, Empty, ErrorBox, navigate, setParams, monthShort, yearLabel,
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
      <h1>대시보드</h1>
      <${MonthPicker} value=${month} onChange=${(m) => setParams({ month: m })} />
    </div>
    ${summary.error && html`<${ErrorBox} error=${summary.error} onRetry=${summary.reload} />`}

    <div class="cards">
      <div class="card clickable" onClick=${() => goCash()}>
        <div class="label">${monthLabel(month)} 수입</div>
        <div class="value">${s ? won(s.income) : "–"}</div>
        <div class="sub">${s ? `전월 ${won(s.prev_income)}` : ""}</div></div>
      <div class="card clickable" title="저축 항목을 뺀 지출" onClick=${() => goCash()}>
        <div class="label">생활비 지출</div>
        <div class="value">${s ? won(s.living_expense) : "–"}</div>
        <div class="sub">${s ? `전월 ${won(s.prev_living_expense)}` : ""}</div></div>
      <div class="card" title="저축 항목(설정 > 항목에서 지정)에 넣은 돈의 합계. 저축률 = 저축액 ÷ 수입">
        <div class="label">저축액</div>
        <div class="value ${s ? cls(s.savings) : ""}">${s ? won(s.savings) : "–"}</div>
        <div class="sub">${!s ? "" : s.savings_category_count === 0 ? "설정 > 항목에서 저축 항목을 지정하세요"
          : `저축률 ${pct(s.savings_rate)} · 전월 ${won(s.prev_savings)}`}</div></div>
    </div>
    ${s && s.pending_income.count > 0 && html`<div class="notice warn">이 달 소득 중 아직 입금일이 없는(미입금) 기록이 ${s.pending_income.count}건, ${won(s.pending_income.total)} 있습니다. 돈이 들어오면 월 예산에서 입금일을 입력하세요.</div>`}

    <div class="panel">
      <div class="panel-head"><h2>월별 수입·지출 추이</h2><span class="hint">막대를 클릭하면 해당 월로 이동</span>
        <div class="spacer"></div>
        <${Segmented} value=${period} onChange=${(p) => setParams({ period: p })} options=${[["6", "최근 6개월"], ["12", "최근 12개월"], ["year", yearLabel(year)]]} /></div>
      <div class="panel-body">${trend.data ? html`<${TrendChart} data=${trend.data} />` : trend.error ? html`<${ErrorBox} error=${trend.error} />` : ""}</div>
    </div>

    <div class="grid c2">
      <div class="panel">
        <div class="panel-head"><h2>저축액 · 저축률</h2><span class="hint">저축액 = 저축 항목에 넣은 돈, 저축률 = 저축액 ÷ 수입</span></div>
        <div class="panel-body">${trend.data && html`<${SavingsChart} data=${trend.data} />`}</div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>${monthLabel(month)} 항목별 지출 비중</h2><span class="hint">조각을 클릭하면 해당 항목 기록으로 이동</span></div>
        <div class="panel-body">${breakdown.data && (breakdown.data.length === 0
          ? html`<${Empty} title="이 달의 실제 지출 기록이 없습니다" />`
          : html`<${ShareChart} data=${breakdown.data} onPick=${() => goCash()} />`)}</div>
      </div>
    </div>

    <div class="grid c2">
      <div class="panel">
        <div class="panel-head"><h2>항목별 계획 대비 실제</h2><span class="hint">항목 클릭 → 계획 대비 실제 표</span></div>
        <div class="panel-body">${pva.data && (pva.data.items.length === 0
          ? html`<${Empty} title="이 달의 지출 계획이 없습니다">월 예산 화면의 지출 표에서 항목별 계획을 입력하세요.<//>`
          : html`<${PlanChart} data=${pva.data} onPick=${() => goCash()} />`)}</div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>${yearLabel(year)} 연간 요약</h2></div>
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
        { label: "수입", data: data.map(d => d.income), backgroundColor: "#2459d6", order: 2 },
        { label: "실제 지출", data: data.map(d => d.expense), backgroundColor: "#e8743b", order: 2 },
        { label: "지출 계획", data: data.map(d => d.plan || null), type: "line", borderColor: "#9aa3b2", borderDash: [4, 3], pointRadius: 2, backgroundColor: "#9aa3b2", order: 1 },
      ],
    },
    options: {
      scales: { y: wonAxis, x: { grid: { display: false } } },
      onClick: (_e, els) => { if (els.length) navigate("cashflow", { month: data[els[0].index].month }); },
      plugins: { tooltip: { callbacks: { title: (items) => monthLabel(data[items[0].dataIndex].month) } } },
    },
  };
  const hasAny = data.some(d => d.income || d.expense || d.plan);
  return hasAny ? html`<${ChartView} config=${config} className="chart-box tall" />` : html`<${Empty} title="이 기간의 기록이 없습니다">월별 수입·지출 페이지에서 기록을 추가하면 추이가 표시됩니다.<//>`;
}

function SavingsChart({ data }) {
  if (!data.some(d => d.income || d.expense)) return html`<${Empty} title="이 기간의 기록이 없습니다" />`;
  const config = {
    type: "bar",
    data: {
      labels: data.map(d => monthShort(d.month)),
      datasets: [
        // order 가 작을수록 위에 그려진다 → 저축률 선을 막대 위에
        { label: "저축액", data: data.map(d => d.savings), backgroundColor: data.map(d => d.savings >= 0 ? "#19a979" : "#d64545"), yAxisID: "y", order: 2 },
        { label: "저축률", data: data.map(d => d.savings_rate), type: "line", borderColor: "#7c3aed", backgroundColor: "#fff",
          pointBorderColor: "#7c3aed", pointBorderWidth: 2, pointRadius: 4, borderWidth: 2.5, yAxisID: "y1", order: 1,
          fmt: (v) => pct(v), spanGaps: true },
      ],
    },
    options: {
      scales: { y: wonAxis, y1: { position: "right", grid: { display: false }, ticks: { callback: (v) => v + "%" } }, x: { grid: { display: false } } },
      plugins: { legend: { labels: { generateLabels: () => [
        { text: "저축액", fillStyle: "#19a979", strokeStyle: "#19a979", datasetIndex: 0 },
        { text: "저축률", fillStyle: "#7c3aed", strokeStyle: "#7c3aed", datasetIndex: 1 },
      ] } } },
    },
  };
  return html`<${ChartView} config=${config} />`;
}

function ShareChart({ data, onPick }) {
  const top = data.slice(0, 9);
  const rest = data.slice(9).reduce((a, d) => a + d.total, 0);
  const labels = [...top.map(d => d.category_full_name), ...(rest ? ["기타 항목"] : [])];
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
        { label: "계획", data: items.map(i => i.plan), backgroundColor: "#c3cde6" },
        { label: "실제", data: items.map(i => i.actual), backgroundColor: items.map(i => i.status === "over" ? "#d64545" : "#2459d6") },
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
      <dt>연간 수입</dt><dd><b>${won(d.income)}</b></dd>
      <dt>연간 생활비 지출</dt><dd><b>${won(d.living_expense)}</b></dd>
      <dt>연간 저축액</dt><dd class=${cls(d.savings)}><b>${won(d.savings)}</b> (${pct(d.savings_rate)})</dd>
      <dt>월평균 생활비 지출</dt><dd>${months.length ? won(d.living_expense / months.length) : "–"} <span class="muted small">(기록 있는 ${months.length}개월)</span></dd>
    </dl>
    ${d.top_expenses.length > 0 && html`<table class="t">
      <thead><tr><th>지출 상위 항목</th><th class="num">금액</th><th class="num">비중</th></tr></thead>
      <tbody>${d.top_expenses.slice(0, 6).map(c => html`<tr><td><span class="dot" style=${c.color ? `background:${c.color}` : ""}></span>${c.category_full_name}</td>
        <td class="num">${won(c.total)}</td><td class="num">${pct(c.share)}</td></tr>`)}</tbody></table>`}
    ${d.income === 0 && d.expense === 0 && html`<${Empty} title="올해 기록이 없습니다" />`}
  </div>`;
}
