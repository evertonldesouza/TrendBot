"""Testes do núcleo quantitativo do TrendBot.

Rodam 100% offline (sem depender de CoinGecko/Binance) usando o gerador
sintético determinístico. ``pytest tests/ -v``
"""

from __future__ import annotations

import pathlib
import re

import numpy as np
import pandas as pd
import pytest
from datetime import datetime

from trendbot import backtest as bt
from trendbot import indicators as ind
from trendbot import risk as rk
from trendbot.advisor import (build_advice, build_orders, contribution_plan,
                              equity_exposure, target_asset_weights)
from trendbot.assets import CASH, resolve_asset, resolve_assets
from trendbot.config import PROFILES, PortfolioState, Settings, get_profile
from trendbot.data import (MarketData, build_market_data, market_data_from_prices,
                           simulate_market)
from trendbot.forecast import (build_features, forecast_asset, forecast_universe,
                               HORIZONS)

DIAS = 700
SEMENTE = 20260101


@pytest.fixture(scope="module")
def preços() -> pd.DataFrame:
    return simulate_market(["BTC", "ETH", "SOL", "ADA"], days=DIAS, seed=SEMENTE)


@pytest.fixture(scope="module")
def mercado(preços) -> MarketData:
    return market_data_from_prices(preços, source="synthetic")


@pytest.fixture(scope="module")
def previsões(mercado):
    return forecast_universe(mercado, horizons=HORIZONS)


# ---------------------------------------------------------------------------
# Ativos
# ---------------------------------------------------------------------------

def test_resolve_asset_aceita_id_e_ticker():
    assert resolve_asset("bitcoin").symbol == "BTC"
    assert resolve_asset("BTC").symbol == "BTC"
    assert resolve_asset("btc").key == "bitcoin"
    assert resolve_asset("USD").is_cash


def test_resolve_assets_remove_duplicatas():
    ativos = resolve_assets(["bitcoin", "BTC", "ethereum"])
    assert [a.symbol for a in ativos] == ["BTC", "ETH"]


def test_resolve_assets_vazio_levanta_erro():
    with pytest.raises(ValueError):
        resolve_assets([])


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------

