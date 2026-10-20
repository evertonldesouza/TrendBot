"""Relatórios: gráficos (PNG) e payload JSON para o painel web.

Os gráficos seguem a identidade visual escura do projeto e são pensados para
serem lidos por quem não é quant: cada figura responde uma pergunta.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from .assets import CASH
from .config import RiskProfile, Settings
from .data import MarketData
from .forecast import AssetForecast, ModelCard

logger = logging.getLogger(__name__)

BG = "#0b0e14"
SURFACE = "#151a23"
BORDER = "#2a313c"
TEXT = "#e6edf3"
MUTED = "#8b949e"
FAINT = "#4d5563"
BLUE = "#58a6ff"
GREEN = "#3fb950"
RED = "#f85149"
AMBER = "#e3b341"
PURPLE = "#a78bfa"
TEAL = "#2dd4bf"

PALETTE = [BLUE, PURPLE, TEAL, AMBER, GREEN, "#f778ba", "#79c0ff", "#d29922", RED, "#7ee787"]


def _apply_theme() -> None:
    plt.rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": SURFACE,
        "axes.edgecolor": BORDER, "axes.labelcolor": MUTED,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "grid.color": BORDER, "grid.linewidth": 0.6,
        "text.color": TEXT, "font.family": "DejaVu Sans", "font.size": 10,
        "legend.facecolor": SURFACE, "legend.edgecolor": BORDER,
    })


def _fmt_price(v: float) -> str:
    if abs(v) >= 1000:
        return f"${v:,.0f}"
    if abs(v) >= 10:
        return f"${v:,.2f}"
    if abs(v) >= 1:
        return f"${v:,.3f}"
    return f"${v:,.5f}"


def _fmt_pct(v: float, digits: int = 0) -> str:
    return f"{v * 100:.{digits}f}%"


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------

def plot_forecast_fan(prices: pd.DataFrame, forecast: AssetForecast,
                      horizon: int = 30, output: str = "forecast.png") -> str:
    """Preço histórico + leque de projeção quantílica para um ativo."""
    _apply_theme()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1],
                                   gridspec_kw={"hspace": 0.08})
    fig.patch.set_facecolor(BG)

    series = prices.dropna().tail(365)
    f = forecast.horizons.get(horizon)
    last_date = series.index[-1]
    last_price = float(series.iloc[-1])
    future_index = pd.date_range(last_date, periods=horizon + 1, freq="D")[1:]

    ax1.plot(series.index, series.to_numpy(), color=BLUE, lw=1.6, label="Preço (12 meses)")
    for w, alpha in ((50, 0.35), (200, 0.25)):
        s = series.rolling(w, min_periods=1).mean()
        ax1.plot(s.index, s.to_numpy(), color=AMBER, lw=0.9, alpha=alpha,
                 ls="--", label=f"MM{w}" if w == 50 else None)

    if f is not None:
        # leque: interpola os quantis do horizonte de forma linear (visual)
        qs = f.intervals
        levels = [(0.05, 0.95, 0.10), (0.10, 0.90, 0.14), (0.25, 0.75, 0.18)]
        for lo_q, hi_q, alpha in levels:
            lo = last_price * (1 + qs.get(f"p{int(lo_q * 100)}", f.lower))
            hi = last_price * (1 + qs.get(f"p{int(hi_q * 100)}", f.upper))
            lo_path = np.linspace(last_price, lo, horizon + 1)
            hi_path = np.linspace(last_price, hi, horizon + 1)
            ax1.fill_between(np.concatenate([[last_date], future_index]), lo_path, hi_path,
                             color=PURPLE, alpha=alpha, lw=0)
        med_path = np.linspace(last_price, last_price * (1 + f.median_return), horizon + 1)
        ax1.plot(np.concatenate([[last_date], future_index]), med_path,
                 color=PURPLE, lw=2, ls="--", label=f"Mediana ({horizon}d)")
        ax1.scatter([future_index[-1]], [med_path[-1]], color=PURPLE, s=60, zorder=5)
        ax1.annotate(f"{_fmt_price(med_path[-1])}\n{f.median_return:+.1%}",
                     xy=(future_index[-1], med_path[-1]), xytext=(8, 0),
                     textcoords="offset points", color=PURPLE, fontsize=9, fontweight="bold")

    ax1.set_title(f"{forecast.symbol} — histórico e projeção de {horizon} dias",
                  color=TEXT, fontsize=13, fontweight="bold", loc="left", pad=12)
    ax1.set_ylabel("Preço (USD)")
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: _fmt_price(x)))
    ax1.grid(alpha=0.25)
    ax1.legend(loc="upper left", fontsize=8, framealpha=0.5)
    ax1.tick_params(labelbottom=False)

    dd = series / series.cummax() - 1
    ax2.fill_between(dd.index, dd.to_numpy() * 100, 0, color=RED, alpha=0.35)
    ax2.plot(dd.index, dd.to_numpy() * 100, color=RED, lw=1)
    ax2.set_ylabel("Queda (%)")
    ax2.grid(alpha=0.2)

    fig.text(0.01, 0.01,
             f"TrendBot · faixas quantílicas do modelo (5–95%) · gerado em "
             f"{datetime.now().strftime('%d/%m/%Y %H:%M')} · não é recomendação de investimento",
             color=FAINT, fontsize=7)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return output


def plot_allocation(target: dict[str, float], current: dict[str, float],
                    output: str = "alocacao.png", title: str = "Alocação recomendada") -> str:
    """Dois anéis: carteira atual x carteira recomendada."""
    _apply_theme()
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    fig.patch.set_facecolor(BG)

    for ax, data, label in ((axes[0], current, "Carteira atual"),
                            (axes[1], target, "Recomendação TrendBot")):
        items = {k: v for k, v in data.items() if v > 0.001}
        if not items:
            items = {CASH: 1.0}
        keys = list(items.keys())
        vals = [items[k] for k in keys]
        colors = [PALETTE[i % len(PALETTE)] if k != CASH else FAINT
                  for i, k in enumerate(keys)]
        wedges, _ = ax.pie(vals, colors=colors, startangle=90,
                           wedgeprops=dict(width=0.42, edgecolor=BG, linewidth=2))
        ax.set_title(label, color=TEXT, fontsize=12, fontweight="bold", pad=10)
        ax.text(0, 0, f"{sum(vals):.0%}", ha="center", va="center",
                color=TEXT, fontsize=15, fontweight="bold")
        labels = [f"{k}  {v:.1%}" for k, v in zip(keys, vals)]
        ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
                  fontsize=9, frameon=False)

    fig.suptitle(title, color=TEXT, fontsize=14, fontweight="bold", y=1.0)
    fig.text(0.01, 0.01, "Caixa/USD aparece em cinza: é o colchão de risco, não uma posição.",
             color=FAINT, fontsize=7)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return output


def plot_risk_contributions(risk: dict, output: str = "risco.png") -> str:
    """Barras horizontais: quanto cada ativo contribui para o risco total."""
    _apply_theme()
    contrib = risk.get("risk_contributions", {})
    if not contrib:
        raise ValueError("Sem contribuições de risco para plotar.")
    items = sorted(contrib.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    values = [v * 100 for _, v in items]

    fig, ax = plt.subplots(figsize=(10, max(3, 0.55 * len(labels) + 2)))
    fig.patch.set_facecolor(BG)
    colors = [RED if v > 40 else (AMBER if v > 25 else BLUE) for v in values]
    ax.barh(labels, values, color=colors)
    for i, v in enumerate(values):
        ax.text(v + 0.6, i, f"{v:.1f}%", va="center", color=MUTED, fontsize=9)
    ax.set_xlabel("Contribuição para a volatilidade da carteira (%)")
    ax.set_title("Quem carrega o risco da carteira", color=TEXT,
                 fontsize=13, fontweight="bold", loc="left", pad=12)
    ax.grid(axis="x", alpha=0.2)
    ax.set_xlim(0, max(values + [10]) * 1.15)

    stats = (f"Volatilidade anualizada {risk.get('volatility', 0) * 100:.0f}%  ·  "
             f"VaR 95% (1 dia) {risk.get('var95', 0) * 100:.1f}%  ·  "
             f"pior queda {abs(risk.get('max_drawdown', 0)) * 100:.0f}%  ·  "
             f"Sharpe {risk.get('sharpe', 0):.2f}")
    fig.text(0.01, 0.01, stats, color=MUTED, fontsize=8)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return output


def plot_backtest(backtest: dict, output: str = "backtest.png") -> str:
    """Curvas de patrimônio comparando as estratégias."""
    _apply_theme()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1],
                                   gridspec_kw={"hspace": 0.12})
    fig.patch.set_facecolor(BG)

    for i, strat in enumerate(backtest["estrategias"]):
        curve = strat.get("equity_curve") or []
        if not curve:
            continue
        dates = pd.to_datetime([c["date"] for c in curve])
        values = [c["value"] for c in curve]
        is_tb = i == 0
        ax1.plot(dates, values, lw=2.4 if is_tb else 1.1,
                 color=PALETTE[i % len(PALETTE)], alpha=1.0 if is_tb else 0.75,
                 label=strat["name"], zorder=5 if is_tb else 2)

    ax1.set_yscale("log")
    ax1.set_title("Backtest: R$ 10.000 investidos (escala logarítmica)",
                  color=TEXT, fontsize=13, fontweight="bold", loc="left", pad=12)
    ax1.set_ylabel("Patrimônio (USD)")
    ax1.grid(alpha=0.25, which="both")
    ax1.legend(fontsize=8, loc="upper left", framealpha=0.6)
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: _fmt_price(x)))

    tb_curve = backtest["estrategias"][0].get("equity_curve") or []
    if tb_curve:
        s = pd.Series([c["value"] for c in tb_curve],
                      index=pd.to_datetime([c["date"] for c in tb_curve]))
        dd = (s / s.cummax() - 1) * 100
        ax2.fill_between(dd.index, dd.to_numpy(), 0, color=RED, alpha=0.4)
        ax2.plot(dd.index, dd.to_numpy(), color=RED, lw=1)
        ax2.set_ylabel("Queda da\ncarteria (%)")
    ax2.grid(alpha=0.2)

    fig.text(0.01, 0.01, backtest["resumo"].get("veredito", "")[:180],
             color=MUTED, fontsize=7.5, wrap=True)
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    fig.savefig(output, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return output


# ---------------------------------------------------------------------------
# Payload para o painel / API
# ---------------------------------------------------------------------------

def build_payload(md: MarketData, forecasts: dict[str, AssetForecast],
                  model: ModelCard, advice, backtest: dict | None,
                  settings: Settings, profile: RiskProfile) -> dict:
    """Monta o JSON único consumido pela API e pelo painel web."""
    prices = md.close
    series = []
    for sym in prices.columns:
        tail = prices[sym].dropna().tail(365)
        series.append({
            "symbol": sym,
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
            "prices": [round(float(v), 6) for v in tail.to_numpy()],
        })

    correlation = []
    if len(prices.columns) > 1:
        corr = prices.pct_change().dropna(how="any").tail(365).corr()
        correlation = [{"a": a, "b": b, "value": round(float(corr.loc[a, b]), 3)}
                       for a in corr.columns for b in corr.columns]

    return {
        "meta": {
            "versao": "2.0",
            "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fonte_dados": md.source,
            "ultimo_preco": md.last_date.strftime("%Y-%m-%d"),
            "dias_historico": int(len(prices)),
            "avisos": md.warnings,
            "universo": list(prices.columns),
            "benchmark": settings.benchmark,
            "perfil": {"chave": profile.key, "rotulo": profile.label,
                       "descricao": profile.description,
                       "vol_alvo": profile.target_vol, "vol_maxima": profile.max_vol,
                       "queda_maxima": profile.max_drawdown},
        },
        "modelo": model.as_dict(),
        "precos": series,
        "correlacao": correlation,
        "previsoes": {s: f.as_dict() for s, f in forecasts.items()},
        "recomendacao": advice.as_dict() if advice else None,
        "backtest": backtest,
    }


def write_json(payload: dict, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    logger.info("Payload gravado em %s", path)
    return path
