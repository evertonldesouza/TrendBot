import matplotlib.pyplot as plt
import schedule
import time
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
from prophet import Prophet
import numpy as np

from sapa_coleta import coletar_dados_historicos 
import logging

logging.getLogger('cmdstanpy').setLevel(logging.WARN)

def criar_features_lagged(df, lags=5):

    df_novo = df.copy()
    
    for i in range(1, lags + 1):
        df_novo[f'Preco_Lag_{i}'] = df_novo['Preco_USD'].shift(i)
        

    df_novo['TARGET'] = df_novo['Preco_USD'].shift(-1)
    
    df_novo = df_novo.dropna()
    
    return df_novo


def treinar_e_prever(df_base):

    print("\nIniciando modelagem com Prophet...")
    
    df_prophet = df_base.reset_index()
    df_prophet.rename(columns={'Data': 'ds', 'Preco_USD': 'y'}, inplace=True)
    
    df_prophet['ds'] = pd.to_datetime(df_prophet['ds'])


    modelo = Prophet(daily_seasonality=True)
    modelo.fit(df_prophet)
    

    future = modelo.make_future_dataframe(periods=1, include_history=False)
    
    forecast = modelo.predict(future)
    
    previsao_amanha = forecast['yhat'].iloc[0]
    
    preco_hoje = df_prophet['y'].iloc[-1]
    
    print("Modelo Prophet treinado com sucesso.")
    
    return preco_hoje, previsao_amanha


def gerar_alerta_visual(df_base, previsao_amanha, variacao_percentual):
    """
    """
    
    if variacao_percentual > 1.0: 
        alerta_tipo = "COMPRA FORTE"
        cor_alerta = "green"
        emoji = "🚀"
    elif variacao_percentual > 0.0:
        alerta_tipo = "ALTA LEVE"
        cor_alerta = "lightgreen"
        emoji = "⬆️"
    elif variacao_percentual < -1.0: 
        alerta_tipo = "VENDA / ALERTA DE QUEDA"
        cor_alerta = "red"
        emoji = "🚨"
    else:
        alerta_tipo = "NEUTRO / ESTABILIDADE"
        cor_alerta = "gray"
        emoji = "⚖️"
        
    print(f"\n{emoji} *** ALERTA GERADO PELO SAPA: {alerta_tipo} *** {emoji}")
    
    
    df_plot = df_base.tail(60).copy()
    
    ultimo_dia = df_plot.index[-1]
    dia_previsao = ultimo_dia + timedelta(days=1)
    
    df_previsao = pd.DataFrame(
        {'Preco_USD': [df_plot['Preco_USD'].iloc[-1], previsao_amanha]},
        index=[ultimo_dia, dia_previsao]
    )
    
    plt.figure(figsize=(10, 6))
    
    plt.plot(df_plot.index, df_plot['Preco_USD'], label='Preço Histórico', color='blue')
    
    plt.plot(df_previsao.index, df_previsao['Preco_USD'], 'r--', label='Projeção SAPA')
    
    plt.scatter(dia_previsao, previsao_amanha, color=cor_alerta, s=100, label=f'Previsão: ${previsao_amanha:,.0f}')
    
    plt.title(f'BTC/USD - Previsão do Sistema SAPA ({alerta_tipo})', fontsize=16)
    plt.xlabel('Data')
    plt.ylabel('Preço (USD)')
    plt.legend()
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    nome_arquivo = f"alerta_sapa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(nome_arquivo)
    print(f"🖼️ Gráfico de alerta salvo como: {nome_arquivo}")
    plt.close()
    
    return alerta_tipo, nome_arquivo


def fluxo_principal():
    print("\n--- INICIANDO FLUXO SAPA ---")
    df_base = coletar_dados_historicos(days=365)
    
    if df_base is not None and not df_base.empty:
        preco_hoje, previsao_amanha = treinar_e_prever(df_base) 
        
        variacao_percentual = ((previsao_amanha - preco_hoje) / preco_hoje) * 100
        
        print("-" * 30)
        print(f"💰 Preço de Hoje (Último dado): ${preco_hoje:,.2f}")
        print(f"🔮 Previsão para Amanhã: ${previsao_amanha:,.2f}")
        print(f"📊 Variação Estimada: {variacao_percentual:+.2f}%")
        
        gerar_alerta_visual(df_base, previsao_amanha, variacao_percentual)
        
    else:
        print("ERRO: Falha ao coletar dados históricos ou DataFrame vazio.")


if __name__ == "__main__":
    
    print("Executando teste inicial do fluxo principal...")
    fluxo_principal() 
    print("Teste inicial concluído. Iniciando modo de agendamento.")
    
    HORARIO_RODADA = "10:00" 
    
    print(f"\n*** SAPA ativado! Agendado para rodar diariamente às {HORARIO_RODADA}. ***")
    
    schedule.every().day.at(HORARIO_RODADA).do(fluxo_principal)
    
    while True:
        schedule.run_pending()
        time.sleep(60) 