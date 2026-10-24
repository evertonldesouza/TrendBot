/**
 * Validação do painel (docs/index.html + docs/script.js).
 *
 * Roda com `node tests/painel/check.mjs`, depois de `npm install`.
 *
 * Três checagens, em ordem de custo:
 *
 *   1. sintaxe — pega o arquivo que nem chega a ser executado;
 *   2. função definida e nunca chamada — já aconteceu duas vezes: a função
 *      existia, passava por revisão e não era ligada a lugar nenhum. No
 *      navegador isso não dá erro nenhum, simplesmente não roda;
 *   3. renderização de verdade — sobe o DOM com os dados publicados e confere
 *      que o painel desenhou. É o que pega o botão que aponta para um arquivo
 *      que não existe mais e o gráfico que sai vazio.
 */

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const ler = (p) => fs.readFileSync(path.join(RAIZ, p), 'utf8');

let falhas = 0;
const falhar = (msg) => { console.error('  FALHA  ' + msg); falhas++; };
const ok = (msg) => console.log('  ok     ' + msg);

/* -- 1. sintaxe ---------------------------------------------------------- */
console.log('sintaxe');
const js = ler('docs/script.js');
try {
    new vm.Script(js, { filename: 'docs/script.js' });
    ok('docs/script.js compila');
} catch (e) {
    falhar(`docs/script.js não compila: ${e.message}`);
    process.exit(1);
}

/* -- 2. função definida e nunca chamada ---------------------------------- */
console.log('\nfunções órfãs');
const html = ler('docs/index.html');
const corpoBusca = `${js}\n${html}`;
const escapa = (s) => s.replace(/\$/g, '\\$');
// token inteiro: evita que `renderCards` conte como uso de `render`
const contar = (nome) =>
    (corpoBusca.match(new RegExp(`(^|[^\\w$])${escapa(nome)}(?![\\w$])`, 'g')) || []).length;

const definidas = [...js.matchAll(/^function\s+([A-Za-z_$][\w$]*)\s*\(/gm)].map((m) => m[1]);
const orfas = definidas.filter((nome) => contar(nome) < 2);
if (orfas.length) {
    orfas.forEach((n) => falhar(`function ${n}() está definida e nunca é chamada`));
} else {
    ok(`${definidas.length} funções, todas chamadas`);
}

/* -- 3. renderização ----------------------------------------------------- */
console.log('\nrenderização');
const data = JSON.parse(ler('docs/data.json'));
const historico = JSON.parse(ler('docs/historico.json'));
let recomendacao = null;
try {
    recomendacao = JSON.parse(ler('docs/recomendacao.json'));
} catch {
    // ausente até a primeira execução publicar; o painel tem de aguentar
}

// O data.json publicado pode ser anterior ao campo `graficos`, que só aparece
// na próxima execução do motor. Aí o painel degrada sem quebrar (e é assim que
// tem de ser), mas este check perderia justamente o caminho do gráfico. Usa uma
// série sintética para exercitar o desenho: o que se quer checar aqui é o
// painel, não o dado.
const serieReal = Boolean(data.graficos);
if (!serieReal) {
    const n = 120;
    const fechamento = Array.from({ length: n }, (_, i) =>
        Number((100 * (1 + 0.15 * Math.sin(i / 9) + i * 0.001)).toFixed(2)));
    const datas = Array.from({ length: n }, (_, i) => {
        const d = new Date(Date.UTC(2026, 0, 1) + i * 86400000);
        return d.toISOString().slice(0, 10);
    });
    data.graficos = Object.fromEntries(data.ativos.map((a) => [a.moeda, {
        datas,
        fechamento,
        projecao: {
            horizonte: 30,
            mediana: 0.02,
            quantis: { p5: -0.12, p10: -0.08, p25: -0.03, p75: 0.05, p90: 0.09, p95: 0.15 },
        },
    }]));
}

const dom = new JSDOM(html, { runScripts: 'dangerously', url: 'https://trendbot.test/' });
const { window } = dom;
const chamadas = [];
window.fetch = (url) => {
    const nome = String(url).replace(/^\.\//, '');
    chamadas.push(nome);
    const mapa = { 'data.json': data, 'historico.json': historico };
    if (nome === 'recomendacao.json') {
        return recomendacao
            ? Promise.resolve({ ok: true, json: () => Promise.resolve(recomendacao) })
            : Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error('404')) });
    }
    if (nome in mapa) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mapa[nome]) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.reject(new Error('404')) });
};

const erroConsole = [];
window.addEventListener('error', (e) => erroConsole.push(e.message));

const tag = window.document.createElement('script');
tag.textContent = js;
window.document.body.appendChild(tag);

// DOMContentLoaded já passou quando o script é injetado, então init() é
// chamado à mão. Como é async, o await aqui espera o painel terminar.
await window.eval('init()');

const doc = window.document;
const grid = doc.getElementById('dashboard-grid');
if (!grid) falhar('não existe #dashboard-grid');

const erroVisivel = grid && grid.querySelector('[role="alert"]');
if (erroVisivel) falhar(`o painel mostrou estado de erro: ${erroVisivel.textContent.trim()}`);

// cards: um por ativo publicado
const cards = doc.querySelectorAll('#dashboard-grid .card');
const esperados = data.ativos.length;
if (cards.length !== esperados) {
    falhar(`renderizou ${cards.length} cards, esperado ${esperados}`);
} else {
    ok(`${cards.length} cards renderizados`);
}

// gráfico em cada card
const svgs = doc.querySelectorAll('#dashboard-grid .card .leque');
if (svgs.length !== esperados) {
    falhar(`${svgs.length} gráficos de ${esperados} cards`);
} else {
    const vazios = [...svgs].filter((s) => !s.querySelector('.leque-preco')).length;
    if (vazios) falhar(`${vazios} gráfico(s) sem a linha de preço`);
    else ok(serieReal
        ? `${svgs.length} gráficos com a série publicada`
        : `${svgs.length} gráficos com série sintética (data.json antigo)`);
}

// nenhum link quebrado para arquivo que não é publicado
const quebrados = [...doc.querySelectorAll('[href]')]
    .map((a) => a.getAttribute('href'))
    .filter((h) => /\.(png|jpe?g)$/i.test(h));
if (quebrados.length) falhar(`o painel aponta para imagem não publicada: ${quebrados.join(', ')}`);
else ok('nenhum link para imagem não publicada');

// cartão do modelo: o projeto se propõe a mostrar as próprias limitações
const veredito = doc.getElementById('mc-verdict');
if (!veredito || !veredito.textContent.trim()) {
    falhar('o veredito do modelo não foi preenchido');
} else {
    ok(`veredito do modelo: "${veredito.textContent.trim().slice(0, 60)}"`);
}

if (erroConsole.length) falhar(`erro de JS em runtime: ${erroConsole.join('; ')}`);

console.log(falhas === 0 ? '\nOK: painel íntegro' : `\n${falhas} falha(s)`);
process.exit(falhas === 0 ? 0 : 1);
