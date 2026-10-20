"""Indicadores técnicos e estatísticos (implementação própria, sem pandas-ta).

Todos os indicadores são puros (Series/DataFrame -> Series) e tolerantes a
janelas curtas, para que o sistema funcione com 120 dias ou com 10 anos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 365


# ---------------------------------------------------------------------------
# Tendência / momentum
# ---------------------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=max(2, window // 2)).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, min_periods=max(2, span // 3), adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """RSI de Wilder (suavização exponencial), padrão de mercado."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    # Sem perdas no período o RSI é 100 (e não "indefinido"): deixar isso
    # virar 50 esconderia justamente as tendências mais fortes.
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.mask((avg_loss.abs() < 1e-12) & (avg_gain > 1e-12), 100.0)
    out = out.mask((avg_gain.abs() < 1e-12) & (avg_loss > 1e-12), 0.0)
    return out.fillna(50.0).clip(0, 100)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(series, fast) - ema(series, slow)
    return pd.DataFrame({"macd": line, "signal": ema(line, signal), "hist": line - ema(line, signal)})


def roc(series: pd.Series, window: int) -> pd.Series:
    return series.pct_change(window)


def momentum_score(series: pd.Series) -> pd.Series:
    """Momentum multi-horizonte (1m / 3m / 6m) combinado e suavizado."""
    m1 = roc(series, 30)
    m3 = roc(series, 90)
    m6 = roc(series, 180)
    score = (0.25 * m1.fillna(0) + 0.35 * m3.fillna(0) + 0.40 * m6.fillna(0))
    return score / score.rolling(180, min_periods=30).std().replace(0, np.nan)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Forceza da tendência (0-100). Acima de 25 indica tendência relevante."""
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=close.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=close.index)
    tr = true_range(high, low, close)
    atr = tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean() / atr.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / window, min_periods=window, adjust=False).mean().fillna(0.0)


# ---------------------------------------------------------------------------
# Volatilidade / risco
# ---------------------------------------------------------------------------

def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    return pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def realized_vol(returns: pd.Series, window: int = 30, annualize: bool = True) -> pd.Series:
    out = returns.rolling(window, min_periods=max(5, window // 3)).std()
    return out * np.sqrt(TRADING_DAYS) if annualize else out


def ewma_vol(returns: pd.Series, span: int = 30, annualize: bool = True) -> pd.Series:
    """Volatilidade com peso exponencial — reage mais rápido a choques."""
    out = returns.ewm(span=span, min_periods=max(5, span // 3)).std()
    return out * np.sqrt(TRADING_DAYS) if annualize else out


def zscore(series: pd.Series, window: int = 90) -> pd.Series:
    mu = series.rolling(window, min_periods=max(10, window // 3)).mean()
    sd = series.rolling(window, min_periods=max(10, window // 3)).std()
    return ((series - mu) / sd.replace(0, np.nan)).fillna(0.0)


def drawdown(series: pd.Series) -> pd.Series:
    return series / series.cummax() - 1.0


def max_drawdown(series: pd.Series) -> float:
    return float(drawdown(series).min())


def ulcer_index(series: pd.Series, window: int = 60) -> pd.Series:
    """Penaliza quedas profundas e longas — complementa a volatilidade."""
    dd = drawdown(series) * 100
    return np.sqrt((dd.clip(upper=0) ** 2).rolling(window, min_periods=10).mean())


def downside_deviation(returns: pd.Series, window: int = 90, target: float = 0.0) -> pd.Series:
    diff = (returns - target).clip(upper=0.0)
    return np.sqrt((diff**2).rolling(window, min_periods=20).mean()) * np.sqrt(TRADING_DAYS)


# ---------------------------------------------------------------------------
# Posição relativa / mean reversion
# ---------------------------------------------------------------------------

def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    sd = series.rolling(window, min_periods=max(5, window // 3)).std()
    return pd.DataFrame({"mid": mid, "upper": mid + n_std * sd, "lower": mid - n_std * sd,
                         "width": (2 * n_std * sd / mid.replace(0, np.nan)),
                         "pctb": (series - (mid - n_std * sd)) / (2 * n_std * sd).replace(0, np.nan)})


def position_in_range(series: pd.Series, window: int = 90) -> pd.Series:
    """Onde o preço está entre mínima e máxima recentes (0 = fundo, 1 = topo)."""
    lo = series.rolling(window, min_periods=max(10, window // 4)).min()
    hi = series.rolling(window, min_periods=max(10, window // 4)).max()
    return ((series - lo) / (hi - lo).replace(0, np.nan)).fillna(0.5).clip(0, 1)


def distance_to_sma(series: pd.Series, window: int) -> pd.Series:
    return series / sma(series, window) - 1.0


# ---------------------------------------------------------------------------
# Construção do painel de indicadores por ativo
# ---------------------------------------------------------------------------

def build_indicator_snapshot(price: pd.Series, high: pd.Series | None = None,
                             low: pd.Series | None = None) -> dict[str, float]:
    """Foto instantânea dos indicadores usados nas explicações e no gráfico."""
    high = high if high is not None else price
    low = low if low is not None else price
    rets = price.pct_change()

    out = {
        "preco": float(price.iloc[-1]),
        "sma7": float(sma(price, 7).iloc[-1]),
        "sma21": float(sma(price, 21).iloc[-1]),
        "sma50": float(sma(price, 50).iloc[-1]),
        "sma200": float(sma(price, 200).iloc[-1]) if len(price) > 60 else float("nan"),
        "rsi14": float(rsi(price, 14).iloc[-1]),
        "vol30d": float(realized_vol(rets, 30).iloc[-1]),
        "vol90d": float(realized_vol(rets, 90).iloc[-1]),
        "vol_zscore": float(zscore(realized_vol(rets, 30).dropna(), 180).iloc[-1]),
        "retorno_7d": float(roc(price, 7).iloc[-1]),
        "retorno_30d": float(roc(price, 30).iloc[-1]),
        "retorno_90d": float(roc(price, 90).iloc[-1]),
        "retorno_365d": float(roc(price, 365).iloc[-1]) if len(price) > 365 else float("nan"),
        "drawdown_atual": float(drawdown(price).iloc[-1]),
        "max_drawdown": max_drawdown(price),
        "posicao_faixa_90d": float(position_in_range(price, 90).iloc[-1]),
        "dist_sma200": float(distance_to_sma(price, 200).iloc[-1]) if len(price) > 60 else float("nan"),
        "atr14_pct": float(atr(high, low, price, 14).iloc[-1] / price.iloc[-1]),
        "ulcer": float(ulcer_index(price).iloc[-1]),
    }
    m = macd(price)
    out["macd_hist"] = float(m["hist"].iloc[-1])
    if len(price) > 30:
        out["adx14"] = float(adx(high, low, price).iloc[-1])
        mom = momentum_score(price)
        out["momentum"] = float(mom.iloc[-1]) if np.isfinite(mom.iloc[-1]) else 0.0
    else:
        out["adx14"] = float("nan")
        out["momentum"] = 0.0
    return {k: (0.0 if isinstance(v, float) and not np.isfinite(v) else v) for k, v in out.items()}


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices / prices.shift(1)).replace([np.inf, -np.inf], np.nan)


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().replace([np.inf, -np.inf], np.nan)
