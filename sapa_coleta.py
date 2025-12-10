

import requests
import pandas as pd
from datetime import datetime

def coletar_dados_historicos(coin='bitcoin', days=90):

    print(f"Buscando dados históricos de {coin} dos últimos {days} dias...")
    
    
    url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency=usd&days={days}"
    
    try:
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()
        
        
        prices = data.get('prices')
        
        df = pd.DataFrame(prices, columns=['Timestamp', 'Preco_USD'])        
        
        df['Data'] = pd.to_datetime(df['Timestamp'], unit='ms')        
        
        df = df.set_index('Data')[['Preco_USD']]
        
        print(f"Coleta concluída. Total de {len(df)} pontos de dados.")
        return df
    
    except requests.exceptions.RequestException as e:
        print(f"ERRO DE CONEXÃO ou API: {e}")
        return None

if __name__ == "__main__":
    df_dados = coletar_dados_historicos(days=365) 
    if df_dados is not None:
        print("\nDados prontos para o ML:")
        print(df_dados.tail())