#pragma once

#include <cstdint>
#include <string>
#include <limits>

#if !defined(__GNUC__) && !defined(__clang__)
#ifndef __builtin_expect
#define __builtin_expect(expr, val) (expr)
#endif
#endif

namespace zerene {

enum class Side : uint8_t {
    BUY = 0,
    SELL = 1
};

enum class OrderType : uint8_t {
    LIMIT = 0,
    MARKET = 1,
    IOC = 2,
    FOK = 3,
    POST_ONLY = 4
};

enum class OrderStatus : uint8_t {
    NEW = 0,
    PARTIALLY_FILLED = 1,
    FILLED = 2,
    CANCELED = 3,
    REJECTED = 4,
    REPLACED = 5
};

// High-speed cache-aligned order structure (packed tightly)
struct alignas(64) Order {
    uint64_t internal_id{0};
    uint64_t order_id_hash{0};
    int64_t price_ticks{0};       // Fixed point (price * 10,000)
    double quantity{0.0};
    double filled_quantity{0.0};
    double timestamp{0.0};
    uint32_t order_id_num{0};     // Fast integer ID
    Side side{Side::BUY};
    OrderType order_type{OrderType::LIMIT};
    OrderStatus status{OrderStatus::NEW};
    uint8_t flags{0};

    // Intrusive Doubly-Linked List pointers for zero-allocation queue
    Order* prev{nullptr};
    Order* next{nullptr};

    inline double remaining_quantity() const noexcept {
        return quantity - filled_quantity;
    }

    inline bool is_active() const noexcept {
        return status == OrderStatus::NEW || status == OrderStatus::PARTIALLY_FILLED;
    }
};

// Trade execution record
struct Trade {
    uint64_t trade_id{0};
    uint32_t maker_order_id_num{0};
    uint32_t taker_order_id_num{0};
    int64_t price_ticks{0};
    double price{0.0};
    double quantity{0.0};
    Side aggressor_side{Side::BUY};
    double timestamp{0.0};
};

} // namespace zerene
