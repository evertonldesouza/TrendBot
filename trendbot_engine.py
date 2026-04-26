import os
import json
import time
import logging
import schedule
import pandas as pd
import matplotlib.pyplot as plt
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from prophet import Prophet
from dotenv import load_dotenv
from trendbot_coleta import coletar_dados_historicos

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('cmdstanpy').setLevel(logging.WARN)

def enviar_email_consolidado(mensagem, lista_imagens):
    email_origem = os.getenv("EMAIL_REMETENTE")
    senha = os.getenv("EMAIL_SENHA")
    email_destino = os.getenv("EMAIL_DESTINO")

    if not all([email_origem, senha, email_destino]):
        logger.error("Credenciais faltando!")
        return

    msg = EmailMessage()
    msg['Subject'] = f"📊 TrendBot Multi-Report: {datetime.now().strftime('%d/%m/%Y')}"
    msg['From'] = email_origem
    msg['To'] = email_destino
    msg.set_content(mensagem)

    for caminho in lista_imagens:
        if os.path.exists(caminho):
            with open(caminho, 'rb') as f:
                file_data = f.read()
                msg.add_attachment(file_data, maintype='image', subtype='png', filename=caminho)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(email_origem, senha)
            smtp.send_message(msg)
        logger.info("Relatório Consolidado enviado com sucesso!")
    except Exception as e:
        logger.error(f"Erro no envio: {e}")

def treinar_e_prever(df_base):
    df_prophet = df_base.reset_index().rename(columns={'Data': 'ds', 'Preco_USD': 'y'})
    modelo = Prophet(daily_seasonality=True).fit(df_prophet)
    future = modelo.make_future_dataframe(periods=1, include_history=False)
    forecast = modelo.predict(future)
    preco_atual = df_prophet['y'].iloc[-1]
    previsao     = forecast['yhat'].iloc[0]
    confianca_min = forecast['yhat_lower'].iloc[0] 
    confianca_max = forecast['yhat_upper'].iloc[0]  
    return preco_atual, previsao, confianca_min, confianca_max

def gerar_alerta_visual(df_base, previsao_amanha, variacao, moeda):
    if variacao > 1.0: alerta, cor, emoji = "COMPRA FORTE", "#00ff00", "🚀"
    elif variacao > 0.0: alerta, cor, emoji = "ALTA LEVE", "#aaffaa", "⬆️"
    elif variacao < -1.0: alerta, cor, emoji = "VENDA", "#ff0000", "🚨"
    else: alerta, cor, emoji = "NEUTRO", "#aaaaaa", "⚖️"
        
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7))
    df_plot = df_base.tail(45)
    ultimo_dia = df_plot.index[-1]
    dia_prev = ultimo_dia + timedelta(days=1)
    
    ax.plot(df_plot.index, df_plot['Preco_USD'], color='#00bfff', label='Histórico')
    ax.plot([ultimo_dia, dia_prev], [df_plot['Preco_USD'].iloc[-1], previsao_amanha], color=cor, linestyle='--')
    ax.scatter(dia_prev, previsao_amanha, color=cor, s=150, edgecolors='white')
    
    ax.annotate(f' ${previsao_amanha:,.0f}\n ({variacao:+.2f}%)', xy=(dia_prev, previsao_amanha), color=cor, fontweight='bold')
    ax.grid(True, alpha=0.2)
    ax.set_title(f'PREVISÃO {moeda.upper()}\nStatus: {alerta} {emoji}')
    
    nome_arq = f"alerta_{moeda}.png"        # nome simples → vai no JSON e no href do JS
    caminho_arq = f"docs/{nome_arq}"        # caminho completo → só para o plt.savefig
    plt.savefig(caminho_arq, dpi=100)
    plt.close()
    return alerta, nome_arq, emoji    

def salvar_dados_dashboard(dados_consolidado):  

    caminho_json = "docs/data.json"    

    dashboard_data = {
        "ultima_atualizacao": datetime.now().strftime('%d/%m/%Y %H:%M'),
        "ativos": dados_consolidado
    }
    
    with open(caminho_json, 'w', encoding='utf-8') as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=4)
    
    logger.info("Arquivo data.json gerado para o Dashboard!")

def carregar_historico():
    caminho = "docs/historico.json"
    if os.path.exists(caminho):
        with open(caminho, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def salvar_historico(historico):
    caminho = "docs/historico.json"
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(historico, f, ensure_ascii=False, indent=4)
    logger.info("Arquivo historico.json atualizado!")

def fluxo_principal():
    logger.info("--- INICIANDO CICLO MULTIMOEDAS ---")
    
    moedas = [m.strip() for m in os.getenv("MOEDAS_ALVO", "bitcoin").split(',')]
    dias = int(os.getenv("DIAS_HISTORICO", "365"))
    hoje = datetime.now().strftime('%d/%m/%Y')
    
    relatorio_texto = "📊 RELATÓRIO TRENDBOT MULTIMOEDAS 📊\n" + "="*40 + "\n\n"
    imagens_geradas = []
    dados_para_json = []

    
    historico = carregar_historico()

    for moeda in moedas:
        logger.info(f"Analisando {moeda.upper()}...")
        df = coletar_dados_historicos(coin=moeda, days=dias)
        
        if df is not None and not df.empty:
            preco_hj, prev_amanha, conf_min, conf_max = treinar_e_prever(df)
            var = ((prev_amanha - preco_hj) / preco_hj) * 100
            status, arq, emoji = gerar_alerta_visual(df, prev_amanha, var, moeda)

            
            for entrada in historico:
                if entrada['moeda'] == moeda.upper() and entrada.get('preco_real') is None:
                    entrada['preco_real'] = round(preco_hj, 2)
                    erro = preco_hj - entrada['previsao']
                    entrada['erro'] = round(erro, 2)
                    entrada['acerto'] = '✅' if abs(erro / preco_hj * 100) < 2 else '❌'

            
            historico.append({
                "data": hoje,
                "moeda": moeda.upper(),
                "previsao": round(prev_amanha, 2),
                "confianca_min": round(conf_min, 2),
                "confianca_max": round(conf_max, 2),
                "preco_real": None,  
                "erro": None,
                "acerto": None
            })

            relatorio_texto += (f"🔹 {moeda.upper()}: {status} {emoji}\n"
                               f"   Preço: ${preco_hj:,.2f} -> Est.: ${prev_amanha:,.2f} ({var:+.2f}%)\n\n")
            imagens_geradas.append(arq)

            dados_para_json.append({
                "moeda": moeda.upper(),
                "preco": f"{preco_hj:,.2f}",
                "previsao": f"{prev_amanha:,.2f}",
                "confianca_min": f"{conf_min:,.2f}",
                "confianca_max": f"{conf_max:,.2f}",
                "variacao": f"{var:+.2f}",
                "status": status,
                "emoji": emoji,
                "imagem": arq
            })
        else:
            relatorio_texto += f"❌ {moeda.upper()}: Erro na coleta.\n\n"

    if imagens_geradas:
        salvar_dados_dashboard(dados_para_json)
        
        historico = historico[-120:]
        salvar_historico(historico)
        enviar_email_consolidado(relatorio_texto, imagens_geradas)

    logger.info("Ciclo concluído.")

if __name__ == "__main__":
    fluxo_principal()

    if not os.getenv("GITHUB_ACTIONS"):
        horario = os.getenv("HORARIO_RODADA", "10:00")
        logger.info(f"Modo local: agendando execução diária às {horario}")
        schedule.every().day.at(horario).do(fluxo_principal)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        logger.info("Ambiente Actions detectado. Encerrando após execução única.")