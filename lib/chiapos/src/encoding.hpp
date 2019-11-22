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

#ifndef SRC_CPP_ENCODING_HPP_
#define SRC_CPP_ENCODING_HPP_

#include <cmath>
#include <utility>
#include <vector>
#include <queue>
#include <map>
#include <string>

#include "util.hpp"
#include "bits.hpp"

#include "../lib/FiniteStateEntropy/lib/hist.h"
#include "../lib/FiniteStateEntropy/lib/fse.h"

std::map<double, FSE_CTable*> CT_MEMO = {};
std::map<double, FSE_DTable*> DT_MEMO = {};

class Encoding {
 public:
    // Encodes two max k bit values into one max 2k bit value. This can be thought of
    // mapping points in a two dimensional space into a one dimensional space. The benefits
    // of this are that we can store these line points efficiently, by sorting them, and only
    // storing the differences between them. Representing numbers as pairs in two
    // dimensions limits the compression strategies that can be used.
    // The x and y here represent table positions in previous tables.
    static uint128_t SquareToLinePoint(uint64_t x, uint64_t y) {
        // Always makes y < x, which maps the random x, y  points from a square into a
        // triangle. This means less data is needed to represent y, since we know it's less
        // than x.
        if (y > x) {
            std::swap(x, y);
        }
        return ((uint128_t)x * (uint128_t)(x-1)) / 2 + y;
    }

    // Does the opposite as the above function, deterministicaly mapping a one dimensional
    // line point into a 2d pair. However, we do not recover the original ordering here.
    static std::pair<uint64_t, uint64_t> LinePointToSquare(uint128_t index) {
        // Performs a square root, without the use of doubles, to use the precision of the
        // uint128_t.
        uint64_t x = 0;
        for (int8_t i = 63; i >= 0; i--) {
            uint64_t new_x = x + ((uint64_t)1 << i);
            if ((uint128_t)new_x * (new_x - 1) / 2 <= index)
                x = new_x;
        }
        return std::pair<uint64_t, uint64_t>(x, index - (((uint128_t)x * (x-1)) / 2));
    }

    static std::vector<short> CreateNormalizedCount(double R) {
        std::vector<double> dpdf;
        int N = 0;
        double E = 2.718281828459;
        double MIN_PRB_THRESHOLD = 1e-50;
        int TOTAL_QUANTA = 1 << 14;
        double p = 1 - pow((E-1) / E, 1.0 / R);

        while (p > MIN_PRB_THRESHOLD && N < 255) {
            dpdf.push_back(p);
            N++;
            p = (pow(E, 1.0 / R) - 1) * pow(E-1, 1.0 / R);
            p /= pow(E, ((N+1) / R));
        }

        std::vector<short> ans(N, 1);
        auto cmp = [&dpdf, &ans](int i, int j) {
            return dpdf[i] * (log2(ans[i] + 1) - log2(ans[i])) <
                    dpdf[j] * (log2(ans[j] + 1) - log2(ans[j]));
        };

        std::priority_queue<int, vector<int>, decltype(cmp)> pq(cmp);
        for (int i = 0; i < N; ++i)
            pq.push(i);

        for (int todo = 0; todo < TOTAL_QUANTA - N; ++todo) {
            int i = pq.top();
            pq.pop();
            ans[i]++;
            pq.push(i);
        }

        for (int i = 0; i < N; ++i) {
            if (ans[i] == 1) {
                ans[i] = (short)-1;
            }
        }
        return ans;
    }

    static ParkBits ANSEncodeDeltas(std::vector<unsigned char> deltas, double R) {
        if (CT_MEMO.find(R) == CT_MEMO.end()) {
            std::vector<short> nCount = Encoding::CreateNormalizedCount(R);
            unsigned maxSymbolValue = nCount.size() - 1;
            unsigned tableLog = 14;

            if (maxSymbolValue > 255) return ParkBits();
            FSE_CTable *ct = FSE_createCTable(maxSymbolValue, tableLog);
            size_t err = FSE_buildCTable(ct, nCount.data(), maxSymbolValue, tableLog);
            if (FSE_isError(err)) {
                throw FSE_getErrorName(err);
            }
            CT_MEMO[R] = ct;
        }

        void *out = malloc(deltas.size() * 8);
        uint64_t num_bytes = FSE_compress_usingCTable(out, deltas.size() * 8, static_cast<void*>(deltas.data()),
                                                      deltas.size(), CT_MEMO[R]);

        ParkBits res = ParkBits(reinterpret_cast<uint8_t*>(out), num_bytes, num_bytes * 8);
        free(out);
        return res;
    }

    template <typename X>
    static std::vector<uint8_t> ANSDecodeDeltas(X bits, int numDeltas, double R) {
        if (DT_MEMO.find(R) == DT_MEMO.end()) {
            std::vector<short> nCount = Encoding::CreateNormalizedCount(R);
            unsigned maxSymbolValue = nCount.size()-1;
            unsigned tableLog = 14;

            FSE_DTable* dt = FSE_createDTable(tableLog);
            FSE_buildDTable(dt, nCount.data(), maxSymbolValue, tableLog);
            DT_MEMO[R] = dt;
        }

        void* inp = malloc(numDeltas * 8);
        memset(inp, 0x00, numDeltas * 8);
        int inpsize = Util::ByteAlign(bits.GetSize()) / 8;
        void* out = malloc(numDeltas);
        memset(out, 0x00, numDeltas);
        bits.ToBytes(reinterpret_cast<uint8_t*>(inp));

        std::vector<uint8_t> deltas(numDeltas);
        size_t err = FSE_decompress_usingDTable(out, numDeltas, inp, inpsize, DT_MEMO[R]);

        if(FSE_isError(err)) {
            throw FSE_getErrorName(err);
        }

        deltas.assign((unsigned char *) out, ((unsigned char *) out) + numDeltas);

        free(inp);
        free(out);
        for (uint32_t i = 0; i < deltas.size(); i++) {
           if (deltas[i] == 0xff) {
              throw std::string("Bad delta detected");
           }
        }
        return deltas;
    }
};

#endif  // SRC_CPP_ENCODING_HPP_
