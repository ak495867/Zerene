"""
Vectorized Multi-Environment Runner for High-Throughput RL Training.
Allows batch execution across N parallel ZERENE simulator instances for
seamless integration with Gymnasium / Stable-Baselines3 / CleanRL.
"""

import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from zerene.strategies.rl_env import RLTradingEnvironment


class VectorRLTradingEnvironment:
    """
    Synchronous Vectorized Market Environment.
    Simulates N independent order books and market simulations in lockstep,
    outputting vectorized tensors for Deep RL policy updates.
    """

    def __init__(
        self,
        num_envs: int = 4,
        symbol: str = "BTC-USD",
        max_steps: int = 1000,
        seed_base: int = 42,
    ):
        self.num_envs = num_envs
        self.symbol = symbol
        self.max_steps = max_steps
        self.envs: List[RLTradingEnvironment] = [
            RLTradingEnvironment(
                symbol=symbol,
                max_steps=max_steps,
                seed=seed_base + i,
            )
            for i in range(num_envs)
        ]

    def reset(self, seed: Optional[int] = None) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """Resets all environments and returns stacked observation array (num_envs, obs_dim)."""
        obs_list = []
        infos = []
        for i, env in enumerate(self.envs):
            s = (seed + i) if seed is not None else None
            o, info = env.reset(seed=s)
            obs_list.append(o)
            infos.append(info)

        return np.vstack(obs_list), infos

    def step(
        self, actions: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[Dict[str, Any]]]:
        """
        Executes a vector of actions across all environments.
        Returns:
          obs: (num_envs, obs_dim)
          rewards: (num_envs,)
          terminated: (num_envs,)
          truncated: (num_envs,)
          infos: list of dicts
        """
        obs_list = []
        rewards = []
        terminated = []
        truncated = []
        infos = []

        for i, env in enumerate(self.envs):
            action_i = int(actions[i])
            o, r, term, trunc, info = env.step(action_i)

            # Auto-reset if episode ends
            if term or trunc:
                info["terminal_observation"] = o
                o, _ = env.reset()

            obs_list.append(o)
            rewards.append(r)
            terminated.append(term)
            truncated.append(trunc)
            infos.append(info)

        return (
            np.vstack(obs_list),
            np.array(rewards, dtype=np.float32),
            np.array(terminated, dtype=bool),
            np.array(truncated, dtype=bool),
            infos,
        )
