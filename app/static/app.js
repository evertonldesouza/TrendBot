/* TrendBot — painel (vanilla JS, SVG próprio, zero dependências externas) */

const state = {
  perfil: "moderado",
  ativos: ["bitcoin", "ethereum", "solana", "cardano"],
  capital: 25000,
  aporte: 1000,
  fonte: "auto",
  dias: 1095,
  backtest: true,
  posicoes: { BTC: 12000, ETH: 5000, SOL: 3000 },
  caixa: 5000,
  horizonte: 30,
  allocView: "target",
  data: null,
  catalogo: [],
  perfis: [],
};

const CORES = ["#58a6ff", "#a78bfa", "#2dd4bf", "#e3b341", "#3fb950",
  "#f778ba", "#79c0ff", "#d29922", "#f85149", "#7ee787"];
const COR_CAIXA = "#4d5563";

/* ---------------------------------------------------------------- utils */
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined) n.textContent = txt;
  return n;
};
const pct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const pctSigned = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const money = (v) => (v < 0 ? "-US$ " : "US$ ") +
  Math.abs(v).toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
const price = (v) => {
  if (v >= 1000) return `US$ ${v.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}`;
  if (v >= 10) return `US$ ${v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}`;
  if (v >= 1) return `US$ ${v.toLocaleString("pt-BR", { maximumFractionDigits: 3 })}`;
  return `US$ ${v.toLocaleString("pt-BR", { maximumFractionDigits: 5 })}`;
};
const corDe = (sym, i) => (sym === "USD" ? COR_CAIXA : CORES[i % CORES.length]);

/* ------------------------------------------------------------ bootstrap */
async function init() {
  const op = await fetch("/api/opcoes").then((r) => r.json());
  state.catalogo = op.ativos;
  state.perfis = op.perfis;

  const sel = $("#in-perfil");
  op.perfis.forEach((p) => {
    const o = el("option", null, `${p.rotulo} — vol alvo ${pct(p.vol_alvo, 0)} a.a.`);
    o.value = p.chave;
    sel.appendChild(o);
  });
  sel.value = state.perfil;
  sel.addEventListener("change", () => {
    state.perfil = sel.value;
    atualizaDescPerfil();
  });
  atualizaDescPerfil();

  renderChipsAtivos();
  renderCarteiraInputs();

  $("#in-capital").value = state.capital;
  $("#in-aporte").value = state.aporte;
  $("#in-fonte").value = state.fonte;
  $("#in-dias").value = state.dias;

  $("#btn-apply").addEventListener("click", () => coletarEEnviar());
  $("#btn-recalc").addEventListener("click", () => carregar(true));
  $("#btn-add-pos").addEventListener("click", () => {
    const livre = state.catalogo.find(
      (a) => a.symbol !== "USD" && !(a.symbol in state.posicoes));
    if (livre) {
      state.posicoes[livre.symbol] = 0;
      renderCarteiraInputs();
    }
  });

  const hz = $("#hz-toggle");
  hz.addEventListener("click", (e) => {
    const b = e.target.closest(".seg-btn");
    if (!b) return;
    state.horizonte = Number(b.dataset.hz);
    hz.querySelectorAll(".seg-btn").forEach((x) => x.classList.toggle("active", x === b));
    renderAtivos();
  });

  $("#alloc-toggle").addEventListener("click", (e) => {
    const b = e.target.closest(".seg-btn");
    if (!b) return;
    state.allocView = b.dataset.view;
    $("#alloc-toggle").querySelectorAll(".seg-btn")
      .forEach((x) => x.classList.toggle("active", x === b));
    renderAlocacao();
  });

  await carregar(false);
}

function atualizaDescPerfil() {
  const p = state.perfis.find((x) => x.chave === state.perfil);
  $("#perfil-desc").textContent = p
    ? `${p.descricao} Vol alvo ${pct(p.vol_alvo, 0)}/ano · tolera queda de até ${pct(p.queda_maxima, 0)}.`
    : "";
}

