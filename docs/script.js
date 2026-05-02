
function statusClass(status) {
    const s = status.toUpperCase();
    if (s.includes('COMPRA')) return 'status-compra';
    if (s.includes('ALTA'))   return 'status-alta';
    if (s.includes('VENDA'))  return 'status-venda';
    return 'status-neutro';
}

function bandPosition(preco, cmin, cmax) {
    const p  = parseFloat(preco.replace(/,/g, ''));
    const mn = parseFloat(cmin.replace(/,/g, ''));
    const mx = parseFloat(cmax.replace(/,/g, ''));
    if (mx === mn) return 50;
    return Math.max(2, Math.min(98, ((p - mn) / (mx - mn)) * 100)).toFixed(1);
}

function calcPrecisao(historico) {
    const comResultado = historico.filter(h => h.acerto !== null);
    if (!comResultado.length) return null;
    const acertos = comResultado.filter(h => h.acerto === '✅').length;
    return Math.round((acertos / comResultado.length) * 100);
}

function acertosPorMoeda(historico, moeda) {
    const filtrado = historico.filter(h => h.moeda === moeda && h.acerto !== null);
    const acertos  = filtrado.filter(h => h.acerto === '✅').length;
    return { acertos, total: filtrado.length };
}


function renderFreshness(ultimaAtualizacao) {
    const partes = ultimaAtualizacao.match(/(\d+)\/(\d+)\/(\d+) (\d+):(\d+)/);
    if (!partes) return;

    const dataUTC = new Date(Date.UTC(
        parseInt(partes[3]),
        parseInt(partes[2]) - 1,
        parseInt(partes[1]),
        parseInt(partes[4]),
        parseInt(partes[5])
    ));

    const horasPassadas = Math.floor((new Date() - dataUTC) / 3600000);
    const badge = document.getElementById('freshness-badge');

    if (horasPassadas < 12) {
        badge.className = 'badge badge-ok';
        badge.innerHTML = `<i class="fas fa-circle-check"></i> Atualizado há ${horasPassadas}h`;
    } else if (horasPassadas < 24) {
        badge.className = 'badge badge-warn';
        badge.innerHTML = `<i class="fas fa-triangle-exclamation"></i> Atualizado há ${horasPassadas}h — pode estar desatualizado`;
    } else {
        badge.className = 'badge badge-err';
        badge.innerHTML = `<i class="fas fa-circle-xmark"></i> Atualizado há ${horasPassadas}h — robô pode estar com problema!`;
    }
}


function renderSummary(data, historico) {
    const ativos = data.ativos;

    const compras = ativos.filter(a => parseFloat(a.variacao) > 0).length;
    const precisao = calcPrecisao(historico);

    const maiorAlta = ativos.reduce((best, a) => {
        const v = parseFloat(a.variacao);
        return v > parseFloat(best.variacao) ? a : best;
    }, ativos[0]);

    const horaAtual = new Date().getHours();
    const horaRodada = 10;
    const horasProx = horaAtual < horaRodada
        ? horaRodada - horaAtual
        : 24 - horaAtual + horaRodada;

    document.getElementById('s-ativos').textContent  = ativos.length;
    document.getElementById('s-compra').textContent  = compras;

    const elPrecisao = document.getElementById('s-precisao');
    if (precisao !== null) {
        elPrecisao.textContent = precisao + '%';
        elPrecisao.className   = 'scard-val ' + (precisao >= 60 ? 'up' : 'down');
    } else {
        elPrecisao.textContent = 'Aguardando';
        elPrecisao.className   = 'scard-val warn';
    }

    document.getElementById('s-alta').textContent =
        `${maiorAlta.moeda.charAt(0) + maiorAlta.moeda.slice(1).toLowerCase()} ${maiorAlta.variacao}%`;

    document.getElementById('s-prox').textContent = `~${horasProx}h`;
}


