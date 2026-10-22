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

function renderModelCard(data) {
    const bloco = document.getElementById('model-card');
    const modelo = data && data.modelo;
    if (!bloco || !modelo) return;

    const skill = Number(modelo.avg_skill);
    const cobertura = Number(modelo.avg_coverage);
    const obs = Number(modelo.observations);

    document.getElementById('mc-verdict').textContent = modelo.verdict || '';

    const metricas = [];
    if (Number.isFinite(skill)) {
        metricas.push(['Habilidade fora da amostra', (skill > 0 ? '+' : '') + skill.toFixed(3),
                       skill > 0.05 ? 'up' : skill < -0.05 ? 'down' : 'warn']);
    }
    if (Number.isFinite(cobertura) && obs > 0) {
        metricas.push(['Cobertura fora da amostra', Math.round(cobertura * 100) + '%',
                       cobertura >= 0.85 && cobertura <= 0.97 ? 'up' : 'warn']);
    }
    metricas.push(['Pontos de teste', String(obs), obs >= 120 ? 'up' : 'warn']);

    document.getElementById('mc-metrics').innerHTML = metricas.map(([rotulo, valor, tom]) =>
        '<div class="mc-metric"><span class="mc-metric-label">' + rotulo +
        '</span><span class="mc-metric-valor ' + tom + '">' + valor + '</span></div>'
    ).join('');

    const notas = (modelo.notes || []).slice();

    // Se os intervalos foram encolhidos por calibração, isso tem de aparecer:
    // a banda exibida não é a que o modelo produziu, e o leitor merece saber
    // com quantos pontos o ajuste foi estimado.
    const cal = data.calibracao;
    if (cal && cal.ajustado && Number(cal.fator) && Number(cal.fator) !== 1) {
        const pct = Math.round((1 - Number(cal.fator)) * 100);
        notas.push('Intervalos reduzidos em ' + pct + '% por calibração, para '
            + 'perseguir ' + Math.round(Number(cal.alvo_cobertura) * 100)
            + '% de cobertura. Estimado com ' + cal.amostra
            + ' previsões já conferidas — amostra pequena significa ajuste '
            + 'menor, de propósito.');
    }

    document.getElementById('mc-notas').innerHTML =
        notas.map(n => '<li>' + escapeHtml(n) + '</li>').join('');

    bloco.hidden = false;
}

function pct(n) {
    return (n * 100).toFixed(1).replace('.', ',') + '%';
}

function valorBR(n) {
    const v = Number(n) || 0;
    return (v < 0 ? '-' : '') + '$' +
           Math.abs(v).toLocaleString('pt-BR', { minimumFractionDigits: 2,
                                                 maximumFractionDigits: 2 });
}