function renderChipsAtivos() {
  const box = $("#in-ativos");
  box.innerHTML = "";
  state.catalogo.forEach((a) => {
    const c = el("div", "chip" + (state.ativos.includes(a.key) ? " active" : ""), a.symbol);
    c.title = a.nome;
    c.addEventListener("click", () => {
      const i = state.ativos.indexOf(a.key);
      if (i >= 0) {
        if (state.ativos.length > 2) state.ativos.splice(i, 1);
      } else if (state.ativos.length < 8) {
        state.ativos.push(a.key);
      }
      renderChipsAtivos();
    });
    box.appendChild(c);
  });
}

function renderCarteiraInputs() {
  const box = $("#in-carteira");
  box.innerHTML = "";
  Object.keys(state.posicoes).forEach((sym) => {
    const row = el("div", "holding-row");
    const s = el("input");
    s.value = sym;
    s.style.textTransform = "uppercase";
    s.addEventListener("change", (e) => {
      const novo = e.target.value.toUpperCase();
      const v = state.posicoes[sym];
      delete state.posicoes[sym];
      state.posicoes[novo] = v;
      renderCarteiraInputs();
    });
    const v = el("input");
    v.type = "number";
    v.min = "0";
    v.step = "100";
    v.value = state.posicoes[sym];
    v.addEventListener("input", (e) => { state.posicoes[sym] = Number(e.target.value) || 0; });
    const x = el("button", "btn-icon", "×");
    x.addEventListener("click", () => { delete state.posicoes[sym]; renderCarteiraInputs(); });
    row.append(s, v, x);
    box.appendChild(row);
  });
  const row = el("div", "holding-row");
  const s = el("input");
  s.value = "USD";
  s.disabled = true;
  const v = el("input");
  v.type = "number";
  v.min = "0";
  v.value = state.caixa;
  v.addEventListener("input", (e) => { state.caixa = Number(e.target.value) || 0; });
  row.append(s, v, el("span"));
  box.appendChild(row);
}

function coletarEEnviar() {
  state.capital = Number($("#in-capital").value) || 0;
  state.aporte = Number($("#in-aporte").value) || 0;
  state.fonte = $("#in-fonte").value;
  state.dias = Number($("#in-dias").value) || 1095;
  state.backtest = $("#in-backtest").checked;
  carregar(true);
}

function montaURL(force) {
  const p = new URLSearchParams({
    perfil: state.perfil,
    ativos: state.ativos.join(","),
    dias: String(state.dias),
    fonte: state.fonte,
    capital: String(state.capital),
    aporte: String(state.aporte),
    backtest: state.backtest ? "1" : "0",
  });
  const pos = Object.entries(state.posicoes).filter(([, v]) => v > 0)
    .map(([k, v]) => `${k}:${v}`);
  if (state.caixa > 0) pos.push(`USD:${state.caixa}`);
  if (pos.length) p.set("carteira", pos.join(","));
  if (force) p.set("_", String(Date.now()));
  return `/api/relatorio?${p.toString()}`;
}

