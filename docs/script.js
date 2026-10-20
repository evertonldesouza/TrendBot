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
    const acertos = comResultado.filter(h => h.acerto === '\u2705').length;
    return Math.round((acertos / comResultado.length) * 100);
}

function acertosPorMoeda(historico, moeda) {
    const alvo = moedaCanonica(moeda);
    const filtrado = historico.filter(h => moedaCanonica(h.moeda) === alvo && h.acerto !== null);
    const acertos  = filtrado.filter(h => h.acerto === '\u2705').length;
    return { acertos, total: filtrado.length };
}

function parseDataBR(str) {
    const partes = str.match(/(\d+)\/(\d+)\/(\d+) (\d+):(\d+)/);
    if (!partes) return null;
    return new Date(
        parseInt(partes[3]),
        parseInt(partes[2]) - 1,
        parseInt(partes[1]),
        parseInt(partes[4]),
        parseInt(partes[5])
    );
}

function renderFreshness(ultimaAtualizacao) {
    const dataUTC = parseDataBR(ultimaAtualizacao);
    if (!dataUTC) return;

    const horasPassadas = Math.floor((new Date() - dataUTC) / 3600000);
    const badge = document.getElementById('freshness-badge');

    if (horasPassadas < 0) {
        badge.className = 'badge badge-ok';
        badge.innerHTML = '<i class="fas fa-circle-check" aria-hidden="true"></i> Dados do futuro (fuso horario?)';
        return;
    }

    if (horasPassadas < 12) {
        badge.className = 'badge badge-ok';
        badge.innerHTML = '<i class="fas fa-circle-check" aria-hidden="true"></i> Atualizado ha ' + horasPassadas + 'h';
    } else if (horasPassadas < 24) {
        badge.className = 'badge badge-warn';
        badge.innerHTML = '<i class="fas fa-triangle-exclamation" aria-hidden="true"></i> Atualizado ha ' + horasPassadas + 'h &mdash; pode estar desatualizado';
    } else {
        badge.className = 'badge badge-err';
        badge.innerHTML = '<i class="fas fa-circle-xmark" aria-hidden="true"></i> Atualizado ha ' + horasPassadas + 'h &mdash; robo pode estar com problema!';
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

    const dataUTC = parseDataBR(data.ultima_atualizacao);
    let horasProx = '~14h';
    if (dataUTC) {
        const horaRodada = dataUTC.getUTCHours() + 3;
        const horaAtual = new Date().getHours();
        horasProx = horaAtual < horaRodada
            ? '~' + (horaRodada - horaAtual) + 'h'
            : '~' + (24 - horaAtual + horaRodada) + 'h';
    }

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
        maiorAlta.moeda.charAt(0) + maiorAlta.moeda.slice(1).toLowerCase() + ' ' + maiorAlta.variacao + '%';

    document.getElementById('s-prox').textContent = horasProx;
}

function escapeHtml(texto) {
    return String(texto)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderFonte(data) {
    const banner = document.getElementById('fonte-banner');
    if (!banner) return;
    const fonte = data.fonte;
    if (!fonte) { banner.hidden = true; return; }

    banner.hidden = false;
    if (fonte.simulada) {
        banner.className = 'fonte-banner';
        banner.innerHTML =
            '<i class="fas fa-triangle-exclamation" aria-hidden="true"></i> ' +
            '<strong>Dados simulados.</strong> ' + escapeHtml(fonte.aviso || '');
    } else {
        banner.className = 'fonte-banner ok';
        banner.innerHTML =
            '<i class="fas fa-circle-info" aria-hidden="true"></i> ' +
            '<strong>Fonte:</strong> ' + escapeHtml(fonte.nome || fonte.id || '') +
            ' &mdash; ' + escapeHtml(fonte.aviso || '');
    }
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
                segmentos += '<div class="acc-seg ' + (i < acertos ? 'ok' : 'err') + '"></div>';
            }
        } else {
            segmentos = '<div class="acc-seg pend" style="flex:3"></div>';
        }

        const pctHtml = pct !== null
            ? '<span class="acc-pct" style="color:' + (pct >= 60 ? 'var(--up)' : 'var(--down)') + '">' + acertos + '/' + total + ' (' + pct + '%)</span>'
            : '<span class="acc-pct" style="color:var(--text-muted)">Aguardando dados</span>';

        const card = document.createElement('div');
        card.className = 'card';
        card.setAttribute('role', 'article');
        card.setAttribute('aria-label', 'Previsao para ' + ativo.moeda);
        card.innerHTML =
            '<div class="card-top">' +
                '<span class="card-name">' + ativo.moeda + '</span>' +
                '<span class="status-chip ' + statusClass(ativo.status) + '">' + ativo.status + '</span>' +
            '</div>' +
            '<div class="card-body">' +
                '<div class="price-row">' +
                    '<span class="price-val">$' + ativo.preco + '</span>' +
                    '<span class="price-chg ' + (isUp ? 'up' : 'down') + '">' +
                        (isUp ? '\u25B2' : '\u25BC') + ' ' + ativo.variacao + '%' +
                    '</span>' +
                '</div>' +
                '<div class="info-row">' +
                    '<span class="info-label">Previsao amanha</span>' +
                    '<span class="info-val ' + (isUp ? 'up' : 'down') + '">$' + ativo.previsao + '</span>' +
                '</div>' +
                '<div class="band-wrap">' +
                    '<div class="band-title">Posicao no intervalo de confianca 90%</div>' +
                    '<div class="band-bar" role="img" aria-label="Posicao do preco atual no intervalo: ' + pos + '%">' +
                        '<div class="band-fill"></div>' +
                        '<div class="band-dot" style="left:' + pos + '%"></div>' +
                    '</div>' +
                    '<div class="band-labels">' +
                        '<span class="band-lbl">$' + ativo.confianca_min + '</span>' +
                        '<span class="band-lbl" style="color:var(--accent);font-size:0.68rem">\u25CF preco atual</span>' +
                        '<span class="band-lbl">$' + ativo.confianca_max + '</span>' +
                    '</div>' +
                '</div>' +
                '<div class="acc-wrap">' +
                    '<div class="acc-bar">' + segmentos + '</div>' +
                    '<div class="acc-row">' +
                        '<span class="acc-label">Acertos recentes (intervalo)</span>' +
                        pctHtml +
                    '</div>' +
                '</div>' +
            '</div>' +
            '<div class="card-footer">' +
                '<a class="chart-btn" href="./' + ativo.imagem + '" target="_blank" rel="noopener">' +
                    '<i class="fas fa-chart-area" aria-hidden="true"></i> Ver grafico de IA' +
                '</a>' +
                '<span class="card-model-label">Prophet + RSI/SMA</span>' +
            '</div>';
        grid.appendChild(card);
    });
}

