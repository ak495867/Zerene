#pragma once

#include "types.hpp"
#include "price_level.hpp"
#include <map>
#include <vector>
#include <unordered_map>
#include <algorithm>
#include <optional>
#include <iostream>

namespace zerene {

class FastOrderBook {
public:
    static constexpr size_t ARENA_SIZE = 65536; // ±32768 ticks around reference anchor

    FastOrderBook(int64_t anchor_ticks = 1'000'000) 
        : anchor_ticks_(anchor_ticks),
          best_bid_ticks_(-1),
          best_ask_ticks_(std::numeric_limits<int64_t>::max())
    {
        order_index_.reserve(1'000'000);
        bid_arena_.resize(ARENA_SIZE);
        ask_arena_.resize(ARENA_SIZE);
        for (size_t i = 0; i < ARENA_SIZE; ++i) {
            int64_t t = arena_idx_to_ticks(i);
            bid_arena_[i] = PriceLevelQueue(t);
            ask_arena_[i] = PriceLevelQueue(t);
        }
    }

    inline int64_t best_bid_ticks() const noexcept {
        return (best_bid_ticks_ >= 0) ? best_bid_ticks_ : -1;
    }

    inline int64_t best_ask_ticks() const noexcept {
        return (best_ask_ticks_ < std::numeric_limits<int64_t>::max()) ? best_ask_ticks_ : -1;
    }

    inline bool insert_order(Order* order) noexcept {
        int64_t ticks = order->price_ticks;
        size_t idx = ticks_to_arena_idx(ticks);

        if (__builtin_expect(idx < ARENA_SIZE, 1)) {
            if (order->side == Side::BUY) {
                bid_arena_[idx].append(order);
                if (ticks > best_bid_ticks_) {
                    best_bid_ticks_ = ticks;
                }
            } else {
                ask_arena_[idx].append(order);
                if (ticks < best_ask_ticks_) {
                    best_ask_ticks_ = ticks;
                }
            }
            order_index_[order->order_id_num] = order;
            return true;
        }

        // Fallback for extreme outlier ticks
        return insert_outlier(order);
    }

    inline Order* remove_order(uint32_t order_id_num) noexcept {
        auto it = order_index_.find(order_id_num);
        if (__builtin_expect(it == order_index_.end(), 0)) {
            return nullptr;
        }

        Order* order = it->second;
        order_index_.erase(it);

        int64_t ticks = order->price_ticks;
        size_t idx = ticks_to_arena_idx(ticks);

        if (__builtin_expect(idx < ARENA_SIZE, 1)) {
            if (order->side == Side::BUY) {
                bid_arena_[idx].remove(order);
                if (ticks == best_bid_ticks_ && bid_arena_[idx].is_empty()) {
                    update_best_bid();
                }
            } else {
                ask_arena_[idx].remove(order);
                if (ticks == best_ask_ticks_ && ask_arena_[idx].is_empty()) {
                    update_best_ask();
                }
            }
        } else {
            remove_outlier(order);
        }

        return order;
    }

    inline PriceLevelQueue* get_level(Side side, int64_t ticks) noexcept {
        size_t idx = ticks_to_arena_idx(ticks);
        if (__builtin_expect(idx < ARENA_SIZE, 1)) {
            return (side == Side::BUY) ? &bid_arena_[idx] : &ask_arena_[idx];
        }
        return get_outlier_level(side, ticks);
    }

    inline void on_level_emptied(Side side, int64_t ticks) noexcept {
        if (side == Side::BUY) {
            if (ticks == best_bid_ticks_) {
                update_best_bid();
            }
        } else {
            if (ticks == best_ask_ticks_) {
                update_best_ask();
            }
        }
    }

    inline Order* find_order(uint32_t order_id_num) const noexcept {
        auto it = order_index_.find(order_id_num);
        return (it != order_index_.end()) ? it->second : nullptr;
    }

    inline void remove_order_index(uint32_t order_id_num) noexcept {
        order_index_.erase(order_id_num);
    }

