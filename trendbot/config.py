"""Configuração e perfil do investidor (objetivo, horizonte, tolerância a risco)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Any

from .assets import CASH, Asset, moeda_canonica, resolve_assets

logger = logging.getLogger(__name__)


def _carregar_dotenv() -> None:
    """Lê o .env do diretório atual, se python-dotenv estiver instalado.

    Sem isso o .env.example era decorativo: nada no projeto carregava o
    arquivo, então quem seguisse a documentação não via efeito nenhum.
    Variáveis já presentes no ambiente ganham (é o caso do CI), porque
    load_dotenv não sobrescreve por padrão.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    # find_dotenv() sem usecwd procura a partir do ARQUIVO que chamou (aqui,
    # trendbot/config.py), e não de onde o usuário rodou o comando — então
    # nunca acharia o .env da raiz do projeto.
    caminho = find_dotenv(usecwd=True)
    if caminho:
        load_dotenv(caminho)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


@dataclass(frozen=True, slots=True)
class RiskProfile:
    """Tradução de um perfil de investidor em restrições numéricas."""

    key: str
    label: str
    description: str
    target_vol: float                    # volatilidade anualizada alvo
    max_vol: float                       # teto de vol anualizada
    max_drawdown: float                  # queda máxima tolerada (0.35 = -35%)
    equity_band: tuple[float, float]     # faixa permitida de exposição a risco
    cash_floor: float                    # colchão mínimo em caixa/stablecoin
    rebalance_band: float                # desvio que dispara rebalanceamento
    max_asset_weight: float              # concentração máxima por ativo
    hedge_allowed: bool

    @property
    def equity_target(self) -> float:
        return (self.equity_band[0] + self.equity_band[1]) / 2


PROFILES: dict[str, RiskProfile] = {
    "conservador": RiskProfile(
        key="conservador", label="Conservador",
        description="Preservação de capital: aceita crescer menos para proteger o patrimônio.",
        target_vol=0.22, max_vol=0.32, max_drawdown=0.20,
        equity_band=(0.15, 0.45), cash_floor=0.35, rebalance_band=0.06,
        max_asset_weight=0.25, hedge_allowed=True,
    ),
    "moderado": RiskProfile(
        key="moderado", label="Moderado",
        description="Equilíbrio entre crescimento e segurança, aceitando quedas relevantes no caminho.",
        target_vol=0.40, max_vol=0.55, max_drawdown=0.35,
        equity_band=(0.35, 0.70), cash_floor=0.15, rebalance_band=0.08,
        max_asset_weight=0.35, hedge_allowed=True,
    ),
    "arrojado": RiskProfile(
        key="arrojado", label="Arrojado",
        description="Busca retorno acima do mercado e convive com alta volatilidade.",
        target_vol=0.60, max_vol=0.80, max_drawdown=0.50,
        equity_band=(0.55, 0.90), cash_floor=0.05, rebalance_band=0.10,
        max_asset_weight=0.45, hedge_allowed=True,
    ),
    "agressivo": RiskProfile(
        key="agressivo", label="Agressivo",
        description="Máxima exposição a cripto, assumendo que pode perder metade do capital.",
        target_vol=0.85, max_vol=1.20, max_drawdown=0.65,
        equity_band=(0.75, 1.00), cash_floor=0.00, rebalance_band=0.12,
        max_asset_weight=0.60, hedge_allowed=False,
    ),
}

DEFAULT_PROFILE = "moderado"


def parse_carteira(texto: str | None) -> tuple[dict[str, float], float]:
    """Converte "BTC:12000,ETH:5000,USD:3000" em (posições, caixa).

    O caixa vem separado porque ``PortfolioState`` trata os dois de forma
    diferente: caixa não é exposição, e deixá-lo dentro de ``holdings`` faria
    o colchão virar "posição em dólar".

    Aceita nome ou símbolo — ``bitcoin:12000`` e ``BTC:12000`` dão no mesmo —
    para que quem configurou na v1 não quebre. Trechos malformados (sem dois pontos,
    valor não numérico) são ignorados com aviso: derrubar o relatório por causa
    de uma vírgula errada é desproporcional.

    Símbolo repetido soma, em vez de o último ganhar: é o que se espera de
    "BTC:1000,BTC:2000".
    """
    posicoes: dict[str, float] = {}
    caixa = 0.0
    if not texto:
        return posicoes, caixa

    for parte in texto.split(","):
        parte = parte.strip()
        if not parte:
            continue
        if ":" not in parte:
            logger.warning("Trecho de carteira ignorado (falta ':'): %r", parte)
            continue

        simbolo, valor_txt = parte.split(":", 1)
        try:
            valor = float(valor_txt.strip())
        except ValueError:
            logger.warning("Valor de carteira inválido ignorado: %r", parte)
            continue
        if valor <= 0:
            continue

        canonico = moeda_canonica(simbolo.strip()).upper() if simbolo.strip() else ""
        if not canonico:
            logger.warning("Ativo de carteira ignorado (sem símbolo): %r", parte)
            continue
        if canonico == CASH:
            caixa += valor
        else:
            posicoes[canonico] = posicoes.get(canonico, 0.0) + valor

    return posicoes, caixa


