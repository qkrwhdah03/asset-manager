import {
  html, useState, useApi, api, won, pct, qty, cls, today, monthLabel, MoneyInput, parseMoney, fmtMoneyInput,
  Modal, Empty, Loading, ErrorBox, toast, toastErr, setParams, ChartView, wonAxis, PALETTE, exportFile, confirmBox,
} from "../lib.js";

const TABS = [["overview", "현황"], ["txns", "변동 기록"], ["holdings", "보유 종목·시세"], ["stats", "자산 통계"], ["accounts", "계좌·유형 관리"]];
const KIND_HELP = {
  deposit: "외부에서 들어온 돈(급여 입금, 초기 잔액 등). 순투입원금 증가",
  withdrawal: "외부로 나간 돈(생활비 사용 등). 순투입원금 감소",
  transfer: "내 계좌 간 이동. 총자산·수익에 영향 없음",
  buy: "현금 감소 + 종목 보유액 증가 (수수료는 취득원가에 포함)",
  sell: "종목 감소 + 현금 유입, 평균단가 기준 실현손익 계산",
  dividend: "배당금 현금 유입 (투자 수익)",
  interest: "이자 현금 유입 (투자 수익)",
  fee: "별도 수수료·세금 (투자 비용)",
  valuation: "시세·평가액 변동(부동산, 펀드 등 잔액형 자산). 현금 이동 없음. 음수 가능",
  adjustment: "기타 조정(초기 잔액·오차 정정). 순투입원금으로 처리. 음수 가능",
};

export function AssetsPage({ params }) {
  const tab = params.tab || "overview";
  const [version, setVersion] = useState(0);
  const bump = () => setVersion(v => v + 1);
  const meta = useApi("/asset-meta");
  const accounts = useApi("/accounts", null, [version]);
  const types = useApi("/asset-types", null, [version]);
  const securities = useApi("/securities", null, [version]);
  const summary = useApi("/assets/summary", {}, [version]);
  const [txnModal, setTxnModal] = useState(null);

  const ctx = { accounts: accounts.data || [], types: types.data || [], securities: securities.data || [],
                kinds: meta.data?.txn_kinds || {}, version, bump, openTxn: (t) => setTxnModal(t || {}) };

  return html`<div class="page">
    <div class="page-head">
      <h1>자산 관리</h1>
      <div class="spacer"></div>
      <button class="btn primary" onClick=${() => setTxnModal({})} disabled=${!ctx.accounts.length}>+ 자산 변동 기록</button>
    </div>
    <div class="tabs">${TABS.map(([k, l]) => html`<button class=${tab === k ? "on" : ""} onClick=${() => setParams({ tab: k })}>${l}</button>`)}</div>
    ${accounts.data && accounts.data.length === 0 && tab !== "accounts" && html`<div class="notice">
      먼저 <a href="#/assets?tab=accounts">계좌·유형 관리</a>에서 현금, 은행 계좌, 증권 계좌 등을 추가하세요.
      기존 잔액은 '입금'(또는 '기타 조정')으로, 보유 주식은 입금 후 '매수'로 입력하면 됩니다.</div>`}
    ${tab === "overview" && html`<${Overview} summary=${summary} ctx=${ctx} />`}
    ${tab === "txns" && html`<${TxnList} ctx=${ctx} params=${params} />`}
    ${tab === "holdings" && html`<${Holdings} summary=${summary} ctx=${ctx} />`}
    ${tab === "stats" && html`<${AssetStats} summary=${summary} ctx=${ctx} />`}
    ${tab === "accounts" && html`<${AccountsAdmin} ctx=${ctx} />`}
    ${txnModal && html`<${TxnModal} ctx=${ctx} initial=${txnModal} onClose=${() => setTxnModal(null)} onSaved=${() => { setTxnModal(null); bump(); }} />`}
  </div>`;
}

