"""Servidor web do TrendBot (FastAPI).

Expõe a API de orientação e serve o painel. Toda a inteligência mora no
pacote ``trendbot`` — este arquivo só cuida de HTTP, cache e formatação.

Endpoints:
    GET  /                  -> painel (SPA)
    GET  /api/health        -> status da fonte de dados
    GET  /api/opcoes        -> ativos e perfis disponíveis
    GET  /api/relatorio     -> payload completo (com cache por parâmetros)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from trendbot import backtest as bt
from trendbot import report
from trendbot.advisor import build_advice
from trendbot.assets import CASH, known_assets, resolve_assets
from trendbot.config import PROFILES, PortfolioState, Settings, get_profile
from trendbot.data import build_market_data, describe_source
from trendbot.forecast import forecast_universe, HORIZONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("trendbot.web")
logging.getLogger("matplotlib").setLevel(logging.WARNING)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="TrendBot", version="2.0.0",
              description="Orientador quantitativo de investimentos em cripto.")

# cache simples em memória: o custo pesado é a simulação/previsão, não o HTTP
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------

class CarteiraInput(BaseModel):
    capital: float = Field(default=10_000.0, ge=0)
    aporte_mensal: float = Field(default=0.0, ge=0)
    posicoes: dict[str, float] = Field(default_factory=dict)
    caixa: float = Field(default=0.0, ge=0)


class RelatorioRequest(BaseModel):
    perfil: str = "moderado"
    ativos: list[str] | None = None
    dias: int = 1095
    fonte: str = "auto"
    horizonte: int = 30
    carteira: CarteiraInput = Field(default_factory=CarteiraInput)
    backtest: bool = True


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _montar_relatorio(req: RelatorioRequest) -> dict:
    settings = Settings.from_env(days=req.dias, source=req.fonte)
    if req.ativos:
        settings.assets = resolve_assets(req.ativos)

    profile = get_profile(req.perfil)
    posicoes = {k.upper(): float(v) for k, v in (req.carteira.posicoes or {}).items() if v}
    caixa = float(req.carteira.caixa or 0.0)
    if not posicoes and caixa <= 0:
        caixa = float(req.carteira.capital or 10_000.0)

    portfolio = PortfolioState(
        capital=max(float(req.carteira.capital), sum(posicoes.values()) + caixa),
        monthly_contribution=float(req.carteira.aporte_mensal),
        holdings=posicoes,
        cash=caixa,
    )

    md = build_market_data(
        settings.assets, days=settings.days, source=settings.source,
        cache_dir=settings.cache_dir, data_dir=settings.data_dir,
        seed=settings.seed, allow_stale=settings.allow_stale_cache,
    )
    forecasts, model = forecast_universe(md, horizons=HORIZONS)
    advice = build_advice(md, forecasts, model, profile, portfolio, settings)

    backtest_payload = None
    if req.backtest and len(md.close) >= 420:
        try:
            backtest_payload = bt.run_backtest(
                md.close, profile, initial=10_000.0, rebalance_freq=30,
                benchmark=settings.benchmark,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Backtest não executado: %s", exc)

    payload = report.build_payload(md, forecasts, model, advice, backtest_payload,
                                   settings, profile)
    payload["meta"]["fonte_legivel"] = describe_source(md)
    return payload


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "versao": app.version, "cache_itens": len(_CACHE)}


@app.get("/api/opcoes")
def opcoes() -> dict:
    return {
        "ativos": [{"key": a.key, "symbol": a.symbol, "nome": a.name,
                    "categoria": a.category} for a in known_assets()],
        "perfis": [{"chave": p.key, "rotulo": p.label, "descricao": p.description,
                    "vol_alvo": p.target_vol, "vol_maxima": p.max_vol,
                    "queda_maxima": p.max_drawdown,
                    "faixa_exposicao": list(p.equity_band)}
                   for p in PROFILES.values()],
        "fontes": ["auto", "coingecko", "binance", "synthetic", "csv"],
        "caixa": CASH,
    }


@app.get("/api/relatorio")
def relatorio_get(
    perfil: str = Query("moderado"),
    ativos: str = Query(""),
    dias: int = Query(1095),
    fonte: str = Query("auto"),
    capital: float = Query(10_000.0),
    aporte: float = Query(0.0),
    carteira: str = Query(""),
    backtest: bool = Query(True),
) -> JSONResponse:
    posicoes: dict[str, float] = {}
    caixa = 0.0
    if carteira:
        for chunk in carteira.split(","):
            if ":" not in chunk:
                continue
            sym, value = chunk.split(":", 1)
            try:
                val = float(value)
            except ValueError:
                continue
            if sym.strip().upper() == CASH:
                caixa = val
            else:
                posicoes[sym.strip().upper()] = val
    req = RelatorioRequest(
        perfil=perfil,
        ativos=[a for a in ativos.split(",") if a.strip()] or None,
        dias=dias, fonte=fonte, backtest=backtest,
        carteira=CarteiraInput(capital=capital, aporte_mensal=aporte,
                               posicoes=posicoes, caixa=caixa),
    )
    return relatorio_post(req)


@app.post("/api/relatorio")
def relatorio_post(req: RelatorioRequest) -> JSONResponse:
    started = time.time()
    chave = hashlib.md5(json.dumps(req.model_dump(), sort_keys=True, default=str)
                        .encode()).hexdigest()
    agora = time.time()
    if chave in _CACHE and agora - _CACHE[chave][0] < CACHE_TTL:
        payload = _CACHE[chave][1]
        payload = dict(payload)
        payload["cache"] = {"hit": True, "idade_s": round(agora - _CACHE[chave][0], 1)}
        return JSONResponse(payload)

    try:
        payload = _montar_relatorio(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao gerar relatório")
        raise HTTPException(status_code=500, detail=f"Falha ao gerar relatório: {exc}") from exc

    payload["cache"] = {"hit": False, "idade_s": 0.0}
    payload["meta"]["tempo_processamento_s"] = round(time.time() - started, 2)
    _CACHE[chave] = (agora, payload)
    if len(_CACHE) > 24:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: len(_CACHE) - 24]:
            _CACHE.pop(k, None)
    return JSONResponse(payload)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# estáticos em /static (o painel referencia /static/app.js e /static/styles.css)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