def get_profile(key: str | None = None) -> RiskProfile:
    """Perfil pelo nome. Sem chave (ou vazia), o padrão.

    Uma chave desconhecida levanta ValueError em vez de cair no padrão em
    silêncio: quem digita "conservdor" receberia a recomendação de outro
    perfil sem saber, e perfil de risco é exatamente a configuração que não
    pode ser trocada por acaso. A API converte isso em 400.
    """
    # o strip vem antes de testar vazio: "  " é truthy, e só depois de limpar
    # vira nome vazio — o que significa "não escolheu", não "nome inválido"
    bruto = (key or os.getenv("PERFIL_RISCO") or "").strip() or DEFAULT_PROFILE
    chave = bruto.lower()
    if chave in PROFILES:
        return PROFILES[chave]
    raise ValueError(
        f"Perfil de risco desconhecido: {bruto!r}. "
        f"Opções: {', '.join(sorted(PROFILES))}."
    )


@dataclass(slots=True)
class Settings:
    """Configuração de execução (fonte de dados, universo, saídas)."""

    assets: list[Asset] = field(default_factory=list)
    days: int = 730
    source: str = "auto"          # auto | coingecko | binance | synthetic | csv
    cache_dir: str = ".cache/trendbot"
    output_dir: str = "out"
    data_dir: str = "data"
    benchmark: str = "BTC"
    risk_free_rate: float = 0.045
    seed: int = 20260101
    allow_stale_cache: bool = True
    offline: bool = False
    # Tentativas por endpoint ao buscar preços. 1 favorece a latência do
    # relatório interativo; o job diário usa mais (ver TENTATIVAS_REDE).
    network_tries: int = 1

    @classmethod
    def from_env(cls, **overrides: Any) -> "Settings":
        _carregar_dotenv()
        raw_assets = os.getenv("MOEDAS_ALVO", "bitcoin,ethereum,solana,cardano")
        assets = resolve_assets([a for a in raw_assets.split(",") if a.strip()])
        cfg = cls(
            assets=assets,
            days=_env_int("DIAS_HISTORICO", 730),
            source=(os.getenv("FONTE_DADOS", "auto") or "auto").strip().lower(),
            cache_dir=os.getenv("CACHE_DIR", ".cache/trendbot"),
            output_dir=os.getenv("OUTPUT_DIR", "out"),
            data_dir=os.getenv("DATA_DIR", "data"),
            benchmark=(os.getenv("BENCHMARK", "BTC") or "BTC").upper(),
            risk_free_rate=_env_float("TAXA_LIVRE_RISCO", 0.045),
            seed=_env_int("SEED", 20260101),
            network_tries=max(1, _env_int("TENTATIVAS_REDE", 1)),
            allow_stale_cache=_env_bool("ACEITAR_CACHE_ANTIGO", True),
            offline=_env_bool("OFFLINE", False),
        )
        for key, value in overrides.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["assets"] = [a.symbol for a in self.assets]
        return data


@dataclass(slots=True)
class PortfolioState:
    """Carteira atual do investidor (o que ele tem hoje)."""

    capital: float = 10_000.0
    monthly_contribution: float = 0.0
    holdings: dict[str, float] = field(default_factory=dict)   # symbol -> USD
    cash: float = 0.0

    @property
    def total(self) -> float:
        invested = sum(max(0.0, v) for v in self.holdings.values())
        return invested + max(0.0, self.cash)

    def normalized(self) -> dict[str, float]:
        total = self.total
        if total <= 0:
            return {}
        weights = {s: max(0.0, v) / total for s, v in self.holdings.items()}
        weights["USD"] = max(0.0, self.cash) / total
        return weights

    def as_target_weights(self) -> dict[str, float]:
        if self.total <= 0:
            return {"USD": 1.0}
        return self.normalized()


def default_portfolio() -> PortfolioState:
    return PortfolioState(
        capital=_env_float("CAPITAL_INICIAL", 10_000.0),
        monthly_contribution=_env_float("APORTE_MENSAL", 0.0),
        holdings={},
        cash=_env_float("CAPITAL_INICIAL", 10_000.0),
    )
