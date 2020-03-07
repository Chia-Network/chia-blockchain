// Copyright 2018 Chia Network Inc

// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at

//    http://www.apache.org/licenses/LICENSE-2.0

// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef SRC_CPP_UTIL_HPP_
#define SRC_CPP_UTIL_HPP_

#include <random>
#include <iostream>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>
#include <numeric>
#include <cstring>
#include <utility>
#include <cassert>
#include <chrono>
#include <set>
#include <map>
#include <queue>

// __uint__128_t is only available in 64 bit architectures and on certain
// compilers.
typedef __uint128_t uint128_t;

// Allows printing of uint128_t
std::ostream &operator<<(std::ostream & strm, uint128_t const & v) {
    strm << "uint128(" << (uint64_t)(v >> 64) << ","
         << (uint64_t)(v & (((uint128_t)1 << 64) - 1)) << ")";
    return strm;
}


class Timer {
 public:
    Timer() :
        wall_clock_time_start_(std::chrono::steady_clock::now()),
        cpu_time_start_(clock())
    {
    }

    static char* GetNow()
    {
        auto now = std::chrono::system_clock::now();
        auto tt = std::chrono::system_clock::to_time_t(now);
        return ctime(&tt); // ctime includes newline
    }

    void PrintElapsed(const std::string& name) const {
        auto end = std::chrono::steady_clock::now();
        auto wall_clock_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                             end - this->wall_clock_time_start_).count();

        double cpu_time_ms =  1000.0 * (static_cast<double>(clock()) - this->cpu_time_start_) / CLOCKS_PER_SEC;

        double cpu_ratio = static_cast<int>(10000 * (cpu_time_ms / wall_clock_ms)) / 100.0;

        std::cout << name << " " << (wall_clock_ms / 1000.0)  << " seconds. CPU (" << cpu_ratio << "%) " << Timer::GetNow();
    }

 private:
  std::chrono::time_point<std::chrono::steady_clock> wall_clock_time_start_;
  clock_t cpu_time_start_;
};


class Util {
 public:
    template <typename X>
    static inline X Mod(X i, X n) {
        return (i % n + n) % n;
    }

    static uint32_t ByteAlign(uint32_t num_bits) {
        return (num_bits + (8 - ((num_bits) % 8)) % 8);
    }

