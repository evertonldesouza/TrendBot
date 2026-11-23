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


@pytest.mark.parametrize("metodo,entrada", [
    ("get", {"dias": -5}),
    ("get", {"dias": 100_000_000}),
    ("get", {"ativos": ",".join(["bitcoin"] * 33)}),
    ("get", {"capital": "inf"}),
    ("post", {"dias": 199}),
    ("post", {"dias": 3001}),
    ("post", {"ativos": ["bitcoin"] * 33}),
    ("post", {"ativos": ["a" * 65]}),
    ("post", {"carteira": {"posicoes": {"BTC": -10}}}),
    ("post", {"carteira": {"posicoes": {str(i): 1 for i in range(33)}}}),
])
def test_relatorio_rejeita_entradas_fora_dos_limites_sem_calcular(monkeypatch, metodo, entrada):
    """GET e POST validam antes de acionar o pipeline de previsão."""
    def nao_calcular(_):
        pytest.fail("entrada inválida chegou ao cálculo")

    monkeypatch.setattr(api, "_montar_relatorio", nao_calcular)
    c = TestClient(api.app)  # sem lifespan: não dispara o aquecimento
    if metodo == "get":
        resposta = c.get("/api/relatorio", params=entrada)
    else:
        resposta = c.post("/api/relatorio", json=entrada)
    assert resposta.status_code == 422
    assert resposta.json()["detail"] == "Parâmetros inválidos."


def test_relatorio_nao_expoe_erros_internos(monkeypatch):
    def falhar(_):
        raise RuntimeError("segredo interno não pode aparecer")

    monkeypatch.setattr(api, "_montar_relatorio", falhar)
    api._CACHE.clear()
    c = TestClient(api.app)
    r = c.post("/api/relatorio", json={"dias": 400})
    assert r.status_code == 500
    assert r.json()["detail"] == "Falha interna ao gerar relatório."
    assert "segredo interno" not in r.text


def test_relatorio_nao_expoe_valueerror_interno(monkeypatch):
    def falhar(_):
        raise ValueError("detalhe interno não pode aparecer")

    monkeypatch.setattr(api, "_montar_relatorio", falhar)
    api._CACHE.clear()
    r = TestClient(api.app).post("/api/relatorio", json={"dias": 400})
    assert r.status_code == 400
    assert "detalhe interno" not in r.text


def test_nucleo_compartilhado_e_unico_arquivo_exposto_em_comum():
    c = TestClient(api.app)
    js = c.get("/comum/comum.js")
    assert js.status_code == 200
    assert "global.TB" in js.text
    assert c.get("/comum/index.html").status_code == 404
    assert c.get("/comum/data.json").status_code == 404


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-Infinity"])
def test_post_nao_aceita_valores_financeiros_nao_finitos(valor):
    resposta = TestClient(api.app).post(
        "/api/relatorio", content='{"carteira":{"capital":' + valor + '}}',
        headers={"content-type": "application/json"},
    )
    assert resposta.status_code == 422
    assert resposta.json()["detail"] == "Parâmetros inválidos."


def test_health_nao_expoe_erro_do_aquecimento(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    def falhar(_):
        raise RuntimeError("informação interna")

    class ThreadImediata:
        def __init__(self, target, **_):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(api, "threading", SimpleNamespace(Thread=ThreadImediata))
    monkeypatch.setattr(api, "_montar_relatorio", falhar)
    monkeypatch.setattr(api, "_WARMUP", {"status": "pendente", "erro": None})

    async def executar():
        async with api.lifespan(api.app):
            assert api.health()["aquecimento"]["erro"] == "Falha no aquecimento."
            assert "informação interna" not in str(api.health())

    asyncio.run(executar())
