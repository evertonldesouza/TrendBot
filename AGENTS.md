# TrendBot — Sessão opencode

## Skills
- python-patterns
- python-testing

## Stack
- Python 3
- pandas, matplotlib, prophet (previsão de séries temporais)
- pandas-ta (indicadores técnicos)
- requests (coleta de dados)
- schedule (tarefas agendadas)
- python-dotenv

## Commands
```bash
# instalar dependências
pip install -r requirements.txt

# coleta de dados
python trendbot_coleta.py

# engine de análise
python trendbot_engine.py
```

## Padrões
- Scripts modulares (coleta, engine, limpeza)
- .env para configuração sensível
- Prophet para previsão de tendências de criptoativos