/* ---------------------------------------------------------------------------
 * Moeda canônica
 *
 * historico.json acumula dois padrões de nome: o legado ("BITCOIN",
 * "ETHEREUM" ...) e o atual ("BTC", "ETH" ...). Sem unificar, o filtro mostra
 * o mesmo ativo duas vezes e — pior — a precisão por moeda dos cards fica
 * zerada, porque data.json usa "BTC" e o histórico antigo usa "BITCOIN".
 * ------------------------------------------------------------------------- */
const MOEDAS_CANONICAS = {
    BTC: { nome: 'Bitcoin',  aliases: ['BTC', 'BITCOIN'] },
    ETH: { nome: 'Ethereum', aliases: ['ETH', 'ETHEREUM', 'ETHER'] },
    SOL: { nome: 'Solana',   aliases: ['SOL', 'SOLANA'] },
    ADA: { nome: 'Cardano',  aliases: ['ADA', 'CARDANO'] },
};

const _ALIAS_PARA_CANONICA = (() => {
    const mapa = {};
    for (const canonica of Object.keys(MOEDAS_CANONICAS)) {
        for (const apelido of MOEDAS_CANONICAS[canonica].aliases) {
            mapa[apelido] = canonica;
        }
    }
    return mapa;
})();

function moedaCanonica(moeda) {
    const chave = String(moeda === null || moeda === undefined ? '' : moeda).trim().toUpperCase();
    return _ALIAS_PARA_CANONICA[chave] || chave;
}

function nomeMoeda(moeda) {
    const canonica = moedaCanonica(moeda);
    return MOEDAS_CANONICAS[canonica]
        ? MOEDAS_CANONICAS[canonica].nome
        : canonica.charAt(0) + canonica.slice(1).toLowerCase();
}

let historicoGlobal = [];

const estadoHistorico = {
    moeda: 'TODOS',
    resultado: 'TODOS',
    periodo: 'TODOS',
    ordem: 'recente',
    pagina: 1,
    porPagina: 25,
};

