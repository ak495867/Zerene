# RFC-001: Matching Engine Specification

**Status:** Active / Implemented  
**Author:** ak495867  
**Created:** 2026-07-14  

---

## 1. Abstract

This specification defines the architecture, behavior, and deterministic rules of the ZERENE Matching Engine (`zerene.engine.matching_engine.MatchingEngine`). The matching engine is responsible for executing price-time priority (`FIFO`) matching, managing order queues, handling partial fills, enforcing order lifecycles, and triggering conditional orders.

---

## 2. Core Principles

### 2.1 Determinism
Given an identical initial limit order book state and an exact chronological sequence of order arrival events, the matching engine MUST produce identical trade outputs, order status transitions, and final book states without exception.

### 2.2 Price-Time Priority (FIFO)
Orders at superior prices (higher bid prices or lower ask prices) MUST be executed before orders at inferior prices. Among resting orders at the exact same price level, execution priority is strictly determined by the arrival timestamp (`Time Priority`).

---

## 3. Order Lifecycle & Statuses

Every order within the ZERENE ecosystem transitions through a strictly validated state machine:

```
[Incoming] ---> [REJECTED] (If validation/FOK fails or PostOnly crosses)
     |
     v
   [NEW]
     |
     +---> [FILLED] (If fully matched immediately upon arrival)
     |
     +---> [PARTIALLY_FILLED] ---> [FILLED] (Upon subsequent matches)
     |              |
     |              +------------> [CANCELED] (Explicit cancel or IOC expiration)
     |
     +---> [TRIGGERED] (For Stop/StopLimit orders once stop price is crossed)
     |
     +---> [REPLACED] (If modified via atomic Cancel-Replace / FIX 35=G)
     |
     +---> [CANCELED] (If canceled while resting on book)
```

### 3.1 Atomic Order Modification (`MODIFY_ORDER` / `FIX 35=G`)
To mirror institutional exchange primitives (`FIX 35=G`), ZERENE supports atomic order modification (`modify_order`) with strict queue priority preservation rules:
1. **Priority Preservation (`Quantity Reduction`):** If an order is modified solely to decrease its resting quantity while the limit price remains unchanged, the order **preserves its exact time priority** in the FIFO `PriceLevel` queue. No queue relocation or timestamp reset occurs.
2. **Priority Loss (`Price Change` or `Quantity Increase`):** If an order is modified to change its limit price or increase its resting quantity, the order **loses priority**. It is atomically removed from its current position and inserted at the tail (`FIFO`) of the appropriate price level queue with a new timestamp.

---

## 4. Supported Order Types & Matching Rules

### 4.1 Market Orders (`MARKET`)
- **Behavior:** Executes immediately against opposite resting liquidity across consecutive price levels starting from the best available price.
- **Unfilled Residual:** If resting liquidity is exhausted before the market order's total quantity is filled, the residual quantity is transitioned to `FILLED` (with whatever was matched) or `CANCELED` (for the unfilled remainder). Market orders NEVER rest on the limit order book.

### 4.2 Limit Orders (`LIMIT`)
- **Behavior:** Specifies a maximum purchase price or minimum sale price.
- **Immediate Crossing:** If a Buy limit order arrives at a price $\ge$ best ask (or Sell limit $\le$ best bid), it matches immediately up to available volume across eligible levels.
- **Resting Residual:** Any remaining quantity after immediate matching rests on the limit order book at the order's specified limit price, sorted by time priority.

### 4.3 Immediate-or-Cancel (`IOC`)
- **Behavior:** Executes immediately against available liquidity up to its limit price (or market price).
- **Residual Handling:** Any unfilled portion is immediately `CANCELED`. Never rests on the book.

### 4.4 Fill-or-Kill (`FOK`)
- **Behavior:** Requires immediate and complete execution upon arrival.
- **Validation:** If total resting liquidity within the price limit is less than the order quantity, the entire order is rejected immediately with zero trades generated.

### 4.5 Post-Only (`POST_ONLY`)
- **Behavior:** Designed specifically for liquidity providers (`Maker`).
- **Validation:** If a incoming `PostOnly` order would cross existing resting orders and execute immediately as a `Taker`, the engine immediately transitions it to `REJECTED` status. Otherwise, it is placed on the book.

### 4.6 Reduce-Only (`REDUCE_ONLY`)
- **Behavior:** Ensures that an order can only decrease or close an existing open position held by `owner_id`.
- **Validation:** Checked in coordination with the `RiskEngine`. If the order would increase position magnitude or flip position sign from long to short (or vice versa), the order is either reduced in quantity (`display_quantity = max(0, abs(pos))`) or rejected.

### 4.7 Iceberg Orders (`ICEBERG`)
- **Behavior:** Hides the true size of an order to minimize market impact. Divided into `display_quantity` and `hidden_quantity`.
- **Replenishment Rule:** When the `display_quantity` is fully filled, the engine automatically replenishes up to `display_quantity` from `hidden_quantity`.
- **Priority Loss:** Every replenishment creates a new time priority entry for the replenished tranche. The hidden portion does NOT preserve the initial arrival timestamp priority.

### 4.8 Stop & Stop-Limit Orders (`STOP`, `STOP_LIMIT`)
- **Behavior:** Conditional orders maintained separately in the `StopManager` queue until market execution triggers them.
- **Trigger Condition:**
  - `Buy Stop`: Triggered when `last_trade_price` $\ge$ `stop_price`.
  - `Sell Stop`: Triggered when `last_trade_price` $\le$ `stop_price`.
- **Action Upon Trigger:**
  - `STOP`: Transformed into a `MARKET` order and submitted to the matching engine.
  - `STOP_LIMIT`: Transformed into a `LIMIT` order at `price` and submitted to the matching engine.

---

## 5. Trade Generation & Partial Fills

When an incoming `Taker` order executes against a resting `Maker` order:
1. A `Trade` record is generated containing `trade_id`, `symbol`, `price`, `quantity`, `maker_order_id`, `taker_order_id`, `aggressor_side`, and `timestamp`.
2. The `filled_quantity` of both orders is incremented by `trade_quantity`.
3. If `maker_order.filled_quantity == maker_order.quantity`, the maker order is removed from the price level queue and marked `FILLED`.
4. If `maker_order.filled_quantity < maker_order.quantity`, it remains in its exact position in the price level queue (`PARTIALLY_FILLED`).

---

## 6. Error & Rejection Handling

The matching engine raises or returns structured rejection reasons:
- `INSUFFICIENT_LIQUIDITY`: FOK order could not be completely filled.
- `WOULD_CROSS`: Post-Only order would immediately match against resting liquidity.
- `INVALID_PRICE`: Order price $\le 0$ or violates tick size constraints.
- `INVALID_QUANTITY`: Order quantity $\le 0$ or violates lot size constraints.
- `RISK_LIMIT_BREACH`: Order rejected by the pre-trade risk checks (`RiskEngine`).