function Overview({ summary, ctx }) {
  if (summary.loading && !summary.data) return html`<${Loading} />`;
  if (summary.error) return html`<${ErrorBox} error=${summary.error} onRetry=${summary.reload} />`;
  const s = summary.data;
  const liq = s.by_liquidity;
  return html`<div>
    <div class="cards">
      <div class="card"><div class="label">총자산</div><div class="value">${won(s.total)}</div><div class="sub">기준일 ${s.as_of}</div></div>
      <div class="card" title="입금 − 출금 + 기타 조정 (계좌 간 이체 제외)"><div class="label">순투입원금</div><div class="value">${won(s.external)}</div>
        <div class="sub">외부에서 넣은 돈의 순합계</div></div>
      <div class="card" title="총자산 − 순투입원금 = 실현 + 평가 + 배당 + 이자 − 수수료 + 평가액 변동"><div class="label">누적 투자 손익</div>
        <div class="value ${cls(s.profit)}">${won(s.profit, { sign: true })}</div><div class="sub">수익률 ${pct(s.return_pct, true)} (순투입 대비)</div></div>
      <div class="card"><div class="label">전월 말 대비 자산 증감</div><div class="value ${cls(s.change_vs_prev_month)}">${won(s.change_vs_prev_month, { sign: true })}</div>
        <div class="sub">순유입 ${won(s.change_flow, { sign: true })} · 투자손익 <span class=${cls(s.change_profit)}>${won(s.change_profit, { sign: true })}</span></div></div>
      <div class="card"><div class="label">현금성 / 투자 / 기타</div>
        <div class="value" style="font-size:15px">${s.total ? `${pct(liq.cash / s.total * 100)} / ${pct(liq.investment / s.total * 100)} / ${pct(liq.other / s.total * 100)}` : "–"}</div>
        <div class="sub">${won(liq.cash)} / ${won(liq.investment)} / ${won(liq.other)}</div></div>
    </div>
    <div class="notice">자산 증감(총자산 변화)과 투자 수익은 다릅니다. <b>자산 증감 = 순유입(저축·인출) + 투자 손익</b>. 계좌 간 이체는 어느 쪽에도 포함되지 않습니다.</div>
    ${s.missing_price && html`<div class="notice warn">시세가 없는 보유 종목이 있어 취득원가로 평가했습니다. '보유 종목·시세' 탭에서 현재가를 입력하세요.</div>`}
    <div class="grid c32">
      <div class="panel">
        <div class="panel-head"><h2>계좌별 잔액</h2><span class="hint">행 클릭 → 해당 계좌 변동 기록</span></div>
        <div class="panel-body flush table-wrap">
          ${s.accounts.length === 0 ? html`<${Empty} title="등록된 계좌가 없습니다" />` : html`<table class="t">
          <thead><tr><th>계좌</th><th>유형</th><th class="num">현금</th><th class="num">종목 평가액</th><th class="num">평가액</th>
            <th class="num">순투입</th><th class="num">손익</th><th class="num">수익률</th></tr></thead>
          <tbody>${s.accounts.filter(a => a.is_active || a.value).map(a => html`<tr style="cursor:pointer" onClick=${() => setParams({ tab: "txns", account: a.account_id })}
              class=${a.is_active ? "" : "inactive"}>
            <td style="min-width:150px"><b>${a.name}</b> ${a.input_mode !== "manual" && html`<span class="tag">${a.input_mode === "api" ? "API" : "CSV"}</span>`}
              ${a.institution && html`<div class="muted small">${a.institution}</div>`}</td>
            <td class="small nowrap">${a.type_name}</td>
            <td class="num">${won(a.cash + a.valuation_adj)}</td>
            <td class="num">${a.holdings_value ? won(a.holdings_value) : html`<span class="muted">–</span>`}</td>
            <td class="num"><b>${won(a.value)}</b></td>
            <td class="num">${won(a.contrib)}</td>
            <td class="num ${cls(a.profit)}">${won(a.profit, { sign: true })}</td>
            <td class="num ${cls(a.return_pct)}">${pct(a.return_pct, true)}</td></tr>`)}</tbody>
          <tfoot><tr><td colspan="4">합계</td><td class="num">${won(s.total)}</td><td></td><td class="num ${cls(s.profit)}">${won(s.profit, { sign: true })}</td><td></td></tr></tfoot>
          </table>`}
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>자산 유형별 비중</h2></div>
        <div class="panel-body">${s.total > 0 ? html`<${ChartView} config=${{
          type: "doughnut",
          data: { labels: s.by_type.map(t => t.type_name), datasets: [{ data: s.by_type.map(t => t.value), backgroundColor: PALETTE }] },
          options: { cutout: "58%", plugins: { legend: { position: "right", labels: { generateLabels: () => s.by_type.map((t, i) => ({ text: `${t.type_name}  ${pct(t.share)}`, fillStyle: PALETTE[i % PALETTE.length], strokeStyle: PALETTE[i % PALETTE.length], index: i })) } },
            tooltip: { callbacks: { label: (c) => ` ${c.label}: ${won(c.parsed)}` } } } },
        }} />` : html`<${Empty} title="평가할 자산이 없습니다" />`}
        <dl class="kv" style="margin-top:12px">
          <dt>실현손익</dt><dd class=${cls(s.realized)}>${won(s.realized, { sign: true })}</dd>
          <dt>평가손익</dt><dd class=${cls(s.unrealized)}>${won(s.unrealized, { sign: true })}</dd>
          <dt>배당 + 이자</dt><dd>${won(s.dividends + s.interest)}</dd>
          <dt>수수료·세금</dt><dd class="neg">${won(-s.fees)}</dd>
          <dt>평가액 변동(잔액형)</dt><dd class=${cls(s.valuation_adj)}>${won(s.valuation_adj, { sign: true })}</dd>
        </dl></div>
      </div>
    </div>
  </div>`;
}