/* ------------------------------------------------------------- carregar */
async function carregar(force) {
  $("#loading").hidden = false;
  $("#results").hidden = true;
  $("#error").hidden = true;
  const btn = $("#btn-apply");
  btn.disabled = true;
  btn.textContent = "Calculando…";
  try {
    const resp = await fetch(montaURL(force));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Erro ao gerar relatório");
    state.data = data;
    render(data);
    $("#loading").hidden = true;
    $("#results").hidden = false;
  } catch (err) {
    $("#loading").hidden = true;
    $("#error").hidden = false;
    $("#error").textContent = `Não foi possível gerar a orientação: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Gerar orientação";
  }
}

/* -------------------------------------------------------------- render */
function render(d) {
  renderFonte(d);
  renderHero(d);
  renderKPIs(d);
  renderAlocacao();
  renderOrdens(d);
  renderRisco(d);
  renderAtivos();
  renderModelo(d);
  renderBacktest(d);
  renderAlertas(d);
  renderListas(d);
}

function renderFonte(d) {
  const badge = $("#source-badge");
  const m = d.meta;
  const demo = m.fonte_dados === "synthetic";
  const cls = demo ? "demo" : (m.fonte_dados === "csv" ? "warn" : "ok");
  badge.className = `badge ${cls}`;
  badge.innerHTML = `<span class="dot"></span>${m.fonte_legivel || m.fonte_dados} · ${m.ultimo_preco}`;
  badge.title = (m.avisos || []).join("\n") || "Dados carregados";
}

function renderHero(d) {
  const n = d.recomendacao.narrative;
  $("#hero-headline").textContent = n.headline;
  const ul = $("#hero-points");
  ul.innerHTML = "";
  n.pontos_principais.forEach((t) => ul.appendChild(el("li", null, t)));
}

function renderKPIs(d) {
  const r = d.recomendacao;
  const rt = r.risk_target;
  const rc = r.risk_current;
  const perfil = d.meta.perfil;
  const box = $("#kpis");
  box.innerHTML = "";

  const kpi = (label, value, sub, cls) => {
    const k = el("div", `kpi ${cls || ""}`);
    k.append(el("div", "kpi-label", label), el("div", "kpi-val", value));
    if (sub) k.appendChild(el("div", "kpi-sub", sub));
    box.appendChild(k);
  };

  kpi("Exposição a cripto", pct(r.equity_exposure, 0),
    `${pct(r.target_weights.USD || 0, 0)} em caixa`, "good");
  kpi("Volatilidade alvo", pct(rt.volatility, 0),
    `perfil pede ${pct(perfil.vol_alvo, 0)}`,
    rt.volatility > perfil.vol_maxima ? "bad" : "");
  const ddOk = Math.abs(rt.max_drawdown) <= perfil.queda_maxima;
  kpi("Pior queda histórica", pct(Math.abs(rt.max_drawdown), 0),
    `limite do perfil ${pct(perfil.queda_maxima, 0)}`, ddOk ? "" : "bad");
  kpi("VaR 95% (1 dia)", pct(rt.var95, 1), `CVaR ${pct(rt.cvar95, 1)}`, "warn");
  kpi("Sharpe estimado", rt.sharpe.toFixed(2), "retorno por unidade de risco",
    rt.sharpe > 0.5 ? "good" : "");
  kpi("Volatilidade atual", pct(rc.volatility, 0),
    rc.volatility > rt.volatility
      ? `recomendação corta ${((rc.volatility - rt.volatility) * 100).toFixed(0)} p.p.`
      : "dentro do alvo",
    rc.volatility > rt.volatility + 0.02 ? "warn" : "");
}

/* ----------------------------------------------------------- alocação */
function renderAlocacao() {
  const r = state.data.recomendacao;
  const alvo = r.target_weights;
  const atual = r.current_weights;
  const view = state.allocView;

  let dados, titulo;
  if (view === "current") {
    dados = atual; titulo = "";
  } else if (view === "delta") {
    dados = {};
    new Set([...Object.keys(alvo), ...Object.keys(atual)]).forEach((s) => {
      dados[s] = (alvo[s] || 0) - (atual[s] || 0);
    });
  } else {
    dados = alvo;
  }

  const itens = Object.entries(dados)
    .map(([s, v]) => [s, v])
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

  $("#alloc-donut").innerHTML =
    view === "delta" ? "" : donutSVG(itens.filter(([, v]) => v > 0.0005));

  const table = $("#alloc-table");
  table.innerHTML = "";
  const maxAbs = Math.max(...itens.map(([, v]) => Math.abs(v)), 0.01);
  itens.forEach(([s, v], i) => {
    const row = el("div", "arow");
    row.appendChild(el("div", "sym", s));
    const val = el("div", null, view === "delta"
      ? `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)} p.p.`
      : pct(v, 1));
    val.style.fontVariantNumeric = "tabular-nums";
    val.style.color = "#c3ccd8";
    row.appendChild(val);
    const bar = el("div", "bar");
    const fill = el("span");
    const w = (Math.abs(v) / maxAbs) * 100;
    fill.style.width = `${w}%`;
    fill.style.background = view === "delta"
      ? (v >= 0 ? "#3fb950" : "#f85149")
      : corDe(s, i);
    bar.appendChild(fill);
    row.appendChild(bar);
    const dv = (alvo[s] || 0) - (atual[s] || 0);
    const d = el("div", "delta " + (Math.abs(dv) < 0.005 ? "flat" : dv > 0 ? "up" : "down"),
      `${dv >= 0 ? "+" : ""}${(dv * 100).toFixed(1)}`);
    row.appendChild(d);
    table.appendChild(row);
  });
  if (!titulo) return;
}

function donutSVG(itens) {
  const size = 230, r = 92, cx = size / 2, cy = size / 2, sw = 30;
  const total = itens.reduce((a, [, v]) => a + v, 0) || 1;
  let acc = 0;
  const circ = 2 * Math.PI * r;
  let arcs = "";
  itens.forEach(([s, v], i) => {
    const frac = v / total;
    const len = frac * circ;
    arcs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
      stroke="${corDe(s, i)}" stroke-width="${sw}"
      stroke-dasharray="${len - 2} ${circ - len + 2}"
      stroke-dashoffset="${-acc * circ}" transform="rotate(-90 ${cx} ${cy})"
      stroke-linecap="butt"><title>${s}: ${pct(frac, 1)}</title></circle>`;
    acc += frac;
  });
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
    ${arcs}
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" fill="#e6edf3"
      font-size="26" font-weight="700">${pct(total, 0)}</text>
    <text x="${cx}" y="${cy + 16}" text-anchor="middle" fill="#8b98a9"
      font-size="11">do patrimônio</text>
  </svg>`;
}

/* -------------------------------------------------------------- ordens */
function renderOrdens(d) {
  const r = d.recomendacao;
  const box = $("#orders");
  box.innerHTML = "";
  const ativas = r.orders.filter((o) => !(o.action === "MANTER" && Math.abs(o.amount) < 1));
  $("#orders-count").textContent = `${ativas.length} movimentações`;
  ativas.forEach((o) => {
    const row = el("div", `order prio${o.priority}`);
    const cls = o.action.includes("COMPRAR") || o.action === "APORTAR" ? "a-buy"
      : o.action.includes("VENDER") || o.action === "ZERAR" ? "a-sell"
        : o.action.includes("CAIXA") ? "a-cash" : "a-hold";
    row.appendChild(el("div", `action ${cls}`, o.action));
    const mid = el("div");
    mid.appendChild(el("div", "reason", o.reason));
    mid.appendChild(el("div", "hint",
      `alvo ${pct(o.target_weight, 1)} · hoje ${pct(o.current_weight, 1)}`));
    row.appendChild(mid);
    const amt = el("div", "amount " + (o.amount > 0 ? "up" : o.amount < 0 ? "down" : "flat"),
      money(o.amount));
    row.appendChild(amt);
    box.appendChild(row);
  });

  const cb = $("#contrib-box");
  if (r.contributions && r.contributions.length) {
    cb.hidden = false;
    cb.innerHTML = "";
    cb.appendChild(el("h4", null,
      `Como dividir o aporte mensal de ${money(state.aporte)}`));
    r.contributions.forEach((c) => {
      const row = el("div", "contrib-row");
      row.appendChild(el("span", null, c.symbol === "USD" ? "Caixa / reserva" : c.symbol));
      row.appendChild(el("b", null, `${money(c.valor)}  (${pct(c.peso, 0)})`));
      cb.appendChild(row);
    });
    cb.appendChild(el("p", "hint",
      "Comprar primeiro o que está abaixo do alvo corrige a carteira sem vender nada."));
  } else {
    cb.hidden = true;
  }
}

/* --------------------------------------------------------------- risco */
function renderRisco(d) {
  const rt = d.recomendacao.risk_target;
  const bars = $("#risk-bars");
  bars.innerHTML = "";
  const contrib = Object.entries(rt.risk_contributions || {})
    .sort((a, b) => b[1] - a[1]);
  contrib.forEach(([s, v], i) => {
    const row = el("div", "rbar");
    row.appendChild(el("div", "sym", s));
    const track = el("div", "track");
    const fill = el("span");
    fill.style.width = `${Math.min(100, v * 100)}%`;
    fill.style.background = v > 0.4 ? "#f85149" : v > 0.25 ? "#e3b341" : "#58a6ff";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "val", pct(v, 1)));
    bars.appendChild(row);
  });
  bars.appendChild(el("p", "hint",
    `Soma 100% do risco da carteira. Índice de diversificação: ${rt.diversification_ratio.toFixed(2)}× — ` +
    "quanto mais perto de 1, menos a diversificação ajuda."));

  const st = $("#stress");
  st.innerHTML = "";
  d.recomendacao.stress.forEach((s) => {
    const row = el("div", "stress-row");
    row.appendChild(el("div", null, s.label));
    const v = el("div", "sv " + (s.impacto_base < 0 ? "down" : "up"),
      `${s.impacto_base >= 0 ? "+" : ""}${pctSigned(s.impacto_base, 0)}`);
    v.title = `Pior caso a 95% dentro do cenário: ${pctSigned(s.impacto_estresse_95, 0)}`;
    row.appendChild(v);
    st.appendChild(row);
  });
}

/* -------------------------------------------------------------- ativos */
function renderAtivos() {
  const d = state.data;
  const box = $("#assets");
  box.innerHTML = "";
  const hz = String(state.horizonte);
  Object.entries(d.previsoes).forEach(([sym, f]) => {
    const h = f.horizons[hz] || f.horizons["30"];
    const card = el("div", "asset-card");
    const head = el("div", "asset-head");
    head.appendChild(el("div", "sym", sym));
    head.appendChild(el("div", "price", price(f.price)));
    card.appendChild(head);

    const reg = f.regime_detail || {};
    card.appendChild(el("div", "asset-sub",
      `${reg.tendencia || ""} · ${reg.volatilidade || ""} · peso do modelo ${pct(f.model_weight, 0)}`));

    const serie = (d.precos.find((p) => p.symbol === sym) || {});
    card.insertAdjacentHTML("beforeend", fanSVG(serie, h, f.price));

    const qg = el("div", "quant-grid");
    const qbox = (l, v, cls) => {
      const b = el("div", "qbox");
      b.appendChild(el("div", "ql", l));
      b.appendChild(el("div", "qv " + (cls || ""), v));
      qg.appendChild(b);
    };
    qbox(`${hz}d mediana`, `${h.median_return >= 0 ? "+" : ""}${pctSigned(h.median_return, 1)}`,
      h.median_return >= 0 ? "up" : "down");
    qbox("p05", pctSigned(h.lower, 0), "down");
    qbox("p95", `+${pctSigned(h.upper, 0)}`, "up");
    qbox("prob. alta", pct(h.prob_up, 0), h.prob_up > 0.55 ? "up" : "flat");
    card.appendChild(qg);

    card.appendChild(el("div", "asset-sub",
      `RSI ${f.indicators.rsi14.toFixed(0)} · vol 30d ${pct(f.indicators.vol30d, 0)} a.a. · ` +
      `queda desde o topo ${pct(Math.abs(f.indicators.drawdown_atual), 0)}`));

    const dr = el("div", "drivers");
    (f.drivers || []).forEach((x) => {
      const row = el("div", `driver d-${x.sinal}`);
      row.appendChild(el("i"));
      row.appendChild(el("div", null, `${x.fator} (${x.valor}): ${x.texto}`));
      dr.appendChild(row);
    });
    card.appendChild(dr);
    box.appendChild(card);
  });
}

function fanSVG(serie, h, precoAtual) {
  if (!serie.prices || !serie.prices.length) return "";
  const W = 340, H = 120, pad = 6;
  const prices = serie.prices;
  const n = prices.length;
  const lo = Math.min(...prices, precoAtual * (1 + h.lower));
  const hi = Math.max(...prices, precoAtual * (1 + h.upper));
  const span = hi - lo || 1;
  const x = (i) => pad + (i / Math.max(1, n - 1)) * (W - pad * 2);
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2);

  const hist = prices.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const fut = n - 1 + 26;
  const fan = (a, b, fill, op) => {
    const y1 = y(precoAtual * (1 + a));
    const y2 = y(precoAtual * (1 + b));
    return `<path d="M${x(n - 1).toFixed(1)},${y(precoAtual).toFixed(1)}
      L${x(fut).toFixed(1)},${y1.toFixed(1)} L${x(fut).toFixed(1)},${y2.toFixed(1)} Z"
      fill="${fill}" opacity="${op}"/>`;
  };

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none">
    <rect x="0" y="0" width="${W}" height="${H}" fill="#131923" rx="8"/>
    ${fan(h.intervals.p95, h.intervals.p05, "#a78bfa", 0.13)}
    ${fan(h.intervals.p90, h.intervals.p10, "#a78bfa", 0.18)}
    ${fan(h.intervals.p75, h.intervals.p25, "#a78bfa", 0.26)}
    <path d="${hist}" fill="none" stroke="#58a6ff" stroke-width="1.6" stroke-linejoin="round"/>
    <line x1="${x(n - 1).toFixed(1)}" y1="${y(precoAtual).toFixed(1)}"
      x2="${x(fut).toFixed(1)}" y2="${y(precoAtual * (1 + h.median_return)).toFixed(1)}"
      stroke="#a78bfa" stroke-width="2" stroke-dasharray="4 3"/>
    <circle cx="${x(fut).toFixed(1)}" cy="${y(precoAtual * (1 + h.median_return)).toFixed(1)}"
      r="3.2" fill="#a78bfa"/>
  </svg>`;
}

