"""
Basic simulation demonstration script showing Market Makers, Momentum Traders, and Noise Flow.
"""

from zerene.exchange.venue import ExchangeVenue
from zerene.strategies.market_maker import MarketMakerStrategy
from zerene.strategies.momentum import MomentumStrategy
from zerene.simulator.market_sim import MarketSimulator


def run_basic_simulation(steps: int = 1000, symbols: list = None) -> str:
    if symbols is None:
        symbols = ["BTC-USD"]

    exchange = ExchangeVenue("ZERENE-DEMO", symbols=symbols)
    simulator = MarketSimulator(exchange, poisson_rate=8.0)

    # Attach Market Maker and Momentum strategies
    for sym in symbols:
        mm = MarketMakerStrategy(
            symbol=sym, owner_id=f"MM_{sym}", spread_bps=12.0, quote_quantity=2.0
        )
        mom = MomentumStrategy(symbol=sym, owner_id=f"MOM_{sym}", trade_quantity=1.5)
        simulator.add_strategy(mm)
        simulator.add_strategy(mom)

    # Run discrete event simulation loop
    simulator.step(steps)

    # Return formatted analytics report summary
    report = simulator.get_analytics_report()
    return report.summary()


if __name__ == "__main__":
    print(run_basic_simulation(steps=500))
