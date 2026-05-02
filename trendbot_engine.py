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

try:
    import pandas_ta as ta
    _TA_DISPONIVEL = True
except ImportError:
    _TA_DISPONIVEL = False

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

    modelo = Prophet(
        daily_seasonality=True,
        interval_width=0.90,
        changepoint_prior_scale=0.05
    )

    usar_regressores = False
    if _TA_DISPONIVEL:
        try:
            df_prophet['rsi'] = ta.rsi(df_prophet['y'], length=14)
            df_prophet['sma7'] = ta.sma(df_prophet['y'], length=7)
            df_prophet['rsi'] = (df_prophet['rsi'] - 50) / 50       
            df_prophet['sma7'] = df_prophet['sma7'] / df_prophet['y'] - 1  
            df_prophet = df_prophet.dropna()
            modelo.add_regressor('rsi')
            modelo.add_regressor('sma7')
            usar_regressores = True
            logger.info("Regressores técnicos (RSI + SMA7) adicionados ao modelo.")
        except Exception as e:
            logger.warning(f"Falha ao calcular indicadores técnicos: {e}. Usando Prophet padrão.")

    modelo.fit(df_prophet)
    future = modelo.make_future_dataframe(periods=1, include_history=False)

    if usar_regressores:
        future['rsi'] = df_prophet['rsi'].iloc[-1]
        future['sma7'] = df_prophet['sma7'].iloc[-1]

    forecast = modelo.predict(future)
    preco_atual   = df_prophet['y'].iloc[-1]
    previsao      = forecast['yhat'].iloc[0]
    confianca_min = forecast['yhat_lower'].iloc[0]
    confianca_max = forecast['yhat_upper'].iloc[0]
    return preco_atual, previsao, confianca_min, confianca_max

