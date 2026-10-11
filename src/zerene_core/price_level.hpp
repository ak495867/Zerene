#pragma once

#include "types.hpp"
#include <cstddef>
#include <cassert>

namespace zerene {

class PriceLevelQueue {
public:
    int64_t price_ticks{0};
    double total_volume{0.0};
    uint32_t order_count{0};
    Order* head{nullptr};
    Order* tail{nullptr};

    PriceLevelQueue() = default;

    explicit PriceLevelQueue(int64_t ticks) noexcept
        : price_ticks(ticks), total_volume(0.0), order_count(0), head(nullptr), tail(nullptr) {}

    inline bool is_empty() const noexcept {
        return head == nullptr;
    }

    inline void append(Order* order) noexcept {
        assert(order != nullptr);
        order->prev = tail;
        order->next = nullptr;
        if (tail) {
            tail->next = order;
        } else {
            head = order;
        }
        tail = order;
        total_volume += order->remaining_quantity();
        order_count++;
    }

    inline void remove(Order* order) noexcept {
        assert(order != nullptr);
        if (order->prev) {
            order->prev->next = order->next;
        } else {
            head = order->next;
        }

        if (order->next) {
            order->next->prev = order->prev;
        } else {
            tail = order->prev;
        }

        total_volume -= order->remaining_quantity();
        if (total_volume < 1e-9) total_volume = 0.0;
        order_count--;
        order->prev = nullptr;
        order->next = nullptr;
    }

    inline Order* pop_head() noexcept {
        if (!head) return nullptr;
        Order* order = head;
        head = head->next;
        if (head) {
            head->prev = nullptr;
        } else {
            tail = nullptr;
        }
        total_volume -= order->remaining_quantity();
        if (total_volume < 1e-9) total_volume = 0.0;
        order_count--;
        order->prev = nullptr;
        order->next = nullptr;
        return order;
    }
};

} // namespace zerene
