"""Testes do núcleo quantitativo do TrendBot.

Rodam 100% offline (sem depender de CoinGecko/Binance) usando o gerador
sintético determinístico. ``pytest tests/ -v``
"""

from __future__ import annotations

import pathlib

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


def test_build_market_data_cai_para_simulacao_sem_rede(tmp_path):
    from trendbot.assets import resolve_assets
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