    inline size_t order_count() const noexcept {
        return order_index_.size();
    }

private:
    inline size_t ticks_to_arena_idx(int64_t ticks) const noexcept {
        int64_t min_tick = anchor_ticks_ - (static_cast<int64_t>(ARENA_SIZE) / 2);
        int64_t max_tick = min_tick + static_cast<int64_t>(ARENA_SIZE) - 1;
        if (ticks < min_tick || ticks > max_tick) {
            return static_cast<size_t>(-1);
        }
        return static_cast<size_t>(ticks - min_tick);
    }

    inline int64_t arena_idx_to_ticks(size_t idx) const noexcept {
        return (anchor_ticks_ - (ARENA_SIZE / 2)) + static_cast<int64_t>(idx);
    }

    void update_best_bid() noexcept {
        if (best_bid_ticks_ < 0) return;
        size_t start_idx = ticks_to_arena_idx(best_bid_ticks_);
        if (start_idx < ARENA_SIZE) {
            for (int64_t i = static_cast<int64_t>(start_idx); i >= 0; --i) {
                if (!bid_arena_[i].is_empty()) {
                    best_bid_ticks_ = arena_idx_to_ticks(i);
                    return;
                }
            }
        }
        // If not found in arena, scan outlier map
        if (!outlier_bids_.empty()) {
            best_bid_ticks_ = outlier_bids_.rbegin()->first;
        } else {
            best_bid_ticks_ = -1;
        }
    }

    void update_best_ask() noexcept {
        if (best_ask_ticks_ >= std::numeric_limits<int64_t>::max()) return;
        size_t start_idx = ticks_to_arena_idx(best_ask_ticks_);
        if (start_idx < ARENA_SIZE) {
            for (size_t i = start_idx; i < ARENA_SIZE; ++i) {
                if (!ask_arena_[i].is_empty()) {
                    best_ask_ticks_ = arena_idx_to_ticks(i);
                    return;
                }
            }
        }
        // If not found in arena, scan outlier map
        if (!outlier_asks_.empty()) {
            best_ask_ticks_ = outlier_asks_.begin()->first;
        } else {
            best_ask_ticks_ = std::numeric_limits<int64_t>::max();
        }
    }

    bool insert_outlier(Order* order) {
        int64_t ticks = order->price_ticks;
        if (order->side == Side::BUY) {
            outlier_bids_[ticks].append(order);
            if (ticks > best_bid_ticks_) best_bid_ticks_ = ticks;
        } else {
            outlier_asks_[ticks].append(order);
            if (ticks < best_ask_ticks_) best_ask_ticks_ = ticks;
        }
        order_index_[order->order_id_num] = order;
        return true;
    }

    void remove_outlier(Order* order) {
        int64_t ticks = order->price_ticks;
        if (order->side == Side::BUY) {
            auto it = outlier_bids_.find(ticks);
            if (it != outlier_bids_.end()) {
                it->second.remove(order);
                if (it->second.is_empty()) {
                    outlier_bids_.erase(it);
                    if (ticks == best_bid_ticks_) update_best_bid();
                }
            }
        } else {
            auto it = outlier_asks_.find(ticks);
            if (it != outlier_asks_.end()) {
                it->second.remove(order);
                if (it->second.is_empty()) {
                    outlier_asks_.erase(it);
                    if (ticks == best_ask_ticks_) update_best_ask();
                }
            }
        }
    }

    PriceLevelQueue* get_outlier_level(Side side, int64_t ticks) {
        if (side == Side::BUY) {
            auto it = outlier_bids_.find(ticks);
            return (it != outlier_bids_.end()) ? &it->second : nullptr;
        } else {
            auto it = outlier_asks_.find(ticks);
            return (it != outlier_asks_.end()) ? &it->second : nullptr;
        }
    }

    int64_t anchor_ticks_;
    int64_t best_bid_ticks_;
    int64_t best_ask_ticks_;
    std::vector<PriceLevelQueue> bid_arena_;
    std::vector<PriceLevelQueue> ask_arena_;
    std::unordered_map<uint32_t, Order*> order_index_;
    std::map<int64_t, PriceLevelQueue> outlier_bids_;
    std::map<int64_t, PriceLevelQueue> outlier_asks_;
};

} // namespace zerene
