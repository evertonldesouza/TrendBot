"""Registro de ativos suportados pelo TrendBot.

Cada ativo é identificado de forma canônica por ``symbol`` (ex.: ``BTC``) e pode
ser coletado em múltiplas fontes. O ID da CoinGecko e o par da Binance ficam no
registro para que a camada de dados não precise de ``if`` espalhados pelo código.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

CASH = "USD"


@dataclass(frozen=True, slots=True)
class Asset:
    """Metadados de um ativo negociável."""

    key: str            # identificador canônico (CoinGecko id)
    symbol: str         # ticker curto usado no portfólio e no dashboard
    name: str
    binance: str | None  # par spot, ex.: BTCUSDT
    category: str = "cripto"
    color: str = "#58a6ff"

    @property
    def is_cash(self) -> bool:
        return self.category == "caixa"


_UNIVERSE: tuple[Asset, ...] = (
    Asset("bitcoin", "BTC", "Bitcoin", "BTCUSDT", "cripto", "#f7931a"),
    Asset("ethereum", "ETH", "Ethereum", "ETHUSDT", "cripto", "#8a9cff"),
    Asset("solana", "SOL", "Solana", "SOLUSDT", "cripto", "#19d3a2"),
    Asset("binancecoin", "BNB", "BNB", "BNBUSDT", "cripto", "#f3ba2f"),
    Asset("ripple", "XRP", "XRP", "XRPUSDT", "cripto", "#9aa4b2"),
    Asset("cardano", "ADA", "Cardano", "ADAUSDT", "cripto", "#4f8dfd"),
    Asset("dogecoin", "DOGE", "Dogecoin", "DOGEUSDT", "cripto", "#c2a633"),
    Asset("avalanche-2", "AVAX", "Avalanche", "AVAXUSDT", "cripto", "#e84142"),
    Asset("chainlink", "LINK", "Chainlink", "LINKUSDT", "cripto", "#2a5ada"),
    Asset("polkadot", "DOT", "Polkadot", "DOTUSDT", "cripto", "#e6007a"),
    Asset("litecoin", "LTC", "Litecoin", "LTCUSDT", "cripto", "#7fb6e8"),
    Asset("polygon-ecosystem-token", "POL", "Polygon", "POLUSDT", "cripto", "#8247e5"),
    Asset("near", "NEAR", "NEAR Protocol", "NEARUSDT", "cripto", "#00ec97"),
    Asset("sui", "SUI", "Sui", "SUIUSDT", "cripto", "#4da2ff"),
    Asset("aptos", "APT", "Aptos", "APTUSDT", "cripto", "#c7f0ff"),
    Asset("arbitrum", "ARB", "Arbitrum", "ARBUSDT", "cripto", "#12aaff"),
    Asset("toncoin", "TON", "Toncoin", "TONUSDT", "cripto", "#0098ea"),
    Asset("unus-sed-leo", "LEO", "LEO Token", None, "cripto", "#f0b90b"),
)

_BY_KEY = {a.key: a for a in _UNIVERSE}
_BY_SYMBOL = {a.symbol: a for a in _UNIVERSE}
CASH_ASSET = Asset(CASH, CASH, "Dólar / Stablecoin", None, "caixa", "#8b949e")


def resolve_asset(identifier: str) -> Asset:
    """Resolve ``bitcoin``, ``BTC`` ou ``btc`` para o registro canônico."""

    raw = (identifier or "").strip()
    if not raw:
        raise ValueError("Identificador de ativo vazio.")
    if raw.upper() == CASH:
        return CASH_ASSET

    lower = raw.lower()
    if lower in _BY_KEY:
        return _BY_KEY[lower]
    if raw.upper() in _BY_SYMBOL:
        return _BY_SYMBOL[raw.upper()]

    # Ativo não catalogado: mantém funcionamento com dados de CSV/demo,
    # mas sem par conhecido na Binance.
    symbol = raw.upper().replace(" ", "")[:8]
    return Asset(lower, symbol, raw.title(), None)


def resolve_assets(identifiers: Iterable[str]) -> list[Asset]:
    seen: set[str] = set()
    out: list[Asset] = []
    for item in identifiers:
        asset = resolve_asset(item)
        if asset.symbol in seen:
            continue
        seen.add(asset.symbol)
        out.append(asset)
    if not out:
        raise ValueError("Nenhum ativo configurado em MOEDAS_ALVO.")
    return out


def known_assets() -> tuple[Asset, ...]:
    return _UNIVERSE


def find_by_symbol(symbol: str) -> Asset:
    return _BY_SYMBOL.get(symbol.upper(), resolve_asset(symbol))


# Nomes legados (escritos pelo motor v1) e nomes atuais (símbolos) convivem no
# histórico: "BITCOIN" e "BTC" são o mesmo ativo. Sem unificar, o mesmo dia é
# registrado duas vezes e a precisão por moeda quebra.
#
# ATENÇÃO: este mapa precisa espelhar MOEDAS_CANONICAS em docs/script.js — o
# teste test_mapa_de_moedas_do_python_e_do_dashboard_concordam confere os dois.
_ALIASES_MOEDA: dict[str, str] = {}


def _construir_aliases() -> None:
    for asset in _UNIVERSE:
        _ALIASES_MOEDA[asset.symbol.upper()] = asset.symbol
        _ALIASES_MOEDA[asset.name.upper()] = asset.symbol
        _ALIASES_MOEDA[asset.key.upper()] = asset.symbol


_construir_aliases()


def moeda_canonica(nome: str) -> str:
    """Converte qualquer variante de nome no símbolo canônico (BTC, ETH...)."""
    chave = str(nome or "").strip().upper()
    return _ALIASES_MOEDA.get(chave, chave)
