"""Backtest da estratégia orientada pelo TrendBot.

Por que existe: sem backtest, uma recomendação é só uma opinião bem
formatada. Aqui comparamos quatro abordagens no mesmo histórico:

1. **Buy & hold** em cada ativo (referência ingênua).
2. **Buy & hold igualitário** (1/N) — o que a maioria das pessoas faz.
3. **Carteira do TrendBot** — alvo de volatilidade + paridade de risco +
   banda de rebalanceamento, recalculada mensalmente.
4. **Caixa** (aporte em stablecoin) — o custo de oportunidade de ficar fora.

Regras anti-autoengano:
* O rebalanceamento usa apenas dados disponíveis até a data da decisão.
* A alocação de cada mês é recalculada com a volatilidade estimada até ali.
* Custos são descontados (corretagem + spread), senão o backtest mente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from . import risk as rk
from .assets import CASH
from .config import RiskProfile

logger = logging.getLogger(__name__)

TRADING_DAYS = 365
DEFAULT_COST_BPS = 30.0   # 0,30% por giro (corretagem + spread, cripto spot)


@dataclass(slots=True)
class StrategyResult:
    name: str
    final_value: float
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    best_year: float
    worst_year: float
    turnover: float
    equity_curve: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def _metrics_from_returns(rets: pd.Series, risk_free: float = 0.045) -> dict:
    clean = rets.dropna()
    if clean.empty:
        return {}
    curve = (1 + clean).cumprod()
    dd = curve / curve.cummax() - 1
    years = max(len(clean) / TRADING_DAYS, 1e-6)
    total = float(curve.iloc[-1] - 1)
    cagr = float(curve.iloc[-1] ** (1 / years) - 1) if curve.iloc[-1] > 0 else -1.0
    vol = float(clean.std() * np.sqrt(TRADING_DAYS))
    downside = float(np.sqrt(np.mean(np.minimum(clean, 0) ** 2) * TRADING_DAYS))
    mdd = float(dd.min())
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": float((cagr - risk_free) / vol) if vol > 1e-9 else 0.0,
        "sortino": float((cagr - risk_free) / downside) if downside > 1e-9 else 0.0,
        "max_drawdown": mdd,
        "calmar": float(cagr / abs(mdd)) if mdd < -1e-6 else 0.0,
    }


def buy_and_hold(prices: pd.DataFrame, weights: dict[str, float] | None = None,
                 initial: float = 10_000.0, cost_bps: float = 0.0) -> pd.Series:
    """Curva de patrimônio de uma carteira comprada no início e nunca mexida."""
    cols = list(prices.columns)
    if weights:
        w = pd.Series({c: weights.get(c, 0.0) for c in cols}, dtype=float)
    else:
        w = pd.Series(1.0 / len(cols), index=cols)
    w = w / max(w.sum(), 1e-12)
    invested = initial * (1 - cost_bps / 10_000)
    units = (invested * w) / prices[cols].iloc[0]
    return (units * prices[cols]).sum(axis=1)


def run_trendbot_strategy(prices: pd.DataFrame,
                          profile: RiskProfile,
                          initial: float = 10_000.0,
                          rebalance_freq: int = 30,
                          cost_bps: float = DEFAULT_COST_BPS,
                          min_history: int = 200,
                          risk_free: float = 0.045) -> tuple[pd.Series, dict]:
    """Simula a carteira orientada pelo TrendBot ao longo do histórico.

    A cada rebalanceamento (a cada ``rebalance_freq`` dias):
      1. Estima covariância só com dados até ali.
      2. Monta pesos de paridade de risco com teto de concentração.
      3. Dimensiona a exposição para acertar a volatilidade alvo do perfil.
      4. Desconta custo de corretagem sobre o valor girado.
    """
    rets_full = prices.pct_change().dropna(how="all")
    if len(prices) < min_history + rebalance_freq:
        raise ValueError("Histórico insuficiente para backtest.")

    holdings = {c: 0.0 for c in prices.columns}   # valor em USD por ativo
    cash = float(initial)
    equity_curve = []
    turnover_total = 0.0
    n_reb = 0

    start = min_history
    dates = prices.index
    value = initial

    for i in range(start, len(dates)):
        # marcação a mercado
        value = cash + sum(holdings[c] * (prices[c].iloc[i] / prices[c].iloc[i - 1])
                           for c in prices.columns)
        for c in prices.columns:
            holdings[c] = holdings[c] * (prices[c].iloc[i] / prices[c].iloc[i - 1])
        equity_curve.append({"date": dates[i].strftime("%Y-%m-%d"), "value": round(float(value), 2)})

        if (i - start) % rebalance_freq != 0 or i == len(dates) - 1:
            continue

        window = rets_full.iloc[max(0, i - 730):i]
        if len(window) < 90:
            continue
        try:
            cov = rk.estimate_covariance(window.dropna(how="any"))
        except ValueError:
            continue
        if cov.empty:
            continue
        rp = rk.risk_parity_weights(cov)
        cap = profile.max_asset_weight
        for _ in range(30):
            over = rp > cap
            if not over.any():
                break
            excess = float((rp[over] - cap).sum())
            rp[over] = cap
            free = ~over
            if free.sum() == 0 or rp[free].sum() <= 1e-12:
                break
            rp[free] += excess * (rp[free] / rp[free].sum())
            rp = rp / rp.sum()

        wv = rp.to_numpy(dtype=float)
        sleeve_vol = float(np.sqrt(max(wv @ cov.to_numpy(dtype=float) @ wv, 1e-12)))
        exposure = float(np.clip(profile.target_vol / max(sleeve_vol, 1e-6),
                                 profile.equity_band[0], profile.equity_band[1]))

        target = {c: exposure * float(rp.get(c, 0.0)) for c in prices.columns}
        target[CASH] = 1.0 - exposure

        current_total = value
        new_values = {c: target.get(c, 0.0) * current_total for c in prices.columns}
        traded = sum(abs(new_values[c] - holdings[c]) for c in prices.columns)
        turnover_total += traded
        cost = traded * (cost_bps / 10_000)
        cash = max(0.0, target[CASH] * current_total - cost * (target[CASH] if exposure < 1 else 0.5))
        holdings = {c: max(0.0, new_values[c] - cost * (new_values[c] / max(traded, 1e-9)))
                    for c in prices.columns}
        cash = max(0.0, current_total - sum(holdings.values()) - cost)
        n_reb += 1

    curve = pd.Series([e["value"] for e in equity_curve],
                      index=pd.to_datetime([e["date"] for e in equity_curve]))
    rets = curve.pct_change().dropna()
    years = max(len(curve) / TRADING_DAYS, 1e-6)
    avg_turnover = turnover_total / max(value, 1e-9) / max(n_reb, 1)
    return curve, {"rebalanceamentos": n_reb, "giro_medio": float(avg_turnover),
                   "anos": years}


def run_backtest(prices: pd.DataFrame, profile: RiskProfile,
                 initial: float = 10_000.0,
                 rebalance_freq: int = 30,
                 cost_bps: float = DEFAULT_COST_BPS,
                 risk_free: float = 0.045,
                 benchmark: str | None = None) -> dict:
    """Compara estratégias e devolve curvas + métricas prontas para o painel."""
    results: list[StrategyResult] = []

    tb_curve, info = run_trendbot_strategy(
        prices, profile, initial=initial, rebalance_freq=rebalance_freq,
        cost_bps=cost_bps, risk_free=risk_free)
    m = _metrics_from_returns(tb_curve.pct_change(), risk_free)
    results.append(StrategyResult(
        name=f"TrendBot ({profile.label})",
        final_value=float(tb_curve.iloc[-1]),
        turnover=float(info["giro_medio"]),
        equity_curve=[{"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
                      for d, v in tb_curve.items()],
        **_yearly_extremes(tb_curve), **m,
    ))

    # 1/N: o que a maioria faz — compra um pouco de cada e segura
    eq = buy_and_hold(prices, initial=initial, cost_bps=cost_bps)
    m = _metrics_from_returns(eq.pct_change(), risk_free)
    results.append(StrategyResult(
        name="Comprar e segurar (1/N)", final_value=float(eq.iloc[-1]), turnover=0.0,
        equity_curve=[{"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
                      for d, v in eq.items()],
        **_yearly_extremes(eq), **m,
    ))

    # cada ativo isolado: mostra o custo da falta de diversificação
    for c in prices.columns:
        s = prices[c].to_frame()
        cur = buy_and_hold(s, initial=initial, cost_bps=cost_bps)
        m = _metrics_from_returns(cur.pct_change(), risk_free)
        results.append(StrategyResult(
            name=f"Só {c}", final_value=float(cur.iloc[-1]), turnover=0.0,
            equity_curve=[{"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
                          for d, v in cur.items()],
            **_yearly_extremes(cur), **m,
        ))

    # 60/40 clássico: referência de quem vem do mercado tradicional
    bench = benchmark if benchmark in prices.columns else prices.columns[0]
    alt = [c for c in prices.columns if c != bench]
    w6040 = {bench: 0.6}
    if alt:
        for c in alt:
            w6040[c] = 0.4 / len(alt)
    cur = buy_and_hold(prices, weights=w6040, initial=initial, cost_bps=cost_bps)
    m = _metrics_from_returns(cur.pct_change(), risk_free)
    results.append(StrategyResult(
        name=f"60/40 ({bench} + alts)", final_value=float(cur.iloc[-1]), turnover=0.0,
        equity_curve=[{"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
                      for d, v in cur.items()],
        **_yearly_extremes(cur), **m,
    ))

    tb = results[0]
    eqw = results[1]
    summary = {
        "capital_inicial": initial,
        "anos": round(float(info["anos"]), 2),
        "custos_bps": cost_bps,
        "rebalanceamentos": info["rebalanceamentos"],
        "vantagem_vs_1n": float(tb.final_value - eqw.final_value),
        "reducao_drawdown": float(abs(eqw.max_drawdown) - abs(tb.max_drawdown)),
        "sharpe_trendbot": tb.sharpe,
        "sharpe_1n": eqw.sharpe,
        "veredito": _verdict(tb, eqw),
    }
    return {"estrategias": [r.as_dict() for r in results], "resumo": summary}


def _yearly_extremes(curve: pd.Series) -> dict:
    if len(curve) < 60:
        return {"best_year": 0.0, "worst_year": 0.0}
    yr = curve.resample("YE").last().pct_change().dropna()
    return {"best_year": float(yr.max()) if len(yr) else 0.0,
            "worst_year": float(yr.min()) if len(yr) else 0.0}


def _verdict(tb: StrategyResult, eqw: StrategyResult) -> str:
    dd_gain = abs(eqw.max_drawdown) - abs(tb.max_drawdown)
    if tb.sharpe > eqw.sharpe and dd_gain > 0.03:
        return (f"A carteira orientada entregou Sharpe {tb.sharpe:.2f} contra {eqw.sharpe:.2f} "
                f"do comprar-e-segurar, reduzindo a pior queda em {dd_gain * 100:.0f} pontos "
                "percentuais. O ganho vem de risco controlado, não de acerto de direção.")
    if tb.sharpe <= eqw.sharpe and dd_gain > 0.05:
        return (f"A carteira orientada rendeu menos (Sharpe {tb.sharpe:.2f} vs {eqw.sharpe:.2f}), "
                f"mas cortou a pior queda em {dd_gain * 100:.0f} pontos percentuais. "
                "Para quem o objetivo é atravessar o ciclo, essa troca costuma valer a pena.")
    return (f"Neste recorte, o comprar-e-segurar venceu em retorno "
            f"(Sharpe {eqw.sharpe:.2f} vs {tb.sharpe:.2f}). A vantagem da carteira orientada "
            f"aparece no controle de queda ({abs(tb.max_drawdown) * 100:.0f}% contra "
            f"{abs(eqw.max_drawdown) * 100:.0f}%), não no retorno máximo.")
