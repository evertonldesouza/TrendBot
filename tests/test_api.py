"""Testes da API FastAPI (app/main.py).

Cobrem o contrato HTTP de verdade — inclusive o que só aparece sob HTTP, como
a conversão de ValueError em 400 e o cache por parâmetros.

Rodam com fonte sintética para não depender de rede.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as api  # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    """Um cliente por módulo: o lifespan dispara o aquecimento, que é caro."""
    with TestClient(api.app) as c:
        yield c


def test_health_responde_sem_tocar_na_rede(cliente):
    r = cliente.get("/api/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ok"
    assert "versao" in corpo


def test_opcoes_expoje_ativos_perfis_e_fontes(cliente):
    r = cliente.get("/api/opcoes")
    assert r.status_code == 200
    corpo = r.json()

    simbolos = {a["symbol"] for a in corpo["ativos"]}
    assert {"BTC", "ETH", "SOL", "ADA"} <= simbolos
    assert "moderado" in {p["chave"] for p in corpo["perfis"]}
    assert "synthetic" in corpo["fontes"]
    assert corpo["caixa"]


def test_relatorio_devolve_recomendacao(cliente):
    r = cliente.get("/api/relatorio", params={
        "perfil": "moderado", "dias": 400, "fonte": "synthetic", "backtest": "false",
    })
    assert r.status_code == 200
    corpo = r.json()

    assert corpo["recomendacao"], "relatório sem recomendação"
    assert corpo["recomendacao"]["narrative"]["headline"]
    assert "modelo" in corpo
    assert corpo["meta"]["fonte_legivel"]


def test_relatorio_repetido_vem_do_cache(cliente):
    params = {"perfil": "conservador", "dias": 400, "fonte": "synthetic",
              "backtest": "false", "capital": 5000}

    primeiro = cliente.get("/api/relatorio", params=params)
    assert primeiro.json()["cache"]["hit"] is False

    segundo = cliente.get("/api/relatorio", params=params)
    assert segundo.json()["cache"]["hit"] is True, (
        "mesmos parâmetros deveriam cair no cache"
    )


def test_relatorio_converte_carteira_da_query_string(cliente):
    """'BTC:12000,USD:5000' vira posições; sem carteira, tudo em caixa."""
    r = cliente.get("/api/relatorio", params={
        "dias": 400, "fonte": "synthetic", "backtest": "false",
        "carteira": "BTC:12000,ETH:5000,USD:3000",
    })
    assert r.status_code == 200
    atual = r.json()["recomendacao"]["current_weights"]

    assert atual["BTC"] > 0 and atual["ETH"] > 0, (
        f"as posições da query string não viraram carteira atual: {atual}"
    )


def test_relatorio_ignora_trecho_malformado_da_carteira(cliente):
    """'lixo; BTC:12000' não pode derrubar a requisição."""
    r = cliente.get("/api/relatorio", params={
        "dias": 400, "fonte": "synthetic", "backtest": "false",
        "carteira": "lixo,BTC:nao-e-numero,BTC:12000,USD:1000",
    })
    assert r.status_code == 200
    assert r.json()["recomendacao"]["current_weights"]["BTC"] > 0


def test_perfil_inexistente_da_400_e_nao_500(cliente):
    r = cliente.get("/api/relatorio", params={
        "perfil": "nao-existe", "dias": 400, "fonte": "synthetic", "backtest": "false",
    })
    assert r.status_code == 400
    assert "detail" in r.json()


def test_index_entrega_o_html_do_painel(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert b"<html" in r.content.lower()


def test_arquivos_estaticos_sao_servidos(cliente):
    r = cliente.get("/static/app.js")
    assert r.status_code == 200
