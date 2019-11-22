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

#ifndef SRC_CPP_POS_CONSTANTS_HPP_
#define SRC_CPP_POS_CONSTANTS_HPP_

#include <numeric>

// Unique plot id which will be used as an AES key, and determines the PoSpace.
const uint32_t kIdLen = 32;

// Must be set high enough to prevent attacks of fast plotting
const uint32_t kMinPlotSize = 15;

// Set at 59 to allow easy use of 64 bit integers
const uint32_t kMaxPlotSize = 59;

// How many f7s per C1 entry, and how many C1 entries per C2 entry
const uint32_t kCheckpoint1Interval = 10000;
const uint32_t kCheckpoint2Interval = 10000;

// F1 evaluations are done in batches of 2^kBatchSizes
const uint32_t kBatchSizes = 8;

// EPP for the final file, the higher this is, the less variability, and lower delta
// Note: if this is increased, ParkVector size must increase
const uint32_t kEntriesPerPark = 2048;

// To store deltas for EPP entries, the average delta must be less than this number of bits
const double kMaxAverageDeltaTable1 = 5.6;
const double kMaxAverageDelta = 3.5;

// C3 entries contain deltas for f7 values, the max average size is the following
const double kC3BitsPerEntry = 2.4;

// The number of bits in the stub is k minus this value
const uint8_t kStubMinusBits = 3;

// The ANS encoding R values for the 7 final plot tables
// Tweaking the R values might allow lowering of the max average deltas, and reducing final
// plot size
const double kRValues[7] = {4.7, 2.75, 2.75, 2.7, 2.6, 2.45};

// The ANS encoding R value for the C3 checkpoint table
const double kC3R = 1.0;

// Plot format (no compatibility guarantees with other formats). If any of the
// above contants are changed, or file format is changed, the version should
// be incremented.
const std::string kFormatDescription = "alpha-v0.4";

// Other constants can be found in pos_constants.hpp
const uint64_t kMemorySize = 2147483648;  // 2^31, or 2GB

// Number of buckets to use for SortOnDisk.
const uint32_t kNumSortBuckets = 16;

struct PlotEntry {
    uint64_t y;
    uint64_t pos;
    uint64_t offset;
    uint128_t left_metadata;  // We only use left_metadata, unless metadata does not
    uint128_t right_metadata; // fit in 128 bits.
};

#endif  // SRC_CPP_POS_CONSTANTS_HPP_
