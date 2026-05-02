# TrendBot: Intelligent Multi-Asset Forecasting & Alert System
 
O TrendBot é um ecossistema de análise preditiva para o mercado de criptoativos que transforma dados brutos em inteligência acionável. Ele combina Engenharia de Dados, Machine Learning e Automação para entregar previsões diárias com validação histórica real.
 
**[Acesse o Dashboard ao vivo](https://evertonldesouza.github.io/TrendBot/)**
 
---
 
## Dashboard
 
O sistema publica automaticamente um dashboard web atualizado diariamente com previsões, intervalos de confiança, indicadores técnicos e histórico de acertos do modelo.
 
![Dashboard Preview](docs/dashboard.png)

---

## Funcionalidades
 
| Módulo | Descrição | Ferramentas |
|--------|-----------|-------------|
| **Coleta** | Puxa dados históricos em tempo real via API pública (CoinGecko) | `requests`, `pandas` |
| **Modelagem Preditiva** | Treina modelo de Séries Temporais com indicadores técnicos (RSI, SMA) como regressores para prever o preço nas próximas 24h com intervalo de confiança de 90% | `Prophet`, `pandas-ta` |
| **Visualização** | Gera gráfico profissional (PNG) com histórico, SMAs, banda de confiança, painel RSI, cards de estatísticas e status de alerta | `matplotlib` |
| **Dashboard Web** | Publica cards com preço, previsão, variação, posição no intervalo de confiança e acertos recentes por ativo | `HTML`, `CSS`, `JavaScript` |
| **Histórico de Acertos** | Salva cada previsão e no ciclo seguinte compara com o preço real, validando se caiu dentro do intervalo de confiança | `JSON` |
| **Relatório por E-mail** | Agrupa análises de todos os ativos e envia um Daily Digest com os gráficos anexados | `smtplib` |
| **Automação CI/CD** | Execução diária automatizada via GitHub Actions com commit e push dos dados gerados | `GitHub Actions` |
 
---
 
## Como Funciona
 
```
CoinGecko API
     │
     ▼
Coleta de dados históricos (365 dias)
     │
     ▼
Cálculo de indicadores técnicos: RSI (14), SMA-7
     │
     ▼
Modelo Prophet + Regressores → Previsão D+1 + Intervalo de Confiança 90%
     │
     ├──► Gráfico PNG profissional (preço, SMAs, banda, RSI, cards de stats)
     │
     ├──► data.json (dashboard web)
     │
     ├──► historico.json (validação de acertos)
     │
     └──► E-mail consolidado (Daily Digest)
```
 
O fluxo completo roda automaticamente todos os dias via GitHub Actions.
 
---
 
## Modelo de IA
 
O TrendBot usa o **Facebook Prophet** com indicadores técnicos como regressores adicionais:
 
| Componente | Função |
|---|---|
| Prophet | Captura sazonalidade e tendência de longo prazo |
| RSI (14 períodos) | Detecta momentum: sobrecomprado / sobrevendido |
| SMA-7 | Desvio do preço em relação à média móvel de curto prazo |
| Intervalo 90% | Faixa esperada de preço — critério oficial de acerto |
 
### Critério de acerto
 
O modelo é considerado **correto** quando o preço real cai dentro do **intervalo de confiança de 90%** — não quando acerta o valor exato. Isso reflete o que o modelo realmente garante estatisticamente e evita penalizar previsões boas por pequenas variações de mercado.
 
---
 
## Estratégia de Alertas
 
| Variação Prevista | Status | Sinal |
|-------------------|--------|-------|
| Acima de +1.0% | COMPRA FORTE | 🚀 |
| Entre 0% e +1.0% | ALTA LEVE | ⬆️ |
| Entre -1.0% e 0% | NEUTRO | ⚖️ |
| Abaixo de -1.0% | VENDA | 🚨 |
 
---
 
## Dashboard Web
 
O dashboard exibe, para cada ativo:
 
- Preço atual e previsão para amanhã com variação percentual
- Badge de status do sinal com cor dinâmica
- Barra visual mostrando onde o preço atual está dentro do intervalo de confiança
- Mini-histórico de acertos recentes com segmentos verde/vermelho
- Precisão geral calculada automaticamente a partir do `historico.json`
- Tabela de histórico com filtro interativo por moeda
- Indicador de frescor dos dados (verde / amarelo / vermelho por horas desde atualização)
- Disclaimer de não-recomendação de investimento
---
 
## Gráficos Gerados
 
Cada moeda gera um gráfico `.png` com layout de dois painéis:
 
**Painel principal:**
- Linha de preço histórico (últimos 45 dias)
- Médias móveis SMA-7 e SMA-21
- Banda de confiança 90% sombreada com rótulos de limite
- Ponto de previsão com anotação colorida pelo sinal
- Máximo e mínimo do período com anotações
- Cards de estatísticas no topo: preço atual, previsão, intervalo, RSI, mín/máx 45d
**Painel RSI:**
- RSI (14 períodos) com zonas sobrecomprado (70) e sobrevendido (30) destacadas
- Valor atual anotado com diagnóstico (Neutro / Sobrecomprado / Sobrevendido)
**Rodapé:** data de geração, modelo utilizado e aviso de não-recomendação de investimento.
 
> Formatação inteligente de preços: ativos abaixo de $1 (ex: Cardano) exibem 4 casas decimais automaticamente.
 
---
 
## Instalação e Configuração
 
**Pré-requisitos**
- Python 3.10+
- Conta Gmail com senha de app habilitada
**1. Clonar e configurar o ambiente**
 
```bash
git clone https://github.com/evertonldesouza/TrendBot.git
cd TrendBot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
 
**2. Criar o arquivo `.env`**
 
```env
EMAIL_REMETENTE=seu@gmail.com
EMAIL_SENHA=sua_senha_de_app
EMAIL_DESTINO=destino@gmail.com
MOEDAS_ALVO=bitcoin,ethereum,solana,cardano
DIAS_HISTORICO=365
HORARIO_RODADA=10:00
```
 
> ⚠️ `EMAIL_SENHA` não é a senha da conta Google. É uma **Senha de App** gerada em:  
> Conta Google → Segurança → Verificação em duas etapas → Senhas de app
 
**3. Rodar localmente**
 
```bash
python trendbot_engine.py
```
 
O sistema executa o ciclo completo e entra em modo de agendamento para rodar diariamente no horário configurado. Em ambiente GitHub Actions, encerra após a execução única.
 
---
 
## Utilitários
 
### Limpar duplicatas do histórico
 
Se o histórico acumular entradas duplicadas (mesma data + moeda), rode:
 
```bash
python limpar_historico.py
```
 
O script remove duplicatas mantendo a entrada mais recente e exibe um resumo do que foi removido.
 
---
 
## Automação com GitHub Actions
 
O arquivo `.github/workflows/daily_report.yml` configura a execução automática diária.
 
**Secrets necessários no repositório:**
 
| Secret | Descrição |
|--------|-----------|
| `EMAIL_REMETENTE` | Endereço Gmail de envio |
| `EMAIL_SENHA` | Senha de app do Gmail |
| `EMAIL_DESTINO` | Endereço de destino do relatório |
 
Configure em: `Settings → Secrets and variables → Actions`
 
---
 
## Estrutura do Projeto
 
```
TrendBot/
├── .github/
│   └── workflows/
│       └── daily_report.yml   # Automação CI/CD
├── docs/                      # Dashboard Web (GitHub Pages)
│   ├── index.html
│   ├── style.css
│   ├── script.js
│   ├── data.json              # Previsões do dia (gerado pelo robô)
│   ├── historico.json         # Histórico de previsões (gerado pelo robô)
│   └── alerta_*.png           # Gráficos gerados pelo robô
├── trendbot_coleta.py         # Módulo de coleta via API CoinGecko
├── trendbot_engine.py         # Motor principal: ML, gráficos, dashboard, e-mail
├── limpar_historico.py        # Utilitário: remove duplicatas do historico.json
├── requirements.txt
└── README.md
```
 
---
 
## Dependências
 
```
requests        — coleta via API
pandas          — manipulação de dados
prophet         — modelo de séries temporais
pandas-ta       — indicadores técnicos (RSI, SMA)
matplotlib      — geração de gráficos
schedule        — agendamento local
python-dotenv   — variáveis de ambiente
```
 
---
 
## Autor
 
**Everton Lima de Souza**
 
[![LinkedIn](https://img.shields.io/badge/LinkedIn-evertonldesouza-blue?logo=linkedin)](https://www.linkedin.com/in/evertonldesouza/)
[![GitHub](https://img.shields.io/badge/GitHub-evertonldesouza-black?logo=github)](https://github.com/evertonldesouza)
[![Email](https://img.shields.io/badge/Email-evertonldesouza%40proton.me-purple?logo=protonmail)](mailto:evertonldesouza@proton.me)
 
---
 
## Licença

Este projeto está sob a licença MIT.

---

⭐ Se este projeto te ajudou, considere dar uma estrela!