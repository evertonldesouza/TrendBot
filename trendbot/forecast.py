"""Previsão probabilística com validação honesta (walk-forward).

Filosofia: o TrendBot não vende "preço de amanhã". Ele estima uma
**distribuição** de retornos para cada horizonte e, principalmente, mede se o
modelo tem ou não habilidade fora da amostra. Quando o modelo não bate um
benchmark ingênuo, o peso dele cai automaticamente — o relatório diz isso ao
usuário em vez de esconder.

Método
------
1. Features de momentum, volatilidade, reversão e posição relativa (sem
   informação do futuro).
2. Ridge (numpy, fechado) treinado em janela expansiva, com validação
   walk-forward passo a passo.
3. Habilidade fora da amostra (R² vs. previsor ingênuo = deriva histórica)
   define o peso do modelo: ``w = clip(R²_oos, 0, 1)`` com desconto por
   amostra curta.
4. Incerteza vem dos erros fora da amostra, reescalados pela volatilidade
   corrente (conformal com ajuste de vol) — não de uma suposição gaussiana.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from . import indicators as ind

logger = logging.getLogger(__name__)

HORIZONS = (1, 7, 30)
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)
TRADING_DAYS = 365

_MIN_TRAIN = 180       # mínimo de dias para treinar
_STEP = 5              # passo base do walk-forward
_RIDGE_ALPHA = 200.0   # regularização padrão (features padronizadas)
_ALPHA_GRID = (10.0, 50.0, 200.0, 1000.0, 5000.0)
_MAX_TRAIN = 750       # janela máxima de treino (adaptação a regimes recentes)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def build_features(price: pd.Series, high: pd.Series | None = None,
                   low: pd.Series | None = None) -> pd.DataFrame:
    """Matriz de features calculadas apenas com informação disponível em ``t``."""
    high = high if high is not None else price
    low = low if low is not None else price

    logp = np.log(price)
    rets = logp.diff()
    vol30 = ind.ewma_vol(rets, span=30, annualize=False)
    vol90 = ind.ewma_vol(rets, span=90, annualize=False)
    # Nas primeiras barras a vol ainda não existe: usa-se o desvio-padrão
    # EXPANDIDO (só do passado), nunca o da amostra inteira — usar o global
    # injetaria informação do futuro nas features.
    safe_vol = vol30.replace(0, np.nan).fillna(rets.expanding(min_periods=5).std())
    safe_vol = safe_vol.ffill().bfill().replace(0, np.nan).fillna(rets.abs().mean())

    feats = pd.DataFrame(index=price.index)
    for w in (7, 30, 90, 180):
        feats[f"mom_{w}"] = (logp.diff(w) / (safe_vol * np.sqrt(w))).replace([np.inf, -np.inf], np.nan)
    feats["rev_5"] = -(logp.diff(5) / (safe_vol * np.sqrt(5))).replace([np.inf, -np.inf], np.nan)
    feats["rsi_dev"] = (ind.rsi(price, 14) - 50.0) / 50.0
    feats["vol_z"] = ind.zscore(vol30, 180).clip(-4, 4)
    feats["vol_level"] = (vol30 * np.sqrt(TRADING_DAYS)).clip(0, 4)
    feats["vol_ratio"] = (vol30 / vol90.replace(0, np.nan)).clip(0, 5).fillna(1.0)
    feats["drawdown"] = ind.drawdown(price).clip(-0.95, 0.0)
    feats["pos_faixa"] = ind.position_in_range(price, 90)
    feats["dist_sma50"] = (price / ind.sma(price, 50) - 1.0).clip(-0.6, 0.6)
    feats["dist_sma200"] = (price / ind.sma(price, 200) - 1.0).clip(-0.8, 0.8)
    feats["macd_norm"] = (ind.macd(price)["hist"] / price * 100).clip(-10, 10)
    feats["atr_pct"] = (ind.atr(high, low, price, 14) / price).clip(0, 0.5)
    feats["tendencia"] = (ind.sma(price, 50) > ind.sma(price, 200)).astype(float)

    return feats.replace([np.inf, -np.inf], np.nan)


def _standardize(train: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = train.mean(axis=0)
    sd = train.std(axis=0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    return mu, sd, None


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float = _RIDGE_ALPHA):
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    Xs = (X - mu) / sd
    yc = y.mean()
    yv = y - yc
    d = Xs.shape[1]
    A = Xs.T @ Xs + alpha * np.eye(d)
    beta = np.linalg.solve(A, Xs.T @ yv)
    return mu, sd, beta, yc


def _select_alpha(X: np.ndarray, y: np.ndarray, grid: tuple[float, ...] = _ALPHA_GRID) -> float:
    """Escolhe a regularização por validação interna (holdout dos últimos 20%).

    Séries financeiras têm relação sinal/ruído minúscula: sem regularização
    forte o modelo decora o passado e perde fora da amostra. O alpha é
    escolhido dentro da janela de treino, nunca com dados do futuro.
    """
    n = len(X)
    if n < 120 or len(grid) < 2:
        return _ALPHA_GRID[len(_ALPHA_GRID) // 2]
    cut = int(n * 0.8)
    X_tr, y_tr = X[:cut], y[:cut]
    X_va, y_va = X[cut:], y[cut:]
    best_alpha, best_mse = grid[0], np.inf
    for alpha in grid:
        try:
            params = _ridge_fit(X_tr, y_tr, alpha=alpha)
        except np.linalg.LinAlgError:
            continue
        mse = float(np.mean((y_va - _ridge_predict(params, X_va)) ** 2))
        if mse < best_mse:
            best_mse, best_alpha = mse, alpha
    return best_alpha


def _ridge_predict(params, X: np.ndarray) -> np.ndarray:
    mu, sd, beta, yc = params
    return ((X - mu) / sd) @ beta + yc


# ---------------------------------------------------------------------------
# Resultados
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class HorizonForecast:
    horizon: int
    expected_return: float      # retorno esperado no horizonte (fração)
    median_return: float
    lower: float                # quantil 5% do retorno
    upper: float                # quantil 95% do retorno
    q25: float
    q75: float
    prob_up: float
    var95: float                # perda esperada no pior 5% (positivo = perda)
    cvar95: float
    intervals: dict[str, float] = field(default_factory=dict)
    model_weight: float = 0.0


@dataclass(slots=True)
class AssetForecast:
    symbol: str
    price: float
    horizons: dict[int, HorizonForecast]
    regime: str
    regime_detail: dict[str, str]
    skill: float                # R² fora da amostra vs. ingênuo
    hit_rate: float             # acerto de direção
    coverage: float             # cobertura empírica do intervalo 90%
    n_observations: int
    model_weight: float
    conviction: float           # -1 (convictamente negativo) .. +1
    drivers: list[dict[str, str]] = field(default_factory=list)
    indicators: dict[str, float] = field(default_factory=dict)
    history: dict[str, list] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["horizons"] = {str(k): asdict(v) for k, v in self.horizons.items()}
        return d


@dataclass(slots=True)
class ModelCard:
    """Resumo auditável da qualidade do modelo (honestidade em primeiro lugar)."""

    n_assets: int
    avg_skill: float
    avg_hit_rate: float
    avg_coverage: float
    observations: int
    verdict: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Núcleo: walk-forward
# ---------------------------------------------------------------------------

def _walk_forward(feats: pd.DataFrame, target: pd.Series, horizon: int,
                  min_train: int = _MIN_TRAIN):
    """Roda validação walk-forward. Retorna arrays de predições e realizados."""
    X_all = feats.to_numpy(dtype=float)
    y_all = target.to_numpy(dtype=float)
    n = len(X_all)

    # Regularização escolhida uma vez, na primeira janela de treino.
    first = min_train
    obs0 = np.isfinite(X_all[:first]).all(axis=1) & np.isfinite(y_all[:first])
    alpha = _select_alpha(X_all[:first][obs0], y_all[:first][obs0]) if obs0.sum() >= 120 else _RIDGE_ALPHA
    # Rotulos de h dias se sobrepoem quando o passo e menor que h. Um passo de
    # h/3 mantem ~3x de sobreposicao: amostra utilizavel sem inflar demais a
    # autocorrelacao dos erros.
    step = max(3, int(np.ceil(horizon / 3)))

    preds, naive, actual, times = [], [], [], []
    start = min_train
    while start + horizon < n:
        if not np.isfinite(y_all[start + horizon]):
            start += step
            continue
        X_tr = X_all[max(0, start - _MAX_TRAIN):start]
        y_tr = y_all[max(0, start - _MAX_TRAIN):start]
        mask = np.isfinite(X_tr).all(axis=1) & np.isfinite(y_tr)
        X_tr, y_tr = X_tr[mask], y_tr[mask]
        if len(X_tr) < 80:
            start += step
            continue
        try:
            params = _ridge_fit(X_tr, y_tr, alpha=alpha)
        except np.linalg.LinAlgError:
            start += step
            continue
        x_now = X_all[start]
        if not np.isfinite(x_now).all():
            start += step
            continue
        preds.append(float(_ridge_predict(params, x_now[None, :])[0]))
        # previsor ingênuo: média histórica dos retornos do horizonte
        naive.append(float(np.nanmean(y_tr[-250:])))
        actual.append(float(y_all[start + horizon]))
        times.append(start)
        start += step

    return (np.asarray(preds), np.asarray(naive), np.asarray(actual), np.asarray(times))


def _skill_score(pred: np.ndarray, naive: np.ndarray, actual: np.ndarray) -> tuple[float, float]:
    """R² fora da amostra do modelo contra o previsor ingênuo."""
    if len(actual) < 20:
        return 0.0, 0.5
    mse_model = float(np.mean((actual - pred) ** 2))
    mse_naive = float(np.mean((actual - naive) ** 2))
    if mse_naive <= 1e-12:
        return 0.0, 0.5
    skill = 1.0 - mse_model / mse_naive
    hit = float(np.mean(np.sign(pred) == np.sign(actual)))
    return float(skill), hit


def _vol_decay(horizon: int, tau: float = 45.0) -> float:
    """Peso da volatilidade corrente na projeção de um horizonte de ``h`` dias."""
    x = horizon / tau
    return float((1.0 - np.exp(-x)) / x) if x > 1e-6 else 1.0


def _horizon_vol(daily_returns: pd.Series, vol_now: float, horizon: int, tau: float = 45.0) -> float:
    """Volatilidade diária esperada ao longo do horizonte.

    A volatilidade reverte à média: projetar a vol de hoje por 30 dias
    superestima muito a incerteza. A fórmula interpola entre a vol corrente e a
    vol de longo prazo conforme o horizonte cresce (decaimento exponencial).
    """
    vol_lr = float(daily_returns.tail(730).std())
    if not np.isfinite(vol_lr) or vol_lr <= 1e-9:
        return float(max(vol_now, 1e-6))
    return float(vol_lr + (vol_now - vol_lr) * _vol_decay(horizon, tau))


def _regime(price: pd.Series, vol_z: float, adx: float, ret_90: float) -> tuple[str, dict[str, str]]:
    sma50 = ind.sma(price, 50).iloc[-1]
    sma200 = ind.sma(price, 200).iloc[-1] if len(price) > 60 else sma50
    if vol_z > 1.5:
        vol_label = "Volatilidade extrema"
    elif vol_z > 0.5:
        vol_label = "Volatilidade elevada"
    elif vol_z < -0.7:
        vol_label = "Volatilidade comprimida"
    else:
        vol_label = "Volatilidade normal"

    if price.iloc[-1] > sma200 and sma50 > sma200 and ret_90 > 0:
        trend_label = "Tendência de alta"
    elif price.iloc[-1] < sma200 and sma50 < sma200 and ret_90 < 0:
        trend_label = "Tendência de baixa"
    elif adx > 0 and adx < 20:
        trend_label = "Lateralizado"
    else:
        trend_label = "Transição / indefinido"

    regime = "risco-ligado" if trend_label == "Tendência de alta" and "extrema" not in vol_label else \
        ("risco-desligado" if trend_label == "Tendência de baixa" or "extrema" in vol_label else "neutro")
    return regime, {"volatilidade": vol_label, "tendencia": trend_label}


def forecast_asset(price: pd.Series, high: pd.Series | None = None,
                   low: pd.Series | None = None, symbol: str = "ATIVO",
                   horizons: tuple[int, ...] = HORIZONS) -> AssetForecast:
    """Gera previsões probabilísticas multi-horizonte para um ativo."""

    price = price.dropna()
    if len(price) < _MIN_TRAIN + 40:
        raise ValueError(f"Histórico insuficiente para {symbol}: {len(price)} dias.")

    feats = build_features(price, high, low)
    logp = np.log(price)
    vol_now = float(ind.ewma_vol(logp.diff(), span=30, annualize=False).iloc[-1])

    snapshot = ind.build_indicator_snapshot(price, high, low)
    horizons_out: dict[int, HorizonForecast] = {}
    skills, hits, coverages = [], [], []
    weights: list[float] = []
    n_tests: list[int] = []

    X_valid = feats.dropna()
    X_mat = X_valid.to_numpy(dtype=float)

    # Com histórico curto (a API pública da CoinGecko limita a 365 dias, e as
    # features consomem ~180 de aquecimento), treinar com 180 dias deixava
    # apenas 5 pontos de teste: abaixo do mínimo, a validação era pulada e o
    # card reportava a sentinela skill=-1 / cobertura=0 como se fosse medição.
    #
    # A regra reserva ~90 linhas para teste (~30 pontos, já descontado o passo
    # de 3) e encurta o treino só quando necessário: com dados de sobra nada
    # muda (sempre o menor dos dois).
    min_train = min(_MIN_TRAIN, max(80, len(X_valid) - 90))

    for h in horizons:
        target = (logp.shift(-h) - logp).reindex(X_valid.index)
        pred, naive, actual, times = _walk_forward(X_valid, target, h, min_train=min_train)
        if len(actual) < 25 or not np.isfinite(actual).all():
            logger.info("%s: amostra insuficiente no horizonte %dd (%d pontos).", symbol, h, len(actual))
            horizons_out[h] = _naive_horizon(logp, h, float(price.iloc[-1]))
            n_tests.append(0)
            continue

        skill, hit = _skill_score(pred, naive, actual)
        # peso do modelo: habilidade positiva, descontada por amostra curta
        w = float(np.clip(skill, 0.0, 1.0))
        w *= min(1.0, len(actual) / 120.0)
        w = float(np.clip(w, 0.0, 0.70))

        # --- tendência central: mistura da previsão do modelo com a deriva ---
        y_mat = target.to_numpy(dtype=float)
        obs = np.isfinite(X_mat).all(axis=1) & np.isfinite(y_mat)
        mu_model = 0.0
        if obs.sum() >= 80:
            try:
                idx = np.where(obs)[0]
                lo = max(0, len(idx) - _MAX_TRAIN)
                X_fit, y_fit = X_mat[idx][lo:], y_mat[idx][lo:]
                alpha_final = _select_alpha(X_fit, y_fit)
                params = _ridge_fit(X_fit, y_fit, alpha=alpha_final)
                mu_model = float(_ridge_predict(params, X_mat[obs][-1:])[0])
            except np.linalg.LinAlgError:
                mu_model = 0.0
        mu_naive = float(np.nanmean(y_mat[obs][-250:]))
        mu_naive *= 0.5   # encolhe a deriva: retornos de cripto são quase imprevisíveis
        mu = w * mu_model + (1 - w) * mu_naive

        # --- incerteza calibrada nos erros fora da amostra ---
        # O erro de cada ponto é padronizado pela volatilidade REALIZADA no
        # período previsto; na hora de prever, ele é reescalado pela
        # volatilidade ESPERADA para o horizonte (com reversão à média).
        daily = logp.diff()
        fwd_vol_series = daily.rolling(h, min_periods=min(h, max(2, h // 2))).std().shift(-(h - 1))
        fwd_vol = fwd_vol_series.reindex(X_valid.index).to_numpy(dtype=float)[times]
        fwd_vol = np.where(np.isfinite(fwd_vol) & (fwd_vol > 1e-9), fwd_vol, vol_now)

        vol_forecast = _horizon_vol(daily, vol_now, h)
        unit = vol_forecast * np.sqrt(h)
        norm = fwd_vol * np.sqrt(h)      # escala realizada de cada erro histórico

        blended = w * pred + (1 - w) * naive
        err_unit = (actual - blended) / norm
        ok = np.isfinite(err_unit)
        if ok.sum() < 25:
            horizons_out[h] = _naive_horizon(logp, h, float(price.iloc[-1]))
            n_tests.append(len(actual))
            continue

        # Cobertura honesta: para cada ponto, o intervalo é montado apenas com
        # os erros ANTERIORES e a volatilidade prevista NAQUELE momento — nunca
        # com o erro do próprio ponto.
        vol_inst = ind.ewma_vol(daily, span=30, annualize=False).reindex(X_valid.index).to_numpy(dtype=float)
        vol_long = daily.rolling(730, min_periods=120).std().reindex(X_valid.index).to_numpy(dtype=float)
        decay = _vol_decay(h)
        unit_hist = np.where(
            np.isfinite(vol_inst[times]) & np.isfinite(vol_long[times]) & (vol_long[times] > 1e-9),
            (vol_long[times] + (vol_inst[times] - vol_long[times]) * decay) * np.sqrt(h),
            unit,
        )

        cov_hits, cov_total = 0, 0
        err_hist: list[float] = []
        for i in range(len(err_unit)):
            if not ok[i]:
                continue
            if len(err_hist) >= 25:
                lo_q, hi_q = np.quantile(err_hist, [0.05, 0.95])
                cov_total += 1
                cov_hits += int(blended[i] + lo_q * unit_hist[i] <= actual[i]
                                <= blended[i] + hi_q * unit_hist[i])
            err_hist.append(float(err_unit[i]))
        coverage = float(cov_hits / cov_total) if cov_total else 0.0

        err_clean = err_unit[ok]
        dist = mu + err_clean * unit
        q05, q25, q50, q75, q95 = np.quantile(dist, list(QUANTILES))

        prob_up = float(np.mean(dist > 0))
        var95 = float(-np.quantile(dist, 0.05))
        tail = dist[dist <= np.quantile(dist, 0.05)]
        cvar95 = float(-tail.mean()) if len(tail) else var95

        skills.append(skill)
        hits.append(hit)
        coverages.append(coverage)
        weights.append(w)
        n_tests.append(len(actual))

        horizons_out[h] = HorizonForecast(
            horizon=h,
            expected_return=float(np.exp(mu + 0.5 * np.var(dist)) - 1.0),
            median_return=float(np.exp(q50) - 1.0),
            lower=float(np.exp(q05) - 1.0),
            upper=float(np.exp(q95) - 1.0),
            q25=float(np.exp(q25) - 1.0),
            q75=float(np.exp(q75) - 1.0),
            prob_up=prob_up,
            var95=var95,
            cvar95=cvar95,
            intervals={f"p{int(q*100)}": float(np.exp(np.quantile(dist, q)) - 1.0)
                       for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)},
            model_weight=w,
        )

    skill = float(np.mean(skills)) if skills else -1.0
    hit = float(np.mean(hits)) if hits else 0.5
    coverage = float(np.mean(coverages)) if coverages else 0.0
    weight = float(np.mean(weights)) if weights else 0.0
    n_obs = int(np.mean([n for n in n_tests if n])) if any(n_tests) else 0

    regime, detail = _regime(
        price,
        snapshot.get("vol_zscore", 0.0),
        snapshot.get("adx14", 0.0),
        snapshot.get("retorno_90d", 0.0),
    )

    # convicção: converte a inclinação da distribuição em algo comparável
    h30 = horizons_out.get(30) or horizons_out.get(max(horizons_out))
    conv_raw = 0.0
    if h30 is not None:
        spread = max(1e-6, h30.upper - h30.lower)
        conv_raw = (h30.median_return / spread) * 2.0
    conviction = float(np.clip(conv_raw, -1.0, 1.0) * (0.4 + 0.6 * weight))

    return AssetForecast(
        symbol=symbol,
        price=float(price.iloc[-1]),
        horizons=horizons_out,
        regime=regime,
        regime_detail=detail,
        skill=skill,
        hit_rate=hit,
        coverage=coverage,
        n_observations=n_obs,
        model_weight=weight,
        conviction=conviction,
        drivers=_explain(snapshot, horizons_out, weight, skill),
        indicators=snapshot,
        history={"dates": [d.strftime("%Y-%m-%d") for d in price.index[-365:]],
                 "prices": [round(float(v), 6) for v in price.iloc[-365:]]},
    )


def _naive_horizon(logp: pd.Series, h: int, price: float) -> HorizonForecast:
    """Fallback quando não há amostra suficiente: só a volatilidade observada."""
    rets = logp.diff().dropna()
    sd = float(rets.tail(90).std() * np.sqrt(h))
    drift = float(rets.tail(365).mean() * h)
    base = np.asarray([drift + sd * z for z in (-1.645, -0.674, 0.0, 0.674, 1.645)])
    return HorizonForecast(
        horizon=h,
        expected_return=float(np.exp(drift) - 1),
        median_return=float(np.exp(base[2]) - 1),
        lower=float(np.exp(base[0]) - 1),
        upper=float(np.exp(base[4]) - 1),
        q25=float(np.exp(base[1]) - 1),
        q75=float(np.exp(base[3]) - 1),
        prob_up=0.5,
        var95=float(-base[0]),
        cvar95=float(-base[0] * 1.3),
        intervals={f"p{int(q*100)}": float(np.exp(drift + sd * z) - 1)
                   for q, z in zip((0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95),
                                   (-1.645, -1.282, -0.674, 0.0, 0.674, 1.282, 1.645))},
        model_weight=0.0,
    )


def _explain(snap: dict[str, float], horizons: dict[int, HorizonForecast],
             weight: float, skill: float) -> list[dict[str, str]]:
    """Gera os 'porquês' legíveis que sustentam a recomendação."""
    drivers: list[dict[str, str]] = []

    rsi = snap.get("rsi14", 50.0)
    if rsi >= 70:
        drivers.append({"fator": "RSI", "valor": f"{rsi:.0f}", "sinal": "negativo",
                        "texto": "Sobrecomprado: historicamente precede realizações de curto prazo."})
    elif rsi <= 30:
        drivers.append({"fator": "RSI", "valor": f"{rsi:.0f}", "sinal": "positivo",
                        "texto": "Sobrevendido: costuma antecipar repiques de curto prazo."})
    else:
        drivers.append({"fator": "RSI", "valor": f"{rsi:.0f}", "sinal": "neutro",
                        "texto": "Momento equilibrado, sem extremo de curto prazo."})

    vsma = snap.get("dist_sma200", 0.0)
    if vsma > 0.10:
        drivers.append({"fator": "Tendência", "valor": f"{vsma:+.0%} vs MM200", "sinal": "positivo",
                        "texto": "Preço bem acima da média de 200 dias — tendência estrutural de alta."})
    elif vsma < -0.10:
        drivers.append({"fator": "Tendência", "valor": f"{vsma:+.0%} vs MM200", "sinal": "negativo",
                        "texto": "Preço abaixo da média de 200 dias — pressão vendedora estrutural."})
    else:
        drivers.append({"fator": "Tendência", "valor": f"{vsma:+.0%} vs MM200", "sinal": "neutro",
                        "texto": "Preço próximo da média longa, sem viés direcional claro."})

    vz = snap.get("vol_zscore", 0.0)
    if vz > 1.0:
        drivers.append({"fator": "Volatilidade", "valor": f"z = {vz:+.1f}", "sinal": "risco",
                        "texto": "Volatilidade muito acima do normal: aumente caixa ou reduza posição."})
    elif vz < -0.8:
        drivers.append({"fator": "Volatilidade", "valor": f"z = {vz:+.1f}", "sinal": "positivo",
                        "texto": "Volatilidade comprimida — ambiente favorável para carregar risco."})
    else:
        drivers.append({"fator": "Volatilidade", "valor": f"z = {vz:+.1f}", "sinal": "neutro",
                        "texto": "Volatilidade dentro da faixa habitual do ativo."})

    dd = snap.get("drawdown_atual", 0.0)
    if dd < -0.35:
        drivers.append({"fator": "Drawdown", "valor": f"{dd:.0%}", "sinal": "risco",
                        "texto": f"Queda de {abs(dd):.0%} desde o topo: risco de capitulação e de continuidade."})

    h30 = horizons.get(30)
    if h30 is not None:
        drivers.append({"fator": "Modelo (30d)",
                        "valor": f"{h30.median_return:+.1%} (p10 {h30.intervals.get('p10', 0):+.0%})",
                        "sinal": "positivo" if h30.median_return > 0.02 else
                                 ("negativo" if h30.median_return < -0.02 else "neutro"),
                        "texto": f"Peso do modelo na decisão: {weight:.0%} "
                                 f"(habilidade fora da amostra: {skill:+.2f})."})

    return drivers


# ---------------------------------------------------------------------------
# Universo
# ---------------------------------------------------------------------------

def forecast_universe(md, symbols: list[str] | None = None,
                      horizons: tuple[int, ...] = HORIZONS) -> tuple[dict[str, AssetForecast], ModelCard]:
    symbols = symbols or list(md.close.columns)
    out: dict[str, AssetForecast] = {}
    for sym in symbols:
        try:
            out[sym] = forecast_asset(
                md.close[sym].dropna(),
                md.high[sym] if md.high is not None and sym in md.high else None,
                md.low[sym] if md.low is not None and sym in md.low else None,
                symbol=sym,
                horizons=horizons,
            )
        except Exception as exc:  # noqa: BLE001 - um ativo não deve derrubar o relatório
            logger.warning("Falha na previsão de %s: %s", sym, exc)

    if not out:
        raise RuntimeError("Nenhuma previsão pôde ser gerada.")

    skills = [f.skill for f in out.values()]
    hits = [f.hit_rate for f in out.values()]
    cover = [f.coverage for f in out.values()]
    avg_skill = float(np.mean(skills))
    avg_hit = float(np.mean(hits))
    avg_cover = float(np.mean(cover))
    obs = int(np.mean([f.n_observations for f in out.values()]))

    notes: list[str] = []
    if obs <= 0:
        # Nenhum horizonte teve amostra fora da amostra suficiente. Aqui -1.0
        # e 0% são sentinelas, não medições: dizer "sem habilidade" acusaria o
        # modelo de algo que não foi testado.
        verdict = ("Histórico insuficiente para avaliar o modelo fora da amostra.")
        notes.append(
            "Nenhum horizonte reuniu o mínimo de pontos de teste, então o peso do "
            "modelo fica em zero por falta de evidência — não porque ele tenha se "
            "mostrado ruim. A recomendação segue guiada por risco e disciplina."
        )
        notes.append(
            "Para habilitar a avaliação, aumente DIAS_HISTORICO (ou use "
            "COINGECKO_API_KEY para levantar o limite de 365 dias da API pública)."
        )
    elif avg_skill > 0.05:
        verdict = "Modelo com habilidade marginal, mas positiva, fora da amostra."
        notes.append("Ainda assim, a vantagem é pequena: use o modelo para calibrar tamanho, não para apostar.")
    elif avg_skill > -0.05:
        verdict = "Modelo neutro: não supera o benchmark ingênuo de forma consistente."
        notes.append("Nesse cenário o TrendBot reduz automaticamente o peso do modelo e prioriza risco e alocação.")
    else:
        verdict = "Modelo sem habilidade fora da amostra neste recorte."
        notes.append("Previsões pontuais foram praticamente desligadas; a recomendação é guiada por risco e disciplina.")

    if 0 < obs < 120:
        notes.append(
            f"A validação rodou com apenas {obs} pontos fora da amostra: a "
            "estimativa de habilidade é ruidosa, e o peso do modelo já vem "
            "descontado por isso."
        )

    if avg_cover and avg_cover < 0.80:
        notes.append(f"Intervalos de 90% cobriram {avg_cover:.0%} dos resultados reais — "
                     "subestimação de cauda. Trate o risco como maior que o reportado.")
    elif avg_cover > 0.97:
        notes.append("Intervalos conservadores (cobertura acima de 97%): o risco real tende a ser menor.")

    return out, ModelCard(
        n_assets=len(out),
        avg_skill=avg_skill,
        avg_hit_rate=avg_hit,
        avg_coverage=avg_cover,
        observations=obs,
        verdict=verdict,
        notes=notes,
    )
