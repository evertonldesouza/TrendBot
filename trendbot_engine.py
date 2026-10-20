"""Compatibilidade com o pipeline legado do TrendBot (v1).

Este arquivo era o motor principal do projeto. Ele foi substituído pelo pacote
``trendbot`` (``python -m trendbot.cli``), mas continua existindo para que:

* o GitHub Actions diário (``.github/workflows/daily_report.yml``) siga
  funcionando sem mudança de segredos/variáveis;
* o dashboard estático em ``docs/`` (GitHub Pages) continue recebendo
  ``data.json`` e ``historico.json`` no formato que ele já lê;
* o histórico de acertos — a validação mais honesta do projeto — continue
  sendo alimentado e conferido dia após dia.

Ele roda o motor novo e apenas "traduz" o resultado para o formato antigo.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from trendbot.assets import CASH
from trendbot.config import PortfolioState, Settings, get_profile
from trendbot.data import build_market_data
from trendbot.forecast import forecast_universe, HORIZONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DOCS = "docs"
HOJE = datetime.now().strftime("%d/%m/%Y")


def carregar_historico(caminho: str = "docs/historico.json") -> list[dict]:
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("histórico ilegível (%s): recomeçando", exc)
    return []


def salvar_historico(historico: list[dict], caminho: str = "docs/historico.json") -> None:
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=4)
    logger.info("historico.json atualizado (%d entradas)", len(historico))


def _status_legado(variacao: float) -> tuple[str, str]:
    if variacao > 1.0:
        return "COMPRA FORTE", "🚀"
    if variacao > 0.0:
        return "ALTA LEVE", "⬆️"
    if variacao < -1.0:
        return "VENDA", "🚨"
    return "NEUTRO", "⚖️"


def _resolver_pendencias(historico: list[dict], precos) -> int:
    """Fecha previsões passadas comparando com o preço realizado.

    Critério de acerto (inalterado desde a v1): o preço real caiu dentro do
    intervalo de 90%. Não é "acertar o preço" — é o intervalo ser honesto.
    """
    resolvidas = 0
    for entrada in historico:
        if entrada.get("preco_real") is not None:
            continue
        simbolo = entrada.get("moeda")
        if simbolo not in getattr(precos, "columns", []):
            continue
        try:
            data = datetime.strptime(entrada["data"], "%d/%m/%Y")
        except (KeyError, ValueError):
            continue
        if datetime.now() - data < timedelta(days=1):
            continue
        preco_real = float(precos[simbolo].iloc[-1])
        entrada["preco_real"] = round(preco_real, 2)
        entrada["erro"] = round(preco_real - float(entrada["previsao"]), 2)
        entrada["acerto"] = "✅" if (
            float(entrada["confianca_min"]) <= preco_real <= float(entrada["confianca_max"])
        ) else "❌"
        resolvidas += 1
    return resolvidas


def fluxo_principal() -> None:
    logger.info("--- INICIANDO CICLO TRENDBOT (compat v1) ---")
    settings = Settings.from_env(days=int(os.getenv("DIAS_HISTORICO", "1095")))
    profile = get_profile(os.getenv("PERFIL_RISCO"))
    md = build_market_data(
        settings.assets, days=settings.days, source=settings.source,
        cache_dir=settings.cache_dir, data_dir=settings.data_dir, seed=settings.seed,
    )
    if md.close.empty:
        logger.error("Sem dados disponíveis. Encerrando.")
        return

    forecasts, card = forecast_universe(md, horizons=HORIZONS)
    logger.info("Habilidade fora da amostra: %+.3f | cobertura: %.0f%%",
                card.avg_skill, card.avg_coverage * 100)

    historico = carregar_historico()
    resolvidas = _resolver_pendencias(historico, md.close)
    if resolvidas:
        logger.info("%d previsões conferidas com o preço realizado", resolvidas)

    dados_json: list[dict] = []
    for simbolo, fc in forecasts.items():
        preco = fc.price
        h1 = fc.horizons[1]
        previsao = preco * (1 + h1.median_return)
        conf_min = preco * (1 + h1.lower)
        conf_max = preco * (1 + h1.upper)
        variacao = ((previsao - preco) / preco) * 100
        status, emoji = _status_legado(variacao)

        dados_json.append({
            "moeda": simbolo,
            "preco": f"{preco:,.2f}",
            "previsao": f"{previsao:,.2f}",
            "confianca_min": f"{conf_min:,.2f}",
            "confianca_max": f"{conf_max:,.2f}",
            "variacao": f"{variacao:+.2f}",
            "status": status,
            "emoji": emoji,
            "imagem": f"alerta_{simbolo.lower()}.png",
            "conviccao": round(fc.conviction, 3),
            "regime": fc.regime,
            "peso_modelo": round(fc.model_weight, 2),
        })

        if not any(e.get("data") == HOJE and e.get("moeda") == simbolo for e in historico):
            historico.append({
                "data": HOJE,
                "moeda": simbolo,
                "previsao": round(previsao, 2),
                "confianca_min": round(conf_min, 2),
                "confianca_max": round(conf_max, 2),
                "preco_real": None,
                "erro": None,
                "acerto": None,
            })

    if not dados_json:
        logger.error("Nenhuma previsão gerada. Nada a publicar.")
        return

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump({
            "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "modelo": card.as_dict(),
            "ativos": dados_json,
        }, f, ensure_ascii=False, indent=4)
    logger.info("docs/data.json atualizado (%d ativos)", len(dados_json))

    salvar_historico(historico[-400:])

    # gráficos legados (mesmos nomes de arquivo que o dashboard antigo usa)
    try:
        from trendbot import report
        for simbolo, fc in forecasts.items():
            report.plot_forecast_fan(
                md.close[simbolo].dropna(), fc, horizon=30,
                output=os.path.join(DOCS, f"alerta_{simbolo.lower()}.png"))
        advise = None
        try:
            from trendbot.advisor import build_advice
            carteira = PortfolioState(capital=float(os.getenv("CAPITAL_INICIAL", "10000")),
                                      cash=float(os.getenv("CAPITAL_INICIAL", "10000")))
            advise = build_advice(md, forecasts, card, profile, carteira, settings)
            report.plot_allocation(advise.target_weights, advise.current_weights,
                                   os.path.join(DOCS, "alocacao.png"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não foi possível gerar gráfico de alocação: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao gerar gráficos: %s", exc)

    with open(os.path.join(DOCS, "relatorio_completo.json"), "w", encoding="utf-8") as f:
        json.dump({
            "meta": {"gerado_em": datetime.now().isoformat(timespec="seconds"),
                     "fonte": md.source, "perfil": profile.key},
            "modelo": card.as_dict(),
            "previsoes": {s: fc.as_dict() for s, fc in forecasts.items()},
            "recomendacao": advise.as_dict() if advise else None,
        }, f, ensure_ascii=False, indent=2, default=str)

    logger.info("Ciclo concluído.")


if __name__ == "__main__":
    fluxo_principal()
