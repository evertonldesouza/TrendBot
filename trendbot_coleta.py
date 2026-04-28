import os
import requests
import logging
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def coletar_dados_historicos(coin: str = None, days: int = None) -> pd.DataFrame:
    
    coin = coin or os.getenv("MOEDA_ALVO", "bitcoin")
    days = days or int(os.getenv("DIAS_HISTORICO", 90))

    logger.info(f"Buscando dados históricos de '{coin}' dos últimos {days} dias...")
    
    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency=usd&days={days}"
    
    try:
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()
        
        prices = data.get('prices')
        if not prices:
            logger.warning("A API retornou sucesso, mas a lista de preços está vazia.")
            return None
            
        df = pd.DataFrame(prices, columns=['Timestamp', 'Preco_USD'])        
        df['Data'] = pd.to_datetime(df['Timestamp'], unit='ms')        
        df = df.set_index('Data')[['Preco_USD']]
        
        logger.info(f"Coleta concluída com sucesso. Total de {len(df)} pontos de dados extraídos.")
        return df
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Falha ao conectar com a API do CoinGecko: {e}")
        return None

if __name__ == "__main__":
    logger.info("Iniciando teste isolado do módulo de coleta...")
    df_dados = coletar_dados_historicos() 
    if df_dados is not None:
        print("\n--- Amostra dos Dados Coletados ---")
        print(df_dados.tail())