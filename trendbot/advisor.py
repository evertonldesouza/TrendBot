"""Motor de orientação de investimentos (alocação, hedge e rebalanceamento).

A tese do TrendBot: **o retorno esperado é quase imprevisível; o risco é
gestionável**. Então o fluxo de decisão é:

1. Definir o orçamento de risco a partir do perfil do investidor.
2. Distribuir esse orçamento entre ativos com critérios robustos (paridade de
   risco + inclinação por convicção, nunca "aposta").
3. Dimensionar o colchão de caixa/hedge para que a volatilidade da carteira
   caia dentro do alvo — é isso que transforma cripto em algo suportável.
4. Converter a carteira alvo em ordens concretas, só quando o desvio passa da
   banda (evita girar carteira à toa).
5. Explicar cada decisão e declarar o que a invalidaria.

Nenhuma função aqui "prevê o futuro": todas leem previsões já calibradas e
aplicam regras de risco auditáveis.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from . import risk as rk
from .assets import CASH
from .config import PortfolioState, RiskProfile, Settings
from .data import MarketData
from .forecast import AssetForecast, ModelCard

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Estruturas de saída
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Order:
    symbol: str
    action: str                  # COMPRAR | VENDER | MANTER | ZERAR | APORTAR
    target_weight: float
    current_weight: float
    delta_weight: float
    amount: float                # em USD (positivo = compra)
    reason: str
    priority: int = 3            # 1 = alta, 3 = baixa

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class HedgePlan:
    cash_weight: float
    cash_amount: float
    rationale: str
    triggers: list[str] = field(default_factory=list)
    de_risk_level: str = "nenhum"   # nenhum | leve | moderado | severo

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Alert:
    level: str          # info | atencao | critico
    title: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Advice:
    profile: str
    generated_at: str
    equity_exposure: float
    target_weights: dict[str, float]
    current_weights: dict[str, float]
    benchmark_weights: dict[str, float]
    orders: list[Order]
    hedge: HedgePlan
    risk_current: dict
    risk_target: dict
    stress: list[dict]
    alerts: list[Alert]
    narrative: dict
    diagnostics: dict
    contributions: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "generated_at": self.generated_at,
            "equity_exposure": self.equity_exposure,
            "target_weights": self.target_weights,
            "current_weights": self.current_weights,
            "benchmark_weights": self.benchmark_weights,
            "orders": [o.as_dict() for o in self.orders],
            "hedge": self.hedge.as_dict(),
            "risk_current": self.risk_current,
            "risk_target": self.risk_target,
            "stress": self.stress,
            "alerts": [a.as_dict() for a in self.alerts],
            "narrative": self.narrative,
            "diagnostics": self.diagnostics,
            "contributions": self.contributions,
        }


# ---------------------------------------------------------------------------
# Passo 1 — orçamento de risco
# ---------------------------------------------------------------------------

def market_conviction(forecasts: dict[str, AssetForecast],
                      weights: dict[str, float]) -> tuple[float, str]:
    """Convicção agregada do mercado, ponderada pelos pesos propostos."""
    num, den = 0.0, 0.0
    for sym, f in forecasts.items():
        w = abs(weights.get(sym, 0.0))
        num += w * f.conviction
        den += w
    conv = float(num / den) if den > 1e-9 else 0.0
    if conv > 0.25:
        label = "construtivo"
    elif conv < -0.25:
        label = "defensivo"
    else:
        label = "neutro"
    return conv, label


def equity_exposure(profile: RiskProfile, conviction: float,
                    sleeve_vol: float, crisis_pressure: float,
                    tilt_fraction: float = 0.30) -> float:
    """Quanto do patrimônio deve ficar exposto a risco.

    O ponto de partida não é "quantos % em cripto", e sim **qual risco cabe no
    perfil**: a exposição que faz a cesta de risco atingir a volatilidade alvo
    é ``target_vol / vol_da_cesta``. Sobre esse número agem (a) a inclinação
    por convicção, limitada, e (b) um corte de crise. O resultado é limitado à
    faixa do perfil e ao teto de volatilidade que ele aceita.
    """
    lo, hi = profile.equity_band
    if sleeve_vol <= 1e-6:
        return lo

    base = profile.target_vol / sleeve_vol
    tilt = tilt_fraction * float(np.clip(conviction, -1, 1))
    exposure = base * (1.0 + tilt)
    exposure *= (1.0 - 0.25 * float(np.clip(crisis_pressure, 0, 1)))

    ceiling = profile.max_vol / sleeve_vol       # nunca excede o teto de risco
    exposure = min(exposure, ceiling)
    return float(np.clip(exposure, lo * 0.6, hi))


# ---------------------------------------------------------------------------
# Passo 2 — pesos entre ativos
# ---------------------------------------------------------------------------

def _risk_penalty(f: AssetForecast) -> float:
    """Multiplicador de penalidade de risco específico do ativo (0.4 .. 1.15)."""
    ind = f.indicators
    pen = 1.0
    vz = ind.get("vol_zscore", 0.0)
    if vz > 2.0:
        pen *= 0.70
    elif vz > 1.0:
        pen *= 0.85
    elif vz < -0.8:
        pen *= 1.10

    dd = ind.get("drawdown_atual", 0.0)
    if dd < -0.60:
        pen *= 0.80
    elif dd < -0.35:
        pen *= 0.92

    rsi = ind.get("rsi14", 50.0)
    if rsi > 78:
        pen *= 0.90

    if f.regime == "risco-desligado":
        pen *= 0.90
    elif f.regime == "risco-ligado":
        pen *= 1.08
    return float(np.clip(pen, 0.40, 1.15))


def target_asset_weights(cov: pd.DataFrame,
                         forecasts: dict[str, AssetForecast],
                         profile: RiskProfile,
                         conviction: float,
                         min_variance_blend: float = 0.0) -> pd.Series:
    """Pesos relativos entre os ativos de risco (somam 1).

    Base = paridade de risco (não depende de previsão de retorno). Em cima
    disso aplica-se uma inclinação limitada por convicção e penalidades de
    risco por ativo. Em regime defensivo, mistura-se mínima variância.
    """
    symbols = [s for s in cov.columns if s in forecasts]
    if not symbols:
        return pd.Series(dtype=float)
    cov_s = cov.loc[symbols, symbols]

    rp = rk.risk_parity_weights(cov_s)
    mv = rk.min_variance_weights(cov_s, max_weight=profile.max_asset_weight)
    base = (1 - min_variance_blend) * rp + min_variance_blend * mv
    base = base.clip(lower=0.0)
    base = base / max(base.sum(), 1e-12)

    tilt_strength = 0.35 + 0.35 * float(np.clip(conviction, -1, 1))
    weights = {}
    for s in symbols:
        f = forecasts[s]
        factor = 1.0 + tilt_strength * f.conviction
        weights[s] = float(base[s]) * factor * _risk_penalty(f)

    w = pd.Series(weights, dtype=float).clip(lower=0.0)
    if w.sum() <= 1e-12:
        return base
    w = w / w.sum()

    # teto de concentração com redistribuição iterativa
    cap = profile.max_asset_weight
    for _ in range(30):
        over = w > cap
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        free = ~over
        if free.sum() == 0 or w[free].sum() <= 1e-12:
            break
        w[free] += excess * (w[free] / w[free].sum())
        w = w / w.sum()

    # pó de arroz: posições irrelevantes só atrapalham a execução
    floor = 0.02
    w[w < floor] = 0.0
    if w.sum() <= 1e-12:
        return base
    return w / w.sum()


# ---------------------------------------------------------------------------
# Passo 3 — plano de contribuição (aportes)
# ---------------------------------------------------------------------------

def contribution_plan(target: dict[str, float], current: dict[str, float],
                      amount: float, capital: float) -> list[dict]:
    """Distribui um aporte comprando primeiro o que está mais abaixo do alvo.

    Aportar no que está defasado corrige a carteira sem vender nada — é a
    forma mais barata (e, no Brasil, mais eficiente) de rebalancear.
    """
    if amount <= 0 or capital <= 0:
        return []
    projected = {s: current.get(s, 0.0) * capital for s in set(target) | set(current)}
    new_total = capital + amount
    gaps = {}
    for s, tw in target.items():
        cur_value = projected.get(s, 0.0)
        need = tw * new_total - cur_value
        gaps[s] = max(0.0, need)
    for s, cw in current.items():
        if s not in target and cw > 0:
            gaps[s] = 0.0

    total_need = sum(gaps.values())
    if total_need <= 1e-9:
        # carteira já equilibrada: aporte segue o alvo
        return [{"symbol": s, "valor": round(amount * w, 2), "peso": round(w, 4)}
                for s, w in sorted(target.items(), key=lambda kv: -kv[1]) if w > 0]

    plan = []
    allocated = 0.0
    for s, need in sorted(gaps.items(), key=lambda kv: -kv[1]):
        if need <= 0:
            continue
        value = min(need, amount * (need / total_need))
        if value < 1e-6:
            continue
        plan.append({"symbol": s, "valor": round(float(value), 2),
                     "peso": round(float(value / amount), 4)})
        allocated += value
    if plan and allocated > 0 and abs(allocated - amount) / amount > 0.02:
        plan[0]["valor"] = round(plan[0]["valor"] + (amount - allocated), 2)
        plan[0]["peso"] = round(plan[0]["valor"] / amount, 4)
    return plan


# ---------------------------------------------------------------------------
# Passo 4 — ordens
# ---------------------------------------------------------------------------

def build_orders(target: dict[str, float], current: dict[str, float],
                 capital: float, profile: RiskProfile,
                 prices: dict[str, float] | None = None) -> list[Order]:
    symbols = sorted(set(target) | set(current),
                     key=lambda s: -abs(target.get(s, 0.0) - current.get(s, 0.0)))
    orders: list[Order] = []
    band = profile.rebalance_band

    for s in symbols:
        tw = float(target.get(s, 0.0))
        cw = float(current.get(s, 0.0))
        delta = tw - cw
        amount = delta * capital
        is_cash = s == CASH
        action = "MANTER"

        if is_cash:
            if abs(delta) >= band:
                action = "AUMENTAR CAIXA" if delta > 0 else "LIBERAR CAIXA"
            reason = ("Colchão de segurança: reduz a volatilidade da carteira e "
                      "dá munição para aportar em quedas." if tw > cw else
                      "Caixa acima do necessário para o risco atual — parte dele "
                      "pode ser colocada para trabalhar.")
            orders.append(Order(s, action, round(tw, 4), round(cw, 4), round(delta, 4),
                                round(amount, 2), reason, priority=2 if abs(delta) >= band else 3))
            continue

        if abs(delta) < band:
            reason = f"Dentro da banda de rebalanceamento ({band:.0%}) — manter evita custo e giro à toa."
            if cw > 0 and tw == 0:
                action = "ZERAR"
                reason = "Ativo fora da carteira recomendada neste cenário de risco."
            orders.append(Order(s, action, round(tw, 4), round(cw, 4), round(delta, 4),
                                round(amount, 2), reason, priority=3))
            continue

        if delta > 0:
            action = "COMPRAR"
            reason = f"Abaixo do alvo ({cw:.0%} → {tw:.0%})."
            priority = 1 if delta > 2 * band else 2
        else:
            action = "VENDER"
            reason = f"Acima do alvo ({cw:.0%} → {tw:.0%}): reduzir concentração e risco."
            priority = 1 if -delta > 2 * band else 2

        orders.append(Order(s, action, round(tw, 4), round(cw, 4), round(delta, 4),
                            round(amount, 2), reason, priority=priority))

    return orders


# ---------------------------------------------------------------------------
# Passo 5 — narrativa
# ---------------------------------------------------------------------------

def _fmt_pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def build_narrative(profile: RiskProfile, exposure: float, conviction: float,
                    conv_label: str, target: dict[str, float],
                    risk_target: rk.PortfolioRisk, risk_current: rk.PortfolioRisk,
                    hedge: HedgePlan, model: ModelCard,
                    forecasts: dict[str, AssetForecast],
                    contributions: list[dict]) -> dict:
    top = sorted(((s, w) for s, w in target.items() if s != CASH and w > 0),
                 key=lambda kv: -kv[1])
    top_txt = ", ".join(f"{s} {_fmt_pct(w, 0)}" for s, w in top[:3]) if top else "só caixa"

    headline = (
        f"Exposição recomendada a cripto: {_fmt_pct(exposure, 0)} do patrimônio "
        f"({top_txt}), com {_fmt_pct(hedge.cash_weight, 0)} em caixa."
    )

    bullet_points = [
        f"Perfil {profile.label}: volatilidade alvo de {_fmt_pct(profile.target_vol, 0)} ao ano e "
        f"tolerância a quedas de até {_fmt_pct(profile.max_drawdown, 0)}.",
        f"Carteira recomendada: volatilidade de {_fmt_pct(risk_target.volatility, 0)} ao ano, "
        f"VaR de 95% em 1 dia de {_fmt_pct(risk_target.var95, 1)} e pior queda histórica de "
        f"{abs(risk_target.max_drawdown) * 100:.0f}%.",
        f"Leitura de mercado {conv_label} (convicção {conviction:+.2f} numa escala de -1 a +1).",
        f"Colchão de caixa de {_fmt_pct(hedge.cash_weight, 0)}: {hedge.rationale}",
    ]
    if contributions:
        bullet_points.append(
            "Com aportes mensais, compre primeiro o que está abaixo do alvo — "
            "rebalanceia sem vender e sem pagar spread."
        )

    improvement = risk_current.volatility - risk_target.volatility
    if improvement > 0.02:
        bullet_points.append(
            f"Comparada à sua carteira atual, a recomendação reduz a volatilidade em "
            f"{improvement * 100:.0f} pontos percentuais."
        )
    elif improvement < -0.02:
        bullet_points.append(
            f"A recomendação aceita {-improvement * 100:.0f} pontos percentuais de volatilidade a mais que a "
            "sua carteira atual, porque o risco corrente está abaixo do seu limite."
        )

    watch_out = [
        f"Volatilidade realizada de 30 dias subir acima de {_fmt_pct(profile.max_vol, 0)} anualizados.",
        f"Queda do patrimônio superior a {_fmt_pct(profile.max_drawdown * 0.6, 0)} a partir do topo.",
        "Correlação média entre os ativos passar de 0,90 (diversificação deixa de funcionar).",
        "Mudança de regime: preço do BTC abaixo da média de 200 dias por mais de 15 dias.",
    ]

    invalidation = [
        "Se o seu horizonte for menor que 12 meses, esta alocação é agressiva demais.",
        "Se você não consegue conviver com uma queda de "
        f"{_fmt_pct(risk_target.max_drawdown, 0)}, reduza a exposição à metade.",
        f"Se o modelo apresentar habilidade negativa por 3 relatórios seguidos "
        f"(hoje: {model.avg_skill:+.2f}), o peso das previsões cai a zero e a "
        "carteira passa a ser puramente defensiva.",
    ]

    honesty = (
        "Retornos de cripto são quase imprevisíveis no curto prazo. Este relatório "
        "não tenta adivinhar o preço de amanhã: ele dimensiona risco, limita "
        "concentração e mantém um colchão de caixa para você atravessar a "
        "volatilidade sem tomar decisões ruins no pior momento."
    )

    return {
        "headline": headline,
        "pontos_principais": bullet_points,
        "o_que_observar": watch_out,
        "o_que_me_faria_mudar_de_ideia": invalidation,
        "sobre_o_modelo": honesty,
        "veredito_modelo": model.verdict,
        "notas_modelo": model.notes,
    }


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def build_advice(md: MarketData,
                 forecasts: dict[str, AssetForecast],
                 model: ModelCard,
                 profile: RiskProfile,
                 portfolio: PortfolioState,
                 settings: Settings) -> Advice:
    """Monta a recomendação completa a partir de dados, previsões e perfil."""
    from datetime import datetime, timezone

    returns = md.close.pct_change().dropna(how="all")
    symbols = [s for s in md.close.columns if s in forecasts]
    returns = returns[symbols].dropna(how="any")
    cov = rk.estimate_covariance(returns)

    current = portfolio.as_target_weights()
    capital = max(portfolio.total, portfolio.capital, 1.0)

    # --- pesos relativos (entre ativos de risco) ---
    rp_weights = rk.risk_parity_weights(cov)
    conviction, conv_label = market_conviction(forecasts, rp_weights.to_dict())

    # --- pressões de risco ---
    bench = settings.benchmark if settings.benchmark in md.close.columns else symbols[0]
    bench_vol = float(cov.loc[bench, bench] ** 0.5) if bench in cov.index else float(np.mean(np.diag(cov)) ** 0.5)
    # Pressão de volatilidade é sempre RELATIVA AO PRÓPRIO MERCADO: comparar a
    # vol do BTC com o alvo de uma carteira conservadora daria "3x" o tempo
    # todo e deixaria o sistema em pânico permanente.
    bench_longrun = float(returns[bench].std() * np.sqrt(rk.TRADING_DAYS)) if bench in returns else bench_vol
    vol_pressure = bench_vol / max(bench_longrun, 0.05)
    bench_price = md.close[bench]
    drawdown_pressure = float(np.clip(-(bench_price.iloc[-1] / bench_price.cummax().iloc[-1] - 1) / 0.40, 0, 1))

    defensive = conv_label == "defensivo" or vol_pressure > 1.5
    mv_blend = 0.35 if defensive else 0.10
    rel = target_asset_weights(cov, forecasts, profile, conviction, min_variance_blend=mv_blend)

    # volatilidade da cesta de risco (pesos relativos, somando 1)
    rel_vec = rel.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)
    sleeve_vol = float(np.sqrt(max(rel_vec @ cov.to_numpy(dtype=float) @ rel_vec, 1e-12)))

    bench_f = forecasts.get(bench)
    vol_z = float((bench_f.indicators.get("vol_zscore", 0.0) if bench_f else 0.0))
    crisis_pressure = float(np.clip(0.5 * drawdown_pressure + 0.5 * np.clip((vol_z - 1.0) / 2.0, 0, 1), 0, 1))

    exposure = equity_exposure(profile, conviction, sleeve_vol, crisis_pressure)

    # --- escala de vol: garante que a carteira caia no orçamento de risco ---
    scaled = {s: exposure * float(rel.get(s, 0.0)) for s in rel.index}
    w_risky = pd.Series(scaled, dtype=float)
    port_vol = float(np.sqrt(max(float(w_risky.to_numpy() @ cov.reindex(index=rel.index, columns=rel.index).to_numpy() @ w_risky.to_numpy()), 0.0)))
    vol_scale = 1.0
    if port_vol > profile.max_vol and port_vol > 1e-9:
        vol_scale = profile.max_vol / port_vol
        w_risky = w_risky * vol_scale
        logger.info("Corte de volatilidade aplicado: %.2f (vol %.0f%% -> alvo %.0f%%)",
                    vol_scale, port_vol, profile.max_vol)

    equity = float(w_risky.sum())
    cash_w = float(np.clip(1 - equity, profile.cash_floor if profile.cash_floor else 0.0, 1.0))
    if cash_w < profile.cash_floor:
        deficit = profile.cash_floor - cash_w
        cash_w = profile.cash_floor
        if w_risky.sum() > 0:
            w_risky = w_risky * max(0.0, (1 - cash_w) / w_risky.sum())
    target = {s: float(v) for s, v in w_risky.items() if v > 1e-6}
    target[CASH] = round(cash_w, 4)

    # normaliza e corrige o resíduo do arredondamento no caixa, para que os
    # pesos exibidos ao usuário somem exatamente 100%
    total_t = sum(target.values())
    if total_t > 1e-9:
        target = {k: v / total_t for k, v in target.items()}
    target = {k: round(v, 4) for k, v in target.items()}
    residuo = round(1.0 - sum(target.values()), 4)
    if abs(residuo) > 1e-9:
        target[CASH] = round(target.get(CASH, 0.0) + residuo, 4)

    # --- risco atual x recomendado ---
    ret_cols = [c for c in returns.columns]
    cur_vec = {c: float(current.get(c, 0.0)) for c in ret_cols}
    if current.get(CASH, 0.0) > 0 and CASH not in ret_cols:
        cur_vec[CASH] = float(current.get(CASH, 0.0))
    tgt_vec = {c: float(target.get(c, 0.0)) for c in ret_cols}
    tgt_vec[CASH] = float(target.get(CASH, 0.0))

    try:
        risk_current = rk.portfolio_risk(cur_vec, returns, cov, benchmark=bench,
                                         risk_free=settings.risk_free_rate)
    except ValueError:
        # sem histórico de carteira (usuário não informou posições)
        risk_current = rk.portfolio_risk(tgt_vec, returns, cov, benchmark=bench,
                                         risk_free=settings.risk_free_rate)
    risk_target = rk.portfolio_risk(tgt_vec, returns, cov, benchmark=bench,
                                    risk_free=settings.risk_free_rate)

    stress = rk.stress_test(tgt_vec, returns, cov)

    # --- hedge ---
    de_risk = "nenhum"
    if vol_pressure > 1.6 or drawdown_pressure > 0.8:
        de_risk = "severo"
    elif vol_pressure > 1.25 or drawdown_pressure > 0.5:
        de_risk = "moderado"
    elif vol_pressure > 1.05 or conv_label == "defensivo":
        de_risk = "leve"

    hedge = HedgePlan(
        cash_weight=round(cash_w, 4),
        cash_amount=round(cash_w * capital, 2),
        rationale=_hedge_rationale(de_risk, vol_pressure, profile, cash_w),
        triggers=[
            f"Volatilidade do mercado acima de {_fmt_pct(profile.max_vol, 0)} anualizados.",
            "BTC abaixo da média móvel de 200 dias com volume crescente.",
            f"Queda do patrimônio acima de {_fmt_pct(profile.max_drawdown * 0.5, 0)}.",
        ],
        de_risk_level=de_risk,
    )

    orders = build_orders(target, current, capital, profile)
    contributions = contribution_plan(target, current, portfolio.monthly_contribution, capital)
    alerts = build_alerts(forecasts, profile, risk_target, target, current, model, de_risk, vol_pressure)

    narrative = build_narrative(profile, equity, conviction, conv_label, target,
                                risk_target, risk_current, hedge, model, forecasts, contributions)

    diagnostics = {
        "fonte_dados": md.source,
        "ativo_referencia": bench,
        "volatilidade_referencia": round(bench_vol, 4),
        "pressao_volatilidade": round(vol_pressure, 3),
        "pressao_drawdown": round(drawdown_pressure, 3),
        "corte_volatilidade": round(vol_scale, 3),
        "conviccao_mercado": round(conviction, 3),
        "leitura_mercado": conv_label,
        "mistura_min_variancia": mv_blend,
        "habilidade_modelo": round(model.avg_skill, 4),
        "cobertura_intervalos": round(model.avg_coverage, 3),
        "dias_historico": int(len(md.close)),
        "ultima_atualizacao": md.last_date.strftime("%Y-%m-%d"),
        "avisos_dados": md.warnings,
    }

    return Advice(
        profile=profile.key,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        equity_exposure=round(equity, 4),
        target_weights={k: round(v, 4) for k, v in target.items()},
        current_weights={k: round(v, 4) for k, v in current.items()},
        benchmark_weights={s: round(float(v), 4) for s, v in rp_weights.items()},
        orders=orders,
        hedge=hedge,
        risk_current=risk_current.as_dict(),
        risk_target=risk_target.as_dict(),
        stress=stress,
        alerts=alerts,
        narrative=narrative,
        diagnostics=diagnostics,
        contributions=contributions,
    )


def _hedge_rationale(level: str, vol_pressure: float, profile: RiskProfile, cash_w: float) -> str:
    if level == "severo":
        return (f"Caixa alto ({cash_w:.0%}) porque a volatilidade está "
                f"{vol_pressure:.1f}x acima do alvo do seu perfil. A prioridade agora é "
                "proteger capital, não perseguir alta.")
    if level == "moderado":
        return (f"Caixa reforçado ({cash_w:.0%}): o mercado está mais volátil que o "
                "seu alvo, então o colchão absorve parte do impacto e serve de munição.")
    if level == "leve":
        return (f"Caixa de {cash_w:.0%} mantém a carteira dentro do orçamento de risco "
                "e permite aportar em quedas sem vender no pior momento.")
    return (f"Caixa de {cash_w:.0%}, o mínimo saudável para o perfil, deixa a carteira "
            "trabalhando sem perder a opção de recomprar em correções.")


def build_alerts(forecasts: dict[str, AssetForecast], profile: RiskProfile,
                 risk_target: rk.PortfolioRisk, target: dict[str, float],
                 current: dict[str, float], model: ModelCard,
                 de_risk: str, vol_pressure: float) -> list[Alert]:
    alerts: list[Alert] = []

    if model.avg_skill < -0.05:
        alerts.append(Alert(
            "info", "Modelo sem vantagem estatística agora",
            f"A habilidade fora da amostra está em {model.avg_skill:+.2f}. As previsões "
            "foram automaticamente desligadas e a carteira está sendo montada só com "
            "critérios de risco. Isso é intencional: é melhor não ter opinião do que "
            "ter uma opinião errada com tamanho grande."))
    if model.avg_coverage and model.avg_coverage < 0.82:
        alerts.append(Alert(
            "atencao", "Intervalos subestimando o risco",
            f"Os intervalos de 90% cobriram {model.avg_coverage:.0%} dos resultados "
            "reais na validação. Considere o risco reportado como um piso, não um teto."))

    if vol_pressure > 1.5:
        alerts.append(Alert(
            "atencao", "Volatilidade muito acima do seu alvo",
            f"A volatilidade do ativo de referência está {vol_pressure:.1f}x o alvo do "
            f"perfil ({profile.target_vol:.0%} a.a.). A exposição foi reduzida para "
            "compensar."))

    top = max(((s, w) for s, w in target.items() if s != CASH), key=lambda kv: kv[1], default=(None, 0))
    if top[0] and top[1] > profile.max_asset_weight * 0.95:
        alerts.append(Alert(
            "atencao", "Concentração no limite",
            f"{top[0]} atingiu {top[1]:.0%}, o teto do perfil. Se cair 50%, o impacto "
            f"no patrimônio será de {top[1] * 0.5:.0%}."))

    risky = sum(w for s, w in target.items() if s != CASH)
    worst = risk_target.max_drawdown
    if abs(worst) > profile.max_drawdown:
        alerts.append(Alert(
            "critico", "Queda histórica acima da sua tolerância",
            f"Esta alocação já teria caído {worst:.0%} no pior momento dos últimos "
            f"{profile.max_drawdown:.0%}. Reduza a exposição se isso te tiraria do "
            "sono — a disciplina importa mais que a carteira ideal."))

    for sym, f in forecasts.items():
        ind = f.indicators
        if ind.get("vol_zscore", 0) > 2.5:
            alerts.append(Alert("atencao", f"{sym}: volatilidade extrema",
                                f"Volatilidade 2,5 desvios acima do normal. "
                                f"Posição sugerida: {target.get(sym, 0):.0%}."))
        if ind.get("drawdown_atual", 0) < -0.6:
            alerts.append(Alert("info", f"{sym}: queda profunda",
                                f"{sym} está {abs(ind['drawdown_atual']) * 100:.0f}% abaixo do topo. "
                                "Aumentar posição aqui é uma aposta de recuperação, não um "
                                "investimento defensivo."))

    drift = sum(abs(target.get(s, 0) - current.get(s, 0)) for s in set(target) | set(current))
    if drift > 0.6:
        alerts.append(Alert(
            "atencao", "Rebalanceamento grande à vista",
            f"O ajuste total é de {drift:.0%} do patrimônio. Se houver custo de "
            "corretagem ou imposto relevante, execute em 2 a 3 etapas."))

    return alerts
