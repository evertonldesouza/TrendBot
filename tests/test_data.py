"""Testes do módulo de dados (trendbot/data.py) — 100% offline.

Este é o módulo mais difícil de testar porque o comportamento interessante
acontece quando a rede falha: é aí que o sistema decide entre dados reais,
cache, CSV local e simulação. Fora daqui, essa decisão só acontece em produção
ou quando a API pública resolve não responder.

Tudo roda com `requests.get` mockado e cache em diretório temporário, então
nenhum teste depende de CoinGecko ou Binance existirem.
"""

from __future__ import annotations

import os
import time
from unittest import mock

import pandas as pd
import pytest

from trendbot import data
from trendbot.assets import Asset, resolve_assets


@pytest.fixture(autouse=True)
def _estado_de_rede_limpo():
    """A indisponibilidade de rede é global e vaza entre testes.

    Um teste que marca a rede como indisponível faria o próximo devolver None
    sem encostar no requests — a falha apareceria longe da causa.
    """
    data._REDE_INDISPONIVEL_ATE = 0.0
    data._ULTIMOS_ERROS_REDE.clear()
    yield
    data._REDE_INDISPONIVEL_ATE = 0.0
    data._ULTIMOS_ERROS_REDE.clear()


class _RespostaFalsa:
    """O mínimo que `_http_get_json` usa de um Response do requests."""

    def __init__(self, status=200, payload=None, texto=""):
        self.status_code = status
        self._payload = payload
        self.text = texto

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _serie(dias: int = 90, valor: float = 100.0) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=dias, freq="D")
    return pd.Series([valor + i for i in range(dias)], index=idx, name="BTC")


# ---------------------------------------------------------------------------
# _http_get_json
# ---------------------------------------------------------------------------

def test_http_get_json_devolve_o_payload():
    with mock.patch("requests.get", return_value=_RespostaFalsa(200, {"ok": True})) as get:
        assert data._http_get_json("http://x") == {"ok": True}
    get.assert_called_once()


def test_http_get_json_4xx_devolve_none_sem_retry():
    """Erro do cliente não se resolve repetindo: desiste logo e registra."""
    with mock.patch("requests.get", return_value=_RespostaFalsa(404, texto="nope")) as get:
        assert data._http_get_json("http://x", tries=3) is None
    assert get.call_count == 1
    assert any("404" in e for e in data.ultimos_erros_rede())


def test_http_get_json_repetindo_429_acaba_dando_certo():
    """Rate limit é passageiro: vale tentar de novo."""
    with mock.patch("time.sleep"), \
         mock.patch("requests.get",
                    side_effect=[_RespostaFalsa(429), _RespostaFalsa(200, {"ok": 1})]) as get:
        assert data._http_get_json("http://x", tries=2) == {"ok": 1}
    assert get.call_count == 2


def test_http_get_json_desiste_quando_o_429_nao_passar():
    with mock.patch("time.sleep"), \
         mock.patch("requests.get", return_value=_RespostaFalsa(429)) as get:
        assert data._http_get_json("http://x", tries=2) is None
    assert get.call_count == 2
    assert any("429" in e for e in data.ultimos_erros_rede())


def test_http_get_json_rede_indisponivel_nao_gasta_tentativa():
    """A janela de indisponibilidade existe para não insistir em API morta."""
    data._marcar_rede_indisponivel()
    with mock.patch("requests.get") as get:
        assert data._http_get_json("http://x") is None
    get.assert_not_called()


def test_http_get_json_excecao_de_rede_nao_proaga():
    """Nunca levanta: quem chama precisa conseguir cair no fallback."""
    with mock.patch("time.sleep"), \
         mock.patch("requests.get", side_effect=OSError("sem rota")):
        assert data._http_get_json("http://x", tries=2) is None
    assert any("OSError" in e for e in data.ultimos_erros_rede())


def test_ultimos_erros_rede_explica_o_fallback():
    """Sem isso, cair em simulação é invisível: o job termina com sucesso."""
    with mock.patch("time.sleep"), \
         mock.patch("requests.get", side_effect=OSError("timeout")):
        data._http_get_json("http://x", tries=1)
    motivos = data.ultimos_erros_rede()
    assert motivos and "timeout" in motivos[-1]


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------

def test_cache_vai_e_volta(tmp_path):
    original = _serie().to_frame()
    data._save_cache(original, str(tmp_path), "bn_BTCUSDT")
    carregado = data._load_cache(str(tmp_path), "bn_BTCUSDT", max_age_days=1.0)
    assert carregado is not None
    assert len(carregado) == len(original)


