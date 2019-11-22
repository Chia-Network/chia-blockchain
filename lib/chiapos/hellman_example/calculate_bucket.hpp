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

#ifndef SRC_CPP_CALCULATE_BUCKET_HPP_
#define SRC_CPP_CALCULATE_BUCKET_HPP_

#include <stdint.h>
#include <cmath>
#include <vector>
#include <bitset>
#include <iostream>
#include <map>
#include <algorithm>
#include <utility>

#include "util.hpp"
#include "bits.hpp"
#include "aes.hpp"
#include "pos_constants.hpp"


// AES block size
const uint8_t kBlockSizeBits = 128;

// Extra bits of output from the f functions. Instead of being a function from k -> k bits,
// it's a function from k -> k + kExtraBits bits. This allows less collisions in matches.
// Refer to the paper for mathematical motivations.
const uint8_t kExtraBits = 5;

// Convenience variable
const uint8_t kExtraBitsPow = 1 << kExtraBits;

// B and C groups which constitute a bucket, or BC group. These groups determine how
// elements match with each other. Two elements must be in adjacent buckets to match.
const uint16_t kB = 60;
const uint16_t kC = 509;
const uint16_t kBC = kB * kC;

// This (times k) is the length of the metadata that must be kept for each entry. For example,
// for a tbale 4 entry, we must keep 4k additional bits for each entry, which is used to
// compute f5.
std::map<uint8_t, uint8_t> kVectorLens = {
    {2, 1},
    {3, 2},
    {4, 4},
    {5, 4},
    {6, 3},
    {7, 2},
    {8, 0}
};

// Precomputed shifts that specify which entries match with which other entries
// in adjacent buckets.
uint16_t matching_shifts_c[2][kC];

// Performs the precomputation of shifts.
void precompute_shifts() {
    for (uint8_t parity = 0; parity < 2; parity++) {
        for (uint16_t r = 0; r < kExtraBitsPow; r++) {
            uint16_t v = (uint16_t)pow((2 * r + parity), 2) % kC;
            matching_shifts_c[parity][r] = v;
        }
    }
}

// Class to evaluate F1
class F1Calculator {
 public:
    inline F1Calculator(uint8_t k, uint8_t* aes_key) {
        this->k_ = k;
        this->aes_key_ = new uint8_t[32];

        // First byte is 1, the index of this table
        this->aes_key_[0] = 1;
        memcpy(this->aes_key_ + 1, aes_key, 31);

        // Loads the key into the global AES context
        aes_load_key(this->aes_key_, 32);

        // Precomputes the shifts, this is only done once
        precompute_shifts();
    }

    inline ~F1Calculator() {
        delete[] this->aes_key_;
    }

    // Disable copying
    F1Calculator(const F1Calculator&) = delete;

    // Reloads the AES key. If another F1 or Fx object is created, this must be called
    // since the AES context is global.
    inline void ReloadKey() {
        aes_load_key(this->aes_key_, 32);
    }

