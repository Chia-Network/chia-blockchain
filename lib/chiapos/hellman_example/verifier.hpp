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

#ifndef SRC_CPP_VERIFIER_HPP_
#define SRC_CPP_VERIFIER_HPP_

#include <vector>
#include <utility>
#include "calculate_bucket.hpp"

class Verifier {
 public:
    // Gets the quality string from a proof in proof ordering. The quality string is two
    // adjacent values, determined by the quality index (1-32), and the proof in plot
    // ordering.
    LargeBits GetQualityString(uint8_t k, LargeBits proof, uint16_t quality_index) {
        // Converts the proof from proof ordering to plot ordering
        for (uint8_t table_index = 1; table_index < 7; table_index++) {
            LargeBits new_proof;
            uint16_t size = k * (1 << (table_index - 1));
            for (uint8_t j = 0; j < (1 << (7 - table_index)); j += 2) {
                LargeBits L = proof.Slice(j * size, (j + 1) * size);
                LargeBits R = proof.Slice((j + 1) * size, (j + 2) * size);
                if (CompareProofBits(L, R, k)) {
                    new_proof += (L + R);
                } else {
                    new_proof += (R + L);
                }
            }
            proof = new_proof;
        }
        // Returns two of the x values, based on the quality index
        return proof.Slice(k * quality_index, k * (quality_index + 2));
    }

    // Validates a proof of space, and returns the quality string if the proof is valid for the given
    // k and challenge. If the proof is invalid, it returns an empty LargeBits().
    LargeBits ValidateProof(uint8_t* id, uint8_t k, uint8_t* challenge, uint8_t* proof_bytes, uint16_t proof_size) {
        LargeBits proof_bits = LargeBits(proof_bytes, proof_size, proof_size * 8);
        if (k * 64 != proof_bits.GetSize()) {
            return LargeBits();
        }
        std::vector<Bits> proof;
        std::vector<Bits> ys;
        std::vector<Bits> metadata;
        F1Calculator f1(k, id);

        // Calculates f1 for each of the given xs. Note that the proof is in proof order.
        for (uint8_t i = 0; i < 64; i++) {
            proof.push_back(Bits(proof_bits.SliceBitsToInt(k * i, k * (i + 1)), k));
            std::pair<Bits, Bits> results = f1.CalculateBucket(proof[i]);
            ys.push_back(std::get<0>(results));
            metadata.push_back(std::get<1>(results));
        }

        // Calculates fx for each table from 2..7, making sure everything matches on the way.
        for (uint8_t depth = 2; depth < 8; depth++) {
            FxCalculator f(k, depth, id);
            std::vector<Bits> new_ys;
            std::vector<Bits> new_metadata;
            for (uint8_t i = 0; i < (1 << (8 - depth)); i += 2) {
                PlotEntry l_plot_entry;
                PlotEntry r_plot_entry;
                l_plot_entry.y = ys[i].GetValue();
                r_plot_entry.y = ys[i+1].GetValue();
                vector<PlotEntry> bucket_L = {l_plot_entry};
                vector<PlotEntry> bucket_R = {r_plot_entry};

                // If there is no match, fails.
                if (f.FindMatches(bucket_L, bucket_R).size() != 1) {
                    return LargeBits();
                }
                std::pair<Bits, Bits> results = f.CalculateBucket(ys[i], ys[i+1],
                                                                  metadata[i], metadata[i+1]);
                new_ys.push_back(std::get<0>(results));
                new_metadata.push_back(std::get<1>(results));
            }
            for (uint8_t i = 0; i < new_ys.size(); i++) {
                if (new_ys[i].GetSize() <= 0) {
                    return LargeBits();
                }
            }

            ys = new_ys;
            metadata = new_metadata;
        }

        Bits challenge_bits = Bits(challenge, 256/8, 256);
        uint16_t quality_index = challenge_bits.Slice(256 - 5).GetValue() << 1;

        // Makes sure the output is equal to the first k bits of the challenge
        if (challenge_bits.Slice(0, k) == ys[0].Slice(0, k)) {
            // Returns quality string, which requires changing proof to plot ordering
            return GetQualityString(k, proof_bits, quality_index);
        } else {
            return LargeBits();
        }
    }

 private:
    // Compares two lists of k values, a and b. a > b iff max(a) > max(b),
    // if there is a tie, the next largest value is compared.
    bool CompareProofBits(LargeBits left, LargeBits right, uint8_t k) {
        uint16_t size = left.GetSize() / k;
        assert(left.GetSize() == right.GetSize());
        for (int16_t i = size - 1; i >= 0; i--) {
            LargeBits left_val = left.Slice(k * i, k * (i + 1));
            LargeBits right_val = right.Slice(k * i, k * (i + 1));
            if (left_val < right_val) {
                return true;
            }
            if (left_val > right_val) {
                return false;
            }
        }
        return false;
    }
};

#endif  // SRC_CPP_VERIFIER_HPP_

