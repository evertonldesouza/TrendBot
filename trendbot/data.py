"""Camada de dados: provedores, cache e carregamento de séries de preço.

Objetivo: entregar sempre um ``MarketData`` utilizável, mesmo sem internet.
A ordem de preferência em modo ``auto`` é: cache fresco -> CoinGecko ->
Binance -> CSV local -> simulação determinística (``synthetic``).

Nada aqui faz "análise": só dados + metadados de qualidade (procedência,
atraso, avisos). O resto do sistema confia nesses metadados para se explicar.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .assets import Asset, CASH

logger = logging.getLogger(__name__)

TRADING_DAYS = 365
SYNTHETIC = "synthetic"
COINGECKO = "coingecko"
BINANCE = "binance"
CSV = "csv"


# ---------------------------------------------------------------------------
# Estrutura de dados
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MarketData:
    """Séries alinhadas de preços + metadados de procedência."""

    close: pd.DataFrame                       # index: DatetimeIndex (UTC, diário)
    high: pd.DataFrame | None = None
    low: pd.DataFrame | None = None
    volume: pd.DataFrame | None = None
    source: str = SYNTHETIC
    fetched_at: str = ""
    symbols: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.close = self.close.sort_index()
        self.close.index = pd.to_datetime(self.close.index, utc=True).tz_localize(None)
        if not self.symbols:
            self.symbols = list(self.close.columns)

    @property
    def last_date(self) -> pd.Timestamp:
        return pd.Timestamp(self.close.index[-1])

    @property
    def staleness_days(self) -> float:
        return max(0.0, (pd.Timestamp.now(tz="UTC").tz_localize(None) - self.last_date).total_seconds() / 86400)

    @property
    def is_live(self) -> bool:
        return self.source in (COINGECKO, BINANCE)

    def restricted(self, symbols: Sequence[str]) -> "MarketData":
        cols = [s for s in symbols if s in self.close.columns]
        return MarketData(
            close=self.close[cols].copy(),
            high=self.high[cols].copy() if self.high is not None else None,
            low=self.low[cols].copy() if self.low is not None else None,
            volume=self.volume[cols].copy() if self.volume is not None else None,
            source=self.source,
            fetched_at=self.fetched_at,
            symbols=cols,
            warnings=list(self.warnings),
        )

    def to_frame(self, column: str = "close") -> pd.DataFrame:
        return getattr(self, column) if getattr(self, column) is not None else self.close


# ---------------------------------------------------------------------------
# Utilidades de rede / cache
# ---------------------------------------------------------------------------

_REDE_INDISPONIVEL_ATE: float = 0.0   # timestamp: evita insistir em rede morta
_JANELA_REDE = 300.0                  # 5 minutos sem tentar rede após falha total


def rede_disponivel() -> bool:
    return time.time() >= _REDE_INDISPONIVEL_ATE


def _marcar_rede_indisponivel() -> None:
    global _REDE_INDISPONIVEL_ATE
    _REDE_INDISPONIVEL_ATE = time.time() + _JANELA_REDE
    logger.info("Rede considerada indisponível pelos próximos %.0fs — usando fallbacks.",
                _JANELA_REDE)


def _http_get_json(url: str, params: dict | None = None, timeout: int = 8, tries: int = 1):
    """GET JSON tolerante a falha. Nunca levanta exceção: devolve None.

    Timeout curto e poucas tentativas são intencionais: em um relatório
    interativo, esperar 20s por uma API pública é pior do que cair no CSV ou
    na simulação e dizer isso ao usuário.
    """
    import requests  # import local: permite rodar 100% offline

    if not rede_disponivel():
        return None

    last_error: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(
                url, params=params, timeout=timeout,
                headers={"User-Agent": "TrendBot/2.0 (+quantitative-advisor)"},
            )
            if resp.status_code == 429:
                wait = attempt * 10
                logger.warning("Rate limit em %s. Aguardando %ss...", url, wait)
                time.sleep(wait)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning("Erro HTTP %s em %s", resp.status_code, url)
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - rede é inerentemente instável
            last_error = exc
            logger.warning("Falha de rede (%s/%s) em %s: %s", attempt, tries, url, exc)
            if attempt < tries:
                time.sleep(attempt * 2)
    if last_error is not None:
        logger.info("Desistindo de %s: %s", url, last_error)
    return None


def _cache_path(cache_dir: str, tag: str) -> str:
    return os.path.join(cache_dir, f"{tag}.csv")


def _save_cache(df: pd.DataFrame, cache_dir: str, tag: str) -> None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        df.to_csv(_cache_path(cache_dir, tag))
    except OSError as exc:
        logger.warning("Não foi possível gravar cache %s: %s", tag, exc)


def _load_cache(cache_dir: str, tag: str, max_age_days: float) -> pd.DataFrame | None:
    path = _cache_path(cache_dir, tag)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return None
        age = (pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(df.index[-1])).days
        if age > max_age_days:
            return None
        return df
    except (OSError, ValueError) as exc:
        logger.warning("Cache %s corrompido: %s", tag, exc)
        return None


# ---------------------------------------------------------------------------
# Provedor sintético (determinístico) — usado em demo, testes e modo offline
# ---------------------------------------------------------------------------

# beta  -> sensibilidade ao fator de mercado criptO
# idio  -> volatilidade idiossincratica (em multiplos da vol base do fator)
# drift -> tendencia anual propria do ativo
# cycle -> peso do ciclo de longo prazo (bull/bear) no retorno do ativo
_ASSET_BEHAVIOR = {
    "BTC":  dict(beta=1.00, idio=0.55, drift=0.45, cycle=0.30),
    "ETH":  dict(beta=1.12, idio=0.85, drift=0.38, cycle=0.34),
    "SOL":  dict(beta=1.35, idio=1.55, drift=0.55, cycle=0.48),
    "BNB":  dict(beta=0.90, idio=0.75, drift=0.25, cycle=0.28),
    "XRP":  dict(beta=1.00, idio=1.15, drift=0.10, cycle=0.38),
    "ADA":  dict(beta=1.12, idio=1.25, drift=0.02, cycle=0.36),
    "DOGE": dict(beta=1.20, idio=1.85, drift=-0.05, cycle=0.55),
    "AVAX": dict(beta=1.30, idio=1.50, drift=0.12, cycle=0.45),
    "LINK": dict(beta=1.18, idio=1.25, drift=0.18, cycle=0.40),
    "DOT":  dict(beta=1.20, idio=1.30, drift=-0.12, cycle=0.42),
    "LTC":  dict(beta=0.98, idio=0.95, drift=-0.05, cycle=0.30),
    "POL":  dict(beta=1.25, idio=1.45, drift=-0.18, cycle=0.45),
    "NEAR": dict(beta=1.22, idio=1.40, drift=0.10, cycle=0.44),
    "SUI":  dict(beta=1.28, idio=1.60, drift=0.30, cycle=0.48),
    "APT":  dict(beta=1.24, idio=1.45, drift=0.00, cycle=0.46),
    "ARB":  dict(beta=1.25, idio=1.50, drift=-0.15, cycle=0.46),
    "TON":  dict(beta=1.05, idio=1.30, drift=0.05, cycle=0.38),
    "LEO":  dict(beta=0.30, idio=0.45, drift=0.18, cycle=0.18),
}

_BASE_PRICE = {
    "BTC": 82000.0, "ETH": 2400.0, "SOL": 104.0, "BNB": 610.0, "XRP": 0.62,
    "ADA": 0.41, "DOGE": 0.085, "AVAX": 22.0, "LINK": 11.5, "DOT": 3.4,
    "LTC": 74.0, "POL": 0.22, "NEAR": 2.6, "SUI": 1.15, "APT": 4.2,
    "ARB": 0.38, "TON": 2.1, "LEO": 9.4,
}

# Regimes de mercado: (prob de permanência, multiplicador de vol, drift extra)
_REGIMES = {
    "calm":   dict(stay=0.985, vol=0.70, drift=+0.35),
    "normal": dict(stay=0.972, vol=1.00, drift=+0.05),
    "stress": dict(stay=0.940, vol=2.10, drift=-0.85),
}
_REGIME_ORDER = ["calm", "normal", "stress"]
_REGIME_START = [0.25, 0.60, 0.15]


def _symbol_seed(symbol: str, seed: int) -> int:
    """Seed estável por símbolo.

    ``hash()`` de string em Python é randomizado por processo (PYTHONHASHSEED),
    então usá-lo aqui fazia a "simulação determinística" gerar séries
    diferentes a cada execução — o que tornava a suíte de testes instável
    (~25% de falha) e qualquer relatório irreproduzível. SHA-256 é estável
    entre processos, versões de Python e plataformas.
    """
    digest = hashlib.sha256(f"{symbol}:{seed}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") or 1


def simulate_market(
    symbols: Sequence[str],
    days: int = 730,
    seed: int = 20260101,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Gera preços realistas (correlacionados, com volatilidade agrupada).

    Modelo: fator de mercado com regimes Markovianos (calmo/normal/estresse),
    retornos com caudas gordas (mistura de normais + saltos) e componente
    idiossincrático por ativo. Determinístico dado ``seed`` — essencial para
    que demos, testes e relatórios sejam reproduzíveis.
    """

    symbols = [s for s in symbols if s != CASH]
    if not symbols:
        raise ValueError("Nenhum ativo para simular.")
    days = max(int(days), 120)

    end = pd.Timestamp(end).normalize() if end is not None else pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    idx = pd.date_range(end=end, periods=days, freq="D")

    rng = np.random.default_rng(seed)
    n = len(idx)

    # --- fator de mercado com regimes ---
    regime_idx = rng.choice(len(_REGIME_ORDER), p=_REGIME_START)
    mkt_vol, mkt_drift = [], []
    for _ in range(n):
        name = _REGIME_ORDER[regime_idx]
        cfg = _REGIMES[name]
        mkt_vol.append(cfg["vol"])
        mkt_drift.append(cfg["drift"])
        if rng.random() > cfg["stay"]:
            # transição: estresse tende a voltar ao normal, calmo ao normal
            regime_idx = 1 if rng.random() < 0.7 else rng.choice([0, 1, 2])

    mkt_vol = np.asarray(mkt_vol, dtype=float)
    mkt_drift = np.asarray(mkt_drift, dtype=float)
    base_vol = 0.023  # vol diária do fator em regime normal

    fat = rng.standard_t(df=4, size=n)          # caudas gordas
    fat = fat / np.sqrt(4 / 2.0)                # normaliza variância para ~1
    jumps = (rng.random(n) < 0.010) * rng.normal(-0.038, 0.030, n)
    market_ret = mkt_drift * 0.0006 + base_vol * mkt_vol * fat + jumps

    # volatilidade agrupada (GARCH-like) sobre o fator
    ewma_var = np.zeros(n)
    var = base_vol**2
    for i in range(n):
        var = 0.06 * market_ret[i] ** 2 + 0.94 * var
        ewma_var[i] = var
    market_ret = market_ret * (np.sqrt(ewma_var) / np.sqrt(np.mean(ewma_var)))

    # ciclo de longo prazo (bull/bear de ~18 meses)
    t = np.arange(n)
    cycle = 0.0009 * np.sin(2 * np.pi * t / 540.0 + 1.1)

    # Precos em cripto sao um passeio aleatorio, mas ancorados por adocao e
    # custo de producao: sem uma forca de volta a media a serie vaga ordens de
    # grandeza em 2 anos e a demo perde qualquer verossimilhanca.
    kappa = 0.0045   # ~0.45%/dia de atracao -> meia-vida de ~155 dias

    series: dict[str, pd.Series] = {}
    for symbol in symbols:
        beh = _ASSET_BEHAVIOR.get(symbol, dict(beta=1.2, idio=1.2, drift=0.1, cycle=0.45))
        srng = np.random.default_rng(_symbol_seed(symbol, seed))
        idio = srng.standard_t(df=5, size=n) / np.sqrt(5 / 3.0)
        idio_jump = (srng.random(n) < 0.008) * srng.normal(0.0, 0.042, n)

        beta, ivol = beh["beta"], beh["idio"]
        shocks = beta * (market_ret + cycle) + (ivol * 0.020) * idio + idio_jump

        # ancora: tendencia suave que termina exatamente no preco de referencia
        anchor = -(beh["drift"] / TRADING_DAYS) * (n - 1 - t)

        logp = np.empty(n)
        logp[0] = anchor[0]
        for i in range(1, n):
            pull = kappa * (anchor[i] - logp[i - 1])
            logp[i] = logp[i - 1] + pull + shocks[i]

        base = _BASE_PRICE.get(symbol, 10.0)
        series[symbol] = pd.Series(base * np.exp(logp - logp[-1]), index=idx, name=symbol)

    return pd.DataFrame(series)


