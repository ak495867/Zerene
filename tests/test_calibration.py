"""
Unit tests for calibration module (Hawkes MLE, Kyle's Lambda, and Stylized Facts).
"""

import pytest
import numpy as np
from zerene.calibration import (
    HawkesCalibrator,
    ImpactCalibrator,
    StylizedFactsEvaluator,
    BinanceDataParser,
    ExchangeTick,
)
from zerene.models import Side


def test_hawkes_mle_calibration():
    # Generate synthetic arrival times under known Hawkes parameters
    # Simple simulated Poisson/Hawkes arrival timestamps
    rng = np.random.default_rng(42)
    t = 0.0
    timestamps = [0.0]
    for _ in range(50):
        t += float(rng.exponential(scale=0.2))
        timestamps.append(t)

    params = HawkesCalibrator.fit(timestamps, fixed_beta=2.0)
    assert params.mu > 0.0
    assert params.alpha >= 0.0
    assert params.beta == 2.0
    assert params.branching_ratio < 1.0  # Stationary
    assert params.n_events == len(timestamps)


def test_impact_calibrator_kyles_lambda():
    ticks = []
    price = 100.0
    # Simulate buying pressure pushing prices up
    for i in range(100):
        side = Side.BUY if i % 2 == 0 else Side.SELL
        sign = 1.0 if side == Side.BUY else -1.0
        qty = 2.0
        price += sign * 0.05 + 0.001
        ticks.append(
            ExchangeTick(
                timestamp=float(i),
                price=price,
                quantity=qty,
                side=side,
            )
        )

    res = ImpactCalibrator.fit_kyles_lambda(ticks, return_horizon_ticks=2)
    assert res.lambda_param >= 0.0
    assert res.model_name == "KylesLambda"
    assert res.num_observations == 98


def test_stylized_facts_evaluator():
    # Synthetic prices with fat tails and volatility clustering
    rng = np.random.default_rng(42)
    prices = [100.0]
    # Simulate GARCH-like / Student-t returns
    for _ in range(500):
        ret = rng.standard_t(df=3) * 0.01  # Heavy-tailed Student-t
        new_p = max(1.0, prices[-1] * (1.0 + ret))
        prices.append(new_p)

    report = StylizedFactsEvaluator.evaluate_prices(prices)
    assert report.num_observations == 500
    assert (
        report.has_heavy_tails is True
    )  # Student-t(3) has large positive excess kurtosis
    d = report.to_dict()
    assert "excess_kurtosis" in d
    assert "is_realistic" in d


def test_binance_data_parser():
    sample_records = [
        {
            "id": 1,
            "price": "50000.0",
            "qty": "0.1",
            "time": 1600000000000,
            "isBuyerMaker": True,
        },
        {
            "id": 2,
            "price": "50005.0",
            "qty": "0.5",
            "time": 1600000001000,
            "isBuyerMaker": False,
        },
    ]
    ticks = BinanceDataParser.parse_trades_json(sample_records)
    assert len(ticks) == 2
    assert ticks[0].price == 50000.0
    assert ticks[0].side == Side.SELL  # Buyer was maker, taker was seller
    assert ticks[1].side == Side.BUY  # Seller was maker, taker was buyer
