"""
Critério de Kelly (crescimento logarítmico esperado da riqueza).

Para aposta binária: com fração f da banca, vitória multiplica por (1 + f·b),
derrota por (1 − f), onde b é o lucro líquido por 1 unidade apostada (ex.: 0,9 → +90% sobre o stake).

Kelly completo: f* = (p·b − (1−p)) / b = (p·b − q) / b, que maximiza E[log W].

Referências clássicas: J. L. Kelly (1956); uso prático com Kelly fracionado e p incerto
(Wilson / Beta) para reduzir risco de modelo.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple


@dataclass(frozen=True)
class TradeOutcome:
    stake: float
    profit: float
    won: bool


def wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Limite inferior do intervalo de confiança de Wilson para a proporção de vitórias (conservador)."""
    if n <= 0:
        return 0.0
    phat = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2.0 * n)
    rad = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    return max(0.0, (centre - rad) / denom)


def beta_posterior_mean(wins: int, losses: int, alpha_prior: float, beta_prior: float) -> float:
    """Média posterior Beta(α+w, β+l) com prior Beta(α,β)."""
    a = alpha_prior + wins
    b = beta_prior + losses
    if a + b <= 0:
        return 0.5
    return a / (a + b)


def kelly_binary_full_fraction(p: float, b: float) -> float:
    """
    Fração Kelly completa da banca (0..∞ teoricamente; deve ser limitada depois).
    p = P(vitória), b = lucro líquido por 1 unidade de stake em vitória; perda = 100% do stake.
    """
    if b <= 1e-12:
        return 0.0
    q = 1.0 - p
    return max(0.0, (p * b - q) / b)


def expected_log_growth(f: float, p: float, b: float) -> float:
    """E[log(1 + f·X)] com X ∈ {b, -1}. Útil para validar f no domínio."""
    q = 1.0 - p
    if f <= 0.0 or f >= 1.0:
        return float("-inf")
    if 1.0 + f * b <= 1e-15 or 1.0 - f <= 1e-15:
        return float("-inf")
    return p * math.log(1.0 + f * b) + q * math.log(1.0 - f)


def mean_win_payoff_ratio(history: List[TradeOutcome]) -> Optional[float]:
    """Média de (profit/stake) apenas em vitórias; None se não houver vitórias na janela."""
    ratios = [t.profit / t.stake for t in history if t.won and t.stake > 1e-12]
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def compute_kelly_stake_fraction(
    history: Deque[TradeOutcome],
    *,
    default_b: float,
    kelly_fraction: float,
    use_wilson_p: bool,
    alpha_prior: float,
    beta_prior: float,
    max_full_kelly: float,
    drawdown: float,
    drawdown_soft_start: float,
    drawdown_min_scale: float,
) -> Tuple[float, dict]:
    """
    Retorna fração da banca a arriscar (0..max_full_kelly após escalas) e metadados para log/debug.
    """
    meta: dict = {"mode": "kelly", "n": len(history)}
    if len(history) == 0:
        meta["reason"] = "sem histórico"
        return 0.0, meta

    wins = sum(1 for t in history if t.won)
    losses = len(history) - wins
    n = len(history)

    b_hat = mean_win_payoff_ratio(list(history))
    if b_hat is None or b_hat <= 1e-12:
        b_hat = default_b
        meta["b_source"] = "default"
    else:
        meta["b_source"] = "empirical"

    meta["b_hat"] = round(b_hat, 4)

    if use_wilson_p:
        p_used = wilson_lower_bound(wins, n)
        meta["p_method"] = "wilson_lb"
    else:
        p_used = beta_posterior_mean(wins, losses, alpha_prior, beta_prior)
        meta["p_method"] = "beta_mean"

    meta["p_used"] = round(p_used, 4)
    meta["wins"] = wins
    meta["losses"] = losses

    f_full = kelly_binary_full_fraction(p_used, b_hat)
    meta["f_full"] = round(f_full, 6)

    if f_full <= 0.0:
        meta["edge"] = "none_or_negative"
        return 0.0, meta

    f_full = min(f_full, max_full_kelly)
    f = f_full * kelly_fraction
    meta["f_after_fractional"] = round(f, 6)

    if drawdown_soft_start > 0.0 and drawdown >= drawdown_soft_start:
        # Do soft_start até DD=100%: escala linearmente f até drawdown_min_scale
        t = min(1.0, (drawdown - drawdown_soft_start) / max(1e-6, 1.0 - drawdown_soft_start))
        scale = 1.0 - t * (1.0 - drawdown_min_scale)
        f *= max(drawdown_min_scale, scale)
        meta["drawdown_scale"] = round(scale, 4)

    meta["f_final"] = round(f, 6)
    meta["expected_log_growth"] = round(expected_log_growth(f, p_used, b_hat), 6)
    return f, meta