function dataHoraISO(iso) {
    // o motor grava ISO ("2026-10-22T12:18:09"), não o "dd/mm/aaaa hh:mm" do
    // restante do painel — parseDataBR não entende esse formato
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    const p = x => String(x).padStart(2, '0');
    return p(d.getDate()) + '/' + p(d.getMonth() + 1) + '/' + d.getFullYear() +
           ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

function renderRecomendacao(rec, data) {
    const bloco = document.getElementById('rec');
    if (!bloco) return;

    const dados = rec && rec.recomendacao;
    if (!dados) { bloco.hidden = true; return; }

    const meta = rec.meta || {};

    // a recomendação carrega a própria fonte, e os dois arquivos podem ter
    // origens diferentes (o motor caiu no simulador num ciclo e não no outro)
    const fontePainel = data && data.fonte ? data.fonte.id : null;
    if (meta.fonte && meta.fonte !== 'synthetic') {
        bloco.classList.remove('rec-fonte-divergente');
    } else if (meta.fonte === 'synthetic') {
        bloco.classList.add('rec-fonte-divergente');
        const aviso = document.getElementById('rec-fonte-aviso');
        if (aviso) aviso.hidden = false;
    }
    if (fontePainel && meta.fonte && meta.fonte !== fontePainel) {
        console.warn('fonte divergente: recomendacao=' + meta.fonte +
                     ' data.json=' + fontePainel);
    }
    const perfil = (meta.perfil || dados.profile || '').toString();
    document.getElementById('rec-meta').textContent =
        (perfil ? 'Perfil ' + perfil.charAt(0).toUpperCase() + perfil.slice(1) : '') +
        (meta.gerado_em ? ' \u00b7 ' + dataHoraISO(meta.gerado_em) : '');

    document.getElementById('rec-headline').textContent =
        (dados.narrative && dados.narrative.headline) || '';

    // alocação: alvo x atual, na ordem de peso alvo (maior primeiro)
    const alvo = dados.target_weights || {};
    const atual = dados.current_weights || {};
    const simbolos = Object.keys(alvo).sort((a, b) => alvo[b] - alvo[a]);
    document.getElementById('rec-alocacao').innerHTML = simbolos.map(simb => {
        const a = alvo[simb] || 0;
        const c = atual[simb] || 0;
        const diff = a - c;
        const tom = Math.abs(diff) < 0.005 ? '' : diff > 0 ? 'up' : 'down';
        // data-label: no celular a tabela vira bloco e o rótulo sai daqui
        return '<tr>' +
               '<td data-label="Ativo">' + escapeHtml(simb) + '</td>' +
               '<td data-label="Atual">' + pct(c) + '</td>' +
               '<td data-label="Alvo">' + pct(a) + '</td>' +
               '<td data-label="Diferenca" class="' + tom + '">' +
               (diff > 0 ? '+' : '') + pct(diff) + '</td></tr>';
    }).join('');

    // ordens sugeridas, por prioridade
    const ordens = (dados.orders || []).slice().sort((a, b) =>
        (a.priority || 99) - (b.priority || 99));
    document.getElementById('rec-ordens').innerHTML = ordens.map(o => {
        const valor = Number(o.amount) || 0;
        const tom = valor > 0 ? 'up' : valor < 0 ? 'down' : '';
        return '<tr>' +
               '<td data-label="Acao">' + escapeHtml(o.symbol + ' \u2014 ' + (o.action || '')) + '</td>' +
               '<td data-label="Valor" class="' + tom + '">' + valorBR(valor) + '</td>' +
               '<td class="rec-motivo">' + escapeHtml(o.reason || '') + '</td></tr>';
    }).join('');

    const hedge = dados.hedge;
    if (hedge) {
        document.getElementById('rec-protecao-bloco').hidden = false;
        document.getElementById('rec-protecao').textContent =
            'Caixa recomendado: ' + pct(hedge.cash_weight || 0) +
            (hedge.de_risk_level && hedge.de_risk_level !== 'nenhum'
                ? ' (redu\u00e7\u00e3o de risco: ' + escapeHtml(hedge.de_risk_level) + ')'
                : '') + '. ' + (hedge.rationale || '');
        document.getElementById('rec-gatilhos').innerHTML =
            (hedge.triggers || []).map(t => '<li>' + escapeHtml(t) + '</li>').join('');
    }

    const alertas = dados.alerts || [];
    if (alertas.length) {
        document.getElementById('rec-alertas-bloco').hidden = false;
        document.getElementById('rec-alertas').innerHTML = alertas.map(a =>
            '<li class="rec-alerta-' + escapeHtml(a.level || 'info') + '"><strong>' +
            escapeHtml(a.title || '') + '</strong> ' + escapeHtml(a.message || '') + '</li>'
        ).join('');
    }

    const narrativa = dados.narrative || {};
    const observar = narrativa.o_que_observar || [];
    const mudar = narrativa.o_que_me_faria_mudar_de_ideia || [];
    if (observar.length) {
        document.getElementById('rec-observar-bloco').hidden = false;
        document.getElementById('rec-observar').innerHTML =
            observar.map(t => '<li>' + escapeHtml(t) + '</li>').join('');
    }
    if (mudar.length) {
        document.getElementById('rec-mudar-bloco').hidden = false;
        document.getElementById('rec-mudar').innerHTML =
            mudar.map(t => '<li>' + escapeHtml(t) + '</li>').join('');
    }

    bloco.hidden = false;
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
    ETH: { nome: 'Ethereum', aliases: ['ETH', 'ETHEREUM'] },
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

/** Erro com sinal: positivo = previu acima do realizado (mostra viés). */
function erroAssinado(h) {
    if (h.preco_real === null || h.preco_real === undefined || !h.preco_real) return null;
    return ((h.previsao - h.preco_real) / h.preco_real) * 100;
}

function formatarNumeroCSV(n) {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return '';
    return Number(n).toFixed(2).replace('.', ',');
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

    // O erro absoluto em dólar não é comparável entre ativos: 2 mil de erro no
    // Bitcoin é 2,5%, na Cardano é 900%. Por isso a coluna de %.
    const pct = erroPercentual(h);
    const pctStr = pct === null
        ? '<span style="color:var(--text-faint)">&mdash;</span>'
        : '<span style="color:' + (pct < 2 ? 'var(--up)' : pct < 6 ? 'var(--warn)' : 'var(--down)') + '">' +
              pct.toFixed(2).replace('.', ',') + '%</span>';

    return '<tr>' +
        '<td data-label="Data">' + h.data + '</td>' +
        '<td class="moeda-cell" data-label="Moeda">' + escapeHtml(nomeMoeda(h.moeda)) + '</td>' +
        '<td data-label="Previsao">$' + h.previsao.toLocaleString('pt-BR') + '</td>' +
        '<td data-label="Real">' + realStr + '</td>' +
        '<td data-label="Intervalo 90%" style="font-size:0.75rem;color:var(--text-muted)">' + intervalo + '</td>' +
        '<td data-label="Erro">' + erroStr + '</td>' +
        '<td data-label="Erro %">' + pctStr + '</td>' +
        '<td data-label="Resultado"><span class="result-chip ' + chipClass + '">' + chipHtml + '</span></td>' +
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


/* ---------------------------------------------------------------------------
 * Gráfico de calibração
 *
 * Misturar ativos num mesmo eixo é inútil: a Cardano custa US$ 0,22 e o
 * Bitcoin US$ 80 mil, seis ordens de grandeza. Por isso o gráfico adapta:
 * com uma moeda filtrada, mostra previsto x realizado (com a reta de 45°);
 * com várias, mostra o erro relativo por dia, que é comparável entre elas.
 * ------------------------------------------------------------------------- */
const CAL = { w: 640, h: 320, top: 16, right: 18, bottom: 44, left: 62 };

function ticksLegais(min, max, count) {
    const span = max - min;
    if (!(span > 0)) return [min];
    const bruto = span / (count || 4);
    const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
    const norm = bruto / mag;
    const passo = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(min / passo) * passo; v <= max + passo * 0.001; v += passo) out.push(v);
    return out;
}

function compacto(n) {
    const a = Math.abs(n);
    if (a >= 1000) return (n / 1000).toFixed(a >= 10000 ? 0 : 1).replace('.', ',') + 'k';
    if (a >= 1) return n.toFixed(0);
    return n.toFixed(2).replace('.', ',');
}

function molduraSVG(xMin, xMax, yMin, yMax, fmtX, fmtY) {
    const esq = CAL.left, dir = CAL.w - CAL.right, topo = CAL.top, base = CAL.h - CAL.bottom;
    const px = v => esq + (v - xMin) / ((xMax - xMin) || 1) * (dir - esq);
    const py = v => base - (v - yMin) / ((yMax - yMin) || 1) * (base - topo);

    const partes = ['<svg viewBox="0 0 ' + CAL.w + ' ' + CAL.h + '" role="img" aria-label="Grafico de calibracao">'];

    for (const t of ticksLegais(yMin, yMax, 4)) {
        const y = py(t);
        partes.push('<line class="cal-grade" x1="' + esq + '" y1="' + y.toFixed(1) + '" x2="' + dir + '" y2="' + y.toFixed(1) + '"/>');
        partes.push('<text class="cal-rotulo" x="' + (esq - 8) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end">' + fmtY(t) + '</text>');
    }
    for (const t of ticksLegais(xMin, xMax, 4)) {
        const x = px(t);
        partes.push('<line class="cal-grade" x1="' + x.toFixed(1) + '" y1="' + topo + '" x2="' + x.toFixed(1) + '" y2="' + base + '"/>');
        partes.push('<text class="cal-rotulo" x="' + x.toFixed(1) + '" y="' + (base + 18) + '" text-anchor="middle">' + fmtX(t) + '</text>');
    }

    partes.push('<line class="cal-eixo" x1="' + esq + '" y1="' + topo + '" x2="' + esq + '" y2="' + base + '"/>');
    partes.push('<line class="cal-eixo" x1="' + esq + '" y1="' + base + '" x2="' + dir + '" y2="' + base + '"/>');

    return { partes, px, py, esq, dir, topo, base };
}

function corDoPonto(h) {
    if (h.acerto === null) return 'var(--text-faint)';
    return h.acerto === '\u2705' ? 'var(--up)' : 'var(--down)';
}

function rotuloPonto(h) {
    const pct = erroPercentual(h);
    return escapeHtml(
        h.data + ' | ' + nomeMoeda(h.moeda) +
        ' | previsto ' + h.previsao.toLocaleString('pt-BR') +
        ' | realizado ' + (h.preco_real === null ? 'pendente' : h.preco_real.toLocaleString('pt-BR')) +
        (pct === null ? '' : ' | erro ' + pct.toFixed(2).replace('.', ',') + '%')
    );
}

function svgPrevistoXRealizado(pontos) {
    const xs = pontos.map(h => h.previsao);
    const ys = pontos.map(h => h.preco_real);
    const min = Math.min(...xs, ...ys), max = Math.max(...xs, ...ys);
    const folga = (max - min) * 0.08 || 1;
    const g = molduraSVG(min - folga, max + folga, min - folga, max + folga, compacto, compacto);

    // reta de 45°: onde previsto == realizado
    g.partes.push('<line class="cal-ref" x1="' + g.px(min - folga).toFixed(1) + '" y1="' + g.py(min - folga).toFixed(1) +
                  '" x2="' + g.px(max + folga).toFixed(1) + '" y2="' + g.py(max + folga).toFixed(1) + '"/>');
    g.partes.push('<text class="cal-rotulo" x="' + (g.dir - 6) + '" y="' + (g.py(max + folga) + 14) + '" text-anchor="end">previsto = realizado</text>');

    for (const h of pontos) {
        g.partes.push('<circle cx="' + g.px(h.previsao).toFixed(1) + '" cy="' + g.py(h.preco_real).toFixed(1) +
                      '" r="3.4" fill="' + corDoPonto(h) + '"><title>' + rotuloPonto(h) + '</title></circle>');
    }
    g.partes.push('<text class="cal-rotulo" x="' + ((g.esq + g.dir) / 2) + '" y="' + (CAL.h - 8) + '" text-anchor="middle">previsto (US$)</text>');
    g.partes.push('</svg>');
    return g.partes.join('');
}

function svgErroPorDia(pontos) {
    const tempos = pontos.map(h => parseDataHistorico(h.data)).filter(Boolean).map(d => d.getTime());
    const erros = pontos.map(erroAssinado).filter(v => v !== null);
    if (!tempos.length || !erros.length) return '';

    const yMax = Math.max(10, Math.max(...erros.map(Math.abs)) * 1.15);
    const g = molduraSVG(Math.min(...tempos), Math.max(...tempos), -yMax, yMax,
                         t => { const d = new Date(t); return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0'); },
                         v => v.toFixed(0) + '%');

    // faixa de tolerância de 2%: dentro dela a previsão foi, na prática, acertada
    g.partes.push('<rect class="cal-faixa" x="' + g.esq + '" y="' + g.py(2).toFixed(1) +
                  '" width="' + (g.dir - g.esq) + '" height="' + (g.py(-2) - g.py(2)).toFixed(1) + '"/>');
    g.partes.push('<line class="cal-ref" x1="' + g.esq + '" y1="' + g.py(0).toFixed(1) +
                  '" x2="' + g.dir + '" y2="' + g.py(0).toFixed(1) + '"/>');

    for (const h of pontos) {
        const t = parseDataHistorico(h.data);
        const e = erroAssinado(h);
        if (!t || e === null) continue;
        g.partes.push('<circle cx="' + g.px(t.getTime()).toFixed(1) + '" cy="' + g.py(e).toFixed(1) +
                      '" r="3.2" fill="' + corDoPonto(h) + '"><title>' + rotuloPonto(h) + '</title></circle>');
    }
    g.partes.push('<text class="cal-rotulo" x="' + ((g.esq + g.dir) / 2) + '" y="' + (CAL.h - 8) + '" text-anchor="middle">dia da previsao</text>');
    g.partes.push('</svg>');
    return g.partes.join('');
}

function renderCalibracao(dados) {
    const titulo = document.getElementById('cal-titulo');
    const corpo = document.getElementById('cal-corpo');
    const nota = document.getElementById('cal-nota');
    if (!corpo) return;

    const resolvidos = dados.filter(h => h.preco_real !== null && h.preco_real !== undefined && h.previsao);

    if (resolvidos.length < 2) {
        titulo.textContent = 'Calibracao: previsto x realizado';
        corpo.innerHTML = '<p class="cal-vazio">Ainda nao ha previsoes resolvidas com esses filtros.</p>';
        nota.textContent = '';
        return;
    }

    let svg;
    if (estadoHistorico.moeda !== 'TODOS') {
        titulo.textContent = 'Previsto x realizado — ' + nomeMoeda(estadoHistorico.moeda);
        svg = svgPrevistoXRealizado(resolvidos);
    } else {
        titulo.textContent = 'Erro relativo por dia (todas as moedas)';
        svg = svgErroPorDia(resolvidos);
    }

    corpo.innerHTML = svg || '<p class="cal-vazio">Sem dados suficientes para o grafico.</p>';

    const media = resolvidos.reduce((soma, h) => soma + Math.abs(erroAssinado(h) || 0), 0) / resolvidos.length;
    const vies = resolvidos.reduce((soma, h) => soma + (erroAssinado(h) || 0), 0) / resolvidos.length;
    nota.textContent = resolvidos.length + ' pontos | erro medio ' + media.toFixed(2).replace('.', ',') +
        '% | vies ' + (vies >= 0 ? '+' : '') + vies.toFixed(2).replace('.', ',') + '%';
}

/* ---------------------------------------------------------------------------
 * Exportação CSV
 * ------------------------------------------------------------------------- */
function csvEscapar(valor) {
    const s = String(valor === null || valor === undefined ? '' : valor);
    return /[";\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function exportarCSV() {
    const dados = historicoFiltrado();
    if (!dados.length) return;

    const cabecalho = ['Data', 'Moeda', 'Previsao', 'Real', 'Intervalo minimo', 'Intervalo maximo',
                       'Erro', 'Erro %', 'Resultado'];
    const linhas = dados.map(h => [
        h.data,
        nomeMoeda(h.moeda),
        formatarNumeroCSV(h.previsao),
        formatarNumeroCSV(h.preco_real),
        formatarNumeroCSV(h.confianca_min),
        formatarNumeroCSV(h.confianca_max),
        formatarNumeroCSV(h.erro),
        formatarNumeroCSV(erroPercentual(h)),
        h.acerto === null ? 'Pendente' : (h.acerto === '\u2705' ? 'Dentro' : 'Fora'),
    ].map(csvEscapar).join(';'));

    // BOM: sem isso o Excel pt-BR quebra os acentos
    const csv = '\uFEFF' + [cabecalho.join(';')].concat(linhas).join('\r\n');

    try {
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'trendbot-historico' +
            (estadoHistorico.moeda !== 'TODOS' ? '-' + estadoHistorico.moeda.toLowerCase() : '') + '.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (err) {
        /* ambiente sem Blob/URL (jsdom, por exemplo): não derruba o painel */
    }
}

function atualizarCobertura(dados) {
    const alvo = document.getElementById('cobertura-nota');
    if (!alvo) return;

    const resolvidos = dados.filter(h => h.acerto !== null);
    if (!resolvidos.length) {
        alvo.textContent = '';
        return;
    }
    const dentro = resolvidos.filter(h => h.acerto === '\u2705').length;
    const pct = Math.round((dentro / resolvidos.length) * 100);
    alvo.textContent = 'acerto real: ' + pct + '% (' + dentro + '/' + resolvidos.length + ')';

    // o rodapé mostra o realizado (histórico inteiro), não a estimativa de 30
    // pontos do cartão: dois números parecidos sem rótulo viram confusão
    const rodape = document.getElementById('footer-cobertura');
    if (rodape) {
        rodape.textContent = '\u00b7 realizado: ' + pct + '% em ' + resolvidos.length +
                             ' previs\u00f5es conferidas';
    }
}

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

    // Gráfico e cobertura acompanham os filtros, mas usam o conjunto filtrado
    // inteiro — não só a página exibida.
    renderCalibracao(dados);
    atualizarCobertura(dados);

    const btnCsv = document.getElementById('btn-csv');
    if (btnCsv) btnCsv.disabled = total === 0;

    if (!total) {
        tbody.innerHTML = '<tr><td colspan="8" class="loading-cell">Nenhum registro encontrado com esses filtros.</td></tr>';
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

    const btnCsv = document.getElementById('btn-csv');
    if (btnCsv) btnCsv.addEventListener('click', exportarCSV);
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
        renderModelCard(data);
        renderSummary(data, historico);
        renderCards(data, historico);
        renderFiltros(historico);
        ligarControles();
        renderHistoricoTabela();

        // separado de propósito: antes da primeira execução que gere o arquivo,
        // o 404 aqui não pode derrubar o resto do painel
        try {
            const res = await fetch('./recomendacao.json');
            if (res.ok) renderRecomendacao(await res.json(), data);
        } catch (e) {
            console.warn('recomendacao.json indisponível:', e.message);
        }

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
