"""
Reinforcement learning training demonstration script.
Shows how to step through RLTradingEnvironment and compute inventory rewards.
"""

from zerene.strategies.rl_env import RLTradingEnvironment


def run_rl_demo(episodes: int = 3, max_steps: int = 100) -> str:
    env = RLTradingEnvironment(symbol="ETH-USD", max_steps=max_steps)
    lines = [
        "==================================================",
        "     ZERENE REINFORCEMENT LEARNING DEMO           ",
        "==================================================",
    ]

    for ep in range(1, episodes + 1):
        obs, _ = env.reset(seed=ep * 42)
        total_reward = 0.0
        terminated, truncated = False, False

        while not (terminated or truncated):
            # Sample simple heuristic action
            if obs[3] > 3.0:      # If long inventory > 3, sell market
                action = 4
            elif obs[3] < -3.0:   # If short inventory < -3, buy market
                action = 3
            else:
                action = (env.current_step % 2) + 1  # Alternate buy limit and sell limit

            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward

        lines.append(f"Episode {ep}: Total Reward = {total_reward:,.2f} | Final Inventory = {info['inventory']:.2f} | PnL = ${info['realized_pnl']:,.2f}")

    lines.append("==================================================")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run_rl_demo())