/** "dd/mm/aaaa" — parseDataBR exige a hora e não serve para o histórico. */
function parseDataHistorico(str) {
    const p = String(str || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!p) return null;
    return new Date(Number(p[3]), Number(p[2]) - 1, Number(p[1]));
}

/** Erro absoluto em % do preço real, ou null quando ainda não há resultado. */
function erroPercentual(h) {
    if (h.erro === null || h.erro === undefined || !h.preco_real) return null;
    return Math.abs(h.erro / h.preco_real) * 100;
}

function historicoFiltrado() {
    const agora = new Date();

    const dados = historicoGlobal.filter(h => {
        if (estadoHistorico.moeda !== 'TODOS' &&
            moedaCanonica(h.moeda) !== estadoHistorico.moeda) return false;

        if (estadoHistorico.resultado === 'PENDENTE' && h.acerto !== null) return false;
        if (estadoHistorico.resultado === 'ACERTO' && h.acerto !== '\u2705') return false;
        if (estadoHistorico.resultado === 'ERRO' && h.acerto !== '\u274C') return false;

        if (estadoHistorico.periodo !== 'TODOS') {
            const data = parseDataHistorico(h.data);
            if (!data) return false;
            const dias = (agora - data) / 86400000;
            if (dias > Number(estadoHistorico.periodo)) return false;
        }
        return true;
    });

    dados.sort((a, b) => {
        if (estadoHistorico.ordem === 'erro') {
            const ea = erroPercentual(a), eb = erroPercentual(b);
            if (ea === null && eb === null) return 0;
            if (ea === null) return 1;   // sem resultado vai para o fim
            if (eb === null) return -1;
            return eb - ea;
        }
        const da = parseDataHistorico(a.data), db = parseDataHistorico(b.data);
        const ta = da ? da.getTime() : 0, tb = db ? db.getTime() : 0;
        return estadoHistorico.ordem === 'antigo' ? ta - tb : tb - ta;
    });

    return dados;
}

function linhaHistorico(h) {
    let chipHtml, chipClass;
    if (h.acerto === null) {
        chipClass = 'chip-pending'; chipHtml = '<i class="fas fa-clock" aria-hidden="true"></i> Aguardando';
    } else if (h.acerto === '\u2705') {
        chipClass = 'chip-ok'; chipHtml = '<i class="fas fa-check" aria-hidden="true"></i> Dentro do intervalo';
    } else {
        chipClass = 'chip-err'; chipHtml = '<i class="fas fa-xmark" aria-hidden="true"></i> Fora do intervalo';
    }

    const realStr = h.preco_real !== null
        ? '$' + h.preco_real.toLocaleString('pt-BR')
        : '<span style="color:var(--text-faint)">&mdash;</span>';

    const erroStr = h.erro !== null
        ? '<span style="color:' + (Math.abs(h.erro / (h.preco_real || 1) * 100) < 2 ? 'var(--up)' : 'var(--down)') + '">' +
              (h.erro > 0 ? '+' : '') + h.erro.toLocaleString('pt-BR') +
          '</span>'
        : '<span style="color:var(--text-faint)">&mdash;</span>';

    const intervalo = '$' + h.confianca_min.toLocaleString('pt-BR') + ' &ndash; $' + h.confianca_max.toLocaleString('pt-BR');

    return '<tr>' +
        '<td>' + h.data + '</td>' +
        '<td class="moeda-cell">' + escapeHtml(nomeMoeda(h.moeda)) + '</td>' +
        '<td>$' + h.previsao.toLocaleString('pt-BR') + '</td>' +
        '<td>' + realStr + '</td>' +
        '<td style="font-size:0.75rem;color:var(--text-muted)">' + intervalo + '</td>' +
        '<td>' + erroStr + '</td>' +
        '<td><span class="result-chip ' + chipClass + '">' + chipHtml + '</span></td>' +
    '</tr>';
}

/** Números de página com elipse: 1 … 4 5 6 … 20 */
function paginasParaMostrar(atual, total) {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);

    const nums = new Set([1, total, atual, atual - 1, atual + 1]);
    if (atual <= 3) [2, 3, 4].forEach(n => nums.add(n));
    if (atual >= total - 2) [total - 3, total - 2, total - 1].forEach(n => nums.add(n));

    const ordenados = [...nums].filter(n => n >= 1 && n <= total).sort((a, b) => a - b);
    const saida = [];
    let anterior = 0;
    for (const n of ordenados) {
        if (anterior && n - anterior > 1) saida.push('...');
        saida.push(n);
        anterior = n;
    }
    return saida;
}

