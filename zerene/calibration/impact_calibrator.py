"""
Market Impact Calibrator.
Estimates Kyle's Lambda (linear impact) and the Square-Root Law scaling factor
from historical trade executions and corresponding quote price revisions.
"""

import math
import numpy as np
from dataclasses import dataclass
from typing import Sequence
from zerene.calibration.adapters import ExchangeTick
from zerene.models import Side


@dataclass(slots=True)
class ImpactFitResult:
    """Results of market impact estimation."""

    model_name: str
    lambda_param: float  # Kyle's lambda or square-root scale factor Y
    power_exponent: float  # 1.0 for Kyle, ~0.5 for square root
    r_squared: float  # Coefficient of determination R^2
    num_observations: int
    mean_abs_error: float


class ImpactCalibrator:
    """
    Calibrates market impact models directly against tick data:
    delta_p = price_{t + horizon} - price_{t}
    Signed volume = side * quantity (+ for BUY, - for SELL)
    """

    @classmethod
    def fit_kyles_lambda(
        cls,
        ticks: Sequence[ExchangeTick],
        return_horizon_ticks: int = 5,
    ) -> ImpactFitResult:
        """
        Fits Kyle's Lambda: delta_p = lambda * (signed_volume) + epsilon via Ordinary Least Squares (OLS).
        """
        signed_vols = []
        delta_prices = []

        n = len(ticks)
        for i in range(n - return_horizon_ticks):
            t_curr = ticks[i]
            t_future = ticks[i + return_horizon_ticks]

            sign = 1.0 if t_curr.side == Side.BUY else -1.0
            q = sign * t_curr.quantity
            dp = t_future.price - t_curr.price

            signed_vols.append(q)
            delta_prices.append(dp)

        if len(signed_vols) < 10:
            raise ValueError(
                "Insufficient trade observations to calibrate Kyle's Lambda"
            )

        x = np.array(signed_vols, dtype=np.float64)
        y = np.array(delta_prices, dtype=np.float64)

        # OLS through origin: lambda = sum(x * y) / sum(x^2)
        denom = np.sum(x**2)
        if denom <= 1e-12:
            lambda_est = 0.0
        else:
            lambda_est = float(np.sum(x * y) / denom)

        # Enforce non-negative price impact (buying pushes price up, selling pushes price down)
        lambda_est = max(0.0, lambda_est)

        # Calculate R^2 and MAE
        y_pred = lambda_est * x
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = float(1.0 - (ss_res / max(1e-12, ss_tot)))
        mae = float(np.mean(np.abs(y - y_pred)))

        return ImpactFitResult(
            model_name="KylesLambda",
            lambda_param=lambda_est,
            power_exponent=1.0,
            r_squared=r2,
            num_observations=len(x),
            mean_abs_error=mae,
        )

    @classmethod
    def fit_square_root_impact(
        cls,
        ticks: Sequence[ExchangeTick],
        daily_volatility: float = 0.02,
        daily_volume: float = 1e6,
        return_horizon_ticks: int = 5,
    ) -> ImpactFitResult:
        """
        Fits Square-Root Impact: delta_p = Y * sigma * sign(q) * sqrt(|q| / V_daily)
        Estimates scaling factor Y via OLS.
        """
        features = []
        delta_prices = []

        n = len(ticks)
        for i in range(n - return_horizon_ticks):
            t_curr = ticks[i]
            t_future = ticks[i + return_horizon_ticks]

            sign = 1.0 if t_curr.side == Side.BUY else -1.0
            norm_q = math.sqrt(t_curr.quantity / max(1.0, daily_volume))
            feat = sign * daily_volatility * norm_q
            dp = t_future.price - t_curr.price

            features.append(feat)
            delta_prices.append(dp)

        if len(features) < 10:
            raise ValueError(
                "Insufficient trade observations to calibrate Square-Root Impact"
            )

        x = np.array(features, dtype=np.float64)
        y = np.array(delta_prices, dtype=np.float64)

        denom = np.sum(x**2)
        y_scale = float(np.sum(x * y) / denom) if denom > 1e-12 else 0.5
        y_scale = max(0.0, y_scale)

        y_pred = y_scale * x
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = float(1.0 - (ss_res / max(1e-12, ss_tot)))
        mae = float(np.mean(np.abs(y - y_pred)))

        return ImpactFitResult(
            model_name="SquareRootImpact",
            lambda_param=y_scale,
            power_exponent=0.5,
            r_squared=r2,
            num_observations=len(x),
            mean_abs_error=mae,
        )
