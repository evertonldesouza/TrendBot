# Dados locais

Coloque aqui um arquivo `prices.csv` para que o TrendBot use **os seus** dados
(preços da sua corretora, dados ajustados, histórico proprietário, etc.).

## Formato

- Primeira coluna: data (`Data`), no formato `YYYY-MM-DD`.
- Demais colunas: um ticker por coluna (`BTC`, `ETH`, `SOL`, …).
- Valores: preço de fechamento em **USD**.
- Ordem: qualquer uma — o motor ordena e alinha automaticamente.

```csv
Data,BTC,ETH,SOL
2024-01-01,42000.0,2200.0,95.0
2024-01-02,43100.5,2255.1,97.3
2024-01-03,42750.2,2230.8,96.1
```

## Como usar

```bash
# CLI
python -m trendbot.cli --fonte csv

# ou por variável de ambiente
FONTE_DADOS=csv python -m trendbot.cli
```

Também é possível deixar `FONTE_DADOS=auto`: o CSV entra como **quarta** opção
da cadeia de fallback (depois de cache, Binance e CoinGecko), o que é útil para
complementar ativos que a API não cobre.

## Boas práticas

- Use pelo menos **400 dias** de histórico (o ideal é 1095) — abaixo de 200 o
  motor avisa que a estimativa de risco fica frágil.
- Mantenha as datas contínuas. Lacunas são preenchidas por `ffill`, mas muitos
  buracos degradam as estimativas.
- Não misture preços em moedas diferentes na mesma coluna.
- Este diretório é versionado: **não coloque aqui dados sensíveis**.