    // Performs one evaluation of the F function on input L of k bits.
    inline Bits CalculateF(const Bits& L) const {
        uint8_t num_output_bits = k_;

        // Calculates the counter that will be AES-encrypted. since k < 128, we can fit several k bit
        // blocks into one AES block.
        Bits counter((L.GetValue() * (uint128_t)num_output_bits) / kBlockSizeBits, kBlockSizeBits);

        // How many bits are before L, in the current block
        uint32_t bits_before_L = (L.GetValue() * (uint128_t)num_output_bits) % kBlockSizeBits;

        // How many bits of L are in the current block (the rest are in the next block)
        const uint8_t bits_of_L = std::min((uint8_t)(kBlockSizeBits - bits_before_L), num_output_bits);

        // True if L is divided into two blocks, and therefore 2 AES encryptions will be performed.
        const bool spans_two_blocks = bits_of_L < num_output_bits;

        uint8_t counter_bytes[kBlockSizeBits/8];
        uint8_t ciphertext_bytes[kBlockSizeBits/8];
        Bits output_bits;

        // This counter is what will be encrypted. This is similar to AES counter mode, but not XORing
        // any data at the end.
        counter.ToBytes(counter_bytes);
        aes256_enc(counter_bytes, ciphertext_bytes);
        Bits ciphertext0(ciphertext_bytes, kBlockSizeBits/8, kBlockSizeBits);

        if (spans_two_blocks) {
            // Performs another encryption if necessary
            ++counter;
            counter.ToBytes(counter_bytes);
            aes256_enc(counter_bytes, ciphertext_bytes);
            Bits ciphertext1(ciphertext_bytes, kBlockSizeBits/8, kBlockSizeBits);
            output_bits = ciphertext0.Slice(bits_before_L) + ciphertext1.Slice(0, num_output_bits - bits_of_L);
        } else {
            output_bits = ciphertext0.Slice(bits_before_L, bits_before_L + num_output_bits);
        }

        // Adds the first few bits of L to the end of the output, production k + kExtraBits of output
        Bits extra_data = L.Slice(0, kExtraBits);
        if (extra_data.GetSize() < kExtraBits) {
            extra_data += Bits(0, kExtraBits - extra_data.GetSize());
        }
        return output_bits + extra_data;
    }

    // Returns an evaluation of F1(L), and the metadata (L) that must be stored to evaluate F2.
    inline std::pair<Bits, Bits> CalculateBucket(const Bits& L) {
        return std::make_pair(CalculateF(L), L);
    }

    // Returns an evaluation of F1(L), and the metadata (L) that must be stored to evaluate F2,
    // for 'number_of_evaluations' adjacent inputs.
    inline std::vector<std::pair<Bits, Bits> > CalculateBuckets(const Bits& start_L, uint64_t number_of_evaluations) {
        uint8_t num_output_bits = k_;

        uint64_t two_to_the_k = (uint64_t)1 << k_;
        if (start_L.GetValue() + number_of_evaluations > two_to_the_k) {
            throw "Evaluation out of range";
        }
        // Counter for the first input
        uint64_t counter = (start_L.GetValue() * (uint128_t)num_output_bits) / kBlockSizeBits;
        // Counter for the last input
        uint64_t counter_end = ((start_L.GetValue() + (uint128_t)number_of_evaluations + 1) * num_output_bits)
                               / kBlockSizeBits;

        std::vector<Bits> blocks;
        uint64_t L = (counter * kBlockSizeBits) / num_output_bits;
        uint8_t counter_bytes[kBlockSizeBits/8];
        uint8_t ciphertext_bytes[kBlockSizeBits/8];

        // Evaluates the AES for each block
        while (counter <= counter_end) {
            Bits counter_bits(counter, kBlockSizeBits);
            counter_bits.ToBytes(counter_bytes);
            aes256_enc(counter_bytes, ciphertext_bytes);
            Bits ciphertext(ciphertext_bytes, kBlockSizeBits/8, kBlockSizeBits);
            blocks.push_back(std::move(ciphertext));
            ++counter;
        }

        std::vector<std::pair<Bits, Bits>> results;
        uint64_t block_number = 0;
        uint8_t start_bit = (start_L.GetValue() * (uint128_t)num_output_bits) % kBlockSizeBits;

        // For each of the inputs, grabs the correct slice from the encrypted data.
        for (L = start_L.GetValue(); L < start_L.GetValue() + number_of_evaluations; L++) {
            Bits L_bits = Bits(L, k_);

            // Takes the first kExtraBits bits from the input, and adds zeroes if it's not enough
            Bits extra_data = L_bits.Slice(0, kExtraBits);
            if (extra_data.GetSize() < kExtraBits) {
                extra_data = extra_data + Bits(0, kExtraBits - extra_data.GetSize());
            }

            if (start_bit + num_output_bits < kBlockSizeBits) {
                // Everything can be sliced from the current block
                results.push_back(std::make_pair(blocks[block_number].Slice(start_bit, start_bit + num_output_bits)
                                                  + extra_data, L_bits));
            } else {
                // Must move forward one block
                Bits left = blocks[block_number].Slice(start_bit);
                Bits right = blocks[block_number + 1].Slice(0, num_output_bits - (kBlockSizeBits - start_bit));
                results.push_back(std::make_pair(left + right + extra_data, L_bits));
                ++block_number;
            }
            // Start bit of the output slice in the current block
            start_bit = (start_bit + num_output_bits) % kBlockSizeBits;
        }
        return results;
    }

