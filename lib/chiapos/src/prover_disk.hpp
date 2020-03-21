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

#ifndef SRC_CPP_PROVER_DISK_HPP_
#define SRC_CPP_PROVER_DISK_HPP_

#include <unistd.h>
#include <stdio.h>
#include <math.h>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <utility>
#include <algorithm>    // std::min

#include "util.hpp"
#include "encoding.hpp"
#include "calculate_bucket.hpp"
#include "plotter_disk.hpp"
#include "../lib/include/picosha2.hpp"

// The DiskProver, given a correctly formatted plot file, can efficiently generate valid proofs
// of space, for a given challenge.
class DiskProver {
 public:
    // The costructor opens the file, and reads the contents of the file header. The table pointers
    // will be used to find and seek to all seven tables, at the time of proving.
    explicit DiskProver(std::string filename) : disk_file(filename, std::ios::in | std::ios::binary) {
        if (!disk_file.is_open()) {
            throw std::invalid_argument("Invalid file " + filename);
        }
        this->filename = filename;
        // 19 bytes  - "Proof of Space Plot" (utf-8)
        // 32 bytes  - unique plot id
        // 1 byte    - k
        // 2 bytes   - format description length
        // x bytes   - format description
        // 2 bytes   - memo length
        // x bytes   - memo

        // Skip the top of file text "Proof of Space Plot"
        disk_file.seekg(19);

        disk_file.read(reinterpret_cast<char*>(this->id), kIdLen);

        uint8_t kbuf[1];
        disk_file.read(reinterpret_cast<char*>(kbuf), 1);
        this->k = kbuf[0];

        uint8_t size_buf[2];
        disk_file.read(reinterpret_cast<char*>(size_buf), 2);
        uint32_t format_description_size = Bits(size_buf, 2, 16).GetValue();
        uint8_t* format_description_read = new uint8_t[format_description_size];
        disk_file.read(reinterpret_cast<char*>(format_description_read), format_description_size);
        std::string format_str(reinterpret_cast<char*>(format_description_read));

        // We cannot read a plot with a different format version
        if (format_description_size != kFormatDescription.size() ||
            memcmp(format_description_read, kFormatDescription.data(), format_description_size) !=0) {
            throw std::invalid_argument("Invalid plot file format: " + format_str);
        }

        disk_file.read(reinterpret_cast<char*>(size_buf), 2);
        this->memo_size = Bits(size_buf, 2, 16).GetValue();
        this->memo = new uint8_t[this->memo_size];
        disk_file.read(reinterpret_cast<char*>(this->memo), this->memo_size);

        this->table_begin_pointers = std::vector<uint64_t>(11, 0);
        this->C2 = std::vector<uint64_t>();

        uint8_t pointer_buf[8];
        for (uint8_t i = 1; i < 11; i++) {
            disk_file.read(reinterpret_cast<char*>(pointer_buf), 8);
            this->table_begin_pointers[i] = Util::EightBytesToInt(pointer_buf);
        }

        disk_file.seekg(table_begin_pointers[9]);

        // The list of C2 entries is small enough to keep in memory. When proving, we can
        // read from disk the C1 and C3 entries.
        uint8_t c2_size = (Util::ByteAlign(k) / 8);
        uint8_t* c2_buf = new uint8_t[c2_size];
        for (uint i = 0; i < floor((table_begin_pointers[10] -
                                    table_begin_pointers[9]) /
                                    c2_size) - 1; i++) {
            disk_file.read(reinterpret_cast<char*>(c2_buf), c2_size);
            this->C2.push_back(Bits(c2_buf, c2_size, c2_size*8).Slice(0, k).GetValue());
        }

        delete[] c2_buf;
        delete[] format_description_read;
    }

    ~DiskProver() {
        this->disk_file.close();
        delete[] this->memo;
    }

    void GetMemo(uint8_t* buffer) {
        memcpy(buffer, memo, this->memo_size);
    }

    uint32_t GetMemoSize() const noexcept {
        return this->memo_size;
    }

    void GetId(uint8_t* buffer) {
        memcpy(buffer, id, kIdLen);
    }

    std::string GetFilename() const noexcept {
        return filename;
    }

    uint8_t GetSize() const noexcept {
        return k;
    }