def gerar_alerta_visual(df_base, previsao_amanha, variacao, moeda, conf_min, conf_max):
    if variacao > 1.0:
        alerta, cor_linha, emoji = "COMPRA FORTE", "#3fb950", "🚀"
    elif variacao > 0.0:
        alerta, cor_linha, emoji = "ALTA LEVE",    "#58a6ff", "⬆️"
    elif variacao < -1.0:
        alerta, cor_linha, emoji = "VENDA",        "#f85149", "🚨"
    else:
        alerta, cor_linha, emoji = "NEUTRO",       "#8b949e", "⚖️"

    # Formatador inteligente: preços < $1 usam 4 casas, < $10 usam 2, demais arredondam
    def fmt(v, decimals=None):
        if decimals is not None:
            return f"${v:,.{decimals}f}"
        if abs(v) < 1:
            return f"${v:.4f}"
        elif abs(v) < 10:
            return f"${v:.2f}"
        else:
            return f"${v:,.0f}"

    BG      = "#0d1117"
    SURFACE = "#161b22"
    SURFACE2= "#21262d"
    BORDER  = "#30363d"
    TEXT    = "#c9d1d9"
    MUTED   = "#8b949e"
    FAINT   = "#484f58"
    BLUE    = "#58a6ff"
    PURPLE  = "#a78bfa"
    AMBER   = "#d29922"
    AMBER2  = "#e3b341"

    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": BG,
        "axes.edgecolor": BORDER, "axes.labelcolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "grid.color": BORDER, "grid.linewidth": 0.5,
        "text.color": TEXT, "font.family": "DejaVu Sans", "font.size": 10,
    })

    df_plot     = df_base.tail(45).copy()
    ultimo_dia  = df_plot.index[-1]
    dia_prev    = ultimo_dia + timedelta(days=1)
    preco_atual = df_plot["Preco_USD"].iloc[-1]
    preco_min45 = df_plot["Preco_USD"].min()
    preco_max45 = df_plot["Preco_USD"].max()
    idx_max     = df_plot["Preco_USD"].idxmax()
    idx_min     = df_plot["Preco_USD"].idxmin()

    df_plot["SMA7"]  = df_plot["Preco_USD"].rolling(7,  min_periods=1).mean()
    df_plot["SMA21"] = df_plot["Preco_USD"].rolling(21, min_periods=1).mean()

    delta = df_plot["Preco_USD"].diff()
    gain  = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss  = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    df_plot["RSI"] = 100 - (100 / (1 + gain / loss.replace(0, 0.0001)))
    rsi_atual  = df_plot["RSI"].iloc[-1]
    rsi_cor    = "#f85149" if rsi_atual > 70 else ("#3fb950" if rsi_atual < 30 else MUTED)
    rsi_label  = "Sobrecomprado" if rsi_atual > 70 else ("Sobrevendido" if rsi_atual < 30 else "Neutro")

    fig = plt.figure(figsize=(14, 10), facecolor=BG)
    gs  = fig.add_gridspec(
        3, 1,
        height_ratios=[0.18, 3, 1],
        hspace=0,
        top=0.93, bottom=0.07, left=0.08, right=0.97
    )
    ax_cards = fig.add_subplot(gs[0])
    ax1      = fig.add_subplot(gs[1])
    ax2      = fig.add_subplot(gs[2], sharex=ax1)

    fig.text(0.08, 0.97, f"{moeda.upper()}", fontsize=18, fontweight="bold",
             color=TEXT, ha="left", va="top")
    fig.text(0.08, 0.963, f"Previsão para as próximas 24h  ·  últimos 45 dias",
             fontsize=9, color=MUTED, ha="left", va="top")
    status_x = 0.97
    status_bg = {"COMPRA FORTE": "#1a3a23", "ALTA LEVE": "#132033",
                 "VENDA": "#3a1a1a", "NEUTRO": "#21262d"}.get(alerta, SURFACE2)
    fig.text(status_x, 0.975, f"  {emoji}  {alerta}  ", fontsize=10, fontweight="bold",
             color=cor_linha, ha="right", va="top",
             bbox=dict(boxstyle="round,pad=0.4", facecolor=status_bg,
                       edgecolor=cor_linha, linewidth=1.2))

    ax_cards.set_facecolor(SURFACE)
    ax_cards.set_xlim(0, 1)
    ax_cards.set_ylim(0, 1)
    ax_cards.axis("off")
    for spine in ax_cards.spines.values():
        spine.set_visible(False)

    ax_cards.axhline(1, color=BORDER, linewidth=0.8)
    ax_cards.axhline(0, color=BORDER, linewidth=0.8)

    cards_data = [
        ("Preço atual",     fmt(preco_atual, 2),                       TEXT),
        ("Previsão amanhã", f"{fmt(previsao_amanha, 2)}  ({variacao:+.2f}%)", cor_linha),
        ("Intervalo 90%",   f"{fmt(conf_min)} – {fmt(conf_max)}",        BLUE),
        ("RSI (14)",        f"{rsi_atual:.1f}  {rsi_label}",               rsi_cor),
        ("Mín 45d",         fmt(preco_min45),                        MUTED),
        ("Máx 45d",         fmt(preco_max45),                        MUTED),
    ]
    positions = [0.03, 0.20, 0.38, 0.58, 0.77, 0.88]
    for (label, valor, cor), x in zip(cards_data, positions):
        ax_cards.text(x, 0.75, label, fontsize=7,  color=FAINT,  va="top")
        ax_cards.text(x, 0.38, valor, fontsize=9.5, color=cor, va="top", fontweight="bold")

    ax1.axhspan(conf_min, conf_max, alpha=0.07, color=BLUE)
    ax1.axhline(conf_min, color=BLUE, linewidth=0.6, linestyle=":", alpha=0.5)
    ax1.axhline(conf_max, color=BLUE, linewidth=0.6, linestyle=":", alpha=0.5)

    ax1.text(df_plot.index[0], conf_min, f" {fmt(conf_min)}  ← limite inf. 90%",
             color=BLUE, fontsize=7, alpha=0.6, va="bottom")
    ax1.text(df_plot.index[0], conf_max, f" {fmt(conf_max)}  ← limite sup. 90%",
             color=BLUE, fontsize=7, alpha=0.6, va="top")

    ax1.plot(df_plot.index, df_plot["SMA21"], color=AMBER,  linewidth=1.2,
             linestyle="--", alpha=0.7, label="SMA-21", zorder=2)
    ax1.plot(df_plot.index, df_plot["SMA7"],  color=AMBER2, linewidth=1.2,
             linestyle="--", alpha=0.9, label="SMA-7",  zorder=2)

    ax1.fill_between(df_plot.index, df_plot["Preco_USD"],
                     df_plot["Preco_USD"].min() * 0.995,
                     alpha=0.06, color=BLUE)
    ax1.plot(df_plot.index, df_plot["Preco_USD"],
             color=BLUE, linewidth=2, zorder=3, label="Preço")

    ax1.scatter([ultimo_dia], [preco_atual], color=BLUE, s=80,
                zorder=6, edgecolors="white", linewidths=1.5)

    ax1.axvline(ultimo_dia, color=BORDER, linewidth=1, linestyle=":", zorder=1)
    y_base = preco_min45 * 0.9975
    ax1.text(ultimo_dia, y_base, "  hoje",   color=MUTED,     fontsize=8, va="top")
    ax1.text(dia_prev,   y_base, "  amanhã", color=cor_linha, fontsize=8, va="top")

    # Linha de previsão
    ax1.plot([ultimo_dia, dia_prev], [preco_atual, previsao_amanha],
             color=cor_linha, linewidth=2, linestyle="--", zorder=4)
    ax1.scatter([dia_prev], [previsao_amanha], color=cor_linha, s=140,
                zorder=5, edgecolors="white", linewidths=2)

    offset_y = (conf_max - conf_min) * 0.045
    ax1.annotate(
        f"{fmt(previsao_amanha)}\n({variacao:+.2f}%)",
        xy=(dia_prev, previsao_amanha),
        xytext=(dia_prev, previsao_amanha + offset_y),
        color=cor_linha, fontsize=10, fontweight="bold", zorder=7, ha="left",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=BG,
                  edgecolor=cor_linha, linewidth=0.8, alpha=0.85)
    )

    ax1.annotate(f"Máx {fmt(preco_max45)}",
                 xy=(idx_max, preco_max45),
                 xytext=(0, 10), textcoords="offset points",
                 color=MUTED, fontsize=8,
                 arrowprops=dict(arrowstyle="-", color=FAINT, lw=0.8))
    ax1.annotate(f"Mín {fmt(preco_min45)}",
                 xy=(idx_min, preco_min45),
                 xytext=(0, -14), textcoords="offset points",
                 color=MUTED, fontsize=8,
                 arrowprops=dict(arrowstyle="-", color=FAINT, lw=0.8))

    ax1.set_ylabel("Preço (USD)", fontsize=9, color=MUTED)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: fmt(x)))
    ax1.grid(True, alpha=0.25)
    ax1.tick_params(labelbottom=False)
    ax1.legend(loc="upper left", fontsize=8, framealpha=0.3,
               facecolor=SURFACE, edgecolor=BORDER, labelcolor=TEXT)

    ax2.fill_between(df_plot.index, df_plot["RSI"], 70,
                     where=(df_plot["RSI"] > 70), alpha=0.15, color="#f85149",
                     interpolate=True)
    ax2.fill_between(df_plot.index, df_plot["RSI"], 30,
                     where=(df_plot["RSI"] < 30), alpha=0.15, color="#3fb950",
                     interpolate=True)
    ax2.fill_between(df_plot.index, df_plot["RSI"], 50,
                     where=(df_plot["RSI"] > 50), alpha=0.05, color="#f85149",
                     interpolate=True)
    ax2.fill_between(df_plot.index, df_plot["RSI"], 50,
                     where=(df_plot["RSI"] <= 50), alpha=0.05, color="#3fb950",
                     interpolate=True)
    ax2.plot(df_plot.index, df_plot["RSI"], color=PURPLE, linewidth=1.5, zorder=3)
    ax2.axhline(70, color="#f85149", linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.axhline(50, color=BORDER,    linewidth=0.5, linestyle=":",  alpha=0.5)
    ax2.axhline(30, color="#3fb950", linewidth=0.8, linestyle="--", alpha=0.6)
    ax2.axvline(ultimo_dia, color=BORDER, linewidth=1, linestyle=":", zorder=1)

    ax2.scatter([df_plot.index[-1]], [rsi_atual], color=PURPLE, s=55,
                zorder=5, edgecolors="white", linewidths=1.2)
    ax2.annotate(f" {rsi_atual:.1f}  {rsi_label}",
                 xy=(df_plot.index[-1], rsi_atual),
                 xytext=(6, 0), textcoords="offset points",
                 color=rsi_cor, fontsize=8, fontweight="bold", va="center")

    ax2.text(df_plot.index[1], 72, "Sobrecomprado (70)", color="#f85149", fontsize=7, alpha=0.7)
    ax2.text(df_plot.index[1], 22, "Sobrevendido (30)",  color="#3fb950", fontsize=7, alpha=0.7)
    ax2.set_ylim(0, 100)
    ax2.set_yticks([30, 50, 70])
    ax2.set_ylabel("RSI (14)", fontsize=9, color=MUTED)
    ax2.grid(True, alpha=0.2)

    fig.text(
        0.08, 0.025,
        f"TrendBot Analytics  ·  Modelo: Prophet + RSI/SMA  ·  "
        f"Intervalo de confiança: 90%  ·  Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}  ·  "
        f"Não constitui recomendação de investimento.",
        fontsize=7, color=FAINT, ha="left"
    )

    nome_arq    = f"alerta_{moeda}.png"
    caminho_arq = f"docs/{nome_arq}"
    plt.savefig(caminho_arq, dpi=130, bbox_inches="tight", facecolor=BG)
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
            status, arq, emoji = gerar_alerta_visual(df, prev_amanha, var, moeda, conf_min, conf_max)

            
            for entrada in historico:
                if entrada['moeda'] == moeda.upper() and entrada.get('preco_real') is None:
                    entrada['preco_real'] = round(preco_hj, 2)
                    erro = preco_hj - entrada['previsao']
                    entrada['erro'] = round(erro, 2)
                    dentro_intervalo = entrada['confianca_min'] <= preco_hj <= entrada['confianca_max']
                    entrada['acerto'] = '✅' if dentro_intervalo else '❌'

            
            ja_existe = any(
                e['data'] == hoje and e['moeda'] == moeda.upper()
                for e in historico
            )
            if not ja_existe:
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
            else:
                logger.info(f"Previsao de {moeda.upper()} para {hoje} ja existe. Pulando append.")

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
from dotenv import load_dotenv
from trendbot_coleta import coletar_dados_historicos

try:
    import pandas_ta as ta
    _TA_DISPONIVEL = True
except ImportError:
    _TA_DISPONIVEL = False

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

    modelo = Prophet(
        daily_seasonality=True,
        interval_width=0.90,
        changepoint_prior_scale=0.05
    )

    usar_regressores = False
    if _TA_DISPONIVEL:
        try:
            df_prophet['rsi'] = ta.rsi(df_prophet['y'], length=14)
            df_prophet['sma7'] = ta.sma(df_prophet['y'], length=7)            
            df_prophet['rsi'] = (df_prophet['rsi'] - 50) / 50       
            df_prophet['sma7'] = df_prophet['sma7'] / df_prophet['y'] - 1  
            df_prophet = df_prophet.dropna()
            modelo.add_regressor('rsi')
            modelo.add_regressor('sma7')
            usar_regressores = True
            logger.info("Regressores técnicos (RSI + SMA7) adicionados ao modelo.")
        except Exception as e:
            logger.warning(f"Falha ao calcular indicadores técnicos: {e}. Usando Prophet padrão.")

    modelo.fit(df_prophet)
    future = modelo.make_future_dataframe(periods=1, include_history=False)

    if usar_regressores:
        future['rsi'] = df_prophet['rsi'].iloc[-1]
        future['sma7'] = df_prophet['sma7'].iloc[-1]

    forecast = modelo.predict(future)
    preco_atual   = df_prophet['y'].iloc[-1]
    previsao      = forecast['yhat'].iloc[0]
    confianca_min = forecast['yhat_lower'].iloc[0]
    confianca_max = forecast['yhat_upper'].iloc[0]
    return preco_atual, previsao, confianca_min, confianca_max

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
            status, arq, emoji = gerar_alerta_visual(df, prev_amanha, var, moeda, conf_min, conf_max)

            
            for entrada in historico:
                if entrada['moeda'] == moeda.upper() and entrada.get('preco_real') is None:
                    entrada['preco_real'] = round(preco_hj, 2)
                    erro = preco_hj - entrada['previsao']
                    entrada['erro'] = round(erro, 2)
                    dentro_intervalo = entrada['confianca_min'] <= preco_hj <= entrada['confianca_max']
                    entrada['acerto'] = '✅' if dentro_intervalo else '❌'

            ja_existe = any(
                e['data'] == hoje and e['moeda'] == moeda.upper()
                for e in historico
            )
            if not ja_existe:
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
            else:
                logger.info(f"Previsao de {moeda.upper()} para {hoje} ja existe. Pulando append.")

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