 private:
    // Size of the plot
    uint8_t k_;

    // 32 byte AES key
    uint8_t* aes_key_;
};

// Class to evaluate F2 .. F7.
class FxCalculator {
 public:
    inline FxCalculator(uint8_t k, uint8_t table_index, uint8_t* aes_key) {
        this->k_ = k;
        this->aes_key_ = new uint8_t[32];
        this->table_index_ = table_index;
        this->length_ = kVectorLens[table_index] * k;


        // First byte is the index of the table
        this->aes_key_[0] = table_index;
        memcpy(this->aes_key_ + 1, aes_key, 15);

        // Loads the AES key into the global AES context. It is 16 bytes since AES128 is used
        // for these f functions (as opposed to f1, which uses a 32 byte key). Note that, however,
        // block sizes are still 128 bits (32 bytes).
        aes_load_key(this->aes_key_, 16);

        // One time precomputation of the shifts
        precompute_shifts();

        // Preallocates vector to be used for matching
        for (uint16_t i = 0; i < kC; i++) {
            std::vector<uint16_t> new_vec;
            this->R_positions.push_back(new_vec);
            this->R_bids.push_back(new_vec);
        }
    }

    inline ~FxCalculator() {
        delete[] this->aes_key_;
    }

    // Disable copying
    FxCalculator(const FxCalculator&) = delete;

    inline void ReloadKey() {
        aes_load_key(this->aes_key_, 16);
    }

    // Performs one evaluation of the f function, whose input is divided into 3 pieces of at
    // most 128 bits each.
    inline Bits CalculateF(const Bits& La, const Bits& Lb, const Bits& Ra, const Bits& Rb) {
        assert(La.GetSize() + Lb.GetSize() == Ra.GetSize() + Rb.GetSize() && La.GetSize() + Lb.GetSize() == length_);

        memset(this->block_1, 0, kBlockSizeBits/8);
        memset(this->block_2, 0, kBlockSizeBits/8);
        memset(this->block_3, 0, kBlockSizeBits/8);
        memset(this->block_3, 0, kBlockSizeBits/8);

        if (length_ * 2 <= kBlockSizeBits) {
            (La + Ra).ToBytes(block_1);
            aes128_enc(this->block_1, this->ciphertext);
        } else if (length_ * 2 <= 2 * kBlockSizeBits) {
            La.ToBytes(this->block_1);
            Ra.ToBytes(this->block_2);
            aes128_2b(this->block_1, this->block_2, this->ciphertext);
        } else if (length_ * 2 <= 3 * kBlockSizeBits) {
            La.ToBytes(this->block_1);
            Ra.ToBytes(this->block_2);
            (Lb + Rb).ToBytes(this->block_3);
            aes128_3b(this->block_1, this->block_2, this->block_3, this->ciphertext);
        } else {
            assert(length_ * 2 <= 4 * kBlockSizeBits);
            La.ToBytes(this->block_1);
            Lb.ToBytes(this->block_2);
            Ra.ToBytes(this->block_3);
            Rb.ToBytes(this->block_4);
            aes128_4b(this->block_1, this->block_2, this->block_3, this->block_4, this->ciphertext);
        }

        return Bits(ciphertext, kBlockSizeBits/8, kBlockSizeBits).Slice(0, k_ + kExtraBits);
    }

    // Composes two metadatas L and R, into a metadata for the next table.
    inline Bits Compose(const Bits& L, const Bits& R) {
        switch (table_index_) {
            case 2:
            case 3:
                return L + R;
            case 4:
                return L ^ R;
            case 5:
                assert(length_ % 4 == 0);
                return (L ^ R).Slice(0, length_*3/4);
            case 6:
                assert(length_ % 3 == 0);
                return (L ^ R).Slice(0, length_*2/3);
            default:
                return Bits();
        }
    }