def test_cache_vencido_e_ignorado(tmp_path):
    antiga = pd.Series([1.0, 2.0, 3.0],
                       index=pd.date_range("2020-01-01", periods=3, freq="D")).to_frame()
    data._save_cache(antiga, str(tmp_path), "bn_BTCUSDT")
    assert data._load_cache(str(tmp_path), "bn_BTCUSDT", max_age_days=1.0) is None


def test_cache_corrompido_nao_derruba_o_ciclo(tmp_path):
    """Cache ilegível tem de virar None, não exceção no meio do relatório."""
    (tmp_path / "bn_BTCUSDT.csv").write_text("isto não,é;um csv\tlido\n???", encoding="utf-8")
    with pytest.raises(Exception) if False else mock.patch.object(data.logger, "warning") as aviso:
        assert data._load_cache(str(tmp_path), "bn_BTCUSDT", max_age_days=1.0) is None
    assert aviso.called


def test_cache_inexistente_devolve_none(tmp_path):
    assert data._load_cache(str(tmp_path), "nao_existe", max_age_days=1.0) is None


# ---------------------------------------------------------------------------
# provedores
# ---------------------------------------------------------------------------

def test_coingecko_atende_do_cache_sem_tocar_na_rede(tmp_path):
    btc = resolve_assets(["BTC"])[0]
    data._save_cache(_serie(400).to_frame(), str(tmp_path), f"cg_{btc.key}")
    with mock.patch("requests.get") as get:
        serie = data.fetch_coingecko(btc, days=365, cache_dir=str(tmp_path))
    get.assert_not_called()
    assert serie is not None and len(serie) == 400


def test_coingecko_converte_o_payload_em_serie(tmp_path):
    btc = resolve_assets(["BTC"])[0]
    agora_ms = int(time.time() * 1000)
    precos = [
        [agora_ms - 2 * 86_400_000, 60000.0],
        [agora_ms - 1 * 86_400_000, 61000.0],
        [agora_ms - 1 * 86_400_000, 61500.0],  # mesmo dia: deve ficar o último
    ]
    with mock.patch("requests.get", return_value=_RespostaFalsa(200, {"prices": precos})):
        serie = data.fetch_coingecko(btc, days=365, cache_dir=str(tmp_path))
    assert serie is not None
    assert len(serie) == 2, "dois registros no mesmo dia viram um só"
    assert serie.iloc[-1] == 61500.0
    assert serie.name == "BTC"


def test_coingecko_sem_prices_devolve_none(tmp_path):
    btc = resolve_assets(["BTC"])[0]
    with mock.patch("requests.get", return_value=_RespostaFalsa(200, {"prices": []})):
        assert data.fetch_coingecko(btc, days=365, cache_dir=str(tmp_path)) is None


def test_binance_sem_par_devolve_none(tmp_path):
    """Nem todo ativo tem par na Binance; isso não é erro, é só ausência."""
    sem_par = Asset(key="sem-par", symbol="XYZ", name="Sem Par", binance=None)
    assert data.fetch_binance(sem_par, days=30, cache_dir=str(tmp_path)) is None


def test_binance_converte_klines_em_ohlcv(tmp_path):
    btc = resolve_assets(["BTC"])[0]
    klines = [
        [1_700_000_000_000, "100", "110", "90", "105", "1000", 0, 0, 0, 0, 0, 0],
        [1_700_086_400_000, "105", "115", "95", "108", "1100", 0, 0, 0, 0, 0, 0],
    ]
    with mock.patch("requests.get", return_value=_RespostaFalsa(200, klines)):
        out = data.fetch_binance(btc, days=30, cache_dir=str(tmp_path))
    assert out is not None
    assert list(out.columns) == [f"{btc.symbol}_{c}" for c in
                                 ("open", "high", "low", "close", "volume")]
    assert out[f"{btc.symbol}_close"].iloc[-1] == 108.0


def test_binance_atende_do_cache(tmp_path):
    btc = resolve_assets(["BTC"])[0]
    df = pd.DataFrame(
        {f"{btc.symbol}_close": [1.0, 2.0, 3.0]},
        index=pd.date_range(end=pd.Timestamp.now().normalize(), periods=3, freq="D"),
    )
    data._save_cache(df, str(tmp_path), f"bn_{btc.binance}")
    with mock.patch("requests.get") as get:
        out = data.fetch_binance(btc, days=30, cache_dir=str(tmp_path))
    get.assert_not_called()
    assert out is not None and len(out) == 3


# ---------------------------------------------------------------------------
# CSV local
# ---------------------------------------------------------------------------

def test_csv_ausente_devolve_none(tmp_path):
    assert data.load_csv_prices(str(tmp_path), ["BTC"]) is None


