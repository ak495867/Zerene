"""
Stylized Facts Evaluator for Market Microstructure Simulation.
Validates whether simulation output or empirical tick streams exhibit established empirical facts:
1. Heavy tails (excess kurtosis of returns > 0)
2. Volatility clustering (autocorrelation of absolute returns > 0)
3. Bid-ask bounce (negative lag-1 return autocorrelation)
4. Order flow persistence / autocorrelation
"""

import numpy as np
from dataclasses import dataclass
from typing import Sequence, Dict, Any
from zerene.models import Trade


@dataclass(slots=True)
class StylizedFactsReport:
    """Summary of empirical stylized facts tests."""

    num_observations: int
    excess_kurtosis: float
    has_heavy_tails: bool  # True if kurtosis > 0.5 (excess fat tails)
    volatility_clustering_lag1_corr: float
    has_volatility_clustering: bool  # True if corr(|r_t|, |r_{t-1}|) > 0.05
    return_autocorr_lag1: float
    has_bid_ask_bounce: bool  # True if corr(r_t, r_{t-1}) < -0.02
    skewness: float
    is_realistic: bool  # Overall validation verdict

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_observations": self.num_observations,
            "excess_kurtosis": round(self.excess_kurtosis, 4),
            "has_heavy_tails": self.has_heavy_tails,
            "volatility_clustering_lag1_corr": round(
                self.volatility_clustering_lag1_corr, 4
            ),
            "has_volatility_clustering": self.has_volatility_clustering,
            "return_autocorr_lag1": round(self.return_autocorr_lag1, 4),
            "has_bid_ask_bounce": self.has_bid_ask_bounce,
            "skewness": round(self.skewness, 4),
            "is_realistic": self.is_realistic,
        }


class StylizedFactsEvaluator:
    """
    Evaluates simulated or real trade time-series against the key empirical stylized facts of financial markets.
    Cont (2001) 'Empirical properties of asset returns: stylized facts and statistical issues'.
    """

    @classmethod
    def evaluate_prices(cls, prices: Sequence[float]) -> StylizedFactsReport:
        """Evaluates stylized facts from an ordered price sequence."""
        p = np.asarray(prices, dtype=np.float64)
        if len(p) < 30:
            raise ValueError("Need at least 30 price points to evaluate stylized facts")

        # Log returns: r_t = log(p_t) - log(p_{t-1})
        p_clean = np.maximum(1e-8, p)
        returns = np.diff(np.log(p_clean))

        n = len(returns)
        mean_r = np.mean(returns)
        std_r = np.std(returns)

        if std_r <= 1e-12:
            return StylizedFactsReport(
                num_observations=n,
                excess_kurtosis=0.0,
                has_heavy_tails=False,
                volatility_clustering_lag1_corr=0.0,
                has_volatility_clustering=False,
                return_autocorr_lag1=0.0,
                has_bid_ask_bounce=False,
                skewness=0.0,
                is_realistic=False,
            )

        # Standardized returns
        z = (returns - mean_r) / std_r

        # Skewness: E[z^3]
        skewness = float(np.mean(z**3))

        # Excess Kurtosis: E[z^4] - 3.0 (normal distribution = 0.0)
        excess_kurtosis = float(np.mean(z**4) - 3.0)
        has_heavy_tails = excess_kurtosis > 0.5

        # Bid-ask bounce: Lag-1 autocorrelation of raw returns (should be negative due to spread crossing)
        r_t = returns[1:]
        r_tm1 = returns[:-1]
        cov_return = np.cov(r_t, r_tm1)
        r_autocorr = float(
            cov_return[0, 1] / max(1e-12, np.sqrt(cov_return[0, 0] * cov_return[1, 1]))
        )
        has_bid_ask_bounce = r_autocorr < -0.02

        # Volatility clustering: Lag-1 autocorrelation of absolute returns |r_t|
        abs_r = np.abs(returns)
        abs_t = abs_r[1:]
        abs_tm1 = abs_r[:-1]
        cov_abs = np.cov(abs_t, abs_tm1)
        vol_corr = float(
            cov_abs[0, 1] / max(1e-12, np.sqrt(cov_abs[0, 0] * cov_abs[1, 1]))
        )
        has_vol_clustering = vol_corr > 0.05

        # Overall verdict: passes if at least 2 of 3 empirical facts hold
        passes_count = sum([has_heavy_tails, has_vol_clustering, has_bid_ask_bounce])
        is_realistic = passes_count >= 2

        return StylizedFactsReport(
            num_observations=n,
            excess_kurtosis=excess_kurtosis,
            has_heavy_tails=has_heavy_tails,
            volatility_clustering_lag1_corr=vol_corr,
            has_volatility_clustering=has_vol_clustering,
            return_autocorr_lag1=r_autocorr,
            has_bid_ask_bounce=has_bid_ask_bounce,
            skewness=skewness,
            is_realistic=is_realistic,
        )

    @classmethod
    def evaluate_trades(cls, trades: Sequence[Trade]) -> StylizedFactsReport:
        """Helper to evaluate directly on ZERENE Trade objects."""
        prices = [t.price for t in trades]
        return cls.evaluate_prices(prices)