    // Given a challenge, returns a quality string, which is sha256(challenge + 2 adjecent x values),
    // from the 64 value proof. Note that this is more efficient than fetching all
    // 64 x values, which are in different parts of the disk.
    std::vector<LargeBits> GetQualitiesForChallenge(const uint8_t* challenge) {
        // This tells us how many f7 outputs (and therefore proofs) we have for this
        // challenge. The expected value is one proof.
        std::vector<uint64_t> p7_entries = GetP7Entries(challenge);

        if (p7_entries.size() == 0) {
            disk_file.clear();
            disk_file.sync();
            return std::vector<LargeBits>();
        }

        std::vector<LargeBits> qualities;
        // The last 5 bits of the challenge determine which route we take to get to
        // our two x values in the leaves.
        LargeBits last_5_bits = LargeBits(challenge, 256/8, 256).Slice(256 - 5);

        for (uint32_t i = 0; i < p7_entries.size(); i++) {
            uint64_t position = p7_entries[i];
            // This inner loop goes from table 6 to table 1, getting the two backpointers,
            // and following one of them.
            for (uint8_t table_index = 6; table_index > 1; table_index--) {
                uint128_t line_point = ReadLinePoint(table_index, position);

                auto xy = Encoding::LinePointToSquare(line_point);
                assert(xy.first >= xy.second);

                if (last_5_bits.Slice(7 - table_index - 1, 7 - table_index).GetValue() == 0) {
                    position = xy.second;
                } else {
                    position = xy.first;
                }
            }
            uint128_t new_line_point = ReadLinePoint(1, position);
            auto x1x2 = Encoding::LinePointToSquare(new_line_point);

            // The final two x values (which are stored in the same location) are hashed
            vector<unsigned char> hash_input(32 + Util::ByteAlign(2 * k) / 8, 0);
            memcpy(hash_input.data(), challenge, 32);
            (LargeBits(x1x2.second, k) + LargeBits(x1x2.first, k)).ToBytes(hash_input.data() + 32);
            vector<unsigned char> hash(picosha2::k_digest_size);
            picosha2::hash256(hash_input.begin(), hash_input.end(), hash.begin(), hash.end());
            qualities.push_back(LargeBits(hash.data(), 32, 256));
        }
        disk_file.clear();
        disk_file.sync();
        return qualities;
    }

    // Given a challenge, and an index, returns a proof of space. This assumes GetQualities was
    // called, and there are actually proofs present. The index represents which proof to fetch,
    // if there are multiple.
    LargeBits GetFullProof(const uint8_t* challenge, uint32_t index) {
        std::vector<uint64_t> p7_entries = GetP7Entries(challenge);
        if (p7_entries.size() == 0 || index >= p7_entries.size()) {
            disk_file.clear();
            disk_file.sync();
            throw std::logic_error("No proof of space for this challenge");
        }

        // Gets the 64 leaf x values, concatenated together into a k*64 bit string.
        std::vector<Bits> xs = GetInputs(p7_entries[index], 6);

        // Sorts them according to proof ordering, where
        // f1(x0) m= f1(x1), f2(x0, x1) m= f2(x2, x3), etc. On disk, they are not stored in
        // proof ordering, they're stored in plot ordering, due to the sorting in the Compress phase.
        std::vector<LargeBits> xs_sorted = ReorderProof(xs);
        LargeBits full_proof;
        for (auto x : xs_sorted) {
            full_proof += x;
        }
        disk_file.clear();
        disk_file.sync();
        return full_proof;
    }

 private:
    ifstream disk_file;
    std::string filename;
    uint32_t memo_size;
    uint8_t *memo;
    uint8_t id[kIdLen];  // Unique plot id
    uint8_t k;
    std::vector<uint64_t> table_begin_pointers;
    std::vector<uint64_t> C2;