def test_csv_local_e_carregado(tmp_path):
    df = pd.DataFrame({"BTC": [1.0, 2.0], "ETH": [3.0, 4.0]},
                      index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    df.to_csv(tmp_path / "prices.csv")
    carregado = data.load_csv_prices(str(tmp_path), ["BTC", "ETH"])
    assert carregado is not None
    assert list(carregado.columns) == ["BTC", "ETH"]


def test_csv_ilegivel_devolve_none(tmp_path):
    """Arquivo que o pandas não parseia: vira None com aviso, não exceção.

    Um data/prices.csv corrompido derrubando o relatório do dia é
    desproporcional — o dado local é o terceiro fallback da fila.
    """
    # mais colunas do que o cabeçalho promete: pandas levanta ParserError,
    # que é subclasse de ValueError
    (tmp_path / "prices.csv").write_text("Data,BTC\n2026-01-01,1,2,3,4\n", encoding="utf-8")
    with mock.patch.object(data.logger, "warning") as aviso:
        assert data.load_csv_prices(str(tmp_path), ["BTC"]) is None
    assert aviso.called


# ---------------------------------------------------------------------------
# orquestração
# ---------------------------------------------------------------------------

def test_build_market_data_atende_do_cache_sem_rede(tmp_path):
    """Cache quente vale como dado ao vivo.

    Se isso quebrar, cada execução sem rede vira simulação mesmo tendo os
    dados em disco — e o relatório passa a mentir sobre a própria fonte.
    """
    ativos = resolve_assets(["BTC", "ETH"])
    for a in ativos:
        df = pd.DataFrame(
            {f"{a.symbol}_close": [100.0 + i for i in range(80)],
             f"{a.symbol}_high": [101.0 + i for i in range(80)],
             f"{a.symbol}_low": [99.0 + i for i in range(80)],
             f"{a.symbol}_volume": [1.0] * 80},
            index=pd.date_range(end=pd.Timestamp.now().normalize(), periods=80, freq="D"),
        )
        data._save_cache(df, str(tmp_path), f"bn_{a.binance}")

    with mock.patch("requests.get") as get:
        md = data.build_market_data(ativos, days=365, cache_dir=str(tmp_path))
    get.assert_not_called()
    assert md.source == data.BINANCE, f"caiu em {md.source} mesmo com cache válido"
    assert set(md.close.columns) == {"BTC", "ETH"}
    assert md.is_live


def test_build_market_data_cai_em_simulacao_quando_nao_ha_nada(tmp_path):
    """Sem rede, sem cache, sem CSV: simulação — mas declarada como tal."""
    ativos = resolve_assets(["BTC"])
    with mock.patch("requests.get", side_effect=OSError("sem rede")):
        md = data.build_market_data(ativos, days=365, cache_dir=str(tmp_path),
                                    data_dir=str(tmp_path))
    assert md.source == data.SYNTHETIC
    assert not md.is_live


def test_build_market_data_fonte_forcada_simulada(tmp_path):
    ativos = resolve_assets(["BTC", "ETH"])
    md = data.build_market_data(ativos, days=200, source="synthetic", cache_dir=str(tmp_path))
    assert md.source == data.SYNTHETIC
    assert {"BTC", "ETH"} == set(md.close.columns)


def test_simulate_market_sem_ativo_util_levanta():
    """Só caixa não é um universo simulável: erro explícito melhor que vazio."""
    with pytest.raises(ValueError):
        data.simulate_market(["USD"], days=200)


def test_restricted_mantem_apenas_as_colunas_pedidas(tmp_path):
    ativos = resolve_assets(["BTC", "ETH", "SOL"])
    md = data.build_market_data(ativos, days=200, source="synthetic", cache_dir=str(tmp_path))
    so_btc = md.restricted(["BTC"])
    assert list(so_btc.close.columns) == ["BTC"]
    assert so_btc.source == md.source


# ---------------------------------------------------------------------------
# caminhos menos trilhados, mas que já foram fonte de relatório mentiroso
# ---------------------------------------------------------------------------

def test_staleness_days_conta_dias_desde_o_ultimo_fechamento():
    md = data.build_market_data(resolve_assets(["BTC"]), days=200, source="synthetic",
                                cache_dir="")
    assert md.staleness_days >= 0
    assert md.last_date == md.close.index[-1]


def test_to_frame_devolve_a_coluna_pedida(tmp_path):
    md = data.build_market_data(resolve_assets(["BTC"]), days=200, source="synthetic",
                                cache_dir=str(tmp_path))
    assert md.to_frame("close") is md.close
    assert md.to_frame("high").equals(md.high)


def test_cache_vazio_devolve_none(tmp_path):
    vazio = pd.DataFrame({"BTC": []}, index=pd.DatetimeIndex([]))
    data._save_cache(vazio, str(tmp_path), "bn_BTCUSDT")
    assert data._load_cache(str(tmp_path), "bn_BTCUSDT", max_age_days=1.0) is None


def test_coingecko_preco_nulo_vira_nan_e_nao_excecao(tmp_path):
    """Preço nulo não derruba: vira NaN e o ffill do build_market_data resolve."""
    btc = resolve_assets(["BTC"])[0]
    agora_ms = int(time.time() * 1000)
    with mock.patch("requests.get", return_value=_RespostaFalsa(
            200, {"prices": [[agora_ms - 86_400_000, 100.0], [agora_ms, None]]})):
        serie = data.fetch_coingecko(btc, days=365, cache_dir=str(tmp_path))
    assert serie is not None
    assert pd.isna(serie.iloc[-1])


def test_build_market_data_usa_coingecko_quando_a_binance_falha(tmp_path):
    """Binance é preferida, mas CoinGecko também é fonte ao vivo.

    A cobertura só exercitava a Binance; se o ramo da CoinGecko quebrasse,
    o sistema cairia em simulação mesmo tendo preço real disponível.
    """
    ativos = resolve_assets(["BTC", "ETH"])
    agora_ms = int(time.time() * 1000)
    um_dia = 86_400_000

    def resposta(url, params=None, **kwargs):
        assert "coingecko" in url
        return _RespostaFalsa(200, {"prices": [
            [agora_ms - (80 - i) * um_dia, 100.0 + i] for i in range(80)
        ]})

    with mock.patch("requests.get", side_effect=resposta):
        md = data.build_market_data(ativos, days=365, source="coingecko",
                                    cache_dir=str(tmp_path))
    assert md.source == data.COINGECKO, f"esperava CoinGecko, veio {md.source}"
    assert md.is_live
    assert {"BTC", "ETH"} == set(md.close.columns)


def test_build_market_data_complementa_com_csv_quando_falta_ativo(tmp_path):
    """Metade do universo ao vivo e metade no CSV: usa os dois e diz isso."""
    ativos = resolve_assets(["BTC", "ETH", "SOL", "ADA"])
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=80, freq="D")

    # 3 dos 4 com cache quente; o 4º (ADA) só existe no CSV. O cache precisa
    # das colunas OHLCV: o build_market_data lê high/low/volume dele.
    for a in ativos[:-1]:
        data._save_cache(
            pd.DataFrame({f"{a.symbol}_close": [100.0 + i for i in range(80)],
                          f"{a.symbol}_high": [101.0 + i for i in range(80)],
                          f"{a.symbol}_low": [99.0 + i for i in range(80)],
                          f"{a.symbol}_volume": [1.0] * 80}, index=idx),
            str(tmp_path), f"bn_{a.binance}")

    csv = pd.DataFrame({a.symbol: [100.0 + i for i in range(80)] for a in ativos}, index=idx)
    csv.to_csv(tmp_path / "prices.csv")

    # quem não tem cache tenta a rede; a rede precisa falhar de verdade
    with mock.patch("requests.get", side_effect=OSError("sem rede")):
        md = data.build_market_data(ativos, days=365, cache_dir=str(tmp_path),
                                    data_dir=str(tmp_path))
    assert md.source == data.BINANCE
    assert "ADA" in md.close.columns, "o ativo que só estava no CSV sumiu"
    assert any("prices.csv" in w for w in md.warnings)


def test_build_market_data_cobertura_insuficiente_cai_em_simulacao(tmp_path):
    """Um ativo de dois não sustenta o relatório: simula e avisa por quê."""
    ativos = resolve_assets(["BTC", "ETH"])
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=80, freq="D")
    data._save_cache(
        pd.DataFrame({f"{ativos[0].symbol}_close": [100.0 + i for i in range(80)],
                      f"{ativos[0].symbol}_high": [101.0 + i for i in range(80)],
                      f"{ativos[0].symbol}_low": [99.0 + i for i in range(80)],
                      f"{ativos[0].symbol}_volume": [1.0] * 80}, index=idx),
        str(tmp_path), f"bn_{ativos[0].binance}")

    with mock.patch("requests.get", side_effect=OSError("sem rede")):
        md = data.build_market_data(ativos, days=365, cache_dir=str(tmp_path),
                                    data_dir=str(tmp_path))
    assert md.source == data.SYNTHETIC
    assert any("insuficiente" in w for w in md.warnings)
