#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <chrono>
#include <iostream>
#include <iomanip>
#include <vector>
#include "matching_engine.hpp"

namespace py = pybind11;
using namespace zerene;

struct CppBenchmarkResult {
    double elapsed_seconds;
    double orders_per_second;
    uint64_t total_operations;
    uint64_t total_trades;
    int64_t best_bid_ticks;
    int64_t best_ask_ticks;
    uint64_t limit_count;
    uint64_t market_count;
    uint64_t cancel_count;
    uint64_t modify_count;
};

inline CppBenchmarkResult run_cpp_benchmark(
    const std::string& symbol,
    uint64_t num_ops,
    uint64_t seed,
    bool verbose = true
) {
    MatchingEngineCore engine(symbol, 1'000'000);
    engine.set_record_trades(false);

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

    // Fast XorShift128+ random generator
    struct XorShift {
        uint64_t s[2];
        inline uint64_t next() noexcept {
            uint64_t s1 = s[0];
            const uint64_t s0 = s[1];
            s[0] = s0;
            s1 ^= s1 << 23;
            s[1] = s1 ^ s0 ^ (s1 >> 18) ^ (s0 >> 5);
            return s[1] + s0;
        }
    } rng;
    rng.s[0] = seed ? seed : 0x123456789ULL;
    rng.s[1] = (seed ^ 0x9E3779B97F4A7C15ULL) ? (seed ^ 0x9E3779B97F4A7C15ULL) : 0x987654321ULL;

    uint64_t limit_count = 0;
    uint64_t market_count = 0;
    uint64_t cancel_count = 0;
    uint64_t modify_count = 0;

    auto t0 = std::chrono::high_resolution_clock::now();

    for (uint64_t i = 0; i < num_ops; ++i) {
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

        if (verbose && __builtin_expect((i + 1) % 2'000'000 == 0, 0)) {
            auto now = std::chrono::high_resolution_clock::now();
            double elapsed = std::chrono::duration<double>(now - t0).count();
            std::cout << "  [bench-cpp] " << (i + 1) / 1'000'000 << "M / "
                      << num_ops / 1'000'000 << "M ops | "
                      << std::fixed << std::setprecision(2) << ((i + 1) / elapsed / 1'000'000.0)
                      << " M ops/sec (trades: " << engine.trade_count() << ")...\n";
        }
    }

    auto t1 = std::chrono::high_resolution_clock::now();
    double elapsed_sec = std::chrono::duration<double>(t1 - t0).count();
    double ops_per_sec = static_cast<double>(num_ops) / std::max(1e-9, elapsed_sec);

    return CppBenchmarkResult{
        elapsed_sec,
        ops_per_sec,
        num_ops,
        engine.trade_count(),
        engine.book().best_bid_ticks(),
        engine.book().best_ask_ticks(),
        limit_count,
        market_count,
        cancel_count,
        modify_count
    };
}

PYBIND11_MODULE(zerene_cpp_core, m) {
    m.doc() = "ZERENE Ultra C++ Matching Core (10M+ ops/sec)";

    py::enum_<Side>(m, "Side")
        .value("BUY", Side::BUY)
        .value("SELL", Side::SELL)
        .export_values();

    py::enum_<OrderType>(m, "OrderType")
        .value("LIMIT", OrderType::LIMIT)
        .value("MARKET", OrderType::MARKET)
        .value("IOC", OrderType::IOC)
        .value("FOK", OrderType::FOK)
        .value("POST_ONLY", OrderType::POST_ONLY)
        .export_values();

    py::class_<Trade>(m, "Trade")
        .def_readonly("trade_id", &Trade::trade_id)
        .def_readonly("maker_order_id_num", &Trade::maker_order_id_num)
        .def_readonly("taker_order_id_num", &Trade::taker_order_id_num)
        .def_readonly("price_ticks", &Trade::price_ticks)
        .def_readonly("price", &Trade::price)
        .def_readonly("quantity", &Trade::quantity)
        .def_readonly("aggressor_side", &Trade::aggressor_side)
        .def_readonly("timestamp", &Trade::timestamp);

    py::class_<CppBenchmarkResult>(m, "CppBenchmarkResult")
        .def_readonly("elapsed_seconds", &CppBenchmarkResult::elapsed_seconds)
        .def_readonly("orders_per_second", &CppBenchmarkResult::orders_per_second)
        .def_readonly("total_operations", &CppBenchmarkResult::total_operations)
        .def_readonly("total_trades", &CppBenchmarkResult::total_trades)
        .def_readonly("best_bid_ticks", &CppBenchmarkResult::best_bid_ticks)
        .def_readonly("best_ask_ticks", &CppBenchmarkResult::best_ask_ticks)
        .def_readonly("limit_count", &CppBenchmarkResult::limit_count)
        .def_readonly("market_count", &CppBenchmarkResult::market_count)
        .def_readonly("cancel_count", &CppBenchmarkResult::cancel_count)
        .def_readonly("modify_count", &CppBenchmarkResult::modify_count);

    m.def("run_cpp_benchmark", &run_cpp_benchmark,
          py::arg("symbol") = "BENCH-USD",
          py::arg("num_ops") = 10'000'000,
          py::arg("seed") = 42,
          py::arg("verbose") = true,
          "Execute ultra-fast matching engine benchmark completely in C++ (10M+ ops/sec)");

    py::class_<MatchingEngineCore>(m, "MatchingEngineCore")
        .def(py::init<const std::string&, int64_t>(),
             py::arg("symbol") = "BENCH-USD",
             py::arg("initial_price_ticks") = 1'000'000)
        .def("process_order_fast", &MatchingEngineCore::process_order_fast,
             py::arg("order_id_num"),
             py::arg("side"),
             py::arg("order_type"),
             py::arg("price_ticks"),
             py::arg("quantity"),
             py::arg("timestamp") = 0.0)
        .def("cancel_order_fast", &MatchingEngineCore::cancel_order_fast,
             py::arg("order_id_num"))
        .def("modify_order_fast", &MatchingEngineCore::modify_order_fast,
             py::arg("order_id_num"),
             py::arg("new_quantity"),
             py::arg("new_price_ticks"))
        .def("best_bid_ticks", [](const MatchingEngineCore& self) {
            return self.book().best_bid_ticks();
        })
        .def("best_ask_ticks", [](const MatchingEngineCore& self) {
            return self.book().best_ask_ticks();
        })
        .def("trade_count", &MatchingEngineCore::trade_count)
        .def("order_count", [](const MatchingEngineCore& self) {
            return self.book().order_count();
        })
        .def("clear_trades", &MatchingEngineCore::clear_trades)
        .def("set_record_trades", &MatchingEngineCore::set_record_trades)
        .def("is_recording_trades", &MatchingEngineCore::is_recording_trades);
}
