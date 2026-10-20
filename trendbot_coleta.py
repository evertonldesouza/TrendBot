"""Compatibilidade com o módulo de coleta da v1.

A coleta agora vive em ``trendbot.data`` e suporta Binance (OHLCV completo),
CoinGecko, CSV local e simulação determinística — com cache em disco e
fallback automático. Esta função existe para não quebrar quem importava
``coletar_dados_historicos`` do arquivo antigo.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd

from trendbot.assets import resolve_asset
from trendbot.data import build_market_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def coletar_dados_historicos(coin: str | None = None, days: int | None = None) -> Optional[pd.DataFrame]:
    """Devolve um DataFrame com a coluna ``Preco_USD`` indexada por ``Data``.

    Mantém a assinatura da v1, mas por baixo usa o carregador novo (com cache,
    retentativas e fallback para simulação quando não há rede).
    """
    coin = coin or os.getenv("MOEDAS_ALVO", "bitcoin").split(",")[0]
    days = int(days or os.getenv("DIAS_HISTORICO", "365"))
    asset = resolve_asset(coin)

    md = build_market_data([asset], days=days,
                           source=os.getenv("FONTE_DADOS", "auto"))
    if md.close.empty or asset.symbol not in md.close.columns:
        logger.error("Não foi possível coletar dados de %s", asset.symbol)
        return None

    df = md.close[[asset.symbol]].rename(columns={asset.symbol: "Preco_USD"})
    df.index.name = "Data"
    logger.info("Coleta concluída: %d pontos de %s (%s)", len(df), asset.symbol, md.source)
    return df


if __name__ == "__main__":
    df = coletar_dados_historicos()
    if df is not None:
        print("\n--- Amostra dos Dados Coletados ---")
        print(df.tail())
