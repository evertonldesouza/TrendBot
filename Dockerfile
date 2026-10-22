# Imagem da API do TrendBot (app/main.py).
#
# Build e execução:
#   docker build -t trendbot .
#   docker run --rm -p 8000:8000 -e FONTE_DADOS=auto trendbot
#   curl localhost:8000/api/health
#
# A imagem não contém segredo nenhum e não escreve nada fora do contêiner:
# o sistema apenas aconselha alocação, não executa ordens.

FROM python:3.12-slim

# matplotlib precisa de um backend sem tela; o Agg já é o padrão quando não há
# display, mas deixar explícito evita surpresa em imagem enxuta.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    PORT=8000

WORKDIR /app

# dependências primeiro: muda pouco, e assim o cache do Docker reaproveita
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# o pacote trendbot (núcleo quantitativo) e a app FastAPI
COPY trendbot ./trendbot
COPY app ./app

# a API lê PORT, mas não expõe nada além de HTTP
EXPOSE 8000

# healthcheck: /api/health responde sem tocar em rede, então é barato
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

# o usuário não-root vem depois do COPY, para não brigar com permissão
RUN useradd --create-home --uid 1000 trendbot && chown -R trendbot:trendbot /app
USER trendbot

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
