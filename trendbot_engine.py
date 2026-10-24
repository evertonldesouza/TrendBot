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

from trendbot.assets import CASH, moeda_canonica
from trendbot.config import (PortfolioState, Settings, get_profile,
                            parse_carteira)
from trendbot.data import build_market_data, describe_source, ultimos_erros_rede
from trendbot.forecast import forecast_universe, HORIZONS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DOCS = "docs"
HOJE = datetime.now().strftime("%d/%m/%Y")


# Quantas previsões o histórico guarda. Com 4 ativos por dia dá ~100 dias, o
# que é mais que suficiente para a calibração dos intervalos (ela quer ~200
# pontos resolvidos). Não é o mesmo que a janela do backtest: aquele usa dados
# de mercado (3,5 anos), este é o histórico de acertos divulgado — coisas
# diferentes, e o README diz isso para ninguém ler um como se fosse o outro.
# Cada entrada tem ~250 bytes, então subir muito aqui vira peso diário no git.
LIMITE_HISTORICO = 400

# Quantos dias de histórico vão para o gráfico do painel (texto, no data.json)
DIAS_GRAFICO = 365

ALVO_COBERTURA = 0.90
MINIMO_AMOSTRA_CALIBRACAO = 40
AMOSTRAS_PARA_CONFIANCA_TOTAL = 200
LIMITES_CALIBRACAO = (0.80, 1.05)


def _quantile(ordenados: list[float], q: float) -> float:
    """Quantil por interpolação linear, sem depender de numpy aqui."""
    if not ordenados:
        return 0.0
    if len(ordenados) == 1:
        return ordenados[0]
    pos = q * (len(ordenados) - 1)
    baixo = int(pos)
    alto = min(baixo + 1, len(ordenados) - 1)
    frac = pos - baixo
    return ordenados[baixo] * (1 - frac) + ordenados[alto] * frac


def fator_calibracao(historico: list[dict]) -> tuple[float, int]:
    """Encolhe o intervalo para que a cobertura realize o alvo de 90%.

    O intervalo publicado é o q05–q95 da distribuição dos resíduos, então
    deveria conter 90% dos preços realizados. Na prática continha 96%: a banda
    era larga demais, e um intervalo que sempre acerta é um intervalo que não
    diz nada.

    O erro é medido em unidades da própria banda (z = erro / meia-largura), o
    que permite juntar moedas e épocas de volatilidade diferente numa única
    amostra. O fator é o quantil 90% de |z|.

    Cada entrada guarda o fator que estava em vigor quando foi gerada, e aqui
    o erro é desfeito antes de medir (z_bruto = z_medido * fator_da_entrada).
    Sem isso o ajuste não converge: o fator novo seria calculado sobre uma
    banda já encolhida, e o ponto fixo pararia em ~93% em vez de 90%.

    Duas proteções, porque com amostra pequena um quantil extremo é ruído:
      - o peso do fator cresce com o tamanho da amostra (com 40 pontos quase
        não mexe, com 200 aplica inteiro);
      - limites duros em 0,80 e 1,05. O piso importa: simulando a estimativa
        ao longo de meses, o quantil oscila e chegava a 0,75 em alguns ciclos,
        o que deixaria a banda estreita demais (cobertura cairia a ~86%). Em
        0,80 o pior caso fica em ~89%: errar para o lado conservador aqui custa
        menos do que um intervalo que não cobre o que promete.
    """
    z: list[float] = []
    for e in historico:
        if e.get("acerto") is None:
            continue
        try:
            previsao = float(e["previsao"])
            minimo = float(e["confianca_min"])
            maximo = float(e["confianca_max"])
            real = float(e["preco_real"])
        except (TypeError, ValueError, KeyError):
            continue
        meia = (maximo - minimo) / 2.0
        if meia <= 0:
            continue
        # entradas anteriores à calibração não têm o campo: foram geradas com 1.0
        try:
            aplicado = float(e.get("calibracao", 1.0) or 1.0)
        except (TypeError, ValueError):
            aplicado = 1.0
        if aplicado <= 0:
            aplicado = 1.0
        z.append(abs((real - previsao) / meia) * aplicado)

    if len(z) < MINIMO_AMOSTRA_CALIBRACAO:
        return 1.0, len(z)

    z.sort()
    bruto = _quantile(z, ALVO_COBERTURA)
    peso = min(1.0, len(z) / AMOSTRAS_PARA_CONFIANCA_TOTAL)
    fator = 1.0 + (bruto - 1.0) * peso
    piso, teto = LIMITES_CALIBRACAO
    return max(piso, min(teto, fator)), len(z)


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


