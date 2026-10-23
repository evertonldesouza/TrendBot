"""Testes do shim de compatibilidade da v1 (trendbot_coleta.py).

Ele existe só para não quebrar quem importava ``coletar_dados_historicos``. O
contrato que importa é o formato de saída: coluna ``Preco_USD``, índice
``Data``.
"""

from __future__ import annotations

from unittest import mock

import pytest

import trendbot_coleta


def test_coleta_devolve_o_formato_da_v1():
    """Quem chamava na v1 espera Preco_USD e índice Data."""
    df = trendbot_coleta.coletar_dados_historicos("bitcoin", 400)

    assert df is not None
    assert "Preco_USD" in df.columns
    assert df.index.name == "Data"
    assert len(df) > 0
    assert df["Preco_USD"].dropna().gt(0).all()


@pytest.mark.parametrize("moeda,simbolo", [
    ("bitcoin", "BTC"),
    ("BTC", "BTC"),
    ("ethereum", "ETH"),
])
def test_coleta_aceita_nome_e_simbolo(moeda, simbolo):
    df = trendbot_coleta.coletar_dados_historicos(moeda, 400)
    assert df is not None
    # a coluna vira Preco_USD, então o símbolo só aparece no log/índice
    assert len(df) > 0


def test_coleta_sem_argumentos_cai_nas_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("MOEDAS_ALVO", "solana,cardano")
    monkeypatch.setenv("DIAS_HISTORICO", "300")
    monkeypatch.setenv("FONTE_DADOS", "synthetic")

    from trendbot.data import MarketData, simulate_market

    # devolve um MarketData de verdade, mas inspecionando a chamada
    with mock.patch.object(trendbot_coleta, "build_market_data",
                           return_value=MarketData(
                               close=simulate_market(["SOL"], days=300, seed=1),
                               source="synthetic")) as bmd:
        df = trendbot_coleta.coletar_dados_historicos()

        df = trendbot_coleta.coletar_dados_historicos()

    assert df is not None
    chamada = bmd.call_args
    # primeira moeda da lista, e os dias do ambiente
    assert chamada.kwargs["days"] == 300
    assert [a.symbol for a in chamada.args[0]] == ["SOL"]


def test_coleta_devolve_none_quando_nao_ha_dados():
    """Sem dados, None — e não um DataFrame vazio que o chamador não trata."""
    from trendbot.data import MarketData
    import pandas as pd

    with mock.patch.object(trendbot_coleta, "build_market_data",
                           return_value=MarketData(close=pd.DataFrame(), source="synthetic")):
        assert trendbot_coleta.coletar_dados_historicos("bitcoin", 30) is None


def test_coleta_devolve_none_quando_o_ativo_vem_fora_do_frame():
    from trendbot.data import MarketData, simulate_market

    # dados existem, mas sem a coluna do ativo pedido
    with mock.patch.object(trendbot_coleta, "build_market_data",
                           return_value=MarketData(
                               close=simulate_market(["ETH"], days=100, seed=1),
                               source="synthetic")):
        assert trendbot_coleta.coletar_dados_historicos("bitcoin", 100) is None
