# RFC-002: Limit Order Book Specification

**Status:** Active / Implemented  
**Author:** ak495867  
**Created:** 2026-07-14  

---

## 1. Abstract

This specification defines the structure, data representation, and analytical interface of the ZERENE Limit Order Book (`zerene.orderbook.book.OrderBook`). The order book maintains two distinct half-books: bids (buy orders) and asks (sell orders), organized by price levels and time priority queues.

---

## 2. Data Structures & Complexity Guarantees

### 2.1 Price Level Organization & $O(\log N)$ Tick Indexing
The order book stores price levels inside hash maps combined with binary-searched tick indexing arrays (`bisect`) to ensure strict $O(1)$ access to best bid (`sorted_bids[0]`) and best ask (`sorted_asks[0]`), while guaranteeing $O(\log N)$ insertion and deletion across tens of thousands of active price levels without sorting overhead (`O(N log N)`):
- **Bids (`bids` & `sorted_bids`):** Indexed in descending order via $O(\log N)$ binary search insertion (`_insort_desc`).
- **Asks (`asks` & `sorted_asks`):** Indexed in ascending order via $O(\log N)$ binary search insertion (`bisect.insort`).

### 2.2 Time Priority Queue per Level (`PriceLevel`)
Each price level (`PriceLevel`) maintains:
- `price`: The exact price of the level.
- `orders`: A double-ended queue (`collections.deque` or doubly-linked list representation) preserving strict order arrival sequence (`FIFO`).
- `total_volume`: Total visible volume (`display_quantity`) resting at this level.
- `hidden_volume`: Total hidden volume (`hidden_quantity` from iceberg/hidden orders) at this level.

### 2.3 Fast Order Lookup Map
To support $O(1)$ order cancellation and queue position querying, the order book maintains a global `order_map: Dict[str, Order]` mapping each `order_id` directly to its `Order` instance.

---

## 3. Order Book Queries & Analytics Interface

### 3.1 Core Market Data
- `best_bid()` $\rightarrow$ `Optional[float]`: Returns the highest resting buy price.
- `best_ask()` $\rightarrow$ `Optional[float]`: Returns the lowest resting sell price.
- `mid_price()` $\rightarrow$ `Optional[float]`: Returns $\frac{\text{best\_bid} + \text{best\_ask}}{2}$.
- `spread()` $\rightarrow$ `Optional[float]`: Returns $\text{best\_ask} - \text{best\_bid}$.

### 3.2 Depth & Market Snapshots
- `get_depth(levels: int = 10) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]`:
  Returns `(bids_depth, asks_depth)` up to the requested number of levels, where each tuple is `(price, total_volume)`.
- `get_volume_profile(bins: int = 20) -> Dict[str, Any]`:
  Aggregates resting volume across price buckets for liquidity density visualization and VWAP execution planning.

### 3.3 Microstructure Metrics
- **Order Imbalance (`imbalance`):**
  $$I = \frac{V_{bid} - V_{ask}}{V_{bid} + V_{ask}}$$
  where $V_{bid}$ and $V_{ask}$ represent total volume across the top $N$ levels. $I \in [-1, 1]$, where positive values indicate buy-side liquidity pressure.
- **Queue Position (`get_queue_position(order_id: str)`):**
  Returns `(level_rank, volume_ahead, orders_ahead)`, allowing strategies and execution routers to accurately model fill probability and adverse selection.

---

## 4. Iceberg & Hidden Order Handling

- **Hidden Orders:** Contribute strictly to `hidden_volume` on the price level and are not published in Level II snapshots (`get_depth()`). They only match if visible volume at that price level is completely exhausted or if matching rules dictate.
- **Iceberg Orders:** Only the `display_quantity` is reflected in `total_volume` and published snapshots. Upon depletion of the visible tranche, the `OrderBook` triggers replenishment from `hidden_quantity`, placing the new visible tranche at the tail of the `orders` queue (`FIFO`).