def _mapa_de_precos_por_dia(precos) -> dict[str, dict]:
    """symbol -> {data: preço de fechamento}, para conferir cada previsão
    no dia em que ela vence, e não "no último dia que tiver"."""
    import pandas as pd

    mapa: dict[str, dict] = {}
    for coluna in getattr(precos, "columns", []):
        simbolo = moeda_canonica(str(coluna))
        if not simbolo:
            continue
        serie = precos[coluna].dropna()
        dias = {pd.Timestamp(i).date(): float(v) for i, v in serie.items()}
        # setdefault: se duas colunas canonizarem para o mesmo símbolo, as
        # datas se somam em vez de uma coluna engolir a outra.
        mapa.setdefault(simbolo, {}).update(dias)
    return mapa


def _projecao_para_grafico(f30, fator: float) -> dict | None:
    """Leque quantílico de 30 dias pronto para o painel desenhar.

    Os quantis saem do modelo; aqui só recebem a MESMA contração aplicada à
    banda publicada de 1 dia. Se o painel desenhasse o leque cru ao lado de
    uma banda calibrada, os dois números não bateriam.
    """
    if f30 is None:
        return None
    mediana = float(f30.median_return)
    quantis = {}
    for nome in ("p5", "p10", "p25", "p75", "p90", "p95"):
        bruto = float(f30.intervals.get(nome, 0.0))
        quantis[nome] = round(mediana + (bruto - mediana) * fator, 5)
    return {"horizonte": 30, "mediana": round(mediana, 5), "quantis": quantis}


def _resolver_pendencias(historico: list[dict], precos) -> int:
    """Fecha previsões passadas comparando com o preço realizado.

    Critério de acerto (inalterado desde a v1): o preço real caiu dentro do
    intervalo de 90%. Não é "acertar o preço" — é o intervalo ser honesto.

    A previsão é para o dia seguinte, então é o fechamento de D+1 que vale.
    A versão anterior usava o ÚLTIMO preço da série, o que funcionava só
    enquanto o job rodava todo dia: se um dia falhasse, a previsão de 20/10
    era conferida contra o preço de 22/10 — e virava acerto ou erro por
    acidente. Quando o D+1 não está na série, a entrada fica pendente: é
    melhor não saber do que saber errado.
    """
    mapa = _mapa_de_precos_por_dia(precos)
    resolvidas = 0
    for entrada in historico:
        if entrada.get("preco_real") is not None:
            continue
        # O histórico da v1 guardava o nome ("CARDANO"), as colunas de preço
        # usam o símbolo ("ADA"). Sem canonizar aqui, a busca falhava sempre e
        # essas entradas ficavam pendentes para nunca mais sair.
        simbolo = moeda_canonica(entrada.get("moeda") or "")
        if simbolo not in mapa:
            continue
        try:
            data = datetime.strptime(entrada["data"], "%d/%m/%Y")
        except (KeyError, ValueError):
            continue

        preco_real = mapa[simbolo].get((data + timedelta(days=1)).date())
        if preco_real is None:
            continue

        entrada["preco_real"] = round(preco_real, 2)
        entrada["erro"] = round(preco_real - float(entrada["previsao"]), 2)
        entrada["acerto"] = "✅" if (
            float(entrada["confianca_min"]) <= preco_real <= float(entrada["confianca_max"])
        ) else "❌"
        resolvidas += 1
    return resolvidas


