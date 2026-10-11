#pragma once

#include "types.hpp"
#include "order_book.hpp"
#include "memory_pool.hpp"
#include <vector>
#include <string>
#include <cmath>

namespace zerene {

class MatchingEngineCore {
public:
    explicit MatchingEngineCore(const std::string& symbol = "BENCH-USD", int64_t initial_price_ticks = 1'000'000)
        : symbol_(symbol),
          order_book_(initial_price_ticks),
          pool_(1'000'000),
          trade_counter_(0),
          last_trade_price_ticks_(0)
    {
        trades_buffer_.reserve(100'000);
    }

    inline FastOrderBook& book() noexcept { return order_book_; }
    inline const FastOrderBook& book() const noexcept { return order_book_; }
    inline uint64_t trade_count() const noexcept { return trade_counter_; }
    inline int64_t last_trade_price_ticks() const noexcept { return last_trade_price_ticks_; }
    inline void set_record_trades(bool record) noexcept { record_trades_ = record; }
    inline bool is_recording_trades() const noexcept { return record_trades_; }

    // Direct C++ hot path for maximum throughput (10M+ ops/sec)
    inline size_t process_order_fast(
        uint32_t order_id_num,
        Side side,
        OrderType order_type,
        int64_t price_ticks,
        double quantity,
        double timestamp = 0.0
    ) noexcept {
        if (__builtin_expect(quantity <= 0.0, 0)) {
            return 0;
        }

        Order* incoming = pool_.allocate();
        incoming->order_id_num = order_id_num;
        incoming->side = side;
        incoming->order_type = order_type;
        incoming->price_ticks = price_ticks;
        incoming->quantity = quantity;
        incoming->filled_quantity = 0.0;
        incoming->timestamp = timestamp;
        incoming->status = OrderStatus::NEW;

        size_t initial_trades = trades_buffer_.size();

        // 1. Crossing / Matching phase
        while (incoming->remaining_quantity() > 1e-9) {
            if (incoming->side == Side::BUY) {
                int64_t best_ask = order_book_.best_ask_ticks();
                if (best_ask < 0 || best_ask >= (std::numeric_limits<int64_t>::max() / 2)) break;
                if (incoming->order_type != OrderType::MARKET && incoming->price_ticks < best_ask) {
                    break;
                }

                PriceLevelQueue* level = order_book_.get_level(Side::SELL, best_ask);
                if (!level || level->is_empty()) {
                    order_book_.on_level_emptied(Side::SELL, best_ask);
                    continue;
                }

                match_against_level(incoming, level, best_ask);

                if (level->is_empty()) {
                    order_book_.on_level_emptied(Side::SELL, best_ask);
                } else {
                    break;
                }
            } else {
                int64_t best_bid = order_book_.best_bid_ticks();
                if (best_bid < 0) break;
                if (incoming->order_type != OrderType::MARKET && incoming->price_ticks > best_bid) {
                    break;
                }

                PriceLevelQueue* level = order_book_.get_level(Side::BUY, best_bid);
                if (!level || level->is_empty()) {
                    order_book_.on_level_emptied(Side::BUY, best_bid);
                    continue;
                }

                match_against_level(incoming, level, best_bid);

                if (level->is_empty()) {
                    order_book_.on_level_emptied(Side::BUY, best_bid);
                } else {
                    break;
                }
            }
        }

        // 2. Resting order placement
        if (incoming->remaining_quantity() > 1e-9) {
            if (incoming->order_type == OrderType::MARKET || incoming->order_type == OrderType::IOC) {
                incoming->status = (incoming->filled_quantity > 0.0) 
                    ? OrderStatus::PARTIALLY_FILLED 
                    : OrderStatus::CANCELED;
                pool_.deallocate(incoming);
            } else {
                order_book_.insert_order(incoming);
            }
        } else {
            incoming->status = OrderStatus::FILLED;
            pool_.deallocate(incoming);
        }

        return trades_buffer_.size() - initial_trades;
    }

    inline bool cancel_order_fast(uint32_t order_id_num) noexcept {
        Order* order = order_book_.remove_order(order_id_num);
        if (order) {
            order->status = OrderStatus::CANCELED;
            pool_.deallocate(order);
            return true;
        }
        return false;
    }

    inline bool modify_order_fast(uint32_t order_id_num, double new_quantity, int64_t new_price_ticks) noexcept {
        Order* existing = order_book_.find_order(order_id_num);
        if (!existing) return false;

        if (new_price_ticks != existing->price_ticks || new_quantity > existing->quantity) {
            // Priority lost: remove & re-insert
            Order* removed = order_book_.remove_order(order_id_num);
            if (!removed) return false;
            removed->quantity = new_quantity;
            removed->price_ticks = new_price_ticks;
            removed->status = OrderStatus::REPLACED;
            order_book_.insert_order(removed);
            return true;
        } else {
            // Priority preserved: update volume in place
            PriceLevelQueue* level = order_book_.get_level(existing->side, existing->price_ticks);
            if (level) {
                double delta = existing->quantity - new_quantity;
                level->total_volume -= delta;
                if (level->total_volume < 1e-9) level->total_volume = 0.0;
            }
            existing->quantity = new_quantity;
            existing->status = OrderStatus::REPLACED;
            return true;
        }
    }

    inline const std::vector<Trade>& trades() const noexcept { return trades_buffer_; }
    inline void clear_trades() noexcept { trades_buffer_.clear(); }

private:
    inline void match_against_level(Order* incoming, PriceLevelQueue* level, int64_t match_ticks) noexcept {
        while (level->head && incoming->remaining_quantity() > 1e-9) {
            Order* resting = level->head;
            if (__builtin_expect(resting->remaining_quantity() <= 1e-9, 0)) {
                resting->status = OrderStatus::FILLED;
                level->pop_head();
                order_book_.remove_order_index(resting->order_id_num);
                pool_.deallocate(resting);
                continue;
            }

            double match_qty = std::min(incoming->remaining_quantity(), resting->remaining_quantity());
            if (__builtin_expect(match_qty <= 1e-9, 0)) break;

            trade_counter_++;
            last_trade_price_ticks_ = match_ticks;

            if (record_trades_) {
                trades_buffer_.push_back(Trade{
                    trade_counter_,
                    resting->order_id_num,
                    incoming->order_id_num,
                    match_ticks,
                    static_cast<double>(match_ticks) / 10000.0,
                    match_qty,
                    incoming->side,
                    incoming->timestamp
                });
            }

            incoming->filled_quantity += match_qty;
            resting->filled_quantity += match_qty;
            level->total_volume -= match_qty;
            if (level->total_volume < 1e-9) level->total_volume = 0.0;

            if (resting->remaining_quantity() <= 1e-9) {
                resting->status = OrderStatus::FILLED;
                level->pop_head();
                order_book_.remove_order_index(resting->order_id_num);
                pool_.deallocate(resting);
            }
        }
    }

    std::string symbol_;
    FastOrderBook order_book_;
    OrderMemoryPool pool_;
    uint64_t trade_counter_;
    int64_t last_trade_price_ticks_;
    bool record_trades_{true};
    std::vector<Trade> trades_buffer_;
};

} // namespace zerene
