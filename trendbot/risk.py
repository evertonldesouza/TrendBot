"""Motor de risco de carteira.

Aqui está o núcleo do que faz o TrendBot ser um *orientador* e não um
adivinhador: medir, atribuir e limitar risco. Todas as funções são puras e
trabalham com retornos diários.

Decisões de modelagem
---------------------
* **365 dias/ano** — cripto negocia todo dia, não há dias úteis.
* **Covariância EWMA + contração (shrinkage)** para alvo de correlação
  constante (estilo Ledoit-Wolf): matrizes amostrais de cripto são ruidosas e
  a contração evita alocações absurdas vindas de ruído de estimação.
* **VaR/CVaR históricos e paramétricos** lado a lado — quando divergem, é
  sinal de cauda gorda, e o relatório diz isso.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

from .assets import CASH

import numpy as np
import pandas as pd

TRADING_DAYS = 365
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Estimativa de risco
# ---------------------------------------------------------------------------

def ewma_covariance(returns: pd.DataFrame, span: int = 180) -> pd.DataFrame:
    """Matriz de covariância anualizada com peso exponencial."""
    clean = returns.dropna(how="any")
    if clean.empty:
        raise ValueError("Sem retornos suficientes para estimar covariância.")
    if len(clean) < 30:
        span = max(20, len(clean) // 2)
    x = clean.to_numpy(dtype=float)
    weights = np.exp(-np.log(2) / max(span, 1) * np.arange(len(x))[::-1])
    weights /= weights.sum()
    mu = weights @ x
    xc = x - mu
    cov = (xc * weights[:, None]).T @ xc
    cov = 0.5 * (cov + cov.T)
    return pd.DataFrame(cov * TRADING_DAYS, index=clean.columns, columns=clean.columns)


def shrink_covariance(cov: pd.DataFrame, intensity: float = 0.25) -> pd.DataFrame:
    """Contração hacia o alvo de correlação constante (Ledoit-Wolf simplificado).

    Em cripto as correlações sobem todas juntas em estresse; contrair para uma
    correlação média é uma forma barata de não confiar demais na amostra.
    """
    if not 0.0 <= intensity <= 1.0:
        raise ValueError("intensity deve estar entre 0 e 1.")
    sd = np.sqrt(np.clip(np.diag(cov.to_numpy(dtype=float)), 1e-12, None))
    corr = cov.to_numpy(dtype=float) / np.outer(sd, sd)
    corr = np.clip(corr, -0.99, 0.99)
    n = len(sd)
    off = corr[~np.eye(n, dtype=bool)]
    rho = float(np.mean(off)) if len(off) else 0.0
    target_corr = np.full((n, n), rho)
    np.fill_diagonal(target_corr, 1.0)
    shrunk = (1 - intensity) * corr + intensity * target_corr
    return pd.DataFrame(shrunk * np.outer(sd, sd), index=cov.index, columns=cov.columns)


def estimate_covariance(returns: pd.DataFrame, span: int = 180,
                        shrink: float = 0.25) -> pd.DataFrame:
    return shrink_covariance(ewma_covariance(returns, span=span), intensity=shrink)


def correlation_matrix(returns: pd.DataFrame, span: int = 120) -> pd.DataFrame:
    cov = estimate_covariance(returns, span=span, shrink=0.15)
    sd = np.sqrt(np.diag(cov.to_numpy(dtype=float)))
    corr = cov.to_numpy(dtype=float) / np.outer(sd, sd)
    return pd.DataFrame(np.clip(corr, -1, 1), index=cov.index, columns=cov.columns)


# ---------------------------------------------------------------------------
# Métricas de carteira
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PortfolioRisk:
    volatility: float
    downside_vol: float
    var95: float            # 1 dia, histórico (positivo = perda)
    var99: float
    cvar95: float
    var95_param: float
    max_drawdown: float
    current_drawdown: float
    sharpe: float
    sortino: float
    calmar: float
    beta: float
    concentration_hhi: float
    top_weight: float
    diversification_ratio: float
    risk_contributions: dict[str, float] = field(default_factory=dict)
    annual_return: float = 0.0
    worst_day: float = 0.0
    best_day: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def portfolio_returns(weights: pd.Series | dict[str, float],
                      returns: pd.DataFrame) -> pd.Series:
    w = pd.Series(weights, dtype=float)
    cols = [c for c in w.index if c in returns.columns]
    w = w.reindex(cols).fillna(0.0)
    if abs(w.sum()) < 1e-9:
        return pd.Series(0.0, index=returns.index)
    return (returns[cols] * w).sum(axis=1)


def portfolio_risk(weights: pd.Series | dict[str, float],
                   returns: pd.DataFrame,
                   cov: pd.DataFrame | None = None,
                   benchmark: str | None = "BTC",
                   risk_free: float = 0.045,
                   normalize: bool = False) -> PortfolioRisk:
    """Calcula o conjunto completo de métricas de risco de uma carteira.

    Os pesos são usados como estão: se somam menos de 100%, a diferença é
    caixa, que tem risco zero e **não** é renormalizada. Renormalizar faria o
    colchão de caixa desaparecer das métricas — o erro clássico de quem acha
    que está protegido e não está.
    """
    w = pd.Series(weights, dtype=float)
    w = w.drop(labels=[c for c in (CASH,) if c in w.index and c not in returns.columns])
    cols = [c for c in w.index if c in returns.columns]
    w = w.reindex(cols).fillna(0.0).astype(float)
    if normalize:
        total = float(w.sum())
        if total > 1e-9:
            w = w / total

    if cov is None:
        cov = estimate_covariance(returns[cols])
    cov = cov.reindex(index=cols, columns=cols).fillna(0.0)

    wv = w.to_numpy(dtype=float)
    cm = cov.to_numpy(dtype=float)
    var_ann = float(wv @ cm @ wv)
    vol = float(np.sqrt(max(var_ann, 0.0)))

    pr = portfolio_returns(w, returns)
    pr = pr.dropna()
    if pr.empty:
        raise ValueError("Sem histórico de retornos da carteira.")

    # VaR histórico usa a janela recente: o risco de 3 anos atrás não descreve
    # o regime atual, e misturar os dois produz um número confortável e inútil.
    daily = pr.tail(365).to_numpy(dtype=float)
    var95 = float(-np.quantile(daily, 0.05))
    var99 = float(-np.quantile(daily, 0.01))
    tail = daily[daily <= np.quantile(daily, 0.05)]
    cvar95 = float(-tail.mean()) if len(tail) else var95
    var95_param = float(1.645 * vol / np.sqrt(TRADING_DAYS))

    downside = daily[daily < 0]
    downside_vol = float(np.sqrt(np.mean(downside**2) * TRADING_DAYS)) if len(downside) else 0.0

    curve = (1 + pr).cumprod()
    dd = curve / curve.cummax() - 1.0
    max_dd = float(dd.min())
    cur_dd = float(dd.iloc[-1])

    ann_ret = float((1 + daily.mean()) ** TRADING_DAYS - 1)
    excess = ann_ret - risk_free
    sharpe = float(excess / vol) if vol > 1e-9 else 0.0
    sortino = float(excess / downside_vol) if downside_vol > 1e-9 else 0.0
    calmar = float(ann_ret / abs(max_dd)) if max_dd < -1e-6 else 0.0

    beta = 1.0
    if benchmark and benchmark in returns.columns:
        bench = returns[benchmark].dropna()
        aligned = pd.concat([pr.rename("p"), bench.rename("b")], axis=1).dropna()
        if len(aligned) > 60:
            cov_pb = float(np.cov(aligned["p"], aligned["b"])[0, 1])
            var_b = float(np.var(aligned["b"], ddof=1))
            beta = float(cov_pb / var_b) if var_b > 1e-12 else 1.0

    w_abs = np.abs(wv)
    hhi = float(np.sum(w_abs**2))
    top = float(np.max(w_abs)) if len(w_abs) else 0.0

    sd_i = np.sqrt(np.clip(np.diag(cm), 1e-12, None))
    weighted_sd = float(w_abs @ sd_i)
    div_ratio = float(weighted_sd / vol) if vol > 1e-9 else 1.0

    contrib = (wv * (cm @ wv)) / max(var_ann, 1e-12)
    risk_contrib = {c: float(v) for c, v in zip(cols, contrib)}

    return PortfolioRisk(
        volatility=vol,
        downside_vol=downside_vol,
        var95=var95,
        var99=var99,
        cvar95=cvar95,
        var95_param=var95_param,
        max_drawdown=max_dd,
        current_drawdown=cur_dd,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        beta=beta,
        concentration_hhi=hhi,
        top_weight=top,
        diversification_ratio=div_ratio,
        risk_contributions=risk_contrib,
        annual_return=ann_ret,
        worst_day=float(daily.min()),
        best_day=float(daily.max()),
    )


# ---------------------------------------------------------------------------
# Estresse
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict[str, float]] = {
    "inverno_cripto": dict(shock=-0.60, corr=0.95, vol_mult=1.8,
                           label="Inverno cripto (-60% no BTC, correlações a 0,95)"),
    "correcao_forte": dict(shock=-0.35, corr=0.90, vol_mult=1.4,
                           label="Correção forte (-35% no BTC)"),
    "choque_liquidez": dict(shock=-0.22, corr=0.98, vol_mult=2.2,
                            label="Choque de liquidez (-22% em um dia, tudo correlacionado)"),
    "alta_forte": dict(shock=0.45, corr=0.80, vol_mult=1.1,
                       label="Alta forte (+45% no BTC)"),
}


def stress_test(weights: pd.Series | dict[str, float],
                returns: pd.DataFrame,
                cov: pd.DataFrame | None = None,
                scenarios: dict[str, dict[str, float]] = SCENARIOS,
                horizon_days: int = 30) -> list[dict]:
    """Impacto estimado da carteira sob cenários adversos.

    Não é previsão: é uma pergunta do tipo "se o BTC cair X e tudo virar uma
    coisa só, quanto eu perco?". Usa volatilidade e beta estimados.
    """
    w = pd.Series(weights, dtype=float)
    cols = [c for c in w.index if c in returns.columns]
    # Mantém os pesos como estão: a parcela em caixa não sofre choque e NÃO é
    # renormalizada — é justamente ela que amortece o cenário adverso.
    w = w.reindex(cols).fillna(0.0)

    if cov is None:
        cov = estimate_covariance(returns[cols])
    sd = pd.Series(np.sqrt(np.clip(np.diag(cov.to_numpy(dtype=float)), 1e-12, None)),
                   index=cov.index)

    # beta de cada ativo contra o benchmark (primeira coluna = proxy de mercado)
    market = returns[cols[0]] if cols else returns.iloc[:, 0]
    betas: dict[str, float] = {}
    for c in cols:
        aligned = pd.concat([returns[c], market], axis=1).dropna()
        if len(aligned) > 60:
            var_m = float(np.var(aligned.iloc[:, 1], ddof=1))
            betas[c] = float(np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])[0, 1] / var_m) if var_m > 1e-12 else 1.0
        else:
            betas[c] = 1.0

    out: list[dict] = []
    for key, cfg in scenarios.items():
        shock, target_corr = cfg["shock"], cfg["corr"]
        # perda sistemática (beta x choque) + dispersão idiossincrática
        systematic = sum(float(w[c]) * betas.get(c, 1.0) for c in cols) * shock
        vol_scale = (sd * np.sqrt(horizon_days / TRADING_DAYS) * cfg["vol_mult"])
        # pior caso a 95% dentro do cenário
        worst = 0.0
        for c in cols:
            wc = float(w[c]) * (betas.get(c, 1.0) * shock - 1.645 * float(vol_scale[c]))
            worst += wc
        # penalidade de correlação: carteira diversificada perde a proteção
        corr_penalty = -0.05 * float(w[cols].sum()) if target_corr > 0.9 else 0.0
        out.append({
            "cenario": key,
            "label": cfg["label"],
            "impacto_base": float(max(systematic + corr_penalty, -0.95)),
            "impacto_estresse_95": float(max(worst + corr_penalty, -0.95)),
            "correlacao_alvo": float(target_corr),
        })
    return out


# ---------------------------------------------------------------------------
# Orçamento de risco
# ---------------------------------------------------------------------------

def risk_parity_weights(cov: pd.DataFrame, budget: dict[str, float] | None = None,
                        max_iter: int = 200) -> pd.Series:
    """Pesos de paridade de risco (cada ativo contribui igualmente para o risco).

    Implementação por ponto fixo (Spinu / cyclical coordinate descent), estável
    e sem dependências externas.
    """
    cm = cov.to_numpy(dtype=float)
    n = len(cm)
    cm = 0.5 * (cm + cm.T)
    cm = cm + 1e-10 * np.eye(n)
    if budget:
        b = np.array([budget.get(c, 1.0) for c in cov.columns], dtype=float)
        b = b / b.sum()
    else:
        b = np.full(n, 1.0 / n)

    w = np.sqrt(b) / np.sqrt(np.clip(np.diag(cm), 1e-10, None))
    w = w / w.sum()
    for _ in range(max_iter):
        wv = cm @ w
        new_w = np.sqrt(b * w**2 / (w * wv + 1e-16))
        new_w = new_w / new_w.sum()
        if np.max(np.abs(new_w - w)) < 1e-10:
            w = new_w
            break
        w = new_w
    return pd.Series(w, index=cov.columns)


def min_variance_weights(cov: pd.DataFrame, max_weight: float = 0.5) -> pd.Series:
    """Carteira de mínima variância com teto por ativo (projeção simples)."""
    cm = cov.to_numpy(dtype=float) + 1e-10 * np.eye(len(cov))
    inv = np.linalg.pinv(cm)
    ones = np.ones(len(cm))
    w = inv @ ones
    w = np.clip(w, 0, None)
    if w.sum() <= 0:
        w = ones / len(ones)
    w = w / w.sum()
    # projeta o teto por ativo de forma iterativa (redistribui o excesso)
    for _ in range(50):
        over = w > max_weight
        if not over.any():
            break
        excess = float((w[over] - max_weight).sum())
        w[over] = max_weight
        free = ~over
        if free.sum() == 0:
            break
        w[free] += excess * (w[free] / max(w[free].sum(), 1e-12))
    return pd.Series(w / max(w.sum(), 1e-12), index=cov.columns)
