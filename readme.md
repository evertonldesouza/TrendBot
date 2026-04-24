# TrendBot: Motor Automatizado de Previsão e Alertas Cripto

O **TrendBot** é uma solução *end-to-end* de Automação e Data Science desenvolvida em Python. O objetivo principal do motor é ingerir dados brutos de séries temporais financeiras (como preços de criptomoedas), aplicar modelagem preditiva e entregar alertas acionáveis com relatórios visuais de forma totalmente autônoma.

Este projeto demonstra a integração prática de **Engenharia de Dados (Consumo de APIs)**, **Machine Learning (Prophet)**, **Automação (Scheduling)** e **Validação Analítica (Backtesting)**.
---
Preview:
![Prévia do App](alerta_sapa_20251209_222355.png)
![Prévia do App](alerta_sapa_20251209_224627.png)

## 🎯 Funcionalidades Principais

| Módulo |Descrição | Ferramentas Chave|
|--------|----------|-----------|
| Módulo 1: Coleta| Puxa dados históricos em tempo real de APIs públicas (CoinGecko).| requests, pandas| 
| Módulo 2: Modelagem Preditiva| Treina um modelo de Séries Temporais para prever o preço do ativo nas próximas 24 horas.| Prophet (Meta/Facebook)| 
| Módulo 3: Visualização e Alerta| Gera um alerta condicional (Compra/Venda/Neutro) e cria um gráfico profissional (PNG) com a projeção.| matplotlib| 
|Módulo 4: Backtesting|Simula a aplicação da estratégia de alerta em dados históricos para provar o lucro teórico.|pandas (simulação customizada)|
|Módulo 5: Automação| Agendamento diário da execução do fluxo e entrega do alerta.schedule| 
| Módulo 6: Distribuição (Opcional)| Envio do alerta e do gráfico PNG para um canal/chat (ex: Telegram).| python-telegram-bot| 

---

## ⚙️ Instalação e Configuração

Pré-requisitos

- Python 3.8+

- Ambiente virtual (venv)

1. Clonar o Repositório e Configurar o Ambiente
   
```
git clone https://github.com/SeuUsuario/sapa_cripto.git
cd sapa_cripto
python -m venv venv
source venv/bin/activate  # Ou venv\Scripts\activate no Windows
```
2. Instalar Dependências

Este projeto requer bibliotecas de Data Science e Automação:
```
pip install requests pandas prophet matplotlib schedule python-telegram-bot
```

3. Configuração do Alerta (Telegram)
Para ativar a distribuição remota (Módulo 6), você precisa inserir suas credenciais no arquivo sapa_modelo.py:
```
Python
# sapa_modelo.py (Busque por estas linhas no topo)
TELEGRAM_TOKEN = 'SEU_TOKEN_DO_BOT_AQUI'
CHAT_ID = 'SEU_CHAT_ID_AQUI' 
```
(Caso o envio para Telegram não esteja configurado, o sistema usará o PyAutoGUI para exibir um pop-up e abrir o gráfico PNG localmente.)

---

## ▶️ Como Rodar o Projeto
O projeto é projetado para rodar indefinidamente, executando o ciclo completo no horário agendado.

1. Execução (Modo Agendamento)
Mantenha o terminal aberto para que o schedule funcione. O sistema fará um teste inicial e entrará em modo de escuta.
```
python sapa_modelo.py
```
2. Teste e Configuração do Agendamento
Ajuste a variável HORARIO_RODADA no final de sapa_modelo.py para definir quando o alerta deve ser enviado todos os dias.
```
Python
# sapa_modelo.py (Final do arquivo)
HORARIO_RODADA = "10:00" # Ex: Alerta enviado diariamente às 10h da manhã
```

---

## 💡 Estratégia de Backtesting (Módulo 4)
O backtesting é executado automaticamente dentro do fluxo principal, simulando a seguinte regra de negociação:

- Sinal de Compra: O modelo Prophet prevê uma variação de preço acima de +1.0% no próximo dia.

- Sinal de Venda: O modelo Prophet prevê uma variação de preço abaixo de -1.0% no próximo dia.
  
O output do Backtesting é o Lucro Total Acumulado que o sistema teria gerado ao longo do período histórico analisado, validando a eficácia preditiva da sua solução.

## 📝 Estrutura do Projeto
```
sapa_cripto/
├── venv/                      # Ambiente Virtual
├── sapa_coleta.py             # Módulo de Coleta de Dados API
├── sapa_modelo.py             # Módulos de ML, Alerta, Backtesting e Agendamento (principal)
├── alerta_sapa_*.png          # Arquivos de gráficos gerados
└── README.md                  # Documentação do Projeto (este arquivo)
```
---

## 👨‍💻 Autor

**Everton Lima de Souza**

- LinkedIn: [@evertonldesouza](https://www.linkedin.com/in/evertonldesouza/)
- GitHub: [@evertonldesouza](https://github.com/evertonldesouza)
- Email: [evertonldesouza@proton.me]

## 📄 Licença

Este projeto está sob a licença MIT.

---

⭐ Se este projeto te ajudou, considere dar uma estrela!
