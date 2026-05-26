import os
import time
import requests
import logging
import pandas as pd
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def coletar_dados_historicos(
    coin: Optional[str] = None,
    days: Optional[int] = None,
    max_tentativas: int = 3,
    timeout: int = 30,
) -> Optional[pd.DataFrame]:
    coin = coin or os.getenv("MOEDAS_ALVO", "bitcoin").split(",")[0]
    days = days or int(os.getenv("DIAS_HISTORICO", "90"))

    logger.info(f"Buscando dados historicos de '{coin}' dos ultimos {days} dias...")

    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
    params = {
        "vs_currency": "usd",
        "days": days,
    }

    for tentativa in range(1, max_tentativas + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)

            if response.status_code == 429:
                espera = tentativa * 10
                logger.warning(
                    f"Rate limit da CoinGecko para '{coin}'. "
                    f"Tentativa {tentativa}/{max_tentativas}. Aguardando {espera}s..."
                )
                time.sleep(espera)
                continue

            if 400 <= response.status_code < 500:
                logger.error(
                    f"Erro permanente da CoinGecko para '{coin}': "
                    f"HTTP {response.status_code}. Verifique se o ID da moeda existe."
                )
                return None

            response.raise_for_status()
            data = response.json()

            prices = data.get("prices")
            if not prices:
                logger.warning("A API retornou sucesso, mas a lista de precos esta vazia.")
                return None

            df = pd.DataFrame(prices, columns=["Timestamp", "Preco_USD"])
            df["Data"] = pd.to_datetime(df["Timestamp"], unit="ms")
            df = df.set_index("Data")[["Preco_USD"]]

            logger.info(f"Coleta concluida com sucesso. Total de {len(df)} pontos de dados extraidos.")
            return df

        except requests.exceptions.Timeout:
            logger.warning(
                f"Timeout ao conectar com a API do CoinGecko para '{coin}'. "
                f"Tentativa {tentativa}/{max_tentativas}."
            )

        except requests.exceptions.RequestException as e:
            logger.warning(
                f"Falha ao conectar com a API do CoinGecko para '{coin}': {e}. "
                f"Tentativa {tentativa}/{max_tentativas}."
            )

        if tentativa < max_tentativas:
            espera = tentativa * 5
            logger.info(f"Nova tentativa em {espera}s...")
            time.sleep(espera)

    logger.error(f"Falha definitiva ao coletar dados de '{coin}' apos {max_tentativas} tentativas.")
    return None

if __name__ == "__main__":
    logger.info("Iniciando teste isolado do modulo de coleta...")
    df_dados = coletar_dados_historicos()
    if df_dados is not None:
        print("\n--- Amostra dos Dados Coletados ---")
        print(df_dados.tail())
