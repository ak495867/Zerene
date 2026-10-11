#include <iostream>
#include <chrono>
#include <vector>
#include <random>
#include <iomanip>
#include "matching_engine.hpp"

using namespace zerene;

int main() {
    constexpr size_t NUM_OPS = 10'000'000;
    std::cout << "[+] Starting ZERENE Ultra C++ Benchmark with " << NUM_OPS << " operations...\n";

    MatchingEngineCore engine("BENCH-USD", 1'000'000);

    // Pre-seed book across 250 price levels on each side
    for (int i = 1; i <= 250; ++i) {
        engine.process_order_fast(1000000 + i, Side::BUY, OrderType::LIMIT, 1'000'000 - i * 5, 1000.0);
        engine.process_order_fast(2000000 + i, Side::SELL, OrderType::LIMIT, 1'000'000 + i * 5, 1000.0);
    }

    std::vector<uint32_t> active_ids;
    active_ids.reserve(50'000);
    for (int i = 1; i <= 250; ++i) {
        active_ids.push_back(1000000 + i);
        active_ids.push_back(2000000 + i);
    }

    // Fast XorShift128+ random generator for maximum speed without PRNG bottleneck
    struct XorShift {
        uint64_t s[2]{0x123456789ULL, 0x987654321ULL};
        inline uint64_t next() noexcept {
            uint64_t s1 = s[0];
            const uint64_t s0 = s[1];
            s[0] = s0;
            s1 ^= s1 << 23;
            s[1] = s1 ^ s0 ^ (s1 >> 18) ^ (s0 >> 5);
            return s[1] + s0;
        }
    } rng;

    size_t limit_count = 0;
    size_t market_count = 0;
    size_t cancel_count = 0;
    size_t modify_count = 0;

    auto t0 = std::chrono::high_resolution_clock::now();

    for (size_t i = 0; i < NUM_OPS; ++i) {
        uint64_t r = rng.next();
        uint32_t op_type = (r % 100);
        Side side = (r & 1) ? Side::BUY : Side::SELL;
        uint32_t oid = static_cast<uint32_t>(i + 1);

        if (op_type < 45) { // 45% Limit orders near inside spread
            limit_count++;
            int64_t offset = static_cast<int64_t>((r >> 8) % 100) - 50; // ±50 ticks
            int64_t price_ticks = 1'000'000 + offset;
            engine.process_order_fast(oid, side, OrderType::LIMIT, price_ticks, 10.0);
            if (active_ids.size() < 50'000) {
                active_ids.push_back(oid);
            } else {
                active_ids[(r >> 16) % 50'000] = oid;
            }
        } else if (op_type < 70) { // 25% Market sweeps
            market_count++;
            engine.process_order_fast(oid, side, OrderType::MARKET, 0, 5.0);
        } else if (op_type < 90 && !active_ids.empty()) { // 20% Cancels
            cancel_count++;
            uint32_t target_id = active_ids[(r >> 24) % active_ids.size()];
            engine.cancel_order_fast(target_id);
        } else if (!active_ids.empty()) { // 10% Modifies
            modify_count++;
            uint32_t target_id = active_ids[(r >> 32) % active_ids.size()];
            int64_t new_price = 1'000'000 + (static_cast<int64_t>((r >> 40) % 20) - 10);
            engine.modify_order_fast(target_id, 20.0, new_price);
        }

        if (__builtin_expect((i + 1) % 1'000'000 == 0, 0)) {
            auto now = std::chrono::high_resolution_clock::now();
            double elapsed = std::chrono::duration<double>(now - t0).count();
            std::cout << "  [bench] Completed " << (i + 1) / 1'000'000 << "M / 10M ops (" 
                      << std::fixed << std::setprecision(2) << ((i + 1) / elapsed / 1'000'000.0) 
                      << " M ops/sec, trades: " << engine.trade_count() << ")...\n";
        }
    }

    auto t1 = std::chrono::high_resolution_clock::now();
    double elapsed_sec = std::chrono::duration<double>(t1 - t0).count();
    double ops_per_sec = static_cast<double>(NUM_OPS) / elapsed_sec;

    std::cout << "\n======================================================\n";
    std::cout << "          ZERENE ULTRA C++ CORE BENCHMARK REPORT      \n";
    std::cout << "======================================================\n";
    std::cout << " Total Operations:      " << NUM_OPS << "\n";
    std::cout << " Elapsed Time:          " << std::fixed << std::setprecision(4) << elapsed_sec << " seconds\n";
    std::cout << " Throughput:            " << std::fixed << std::setprecision(2) << ops_per_sec << " ops/sec\n";
    std::cout << " Millions of Ops/Sec:   " << std::fixed << std::setprecision(2) << (ops_per_sec / 1'000'000.0) << " M ops/sec\n";
    std::cout << " Total Trades Matched:  " << engine.trade_count() << "\n";
    std::cout << " Best Bid Ticks:        " << engine.book().best_bid_ticks() << " ($" << (engine.book().best_bid_ticks() / 10000.0) << ")\n";
    std::cout << " Best Ask Ticks:        " << engine.book().best_ask_ticks() << " ($" << (engine.book().best_ask_ticks() / 10000.0) << ")\n";
    std::cout << "======================================================\n";

    return 0;
}