function renderPaginacao(total, de, ate) {
    const nav = document.getElementById('paginacao');
    const paginas = Math.max(1, Math.ceil(total / estadoHistorico.porPagina));

    if (total === 0) {
        nav.innerHTML = '';
        return;
    }

    const partes = [];
    partes.push('<button class="pag-btn" data-pagina="' + (estadoHistorico.pagina - 1) + '"' +
                (estadoHistorico.pagina <= 1 ? ' disabled' : '') +
                ' aria-label="Pagina anterior">&laquo; Anterior</button>');

    for (const item of paginasParaMostrar(estadoHistorico.pagina, paginas)) {
        if (item === '...') {
            partes.push('<span class="pag-ellipsis" aria-hidden="true">…</span>');
            continue;
        }
        const ativa = item === estadoHistorico.pagina;
        partes.push('<button class="pag-btn" data-pagina="' + item + '"' +
                    (ativa ? ' aria-current="page"' : '') +
                    ' aria-label="Pagina ' + item + '">' + item + '</button>');
    }

    partes.push('<button class="pag-btn" data-pagina="' + (estadoHistorico.pagina + 1) + '"' +
                (estadoHistorico.pagina >= paginas ? ' disabled' : '') +
                ' aria-label="Proxima pagina">Proxima &raquo;</button>');

    nav.innerHTML = partes.join('');
}

document.addEventListener('click', e => {
    const btn = e.target.closest('#paginacao .pag-btn');
    if (!btn || btn.disabled) return;
    estadoHistorico.pagina = Number(btn.dataset.pagina);
    salvarEstadoNaURL();
    renderHistoricoTabela();
});

function renderHistoricoTabela() {
    const tbody = document.getElementById('historico-body');
    const dados = historicoFiltrado();
    const total = dados.length;
    const paginas = Math.max(1, Math.ceil(total / estadoHistorico.porPagina));

    // Filtro mudou e a página atual ficou fora do intervalo: volta para a 1.
    if (estadoHistorico.pagina > paginas) estadoHistorico.pagina = paginas;
    if (estadoHistorico.pagina < 1) estadoHistorico.pagina = 1;

    const inicio = (estadoHistorico.pagina - 1) * estadoHistorico.porPagina;
    const pagina = dados.slice(inicio, inicio + estadoHistorico.porPagina);

    const contagem = document.getElementById('hist-contagem');
    if (total === 0) {
        contagem.textContent = 'Nenhum registro com esses filtros.';
    } else {
        contagem.textContent = 'Mostrando ' + (inicio + 1) + '–' + (inicio + pagina.length) +
            ' de ' + total + (total !== historicoGlobal.length ? ' (de ' + historicoGlobal.length + ' no total)' : '');
    }

    if (!total) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading-cell">Nenhum registro encontrado com esses filtros.</td></tr>';
        renderPaginacao(0, 0, 0);
        return;
    }

    tbody.innerHTML = pagina.map(linhaHistorico).join('');
    renderPaginacao(total, inicio + 1, inicio + pagina.length);
}

function renderFiltros(historico) {
    const row = document.getElementById('filter-row');
    const contagemPorMoeda = {};
    historico.forEach(h => {
        const c = moedaCanonica(h.moeda);
        contagemPorMoeda[c] = (contagemPorMoeda[c] || 0) + 1;
    });

    const moedas = Object.keys(contagemPorMoeda)
        .sort((a, b) => nomeMoeda(a).localeCompare(nomeMoeda(b), 'pt-BR'));

    row.innerHTML = '<button class="filter-btn" data-moeda="TODOS" role="tab">Todos (' + historico.length + ')</button>';

    moedas.forEach(moeda => {
        const btn = document.createElement('button');
        btn.className = 'filter-btn';
        btn.dataset.moeda = moeda;
        btn.textContent = nomeMoeda(moeda) + ' (' + contagemPorMoeda[moeda] + ')';
        btn.setAttribute('role', 'tab');
        row.appendChild(btn);
    });

    sincronizarFiltrosUI();
}

function sincronizarFiltrosUI() {
    const row = document.getElementById('filter-row');
    if (row) {
        row.querySelectorAll('.filter-btn').forEach(b => {
            const ativo = b.dataset.moeda === estadoHistorico.moeda;
            b.classList.toggle('active', ativo);
            b.setAttribute('aria-selected', ativo ? 'true' : 'false');
        });
    }
    const set = (id, valor) => { const el = document.getElementById(id); if (el) el.value = valor; };
    set('filtro-resultado', estadoHistorico.resultado);
    set('filtro-periodo', estadoHistorico.periodo);
    set('filtro-ordem', estadoHistorico.ordem);
    set('filtro-porpagina', String(estadoHistorico.porPagina));
}