    static std::string HexStr(const uint8_t* data, size_t len) {
        std::stringstream s;
        s << std::hex;
        for (size_t i=0; i < len; ++i)
            s << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]);
        s << std::dec;
        return s.str();
    }

    static void WriteZeroesHeap(std::ofstream &file, uint32_t num_bytes) {
        uint8_t* buf = new uint8_t[num_bytes];
        memset(buf, 0, num_bytes);
        file.write(reinterpret_cast<char*>(buf), num_bytes);
        delete[] buf;
    }

    static void WriteZeroesStack(std::ofstream &file, uint32_t num_bytes) {
        uint8_t buf[num_bytes];
        memset(buf, 0, num_bytes);
        file.write(reinterpret_cast<char*>(buf), num_bytes);
    }

    /*
     * Converts a 32 bit int to bytes.
     */
    static void IntToFourBytes(uint8_t* result, const uint32_t input) {
        for (size_t i = 0; i < 4; i++) {
            result[3 - i] = (input >> (i * 8));
        }
    }

    /*
     * Converts a byte array to a 32 bit int.
     */
    static uint32_t FourBytesToInt(const uint8_t* bytes) {
        uint32_t sum = 0;
        for (size_t i = 0; i < 4; i++) {
            uint32_t addend = (uint64_t) bytes[i] << (8 * (3 - i));
            sum += addend;
        }
        return sum;
    }

    /*
     * Converts a byte array to a 64 bit int.
     */
    static uint64_t EightBytesToInt(const uint8_t* bytes) {
        uint64_t sum = 0;
        for (size_t i = 0; i < 8; i++) {
            uint64_t addend = (uint64_t)bytes[i] << (8 * (7 - i));
            sum += addend;
        }
        return sum;
    }

    /*
     * Retrieves the size of an integer, in Bits.
     */
    static uint8_t GetSizeBits(uint128_t value) {
        uint8_t count = 0;
        while (value) {
            count++;
            value >>= 1;
        }
        return count;
    }

    inline static uint64_t SliceInt64FromBytes(const uint8_t* bytes, const uint32_t bytes_len,
                                               const uint32_t start_bit, const uint32_t num_bits) {
        // assert(Util::ByteAlign(start_bit + num_bits) <= bytes_len * 8);
        assert(num_bits <= 64);

        uint64_t sum = 0;
        uint32_t taken_bits = 0;

        uint32_t curr_byte = start_bit/8;
        if (start_bit/8 != (start_bit + num_bits) / 8) {
            sum += bytes[curr_byte] & ((1 << (8 - (start_bit % 8))) - 1);
            taken_bits += (8 - (start_bit % 8));
            ++curr_byte;
        } else {
            // Start and end bits are in the same byte
            return (uint64_t)((bytes[curr_byte] & ((1 << (8 - (start_bit % 8))) - 1))
                              >> (8 - (start_bit % 8) - num_bits));
        }

        const uint32_t end_byte = ((start_bit + num_bits) / 8);
        for (; curr_byte < end_byte; ++curr_byte) {
            sum <<= 8;
            taken_bits += 8;
            sum += bytes[curr_byte];
        }
        if (taken_bits < num_bits) {
            sum <<= (num_bits - taken_bits);
            sum += (bytes[curr_byte] >> (8 - (num_bits - taken_bits)));
        }
        return sum;
    }
    inline static uint128_t SliceInt128FromBytes(const uint8_t* bytes, const uint32_t bytes_len,
                                                 const uint32_t start_bit, const uint32_t num_bits) {
        assert(Util::ByteAlign(start_bit + num_bits) <= bytes_len * 8);
        uint128_t sum = 0;
        uint32_t taken_bits = 0;

        uint32_t curr_byte = start_bit/8;
        if (start_bit/8 != (start_bit + num_bits) / 8) {
            sum += (uint128_t)(bytes[curr_byte] & ((1 << (8 - (start_bit % 8))) - 1));
            taken_bits += (8 - (start_bit % 8));
            ++curr_byte;
        } else {
            // Start and end bits are in the same byte
            return (uint128_t)((bytes[curr_byte] & ((1 << (8 - (start_bit % 8))) - 1))
                              >> (8 - (start_bit % 8) - num_bits));
        }

        const uint32_t end_byte = ((start_bit + num_bits) / 8);
        for (; curr_byte < end_byte; ++curr_byte) {
            sum <<= 8;
            taken_bits += 8;
            sum += bytes[curr_byte];
        }
        if (taken_bits < num_bits) {
            sum <<= (num_bits - taken_bits);
            sum += (uint128_t)(bytes[curr_byte] >> (8 - (num_bits - taken_bits)));
        }
        return sum;
    }

    static void GetRandomBytes(uint8_t* buf, uint32_t num_bytes) {
        std::random_device rd;
        std::mt19937 mt(rd());
        std::uniform_real_distribution<double> dist(0, 256);
        for (uint32_t i = 0; i < num_bytes; i++) {
            buf[i] = static_cast<uint32_t>(floor(dist(mt))) % 256;  // Mod in case we generate the random number 256:
        }
    }

    static uint64_t find_islands(std::vector<std::pair<uint64_t, uint64_t> > edges) {
        std::map<uint64_t, std::vector<uint64_t> > edge_indeces;
        for (uint64_t edge_index = 0; edge_index < edges.size(); edge_index++) {
            edge_indeces[edges[edge_index].first].push_back(edge_index);
            edge_indeces[edges[edge_index].second].push_back(edge_index);
        }
        std::set<uint64_t> visited_nodes;
        std::queue<uint64_t> nodes_to_visit;
        uint64_t num_islands = 0;
        for (auto new_edge : edges) {
            uint64_t old_size = visited_nodes.size();
            if (visited_nodes.find(new_edge.first) == visited_nodes.end()) {
                visited_nodes.insert(new_edge.first);
                nodes_to_visit.push(new_edge.first);
            }
            if (visited_nodes.find(new_edge.second) == visited_nodes.end()) {
                visited_nodes.insert(new_edge.second);
                nodes_to_visit.push(new_edge.second);
            }
            while (!nodes_to_visit.empty()) {
                uint64_t node = nodes_to_visit.front();
                nodes_to_visit.pop();
                for (uint64_t edge_index : edge_indeces[node]) {
                    std::pair<uint64_t, uint64_t> edge = edges[edge_index];
                    if (visited_nodes.find(edge.first) == visited_nodes.end()) {
                        visited_nodes.insert(edge.first);
                        nodes_to_visit.push(edge.first);
                    }
                    if (visited_nodes.find(edge.second) == visited_nodes.end()) {
                        visited_nodes.insert(edge.second);
                        nodes_to_visit.push(edge.second);
                    }
                }
            }
            if (visited_nodes.size() > old_size) {
                num_islands++;
            }
        }
        return num_islands;
    }
};

#endif  // SRC_CPP_UTIL_HPP_