    // Reads exactly one line point (pair of two k bit back-pointers) from the given table.
    // The entry at index "position" is read. First, the park index is calculated, then
    // the park is read, and finally, entry deltas are added up to the position that we
    // are looking for.
    uint128_t ReadLinePoint(uint8_t table_index, uint64_t position) {
        uint64_t park_index = floor(position / kEntriesPerPark);
        uint32_t park_size_bits = DiskPlotter::CalculateParkSize(k, table_index) * 8;
        disk_file.seekg(table_begin_pointers[table_index] + (park_size_bits / 8) * park_index);

        // This is the checkpoint at the beginning of the park
        uint16_t line_point_size_bits = DiskPlotter::CalculateLinePointSize(k) * 8;
        uint8_t * line_point_bin = new uint8_t[line_point_size_bits / 8];
        disk_file.read(reinterpret_cast<char*>(line_point_bin), line_point_size_bits / 8);
        uint128_t line_point = Bits(line_point_bin, line_point_size_bits / 8, line_point_size_bits)
                            .Slice(0, k * 2)
                            .GetValue();

        // Reads EPP stubs
        uint32_t stubs_size_bits = DiskPlotter::CalculateStubsSize(k) * 8;
        uint8_t* stubs_bin = new uint8_t[stubs_size_bits / 8 + 1];
        disk_file.read(reinterpret_cast<char*>(stubs_bin), stubs_size_bits / 8);
        std::vector<uint64_t> stubs;
        stubs.push_back(0);

        for (uint32_t i = 0; i < kEntriesPerPark - 1; i++) {
            ParkBits stubs_section = ParkBits(stubs_bin + (i*(k-kStubMinusBits))/8,
                                              (Util::ByteAlign((k-kStubMinusBits))/8) + 1,
                                              (Util::ByteAlign((k-kStubMinusBits))/8 + 1)*8);
            uint8_t start_bit = (i*(k-kStubMinusBits)) % 8;
            stubs.push_back(stubs_section.Slice(start_bit, start_bit + (k-kStubMinusBits)).GetValue());
        }

        // Reads EPP deltas
        uint32_t max_deltas_size_bits = DiskPlotter::CalculateMaxDeltasSize(k, table_index) * 8;
        uint8_t* deltas_bin = new uint8_t[max_deltas_size_bits / 8];

        // Reads the size of the encoded deltas object
        uint16_t encoded_deltas_size = 0;
        disk_file.read(reinterpret_cast<char*>(&encoded_deltas_size), sizeof(uint16_t));

        vector<uint8_t> deltas;

        if(0x8000&encoded_deltas_size)
        {
             // Uncompressed
             encoded_deltas_size&=0x7fff;
             deltas.resize(encoded_deltas_size);
             disk_file.read(reinterpret_cast<char*>(deltas.data()), encoded_deltas_size);
        }
        else
        {
             // Compressed
             disk_file.read(reinterpret_cast<char*>(deltas_bin), encoded_deltas_size);
             ParkBits deltas_park = ParkBits(deltas_bin, encoded_deltas_size, encoded_deltas_size*8);

             // Decodes the deltas
             double R = kRValues[table_index - 1];
             deltas = Encoding::ANSDecodeDeltas(deltas_park, kEntriesPerPark - 1, R);
        }

        deltas.insert(deltas.begin(), 1, 0);

        uint128_t sum_deltas = 0;
        uint128_t sum_stubs = 0;
        for (uint32_t i = 0; i < std::min((uint32_t)(position % kEntriesPerPark) + 1, (uint32_t)deltas.size()); i++) {
            sum_deltas += deltas[i];
            sum_stubs += stubs[i];
        }

        uint128_t big_delta = ((uint128_t)1 << (k-kStubMinusBits)) * sum_deltas + sum_stubs;
        uint128_t final_line_point = line_point + big_delta;

        delete[] line_point_bin;
        delete[] stubs_bin;
        delete[] deltas_bin;

        return final_line_point;
    }

    // Gets the P7 positions of the target f7 entries. Uses the C3 encoded bitmask read from disk.
    // A C3 park is a list of deltas between p7 entries, ANS encoded.
    std::vector<uint64_t> GetP7Positions(uint64_t curr_f7, uint64_t f7, uint64_t curr_p7_pos, uint8_t* bit_mask,
                                         uint16_t encoded_size, uint64_t c1_index) {
        std::vector<uint8_t> deltas = Encoding::ANSDecodeDeltas(LargeBits(bit_mask, encoded_size, encoded_size*8),
                                                                kCheckpoint1Interval, kC3R);
        std::vector<uint64_t> p7_positions;
        for (uint8_t delta : deltas) {
            if (curr_f7 > f7) {
                break;
            }
            curr_f7 += delta;
            curr_p7_pos += 1;

            if (curr_f7 == f7) {
                p7_positions.push_back(curr_p7_pos);
            }

            // In the last park, we might have extra deltas
            if ((int64_t)curr_p7_pos >= (int64_t)((c1_index + 1) * kCheckpoint1Interval) - 1
                || curr_f7 >= (((uint64_t)1) << k)) {
                return p7_positions;
            }
        }
        return p7_positions;
    }

