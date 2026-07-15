"""
Tests for reinforcement learning trading environment (`RLTradingEnvironment`).
Verifies OpenAI Gym/Gymnasium API compatibility, isolated RNG, and MarketSimulator integration.
"""

import pytest
import numpy as np
from zerene.strategies.rl_env import RLTradingEnvironment


def test_rl_env_reset_and_step():
    env = RLTradingEnvironment(symbol="BTC-USD", max_steps=10, seed=42)
    obs, info = env.reset(seed=42)
    assert isinstance(obs, np.ndarray)
    assert obs.shape == (6,)
    assert obs[0] > 0.0  # mid_price

    # Take actions across discrete space
    for action in [0, 1, 2, 3, 4]:
        obs, reward, terminated, truncated, info = env.step(action)
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert "inventory" in info
        assert "reward" in info

    assert env.current_step == 5


def test_rl_env_deterministic_seeding():
    env1 = RLTradingEnvironment(symbol="ETH-USD", max_steps=5, seed=123)
    obs1, _ = env1.reset(seed=123)
    _, r1_1, _, _, _ = env1.step(1)
    _, r1_2, _, _, _ = env1.step(3)

    env2 = RLTradingEnvironment(symbol="ETH-USD", max_steps=5, seed=123)
    obs2, _ = env2.reset(seed=123)
    _, r2_1, _, _, _ = env2.step(1)
    _, r2_2, _, _, _ = env2.step(3)

    assert np.allclose(obs1, obs2)
    assert abs(r1_1 - r2_1) < 1e-9
    assert abs(r1_2 - r2_2) < 1e-9