function salvarEstadoNaURL() {
    try {
        const p = new URLSearchParams();
        if (estadoHistorico.moeda !== 'TODOS') p.set('moeda', estadoHistorico.moeda);
        if (estadoHistorico.resultado !== 'TODOS') p.set('resultado', estadoHistorico.resultado);
        if (estadoHistorico.periodo !== 'TODOS') p.set('periodo', estadoHistorico.periodo);
        if (estadoHistorico.ordem !== 'recente') p.set('ordem', estadoHistorico.ordem);
        if (estadoHistorico.porPagina !== 25) p.set('porPagina', String(estadoHistorico.porPagina));
        if (estadoHistorico.pagina > 1) p.set('pagina', String(estadoHistorico.pagina));
        const query = p.toString();
        history.replaceState(null, '', query ? '?' + query : location.pathname);
    } catch (err) {
        /* file:// ou navegador sem suporte: o estado segue apenas em memória */
    }
}

function carregarEstadoDaURL() {
    try {
        const p = new URLSearchParams(location.search);
        const permitidos = (valor, opcoes) => opcoes.includes(valor) ? valor : null;

        const moeda = p.get('moeda');
        if (moeda && /^[A-Z]{2,10}$/.test(moeda)) estadoHistorico.moeda = moeda;

        const resultado = permitidos(p.get('resultado'), ['TODOS', 'ACERTO', 'ERRO', 'PENDENTE']);
        if (resultado) estadoHistorico.resultado = resultado;

        const periodo = permitidos(p.get('periodo'), ['TODOS', '7', '30', '90', '365']);
        if (periodo) estadoHistorico.periodo = periodo;

        const ordem = permitidos(p.get('ordem'), ['recente', 'antigo', 'erro']);
        if (ordem) estadoHistorico.ordem = ordem;

        const porPagina = permitidos(p.get('porPagina'), ['10', '25', '50', '100']);
        if (porPagina) estadoHistorico.porPagina = Number(porPagina);

        const pagina = Number(p.get('pagina'));
        if (Number.isInteger(pagina) && pagina > 0) estadoHistorico.pagina = pagina;
    } catch (err) {
        /* ignora: estado padrão */
    }
}

function ligarControles() {
    const row = document.getElementById('filter-row');
    row.addEventListener('click', e => {
        const btn = e.target.closest('.filter-btn');
        if (!btn) return;
        estadoHistorico.moeda = btn.dataset.moeda;
        estadoHistorico.pagina = 1;
        sincronizarFiltrosUI();
        salvarEstadoNaURL();
        renderHistoricoTabela();
    });

    const aoMudar = (id, chave, converter) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', () => {
            estadoHistorico[chave] = converter ? converter(el.value) : el.value;
            estadoHistorico.pagina = 1;
            salvarEstadoNaURL();
            renderHistoricoTabela();
        });
    };

    aoMudar('filtro-resultado', 'resultado');
    aoMudar('filtro-periodo', 'periodo');
    aoMudar('filtro-ordem', 'ordem');
    aoMudar('filtro-porpagina', 'porPagina', Number);
}

async function init() {
    try {
        const [resData, resHist] = await Promise.all([
            fetch('./data.json'),
            fetch('./historico.json')
        ]);

        if (!resData.ok || !resHist.ok) {
            throw new Error('Falha ao carregar dados');
        }

        const data      = await resData.json();
        const historico = await resHist.json();

        historicoGlobal = historico;
        carregarEstadoDaURL();

        renderFreshness(data.ultima_atualizacao);
        renderFonte(data);
        renderSummary(data, historico);
        renderCards(data, historico);
        renderFiltros(historico);
        ligarControles();
        renderHistoricoTabela();

    } catch (err) {
        console.error('Erro ao carregar dados:', err);
        document.getElementById('dashboard-grid').innerHTML =
            '<p class="loading" style="color:var(--down)" role="alert">' +
                '<i class="fas fa-circle-xmark" aria-hidden="true"></i> ' +
                'Erro ao carregar dados. O robo precisa rodar ao menos uma vez.' +
            '</p>';
    }
}

window.addEventListener('DOMContentLoaded', init);