    // Returns P7 table entries (which are positions into table P6), for a given challenge
    std::vector<uint64_t> GetP7Entries(const uint8_t* challenge) {
        if (C2.size() == 0) {
            return std::vector<uint64_t>();
        }
        Bits challenge_bits = Bits(challenge, 256/8, 256);

        // The first k bits determine which f7 matches with the challenge.
        const uint64_t f7 = challenge_bits.Slice(0, k).GetValue();

        int64_t c1_index = 0;
        bool broke = false;
        uint64_t c2_entry_f = 0;
        // Goes through C2 entries until we find the correct C2 checkpoint. We read each entry,
        // comparing it to our target (f7).
        for (uint64_t c2_entry : C2) {
            c2_entry_f = c2_entry;
            if (f7 < c2_entry) {
                // If we passed our target, go back by one.
                c1_index -= kCheckpoint2Interval;
                broke = true;
                break;
            }
            c1_index += kCheckpoint2Interval;
        }

        if (c1_index < 0) {
            return std::vector<uint64_t>();
        }

        if (!broke) {
            // If we didn't break, go back by one, to get the final checkpoint.
            c1_index -= kCheckpoint2Interval;
        }

        uint32_t c1_entry_size = Util::ByteAlign(k) / 8;

        uint8_t* c1_entry_bytes = new uint8_t[c1_entry_size];
        disk_file.seekg(table_begin_pointers[8] + c1_index * Util::ByteAlign(k) / 8);

        uint64_t curr_f7 = c2_entry_f;
        uint64_t prev_f7 = c2_entry_f;
        broke = false;
        // Goes through C2 entries until we find the correct C1 checkpoint.
        for (uint64_t start = 0; start < kCheckpoint1Interval; start ++) {
            disk_file.read(reinterpret_cast<char*>(c1_entry_bytes), c1_entry_size);
            Bits c1_entry = Bits(c1_entry_bytes, Util::ByteAlign(k) / 8, Util::ByteAlign(k));
            uint64_t read_f7 = c1_entry.Slice(0, k).GetValue();

            if (start != 0 && read_f7 == 0) {
                // We have hit the end of the checkpoint list
                break;
            }
            curr_f7 = read_f7;

            if (f7 < curr_f7) {
                // We have passed the number we are looking for, so go back by one
                curr_f7 = prev_f7;
                c1_index -= 1;
                broke = true;
                break;
            }

            c1_index += 1;
            prev_f7 = curr_f7;
        }
        if (!broke)  {
            // We never broke, so go back by one.
            c1_index -= 1;
        }

        uint32_t c3_entry_size = DiskPlotter::CalculateC3Size(k);
        uint8_t* bit_mask = new uint8_t[c3_entry_size];

        // Double entry means that our entries are in more than one checkpoint park.
        bool double_entry = f7 == curr_f7 && c1_index > 0;

        uint64_t next_f7;
        uint8_t encoded_size_buf[2];
        uint16_t encoded_size;
        std::vector<uint64_t> p7_positions;
        int64_t curr_p7_pos = c1_index * kCheckpoint1Interval;

        if (double_entry) {
            // In this case, we read the previous park as well as the current one
            c1_index -= 1;
            uint8_t* c1_entry_bytes = new uint8_t[Util::ByteAlign(k) / 8];
            disk_file.seekg(table_begin_pointers[8] + c1_index * Util::ByteAlign(k) / 8);
            disk_file.read(reinterpret_cast<char*>(c1_entry_bytes), Util::ByteAlign(k) / 8);
            Bits c1_entry_bits = Bits(c1_entry_bytes, Util::ByteAlign(k) / 8, Util::ByteAlign(k));
            next_f7 = curr_f7;
            curr_f7 = c1_entry_bits.Slice(0, k).GetValue();

            disk_file.seekg(table_begin_pointers[10] + c1_index * c3_entry_size);

            disk_file.read(reinterpret_cast<char*>(encoded_size_buf), 2);
            encoded_size = Bits(encoded_size_buf, 2, 16).GetValue();
            disk_file.read(reinterpret_cast<char*>(bit_mask), c3_entry_size - 2);

            p7_positions = GetP7Positions(curr_f7, f7, curr_p7_pos, bit_mask, encoded_size, c1_index);

            disk_file.read(reinterpret_cast<char*>(encoded_size_buf), 2);
            encoded_size = Bits(encoded_size_buf, 2, 16).GetValue();
            disk_file.read(reinterpret_cast<char*>(bit_mask), c3_entry_size - 2);
            delete[] c1_entry_bytes;

            c1_index++;
            curr_p7_pos = c1_index * kCheckpoint1Interval;
            curr_f7 = next_f7;
            auto second_positions = GetP7Positions(next_f7, f7, curr_p7_pos, bit_mask, encoded_size, c1_index);
            p7_positions.insert(p7_positions.end(), second_positions.begin(), second_positions.end());

        } else {
            disk_file.seekg(table_begin_pointers[10] + c1_index * c3_entry_size);
            disk_file.read(reinterpret_cast<char*>(encoded_size_buf), 2);
            encoded_size = Bits(encoded_size_buf, 2, 16).GetValue();
            disk_file.read(reinterpret_cast<char*>(bit_mask), c3_entry_size - 2);

            p7_positions = GetP7Positions(curr_f7, f7, curr_p7_pos, bit_mask, encoded_size, c1_index);
        }

        // p7_positions is a list of all the positions into table P7, where the output is equal to f7.
        // If it's empty, no proofs are present for this f7.
        if (p7_positions.size() == 0) {
            delete[] bit_mask;
            delete[] c1_entry_bytes;
            return std::vector<uint64_t>();
        }

        uint64_t p7_park_size_bytes = Util::ByteAlign((k+1) * kEntriesPerPark)/8;

        std::vector<uint64_t> p7_entries;

        // Given the p7 positions, which are all adjacent, we can read the pos6 values from table P7.
        uint8_t* p7_park_buf = new uint8_t[p7_park_size_bytes];
        uint64_t park_index = (p7_positions[0] == 0 ? 0 : p7_positions[0]) / kEntriesPerPark;
        disk_file.seekg(table_begin_pointers[7] + park_index * p7_park_size_bytes);
        disk_file.read(reinterpret_cast<char*>(p7_park_buf), p7_park_size_bytes);
        ParkBits p7_park = ParkBits(p7_park_buf, p7_park_size_bytes, p7_park_size_bytes*8);
        for (uint64_t i = 0; i < p7_positions[p7_positions.size() - 1] - p7_positions[0] + 1; i++) {
            uint64_t new_park_index = (p7_positions[i]) / kEntriesPerPark;
            if (new_park_index > park_index) {
                disk_file.seekg(table_begin_pointers[7] + new_park_index * p7_park_size_bytes);
                disk_file.read(reinterpret_cast<char*>(p7_park_buf), p7_park_size_bytes);
                p7_park = ParkBits(p7_park_buf, p7_park_size_bytes, p7_park_size_bytes*8);
            }
            uint32_t start_bit_index = (p7_positions[i] % kEntriesPerPark) * (k + 1);

            uint64_t p7_int = p7_park.Slice(start_bit_index, start_bit_index + k + 1).GetValue();
            p7_entries.push_back(p7_int);
        }

        delete[] bit_mask;
        delete[] c1_entry_bytes;
        delete[] p7_park_buf;

        return p7_entries;
    }

