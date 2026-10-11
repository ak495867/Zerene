"""
Hawkes Process Maximum Likelihood Estimation (MLE) Calibrator.
Estimates baseline arrival rate (mu), self-excitation (alpha), and decay rate (beta)
from empirical tick arrival timestamps (e.g., real trade or quote events).
"""

import math
import numpy as np
from dataclasses import dataclass
from typing import List, Sequence, Tuple, Optional


@dataclass(slots=True)
class HawkesParams:
    """Fitted parameters for a 1D or 2D Hawkes process."""

    mu: float  # Baseline intensity
    alpha: float  # Excitation amplitude
    beta: float  # Exponential decay rate
    branching_ratio: float  # alpha / beta (must be < 1.0 for stationarity)
    log_likelihood: float
    n_events: int
    duration: float


class HawkesCalibrator:
    """
    Fits Hawkes process parameters (mu, alpha, beta) to empirical event timestamps.
    Uses Maximum Likelihood Estimation (MLE) via gradient-free / L-BFGS-B optimization
    with an exact recursive log-likelihood formulation:

    log L = sum_{i=1}^N log(lambda(t_i)) - int_0^T lambda(t) dt
    where:
    lambda(t_i) = mu + alpha * R(i)
    R(i) = exp(-beta * (t_i - t_{i-1})) * (1 + R(i-1)), R(1) = 0
    int_0^T lambda(t) dt = mu * T + (alpha / beta) * sum_{i=1}^N (1 - exp(-beta * (T - t_i)))
    """

    @staticmethod
    def log_likelihood(
        timestamps: np.ndarray,
        mu: float,
        alpha: float,
        beta: float,
        total_duration: Optional[float] = None,
    ) -> float:
        """
        Computes exact log-likelihood in O(N) using the recursive formulation (Ozaki 1979).
        """
        n = len(timestamps)
        if n < 2 or mu <= 1e-6 or alpha < 0.0 or beta <= 1e-6 or alpha >= beta:
            return -1e12

        t_0 = timestamps[0]
        t_n = timestamps[-1]
        T = total_duration if total_duration is not None else (t_n - t_0)
        if T <= 0.0:
            return -1e12

        # Shift timestamps relative to t_0
        t = timestamps - t_0

        # Recursive calculation of R(i)
        log_lambda_sum = 0.0
        r = 0.0

        for i in range(n):
            if i > 0:
                dt = t[i] - t[i - 1]
                r = math.exp(-beta * dt) * (1.0 + r)

            lam = mu + alpha * r
            if lam <= 0.0:
                return -1e12
            log_lambda_sum += math.log(lam)

        # Integral term: int_0^T lambda(t) dt
        # = mu * T + sum_{i=1}^n (alpha / beta) * (1 - exp(-beta * (T - t[i])))
        int_term = mu * T
        exp_terms = np.exp(-beta * (T - t))
        int_term += (alpha / beta) * np.sum(1.0 - exp_terms)

        return log_lambda_sum - int_term

    @classmethod
    def fit(
        cls,
        timestamps: Sequence[float],
        initial_beta: float = 2.0,
        fixed_beta: Optional[float] = None,
        max_iter: int = 200,
    ) -> HawkesParams:
        """
        Fits Hawkes parameters via Nelder-Mead / Powell numerical optimization.
        If `fixed_beta` is provided, estimates only (mu, alpha).
        """
        ts = np.asarray(sorted(timestamps), dtype=np.float64)
        n = len(ts)
        if n < 5:
            raise ValueError("Need at least 5 timestamps to fit Hawkes process")

        t_0 = ts[0]
        t_n = ts[-1]
        T = max(1e-4, t_n - t_0)
        empirical_rate = n / T

        # Initial heuristics
        init_mu = empirical_rate * 0.4
        init_alpha = 0.8
        init_beta = fixed_beta if fixed_beta is not None else initial_beta

        def objective(params: np.ndarray) -> float:
            if fixed_beta is not None:
                mu, alpha = params[0], params[1]
                beta = fixed_beta
            else:
                mu, alpha, beta = params[0], params[1], params[2]

            # Penalize out of bounds
            if mu <= 1e-4 or alpha < 0.0 or beta <= 1e-4:
                return 1e12
            if alpha >= 0.999 * beta:  # Stationarity condition: alpha / beta < 1
                return 1e12 + (alpha - 0.999 * beta) * 1e6

            ll = cls.log_likelihood(ts, mu, alpha, beta, total_duration=T)
            return -ll  # Minimize negative log-likelihood

        # Simple grid / Nelder-Mead search without requiring heavy external solver
        best_loss = float("inf")
        best_params = (init_mu, init_alpha, init_beta)

        # Grid initialize
        test_mus = [empirical_rate * 0.2, empirical_rate * 0.5, empirical_rate * 0.8]
        test_ratios = [0.2, 0.5, 0.7]
        test_betas = [init_beta] if fixed_beta is not None else [0.5, 1.5, 3.0, 5.0]

        for b in test_betas:
            for r in test_ratios:
                a = r * b
                for m in test_mus:
                    p = np.array([m, a] if fixed_beta is not None else [m, a, b])
                    loss = objective(p)
                    if loss < best_loss:
                        best_loss = loss
                        best_params = (m, a, b)

        # Local coordinate descent refinement
        curr_mu, curr_alpha, curr_beta = best_params
        step_sizes = [
            curr_mu * 0.1,
            curr_alpha * 0.1,
            curr_beta * 0.1 if fixed_beta is None else 0.0,
        ]

        for _ in range(max_iter):
            improved = False
            # Optimize mu
            for d in [-step_sizes[0], step_sizes[0]]:
                candidate = (curr_mu + d, curr_alpha, curr_beta)
                p = np.array(
                    [candidate[0], candidate[1]]
                    if fixed_beta is not None
                    else candidate
                )
                loss = objective(p)
                if loss < best_loss:
                    best_loss = loss
                    curr_mu = candidate[0]
                    improved = True

            # Optimize alpha
            for d in [-step_sizes[1], step_sizes[1]]:
                candidate = (curr_mu, curr_alpha + d, curr_beta)
                p = np.array(
                    [candidate[0], candidate[1]]
                    if fixed_beta is not None
                    else candidate
                )
                loss = objective(p)
                if loss < best_loss:
                    best_loss = loss
                    curr_alpha = candidate[1]
                    improved = True

            # Optimize beta if not fixed
            if fixed_beta is None:
                for d in [-step_sizes[2], step_sizes[2]]:
                    candidate = (curr_mu, curr_alpha, curr_beta + d)
                    p = np.array(candidate)
                    loss = objective(p)
                    if loss < best_loss:
                        best_loss = loss
                        curr_beta = candidate[2]
                        improved = True

            if not improved:
                step_sizes = [s * 0.5 for s in step_sizes]
                if step_sizes[0] < 1e-4:
                    break

        branching_ratio = curr_alpha / curr_beta
        final_ll = -best_loss

        return HawkesParams(
            mu=float(curr_mu),
            alpha=float(curr_alpha),
            beta=float(curr_beta),
            branching_ratio=float(branching_ratio),
            log_likelihood=float(final_ll),
            n_events=n,
            duration=float(T),
        )
