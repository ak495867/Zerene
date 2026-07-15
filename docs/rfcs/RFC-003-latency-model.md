# RFC-003: Multi-Hop Latency Model Specification

**Status:** Active / Implemented  
**Author:** ak495867  
**Created:** 2026-07-14  

---

## 1. Abstract

This specification describes the ZERENE multi-hop latency simulation model (`zerene.latency.gateway.LatencyGateway` and `zerene.latency.models.*`). Realistic institutional market simulation requires accurate modeling of communication delays between participants and the matching engine, including network transit, gateway serialization, matching engine execution, and confirmation dissemination.

---

## 2. Multi-Hop Architectural Pipeline

Every order submission, cancellation, modification, and confirmation traverses a strictly ordered pipeline:

```
+------------+       T_client_out
|   Client   |-------------------------------+
+------------+                               |
                                             v
+------------+       Network Delay     +-----------+
|  Gateway   |<------------------------|  Network  |
+------------+                         +-----------+
      |
      | Gateway Serialization & Validation Delay
      v
+------------+       Exchange Queue    +-----------+
|  Exchange  |------------------------>| Matching  |
+------------+                         |  Engine   |
                                       +-----------+
                                             |
                                             | Execution & Trade Generation
                                             v
+------------+       Confirmation      +-----------+
|   Client   |<------------------------| Gateway / |
+------------+       Network Delay     | Exchange  |
                                       +-----------+
```

### 2.1 Latency Hops
1. **Client to Gateway (`L_net_in`):** Propagation delay across physical lines or cross-connect cables from the participant's trading server to the exchange boundary.
2. **Gateway Processing (`L_gateway`):** Time spent in risk check pre-validation and protocol deserialization (`MessagePack`/`FIX`).
3. **Matching Engine Queue (`L_engine`):** Lock-free queue transit and order matching execution time inside the matching engine core.
4. **Gateway to Client (`L_net_out`):** Return propagation of fill/cancel confirmation messages (`OrderEvent`) and public market data broadcasts (`L2/L3 updates`).

---

## 3. Latency Distribution Models

ZERENE supports both deterministic and stochastic delay profiles to evaluate execution sensitivity and race conditions:

### 3.1 Deterministic Profile (`DeterministicLatency`)
- Constant delay $L = \mu$ across all hops.
- Used for baseline verification, reproducible regression tests, and exact timing analysis.

### 3.2 Stochastic Profile (`StochasticLatency`)
Simulates real-world network jitter, queuing delays, and micro-burst packet loss:
- **Normal / Gaussian:** $L \sim \mathcal{N}(\mu, \sigma^2)$, truncated at minimum baseline latency $L_{min}$.
- **Exponential / Poisson Queue:** $L = L_{min} + \text{Exp}(\lambda)$, modeling queuing theory delays under load.
- **Lognormal Profile:** $L \sim \text{Lognormal}(\mu, \sigma)$, capturing right-skewed heavy-tail latency spikes (`microbursts`).
- **Pareto / Heavy-Tail:** Models rare institutional network freezes or garbage collection pauses.

### 3.3 Packet Drop Simulation (`packet_drop_rate`)
Each hop has a configurable probability $P_{drop} \in [0, 1)$ that an order submission or confirmation event is lost due to network degradation, forcing the client strategy to invoke timeout and retry logic.

---

## 4. Priority Event Queue Management

To preserve strict causality across asynchronous multi-hop participants:
1. The `LatencyGateway` wraps each event into a timestamped envelope:
   $$\text{Arrival Time} = T_{\text{source}} + L_{\text{total}}$$
2. Envelopes are pushed onto a min-heap (`heapq`) sorted by `arrival_time`.
3. When the `MarketSimulator` advances the discrete simulation clock to $T_{sim}$, all pending events where `arrival_time` $\le T_{sim}$ are popped in strict chronological order and delivered to their destination (matching engine or participant).
