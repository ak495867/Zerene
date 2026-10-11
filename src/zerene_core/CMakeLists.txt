cmake_minimum_required(VERSION 3.20)
project(zerene_core CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(zerene_bench standalone_bench.cpp)
target_include_directories(zerene_bench PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

if(MSVC)
    target_compile_options(zerene_bench PRIVATE /O2 /std:c++20)
else()
    target_compile_options(zerene_bench PRIVATE -O3 -march=native -Wall -Wextra)
endif()
