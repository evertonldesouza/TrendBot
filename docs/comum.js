/* Núcleo compartilhado pelos dois modos do painel TrendBot.
 *
 * Este arquivo vive em docs/ porque o GitHub Pages serve o branch sem build:
 * para ser público, o arquivo precisa estar fisicamente aqui. A API também o
 * serve (montado em /comum), então existe UMA implementação e não duas.
 *
 * Antes existiam dois painéis independentes — app/static/ e docs/ — cada um
 * com sua cópia de formatação e do leque de projeção. Nada os mantinha em
 * sincronia: consertar num não chegava no outro.
 *
 * Carrega como script clássico (sem módulos) para valer nos dois contextos.
 */
(function (global) {
    'use strict';

    /* ------------------------------------------------------- catálogo ---- */

    const MOEDAS_CANONICAS = {
        BTC: { nome: 'Bitcoin', aliases: ['BTC', 'BITCOIN'] },
        ETH: { nome: 'Ethereum', aliases: ['ETH', 'ETHEREUM'] },
        SOL: { nome: 'Solana', aliases: ['SOL', 'SOLANA'] },
        ADA: { nome: 'Cardano', aliases: ['ADA', 'CARDANO'] },
        /* USD é a rubrica de caixa. USDT fica de fora de propósito: no
           catálogo do Python ele é categoria 'cripto', uma posição como
           qualquer outra — alias para USD o transformaria em dinheiro parado
           e faria o painel discordar do motor. */
        USD: { nome: 'Caixa (USD)', aliases: ['USD'] },
    };

    /* 10 cores: o painel interativo mostra até 8 ativos + benchmark no donut,
       então uma paleta de 6 repetiria cor. O público usa no máximo 4. */
    const CORES = ['#58a6ff', '#a78bfa', '#2dd4bf', '#e3b341', '#3fb950',
                   '#f778ba', '#79c0ff', '#d29922', '#f85149', '#7ee787'];
    const COR_CAIXA = '#4d5563';

    const _ALIAS_PARA_CANONICA = (function () {
        const mapa = {};
        Object.keys(MOEDAS_CANONICAS).forEach(function (canonica) {
            MOEDAS_CANONICAS[canonica].aliases.forEach(function (apelido) {
                mapa[apelido] = canonica;
            });
        });
        return mapa;
    })();

    function moedaCanonica(moeda) {
        const chave = String(moeda === null || moeda === undefined ? '' : moeda)
            .trim().toUpperCase();
        return _ALIAS_PARA_CANONICA[chave] || chave;
    }

    function nomeMoeda(moeda) {
        const canonica = moedaCanonica(moeda);
        return MOEDAS_CANONICAS[canonica] ? MOEDAS_CANONICAS[canonica].nome : canonica;
    }

    function corDe(simbolo, i) {
        return simbolo === 'USD' ? COR_CAIXA : CORES[i % CORES.length];
    }

    /* ----------------------------------------------------- formatação ---- */

    function pct(v, d) {
        const n = Number(v) || 0;
        return (n * 100).toFixed(d === undefined ? 1 : d).replace('.', ',') + '%';
    }

    function pctComSinal(v, d) {
        const n = Number(v) || 0;
        return (n > 0 ? '+' : '') + pct(n, d);
    }

    function money(v) {
        const n = Number(v) || 0;
        return (n < 0 ? '-US$ ' : 'US$ ') +
            Math.abs(n).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
    }

    function price(v) {
        const n = Number(v) || 0;
        const casas = n >= 1000 ? 0 : n >= 10 ? 2 : n >= 1 ? 3 : 5;
        return 'US$ ' + n.toLocaleString('pt-BR', {
            minimumFractionDigits: casas, maximumFractionDigits: casas,
        });
    }

    /* Usado em rótulos de eixo e no fim do leque, onde espaço é curto. */
    function precoCurto(v) {
        const n = Number(v) || 0;
        if (Math.abs(n) >= 1000) {
            return (n / 1000).toFixed(1).replace('.', ',') + 'k';
        }
        if (Math.abs(n) >= 1) return n.toFixed(0);
        return n.toFixed(3);
    }

    /* --------------------------------------------------------- leque ----- */

    /**
     * Histórico + leque de projeção em SVG. Uma implementação, dois modos.
     *
     * opcoes = {
     *   precos:    number[]            série histórica de fechamento
     *   mediana:   number|null         retorno mediano no horizonte (0.02 = +2%)
     *   faixas:    [{inferior, superior, opacidade}]  ordenadas da mais larga
     *   horizonte: number              dias projetados
     *   altura:    number              altura em px do viewBox
     *   rotulo:    string              texto do aria-label
     * }
     *
     * Devolve '' se não há série suficiente — nunca quebra o card.
     */
    function leque(opcoes) {
        const precos = (opcoes.precos || []).map(Number).filter(function (v) {
            return isFinite(v);
        });
        if (precos.length < 2) return '';

        const faixas = opcoes.faixas || [];
        const mediana = opcoes.mediana;
        const horizonte = Number(opcoes.horizonte) || 30;
        const W = 360, H = Number(opcoes.altura) || 132;
        const L = 6, R = 44, T = 8, B = 16;
        const iw = W - L - R, ih = H - T - B;

        const ultimo = precos[precos.length - 1];
        let lo = Math.min.apply(null, precos);
        let hi = Math.max.apply(null, precos);
        faixas.forEach(function (f) {
            lo = Math.min(lo, ultimo * (1 + Number(f.inferior)));
            hi = Math.max(hi, ultimo * (1 + Number(f.superior)));
        });
        if (mediana !== null && isFinite(mediana)) {
            const fim = ultimo * (1 + mediana);
            lo = Math.min(lo, fim);
            hi = Math.max(hi, fim);
        }
        if (hi - lo < 1e-9) hi = lo + 1;
        const margem = (hi - lo) * 0.06;
        lo -= margem; hi += margem;

        const xMax = (precos.length - 1) + horizonte;
        const px = function (i) { return L + (i / xMax) * iw; };
        const py = function (v) { return T + (1 - (v - lo) / (hi - lo)) * ih; };

        const p = [];
        p.push('<svg class="leque" viewBox="0 0 ' + W + ' ' + H +
               '" preserveAspectRatio="none" role="img"');
        p.push(' aria-label="' + (opcoes.rotulo || 'Histórico e projeção') + '">');

        faixas.forEach(function (f) {
            const a = ultimo * (1 + Number(f.superior));
            const b = ultimo * (1 + Number(f.inferior));
            p.push('<polygon class="leque-faixa" opacity="' + f.opacidade + '" points="' +
                px(precos.length - 1).toFixed(1) + ',' + py(ultimo).toFixed(1) + ' ' +
                px(xMax).toFixed(1) + ',' + py(a).toFixed(1) + ' ' +
                px(xMax).toFixed(1) + ',' + py(b).toFixed(1) + '"/>');
        });

        p.push('<polyline class="leque-preco" points="' +
            precos.map(function (v, i) {
                return px(i).toFixed(1) + ',' + py(v).toFixed(1);
            }).join(' ') + '"/>');

        if (mediana !== null && isFinite(mediana)) {
            const fim = ultimo * (1 + mediana);
            const x0 = px(precos.length - 1).toFixed(1), y0 = py(ultimo).toFixed(1);
            const x1 = px(xMax).toFixed(1), y1 = py(fim).toFixed(1);
            p.push('<line class="leque-mediana" x1="' + x0 + '" y1="' + y0 +
                   '" x2="' + x1 + '" y2="' + y1 + '"/>');
            p.push('<circle class="leque-fim" cx="' + x1 + '" cy="' + y1 + '" r="2.6"/>');
            p.push('<text class="leque-valor" x="' + (px(xMax) + 4).toFixed(1) +
                   '" y="' + (py(fim) + 3).toFixed(1) + '">' + precoCurto(fim) + '</text>');
        }
        p.push('</svg>');
        return p.join('');
    }

    /* ------------------------------------------------------ exporta ------ */

    global.TB = {
        MOEDAS_CANONICAS: MOEDAS_CANONICAS,
        CORES: CORES,
        COR_CAIXA: COR_CAIXA,
        moedaCanonica: moedaCanonica,
        nomeMoeda: nomeMoeda,
        corDe: corDe,
        pct: pct,
        pctComSinal: pctComSinal,
        money: money,
        price: price,
        precoCurto: precoCurto,
        leque: leque,
    };
})(window);