function TxnList({ ctx, params }) {
  const accountId = params.account ? Number(params.account) : null;
  const kind = params.kind || "";
  const list = useApi("/asset-txns", { account_id: accountId, kind }, [ctx.version]);
  async function del(t) {
    if (!await confirmBox(`${t.date} ${t.kind_label} 기록을 삭제할까요?`)) return;
    try { await api(`/asset-txns/${t.id}`, { method: "DELETE" }); ctx.bump(); } catch (e) { toastErr(e); }
  }
  const rows = list.data || [];
  return html`<div class="panel">
    <div class="panel-head"><h2>자산 변동 기록</h2><span class="hint">${rows.length}건</span><div class="spacer"></div>
      <select value=${accountId || ""} onChange=${(e) => setParams({ account: e.target.value })}>
        <option value="">전체 계좌</option>${ctx.accounts.map(a => html`<option value=${a.id}>${a.name}</option>`)}</select>
      <select value=${kind} onChange=${(e) => setParams({ kind: e.target.value })}>
        <option value="">전체 유형</option>${Object.entries(ctx.kinds).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select>
      <button class="btn" onClick=${() => exportFile("/export/asset-txns", { account_id: accountId })}>CSV 내보내기</button>
    </div>
    <div class="panel-body flush table-wrap" style="max-height:640px">
      ${list.error && html`<${ErrorBox} error=${list.error} />`}
      ${rows.length === 0 && !list.loading ? html`<${Empty} title="변동 기록이 없습니다">우측 상단 '+ 자산 변동 기록'으로 입금·매수 등을 기록하세요.<//>` : html`
      <table class="t">
        <thead><tr><th>날짜</th><th>유형</th><th>계좌</th><th>종목/상대계좌</th><th class="num">수량</th><th class="num">단가</th>
          <th class="num">금액</th><th class="num">수수료</th><th>메모</th><th></th></tr></thead>
        <tbody>${rows.map(t => {
          const outflow = ["withdrawal", "buy", "fee"].includes(t.kind) || (t.kind === "transfer" && t.account_id === accountId) || (["valuation", "adjustment"].includes(t.kind) && t.amount < 0);
          return html`<tr key=${t.id} onDblClick=${() => ctx.openTxn(t)}>
          <td class="nowrap">${t.date}</td>
          <td><span class="tag ${["dividend", "interest"].includes(t.kind) ? "green" : t.kind === "transfer" ? "blue" : ["valuation"].includes(t.kind) ? "amber" : ""}">${t.kind_label}</span></td>
          <td>${t.account_name}</td>
          <td>${t.kind === "transfer" ? html`→ ${t.to_account_name}` : t.security_name ? html`${t.security_name} <span class="muted small">${t.symbol}</span>` : ""}</td>
          <td class="num">${t.quantity ? qty(t.quantity) : ""}</td>
          <td class="num">${t.price ? won(t.price, { unit: false }) : ""}</td>
          <td class="num ${outflow ? "neg" : ""}">${won(t.amount)}</td>
          <td class="num">${t.fee ? won(t.fee) : ""}</td>
          <td class="muted">${t.memo}</td>
          <td class="actions"><button class="btn sm" onClick=${() => ctx.openTxn(t)}>수정</button>
            <button class="btn sm danger" onClick=${() => del(t)}>삭제</button></td></tr>`; })}</tbody>
      </table>`}
    </div></div>`;
}

