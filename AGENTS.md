# TrendBot — guia para agentes

Projeto: **orientador quantitativo de investimentos em cripto** (risk-first).
Linguagem do domínio e das mensagens ao usuário: **português do Brasil**.
Nomes de código, docstrings e logs: português também (o projeto é todo em pt-BR).

## Stack

- Python 3.12 (`numpy`, `pandas`, `requests`, `python-dotenv`, `matplotlib`,
  `fastapi`, `uvicorn`, `pydantic`). `scipy` e `scikit-learn` **não** são usados
  — ficaram listados por inércia e saíram.
- Frontend: HTML/CSS/JS puro, gráficos em SVG escritos à mão (sem CDN, sem build)
- Testes: `pytest` (suíte Python) + `jsdom` (checagem do painel, só dev)

## Comandos

```bash
pip install -r requirements.txt

# relatório completo no terminal + JSON + PNGs em out/
python -m trendbot.cli --perfil moderado --capital 25000 --aporte 1000 \
    --carteira "BTC:12000,ETH:5000,USD:5000"

# painel interativo (API + estáticos em app/static/)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# testes Python (rodam offline)
pytest tests/ -v

# checagem do painel público (docs/): sintaxe, função morta, renderização
npm ci
node tests/painel/check.mjs

# imagem da API
docker build -t trendbot .
docker run --rm -p 8000:8000 trendbot

# pipeline legado (GitHub Actions / GitHub Pages)
python trendbot_engine.py
```

## Mapa do código

| Arquivo | Responsabilidade |
|---|---|
| `trendbot/assets.py` | catálogo de ativos, resolução `bitcoin` ↔ `BTC` |
| `trendbot/config.py` | perfis de risco, `Settings`, `PortfolioState`, `parse_carteira` |
| `trendbot/data.py` | provedores (Binance/CoinGecko/CSV/simulação), cache, fallback |
| `trendbot/indicators.py` | indicadores técnicos e estatísticos |
| `trendbot/forecast.py` | features, ridge, walk-forward, quantis de erro |
| `trendbot/risk.py` | covariância, VaR/CVaR, paridade de risco, estresse |
| `trendbot/advisor.py` | orçamento de risco, alocação, hedge, ordens, narrativa |
| `trendbot/backtest.py` | comparação de estratégias com custos |
| `trendbot/report.py` | gráficos PNG e payload JSON |
| `trendbot/cli.py` | linha de comando |
| `app/main.py` | API FastAPI |
| `app/static/` | painel interativo servido pela API (`app.js`, `styles.css`) |
| `docs/` | painel público do GitHub Pages (`script.js`, `style.css`, `data.json`) |
| `tests/painel/check.mjs` | checagem do painel público com jsdom |
| `trendbot_engine.py` | compatibilidade com o pipeline v1 (Actions/Pages) |

### Atenção: são dois painéis

`app/static/` e `docs/` são implementações **independentes** da mesma ideia e
não compartilham código. Nada os mantém em sincronia senão quem mexe. Uma
correção aplicada em um não chega no outro — vale conferir os dois.

O `docs/` é servido direto do branch, sem build: é o que o público vê. O CI
roda `tests/painel/check.mjs` sobre ele em todo PR.

## Regras de ouro do projeto

1. **Nunca use informação do futuro.** Features, médias móveis e padronizações
   só podem usar dados até `t`. Existe teste para isso
   (`test_features_sem_informacao_do_futuro`).
2. **O modelo declara a própria competência.** Habilidade fora da amostra
   (`skill`) define o peso do modelo; negativa → peso zero. Nunca esconda isso.
3. **Caixa não é renormalizado.** Se a carteira tem 50% em caixa, o risco medido
   cai. Renormalizar faria o colchão desaparecer das métricas.
4. **Honestidade acima de persuasão.** Se o backtest perder, o texto diz que
   perdeu. Se os intervalos subestimarem o risco, o alerta aparece.
5. **Explique cada decisão.** Toda recomendação carrega motivo, risco e o que a
   invalidaria.
6. **Dados simulados são sempre rotulados** como simulados.
7. **Não versionar binário regenerado.** Gráficos que mudam todo dia vão para o
   painel como dados em texto e são desenhados em SVG. Binário novo todo dia não
   tem delta no git — foi assim que o repositório chegou a 126 MB.

## Ao alterar o núcleo quantitativo

- rode `pytest tests/ -v` (156 testes, ~20s, offline, 91% de cobertura);
- rode `node tests/painel/check.mjs` se mexeu em `docs/`;
- verifique se os quatro perfis continuam batendo o alvo de volatilidade
  (`test_carteira_recomendada_bate_o_alvo_de_volatilidade`);
- verifique se a cobertura dos intervalos continua entre 70% e 100%;
- **verifique o teste por mutação**: reverta a correção e confirme que o teste
  falha. Teste que passa com o defeito de volta não está segurando nada.

## Fora do escopo

- execução automática de ordens (o sistema **orienta**, não opera);
- integração com corretoras para custódia ou saque;
- qualquer promessa de retorno;
- envio de e-mail (não existe mais: não há SMTP em lugar nenhum do projeto).