def test_simulacao_e_deterministica():
    a = simulate_market(["BTC"], days=400, seed=7)
    b = simulate_market(["BTC"], days=400, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_simulacao_produz_estatisticas_plausiveis():
    precos = simulate_market(["BTC", "ETH", "SOL"], days=900, seed=99)
    ret = precos.pct_change().dropna()
    vol = ret.std() * np.sqrt(365)
    assert 0.4 < vol["BTC"] < 1.2, "volatilidade do BTC fora da faixa realista"
    corr = ret.corr()
    media_fora_diag = corr.to_numpy()[~np.eye(len(corr), dtype=bool)].mean()
    assert 0.35 < media_fora_diag < 0.97, "correlações irreais entre cripto"
    assert (precos > 0).all().all()


def test_market_data_filtra_e_ordena():
    md = market_data_from_prices(
        pd.DataFrame({"BTC": [1.0, 2.0, 3.0]},
                     index=pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"])))
    assert md.close.index.is_monotonic_increasing
    assert md.last_date == pd.Timestamp("2024-01-03")


def test_build_market_data_cai_para_simulacao_sem_rede(tmp_path, monkeypatch):
    """Sem provedor nenhum, cai na simulação — e avisa.

    Cuidado: este teste já passou "por acidente", porque o CI não conseguia
    falar com a CoinGecko (HTTP 401 por range inválido). No momento em que a
    busca voltou a funcionar, ele quebrou. A ausência de rede tem de ser
    simulada de forma explícita, nunca dependente do ambiente — do contrário o
    teste mede a sorte da máquina, não o comportamento do código.
    """
    from trendbot import data as modulo
    from trendbot.assets import resolve_assets

    monkeypatch.setattr(modulo, "_http_get_json", lambda *args, **kwargs: None)

    md = build_market_data(
        resolve_assets(["bitcoin", "ethereum"]), days=400,
        source="coingecko", cache_dir=str(tmp_path), data_dir=str(tmp_path),
        seed=5, allow_stale=False,
    )
    assert not md.close.empty
    assert md.source == "synthetic"
    assert md.warnings


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def test_rsi_fica_entre_0_e_100(preços):
    rsi = ind.rsi(preços["BTC"])
    assert rsi.dropna().between(0, 100).all()


def test_rsi_sobe_em_tendencia_de_alta():
    s = pd.Series(np.linspace(100, 200, 60))
    assert ind.rsi(s).iloc[-1] > 70


def test_media_movel_e_volatilidade(preços):
    assert ind.sma(preços["BTC"], 20).iloc[-1] > 0
    vol = ind.realized_vol(preços["BTC"].pct_change(), 30)
    assert 0.05 < vol.dropna().iloc[-1] < 3.0


def test_drawdown_e_max_drawdown():
    s = pd.Series([100, 120, 60, 90.0])
    assert ind.max_drawdown(s) == pytest.approx(-0.5)
    assert ind.drawdown(s).iloc[-1] == pytest.approx(-0.25)


def test_snapshot_devolve_campos_esperados(preços):
    snap = ind.build_indicator_snapshot(preços["BTC"])
    for campo in ("preco", "rsi14", "vol30d", "drawdown_atual", "posicao_faixa_90d"):
        assert campo in snap
        assert np.isfinite(snap[campo])


# ---------------------------------------------------------------------------
# Previsão
# ---------------------------------------------------------------------------

def test_features_sem_informacao_do_futuro(preços):
    """Mudar o último preço não pode alterar as features de dias anteriores."""
    f1 = build_features(preços["BTC"])
    alterado = preços["BTC"].copy()
    alterado.iloc[-1] *= 1.5
    f2 = build_features(alterado)
    pd.testing.assert_frame_equal(f1.iloc[:-1], f2.iloc[:-1])


def test_previsao_devolve_horizontes_e_quantis_coerentes(mercado):
    fc, _ = forecast_universe(mercado, horizons=HORIZONS)
    for simbolo, f in fc.items():
        assert set(f.horizons) == set(HORIZONS)
        for h, hz in f.horizons.items():
            assert hz.lower <= hz.median_return <= hz.upper
            assert 0.0 <= hz.prob_up <= 1.0
            assert hz.cvar95 >= hz.var95 - 1e-9
        assert -1.0 <= f.conviction <= 1.0
        assert 0.0 <= f.model_weight <= 0.75


def test_intervalo_de_30d_e_mais_largo_que_o_de_1d(mercado):
    fc, _ = forecast_universe(mercado, horizons=HORIZONS)
    for f in fc.values():
        largura1 = f.horizons[1].upper - f.horizons[1].lower
        largura30 = f.horizons[30].upper - f.horizons[30].lower
        assert largura30 > largura1


def test_modelo_detecta_sinal_quando_ele_existe():
    """Série com fator de tendência lento: o modelo deve ganhar do ingênuo."""
    rng = np.random.default_rng(3)
    n = 1400
    mu = np.zeros(n)
    r = np.zeros(n)
    for i in range(1, n):
        mu[i] = 0.985 * mu[i - 1] + rng.normal(0, 0.0015)
        r[i] = 0.9 * mu[i] + rng.normal(0, 0.025)
    preco = pd.Series(100 * np.exp(np.cumsum(r)),
                      index=pd.date_range("2022-01-01", periods=n, freq="D"))
    f = forecast_asset(preco, symbol="MOM")
    assert f.skill > 0.0, "modelo deveria detectar o momentum sintético"
    assert f.model_weight > 0.0


def test_modelo_confia_mais_quando_ha_sinal_do_que_no_ruido():
    """Mesma forma de série, com e sem fator de tendência previsível.

    O teste é comparativo de propósito: habilidade fora da amostra é uma
    estimativa ruidosa, então exigir "zero" em uma série de ruído deixaria o
    teste instável. O que precisa valer é a ordem de grandeza da confiança.
    """
    rng = np.random.default_rng(3)
    n = 1400
    idx = pd.date_range("2022-01-01", periods=n, freq="D")

    mu = np.zeros(n)
    r_mom = np.zeros(n)
    for i in range(1, n):
        mu[i] = 0.985 * mu[i - 1] + rng.normal(0, 0.0015)
        r_mom[i] = 0.9 * mu[i] + rng.normal(0, 0.025)
    com_sinal = forecast_asset(
        pd.Series(100 * np.exp(np.cumsum(r_mom)), index=idx), symbol="MOM")

    ruido = rng.normal(0, 0.025, n)
    sem_sinal = forecast_asset(
        pd.Series(100 * np.exp(np.cumsum(ruido)), index=idx), symbol="RUIDO")

    assert com_sinal.skill > sem_sinal.skill
    assert com_sinal.model_weight > sem_sinal.model_weight
    assert sem_sinal.model_weight < 0.25, "ruído não deve gerar convicção"


def test_cobertura_dos_intervalos_fica_perto_do_alvo(mercado):
    _, card = forecast_universe(mercado, horizons=HORIZONS)
    assert 0.70 <= card.avg_coverage <= 1.0


def test_previsao_com_historico_curto_usa_fallback():
    preco = pd.Series(np.linspace(100, 120, 100),
                      index=pd.date_range("2024-01-01", periods=100, freq="D"))
    with pytest.raises(ValueError):
        forecast_asset(preco, symbol="CURTO")


# ---------------------------------------------------------------------------
# Risco
# ---------------------------------------------------------------------------

def test_covariancia_e_simetrica_e_positiva(preços):
    cov = rk.estimate_covariance(preços.pct_change().dropna())
    assert np.allclose(cov.to_numpy(), cov.to_numpy().T)
    assert np.all(np.linalg.eigvalsh(cov.to_numpy()) > -1e-8)


def test_shrinkage_aproxima_correlacoes_da_media(preços):
    ret = preços.pct_change().dropna()
    bruta = rk.ewma_covariance(ret)
    contraida = rk.estimate_covariance(ret, shrink=1.0)
    def dispersao(m):
        c = m.to_numpy() / np.outer(np.sqrt(np.diag(m)), np.sqrt(np.diag(m)))
        off = c[~np.eye(len(c), dtype=bool)]
        return float(off.std())
    assert dispersao(contraida) <= dispersao(bruta) + 1e-6


def test_caixa_nao_e_renormalizado(preços):
    """O colchão de caixa precisa reduzir o risco medido, não desaparecer."""
    ret = preços.pct_change().dropna()
    cov = rk.estimate_covariance(ret)
    cheio = rk.portfolio_risk({"BTC": 1.0}, ret, cov)
    com_caixa = rk.portfolio_risk({"BTC": 0.4, CASH: 0.6}, ret, cov)
    assert com_caixa.volatility < cheio.volatility * 0.5


def test_contribuicoes_de_risco_somam_um(preços):
    ret = preços.pct_change().dropna()
    cov = rk.estimate_covariance(ret)
    pesos = {c: 0.25 for c in ret.columns}
    r = rk.portfolio_risk(pesos, ret, cov)
    assert sum(r.risk_contributions.values()) == pytest.approx(1.0, abs=1e-6)


def test_paridade_de_risco_igualiza_contribuicoes(preços):
    ret = preços.pct_change().dropna()
    cov = rk.estimate_covariance(ret)
    w = rk.risk_parity_weights(cov)
    contrib = rk.portfolio_risk(w.to_dict(), ret, cov, normalize=True).risk_contributions
    valores = np.array(list(contrib.values()))
    assert valores.std() < 0.05


def test_estresse_respeita_o_colchao_de_caixa(preços):
    ret = preços.pct_change().dropna()
    cov = rk.estimate_covariance(ret)
    conservador = rk.stress_test({"BTC": 0.2, CASH: 0.8}, ret, cov)
    agressivo = rk.stress_test({"BTC": 1.0}, ret, cov)
    pior_cons = min(s["impacto_base"] for s in conservador)
    pior_agr = min(s["impacto_base"] for s in agressivo)
    assert pior_cons > pior_agr
    assert all(s["impacto_base"] >= -0.95 for s in agressivo)


# ---------------------------------------------------------------------------
# Alocação / orientação
# ---------------------------------------------------------------------------

def test_exposicao_cresce_com_a_conviccao():
    perfil = get_profile("moderado")
    defensivo = equity_exposure(perfil, -1.0, sleeve_vol=1.0, crisis_pressure=0.0)
    neutro = equity_exposure(perfil, 0.0, sleeve_vol=1.0, crisis_pressure=0.0)
    otimista = equity_exposure(perfil, 1.0, sleeve_vol=1.0, crisis_pressure=0.0)
    assert defensivo < neutro < otimista


def test_exposicao_respeita_o_teto_de_volatilidade():
    perfil = get_profile("conservador")
    exp = equity_exposure(perfil, 1.0, sleeve_vol=0.9, crisis_pressure=0.0)
    assert exp * 0.9 <= perfil.max_vol + 1e-9


def test_pesos_respeitam_teto_de_concentracao(preços):
    ret = preços.pct_change().dropna()
    cov = rk.estimate_covariance(ret)
    perfil = get_profile("conservador")
    from trendbot.forecast import AssetForecast
    forecasts = {
        s: AssetForecast(s, 100.0, {}, "neutro", {}, 0.0, 0.5, 0.9, 0, 0.3, 0.5)
        for s in cov.columns
    }
    w = target_asset_weights(cov, forecasts, perfil, conviction=1.0)
    assert w.max() <= perfil.max_asset_weight + 1e-9
    assert w.sum() == pytest.approx(1.0, abs=1e-6)


def test_ordens_respeitam_banda_de_rebalanceamento():
    perfil = get_profile("moderado")
    ordens = build_orders({"BTC": 0.40, CASH: 0.60},
                          {"BTC": 0.42, CASH: 0.58}, 10_000, perfil)
    btc = next(o for o in ordens if o.symbol == "BTC")
    assert btc.action == "MANTER"


def test_ordens_somam_zero():
    perfil = get_profile("moderado")
    alvo = {"BTC": 0.3, "ETH": 0.2, CASH: 0.5}
    atual = {"BTC": 0.8, "ETH": 0.0, CASH: 0.2}
    ordens = build_orders(alvo, atual, 10_000, perfil)
    assert sum(o.amount for o in ordens) == pytest.approx(0.0, abs=1.0)


def test_aporte_vai_primeiro_para_o_que_esta_abaixo_do_alvo():
    alvo = {"BTC": 0.5, "ETH": 0.5}
    atual = {"BTC": 0.9, "ETH": 0.1}
    plano = contribution_plan(alvo, atual, 1000.0, 10_000.0)
    eth = next(p for p in plano if p["symbol"] == "ETH")
    btc = next((p for p in plano if p["symbol"] == "BTC"), {"valor": 0.0})
    assert eth["valor"] > btc["valor"]


def test_carteira_recomendada_bate_o_alvo_de_volatilidade(mercado, previsões):
    forecasts, card = previsões
    for chave, perfil in PROFILES.items():
        carteira = PortfolioState(capital=50_000, monthly_contribution=1000,
                                  holdings={"BTC": 50_000}, cash=0.0)
        advice = build_advice(mercado, forecasts, card, perfil, carteira,
                              Settings.from_env())
        vol = advice.risk_target["volatility"]
        assert vol <= perfil.max_vol + 1e-6, f"{chave}: vol {vol} acima do teto"
        soma = sum(advice.target_weights.values())
        assert soma == pytest.approx(1.0, abs=1e-6)
        assert advice.target_weights[CASH] >= perfil.cash_floor - 1e-6


def test_ordens_fecham_com_a_carteira_alvo(mercado, previsões):
    forecasts, card = previsões
    perfil = get_profile("moderado")
    carteira = PortfolioState(capital=20_000, monthly_contribution=0,
                              holdings={"BTC": 20_000}, cash=0.0)
    advice = build_advice(mercado, forecasts, card, perfil, carteira, Settings.from_env())
    if not advice.orders:
        pytest.skip("sem ordens neste cenário")
    assert sum(o.amount for o in advice.orders) == pytest.approx(0.0, abs=1.0)


def test_alertas_aparecem_quando_modelo_efraco(mercado, previsões):
    forecasts, card = previsões
    if card.avg_skill >= -0.05:
        pytest.skip("modelo com habilidade neste cenário")
    advice = build_advice(mercado, forecasts, card, get_profile("moderado"),
                          PortfolioState(capital=10_000, cash=10_000), Settings.from_env())
    assert any("vantagem" in a.title.lower() for a in advice.alerts)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def test_backtest_devolve_estrategias_e_curvas(preços):
    resultado = bt.run_backtest(preços, get_profile("moderado"), initial=10_000.0)
    nomes = [e["name"] for e in resultado["estrategias"]]
    assert any("TrendBot" in n for n in nomes)
    assert any("1/N" in n for n in nomes)
    for e in resultado["estrategias"]:
        assert e["equity_curve"]
        assert e["final_value"] > 0
        assert e["max_drawdown"] <= 0


def test_backtest_caixa_na_alocacao_reduz_queda(preços):
    """A carteira orientada não pode ter queda pior que 100% cripto."""
    resultado = bt.run_backtest(preços, get_profile("conservador"), initial=10_000.0)
    tb = resultado["estrategias"][0]
    um_n = next(e for e in resultado["estrategias"] if "1/N" in e["name"])
    assert abs(tb["max_drawdown"]) < abs(um_n["max_drawdown"])


def test_backtest_sem_historico_suficiente_levanta_erro():
    curto = simulate_market(["BTC"], days=120, seed=1)
    with pytest.raises(ValueError):
        bt.run_backtest(curto, get_profile("moderado"))


# ---------------------------------------------------------------------------
# Relatório / integração
# ---------------------------------------------------------------------------

def test_payload_e_serializavel(mercado, previsões):
    import json
    from trendbot import report
    forecasts, card = previsões
    perfil = get_profile("moderado")
    advice = build_advice(mercado, forecasts, card, perfil,
                          PortfolioState(capital=10_000, cash=10_000),
                          Settings.from_env())
    payload = report.build_payload(mercado, forecasts, card, advice, None,
                                   Settings.from_env(), perfil)
    texto = json.dumps(payload, default=str)
    assert len(texto) > 1000
    assert payload["meta"]["perfil"]["chave"] == "moderado"


def test_cli_gera_relatorio(tmp_path):
    from trendbot.cli import main
    codigo = main([
        "--fonte", "synthetic", "--dias", "600", "--perfil", "moderado",
        "--capital", "20000", "--aporte", "500",
        "--ativos", "bitcoin,ethereum,solana",
        "--out", str(tmp_path), "--json", "--sem-graficos", "--sem-backtest",
    ])
    assert codigo == 0
    assert (tmp_path / "relatorio.json").exists()


# ---------------------------------------------------------------------------
# API / painel
# ---------------------------------------------------------------------------

def _bloco_state_do_js() -> str:
    """Extrai o objeto ``state`` do painel (app/static/app.js)."""
    import re
    raiz = pathlib.Path(__file__).resolve().parents[1]
    js = (raiz / "app" / "static" / "app.js").read_text(encoding="utf-8")
    inicio = js.index("const state = {")
    fim = js.index("};", inicio)
    return js[inicio:fim]


def _campo(bloco: str, nome: str) -> str:
    import re
    m = re.search(rf"\b{nome}:\s*(.+)", bloco)
    if not m:
        raise AssertionError(f"campo '{nome}' não encontrado no state do painel")
    return m.group(1).strip().rstrip(",")


def test_defaults_do_painel_e_da_api_estao_em_sincronia():
    """O aquecimento do startup só acerta o cache se os defaults casarem.

    Se o painel e a API divergirem, o primeiro clique do usuário não encontra
    o payload pré-computado e paga o custo inteiro (sondagem de rede +
    previsões + backtest). Este teste transforma essa divergência silenciosa
    em falha explícita.
    """
    pytest.importorskip("fastapi", reason="fastapi não instalado")
    import sys
    raiz = pathlib.Path(__file__).resolve().parents[1]
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    try:
        from app.main import PADRAO_ATIVOS, PADRAO_CAIXA, PADRAO_POSICOES, RelatorioRequest
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"não foi possível importar a app: {exc}")

    bloco = _bloco_state_do_js()
    import re

    perfil_js = _campo(bloco, "perfil").strip('"')
    ativos_js = re.findall(r'"([^"]+)"', _campo(bloco, "ativos"))
    dias_js = int(_campo(bloco, "dias"))
    capital_js = float(_campo(bloco, "capital"))
    aporte_js = float(_campo(bloco, "aporte"))
    caixa_js = float(_campo(bloco, "caixa"))
    posicoes_js = {
        s.upper(): float(v)
        for s, v in re.findall(r'(\w+):\s*([\d_]+)', _campo(bloco, "posicoes"))
    }

    req = RelatorioRequest()
    assert req.perfil == perfil_js
    assert list(req.ativos or []) == ativos_js == list(PADRAO_ATIVOS)
    assert req.dias == dias_js
    assert req.carteira.capital == capital_js
    assert req.carteira.aporte_mensal == aporte_js
    assert req.carteira.caixa == caixa_js == PADRAO_CAIXA
    assert {k: v for k, v in req.carteira.posicoes.items()} == posicoes_js == PADRAO_POSICOES


# ---------------------------------------------------------------------------
# Regressões
# ---------------------------------------------------------------------------

def test_seed_por_simbolo_e_estavel_entre_processos():
    """Golden value: trava a correção do bug do hash() randomizado.

    ``hash()`` de string em Python varia por processo (PYTHONHASHSEED). Usá-lo
    para derivar o seed de cada símbolo fazia a "simulação determinística"
    gerar séries diferentes a cada execução — a suíte falhava em ~25% das
    rodadas e nenhum relatório era reproduzível. O valor abaixo só muda se a
    forma de derivar o seed mudar (o que é uma quebra deliberada).
    """
    from trendbot.data import _symbol_seed

    assert _symbol_seed("BTC", 7) == 1890574365
    assert _symbol_seed("ETH", 7) == 626124320
    # símbolos diferentes, mesma semente global, seeds diferentes
    assert _symbol_seed("BTC", 7) != _symbol_seed("ETH", 7)
    # mesmo símbolo, sementes globais diferentes, seeds diferentes
    assert _symbol_seed("BTC", 7) != _symbol_seed("BTC", 8)


def test_determinismo_nao_depende_do_hash_da_string():
    """Simula o que o hash randomizado causava: seeds derivados de forma estável."""
    a = simulate_market(["BTC", "ETH"], days=300, seed=7)
    b = simulate_market(["BTC", "ETH"], days=300, seed=7)
    pd.testing.assert_frame_equal(a, b)
    # e sementes diferentes produzem séries diferentes
    c = simulate_market(["BTC", "ETH"], days=300, seed=8)
    assert not np.allclose(a["BTC"].to_numpy(), c["BTC"].to_numpy())


def test_nenhum_peso_alvo_e_negativo_em_qualquer_perfil(mercado, previsões):
    """Caixa negativo já apareceu em produção (-0,01%) por arredondamento.

    Em perfis agressivos a exposição vai a 100% e o resíduo do arredondamento
    empurrava o caixa para baixo de zero, o que virava um peso absurdo no
    painel. Este teste cobre os quatro perfis.
    """
    forecasts, card = previsões
    for chave, perfil in PROFILES.items():
        carteira = PortfolioState(capital=30_000, monthly_contribution=500,
                                  holdings={"BTC": 30_000}, cash=0.0)
        advice = build_advice(mercado, forecasts, card, perfil, carteira,
                              Settings.from_env())
        for simbolo, peso in advice.target_weights.items():
            assert peso >= 0.0, f"{chave}: peso negativo em {simbolo} ({peso})"
        assert advice.target_weights[CASH] >= perfil.cash_floor - 1e-6
        assert sum(advice.target_weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_relatorio_publicado_declara_a_origem_dos_dados():
    """O dashboard do Pages precisa dizer se os dados são simulados.

    Já publicamos preços da simulação (âncoras redondas: BTC 82.000,00) sem
    nenhum aviso, porque o data.json não tinha campo de fonte e o dashboard
    nunca mencionava origem. Se o fetch cair no fallback, o relatório tem de
    dizer isso — do contrário parece dado de mercado real.
    """
    import json
    import os
    import re

    fonte_mod = pathlib.Path("trendbot_engine.py").read_text(encoding="utf-8")
    # data.json precisa expor a fonte junto dos ativos
    assert '"fonte"' in fonte_mod
    assert "describe_source" in fonte_mod
    assert "simulada" in fonte_mod

    # e o dashboard precisa renderizar o aviso
    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")
    assert "renderFonte" in js and "fonte-banner" in js
    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
    assert 'id="fonte-banner"' in html


def test_tentativas_de_rede_sao_configuraveis_e_o_job_diario_insiste_mais():
    """Uma tentativa só derrubava o relatório diário para a simulação.

    A API pública da CoinGecko responde 429 com frequência a IPs de datacenter
    (GitHub Actions). Com tries=1 o 429 encerrava a busca e o relatório caía
    na simulação. O padrão continua 1 (latência do relatório interativo), mas
    o caminho do job diário tem de insistir mais.
    """
    import inspect
    import os

    from trendbot import data as modulo_data
    from trendbot.config import Settings

    assert "network_tries" in inspect.signature(modulo_data.build_market_data).parameters
    assert modulo_data.build_market_data.__defaults__ is not None

    # padrão: sem espera extra para quem está olhando o painel
    assert Settings().network_tries == 1

    # job diário: mais tentativas
    os.environ["TENTATIVAS_REDE"] = "4"
    try:
        assert Settings.from_env().network_tries == 4
    finally:
        os.environ.pop("TENTATIVAS_REDE", None)


def test_coingecko_respeita_o_limite_de_historico_da_api_publica(monkeypatch, tmp_path):
    """A API pública da CoinGecko recusa mais de 365 dias.

    Pedir 1095 devolvia HTTP 401 (error_code 10012, "exceeds the allowed time
    range") e derrubava a busca inteira para a simulação. Com chave, o pedido
    original é preservado.
    """
    from trendbot import data as modulo
    from trendbot.assets import resolve_asset

    chamadas: list[dict] = []

    def http_falso(url, params=None, timeout=8, tries=1):
        chamadas.append(dict(params or {}))
        return None

    monkeypatch.setattr(modulo, "_http_get_json", http_falso)
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    asset = resolve_asset("bitcoin")

    modulo.fetch_coingecko(asset, days=1095, cache_dir=str(tmp_path))
    assert chamadas, "deveria ter chamado a API"
    assert chamadas[-1]["days"] == modulo.LIMITE_DIAS_COINGECKO_PUBLICO
    assert "interval" not in chamadas[-1], "interval é de plano pago, a pública recusa"
    assert "x_cg_demo_api_key" not in chamadas[-1]

    # com chave, mantém o range pedido sem cortar
    monkeypatch.setenv("COINGECKO_API_KEY", "demo-key")
    modulo.fetch_coingecko(asset, days=1095, cache_dir=str(tmp_path / "b"))
    assert chamadas[-1]["days"] == 1095
    assert chamadas[-1]["x_cg_demo_api_key"] == "demo-key"

    # um pedido já dentro do limite não é mexido
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    modulo.fetch_coingecko(asset, days=180, cache_dir=str(tmp_path / "c"))
    assert chamadas[-1]["days"] == 180


# ---------------------------------------------------------------------------
# Dashboard: moeda canônica
# ---------------------------------------------------------------------------

def _aliases_de_moeda_do_dashboard() -> dict[str, str]:
    """Lê o mapa MOEDAS_CANONICAS de docs/script.js.

    Lê o arquivo de verdade em vez de repetir a tabela aqui: o que importa é
    que o dashboard consiga unificar os nomes, não que exista uma lista em
    Python.
    """
    import re

    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")
    bloco = re.search(r"const MOEDAS_CANONICAS = \{(.*?)\n\};", js, re.S)
    assert bloco, "MOEDAS_CANONICAS sumiu de docs/script.js"

    mapa: dict[str, str] = {}
    for simbolo, _nome, aliases in re.findall(
        r"(\w+):\s*\{\s*nome:\s*'([^']+)',\s*aliases:\s*\[([^\]]+)\]", bloco.group(1)
    ):
        for apelido in re.findall(r"'([^']+)'", aliases):
            mapa[apelido.strip().upper()] = simbolo
    return mapa


def test_toda_moeda_do_historico_e_do_dashboard_tem_nome_canonico():
    """Nenhum nome pode sobrar fora do mapa.

    historico.json acumula o padrão legado ("BITCOIN") e o atual ("BTC").
    Enquanto os dois não forem unificados, o filtro mostra o mesmo ativo duas
    vezes e a precisão por moeda dos cards zera (data.json usa "BTC").
    """
    import json

    mapa = _aliases_de_moeda_do_dashboard()
    assert mapa, "mapa de moedas vazio"

    historico = json.loads(pathlib.Path("docs/historico.json").read_text(encoding="utf-8"))
    dados = json.loads(pathlib.Path("docs/data.json").read_text(encoding="utf-8"))

    nomes = {str(h["moeda"]).strip().upper() for h in historico}
    nomes |= {str(a["moeda"]).strip().upper() for a in dados["ativos"]}

    desconhecidos = sorted(n for n in nomes if n not in mapa)
    assert not desconhecidos, f"moedas fora do mapa canônico: {desconhecidos}"


def test_nomes_legados_e_novos_colapsam_no_mesmo_simbolo():
    """O legado 'BITCOIN' e o atual 'BTC' precisam virar a mesma moeda.

    Foi exatamente isso que quebrou os cards: com o filtro por igualdade
    exata, o card do BTC mostrava 'Aguardando dados' mesmo com 34 previsões
    já resolvidas no histórico.
    """
    mapa = _aliases_de_moeda_do_dashboard()

    pares = [("BITCOIN", "BTC"), ("ETHEREUM", "ETH"), ("SOLANA", "SOL"), ("CARDANO", "ADA")]
    for legado, simbolo in pares:
        if legado in mapa:
            assert mapa[legado] == simbolo, f"{legado} deveria canonicalizar para {simbolo}"

    # Tem de ser dentro do corpo da função: checar a substring no arquivo
    # inteiro não pega nada, porque ela também aparece no filtro da tabela.
    import re

    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")
    corpo = re.search(r"function acertosPorMoeda\(historico, moeda\) \{(.*?)\n\}", js, re.S)
    assert corpo, "acertosPorMoeda sumiu de docs/script.js"
    assert "moedaCanonica(h.moeda)" in corpo.group(1), (
        "a precisão por moeda voltou a comparar nomes crus; o card do BTC "
        "mostra 'Aguardando dados' mesmo com histórico resolvido"
    )


# ---------------------------------------------------------------------------
# Autoavaliação do modelo com histórico curto
# ---------------------------------------------------------------------------

def _mercado_simulado(dias: int, seed: int = 20260101):
    from trendbot.data import MarketData, simulate_market

    precos = simulate_market(["BTC", "ETH", "SOL", "ADA"], days=dias, seed=seed)
    return MarketData(close=precos, source="synthetic")


def test_modelo_e_avaliado_mesmo_com_365_dias():
    """A API pública da CoinGecko limita o histórico a 365 dias.

    Nesse recorte a validação era pulada: as features comem ~180 dias de
    aquecimento, sobravam 5 pontos de teste (abaixo do mínimo de 25) e o card
    devolvia as sentinelas skill=-1 / cobertura=0. Agora o tamanho do treino
    cede para que sobre amostra de teste.
    """
    fc, card = forecast_universe(_mercado_simulado(365), horizons=(1,))

    assert card.observations > 0, (
        "a validação foi pulada: com 365 dias o modelo volta a não ser avaliado "
        "e o card reporta sentinelas como se fossem medição"
    )
    # -1.0 e 0% eram as sentinelas do caminho "sem dados"
    assert card.avg_skill != -1.0
    assert card.avg_coverage > 0.0


def test_historico_curto_diz_que_faltam_dados_e_nao_que_o_modelo_e_ruim():
    """Sem amostra de teste, o veredito não pode acusar o modelo.

    Dizer "sem habilidade" quando não houve uma única observação fora da
    amostra é pior que inútil: o usuário conclui que o modelo foi testado e
    reprovado, quando na verdade não foi testado.
    """
    fc, card = forecast_universe(_mercado_simulado(240), horizons=(1,))

    assert card.observations == 0
    assert "insuficiente" in card.verdict.lower()
    assert "sem habilidade" not in card.verdict.lower()


def test_avaliacao_com_poucos_pontos_avisa_que_e_ruidosa():
    """Estimativa com amostra curta precisa se dizer ruidosa."""
    fc, card = forecast_universe(_mercado_simulado(365), horizons=(1,))

    assert card.observations < 120
    assert any("ruidosa" in n.lower() for n in card.notes), card.notes


def test_historico_longo_nao_muda_o_tamanho_do_treino():
    """A regra só encurta o treino quando falta dado; com sobra, nada muda."""
    curto = forecast_universe(_mercado_simulado(730), horizons=(1,))[1]
    longo = forecast_universe(_mercado_simulado(1095), horizons=(1,))[1]

    assert curto.observations > 30
    assert longo.observations > curto.observations


# ---------------------------------------------------------------------------
# Dashboard: consistência da tabela e melhorias do histórico
# ---------------------------------------------------------------------------

def _corpo_da_funcao(js: str, nome: str) -> str:
    import re

    corpo = re.search(r"function " + nome + r"\(.*?\) \{(.*?)\n\}", js, re.S)
    assert corpo, f"{nome} sumiu de docs/script.js"
    return corpo.group(1)


def test_tabela_tem_o_mesmo_numero_de_colunas_em_todos_os_lugares():
    """Cabeçalho, linha renderizada e célula de 'vazio' precisam concordar.

    Eu mesmo quebrei isso: adicionei a coluna de erro % no HTML e esqueci o
    colspan do estado vazio no script.js, que ficou valendo 7 com 8 colunas.
    O sintoma é sutil — a tabela funciona e só a mensagem de 'nenhum
    registro' sai torta.
    """
    import re

    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")

    colunas = len(re.findall(r'<th scope="col">', html))
    assert colunas >= 7, f"cabeçalho com {colunas} colunas?"

    linha = _corpo_da_funcao(js, "linhaHistorico")
    tds = len(re.findall(r"<td ", linha))
    assert tds == colunas, f"cabeçalho tem {colunas} colunas, a linha renderiza {tds}"

    colspans = {int(n) for n in re.findall(r'colspan="(\d+)"', js + html)}
    assert colspans == {colunas}, f"colspan {colspans} não bate com {colunas} colunas"


def test_coluna_de_erro_relativo_existe_e_usa_o_erro_percentual():
    """O erro em dólar não compara ativos: 2 mil no BTC é 2,5%, na ADA é 900%."""
    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")

    assert "Erro %" in html, "a coluna de erro relativo sumiu do cabeçalho"

    linha = _corpo_da_funcao(js, "linhaHistorico")
    assert "erroPercentual(h)" in linha, (
        "a coluna de % voltou a usar o erro absoluto; comparar Bitcoin e "
        "Cardano em dólar não diz nada"
    )


def test_dashboard_declara_a_cobertura_realizada():
    """O rótulo 'Intervalo 90%' sem o acerto real induz o leitor ao erro.

    No histórico acumulado a cobertura é de ~97%: os intervalos são mais
    conservadores do que o nome sugere, e esconder isso superestima o risco.
    """
    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")

    assert 'id="cobertura-nota"' in html
    nota = _corpo_da_funcao(js, "atualizarCobertura")
    assert "acerto real" in nota


def test_linhas_tem_data_label_para_o_layout_de_celular():
    """Sem data-label, o layout em cards abaixo de 640px fica sem rótulos."""
    import re

    linha = _corpo_da_funcao(pathlib.Path("docs/script.js").read_text(encoding="utf-8"), "linhaHistorico")

    # <td\b([^>]*)> pega tanto "<td>" quanto "<td data-label=...>": com espaço
    # fixo no regex, a célula sem label escapava e o teste não pegava nada.
    tds = re.findall(r"<td\b([^>]*)>", linha)
    assert len(tds) >= 7, f"só {len(tds)} células encontradas"

    for attrs in tds:
        if "loading-cell" in attrs:
            continue
        assert "data-label=" in attrs, f"célula sem data-label: {attrs!r}"


# ---------------------------------------------------------------------------
# Honestidade do histórico e do painel
# ---------------------------------------------------------------------------

def test_previsao_simulada_nao_entra_no_historico_de_acertos(tmp_path, monkeypatch):
    """Previsão de dado simulado não pode ser conferida contra preço real.

    Ela entraria nas estatísticas de acerto como se fosse uma previsão de
    verdade. Já aconteceu: há entradas de 20/10/2026 com os valores-âncora do
    simulador convivendo com entradas reais.
    """
    import importlib.util
    from unittest import mock

    # o motor escreve docs/data.json e os PNGs de alerta de verdade, então o
    # teste roda num diretório descartável: sem isso, ele sobrescreve os dados
    # publicados com o resultado de uma simulação (aconteceu).
    (tmp_path / "docs").mkdir()
    origem = pathlib.Path(__file__).resolve().parent.parent / "trendbot_engine.py"
    monkeypatch.chdir(tmp_path)

    espec = importlib.util.spec_from_file_location("motor_compat", str(origem))
    motor = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(motor)

    with mock.patch.object(motor, "carregar_historico", return_value=[]), \
         mock.patch.object(motor, "salvar_historico") as salvar, \
         mock.patch.object(motor, "build_market_data") as bmd, \
         mock.patch.object(motor, "forecast_universe") as prever:

        bmd.return_value = _mercado_simulado(365)
        prever.return_value = forecast_universe(_mercado_simulado(365), horizons=(1,))

        motor.fluxo_principal()

    assert salvar.called, "o motor deveria ter chamado salvar_historico"
    gravado = salvar.call_args[0][0]
    assert gravado == [], (
        f"fonte simulada gravou {len(gravado)} entradas no histórico; elas "
        "seriam conferidas contra o preço real e virariam estatística"
    )


def test_mapa_de_moedas_do_python_e_do_dashboard_concordam():
    """Duas tabelas de nomes precisam bater: a do Python e a do dashboard.

    Se divergirem, o histórico volta a registrar o mesmo ativo sob dois nomes
    e a precisão por moeda quebra de novo.
    """
    from trendbot.assets import moeda_canonica

    mapa_js = _aliases_de_moeda_do_dashboard()
    for apelido, canonica_js in mapa_js.items():
        assert moeda_canonica(apelido) == canonica_js, (
            f"'{apelido}': Python diz {moeda_canonica(apelido)}, "
            f"o dashboard diz {canonica_js}"
        )


def test_limpar_historico_remove_simuladas_sem_tocar_nas_reais():
    """A digital do simulador é exata — tolerância apagaria dado real.

    Uma faixa de 0,5% em torno da âncora marcava 11 entradas, e várias eram
    reais (BITCOIN de 14/10 a 19/10, da era v1, quando a CoinGecko respondia).
    """
    import importlib.util

    espec = importlib.util.spec_from_file_location("limpador", "limpar_historico.py")
    limpador = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(limpador)

    digitais = limpador.digitais_do_simulador(["BTC", "ETH"])
    assert digitais, "digital do simulador não calculada"

    historico = [
        # simulada: bate centavo por centavo com a digital
        {"data": "20/10/2026", "moeda": "BTC", "previsao": digitais["BTC"],
         "confianca_min": 1.0, "confianca_max": 2.0, "preco_real": None, "erro": None, "acerto": None},
        # real: perto da âncora, mas não igual
        {"data": "14/10/2026", "moeda": "BITCOIN", "previsao": digitais["BTC"] + 2500,
         "confianca_min": 1.0, "confianca_max": 2.0, "preco_real": 82000.0, "erro": 1.0, "acerto": "✅"},
        # real, já resolvida, sem nada a ver com a âncora
        {"data": "13/10/2026", "moeda": "ETH", "previsao": digitais["ETH"] * 1.4,
         "confianca_min": 1.0, "confianca_max": 2.0, "preco_real": 2400.0, "erro": 2.0, "acerto": "❌"},
    ]

    limpas, removidas = limpador.remover_simuladas(historico)
    assert len(removidas) == 1, f"deveria remover só a simulada, removeu {len(removidas)}"
    assert removidas[0]["moeda"] == "BTC"
    assert {e["data"] for e in limpas} == {"14/10/2026", "13/10/2026"}


def test_deduplicacao_usa_o_nome_canonico():
    """'BITCOIN' e 'BTC' no mesmo dia são a mesma previsão registrada duas vezes."""
    import importlib.util

    espec = importlib.util.spec_from_file_location("limpador2", "limpar_historico.py")
    limpador = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(limpador)

    historico = [
        {"data": "20/10/2026", "moeda": "BITCOIN", "previsao": 83123.34},
        {"data": "20/10/2026", "moeda": "BTC", "previsao": 82033.62},
    ]
    limpas, removidas = limpador.remover_duplicatas(historico)
    assert len(limpas) == 1
    assert len(removidas) == 1


def test_painel_nao_cita_mais_o_modelo_antigo():
    """O rodapé entregava 'Prophet' muito depois de o modelo ter mudado."""
    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")

    assert "Prophet" not in html


def test_painel_exibe_a_avaliacao_do_modelo():
    """Habilidade, cobertura e veredito existem no data.json e nunca apareciam."""
    import json

    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")
    dados = json.loads(pathlib.Path("docs/data.json").read_text(encoding="utf-8"))

    assert 'id="model-card"' in html
    assert 'id="footer-cobertura"' in html
    assert re.search(r"getElementById\('footer-cobertura'\)", js), "rodapé sem wiring"
    # a definição "function renderModelCard(data) {" contém o mesmo texto da
    # chamada, então contar substring não prova nada: exija o ponto de chamada
    # (indentado, com ponto-e-vírgula), que é o que já faltou uma vez antes.
    assert re.search(r"^\s+renderModelCard\(data\);$", js, re.M), (
        "renderModelCard existe mas não é chamada em lugar nenhum"
    )
    for campo in ("avg_skill", "avg_coverage", "observations", "verdict", "notes"):
        assert campo in dados["modelo"], f"data.json sem '{campo}' no model card"


def test_dotenv_e_lido_de_verdade(tmp_path, monkeypatch):
    """O .env.example era decorativo: nada carregava o arquivo.

    Quem copiasse .env.example para .env e preenchesse não via efeito nenhum.
    """
    from trendbot.config import Settings

    (tmp_path / ".env").write_text("MOEDAS_ALVO=bitcoin,solana\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MOEDAS_ALVO", raising=False)

    assert [a.symbol for a in Settings.from_env().assets] == ["BTC", "SOL"]


def test_dotenv_nao_atropela_quem_ja_define_a_variavel(tmp_path, monkeypatch):
    """No CI a variável vem do ambiente e tem de ganhar do arquivo."""
    from trendbot.config import Settings

    (tmp_path / ".env").write_text("MOEDAS_ALVO=bitcoin\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOEDAS_ALVO", "cardano")

    assert [a.symbol for a in Settings.from_env().assets] == ["ADA"]


def test_workflow_nao_injeta_segredos_de_email():
    """A v2 não manda e-mail, mas o workflow injetava os três segredos."""
    from pathlib import Path as _P
    import re as _re

    yml = _P(".github/workflows/daily_report.yml").read_text(encoding="utf-8")
    assert not _re.search(r"\bEMAIL_(REMETENTE|SENHA|DESTINO)\b", yml), (
        "o workflow voltou a injetar segredo de e-mail; nada no projeto lê isso"
    )


def test_requirements_nao_lista_dependencia_morta():
    """scipy, scikit-learn e schedule não são importados em lugar nenhum.

    Ficaram na lista por inércia, da época em que o modelo era Prophet.
    """
    linhas = pathlib.Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    # sem os comentários: a justificativa cita os nomes de propósito
    pacotes = [ln.split("#")[0].strip() for ln in linhas if ln.strip()]
    for morta in ("schedule", "scipy", "scikit-learn"):
        assert not any(p.startswith(morta) for p in pacotes), (
            f"{morta} voltou ao requirements.txt sem ser importado em lugar nenhum"
        )


def test_motor_publica_recomendacao_enxuta_para_o_painel(tmp_path, monkeypatch):
    """O relatório completo tem 94 KB de grades de quantis que o painel não lê.

    Publicar isso todo dia no git, e fazer o navegador baixar, para mostrar
    meia dúzia de números não compensa: o motor escreve um arquivo à parte.
    """
    import importlib.util
    import json as _json
    from unittest import mock

    (tmp_path / "docs").mkdir()
    origem = pathlib.Path(__file__).resolve().parent.parent / "trendbot_engine.py"
    monkeypatch.chdir(tmp_path)
    espec = importlib.util.spec_from_file_location("motor_rec", str(origem))
    motor = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(motor)

    with mock.patch.object(motor, "carregar_historico", return_value=[]), \
         mock.patch.object(motor, "salvar_historico"):
        motor.fluxo_principal()

    docs = tmp_path / "docs"
    completo = docs / "relatorio_completo.json"
    enxuto = docs / "recomendacao.json"

    assert completo.exists(), "o relatório completo deveria continuar sendo gerado"
    assert enxuto.exists(), "recomendacao.json não foi publicado"

    dados = _json.loads(enxuto.read_text(encoding="utf-8"))
    assert set(dados) == {"meta", "recomendacao"}
    assert "previsoes" not in dados, "as grades de quantis voltaram para o arquivo do painel"
    assert dados["meta"]["fonte"], "sem a fonte o painel não pode avisar sobre simulação"

    # o enxuto tem de ser bem menor, senão não vale o arquivo extra
    assert enxuto.stat().st_size < completo.stat().st_size / 4


def test_sem_recomendacao_nova_o_painel_nao_serve_a_antiga(tmp_path, monkeypatch):
    """Uma recomendação de ontem servida como se fosse de hoje é pior que nenhuma."""
    import importlib.util
    from unittest import mock

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "recomendacao.json").write_text("{}", encoding="utf-8")
    origem = pathlib.Path(__file__).resolve().parent.parent / "trendbot_engine.py"
    monkeypatch.chdir(tmp_path)
    espec = importlib.util.spec_from_file_location("motor_rec2", str(origem))
    motor = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(motor)

    # build_advice é importado DENTRO da função, então patch no módulo de origem
    with mock.patch.object(motor, "carregar_historico", return_value=[]), \
         mock.patch.object(motor, "salvar_historico"), \
         mock.patch("trendbot.advisor.build_advice", return_value=None):
        motor.fluxo_principal()

    assert not (tmp_path / "docs" / "recomendacao.json").exists()


def test_painel_mostra_a_recomendacao():
    """A recomendação é calculada e publicada, e o painel precisa exibi-la."""
    html = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
    js = pathlib.Path("docs/script.js").read_text(encoding="utf-8")

    assert 'id="rec"' in html
    # a definição contém o mesmo texto da chamada: exija o ponto de chamada
    assert re.search(r"renderRecomendacao\(await res\.json\(\), data\)", js), (
        "renderRecomendacao não é chamada, ou é chamada sem o data.json "
        "(sem ele o painel não compara a fonte da recomendação)"
    )
    assert "recomendacao.json" in js

    # ausente antes da primeira execução não pode derrubar o painel inteiro
    assert re.search(r"catch\s*\(\s*e\s*\)\s*\{[^}]*recomendacao", js), (
        "a busca da recomendação precisa tolerar 404 sem quebrar o resto"
    )