def _synthetic_ohlcv(close: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Deriva OHLC plausível a partir do fechamento (usado no modo sintético)."""
    rng = np.random.default_rng(seed + 7)
    ret = close.pct_change().abs().fillna(0.02)
    span = (0.006 + 0.55 * ret.to_numpy())
    span = np.clip(span, 0.002, 0.35)
    noise = rng.random(close.shape)
    high = close * (1 + span * (0.35 + 0.65 * noise))
    low = close * (1 - span * (0.35 + 0.65 * (1 - noise)))
    base_vol = close.mean(axis=0) * 4e6
    volume = pd.DataFrame(
        rng.lognormal(mean=np.log(base_vol.to_numpy()), sigma=0.45, size=close.shape),
        index=close.index, columns=close.columns,
    ) * (1 + 6 * ret.to_numpy())
    return pd.DataFrame(high, index=close.index, columns=close.columns), \
        pd.DataFrame(low, index=close.index, columns=close.columns), volume


# ---------------------------------------------------------------------------
# Provedores reais
# ---------------------------------------------------------------------------

def fetch_coingecko(asset: Asset, days: int, cache_dir: str, max_retries: int = 1) -> pd.Series | None:
    """Série diária de fechamento via API pública da CoinGecko."""
    cached = _load_cache(cache_dir, f"cg_{asset.key}", max_age_days=1.0)
    if cached is not None and len(cached) >= max(30, int(days * 0.8)):
        return cached.iloc[:, 0].rename(asset.symbol)

    url = f"https://api.coingecko.com/api/v3/coins/{asset.key}/market_chart"
    data = _http_get_json(url, {"vs_currency": "usd", "days": int(days), "interval": "daily"}, tries=max_retries)
    prices = (data or {}).get("prices") if isinstance(data, dict) else None
    if not prices:
        return None

    df = pd.DataFrame(prices, columns=["ts", "price"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.tz_localize(None).dt.normalize()
    series = df.groupby("date")["price"].last().rename(asset.symbol)
    if series.empty:
        return None
    _save_cache(series.to_frame(), cache_dir, f"cg_{asset.key}")
    return series


def fetch_binance(asset: Asset, days: int, cache_dir: str, max_retries: int = 1) -> pd.DataFrame | None:
    """OHLCV diário via Binance (mais confiável e granular que a CoinGecko)."""
    if not asset.binance:
        return None
    tag = f"bn_{asset.binance}"
    cached_path = os.path.join(cache_dir, f"{tag}.csv")
    if os.path.exists(cached_path):
        try:
            cached = pd.read_csv(cached_path, index_col=0, parse_dates=True)
            if not cached.empty and (pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cached.index[-1])).days <= 1:
                return cached
        except (OSError, ValueError):
            pass

    end_ms = int(time.time() * 1000)
    data = _http_get_json(
        "https://api.binance.com/api/v3/klines",
        {"symbol": asset.binance, "interval": "1d", "limit": min(int(days) + 5, 1000)},
        tries=max_retries,
    )
    if not data:
        return None

    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "tbb", "tbq", "ignore"]
    df = pd.DataFrame(data, columns=cols)
    df["date"] = pd.to_datetime(df["open_time"], unit="ms").dt.tz_localize(None).dt.normalize()
    out = df.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)
    out.columns = [f"{asset.symbol}_open", f"{asset.symbol}_high", f"{asset.symbol}_low",
                   f"{asset.symbol}_close", f"{asset.symbol}_volume"]
    _save_cache(out, cache_dir, tag)
    return out


def load_csv_prices(data_dir: str, symbols: Sequence[str]) -> pd.DataFrame | None:
    """Carrega ``data/prices.csv`` (colunas: Data, TICKER...), se existir."""
    path = os.path.join(data_dir, "prices.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df = df[[c for c in symbols if c in df.columns]]
        return df.dropna(how="all") if not df.empty else None
    except (OSError, ValueError) as exc:
        logger.warning("Falha ao ler %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def build_market_data(
    assets: Sequence[Asset],
    days: int = 730,
    source: str = "auto",
    cache_dir: str = ".cache/trendbot",
    data_dir: str = "data",
    seed: int = 20260101,
    allow_stale: bool = True,
    network_tries: int = 1,
) -> MarketData:
    """Carrega preços do universo pedido, com fallback gracioso.

    ``network_tries`` controla quantas vezes cada endpoint é tentado. O padrão
    (1) favorece a latência do relatório interativo. Para o job diário use 3+:
    a API pública da CoinGecko responde 429 com frequência a IPs de datacenter,
    e com uma tentativa só o relatório caía na simulação e era publicado como
    se fossem dados reais.
    """

    symbols = [a.symbol for a in assets]
    warnings: list[str] = []
    frames: list[pd.DataFrame] = []
    ohlc: dict[str, pd.DataFrame] = {"high": [], "low": [], "volume": []}
    used_source = SYNTHETIC

    csv_df = load_csv_prices(data_dir, symbols)
    live_ok = 0

    if source in ("auto", COINGECKO, BINANCE) and rede_disponivel():
        def coletar(asset: Asset) -> tuple[Asset, pd.Series | None, pd.DataFrame | None]:
            """Tenta Binance (OHLCV completo) e, se falhar, CoinGecko."""
            if source in ("auto", BINANCE):
                ohlcv = fetch_binance(asset, days, cache_dir, max_retries=network_tries)
                if ohlcv is not None and not ohlcv.empty:
                    return asset, ohlcv[f"{asset.symbol}_close"].rename(asset.symbol), ohlcv
            if source in ("auto", COINGECKO):
                s = fetch_coingecko(asset, days, cache_dir, max_retries=network_tries)
                if s is not None:
                    return asset, s, None
            return asset, None, None

        with ThreadPoolExecutor(max_workers=min(6, len(assets))) as pool:
            resultados = list(pool.map(coletar, assets))

        if all(r[1] is None for r in resultados) and not any(
            os.path.exists(os.path.join(cache_dir, f"{pre}_{a.key if pre == 'cg' else a.binance}.csv"))
            for a in assets for pre in ("cg", "bn") if (pre == "cg" or a.binance)
        ):
            _marcar_rede_indisponivel()

        for asset, series, ohlcv in resultados:
            if series is not None and len(series) >= 60:
                frames.append(series.to_frame())
                live_ok += 1
                if ohlcv is not None:
                    ohlc["high"].append(ohlcv[f"{asset.symbol}_high"].rename(asset.symbol))
                    ohlc["low"].append(ohlcv[f"{asset.symbol}_low"].rename(asset.symbol))
                    ohlc["volume"].append(ohlcv[f"{asset.symbol}_volume"].rename(asset.symbol))
                    used_source = BINANCE
                else:
                    used_source = COINGECKO if source != BINANCE else used_source
            else:
                warnings.append(f"Sem dados de mercado ao vivo para {asset.symbol}.")

    if csv_df is not None and live_ok < len(assets):
        frames.append(csv_df)
        used_source = CSV if used_source == SYNTHETIC else used_source
        warnings.append("Complementando com dados locais (data/prices.csv).")

    if live_ok >= max(2, int(len(assets) * 0.6)):
        close = pd.concat(frames, axis=1).sort_index()
        close = close.loc[:, ~close.columns.duplicated()]
    else:
        if live_ok or frames:
            warnings.append("Cobertura insuficiente de dados reais — usando simulação determinística.")
        close = simulate_market(symbols, days=days, seed=seed)
        used_source = SYNTHETIC
        ohlc = {"high": [], "low": [], "volume": []}

    if source == SYNTHETIC:
        close = simulate_market(symbols, days=days, seed=seed)
        used_source = SYNTHETIC

    close = close.dropna(how="all").ffill().dropna(how="any")
    if isinstance(close.index, pd.DatetimeIndex) and close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    close = close[sorted(close.columns)]

    high_df = pd.concat(ohlc["high"], axis=1) if ohlc["high"] else None
    low_df = pd.concat(ohlc["low"], axis=1) if ohlc["low"] else None
    vol_df = pd.concat(ohlc["volume"], axis=1) if ohlc["volume"] else None
    if used_source == SYNTHETIC:
        high_df, low_df, vol_df = _synthetic_ohlcv(close, seed)

    if used_source == SYNTHETIC:
        warnings.append(
            "Preços simulados (modo demonstração). Configure FONTE_DADOS=auto com rede "
            "liberada, ou forneça data/prices.csv, para operar com dados reais."
        )

    return MarketData(
        close=close,
        high=high_df.reindex(close.index).reindex(columns=close.columns) if high_df is not None else None,
        low=low_df.reindex(close.index).reindex(columns=close.columns) if low_df is not None else None,
        volume=vol_df.reindex(close.index).reindex(columns=close.columns) if vol_df is not None else None,
        source=used_source,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        symbols=list(close.columns),
        warnings=warnings,
    )


def market_data_from_prices(close: pd.DataFrame, source: str = CSV, **kwargs) -> MarketData:
    """Constrói MarketData a partir de uma matriz de preços já pronta."""
    return MarketData(close=close.copy(), source=source, **kwargs)


def describe_source(md: MarketData) -> str:
    labels = {
        COINGECKO: "CoinGecko (tempo real)",
        BINANCE: "Binance (tempo real)",
        CSV: "Arquivo local data/prices.csv",
        SYNTHETIC: "Simulação determinística (demo)",
    }
    return labels.get(md.source, md.source)