function renderCards(data, historico) {
    const grid = document.getElementById('dashboard-grid');
    grid.innerHTML = '';

    data.ativos.forEach(ativo => {
        const isUp  = parseFloat(ativo.variacao) > 0;
        const pos   = bandPosition(ativo.preco, ativo.confianca_min, ativo.confianca_max);
        const { acertos, total } = acertosPorMoeda(historico, ativo.moeda);
        const pct = total > 0 ? Math.round((acertos / total) * 100) : null;

        let segmentos = '';
        if (total > 0) {
            for (let i = 0; i < total; i++) {
                segmentos += `<div class="acc-seg ${i < acertos ? 'ok' : 'err'}"></div>`;
            }
        } else {
            segmentos = `<div class="acc-seg pend" style="flex:3"></div>`;
        }

        const pctHtml = pct !== null
            ? `<span class="acc-pct" style="color:${pct >= 60 ? 'var(--up)' : 'var(--down)'}">${acertos}/${total} (${pct}%)</span>`
            : `<span class="acc-pct" style="color:var(--text-muted)">Aguardando dados</span>`;

        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
            <div class="card-top">
                <span class="card-name">${ativo.moeda}</span>
                <span class="status-chip ${statusClass(ativo.status)}">${ativo.status}</span>
            </div>
            <div class="card-body">
                <div class="price-row">
                    <span class="price-val">$${ativo.preco}</span>
                    <span class="price-chg ${isUp ? 'up' : 'down'}">
                        ${isUp ? '▲' : '▼'} ${ativo.variacao}%
                    </span>
                </div>

                <div class="info-row">
                    <span class="info-label">Previsão amanhã</span>
                    <span class="info-val ${isUp ? 'up' : 'down'}">$${ativo.previsao}</span>
                </div>

                <div class="band-wrap">
                    <div class="band-title">Posição no intervalo de confiança 90%</div>
                    <div class="band-bar">
                        <div class="band-fill"></div>
                        <div class="band-dot" style="left:${pos}%"></div>
                    </div>
                    <div class="band-labels">
                        <span class="band-lbl">$${ativo.confianca_min}</span>
                        <span class="band-lbl" style="color:var(--accent);font-size:0.68rem">● preço atual</span>
                        <span class="band-lbl">$${ativo.confianca_max}</span>
                    </div>
                </div>

                <div class="acc-wrap">
                    <div class="acc-bar">${segmentos}</div>
                    <div class="acc-row">
                        <span class="acc-label">Acertos recentes (intervalo)</span>
                        ${pctHtml}
                    </div>
                </div>
            </div>
            <div class="card-footer">
                <a class="chart-btn" href="./${ativo.imagem}" target="_blank">
                    <i class="fas fa-chart-area"></i> Ver gráfico de IA
                </a>
                <span class="card-model-label">Prophet + RSI/SMA</span>
            </div>
        `;
        grid.appendChild(card);
    });
}


let historicoGlobal = [];
let filtroAtivo = 'TODOS';

function renderFiltros(historico) {
    const moedas = [...new Set(historico.map(h => h.moeda))].sort();
    const row = document.getElementById('filter-row');
    row.innerHTML = `<button class="filter-btn active" data-moeda="TODOS">Todos</button>`;

    moedas.forEach(moeda => {
        const btn = document.createElement('button');
        btn.className = 'filter-btn';
        btn.dataset.moeda = moeda;
        btn.textContent = moeda.charAt(0) + moeda.slice(1).toLowerCase();
        row.appendChild(btn);
    });

    row.addEventListener('click', e => {
        const btn = e.target.closest('.filter-btn');
        if (!btn) return;
        filtroAtivo = btn.dataset.moeda;
        row.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b === btn));
        renderHistoricoTabela();
    });
}

function renderHistoricoTabela() {
    const tbody = document.getElementById('historico-body');
    const dados = filtroAtivo === 'TODOS'
        ? historicoGlobal
        : historicoGlobal.filter(h => h.moeda === filtroAtivo);

    if (!dados.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">Nenhum dado encontrado.</td></tr>`;
        return;
    }

    tbody.innerHTML = [...dados].reverse().map(h => {
        let chipHtml, chipClass;
        if (h.acerto === null) {
            chipClass = 'chip-pending'; chipHtml = '<i class="fas fa-clock"></i> Aguardando';
        } else if (h.acerto === '✅') {
            chipClass = 'chip-ok'; chipHtml = '<i class="fas fa-check"></i> Dentro do intervalo';
        } else {
            chipClass = 'chip-err'; chipHtml = '<i class="fas fa-xmark"></i> Fora do intervalo';
        }

        const realStr = h.preco_real !== null
            ? `$${h.preco_real.toLocaleString('pt-BR')}`
            : `<span style="color:var(--text-faint)">—</span>`;

        const erroStr = h.erro !== null
            ? `<span style="color:${Math.abs(h.erro / (h.preco_real || 1) * 100) < 2 ? 'var(--up)' : 'var(--down)'}">
                ${h.erro > 0 ? '+' : ''}${h.erro.toLocaleString('pt-BR')}
               </span>`
            : `<span style="color:var(--text-faint)">—</span>`;

        const intervalo = `$${h.confianca_min.toLocaleString('pt-BR')} – $${h.confianca_max.toLocaleString('pt-BR')}`;

        return `<tr>
            <td>${h.data}</td>
            <td class="moeda-cell">${h.moeda}</td>
            <td>$${h.previsao.toLocaleString('pt-BR')}</td>
            <td>${realStr}</td>
            <td style="font-size:0.75rem;color:var(--text-muted)">${intervalo}</td>
            <td>${erroStr}</td>
            <td><span class="result-chip ${chipClass}">${chipHtml}</span></td>
        </tr>`;
    }).join('');
}

/* ── INIT ────────────────────────────────────────────── */

async function init() {
    try {
        const [resData, resHist] = await Promise.all([
            fetch('./data.json'),
            fetch('./historico.json')
        ]);

        const data      = await resData.json();
        const historico = await resHist.json();

        historicoGlobal = historico;

        renderFreshness(data.ultima_atualizacao);
        renderSummary(data, historico);
        renderCards(data, historico);
        renderFiltros(historico);
        renderHistoricoTabela();

    } catch (err) {
        console.error('Erro ao carregar dados:', err);
        document.getElementById('dashboard-grid').innerHTML =
            `<p class="loading" style="color:var(--down)">
                <i class="fas fa-circle-xmark"></i>
                Erro ao carregar dados. O robô precisa rodar ao menos uma vez.
             </p>`;
    }
}

window.addEventListener('DOMContentLoaded', init);