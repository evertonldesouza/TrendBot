"""Testes da linha de comando (trendbot/cli.py).

Rodam com fonte sintética para não depender de rede, e escrevem sempre em
diretório temporário — o CLI grava JSON e PNGs no disco.
"""

from __future__ import annotations

import json
import os

import pytest

from trendbot import cli


BASE = ["--fonte", "synthetic", "--dias", "400", "--sem-backtest", "--sem-graficos"]


def test_cli_gera_o_relatorio_e_devolve_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    codigo = cli.main([*BASE, "--out", str(tmp_path / "saida")])

    assert codigo == 0
    relatorio = tmp_path / "saida" / "relatorio.json"
    assert relatorio.exists()

    payload = json.loads(relatorio.read_text(encoding="utf-8"))
    assert payload["recomendacao"]["narrative"]["headline"]
    assert payload["modelo"]

    saida = capsys.readouterr().out
    assert "ALOCAÇÃO RECOMENDADA" in saida
    assert "Relatório gravado em" in saida


def test_cli_json_nao_imprime_resumo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert cli.main([*BASE, "--json", "--out", str(tmp_path / "s")]) == 0

    saida = capsys.readouterr().out
    assert "ALOCAÇÃO RECOMENDADA" not in saida
    assert "Relatório gravado em" in saida


def test_cli_gera_os_graficos_quando_pedido(tmp_path, monkeypatch):
    """Sem --sem-graficos, os PNGs têm de aparecer — inclusive o leque."""
    monkeypatch.chdir(tmp_path)
    saida = tmp_path / "com_graficos"

    assert cli.main(["--fonte", "synthetic", "--dias", "400",
                     "--sem-backtest", "--out", str(saida)]) == 0

    pngs = sorted(p.name for p in saida.glob("*.png"))
    assert "alocacao.png" in pngs
    assert "risco.png" in pngs
    assert any(p.startswith("projecao_") for p in pngs), f"sem leque: {pngs}"


def test_cli_respeita_os_ativos_da_linha_de_comando(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert cli.main([*BASE, "--ativos", "bitcoin,ethereum",
                     "--out", str(tmp_path / "s")]) == 0

    payload = json.loads((tmp_path / "s" / "relatorio.json").read_text())
    simbolos = set(payload["recomendacao"]["target_weights"])
    assert simbolos == {"BTC", "ETH", "USD"}, simbolos


def test_cli_aceita_a_carteira_atual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert cli.main([*BASE, "--carteira", "BTC:12000,ETH:5000,USD:3000",
                     "--out", str(tmp_path / "s")]) == 0

    payload = json.loads((tmp_path / "s" / "relatorio.json").read_text())
    atual = payload["recomendacao"]["current_weights"]
    assert atual["BTC"] > 0 and atual["ETH"] > 0, atual


def test_cli_rejeita_perfil_inexistente(tmp_path, monkeypatch):
    """O argparse limita as escolhas; erro de usuário, não exceção."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        cli.main([*BASE, "--perfil", "conservdor", "--out", str(tmp_path)])
    assert exc.value.code == 2


def test_cli_com_perfil_conservador(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert cli.main([*BASE, "--perfil", "conservador",
                     "--out", str(tmp_path / "s")]) == 0


@pytest.mark.parametrize("texto,esperado", [
    ("BTC:12000,ETH:5000", {"BTC": 12000.0, "ETH": 5000.0}),
    ("btc:100", {"BTC": 100.0}),
    (None, {}),
    ("", {}),
    ("sem-dois-pontos", {}),
])
def test_parse_portfolio(texto, esperado):
    assert cli._parse_portfolio(texto, 0.0, 0.0) == esperado


def test_parse_portfolio_ignora_valor_nao_numerico(caplog):
    """'BTC:dez-mil' não pode derrubar o comando."""
    with caplog.at_level("WARNING"):
        assert cli._parse_portfolio("BTC:dez-mil,ETH:5000", 0.0, 0.0) == {"ETH": 5000.0}
    assert "inválido" in caplog.text


def test_describe_source_name_traduz_e_devolve_o_proprio_se_desconhecido():
    assert cli.describe_source_name("coingecko") == "CoinGecko (tempo real)"
    assert cli.describe_source_name("synthetic") == "simulação determinística (demo)"
    assert cli.describe_source_name("outra-coisa") == "outra-coisa"


def test_resumo_imprime_alertas_e_ordens(tmp_path, monkeypatch, capsys):
    """_print_summary percorre os alertas, o hedge e as ordens."""
    monkeypatch.chdir(tmp_path)
    assert cli.main([*BASE, "--out", str(tmp_path / "s")]) == 0
    payload = json.loads((tmp_path / "s" / "relatorio.json").read_text())

    capsys.readouterr()
    cli._print_summary(payload)
    saida = capsys.readouterr().out

    assert "ORDENS" in saida
    assert "PROTEÇÃO" in saida or "CAIXA" in saida.upper()
    assert payload["recomendacao"]["narrative"]["headline"][:40] in saida


def test_cli_usa_capital_do_ambiente_quando_sem_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CAPITAL_INICIAL", "25000")
    monkeypatch.setenv("APORTE_MENSAL", "500")

    assert cli.main([*BASE, "--out", str(tmp_path / "s")]) == 0
    payload = json.loads((tmp_path / "s" / "relatorio.json").read_text())

    assert payload["recomendacao"]["hedge"]["cash_amount"] > 0
    os.environ.pop("CAPITAL_INICIAL", None)
