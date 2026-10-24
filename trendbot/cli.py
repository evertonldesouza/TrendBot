"""Interface de linha de comando do TrendBot.

Uso típico::

    python -m trendbot.cli --perfil moderado --capital 25000 --aporte 1000

Gera em ``out/``: ``relatorio.json`` (payload completo) e os gráficos
``alocacao.png``, ``risco.png``, ``backtest.png`` e ``projecao_<ATIVO>.png``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Sequence

import pandas as pd

from . import backtest as bt
from . import report
from .advisor import build_advice
from .config import PROFILES, PortfolioState, Settings, get_profile, parse_carteira
from .data import build_market_data, describe_source
from .forecast import forecast_universe, HORIZONS

logger = logging.getLogger(__name__)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="trendbot",
        description="TrendBot — orientador quantitativo de investimentos em cripto.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemplo:\n  python -m trendbot.cli --perfil moderado --capital 25000 --aporte 1000\n",
    )
    p.add_argument("--perfil", choices=sorted(PROFILES), default=None,
                   help="Perfil de risco (padrão: PERFIL_RISCO ou 'moderado').")
    p.add_argument("--capital", type=float, default=None, help="Patrimônio atual em USD.")
    p.add_argument("--aporte", type=float, default=None, help="Aporte mensal em USD.")
    p.add_argument("--ativos", default=None,
                   help="Lista de ativos (ex.: bitcoin,ethereum,solana).")
    p.add_argument("--dias", type=int, default=None, help="Dias de histórico (padrão 1095).")
    p.add_argument("--fonte", default=None,
                   choices=["auto", "coingecko", "binance", "synthetic", "csv"],
                   help="Fonte de dados (padrão: auto).")
    p.add_argument("--carteira", default=None,
                   help="Carteira atual no formato BTC:12000,ETH:5000,USD:5000")
    p.add_argument("--out", default=None, help="Diretório de saída (padrão: out).")
    p.add_argument("--sem-backtest", action="store_true", help="Não roda o backtest.")
    p.add_argument("--sem-graficos", action="store_true", help="Não gera PNGs.")
    p.add_argument("--json", dest="json_only", action="store_true",
                   help="Só grava o JSON, sem resumo no terminal.")
    p.add_argument("-v", "--verbose", action="store_true", help="Log detalhado.")
    return p.parse_args(argv)


LABELS_FONTE = {
    "coingecko": "CoinGecko (tempo real)",
    "binance": "Binance (tempo real)",
    "csv": "arquivo local data/prices.csv",
    "synthetic": "simulação determinística (demo)",
}


def describe_source_name(src: str) -> str:
    return LABELS_FONTE.get(src, src)


def _print_summary(payload: dict) -> None:
    rec = payload["recomendacao"]
    meta = payload["meta"]
    line = "─" * 78

    print()
    print(line)
    print(f"  TRENDBOT · ORIENTADOR DE INVESTIMENTOS  ·  perfil {meta['perfil']['rotulo']}")
    print(f"  dados: {describe_source_name(meta['fonte_dados'])}  ·  último pregão {meta['ultimo_preco']}  ·  "
          f"{meta['dias_historico']} dias de histórico")
    print(line)

    print(f"\n  {rec['narrative']['headline']}\n")

    print("  ALOCAÇÃO RECOMENDADA")
    cur = rec["current_weights"]
    for sym, w in sorted(rec["target_weights"].items(), key=lambda kv: -kv[1]):
        c = cur.get(sym, 0.0)
        arrow = "" if abs(w - c) < 0.005 else ("  ↑" if w > c else "  ↓")
        bar = "█" * int(round(w * 40))
        print(f"    {sym:6s} {w * 100:5.1f}%  (hoje {c * 100:5.1f}%){arrow:3s} {bar}")

    print("\n  ORDENS")
    for o in rec["orders"]:
        if o["action"] == "MANTER" and abs(o["delta_weight"]) < 0.01:
            continue
        print(f"    [{o['priority']}] {o['action']:14s} {o['symbol']:6s} "
              f"{o['amount']:+12,.2f} USD   {o['reason']}")

    rt = rec["risk_target"]
    print("\n  RISCO DA CARTEIRA RECOMENDADA")
    print(f"    Volatilidade anualizada : {rt['volatility'] * 100:5.1f}%   "
          f"(alvo do perfil {meta['perfil']['vol_alvo'] * 100:.0f}%)")
    print(f"    VaR 95% (1 dia)         : {rt['var95'] * 100:5.2f}%")
    print(f"    CVaR 95% (1 dia)        : {rt['cvar95'] * 100:5.2f}%")
    print(f"    Pior queda no histórico : {abs(rt['max_drawdown']) * 100:5.1f}%")
    print(f"    Sharpe                  : {rt['sharpe']:5.2f}")

    print("\n  CENÁRIOS DE ESTRESSE")
    for s in rec["stress"]:
        print(f"    {s['label'][:52]:54s} {s['impacto_base'] * 100:+6.1f}%")

    if rec["alerts"]:
        print("\n  ALERTAS")
        for a in rec["alerts"]:
            print(f"    [{a['level'].upper():8s}] {a['title']}: {a['message']}")

    print("\n  MODELO (honestidade)")
    print(f"    {rec['narrative']['veredito_modelo']}")
    for n in rec["narrative"]["notas_modelo"]:
        print(f"      · {n}")

    b = payload.get("backtest")
    if b:
        print("\n  BACKTEST (US$ 10.000 no início do período)")
        for s in b["estrategias"]:
            print(f"    {s['name']:26s} {s['final_value']:10,.0f}  "
                  f"CAGR {s['cagr'] * 100:+6.1f}%  vol {s['volatility'] * 100:3.0f}%  "
                  f"Sharpe {s['sharpe']:+.2f}  queda {s['max_drawdown'] * 100:6.1f}%")
        print(f"\n    {b['resumo']['veredito']}")

    print()
    print(line)
    print("  Este relatório é informativo e não constitui recomendação de investimento.")
    print(line)
    print()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)

    started = time.time()
    settings = Settings.from_env(
        days=args.dias or 1095,
        source=args.fonte,
        output_dir=args.out,
    )
    if args.ativos:
        from .assets import resolve_assets
        settings.assets = resolve_assets([a.strip() for a in args.ativos.split(",") if a.strip()])

    profile = get_profile(args.perfil)
    holdings, caixa = parse_carteira(args.carteira)
    capital = args.capital if args.capital is not None else float(
        os.getenv("CAPITAL_INICIAL", "10000"))
    monthly = args.aporte if args.aporte is not None else float(
        os.getenv("APORTE_MENSAL", "0"))

    if holdings or caixa > 0:
        cash = caixa
        invested = sum(holdings.values())
    else:
        invested, cash = 0.0, capital
    portfolio = PortfolioState(
        capital=max(capital, invested + cash),
        monthly_contribution=monthly,
        holdings=holdings,
        cash=cash,
    )

    logger.info("Carregando dados de %d ativos (%s)...", len(settings.assets), settings.source)
    md = build_market_data(
        settings.assets, days=settings.days, source=settings.source,
        cache_dir=settings.cache_dir, data_dir=settings.data_dir,
        seed=settings.seed, allow_stale=settings.allow_stale_cache,
    )
    logger.info("Fonte utilizada: %s (%d dias)", describe_source(md), len(md.close))

    logger.info("Gerando previsões com validação walk-forward...")
    forecasts, model = forecast_universe(md, horizons=HORIZONS)
    logger.info("Habilidade média fora da amostra: %+.3f | cobertura: %.0f%%",
                model.avg_skill, model.avg_coverage * 100)

    logger.info("Montando recomendação para o perfil %s...", profile.label)
    advice = build_advice(md, forecasts, model, profile, portfolio, settings)

    backtest_payload = None
    if not args.sem_backtest and len(md.close) >= 420:
        logger.info("Rodando backtest comparativo...")
        try:
            backtest_payload = bt.run_backtest(
                md.close, profile, initial=10_000.0, rebalance_freq=30,
                benchmark=settings.benchmark)
        except Exception as exc:  # noqa: BLE001 - backtest não deve derrubar o relatório
            logger.warning("Backtest não executado: %s", exc)

    payload = report.build_payload(md, forecasts, model, advice, backtest_payload,
                                   settings, profile)

    out_dir = settings.output_dir
    os.makedirs(out_dir, exist_ok=True)
    json_path = report.write_json(payload, os.path.join(out_dir, "relatorio.json"))

    if not args.sem_graficos:
        try:
            report.plot_allocation(advice.target_weights, advice.current_weights,
                                   os.path.join(out_dir, "alocacao.png"))
            report.plot_risk_contributions(advice.risk_target,
                                           os.path.join(out_dir, "risco.png"))
            if backtest_payload:
                report.plot_backtest(backtest_payload,
                                     os.path.join(out_dir, "backtest.png"))
            for sym, fc in forecasts.items():
                report.plot_forecast_fan(md.close[sym].dropna(), fc, horizon=30,
                                         output=os.path.join(out_dir, f"projecao_{sym}.png"))
        except Exception as exc:  # noqa: BLE001 - gráfico é acessório
            logger.warning("Falha ao gerar gráficos: %s", exc)

    if not args.json_only:
        _print_summary(payload)
    print(f"Relatório gravado em {json_path}  ({time.time() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
