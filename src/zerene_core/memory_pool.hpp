#pragma once

#include "types.hpp"
#include <vector>
#include <cassert>

namespace zerene {

class OrderMemoryPool {
public:
    explicit OrderMemoryPool(size_t initial_capacity = 250'000) {
        reserve(initial_capacity);
    }

    ~OrderMemoryPool() {
        for (auto* chunk : chunks_) {
            delete[] chunk;
        }
    }

    OrderMemoryPool(const OrderMemoryPool&) = delete;
    OrderMemoryPool& operator=(const OrderMemoryPool&) = delete;

    inline Order* allocate() noexcept {
        if (__builtin_expect(!free_list_, 0)) {
            expand();
        }
        Order* order = free_list_;
        free_list_ = free_list_->next;
        order->prev = nullptr;
        order->next = nullptr;
        return order;
    }

    inline void deallocate(Order* order) noexcept {
        assert(order != nullptr);
        order->next = free_list_;
        order->prev = nullptr;
        free_list_ = order;
    }

    void reset() noexcept {
        // Re-thread entire free list from all chunks
        free_list_ = nullptr;
        for (auto* chunk : chunks_) {
            for (size_t i = 0; i < chunk_size_; ++i) {
                chunk[i].next = free_list_;
                chunk[i].prev = nullptr;
                free_list_ = &chunk[i];
            }
        }
    }

private:
    void reserve(size_t capacity) {
        chunk_size_ = capacity;
        expand();
    }

    void expand() {
        Order* new_chunk = new Order[chunk_size_];
        chunks_.push_back(new_chunk);
        for (size_t i = 0; i < chunk_size_; ++i) {
            new_chunk[i].next = free_list_;
            new_chunk[i].prev = nullptr;
            free_list_ = &new_chunk[i];
        }
    }

    size_t chunk_size_{250'000};
    Order* free_list_{nullptr};
    std::vector<Order*> chunks_;
};

} // namespace zerene
