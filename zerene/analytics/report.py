"""
Structured Analytics & Microstructure Quality Report container.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List
from zerene.analytics.metrics import (
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
)


@dataclass
class AnalyticsReport:
    """Comprehensive performance and microstructure quality report generated post-simulation."""

    total_steps: int
    total_trades: int
    total_volume_traded: float
    participant_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    market_quality_metrics: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_simulation(cls, sim: Any) -> "AnalyticsReport":
        total_trades = 0
        total_vol = 0.0
        for engine in sim.exchange.engines.values():
            total_trades += len(engine.trade_history)
            total_vol += sum(t.quantity * t.price for t in engine.trade_history)

        participant_metrics = {}
        for owner_id, state in sim.exchange.risk_engine.states.items():
            if owner_id in ("SEED_LP", "NOISE_TRADER"):
                continue
            dd = state.calculate_drawdown()
            sharpe = calculate_sharpe_ratio(state.return_history)
            participant_metrics[owner_id] = {
                "initial_capital": state.initial_capital,
                "realized_pnl": state.realized_pnl,
                "equity": state.equity,
                "max_drawdown": dd,
                "sharpe_ratio": sharpe,
                "kill_switch_active": state.kill_switch_active,
                "kill_switch_reason": state.kill_switch_reason,
            }

        return cls(
            total_steps=sim.step_count,
            total_trades=total_trades,
            total_volume_traded=total_vol,
            participant_metrics=participant_metrics,
            market_quality_metrics={
                "poisson_rate": sim.poisson_rate,
                "regime": sim.regime.value,
            },
        )

    def summary(self) -> str:
        lines = [
            "==================================================",
            "        ZERENE MARKET SIMULATION REPORT           ",
            "==================================================",
            f"Total Simulation Steps: {self.total_steps}",
            f"Total Trades Generated: {self.total_trades}",
            f"Total Volume Traded:    ${self.total_volume_traded:,.2f}",
            f"Market Regime:          {self.market_quality_metrics.get('regime', 'NORMAL')}",
            "--------------------------------------------------",
            "Participant Performance Metrics:",
        ]
        for pid, m in self.participant_metrics.items():
            lines.append(f"  [{pid}]")
            lines.append(
                f"    Realized PnL:   ${m['realized_pnl']:,.2f} (Equity: ${m['equity']:,.2f})"
            )
            lines.append(f"    Max Drawdown:   {m['max_drawdown']*100:.2f}%")
            lines.append(f"    Sharpe Ratio:   {m['sharpe_ratio']:.2f}")
            if m["kill_switch_active"]:
                lines.append(f"    [!] KILL SWITCH TRIPPED: {m['kill_switch_reason']}")
        lines.append("==================================================")
        return "\n".join(lines)