function TxnModal({ ctx, initial, onClose, onSaved }) {
  const isEdit = !!initial.id;
  const [f, setF] = useState({
    kind: initial.kind || "deposit", date: initial.date || today(), account_id: initial.account_id || ctx.accounts.find(a => a.is_active)?.id || "",
    to_account_id: initial.to_account_id || "", security_id: initial.security_id || "", quantity: initial.quantity || "",
    price: initial.price || "", amount: initial.amount !== undefined && !["buy", "sell"].includes(initial.kind) ? fmtMoneyInput(String(initial.amount)) : "",
    fee: initial.fee ? fmtMoneyInput(String(initial.fee)) : "", memo: initial.memo || "",
  });
  const [newSec, setNewSec] = useState(null);
  const [saving, setSaving] = useState(false);
  const upd = (k) => (v) => setF({ ...f, [k]: v });
  const trade = ["buy", "sell"].includes(f.kind);
  const gross = trade && f.quantity && f.price ? Math.round(Number(f.quantity) * Number(String(f.price).replace(/,/g, ""))) : null;

  async function save() {
    setSaving(true);
    try {
      let security_id = f.security_id;
      if (newSec && (f.kind === "buy" || f.kind === "dividend")) {
        const s = await api("/securities", { method: "POST", body: newSec });
        security_id = s.id;
      }
      const body = { ...f, security_id: security_id || null, to_account_id: f.to_account_id || null,
                     amount: parseMoney(f.amount), fee: parseMoney(f.fee) || 0, price: String(f.price).replace(/,/g, "") };
      if (isEdit) await api(`/asset-txns/${initial.id}`, { method: "PUT", body });
      else await api("/asset-txns", { method: "POST", body });
      toast(isEdit ? "수정했습니다." : "기록했습니다.", "ok");
      onSaved();
    } catch (e) { toastErr(e); } finally { setSaving(false); }
  }
  const active = ctx.accounts.filter(a => a.is_active || a.id === f.account_id || a.id === f.to_account_id);
  return html`<${Modal} title=${isEdit ? "자산 변동 수정" : "자산 변동 기록"} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button><button class="btn primary" onClick=${save} disabled=${saving}>저장</button>`}>
    <div class="form-grid">
      <label>유형</label>
      <select value=${f.kind} onChange=${(e) => upd("kind")(e.target.value)}>${Object.entries(ctx.kinds).map(([k, l]) => html`<option value=${k}>${l}</option>`)}</select>
      <div class="field-help">${KIND_HELP[f.kind]}</div>
      <label>날짜</label><input type="date" value=${f.date} onInput=${(e) => upd("date")(e.target.value)} />
      <label>${f.kind === "transfer" ? "보내는 계좌" : "계좌"}</label>
      <select value=${f.account_id} onChange=${(e) => upd("account_id")(Number(e.target.value))}>${active.map(a => html`<option value=${a.id}>${a.name} (${a.type_name})</option>`)}</select>
      ${f.kind === "transfer" && html`<label>받는 계좌</label>
        <select value=${f.to_account_id} onChange=${(e) => upd("to_account_id")(Number(e.target.value))}>
          <option value="">선택</option>${active.filter(a => a.id !== f.account_id).map(a => html`<option value=${a.id}>${a.name}</option>`)}</select>`}
      ${(trade || f.kind === "dividend") && html`<label>종목</label>
        <div class="row">
          ${newSec ? html`<input type="text" placeholder="종목코드" style="width:110px" value=${newSec.symbol} onInput=${(e) => setNewSec({ ...newSec, symbol: e.target.value })} />
              <input type="text" placeholder="종목명" style="flex:1" value=${newSec.name} onInput=${(e) => setNewSec({ ...newSec, name: e.target.value })} />
              <select value=${newSec.kind} onChange=${(e) => setNewSec({ ...newSec, kind: e.target.value })}><option value="stock">주식</option><option value="etf">ETF</option><option value="fund">펀드</option><option value="other">기타</option></select>
              <button class="btn sm" onClick=${() => setNewSec(null)}>취소</button>`
            : html`<select style="flex:1" value=${f.security_id} onChange=${(e) => upd("security_id")(e.target.value ? Number(e.target.value) : "")}>
                <option value="">${f.kind === "dividend" ? "(선택 사항)" : "종목 선택"}</option>
                ${ctx.securities.map(s => html`<option value=${s.id}>${s.name} (${s.symbol})</option>`)}</select>
              ${f.kind !== "sell" && html`<button class="btn sm" onClick=${() => setNewSec({ symbol: "", name: "", kind: "stock" })}>새 종목</button>`}`}
        </div>`}
      ${trade ? html`
        <label>수량</label><input type="text" inputmode="decimal" class="amount" value=${f.quantity} onInput=${(e) => upd("quantity")(e.target.value)} placeholder="소수점 가능" />
        <label>단가(원)</label><input type="text" inputmode="decimal" class="amount" value=${f.price} onInput=${(e) => upd("price")(e.target.value)} />
        <label>수수료·세금</label><${MoneyInput} value=${f.fee} onInput=${upd("fee")} />
        <label>거래 금액</label><div class="num" style="text-align:left">${gross !== null ? html`${won(gross)} <span class="muted small">
          (${f.kind === "buy" ? `현금 −${won(gross + Number(parseMoney(f.fee) || 0))}` : `현금 +${won(gross - Number(parseMoney(f.fee) || 0))}`})</span>` : "–"}</div>`
      : html`
        <label>금액(원)</label><${MoneyInput} value=${f.amount} onInput=${upd("amount")} placeholder=${["valuation", "adjustment"].includes(f.kind) ? "음수 가능 (예: -100,000)" : "0"} />
        ${f.kind === "transfer" && html`<label>이체 수수료</label><${MoneyInput} value=${f.fee} onInput=${upd("fee")} />`}`}
      <label>메모</label><input type="text" value=${f.memo} onInput=${(e) => upd("memo")(e.target.value)} />
    </div>
  <//>`;
}