    // Changes a proof of space (64 k bit x values) from plot ordering to proof ordering.
    // Proof ordering: x1..x64 s.t.
    //  f1(x1) m= f1(x2) ... f1(x63) m= f1(x64)
    //  f2(C(x1, x2)) m= f2(C(x3, x4)) ... f2(C(x61, x62)) m= f2(C(x63, x64))
    //  ...
    //  f7(C(....)) == challenge
    //
    // Plot ordering: x1..x64 s.t.
    //  f1(x1) m= f1(x2) || f1(x2) m= f1(x1) .....
    //  For all the levels up to f7
    //  AND x1 < x2, x3 < x4
    //     C(x1, x2) < C(x3, x4)
    //     For all comparisons up to f7
    //     Where a < b is defined as:  max(b) > max(a) where a and b are lists of k bit elements
    std::vector<LargeBits> ReorderProof(const std::vector<Bits>& xs_input) const {
        F1Calculator f1(k, id);
        std::vector<std::pair<Bits, Bits> > results;
        LargeBits xs;

        // Calculates f1 for each of the inputs
        for (uint8_t i = 0; i < 64; i++) {
            results.push_back(f1.CalculateBucket(xs_input[i]));
            xs += std::get<1>(results[i]);
        }

        // The plotter calculates f1..f7, and at each level, decides to swap or not swap. Here, we
        // are doing a similar thing, we swap left and right, such that we end up with proof ordering.
        for (uint8_t table_index = 2; table_index < 8; table_index++) {
            LargeBits new_xs;
            // New results will be a list of pairs of (y, metadata), it will decrease in size by 2x
            // at each iteration of the outer loop.
            std::vector<pair<Bits, Bits> > new_results;
            FxCalculator f(k, table_index, id);
            // Iterates through pairs of things, starts with 64 things, then 32, etc, up to 2.
            for (uint8_t i = 0; i < results.size(); i += 2) {
                std::pair<Bits, Bits> new_output;
                // Compares the buckets of both ys, to see which one goes on the left, and which
                // one goes on the right
                if (std::get<0>(results[i]).GetValue() < std::get<0>(results[i+1]).GetValue()) {
                    new_output = f.CalculateBucket(std::get<0>(results[i]), std::get<0>(results[i+1]),
                                                   std::get<1>(results[i]), std::get<1>(results[i+1]));
                    uint64_t start = (uint64_t) k * i * ((uint64_t)1 << (table_index - 2));
                    uint64_t end = (uint64_t) k * (i + 2) * ((uint64_t)1 << (table_index - 2));
                    new_xs += xs.Slice(start, end);
                } else {
                    // Here we switch the left and the right
                    new_output = f.CalculateBucket(std::get<0>(results[i+1]), std::get<0>(results[i]),
                                                   std::get<1>(results[i+1]), std::get<1>(results[i]));
                    uint64_t start = (uint64_t) k * i * ((uint64_t)1 << (table_index - 2));
                    uint64_t start2 = (uint64_t) k * (i + 1) * ((uint64_t)1 << (table_index - 2));
                    uint64_t end = (uint64_t) k * (i + 2) * ((uint64_t)1 << (table_index - 2));
                    new_xs += (xs.Slice(start2, end) + xs.Slice(start, start2));
                }
                assert(std::get<0>(new_output).GetSize() != 0);
                new_results.push_back(new_output);
            }
            // Advances to the next table
            // xs is a concatenation of all 64 x values, in the current order. Note that at each
            // iteration, we can swap several parts of xs
            results = new_results;
            xs = new_xs;
        }
        std::vector<LargeBits> ordered_proof;
        for (uint8_t i = 0; i < 64; i++) {
            ordered_proof.push_back(xs.Slice(i * k, (i + 1) * k));
        }
        return ordered_proof;
    }

    // Recursive function to go through the tables on disk, backpropagating and fetching
    // all of the leaves (x values). For example, for depth=5, it fetches the positionth
    // entry in table 5, reading the two backpointers from the line point, and then
    // recursively calling GetInputs for table 4.
    std::vector<Bits> GetInputs(uint64_t position, uint8_t depth) {
        uint128_t line_point = ReadLinePoint(depth, position);
        std::pair<uint64_t, uint64_t> xy = Encoding::LinePointToSquare(line_point);

        if (depth == 1) {
            // For table P1, the line point represents two concatenated x values.
            std::vector<Bits> ret;
            ret.push_back(Bits(xy.second, k));  // y
            ret.push_back(Bits(xy.first, k));  // x
            return ret;
        } else {
            std::vector<Bits> left = GetInputs(xy.second, depth - 1);  // y
            std::vector<Bits> right = GetInputs(xy.first, depth - 1);  // x
            left.insert(left.end(), right.begin(), right.end());
            return left;
        }
    }

};

#endif  // SRC_CPP_PROVER_DISK_HPP_