    // Returns an evaluation of F_i(L), and the metadata (L) that must be stored to evaluate F_i+1.
    inline std::pair<Bits, Bits> CalculateBucket(const Bits& y1, const Bits& y2, const Bits& L, const Bits& R, bool check = false) {
        // y1 is xored into the result. This ensures that we have some cryptographic "randomness"
        // encoded into each f function, since f1 output y is the results of an AES256 encryption.
        // All other f functions apart from f1 don't use AES256, they use 2 round AES128.
        if (check) {
            std::vector<PlotEntry> l_entry, r_entry;
            l_entry = r_entry = {PlotEntry()};
            l_entry[0].y = y1.GetValue();
            r_entry[0].y = y2.GetValue();
            if (FindMatches(l_entry, r_entry).size() == 0)
                return std::make_pair(Bits(), Bits());
        }
        if (L.GetSize() <= kBlockSizeBits) {
            return std::make_pair(CalculateF(L, Bits(), R, Bits()) ^ y1, Compose(L, R));
        } else {
            return std::make_pair(CalculateF(L.Slice(0, kBlockSizeBits),
                                        L.Slice(kBlockSizeBits),
                                        R.Slice(0, kBlockSizeBits),
                                        R.Slice(kBlockSizeBits)) ^ y1,
                                  Compose(L, R));
        }
    }

    // Given two buckets with entries (y values), computes which y values match, and returns a list
    // of the pairs of indeces into bucket_L and bucket_R.
    inline std::vector<std::pair<uint16_t, uint16_t>> FindMatches(const std::vector<PlotEntry>& bucket_L,
                                                                  const std::vector<PlotEntry>& bucket_R) {
        std::vector<std::pair<uint16_t, uint16_t>> matches;
        for (uint16_t i = 0; i < kC; i++) {
            this->R_bids[i].clear();
            this->R_positions[i].clear();
        }
        uint16_t parity = (bucket_L[0].y / kBC) % 2;

        for (uint16_t pos_R = 0; pos_R < bucket_R.size(); pos_R++) {
            R_bids[bucket_R[pos_R].y % kC].push_back((bucket_R[pos_R].y % kBC) / kC);
            R_positions[bucket_R[pos_R].y % kC].push_back(pos_R);
        }

        for (uint16_t pos_L = 0; pos_L < bucket_L.size(); pos_L++) {
            uint16_t yl_bid = (bucket_L[pos_L].y % kBC) / kC;
            uint16_t yl_cid = bucket_L[pos_L].y % kC;
            for (uint8_t m = 0; m < kExtraBitsPow; m++) {
                uint16_t target_bid = (yl_bid + m);
                uint16_t target_cid = yl_cid + matching_shifts_c[parity][m];
                if (target_bid >= kB) {
                    target_bid -= kB;
                }
                if (target_cid >= kC) {
                    target_cid -= kC;
                }

                for (uint32_t i = 0; i < R_bids[target_cid].size(); i++) {
                    uint16_t R_bid = R_bids[target_cid][i];
                    if (target_bid == R_bid) {
                        // uint64_t yl_bucket = bucket_L[pos_L].y / kBC;
                        // assert(yl_bucket == bucket_R[R_positions[target_cid][i]].y / kBC));
                        matches.push_back(std::make_pair(pos_L, R_positions[target_cid][i]));
                    }
                }
            }
        }
        return matches;
    }

 private:
    uint8_t k_;
    uint8_t* aes_key_;
    uint8_t table_index_;
    uint8_t length_;
    uint8_t block_1[kBlockSizeBits/8];
    uint8_t block_2[kBlockSizeBits/8];
    uint8_t block_3[kBlockSizeBits/8];
    uint8_t block_4[kBlockSizeBits/8];
    uint8_t ciphertext[kBlockSizeBits/8];
    std::vector<std::vector<uint16_t> > R_positions;
    std::vector<std::vector<uint16_t> > R_bids;
};

#endif  // SRC_CPP_CALCULATE_BUCKET_HPP_
