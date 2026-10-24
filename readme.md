# TrendBot · Orientador Quantitativo de Investimentos

> **De "previsor de preço" para "gestor de risco".**
> O TrendBot não tenta adivinhar o preço de amanhã. Ele dimensiona risco,
> limita concentração, mantém colchão de caixa e **prova o que afirma** com
> validação fora da amostra e backtest com custos.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)](https://fastapi.tiangolo.com/)
[![Testes](https://img.shields.io/badge/testes-39%20passando-brightgreen)](#testes)
[![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-green)](LICENSE)

---

## Sumário

- [A tese](#a-tese)
- [O que ele faz](#o-que-ele-faz)
- [Demonstração rápida](#demonstração-rápida)
- [Arquitetura](#arquitetura)
- [O motor de previsão](#o-motor-de-previsão)
- [O motor de risco](#o-motor-de-risco)
- [A recomendação](#a-recomendação)
- [Backtest](#backtest)
- [Perfis de risco](#perfis-de-risco)
- [Fontes de dados](#fontes-de-dados)
- [API](#api)
- [Instalação](#instalação)
- [Testes](#testes)
- [Automação (GitHub Actions)](#automação-github-actions)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Limitações e honestidade](#limitações-e-honestidade)
- [Licença e autor](#licença-e-autor)

---

## A tese

A versão 1 do TrendBot previa o preço de 4 criptos para as próximas 24h com
Prophet e mandava um e-mail com o sinal de compra ou venda. Funcionava, e a
engenharia era boa — mas a premissa era frágil: **retorno de cripto no curto
prazo é quase imprevisível**, e um sistema que se vende como "sinal" herda essa
fragilidade.

A versão 2 inverte a pergunta:

| | TrendBot v1 | TrendBot v2 |
|---|---|---|
| Pergunta central | "O preço vai subir amanhã?" | "Quanto risco cabe no seu perfil?" |
| Unidade de decisão | sinal de compra/venda | **orçamento de risco + alocação** |
| Papel do caixa | nenhum | **colchão dimensionado por volatilidade** |
| Validação | acerto do intervalo de 90% | habilidade fora da amostra, cobertura, Sharpe, drawdown |
| Postura | "confie no modelo" | **"se o modelo não tem vantagem, ele se desliga"** |
| Escala | 4 ativos fixos | universo configurável de 18 ativos |
| Interface | dashboard estático + e-mail | **painel interativo + API + CLI** |

O resultado é um orientador que você pode realmente seguir: ele diz o que
fazer, **por quê**, quanto custa em risco, e **o que o faria mudar de ideia**.

---

## O que ele faz

1. **Coleta** preços de 18 criptoativos (Binance OU CoinGecko, com cache,
   retentativas e fallback automático para CSV local ou simulação).
2. **Prevê distribuições** de retorno para 1, 7 e 30 dias — não um número único:
   mediana, faixa de 5–95%, probabilidade de alta, VaR e CVaR.
3. **Mede a própria competência** em validação walk-forward e desliga as
   previsões quando não há vantagem estatística.
4. **Dimensiona o risco**: calcula a exposição que faz a carteira atingir a
   volatilidade alvo do seu perfil, com teto de concentração por ativo.
5. **Distribui** esse orçamento entre ativos por paridade de risco, com
   inclinação limitada por convicção e penalidades por ativo estressado.
6. **Monta as ordens** só quando o desvio passa da banda de rebalanceamento, e
   mostra quanto comprar/vender em dólar.
7. **Direciona aportes** primeiro para o que está abaixo do alvo — rebalanceia
   sem vender nada.
8. **Estressa a carteira** em quatro cenários (inverno cripto, correção forte,
   choque de liquidez, alta forte).
9. **Compara com alternativas** em backtest com custos de 0,30% por giro.
10. **Explica tudo** em português, incluindo o que invalidaria a recomendação.

---

## Demonstração rápida

```bash
git clone https://github.com/evertonldesouza/TrendBot.git
cd TrendBot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# relatório completo no terminal + JSON + gráficos
python -m trendbot.cli --perfil moderado --capital 25000 --aporte 1000 \
    --carteira "BTC:12000,ETH:5000,SOL:3000,USD:5000"

# painel interativo em http://localhost:8000
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Saída real do CLI (dados simulados, perfil Moderado):

```
  Exposição recomendada a cripto: 49% do patrimônio (BTC 16%, ETH 14%, ADA 11%), com 51% em caixa.

  ALOCAÇÃO RECOMENDADA
    USD     50.8%  (hoje  20.0%)  ↑ ████████████████████
    BTC     16.4%  (hoje  48.0%)  ↓ ███████
    ETH     13.6%  (hoje  20.0%)  ↓ █████
    ADA     10.5%  (hoje   0.0%)  ↑ ████
    SOL      8.7%  (hoje  12.0%)  ↓ ███

  ORDENS
    [1] VENDER         BTC       -7,901.38 USD   Acima do alvo (48% → 16%): reduzir concentração.
    [2] AUMENTAR CAIXA USD       +7,692.13 USD   Colchão de segurança: reduz a volatilidade…
    [2] COMPRAR        ADA       +2,637.80 USD   Abaixo do alvo (0% → 11%).

  RISCO DA CARTEIRA RECOMENDADA
    Volatilidade anualizada :  40.2%   (alvo do perfil 40%)
    VaR 95% (1 dia)         :   2.09%
    Pior queda no histórico :  23.2%
    Sharpe                  :   0.90

  MODELO (honestidade)
    Modelo sem habilidade fora da amostra neste recorte.
      · Previsões praticamente desligadas; a recomendação é guiada por risco e disciplina.
```

Reparou no melhor detalhe? **O sistema admite que o modelo não tem vantagem** e
mesmo assim entrega uma recomendação coerente — porque ela não depende da
previsão. É isso que o torna utilizável.

---

## Arquitetura

```
                        ┌──────────────────────────────┐
                        │   FONTES DE DADOS            │
                        │  Binance · CoinGecko · CSV   │
                        │  · simulação determinística  │
                        └───────────────┬──────────────┘
                                        ▼
                        ┌──────────────────────────────┐
                        │  trendbot.data               │
                        │  cache, fallback, metadados  │
                        └───────────────┬──────────────┘
                                        ▼
     ┌──────────────────────────────────┴──────────────────────────────┐
     ▼                                                                 ▼
┌─────────────────────┐                                   ┌─────────────────────┐
│ trendbot.forecast   │                                   │ trendbot.risk       │
│ features → ridge    │                                   │ covariância EWMA +  │
│ walk-forward        │                                   │ shrinkage, VaR/CVaR │
│ habilidade → peso   │                                   │ paridade de risco,  │
│ quantis de erro     │                                   │ estresse, drawdown  │
└──────────┬──────────┘                                   └──────────┬──────────┘
           │  distribuições calibradas                               │  métricas
           └────────────────────────┬────────────────────────────────┘
                                    ▼
                        ┌──────────────────────────────┐
                        │  trendbot.advisor            │
                        │  orçamento de risco → pesos  │
                        │  → caixa → ordens → alertas  │
                        │  → narrativa explicável      │
                        └───────────────┬──────────────┘
                                        ▼
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
   ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────────┐
   │ trendbot.cli     │   │ app.main (FastAPI)   │   │ trendbot.report  │
   │ terminal + JSON  │   │ API + painel web     │   │ gráficos PNG     │
   └──────────────────┘   └──────────────────────┘   └──────────────────┘
                                                      ┌──────────────────┐
                                                      │ trendbot.backtest│
                                                      └──────────────────┘
```

Todas as camadas são funções puras sobre `DataFrame`/`dict`. Nenhuma delas
"puxa" a outra: o fluxo é explícito, o que torna cada parte testável isoladamente.

---

## O motor de previsão

**Por que saímos do Prophet?** Prophet é ótimo para séries com sazonalidade
forte (vendas, tráfego). Em cripto, o que importa é: incerteza que muda com o
regime de volatilidade, caudas gordas e quase nenhuma previsibilidade de nível.
O modelo novo ataca exatamente isso.

### Pipeline

1. **16 features**, todas calculadas só com informação disponível no dia:
   momentum normalizado por volatilidade (7/30/90/180d), reversão de 5 dias,
   RSI, nível e z-score de volatilidade, razão vol curta/longa, drawdown,
   posição na faixa de 90 dias, distância das médias de 50 e 200 dias, MACD
   normalizado, ATR%, flag de tendência.
2. **Ridge regularizado**, com `alpha` escolhido por validação interna (holdout
   dos últimos 20% da janela de treino). Sem regularização forte, o modelo
   decora o passado — é o erro clássico em séries financeiras.
3. **Validação walk-forward** em janela expansiva: treina com tudo até `t`,
   prevê `t → t+h`, anda. Passo de `h/3` dias (sobreposição controlada).
4. **Habilidade fora da amostra**: `skill = 1 − MSE_modelo / MSE_ingênuo`, onde
   o ingênuo é a deriva histórica. É a pergunta certa: *"meu modelo ganha de um
   chute bem informado?"*
5. **Peso do modelo**: `w = clip(skill, 0, 0.70) × min(1, n/120)`.
   Habilidade negativa → peso zero → **previsão desligada**.
6. **Incerteza vem dos erros reais**, não de uma curva gaussiana: cada erro
   fora da amostra é padronizado pela volatilidade **realizada** no período e,
   na hora de prever, reescalado pela volatilidade **esperada** para o
   horizonte — que reverte à média (projetar a vol de hoje por 30 dias
   superestima muito).
7. **Cobertura honesta**: para cada ponto de teste, o intervalo é montado só
   com os erros **anteriores** e a vol prevista **naquele** momento. Nunca com o
   erro do próprio ponto (isso daria 90% de cobertura por construção e não
   provaria nada).

### O que ele entrega por ativo

| Saída | Significado |
|---|---|
| `median_return` | retorno mediano esperado no horizonte |
| `lower` / `upper` | faixa de 90% (quantis 5% e 95%) |
| `prob_up` | probabilidade de retorno positivo |
| `var95` / `cvar95` | perda no pior 5% / perda média nesse pior 5% |
| `model_weight` | quanto o modelo está sendo ouvido (0 = desligado) |
| `conviction` | inclinação da distribuição, escala −1…+1, já descontada pelo peso |
| `drivers` | os "porquês" legíveis: RSI, tendência, volatilidade, drawdown |
| `regime` | risco-ligado / neutro / risco-desligado |

### Prova de que o detector de habilidade funciona

Levantamos duas séries sintéticas idênticas em tudo, menos em uma coisa: uma
tem um fator de tendência lento e previsível, a outra é ruído puro.

| Série | Habilidade (skill) | Peso do modelo |
|---|---|---|
| Com momentum real | **+0,094** | 0,08 |
| Ruído puro | **−0,114** | **0,00** |

Ele liga quando há sinal e se desliga quando não há. Isso está coberto por
teste (`tests/test_trendbot.py::test_modelo_confia_mais_quando_ha_sinal_do_que_no_ruido`).

---

## O motor de risco

### Estimativa

- **365 dias/ano** — cripto negocia todo dia.
- **Covariância EWMA** (meia-vida de 180 dias, janela de até 2 anos).
- **Contração para correlação constante** (estilo Ledoit-Wolf, intensidade
  0,25): matrizes amostrais de cripto são ruidosas e geram alocações absurdas.
  Em estresse as correlações sobem juntas — contrair para a média é uma forma
  barata de não confiar demais na amostra.

### Métricas

Volatilidade, volatilidade de queda, VaR 95% e 99% (histórico sobre 365 dias e
paramétrico lado a lado — quando divergem, é cauda gorda), CVaR 95%, pior
queda, queda atual, Sharpe, Sortino, Calmar, beta contra o benchmark, HHI de
concentração, índice de diversificação e **contribuição marginal ao risco por
ativo**.

> **Detalhe que importa:** caixa não é renormalizado. Se você tem 50% em caixa,
> o risco medido cai pela metade. Renormalizar faria o colchão desaparecer das
> métricas — o erro clássico de quem acha que está protegido e não está.
> Há teste para isso.

### Estresse

| Cenário | Choque no benchmark | Correlação alvo |
|---|---|---|
| Inverno cripto | −60% | 0,95 |
| Correção forte | −35% | 0,90 |
| Choque de liquidez | −22% em 1 dia | 0,98 |
| Alta forte | +45% | 0,80 |

---

## A recomendação

O fluxo de decisão, nessa ordem:

**1. Orçamento de risco.** A exposição não começa em "quantos % em cripto", e
sim na pergunta *"qual risco cabe no seu perfil?"*:

```
exposição_base = vol_alvo_do_perfil / vol_da_cesta_de_risco
exposição      = exposição_base × (1 + 0,30 × convicção) × (1 − 0,25 × pressão_de_crise)
exposição      = min(exposição, vol_máxima_do_perfil / vol_da_cesta)
```

Isso faz a carteira **acertar o alvo de volatilidade do perfil** em vez de
chutar um número fixo. Nos testes, os quatro perfis batem 19–22%, 35–40% e
53–61% contra alvos de 22%, 40% e 60%.

**2. Distribuição entre ativos.** Base = paridade de risco (não depende de
previsão de retorno). Em cima dela:

- inclinação por convicção, limitada a ±30%;
- penalidade por ativo: volatilidade 2 desvios acima do normal (−30%), drawdown
  abaixo de −35% (−8%) ou −60% (−20%), RSI acima de 78 (−10%), regime
  desligado (−10%) / ligado (+8%);
- teto de concentração por ativo, com redistribuição iterativa do excesso;
- piso de 2%: posição irrelevante só atrapalha a execução.

**3. Colchão de caixa.** `1 − exposição`, com piso no mínimo do perfil. Ele é
dimensionado pela volatilidade, e é a razão pela qual a carteira aguenta o
inverno sem você vender no fundo.

**4. Ordens.** Só executa o que sair da banda de rebalanceamento (6% a 12%,
conforme o perfil). Cada ordem vem com prioridade, valor em dólar e motivo.

**5. Aportes.** O dinheiro novo vai primeiro para o que está mais abaixo do
alvo. Rebalanceia sem vender, sem spread e sem imposto.

**6. Alertas.** Concentração no limite, volatilidade extrema, queda profunda,
intervalos subestimando o risco, rebalanceamento grande demais para executar de
uma vez.

**7. Narrativa.** Cabeçalho, pontos principais, o que observar e — a parte mais
importante — **o que me faria mudar de ideia**.

---

## Backtest

Quatro abordagens no mesmo histórico, com custo de 0,30% por giro:

| Estratégia | O que é |
|---|---|
| **TrendBot** | alvo de volatilidade + paridade de risco, rebalanceada a cada 30 dias |
| Comprar e segurar (1/N) | o que a maioria das pessoas faz |
| Só `<ativo>` | o custo da falta de diversificação |
| 60/40 | referência de quem vem do mercado tradicional |

Regras anti-autoengano: só usa dados até a data da decisão; a covariância é
reestimada a cada rebalanceamento; custos são descontados sobre o valor girado.

Exemplo real (dados simulados, perfil Moderado, 3,5 anos):

| Estratégia | Resultado | CAGR | Vol | Sharpe | Pior queda |
|---|---|---|---|---|---|
| **TrendBot (Moderado)** | US$ 28.748 | +35,8% | 37% | **0,86** | **−33%** |
| Comprar e segurar (1/N) | US$ 23.691 | +24,2% | 70% | 0,28 | −63% |
| Só BTC | US$ 36.512 | +38,4% | 61% | 0,56 | −52% |
| Só DOGE | US$ 4.980 | −15,9% | 100% | −0,20 | −81% |

O veredito é **gerado a partir dos números**: se a carteira orientada perder em
retorno, o relatório diz isso e mostra onde ela ganhou (controle de queda).

---

## Perfis de risco

| Perfil | Vol alvo (a.a.) | Teto de vol | Queda tolerada | Exposição em cripto | Caixa mínimo | Teto por ativo | Banda de rebalanceamento |
|---|---|---|---|---|---|---|---|
| Conservador | 22% | 32% | 20% | 15% – 45% | 35% | 25% | 6% |
| Moderado | 40% | 55% | 35% | 35% – 70% | 15% | 35% | 8% |
| Arrojado | 60% | 80% | 50% | 55% – 90% | 5% | 45% | 10% |
| Agressivo | 85% | 120% | 65% | 75% – 100% | 0% | 60% | 12% |

Configurável por `PERFIL_RISCO` no `.env` ou no painel.

---

## Fontes de dados

Ordem de preferência em modo `auto`:

1. **Cache fresco** em `.cache/trendbot/` (menos de 1 dia).
2. **Binance** (`/api/v3/klines`) — OHLCV diário completo, melhor qualidade.
3. **CoinGecko** (`/market_chart`) — fallback por ativo.
4. **CSV local** (`data/prices.csv`) — para dados proprietários.
5. **Simulação determinística** — usada em demo, testes e quando não há rede.

### Limites da API pública da CoinGecko

A API **pública e gratuita** da CoinGecko tem duas restrições que importam aqui:

| Restrição | Consequência | O que o código faz |
| --- | --- | --- |
| Histórico máximo de **365 dias** | pedir 1095 dias devolve HTTP 401 (`error_code 10012`, *exceeds the allowed time range*) | corta o pedido em 365 e avisa no log |
| Parâmetro `interval` é de plano pago | responder 4xx derruba a busca inteira | nunca envia `interval` |

Para usar o histórico completo, defina `COINGECKO_API_KEY` (chave demo ou pro)
como secret/variável de ambiente; o pedido original é então preservado e a
chave é enviada como `x_cg_demo_api_key`.

A Binance costuma responder **HTTP 451** (*Service unavailable from a
restricted location*) a partir de IPs de datacenter — inclusive os do GitHub
Actions. Isso é esperado: o `auto` cai para a CoinGecko sem alarde.

Se todos os provedores falharem, o relatório cai na simulação — e **isso é
declarado**: `data.json` expõe `fonte.simulada` com o motivo em
`fonte.detalhes`, e o dashboard mostra um aviso vermelho no topo. nunca
confie num número deste projeto sem conferir a faixa de fonte.

A simulação não é aleatória "de mentira": é um modelo de **fator de mercado com
regimes** (calmo / normal / estresse, cadeia de Markov), retornos com caudas
gordas (t-Student), saltos, volatilidade agrupada (GARCH-like), ciclo de longo
prazo e reversão à média em log — calibrada para reproduzir volatilidades de
60% a 120% a.a. e correlações de 0,6 a 0,9, típicas de cripto.

**Sempre que os dados forem simulados, o sistema avisa** no painel, no JSON e
no terminal. Você nunca confunde demo com mercado real.

Formato de `data/prices.csv`:

```csv
Data,BTC,ETH,SOL
2024-01-01,42000.0,2200.0,95.0
2024-01-02,43100.5,2255.1,97.3
```

---

## API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

| Endpoint | Descrição |
|---|---|
| `GET /` | painel interativo |
| `GET /api/health` | status do serviço |
| `GET /api/opcoes` | catálogo de ativos e perfis |
| `GET /api/relatorio` | relatório completo (querystring) |
| `POST /api/relatorio` | relatório completo (JSON) |
| `GET /docs` | documentação OpenAPI automática |

Exemplo:

```bash
curl "localhost:8000/api/relatorio?perfil=moderado&ativos=bitcoin,ethereum\
&capital=25000&aporte=1000&carteira=BTC:12000,ETH:5000,USD:5000"
```

Parâmetros: `perfil`, `ativos`, `dias`, `fonte`, `capital`, `aporte`,
`carteira` (`BTC:12000,USD:5000`), `backtest`.

Respostas ficam em cache por 10 minutos (chave = hash dos parâmetros).

No startup, um thread de **aquecimento** já monta o relatório-padrão em
segundo plano: a sondagem de rede, as previsões e o backtest acontecem antes do
primeiro acesso, então a tela inicial responde em ~10 ms. O estado aparece em
`GET /api/health`:

```json
{"status": "ok", "versao": "2.0.0", "cache_itens": 1,
 "aquecimento": {"status": "pronto", "erro": null, "duracao_s": 1.24}}
```

Os defaults da API (`PADRAO_ATIVOS`, `PADRAO_POSICOES`, `PADRAO_CAIXA` em
`app/main.py`) replicam os do painel (`state` em `app/static/app.js`). Há um
teste que falha se os dois divergirem — sem isso a tela inicial perderia o
cache e pagaria o custo cheio de novo.

---

## Instalação

**Pré-requisitos:** Python 3.10+.

```bash
git clone https://github.com/evertonldesouza/TrendBot.git
cd TrendBot
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### CLI

```bash
python -m trendbot.cli --perfil moderado \
    --capital 25000 --aporte 1000 \
    --carteira "BTC:12000,ETH:5000,USD:5000" \
    --ativos bitcoin,ethereum,solana,cardano
```

Opções: `--perfil`, `--capital`, `--aporte`, `--ativos`, `--dias`, `--fonte`,
`--carteira`, `--out`, `--sem-backtest`, `--sem-graficos`, `--json`, `-v`.

Gera em `out/`: `relatorio.json`, `alocacao.png`, `risco.png`, `backtest.png` e
`projecao_<ATIVO>.png`.

### Painel web

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Deploy (Docker)

A API tem um `Dockerfile` na raiz. É o caminho mais curto para pôr o serviço no
ar em qualquer lugar que rode contêiner (Render, Railway, Fly.io, Cloud Run):

```bash
docker build -t trendbot .
docker run --rm -p 8000:8000 -e FONTE_DADOS=auto trendbot
curl localhost:8000/api/health
```

Algumas decisões do `Dockerfile`:

- **Sem segredo nenhum na imagem.** O único opcional é `COINGECKO_API_KEY`, que
  entra por variável de ambiente em tempo de execução — nunca no build.
- **`MPLBACKEND=Agg`.** Os gráficos rodam sem tela; numa imagem enxuta, sem
  isso o matplotlib procura um display que não existe.
- **`PORT` é lido pela app**, então plataformas que injetam a porta funcionam
  sem mudança de código.
- **Healthcheck em `/api/health`**, que responde sem tocar em rede — barato o
  suficiente para rodar a cada minuto.
- **Usuário não-root** (uid 1000), criado depois do `COPY` para não brigar com
  permissão.

O `.dockerignore` exclui `docs/`, `tests/` e artefatos locais: o repositório
carrega bem mais do que a API precisa, e `docs/` é ~1 MB de dados publicados
que o painel estático serve por conta própria.

**Nenhum deploy executa ordens.** O sistema devolve uma recomendação de
alocação; a API não tem — e não deve ter — credencial de corretora.

### Variáveis de ambiente

```env
# Universo e histórico
MOEDAS_ALVO=bitcoin,ethereum,solana,cardano
DIAS_HISTORICO=1095
FONTE_DADOS=auto

# Perfil e carteira
PERFIL_RISCO=moderado
CAPITAL_INICIAL=25000
APORTE_MENSAL=1000

# O que você tem hoje: SÍMBOLO:valor_em_USD, separados por vírgula.
# Aceita nome ("bitcoin") ou símbolo ("BTC").
CARTEIRA_ATUAL=BTC:12000,ETH:5000,USD:3000
BENCHMARK=BTC
TAXA_LIVRE_RISCO=0.045

# Saídas
OUTPUT_DIR=out
CACHE_DIR=.cache/trendbot
DATA_DIR=data
```

---

## Testes

```bash
pytest tests/ -v

# cobertura
coverage run --source=trendbot,trendbot_engine,trendbot_coleta,app -m pytest tests/
coverage report
```

**124 testes, 100% offline** (nenhum toca em CoinGecko ou Binance), cobrindo
**88%** do núcleo.

| Módulo | Cobertura | O que segura no lugar |
|---|---|---|
| `backtest.py` | 95% | métricas do comparativo |
| `assets.py` | 93% | catálogo e nomes canônicos |
| `forecast.py` | 92% | quantis, calibração, peso do modelo |
| `risk.py` | 92% | risco, estresse, contribuições |
| `app/main.py` | 91% | contrato HTTP da API |
| `cli.py` | 91% | linha de comando |
| `advisor.py` | 90% | montagem da recomendação |
| `indicators.py` | 90% | indicadores técnicos |
| `config.py` | 86% | perfis e settings |
| `trendbot_coleta.py` | 85% | shim de compatibilidade da v1 |
| `report.py` | 82% | gráficos e payload |
| `data.py` | 73% | provedores, cache e fallback |

### O painel também é testado

O dashboard é servido direto do `docs/`, sem build. Durante muito tempo isso
significou que **nada** o validava — e ele já entregou função definida e nunca
chamada, e link para imagem que deixou de existir. Os dois passam batido porque
o navegador não reclama de função parada nem confere `href`.

```bash
npm ci
node tests/painel/check.mjs
```

Sobe o DOM com os dados publicados e confere: sintaxe, **função definida e
nunca chamada**, um card por ativo, o gráfico desenhado, nenhum link para
arquivo não publicado, e o veredito do modelo preenchido — porque um painel que
esconde as próprias limitações está justamente burlando a proposta do projeto.

### A imagem Docker

```bash
docker build -t trendbot .
docker run --rm -p 8000:8000 trendbot
```

O CI constrói a imagem e espera o healthcheck dela ficar `healthy` em todo PR.
Antes, um Dockerfile quebrado — ou um `requirements.txt` sem o uvicorn, que é o
`CMD` — só aparecia quando alguém tentava subir o contêiner à mão.

Os testes que mais importam são os que travam uma decisão de projeto, não os
que exercitam código:

- **ausência de informação do futuro nas features** — alterar o último preço não
  pode mudar as features anteriores;
- **caixa não renormalizado** — o colchão tem de continuar sendo caixa, e não
  virar "exposição implícita";
- **previsão simulada não entra no histórico de acertos**;
- **a pendência é conferida com o preço de D+1**, não com o último disponível;
- **o model card aparece no painel** — já foi calculado e descartado uma vez;
- **as tabelas de nomes do Python e do dashboard concordam**;
- **o `.env` é lido de verdade**, e não atropela quem já definiu a variável;
- **perfil inexistente falha**, em vez de cair no padrão em silêncio.

Todo teste novo passa por **verificação por mutação**: reintroduzo o defeito e
confirmo que o teste quebra. Vários não quebravam na primeira versão — em geral
por procurarem o texto da *definição* de uma função (que contém o da chamada) ou
por construírem dados em que a grandeza medida não variava.

---

## Automação (GitHub Actions)

O workflow `.github/workflows/daily_report.yml` roda diariamente:

1. **job `qualidade`** — instala dependências e roda os testes;
2. **job `relatorio`** (só se os testes passarem) — executa
   `python trendbot_engine.py`, que roda o motor novo e publica no formato
   legado: `docs/data.json`, `docs/historico.json`, `docs/relatorio_completo.json`
   e os gráficos. O dashboard estático do GitHub Pages em `docs/` continua
   funcionando sem alteração, e o histórico de acertos segue sendo conferido
   dia após dia (critério: preço realizado dentro do intervalo de 90%).

#### A recomendação precisa conhecer a sua carteira

Sem `CARTEIRA_ATUAL`, o motor monta a carteira como **100% caixa** — e a
recomendação publicada todo dia é sempre a mesma, "aplique 69% a partir do
caixa", independentemente do que você tem. Ela não está errada, mas é uma
resposta para uma pergunta que ninguém fez.

Com `CARTEIRA_ATUAL`, o relatório passa a ser um **rebalanceamento**: compara o
que você tem com o alvo e diz o que mover, e o colchão de caixa é calculado
sobre o patrimônio real.

Aceita nome ou símbolo (`bitcoin:12000` e `BTC:12000` dão no mesmo), soma
símbolo repetido, e ignora trecho malformado com um aviso — derrubar o
relatório do dia por causa de uma vírgula errada seria desproporcional. Se a
soma das posições passar do `CAPITAL_INICIAL`, vale o que você tem: o
patrimônio é o que está na carteira, não o que foi declarado.

Esse parsing existia em três cópias (motor, CLI e API) e agora é um só, em
`trendbot/config.py::parse_carteira`.

**Nenhum segredo é obrigatório.** Opcionais: variáveis `MOEDAS_ALVO`,
`DIAS_HISTORICO`, `PERFIL_RISCO`, `CAPITAL_INICIAL`, `TENTATIVAS_REDE`, e o
segredo `COINGECKO_API_KEY` (a API pública já responde, mas limita o histórico
a 365 dias).

As variáveis `EMAIL_*` saíram: a versão 2 não envia e-mail, mas o workflow
seguia injetando os três segredos como se enviasse.

### Painel do GitHub Pages

O dashboard em `docs/` é estático (HTML/CSS/JS puro, sem build e sem CDN) e
lê `data.json` + `historico.json`. A lista de histórico tem:

- **filtros** por moeda, por resultado (dentro/fora do intervalo, pendente) e
  por período (7/30/90/365 dias);
- **ordenação** por mais recentes, mais antigos ou **maior erro** — este último
  por erro *relativo* ao preço, senão o Bitcoin ($80 mil) dominaria a lista e
  esconderia um desvio de 9% na Cardano ($0,22);
- **paginação** de 10/25/50/100 por página, com controle de páginas e contagem
  "mostrando X–Y de Z (de N no total)";
- **estado na URL** (`?moeda=ETH&resultado=ERRO&pagina=2`), para compartilhar
  uma visão filtrada. Parâmetros inválidos são ignorados;
- **coluna de erro em %** ao lado do erro em dólar — 2 mil de erro no Bitcoin
  é 2,5%, na Cardano é 900%, então o valor absoluto não compara ativos;
- **cobertura realizada** sob o rótulo "Intervalo 90%" (ex.: *acerto real 97%,
  112/116*). O nome diz o alvo; o número diz o que aconteceu — esconder isso
  superestima o risco;
- **gráfico de calibração**, que se adapta: com uma moeda filtrada mostra
  previsto × realizado com a reta de 45°; com várias, o erro relativo por dia
  (misturar Bitcoin e Cardano no mesmo eixo, seis ordens de grandeza, não diz
  nada). Inclui média e viés do erro;
- **exportação CSV** do resultado filtrado — todas as páginas, não só a atual,
  com separador `;`, decimais com vírgula e BOM (senão o Excel pt-BR quebra os
  acentos);
- **layout em cards** abaixo de 640px: a tabela de 8 colunas vira uma lista
  rotulada no celular.

#### Recomendação de carteira

Abaixo dos cards, o painel mostra a recomendação que o motor calcula:
alocação-alvo contra a atual, as ordens sugeridas com o motivo de cada uma, o
colchão de caixa com os gatilhos de proteção, os alertas, e a narrativa com o
que observar e o que faria o sistema mudar de ideia.

Ela vem de `docs/recomendacao.json`, e não do `relatorio_completo.json`: este
tem ~94 KB de grades de quantis que o painel não lê, e publicar isso todo dia
no git para exibir meia dúzia de números não compensa. O arquivo do painel tem
~8,5 KB. O relatório completo continua sendo gerado, para quem depura.

Duas proteções: se o ciclo não consegue montar a carteira, o motor **apaga** o
arquivo em vez de deixar a recomendação de ontem no ar como se fosse de hoje; e
como a recomendação carrega a própria fonte, o painel avisa em destaque quando
ela foi gerada com dados simulados — os dois arquivos podem cair no simulador em
ciclos diferentes.

Os nomes de moeda são **canonizados** no painel: o histórico antigo guarda
`BITCOIN` e o motor atual grava `BTC`. Sem unificar, o filtro mostrava o mesmo
ativo duas vezes e a "precisão por moeda" dos cards ficava zerada — o card do
BTC exibia "Aguardando dados" mesmo com 34 previsões já resolvidas.

#### De quanto tempo é esse histórico

O `historico.json` guarda no máximo 400 entradas. Com 4 ativos por dia, isso dá
cerca de **100 dias de histórico de acertos** — suficiente para a calibração dos
intervalos, que quer ~200 pontos resolvidos. Cada entrada pesa ~250 bytes, então
aumentar muito aqui vira peso diário no git; quando o teto corta, o motor avisa
quantas previsões saíram.

**Isso não é a janela do backtest.** O backtest roda sobre dados de mercado e
cobre 3,5 anos; o histórico de acertos cobre os últimos ~100 dias de previsões
publicadas. São coisas diferentes, e um não valida o outro: o backtest diz como a
estratégia teria se saído, o histórico diz como os intervalos estão se
comportando agora.

---

## Estrutura do projeto

```
TrendBot/
├── trendbot/                     # núcleo quantitativo (v2)
│   ├── assets.py                 # catálogo de 18 ativos + resolução de tickers
│   ├── config.py                 # perfis de risco, settings, estado da carteira
│   ├── data.py                   # provedores, cache, fallback, simulação
│   ├── indicators.py             # indicadores técnicos e estatísticos
│   ├── forecast.py               # previsão probabilística walk-forward
│   ├── risk.py                   # covariância, VaR/CVaR, estresse, paridade
│   ├── advisor.py                # alocação, hedge, ordens, narrativa, alertas
│   ├── backtest.py               # comparação de estratégias com custos
│   ├── report.py                 # gráficos PNG e payload JSON
│   └── cli.py                    # interface de linha de comando
├── app/
│   ├── main.py                   # API FastAPI
│   └── static/                   # painel (HTML/CSS/JS puro, SVG próprio)
├── tests/test_trendbot.py        # 39 testes
├── docs/                         # dashboard estático (GitHub Pages, legado)
├── trendbot_engine.py            # compatibilidade com o pipeline v1
├── trendbot_coleta.py            # compatibilidade com a coleta v1
├── limpar_historico.py           # utilitário: remove duplicatas do histórico
├── requirements.txt
└── readme.md
```

---

## Limitações e honestidade

Este projeto é deliberadamente conservador. Vale ler antes de usar:

1. **Retorno de cripto no curto prazo é quase imprevisível.** O modelo reporta
   isso e se desliga. Se você procurava um "sinal", este não é o projeto.
2. **Backtest não é promessa.** Os resultados vêm de um recorte específico, com
   hipóteses de custo e liquidez. O futuro pode — e vai — ser diferente.
3. **Dados simulados não são mercado.** Sempre que a fonte for `synthetic`, o
   sistema avisa. Em produção, configure `FONTE_DADOS=auto` com rede liberada.
4. **Correlações em cripto sobem em crise.** A diversificação ajuda menos
   exatamente quando você mais precisa. O módulo de estresse existe para isso.
5. **Impostos, taxas e slippage variam por país e corretora.** Os 0,30% por giro
   são uma hipótese, não a sua realidade.
6. **Não é consultoria financeira.** É uma ferramenta de análise quantitativa.
   A decisão — e o risco — são seus.

---

## Licença e autor

Distribuído sob licença **MIT**. Veja [LICENSE](LICENSE).

**Desenvolvido com ☕ e dedicação por Everton L. de Souza.**

[![LinkedIn](https://img.shields.io/badge/LinkedIn-evertonldesouza-blue?logo=linkedin)](https://www.linkedin.com/in/evertonldesouza/)
[![GitHub](https://img.shields.io/badge/GitHub-evertonldesouza-black?logo=github)](https://github.com/evertonldesouza)
[![Email](https://img.shields.io/badge/Email-evertonldesouza%40proton.me-purple?logo=protonmail)](mailto:evertonldesouza@proton.me)

---

⭐ Se este projeto te ajudou, considere dar uma estrela!
