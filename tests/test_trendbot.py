"""Testes unitarios do TrendBot."""

import json
import math
import pandas as pd
import pytest
from datetime import datetime, timedelta

from trendbot_coleta import coletar_dados_historicos
from trendbot_engine import (
    treinar_e_prever,
    gerar_alerta_visual,
    carregar_historico,
    salvar_historico,
    salvar_dados_dashboard,
)


def test_coleta_retorna_dataframe():
    df = coletar_dados_historicos(coin="bitcoin", days=5)
    if df is None:
        pytest.skip("API CoinGecko rate limit excedido")
    assert not df.empty
    assert "Preco_USD" in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) >= 1


def test_coleta_moeda_invalida():
    df = coletar_dados_historicos(coin="moeda_inexistente_xyz", days=5)
    assert df is None


@pytest.fixture
def df_exemplo():
    datas = pd.date_range(end=datetime.now(), periods=100, freq="D")
    return pd.DataFrame(
        {"Preco_USD": [50000 + i * 10 + (i % 5) * 50 for i in range(100)]},
        index=pd.Index(datas, name="Data"),
    )


def test_treino_e_previsao_retorna_valores(df_exemplo):
    preco, previsao, cmin, cmax = treinar_e_prever(df_exemplo)
    assert isinstance(preco, float)
    assert isinstance(previsao, float)
    assert isinstance(cmin, float)
    assert isinstance(cmax, float)
    assert cmin <= previsao <= cmax
    assert preco > 0
    assert previsao > 0


def test_gerar_alerta_visual_compra_forte(df_exemplo):
    moeda = "bitcoin"
    preco_atual = df_exemplo["Preco_USD"].iloc[-1]
    previsao = preco_atual * 1.02
    variacao = 2.0
    conf_min = preco_atual * 0.98
    conf_max = preco_atual * 1.06

    alerta, nome_arq, emoji = gerar_alerta_visual(
        df_exemplo, previsao, variacao, moeda, conf_min, conf_max
    )
    assert alerta == "COMPRA FORTE"
    assert "🚀" in emoji
    assert nome_arq == "alerta_bitcoin.png"


def test_gerar_alerta_visual_venda(df_exemplo):
    moeda = "bitcoin"
    preco_atual = df_exemplo["Preco_USD"].iloc[-1]
    previsao = preco_atual * 0.97
    variacao = -3.0
    conf_min = preco_atual * 0.90
    conf_max = preco_atual * 1.02

    alerta, nome_arq, emoji = gerar_alerta_visual(
        df_exemplo, previsao, variacao, moeda, conf_min, conf_max
    )
    assert alerta == "VENDA"
    assert "🚨" in emoji
    assert nome_arq == "alerta_bitcoin.png"


def test_gerar_alerta_visual_neutro(df_exemplo):
    moeda = "bitcoin"
    preco_atual = df_exemplo["Preco_USD"].iloc[-1]
    previsao = preco_atual * 0.995
    variacao = -0.5
    conf_min = preco_atual * 0.95
    conf_max = preco_atual * 1.05

    alerta, nome_arq, emoji = gerar_alerta_visual(
        df_exemplo, previsao, variacao, moeda, conf_min, conf_max
    )
    assert alerta == "NEUTRO"
    assert "⚖️" in emoji


def test_gerar_alerta_visual_alta_leve(df_exemplo):
    moeda = "ethereum"
    preco_atual = df_exemplo["Preco_USD"].iloc[-1]
    previsao = preco_atual * 1.005
    variacao = 0.5
    conf_min = preco_atual * 0.97
    conf_max = preco_atual * 1.03

    alerta, nome_arq, emoji = gerar_alerta_visual(
        df_exemplo, previsao, variacao, moeda, conf_min, conf_max
    )
    assert alerta == "ALTA LEVE"
    assert "⬆️" in emoji
    assert nome_arq == "alerta_ethereum.png"


def test_carregar_historico_arquivo_inexistente(tmp_path):
    import os
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        hist = carregar_historico()
        assert hist == []
    finally:
        os.chdir(original)


def test_salvar_e_carregar_historico(tmp_path):
    import os
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        os.makedirs("docs", exist_ok=True)
        dados = [
            {
                "data": "01/01/2026",
                "moeda": "BTC",
                "previsao": 50000.0,
                "confianca_min": 48000.0,
                "confianca_max": 52000.0,
                "preco_real": None,
                "erro": None,
                "acerto": None,
            }
        ]
        salvar_historico(dados)
        carregado = carregar_historico()
        assert len(carregado) == 1
        assert carregado[0]["moeda"] == "BTC"
    finally:
        os.chdir(original)


def test_salvar_dados_dashboard(tmp_path):
    import os
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        os.makedirs("docs", exist_ok=True)
        dados = [
            {
                "moeda": "BTC",
                "preco": "50000.00",
                "previsao": "51000.00",
                "confianca_min": "48000.00",
                "confianca_max": "52000.00",
                "variacao": "+2.00",
                "status": "COMPRA FORTE",
                "emoji": "🚀",
                "imagem": "alerta_bitcoin.png",
            }
        ]
        salvar_dados_dashboard(dados)
        caminho = "docs/data.json"
        assert os.path.exists(caminho)
        with open(caminho) as f:
            conteudo = json.load(f)
        assert "ultima_atualizacao" in conteudo
        assert len(conteudo["ativos"]) == 1
    finally:
        os.chdir(original)


def test_formato_preco_na_geracao_grafico(df_exemplo):
    moeda = "cardano"
    preco_atual = df_exemplo["Preco_USD"].iloc[-1]
    previsao = preco_atual * 0.995
    variacao = -0.5
    conf_min = preco_atual * 0.93
    conf_max = preco_atual * 1.07

    alerta, nome_arq, emoji = gerar_alerta_visual(
        df_exemplo, previsao, variacao, moeda, conf_min, conf_max
    )
    assert nome_arq == "alerta_cardano.png"