/* -------------------------------------------------------------- modelo */
function renderModelo(d) {
  const m = d.modelo;
  const n = d.recomendacao.narrative;
  $("#model-verdict").textContent = n.veredito_modelo;
  const box = $("#model-body");
  box.innerHTML = "";
  const grid = el("div", "model-grid");
  const metric = (l, v, note) => {
    const b = el("div", "metric");
    b.append(el("div", "ml", l), el("div", "mv", v));
    if (note) b.appendChild(el("div", "mn", note));
    grid.appendChild(b);
  };
  metric("Habilidade fora da amostra", m.avg_skill.toFixed(3),
    "0 = empata com o chute ingênuo");
  metric("Acerto de direção", pct(m.avg_hit_rate, 1), "50% = cara ou coroa");
  metric("Cobertura dos intervalos", pct(m.avg_coverage, 0), "alvo: 90%");
  metric("Observações de teste", String(m.observations), "validação walk-forward");
  box.appendChild(grid);

  const notes = el("div", "notes");
  (m.notes || []).forEach((t) => notes.appendChild(el("div", "note", t)));
  notes.appendChild(el("div", "note", n.sobre_o_modelo));
  box.appendChild(notes);
}

/* ------------------------------------------------------------ backtest */
function renderBacktest(d) {
  const bt = d.backtest;
  const card = $("#backtest-card");
  if (!bt) { card.hidden = true; return; }
  card.hidden = false;

  const estrategias = bt.estrategias.filter((s) => s.equity_curve && s.equity_curve.length);
  const todas = estrategias.flatMap((s) => s.equity_curve.map((p) => p.date));
  const minD = todas.reduce((a, b) => (a < b ? a : b));
  const maxD = todas.reduce((a, b) => (a > b ? a : b));
  const W = 860, H = 300, padL = 56, padR = 12, padT = 14, padB = 30;

  const vals = estrategias.flatMap((s) => s.equity_curve.map((p) => p.value));
  const lo = Math.max(1, Math.min(...vals)), hi = Math.max(...vals);
  const t0 = new Date(minD).getTime(), t1 = new Date(maxD).getTime();
  const sx = (dateStr) => padL + ((new Date(dateStr).getTime() - t0) / Math.max(1, t1 - t0)) * (W - padL - padR);
  const sy = (v) => padT + (1 - (Math.log10(Math.max(v, 1)) - Math.log10(lo)) /
    Math.max(1e-9, Math.log10(hi) - Math.log10(lo))) * (H - padT - padB);

  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`;
  svg += `<rect x="0" y="0" width="${W}" height="${H}" fill="#131923" rx="10"/>`;
  const ticks = [lo, Math.sqrt(lo * hi), hi];
  ticks.forEach((v) => {
    svg += `<line x1="${padL}" y1="${sy(v).toFixed(1)}" x2="${W - padR}" y2="${sy(v).toFixed(1)}"
      stroke="#263041" stroke-width="1"/>`;
    svg += `<text x="${padL - 8}" y="${(sy(v) + 4).toFixed(1)}" text-anchor="end"
      fill="#5b6676" font-size="10">${price(v)}</text>`;
  });
  [minD, maxD].forEach((d2, i) => {
    const xx = sx(d2);
    svg += `<text x="${xx.toFixed(1)}" y="${H - 10}" text-anchor="${i === 0 ? "start" : "end"}"
      fill="#5b6676" font-size="10">${d2}</text>`;
  });

  estrategias.forEach((s, i) => {
    const isTb = i === 0;
    const pts = s.equity_curve.map((p) => `${sx(p.date).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
    svg += `<polyline points="${pts}" fill="none"
      stroke="${corDe(s.name === "TrendBot" ? "USD" : "BTC", i)}"
      stroke-width="${isTb ? 2.6 : 1.2}" opacity="${isTb ? 1 : 0.72}"/>`;
    const last = s.equity_curve[s.equity_curve.length - 1];
    svg += `<circle cx="${sx(last.date).toFixed(1)}" cy="${sy(last.value).toFixed(1)}"
      r="${isTb ? 4 : 2.6}" fill="${corDe(s.name === "TrendBot" ? "USD" : "BTC", i)}"/>`;
  });
  svg += "</svg>";

  let legenda = '<div class="fan-legend" style="margin-top:8px">';
  estrategias.forEach((s, i) => {
    legenda += `<span><i style="background:${corDe(s.name.startsWith("TrendBot") ? "USD" : "BTC", i)}"></i>${s.name}</span>`;
  });
  legenda += "</div>";

  $("#backtest-chart").innerHTML = svg + legenda;

  const tb = document.createElement("table");
  tb.className = "bt-table";
  tb.innerHTML = `<thead><tr><th>Estratégia</th><th>Resultado</th><th>CAGR</th>
    <th>Vol</th><th>Sharpe</th><th>Pior queda</th></tr></thead>`;
  const body = el("tbody");
  bt.estrategias.forEach((s, i) => {
    const tr = el("tr", i === 0 ? "hl" : "");
    tr.appendChild(el("td", null, s.name));
    tr.appendChild(el("td", null, money(s.final_value)));
    tr.appendChild(el("td", null, `${(s.cagr * 100).toFixed(1)}%`));
    tr.appendChild(el("td", null, `${(s.volatility * 100).toFixed(0)}%`));
    tr.appendChild(el("td", null, s.sharpe.toFixed(2)));
    tr.appendChild(el("td", null, `${(s.max_drawdown * 100).toFixed(0)}%`));
    body.appendChild(tr);
  });
  tb.appendChild(body);
  $("#backtest-table").innerHTML = "";
  $("#backtest-table").appendChild(tb);
  $("#backtest-verdict").textContent = bt.resumo.veredito;
}

/* ------------------------------------------------------------- alertas */
function renderAlertas(d) {
  const alerts = d.recomendacao.alerts || [];
  const card = $("#alerts-card");
  card.hidden = alerts.length === 0;
  const box = $("#alerts");
  box.innerHTML = "";
  alerts.forEach((a) => {
    const row = el("div", `alert ${a.level}`);
    row.appendChild(el("div", "lvl", a.level));
    const msg = el("div", "msg");
    msg.appendChild(el("b", null, a.title));
    msg.appendChild(document.createTextNode(a.message));
    row.appendChild(msg);
    box.appendChild(row);
  });
}

function renderListas(d) {
  const n = d.recomendacao.narrative;
  const fill = (sel, arr) => {
    const ul = $(sel);
    ul.innerHTML = "";
    arr.forEach((t) => ul.appendChild(el("li", null, t)));
  };
  fill("#watch", n.o_que_observar);
  fill("#invalidate", n.o_que_me_faria_mudar_de_ideia);
}

document.addEventListener("DOMContentLoaded", init);
