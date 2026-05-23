import os
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

def coletar_dados_historicos(coin: Optional[str] = None, days: Optional[int] = None) -> Optional[pd.DataFrame]:
    coin = coin or os.getenv("MOEDAS_ALVO", "bitcoin").split(",")[0]
    days = days or int(os.getenv("DIAS_HISTORICO", "90"))

    logger.info(f"Buscando dados historicos de '{coin}' dos ultimos {days} dias...")

    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency=usd&days={days}"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        prices = data.get('prices')
        if not prices:
            logger.warning("A API retornou sucesso, mas a lista de precos esta vazia.")
            return None

        df = pd.DataFrame(prices, columns=['Timestamp', 'Preco_USD'])
        df['Data'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df = df.set_index('Data')[['Preco_USD']]

        logger.info(f"Coleta concluida com sucesso. Total de {len(df)} pontos de dados extraidos.")
        return df

    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao conectar com a API do CoinGecko para '{coin}'")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Falha ao conectar com a API do CoinGecko para '{coin}': {e}")
        return None

if __name__ == "__main__":
    logger.info("Iniciando teste isolado do modulo de coleta...")
    df_dados = coletar_dados_historicos()
    if df_dados is not None:
        print("\n--- Amostra dos Dados Coletados ---")
        print(df_dados.tail())
