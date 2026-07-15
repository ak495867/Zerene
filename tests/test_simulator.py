"""
Tests for strategies, simulation loop, and CLI.
"""

import pytest
from zerene.exchange.venue import ExchangeVenue
from zerene.strategies.market_maker import MarketMakerStrategy
from zerene.simulator.market_sim import MarketSimulator
from zerene.cli.main import main


def test_simulation_and_strategy_execution():
    exchange = ExchangeVenue("ZERENE-TEST", symbols=["ETH-USD"])
    sim = MarketSimulator(exchange, time_step=1.0, poisson_rate=5.0)
    mm = MarketMakerStrategy(symbol="ETH-USD", owner_id="MM_TEST", spread_bps=10.0)
    sim.add_strategy(mm)

    sim.step(50)
    report = sim.get_analytics_report()
    assert report.total_steps == 50
    assert report.total_trades > 0


def test_cli_bench_and_sim(capsys):
    ret = main(["benchmark", "--orders", "1000", "--symbol", "TEST-USD"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "orders_per_second" in captured.out

    ret_sim = main(["sim", "--symbols", "BTC-USD", "--steps", "10"])
    assert ret_sim == 0