function Holdings({ summary, ctx }) {
  const [priceFor, setPriceFor] = useState(null);
  if (!summary.data) return summary.error ? html`<${ErrorBox} error=${summary.error} />` : html`<${Loading} />`;
  const s = summary.data;
  return html`<div>
    <div class="panel">
      <div class="panel-head"><h2>보유 종목</h2><span class="hint">평가액 = 보유 수량 × 기준일 이전 최신 시세(없으면 최근 거래 단가)</span></div>
      <div class="panel-body flush table-wrap">
        ${s.holdings.length === 0 ? html`<${Empty} title="보유 종목이 없습니다">증권 계좌에 입금한 뒤 '매수'를 기록하세요.<//>` : html`<table class="t">
        <thead><tr><th>종목</th><th>계좌</th><th class="num">수량</th><th class="num">평균단가</th><th class="num">취득원가</th>
          <th class="num">현재가</th><th>시세 기준일</th><th class="num">평가액</th><th class="num">평가손익</th><th class="num">수익률</th><th class="num">실현손익</th><th></th></tr></thead>
        <tbody>${s.holdings.map(h => html`<tr>
          <td><b>${h.security_name}</b> <span class="muted small">${h.symbol}</span></td><td class="small">${h.account_name}</td>
          <td class="num">${qty(h.quantity)}</td><td class="num">${won(h.avg_cost, { unit: false })}</td><td class="num">${won(h.cost)}</td>
          <td class="num">${h.price ? won(h.price, { unit: false }) : html`<span class="tag amber">없음</span>`}</td>
          <td class="small nowrap">${h.price_date || "–"} ${h.price_source === "trade" && html`<span class="tag" title="등록된 시세가 없어 거래 단가 사용">거래가</span>`}</td>
          <td class="num"><b>${won(h.value)}</b></td>
          <td class="num ${cls(h.unrealized)}">${won(h.unrealized, { sign: true })}</td>
          <td class="num ${cls(h.unrealized_pct)}">${pct(h.unrealized_pct, true)}</td>
          <td class="num ${cls(h.realized)}">${h.realized ? won(h.realized, { sign: true }) : "–"}</td>
          <td class="actions"><button class="btn sm" onClick=${() => setPriceFor(ctx.securities.find(x => x.id === h.security_id))}>시세 입력</button></td>
        </tr>`)}</tbody></table>`}
      </div>
    </div>
    ${s.closed_positions.length > 0 && html`<div class="panel"><div class="panel-head"><h2>청산된 종목</h2></div><div class="panel-body flush"><table class="t">
      <thead><tr><th>종목</th><th>계좌</th><th class="num">실현손익</th><th class="num">배당</th></tr></thead>
      <tbody>${s.closed_positions.map(h => html`<tr><td>${h.security_name} <span class="muted small">${h.symbol}</span></td><td>${h.account_name}</td>
        <td class="num ${cls(h.realized)}">${won(h.realized, { sign: true })}</td><td class="num">${won(h.dividends)}</td></tr>`)}</tbody></table></div></div>`}
    <div class="panel">
      <div class="panel-head"><h2>등록 종목</h2><span class="hint">시세는 수동 입력 또는 CSV(설정 → 데이터 가져오기)로 갱신</span></div>
      <div class="panel-body flush"><table class="t">
        <thead><tr><th>종목코드</th><th>종목명</th><th>구분</th><th class="num">최근 시세</th><th>기준일</th><th class="num">거래 수</th><th></th></tr></thead>
        <tbody>${ctx.securities.map(x => html`<tr><td><code>${x.symbol}</code></td><td>${x.name}</td><td class="small">${{ stock: "주식", etf: "ETF", fund: "펀드", other: "기타" }[x.kind]}</td>
          <td class="num">${x.last_price ? won(x.last_price, { unit: false }) : "–"}</td><td class="small">${x.last_price_date || "–"}</td><td class="num">${x.txn_count}</td>
          <td class="actions"><button class="btn sm" onClick=${() => setPriceFor(x)}>시세</button>
            ${x.txn_count === 0 && html`<button class="btn sm danger" onClick=${async () => { try { await api(`/securities/${x.id}`, { method: "DELETE" }); ctx.bump(); } catch (e) { toastErr(e); } }}>삭제</button>`}</td></tr>`)}
          ${ctx.securities.length === 0 && html`<tr><td colspan="7"><${Empty} title="등록된 종목이 없습니다">매수 기록 시 '새 종목'으로 추가할 수 있습니다.<//></td></tr>`}</tbody>
      </table></div>
    </div>
    ${priceFor && html`<${PriceModal} sec=${priceFor} onClose=${() => { setPriceFor(null); ctx.bump(); }} />`}
  </div>`;
}

function PriceModal({ sec, onClose }) {
  const prices = useApi(`/securities/${sec.id}/prices`);
  const [d, setD] = useState(today());
  const [p, setP] = useState("");
  async function add() {
    try { await api(`/securities/${sec.id}/prices`, { method: "POST", body: { date: d, price: p.replace(/,/g, "") } }); setP(""); prices.reload(); toast("시세를 저장했습니다.", "ok"); }
    catch (e) { toastErr(e); }
  }
  async function del(date) { try { await api(`/securities/${sec.id}/prices`, { method: "DELETE", params: { date } }); prices.reload(); } catch (e) { toastErr(e); } }
  return html`<${Modal} title=${`${sec.name} (${sec.symbol}) 시세`} onClose=${onClose} footer=${html`<button class="btn" onClick=${onClose}>닫기</button>`}>
    <div class="notice">자동 시세 연동은 아직 제공하지 않습니다(공식 무료 API 미확보). 증권사 앱에서 확인한 종가를 입력하세요.</div>
    <div class="row" style="margin-bottom:10px"><input type="date" value=${d} onInput=${(e) => setD(e.target.value)} />
      <input type="text" class="amount" placeholder="가격(원)" value=${p} onInput=${(e) => setP(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && add()} style="width:140px" />
      <button class="btn primary" onClick=${add}>저장</button></div>
    <div class="table-wrap" style="max-height:300px"><table class="t"><thead><tr><th>기준일</th><th class="num">가격</th><th>출처</th><th></th></tr></thead>
      <tbody>${(prices.data || []).map(x => html`<tr><td>${x.date}</td><td class="num">${won(x.price, { unit: false })}</td><td class="small">${x.source}</td>
        <td class="actions"><button class="btn sm danger" onClick=${() => del(x.date)}>삭제</button></td></tr>`)}</tbody></table>
      ${prices.data && prices.data.length === 0 && html`<${Empty} title="등록된 시세가 없습니다" />`}</div>
  <//>`;
}

function AssetStats({ summary, ctx }) {
  const hist = useApi("/assets/history", {}, [ctx.version]);
  if (hist.loading && !hist.data) return html`<${Loading} />`;
  if (hist.error) return html`<${ErrorBox} error=${hist.error} />`;
  const m = hist.data.months.slice(-24);
  if (!m.length || m.every(x => x.total === 0)) return html`<${Empty} title="자산 변동 기록이 없습니다" />`;
  const labels = m.map(x => x.month.slice(2).replace("-", "."));
  const accs = hist.data.accounts.filter(a => a.series.some(p => p.value));
  return html`<div>
    <div class="panel"><div class="panel-head"><h2>월별 총자산</h2><span class="hint">월말 기준 · 현금성/투자/기타 누적</span></div>
      <div class="panel-body"><${ChartView} className="chart-box tall" config=${{
        type: "bar",
        data: { labels, datasets: [
          { label: "현금성", data: m.map(x => x.by_liquidity.cash), backgroundColor: "#7aa2f7", stack: "s" },
          { label: "투자", data: m.map(x => x.by_liquidity.investment), backgroundColor: "#e8743b", stack: "s" },
          { label: "기타", data: m.map(x => x.by_liquidity.other), backgroundColor: "#b9bfca", stack: "s" },
          { label: "순투입원금", data: m.map(x => x.external), type: "line", borderColor: "#1d2330", borderDash: [4, 3], pointRadius: 0, backgroundColor: "#1d2330" },
        ] },
        options: { scales: { x: { stacked: true, grid: { display: false } }, y: { ...wonAxis, stacked: true } } },
      }} /></div></div>
    <div class="grid c2">
      <div class="panel"><div class="panel-head"><h2>월별 자산 증감 분해</h2><span class="hint">증감 = 순유입 + 투자 손익</span></div>
        <div class="panel-body"><${ChartView} config=${{
          type: "bar",
          data: { labels, datasets: [
            { label: "순유입(저축·인출)", data: m.map(x => x.flow), backgroundColor: "#7aa2f7", stack: "s" },
            { label: "투자 손익", data: m.map(x => x.profit), backgroundColor: m.map(x => x.profit >= 0 ? "#19a979" : "#d64545"), stack: "s" },
          ] },
          options: { scales: { x: { stacked: true, grid: { display: false } }, y: { ...wonAxis, stacked: true } } },
        }} /></div></div>
      <div class="panel"><div class="panel-head"><h2>계좌별 평가액 변화</h2></div>
        <div class="panel-body"><${ChartView} config=${{
          type: "line",
          data: { labels, datasets: accs.map((a, i) => ({ label: a.name, data: a.series.slice(-24).map(p => p.value), borderColor: PALETTE[i % PALETTE.length], backgroundColor: PALETTE[i % PALETTE.length], pointRadius: 1.5, tension: 0.15 })) },
          options: { scales: { y: wonAxis, x: { grid: { display: false } } } },
        }} /></div></div>
    </div>
    <div class="panel"><div class="panel-head"><h2>월별 자산 표</h2><span class="hint">월 수익률 = 투자손익 ÷ (기초자산 + 순유입/2) · 근사치</span></div>
      <div class="panel-body flush table-wrap"><table class="t">
        <thead><tr><th>월</th><th class="num">월말 총자산</th><th class="num">증감</th><th class="num">순유입</th><th class="num">투자 손익</th><th class="num">월 수익률</th><th class="num">누적 손익</th></tr></thead>
        <tbody>${[...m].reverse().map(x => html`<tr><td>${monthLabel(x.month)}</td><td class="num"><b>${won(x.total)}</b></td>
          <td class="num ${cls(x.change)}">${won(x.change, { sign: true })}</td><td class="num">${won(x.flow, { sign: true })}</td>
          <td class="num ${cls(x.profit)}">${won(x.profit, { sign: true })}</td><td class="num ${cls(x.return_pct)}">${pct(x.return_pct, true)}</td>
          <td class="num ${cls(x.cum_profit)}">${won(x.cum_profit, { sign: true })}</td></tr>`)}</tbody></table></div></div>
  </div>`;
}

function AccountsAdmin({ ctx }) {
  const [acc, setAcc] = useState(null);
  const [type, setType] = useState(null);
  async function delAcc(a) {
    if (!await confirmBox(`'${a.name}' 계좌를 삭제할까요? (기록이 있으면 비활성화됩니다)`)) return;
    try { const r = await api(`/accounts/${a.id}`, { method: "DELETE" }); toast(r.action === "deleted" ? "삭제했습니다." : `기록 ${r.txn_count}건이 있어 비활성화했습니다.`, "ok"); ctx.bump(); }
    catch (e) { toastErr(e); }
  }
  async function delType(t) {
    try { await api(`/asset-types/${t.id}`, { method: "DELETE" }); ctx.bump(); } catch (e) { toastErr(e); }
  }
  return html`<div class="grid c32">
    <div class="panel"><div class="panel-head"><h2>계좌 / 보유 수단</h2><div class="spacer"></div>
      <button class="btn primary sm" onClick=${() => setAcc({ type_id: ctx.types[0]?.id, input_mode: "manual", is_active: true })}>+ 계좌 추가</button></div>
      <div class="panel-body flush"><table class="t">
        <thead><tr><th>이름</th><th>유형</th><th>금융기관</th><th>입력 방식</th><th class="num">기록</th><th>상태</th><th></th></tr></thead>
        <tbody>${ctx.accounts.map(a => html`<tr class=${a.is_active ? "" : "inactive"}><td><b>${a.name}</b><div class="muted small">${a.memo}</div></td>
          <td>${a.type_name}</td><td>${a.institution}</td><td class="small">${{ manual: "수동", api: "API 연동", csv: "CSV 가져오기" }[a.input_mode]}</td>
          <td class="num">${a.txn_count}</td><td>${a.is_active ? html`<span class="tag green">사용</span>` : html`<span class="tag">비활성</span>`}</td>
          <td class="actions"><button class="btn sm" onClick=${() => setAcc(a)}>수정</button><button class="btn sm danger" onClick=${() => delAcc(a)}>삭제</button></td></tr>`)}
          ${ctx.accounts.length === 0 && html`<tr><td colspan="7"><${Empty} title="계좌가 없습니다">예: 현금(지갑), OO은행 생활비 통장, 카카오페이증권 계좌<//></td></tr>`}</tbody></table></div></div>
    <div class="panel"><div class="panel-head"><h2>자산 유형</h2><div class="spacer"></div>
      <button class="btn sm" onClick=${() => setType({ valuation: "balance", liquidity: "cash" })}>+ 유형 추가</button></div>
      <div class="panel-body flush"><table class="t">
        <thead><tr><th>유형</th><th>평가 방식</th><th>성격</th><th class="num">계좌</th><th></th></tr></thead>
        <tbody>${ctx.types.map(t => html`<tr><td>${t.name}</td><td class="small">${t.valuation === "holdings" ? "수량×가격" : "잔액"}</td>
          <td class="small">${{ cash: "현금성", investment: "투자", other: "기타" }[t.liquidity]}</td><td class="num">${t.account_count}</td>
          <td class="actions"><button class="btn sm" onClick=${() => setType(t)}>수정</button>
            ${t.account_count === 0 && html`<button class="btn sm danger" onClick=${() => delType(t)}>삭제</button>`}</td></tr>`)}</tbody></table></div></div>
    ${acc && html`<${AccountModal} ctx=${ctx} initial=${acc} onClose=${() => setAcc(null)} onSaved=${() => { setAcc(null); ctx.bump(); }} />`}
    ${type && html`<${TypeModal} initial=${type} onClose=${() => setType(null)} onSaved=${() => { setType(null); ctx.bump(); }} />`}
  </div>`;
}

function AccountModal({ ctx, initial, onClose, onSaved }) {
  const [f, setF] = useState({ name: "", institution: "", memo: "", ...initial });
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  async function save() {
    try { await api(initial.id ? `/accounts/${initial.id}` : "/accounts", { method: initial.id ? "PUT" : "POST", body: f }); onSaved(); }
    catch (e) { toastErr(e); }
  }
  return html`<${Modal} title=${initial.id ? "계좌 수정" : "계좌 추가"} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button><button class="btn primary" onClick=${save}>저장</button>`}>
    <div class="form-grid">
      <label>자산명</label><input type="text" value=${f.name} onInput=${upd("name")} placeholder="예: 카카오페이증권 위탁계좌" />
      <label>자산 유형</label><select value=${f.type_id} onChange=${upd("type_id")}>${ctx.types.map(t => html`<option value=${t.id}>${t.name}</option>`)}</select>
      <label>금융기관</label><input type="text" value=${f.institution} onInput=${upd("institution")} placeholder="예: 카카오페이증권" />
      <label>입력 방식</label><select value=${f.input_mode} onChange=${upd("input_mode")}>
        <option value="manual">수동 입력</option><option value="csv">CSV 가져오기</option><option value="api" disabled>API 연동 (미지원)</option></select>
      <div class="field-help">현재 공식 API 연동이 가능한 금융기관이 없어 수동/CSV만 지원합니다.</div>
      <label>메모</label><input type="text" value=${f.memo} onInput=${upd("memo")} />
      <label>사용</label><label><input type="checkbox" checked=${f.is_active} onChange=${upd("is_active")} /> 사용 중</label>
    </div><//>`;
}

function TypeModal({ initial, onClose, onSaved }) {
  const [f, setF] = useState({ name: "", ...initial });
  const upd = (k) => (e) => setF({ ...f, [k]: e.target.value });
  async function save() {
    try { await api(initial.id ? `/asset-types/${initial.id}` : "/asset-types", { method: initial.id ? "PUT" : "POST", body: f }); onSaved(); }
    catch (e) { toastErr(e); }
  }
  return html`<${Modal} title=${initial.id ? "자산 유형 수정" : "자산 유형 추가"} onClose=${onClose}
    footer=${html`<button class="btn" onClick=${onClose}>취소</button><button class="btn primary" onClick=${save}>저장</button>`}>
    <div class="form-grid">
      <label>이름</label><input type="text" value=${f.name} onInput=${upd("name")} placeholder="예: 연금저축, 가상자산" />
      <label>평가 방식</label><select value=${f.valuation} onChange=${upd("valuation")}><option value="balance">잔액 (현금·예금·기타)</option><option value="holdings">보유 수량 × 가격 (주식·ETF)</option></select>
      <label>성격</label><select value=${f.liquidity} onChange=${upd("liquidity")}><option value="cash">현금성</option><option value="investment">투자</option><option value="other">기타</option></select>
    </div><//>`;
}
