"""limpar_historico.py
-------------------
Limpa o histórico de previsões (docs/historico.json).

Uso:
    python limpar_historico.py                       # só remove duplicatas
    python limpar_historico.py --remover-simuladas   # também remove as entradas geradas pelo simulador
    python limpar_historico.py historico.json        # arquivo customizado
    python limpar_historico.py --dry-run             # mostra o que faria, sem salvar

Duas limpezas distintas:

1. Duplicatas. O motor v1 gravava o nome por extenso ("BITCOIN") e o v2 grava
   o símbolo ("BTC"). Como o mesmo dia foi registrado nos dois padrões, a
   deduplicação por nome cru não via nada — por isso ela agora usa o nome
   canônico.

2. Entradas simuladas. Até 2026-10 o motor registrava a previsão do dia mesmo
   quando a API pública não respondia e ele caía na simulação. Essa previsão é
   conferida contra o preço real no dia seguinte e entra nas estatísticas de
   acerto como se fosse uma previsão de verdade. Entradas novas carregam o
   campo "fonte" e o motor não grava mais nada quando a fonte é sintética;
   esta opção serve para limpar as antigas, que nasceram sem esse campo e são
   identificadas pelo valor-âncora do simulador.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trendbot.assets import moeda_canonica  # noqa: E402
from trendbot.data import MarketData, simulate_market  # noqa: E402
from trendbot.forecast import forecast_universe  # noqa: E402

CAMINHO_PADRAO = "docs/historico.json"
DIAS_SIMULACAO = 1095
SEED_SIMULACAO = 20260101


def digitais_do_simulador(simbolos: list[str]) -> dict[str, float]:
    """Previsão exata (em centavos) que o simulador produz para cada símbolo.

    O simulador é determinístico e ancorado: a previsão do último dia sai
    igual em qualquer data. Isso dá uma impressão digital, e não uma faixa de
    tolerância — uma previsão real cair no centavo exato é impossível.

    Uma tolerância de 0,5% em torno da âncora parecia razoável e marcava 11
    entradas, mas várias eram reais (BITCOIN de 14/10 a 19/10, da era v1,
    quando a CoinGecko respondia). Prefiro não apagar dado real.
    """
    precos = simulate_market(simbolos, days=DIAS_SIMULACAO, seed=SEED_SIMULACAO)
    fc, _ = forecast_universe(MarketData(close=precos, source="synthetic"), horizons=(1,))
    return {
        s: round(fc[s].price * (1 + fc[s].horizons[1].median_return), 2)
        for s in simbolos if s in fc
    }


def remover_duplicatas(historico: list[dict]) -> tuple[list[dict], list[dict]]:
    """Mantém a entrada mais recente de cada (data, moeda canônica)."""
    vistos: dict[tuple[str, str], dict] = {}
    removidas: list[dict] = []

    for entrada in historico:
        chave = (entrada.get("data"), moeda_canonica(entrada.get("moeda")))
        if chave in vistos:
            # a última gravação é a mais recente: substitui a anterior
            removidas.append(vistos[chave])
        vistos[chave] = entrada

    return list(vistos.values()), removidas


def remover_simuladas(historico: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove o que veio do simulador: pelo campo "fonte" ou pela digital exata."""
    simbolos = sorted({moeda_canonica(e.get("moeda")) for e in historico})
    digitais = digitais_do_simulador(simbolos)

    limpas, removidas = [], []
    for entrada in historico:
        fonte = entrada.get("fonte")
        if fonte == "synthetic":
            removidas.append(entrada)
            continue

        # entradas antigas não têm "fonte": identificadas pela digital exata
        previsao = entrada.get("previsao")
        if previsao is not None:
            digital = digitais.get(moeda_canonica(entrada.get("moeda")))
            if digital is not None and round(float(previsao), 2) == digital:
                removidas.append(entrada)
                continue

        limpas.append(entrada)
    return limpas, removidas


def main() -> int:
    args = [a for a in sys.argv[1:]]
    dry_run = "--dry-run" in args
    args = [a for a in args if not a.startswith("--")]
    remover_simuladas_flag = "--remover-simuladas" in sys.argv
    caminho = args[0] if args else CAMINHO_PADRAO

    if not os.path.exists(caminho):
        print(f"Arquivo não encontrado: {caminho}")
        return 1

    with open(caminho, "r", encoding="utf-8") as f:
        historico = json.load(f)

    total_antes = len(historico)

    # Ordem importa: remover as simuladas ANTES de deduplicar. Rodando a
    # dedução primeiro, ela mantinha a última gravação do dia — que era justo
    # a simulada — e descartava a real.
    simuladas: list[dict] = []
    if remover_simuladas_flag:
        historico, simuladas = remover_simuladas(historico)

    historico, duplicatas = remover_duplicatas(historico)

    print(f"Arquivo            : {caminho}")
    print(f"Entradas antes     : {total_antes}")
    if duplicatas:
        print(f"Duplicatas removidas: {len(duplicatas)}")
        for e in duplicatas:
            print(f"   - {e.get('data')} {e.get('moeda')} (mantida a versão mais recente)")
    if remover_simuladas_flag:
        print(f"Simuladas removidas : {len(simuladas)}")
        for e in simuladas:
            print(f"   - {e.get('data')} {e.get('moeda')} previsao={e.get('previsao')}")
    print(f"Entradas depois    : {len(historico)}")

    if dry_run:
        print("\n--dry-run: nada foi salvo.")
        return 0

    if len(historico) == total_antes:
        print("\nNada a alterar.")
        return 0

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=4)
    print(f"\nArquivo salvo com {len(historico)} entradas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