def fluxo_principal() -> None:
    logger.info("--- INICIANDO CICLO TRENDBOT (compat v1) ---")
    # O job diário roda uma vez por dia e não tem pressa: vale insistir nos
    # endpoints públicos. Com uma tentativa só, um 429 da CoinGecko derrubava
    # o relatório para a simulação, que era publicada sem aviso no dashboard.
    settings = Settings.from_env(
        days=int(os.getenv("DIAS_HISTORICO", "1095")),
        network_tries=max(1, int(os.getenv("TENTATIVAS_REDE", "4"))),
    )
    profile = get_profile(os.getenv("PERFIL_RISCO"))
    md = build_market_data(
        settings.assets, days=settings.days, source=settings.source,
        cache_dir=settings.cache_dir, data_dir=settings.data_dir, seed=settings.seed,
        network_tries=settings.network_tries,
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

    fator, amostra = fator_calibracao(historico)
    if fator != 1.0:
        logger.info(
            "Calibração dos intervalos: fator %.3f estimado com %d pontos "
            "resolvidos (alvo de cobertura %.0f%%).", fator, amostra,
            ALVO_COBERTURA * 100,
        )
    else:
        logger.info(
            "Calibração dos intervalos: sem ajuste (%d pontos resolvidos, "
            "mínimo é %d).", amostra, MINIMO_AMOSTRA_CALIBRACAO,
        )

    dados_json: list[dict] = []
    graficos: dict[str, dict] = {}
    for simbolo, fc in forecasts.items():
        preco = fc.price
        h1 = fc.horizons[1]
        previsao = preco * (1 + h1.median_return)
        conf_min = preco * (1 + h1.lower)
        conf_max = preco * (1 + h1.upper)

        # encolhe os dois lados em direção à mediana, mantendo a assimetria
        conf_min = previsao - (previsao - conf_min) * fator
        conf_max = previsao + (conf_max - previsao) * fator
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
            "grafico": simbolo,
            "conviccao": round(fc.conviction, 3),
            "regime": fc.regime,
            "peso_modelo": round(fc.model_weight, 2),
        })

        # Série e leque vão como TEXTO no data.json de propósito. Os PNGs
        # diários (4 x ~150 KB) eram 98,6% do repositório — 126 MB em 77 dias
        # — porque binário novo todo dia não tem delta para comprimir. Texto
        # tem, e o painel desenha o gráfico em SVG.
        serie = md.close[simbolo].dropna().tail(DIAS_GRAFICO)
        f30 = fc.horizons.get(30)
        graficos[simbolo] = {
            "datas": [d.strftime("%Y-%m-%d") for d in serie.index],
            "fechamento": [round(float(v), 2) for v in serie.to_numpy()],
            "projecao": _projecao_para_grafico(f30, fator),
        }

        # Previsão gerada a partir de DADOS SIMULADOS não entra no histórico.
        # Ela seria conferida contra o preço real no dia seguinte e entraria
        # nas estatísticas de acerto como se fosse uma previsão de verdade —
        # foi exatamente o que aconteceu: há entradas de 20/10/2026 com os
        # valores-âncora do simulador convivendo com entradas reais.
        if md.source == "synthetic":
            logger.warning(
                "Fonte simulada (%s): previsão de %s NÃO será registrada no "
                "histórico de acertos, para não contaminar as estatísticas.",
                md.source, simbolo,
            )
        elif not any(
            e.get("data") == HOJE and moeda_canonica(e.get("moeda")) == moeda_canonica(simbolo)
            for e in historico
        ):
            historico.append({
                "data": HOJE,
                "moeda": simbolo,
                "previsao": round(previsao, 2),
                "confianca_min": round(conf_min, 2),
                "confianca_max": round(conf_max, 2),
                "preco_real": None,
                "erro": None,
                "acerto": None,
                "fonte": md.source,
                "calibracao": round(fator, 4),
            })

    if not dados_json:
        logger.error("Nenhuma previsão gerada. Nada a publicar.")
        return

    os.makedirs(DOCS, exist_ok=True)
    simulado = md.source == "synthetic"
    # Se não conseguiu dados de mercado, declara o motivo: um fallback para
    # simulação que não diz por quê é indistinguível de um relatório real.
    detalhes = ultimos_erros_rede() if simulado else []
    fonte = {
        "detalhes": detalhes,
        "id": md.source,
        "nome": describe_source(md),
        "simulada": simulado,
        "aviso": (
            "ATENÇÃO: os dados abaixo são de uma SIMULAÇÃO determinística, não de "
            "mercado real. As APIs públicas não responderam nesta execução."
            if simulado else
            "Preços de mercado obtidos de fonte pública. Projeções são estimativas, "
            "não garantia."
        ),
    }
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump({
            "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "fonte": fonte,
            "modelo": card.as_dict(),
            "calibracao": {
                "alvo_cobertura": ALVO_COBERTURA,
                "fator": round(fator, 4),
                "amostra": amostra,
                "minimo_amostra": MINIMO_AMOSTRA_CALIBRACAO,
                "ajustado": fator != 1.0,
            },
            "ativos": dados_json,
            "graficos": graficos,
        }, f, ensure_ascii=False, indent=4)
    logger.info("docs/data.json atualizado (%d ativos) | fonte: %s",
                len(dados_json), fonte["nome"])
    if simulado:
        logger.warning("DADOS SIMULADOS publicados em docs/data.json — "
                       "as APIs públicas falharam. O dashboard exibe o aviso.")
        for motivo in detalhes:
            logger.warning("  motivo: %s", motivo)

    if len(historico) > LIMITE_HISTORICO:
        descartadas = len(historico) - LIMITE_HISTORICO
        logger.warning(
            "Histórico cheio (%d entradas, teto de %d): %d previsões antigas "
            "deixarão de constar. A estatística de acerto passa a cobrir só a "
            "janela retida — não é a mesma coisa que o backtest de 3,5 anos.",
            len(historico), LIMITE_HISTORICO, descartadas,
        )
    salvar_historico(historico[-LIMITE_HISTORICO:])

    # Fora do try de propósito: se a geração dos gráficos falhar, o bloco
    # abaixo segue e 'advise' precisa existir. Ficava dentro e, quando o
    # plot_forecast_fan lançava exceção, o ciclo morria mais adiante com
    # UnboundLocalError — foi o que o pandas 3 expôs.
    advise = None

    # Os PNGs por ativo (alerta_*.png) saíram do pipeline diário. Eram 4
    # imagens de ~150 KB cometidas TODO DIA e viraram 98,6% do repositório
    # (126 MB em 77 dias): binário regenerado não tem delta entre um dia e
    # outro. O painel agora desenha o mesmo leque em SVG a partir de
    # data.json, que é texto e comprime. Quem quiser a imagem ainda tem
    # `trendbot report` (CLI), que continua gerando.
    try:
        # 'report' continua necessário: é ele que desenha a alocação.
        from trendbot import report
        from trendbot.advisor import build_advice
        # Sem CARTEIRA_ATUAL, tudo em caixa — o comportamento de antes.
        # Com ela, a recomendação passa a ser um rebalanceamento do que a
        # pessoa tem, e não "como aplicar do zero".
        posicoes, caixa = parse_carteira(os.getenv("CARTEIRA_ATUAL"))
        capital = float(os.getenv("CAPITAL_INICIAL", "10000"))
        # sem carteira configurada fica tudo em caixa. O advisor já usa
        # `max(total, capital)` como piso (advisor.py), então não precisa
        # de fallback aqui — medir a diferença deu exatamente o mesmo
        # resultado, e uma linha que nenhum teste distingue é dívida.
        carteira = PortfolioState(
            capital=max(capital, sum(posicoes.values()) + caixa),
            monthly_contribution=float(os.getenv("APORTE_MENSAL", "0")),
            holdings=posicoes,
            cash=caixa,
        )
        advise = build_advice(md, forecasts, card, profile, carteira, settings)
        report.plot_allocation(advise.target_weights, advise.current_weights,
                               os.path.join(DOCS, "alocacao.png"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível gerar gráfico de alocação: %s", exc)

    meta = {"gerado_em": datetime.now().isoformat(timespec="seconds"),
            "fonte": md.source, "perfil": profile.key}

    with open(os.path.join(DOCS, "relatorio_completo.json"), "w", encoding="utf-8") as f:
        json.dump({
            "meta": meta,
            "modelo": card.as_dict(),
            "previsoes": {s: fc.as_dict() for s, fc in forecasts.items()},
            "recomendacao": advise.as_dict() if advise else None,
        }, f, ensure_ascii=False, indent=2, default=str)

    # O relatório completo tem as grades de quantis e pesa ~94 KB. Publicar
    # isso todo dia no git (e fazer o painel baixar) para mostrar meia dúzia
    # de números não compensa: o painel lê este arquivo enxuto, com só a
    # recomendação. O completo continua sendo gerado para quem depura.
    if advise is not None:
        with open(os.path.join(DOCS, "recomendacao.json"), "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "recomendacao": advise.as_dict()},
                      f, ensure_ascii=False, indent=2, default=str)
    elif os.path.exists(os.path.join(DOCS, "recomendacao.json")):
        # sem recomendação nova, não deixa o painel servir uma velha como se
        # fosse de hoje
        os.remove(os.path.join(DOCS, "recomendacao.json"))
        logger.warning("Sem recomendação neste ciclo: recomendacao.json antigo removido.")

    logger.info("Ciclo concluído.")


if __name__ == "__main__":
    fluxo_principal()
