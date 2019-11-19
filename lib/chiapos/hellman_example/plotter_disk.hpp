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

#ifndef SRC_CPP_PLOTTER_DISK_HPP_
#define SRC_CPP_PLOTTER_DISK_HPP_

#include <unistd.h>
#include <stdio.h>

#include <iostream>
#include <fstream>
#include <map>
#include <algorithm>
#include <vector>
#include <string>
#include <utility>

#include "util.hpp"
#include "encoding.hpp"
#include "calculate_bucket.hpp"
#include "sort_on_disk.hpp"
#include "pos_constants.hpp"
#include "hellman.hpp"

// During backprop and compress, the write pointer is ahead of the read pointer
// Note that the large the offset, the higher these values must be
const uint32_t kReadMinusWrite = 2048;
const uint32_t kCachedPositionsSize = 8192;

// Distance between matching entries is stored in the offset
const uint32_t kOffsetSize = 11;

// Max matches a single entry can have, used for hardcoded memory allocation
const uint32_t kMaxMatchesSingleEntry = 30;

// Results of phase 3. These are passed into Phase 4, so the checkpoint tables
// can be properly built.
struct Phase3Results {
    // Pointers to each table start byte in the plot file
    vector<uint64_t> plot_table_begin_pointers;
    // Pointers to each table start byet in the final file
    vector<uint64_t> final_table_begin_pointers;
    // Number of entries written for f7
    uint64_t final_entries_written;
    uint32_t right_entry_size_bits;

    uint32_t header_size;
};

const Bits empty_bits;

class DiskPlotter {
 public:
    // This method creates a plot on disk with the filename. A temporary file, "plotting" + filename,
    // is created and will be larger than the final plot file. This file is deleted at the end of
    // the process.
    void CreatePlotDisk(std::string filename, uint8_t k, uint8_t* memo,
                        uint32_t memo_len, uint8_t* id, uint32_t id_len) {
        std::cout << std::endl << "Starting plotting progress into file " << filename << "." << std::endl;
        std::cout << "Memo: " << Util::HexStr(memo, memo_len) << std::endl;
        std::cout << "ID: " << Util::HexStr(id, id_len) << std::endl;
        std::cout << "Plot size is: " << static_cast<int>(k) << std::endl;

        // These variables are used in the WriteParkToFile method. They are preallocatted here
        // to save time.
        first_line_point_bytes = new uint8_t[CalculateLinePointSize(k)];
        park_stubs_bytes = new uint8_t[CalculateStubsSize(k)];
        park_deltas_bytes = new uint8_t[CalculateMaxDeltasSize(k, 1)];

        assert(id_len == kIdLen);
        assert(k >= kMinPlotSize);
        assert(k <= kMaxPlotSize);

        std::string plot_filename = filename + ".tmp";

        std::cout << std::endl << "Starting phrase 0/4: Hellman Attacks extra storage..." << std::endl;
        Timer extra_storage_timer;
        std::vector<uint64_t> extra_metadata;
        Timer hellman_timer;
        BuildExtraStorage(k, id, plot_filename, extra_metadata);
        hellman_timer.PrintElapsed("Time for phrase 0 = ");

        std::cout << std::endl << "Starting phase 1/4: Forward Propagation..." << std::endl;
        Timer p1;
        Timer all_phases;
        std::vector<uint64_t> results = WritePlotFile(plot_filename, k, id, memo, memo_len);
        p1.PrintElapsed("Time for phase 1 =");

        std::cout << std::endl << "Starting phase 2/4: Backpropagation..." << std::endl;
        Timer p2;
        Backpropagate(filename, plot_filename, k, id, memo, memo_len, results);
        p2.PrintElapsed("Time for phase 2 =");

        std::cout << std::endl << "Starting phase 3/4: Compression..." << std::endl;
        Timer p3;
        Phase3Results res = CompressTables(k, results, filename, plot_filename, id, memo, memo_len, extra_metadata);
        p3.PrintElapsed("Time for phase 3 =");

        std::cout << std::endl << "Starting phase 4/4: Write Checkpoint tables..." << std::endl;
        Timer p4;
        WriteCTables(k, k + 1, filename, plot_filename, res);
        p4.PrintElapsed("Time for phase 4 =");

        int removed = remove(plot_filename.c_str());
        assert(removed == 0);

        extra_storage_timer.PrintElapsed("Time for extra storage = ");
        all_phases.PrintElapsed("Total time =");


        delete[] first_line_point_bytes;
        delete[] park_stubs_bytes;
        delete[] park_deltas_bytes;
    }

    static uint32_t GetMaxEntrySize(uint8_t k, uint8_t table_index, bool phase_1_size) {
        switch (table_index) {
            case 1:
               // Represents f1, x
               return Util::ByteAlign(k + kExtraBits + k) / 8;
            case 2:
            case 3:
            case 4:
            case 5:
            case 6:
                if (phase_1_size)
                    // If we are in phase 1, use the max size, with metadata.
                    // Represents f, pos, offset, and metadata
                    return Util::ByteAlign(k + kExtraBits + (k + 1) + kOffsetSize +
                                           k * kVectorLens[table_index + 1]) / 8;
                else
                    // If we are past phase 1, we can use a smaller size, the smaller between
                    // phases 2 and 3. Represents either:
                    //    a:  sort_key, pos, offset        or
                    //    b:  line_point, sort_key
                    return Util::ByteAlign(max(static_cast<uint32_t>(k + 1 + (k + 1) + kOffsetSize),
                                               static_cast<uint32_t>(2 * k + k+1))) / 8;
            case 7:
            default:
                // Represents line_point, f7
                return Util::ByteAlign(3 * k) / 8;
        }
    }

    // Calculates the size of one C3 park. This will store bits for each f7 between
    // two C1 checkpoints, depending on how many times that f7 is present. For low
    // values of k, we need extra space to account for the additional variability.
    static uint32_t CalculateC3Size(uint8_t k) {
        if (k < 20) {
            return floor(Util::ByteAlign(8 * kCheckpoint1Interval) / 8);
        } else {
            // TODO(alex): tighten this bound, based on formula
            return Util::ByteAlign(kC3BitsPerEntry * kCheckpoint1Interval) / 8;
        }
    }

    static uint32_t CalculateLinePointSize(uint8_t k) {
        return Util::ByteAlign(2*k) / 8;
    }

    // This is the full size of the deltas section in a park. However, it will not be fully filled
    static uint32_t CalculateMaxDeltasSize(uint8_t k, uint8_t table_index) {
        if (table_index == 1) {
            return Util::ByteAlign((kEntriesPerPark - 1) * kMaxAverageDeltaTable1) / 8;
        }
        if (table_index == 2) {
            return Util::ByteAlign(std::floor((kEntriesPerPark - 1) * (kMaxAverageDelta + 1))) / 8;
        }
        return Util::ByteAlign((kEntriesPerPark - 1) * kMaxAverageDelta) / 8;
    }

    static uint32_t CalculateStubsSize(uint k) {
        return Util::ByteAlign((kEntriesPerPark - 1) * (k - kStubMinusBits)) / 8;
    }

    static uint32_t CalculateParkSize(uint8_t k, uint8_t table_index) {
        return CalculateLinePointSize(k) + CalculateStubsSize(k) + CalculateMaxDeltasSize(k, table_index);
    }

 private:
    uint8_t* first_line_point_bytes;
    uint8_t* park_stubs_bytes;
    uint8_t* park_deltas_bytes;

    // Writes the plot file header to a file
    uint32_t WriteHeader(std::ofstream &plot_file, uint8_t k, uint8_t* id, uint8_t* memo, uint32_t memo_len) {
        // 19 bytes  - "Proof of Space Plot" (utf-8)
        // 32 bytes  - unique plot id
        // 1 byte    - k
        // 2 bytes   - format description length
        // x bytes   - format description
        // 2 bytes   - memo length
        // x bytes   - memo

        std::string header_text = "Proof of Space Plot";
        plot_file.write(header_text.data(), header_text.size());

        plot_file.write(reinterpret_cast<char*>(id), kIdLen);

        uint8_t k_buffer[1];
        k_buffer[0] = k;
        plot_file.write(reinterpret_cast<char*>(k_buffer), 1);

        uint8_t size_buffer[2];
        Bits(kFormatDescription.size(), 16).ToBytes(size_buffer);
        plot_file.write(reinterpret_cast<char*>(size_buffer), 2);
        plot_file.write(kFormatDescription.data(), kFormatDescription.size());

        Bits(memo_len, 16).ToBytes(size_buffer);
        plot_file.write(reinterpret_cast<char*>(size_buffer), 2);
        plot_file.write(reinterpret_cast<char*>(memo), memo_len);

        uint8_t pointers[10*8];
        memset(pointers, 0, 10*8);
        plot_file.write(reinterpret_cast<char*>(pointers), 10*8);

        uint32_t bytes_written = header_text.size() + kIdLen + 1 + 2 + kFormatDescription.size()
                                 + 2 + memo_len + 10*8;
        std::cout << "Wrote: " << bytes_written << std::endl;
        return bytes_written;
    }

    // This is Phase 1, or forward propagation. During this phase, all of the 7 tables,
    // and f functions, are evaluated. The result is an intermediate plot file, that is
    // several times larger than what the final file will be, but that has all of the
    // proofs of space in it. First, F1 is computed, which is special since it uses
    // AES256, and each encrption provides multiple output values. Then, the rest of the
    // f functions are computed, and a sort on disk happens for each table.
    std::vector<uint64_t> WritePlotFile(std::string plot_filename, uint8_t k, uint8_t* id,
                                        uint8_t* memo, uint8_t memo_len) {
        // Note that the plot file is not the final file that will be stored on disk,
        // it is only present during plotting.
        std::ofstream plot_file(plot_filename, std::ios::out | std::ios::trunc | std::ios::binary);
        if (!plot_file.is_open()) {
            throw std::string("File not opened correct");
        }
        uint32_t header_size = WriteHeader(plot_file, k, id, memo, memo_len);

        std::cout << "Computing table 1" << std::endl;
        Timer f1_start_time;
        F1Calculator f1(k, id);
        uint64_t x = 0;

        uint32_t entry_size_bytes = GetMaxEntrySize(k, 1, true);

        // The max value our input (x), can take. A proof of space is 64 of these x values.
        uint64_t max_value = ((uint64_t)1 << (k)) - 1;
        uint8_t* buf = new uint8_t[entry_size_bytes];

        // These are used for sorting on disk. The sort on disk code needs to know how
        // many elements are in each bucket.
        std::vector<uint64_t> bucket_sizes(kNumSortBuckets, 0);
        std::vector<uint64_t> right_bucket_sizes(kNumSortBuckets, 0);

        uint32_t bucket_log = floor(log2(kNumSortBuckets));

        // Instead of computing f1(1), f1(2), etc, for each x, we compute them in batches
        // to increase CPU efficency.
        for (uint64_t lp = 0; lp <= (((uint64_t)1) << (k-kBatchSizes)); lp++) {
            // For each pair x, y in the batch
            for (auto kv : f1.CalculateBuckets(Bits(x, k), 2 << (kBatchSizes - 1))) {
                // TODO(mariano): fix inefficient memory alloc here
                (std::get<0>(kv) + std::get<1>(kv)).ToBytes(buf);

                // We write the x, y pair
                plot_file.write(reinterpret_cast<char*>(buf), entry_size_bytes);

                bucket_sizes[SortOnDiskUtils::ExtractNum(buf, entry_size_bytes, 0, bucket_log)] += 1;

                if (x + 1 > max_value) {
                    break;
                }
                ++x;
            }
            if (x + 1 > max_value) {
                break;
            }
        }
        delete[] buf;
        // A zero entry is the end of table symbol.
        Util::WriteZeroesStack(plot_file, entry_size_bytes);
        plot_file.close();

        f1_start_time.PrintElapsed("F1 complete, Time = ");

        // Begin byte of the f1 table
        uint64_t begin_byte = header_size;
        // Total number of entries in the current table (f1)
        uint64_t total_table_entries = ((uint64_t)1) << k;

        // This will contain the start bytes (into the plot file) for each table
        std::vector<uint64_t> plot_table_begin_pointers(9, 0);
        plot_table_begin_pointers[1] = begin_byte;

        // Store positions to previous tables, in k+1 bits. This is because we may have
        // more than 2^k entries in some of the tables, so we need an extra bit.
        uint8_t pos_size = k + 1;
        uint32_t right_entry_size_bytes = 0;

        // Number of buckets that y values will be put into.
        double num_buckets = ((uint64_t)1 << (k + kExtraBits)) / static_cast<double>(kBC) + 1;

        // Memory to be used for sorting
        uint8_t* memory = new uint8_t[kMemorySize];

        // For tables 1 through 6, sort the table, calculate matches, and write
        // the next table. This is the left table index.
        for (uint8_t table_index = 1; table_index < 7; table_index++) {
            Timer table_timer;
            uint8_t metadata_size = kVectorLens[table_index + 1] * k;

            // Determines how many bytes the entries in our left and right tables will take up.
            uint32_t entry_size_bytes = GetMaxEntrySize(k, table_index, true);
            right_entry_size_bytes = GetMaxEntrySize(k, table_index + 1, true);

            uint64_t begin_byte_next = begin_byte + (entry_size_bytes * (total_table_entries + 1));

            std::cout << "Computing table " << int{table_index + 1} << " at position 0x"
                      << std::hex << begin_byte_next << std::dec << std::endl;

            total_table_entries = 0;

            std::cout << "\tSorting table " << int{table_index} << std::endl;

            // Performs a sort on the left table,
            Timer sort_timer;
            FileDisk d(plot_filename);
            Sorting::SortOnDisk(d, begin_byte, begin_byte_next, entry_size_bytes,
                                0, bucket_sizes, memory, kMemorySize);
            d.Close();
            sort_timer.PrintElapsed("\tSort time:");

            Timer computation_pass_timer;

            // Streams to read and right to tables. We will have handles to two tables. We will
            // read through the left table, compute matches, and evaluate f for matching entries,
            // writing results to the right table.
            std::ifstream left_reader(plot_filename, std::fstream::in | std::fstream::binary);
            std::fstream right_writer(plot_filename, std::fstream::out | std::fstream::in | std::fstream::binary);

            left_reader.seekg(begin_byte);
            right_writer.seekp(begin_byte_next);

            FxCalculator f(k, table_index + 1, id);

            // This is a sliding window of entries, since things in bucket i can match with things in bucket
            // i + 1. At the end of each bucket, we find matches between the two previous buckets.
            std::vector<PlotEntry> bucket_L;
            std::vector<PlotEntry> bucket_R;

            uint64_t bucket = 0;
            uint64_t pos = 0;  // Position into the left table
            bool end_of_table = false;  // We finished all entries in the left table
            uint64_t matches = 0;  // Total matches

            // Buffers for storing a left or a right entry, used for disk IO
            uint8_t* left_buf = new uint8_t[entry_size_bytes];
            uint8_t* right_buf = new uint8_t[right_entry_size_bytes];
            Bits zero_bits(0, metadata_size);

            // Start at left table pos = 0 and iterate through the whole table. Note that the left table
            // will already be sorted by y
            while (!end_of_table) {
                PlotEntry left_entry;
                left_entry.right_metadata = 0;
                // Reads a left entry from disk
                left_reader.read(reinterpret_cast<char*>(left_buf), entry_size_bytes);
                if (table_index == 1) {
                    // For table 1, we only have y and metadata
                    left_entry.y = Util::SliceInt64FromBytes(left_buf, entry_size_bytes,
                                                             0, k + kExtraBits);
                    left_entry.left_metadata = Util::SliceInt128FromBytes(left_buf, entry_size_bytes,
                                                                          k + kExtraBits, metadata_size);
                } else {
                    // For tables 2-6, we we also have pos and offset, but we don't use it here.
                    left_entry.y = Util::SliceInt64FromBytes(left_buf, entry_size_bytes, 0, k + kExtraBits);
                    if (metadata_size <= 128) {
                        left_entry.left_metadata = Util::SliceInt128FromBytes(left_buf, entry_size_bytes,
                                                                              k + kExtraBits + pos_size + kOffsetSize,
                                                                              metadata_size);
                    } else {
                        // Large metadatas that don't fit into 128 bits. (k > 32).
                        left_entry.left_metadata = Util::SliceInt128FromBytes(left_buf, entry_size_bytes,
                                                                              k + kExtraBits + pos_size
                                                                                + kOffsetSize, 128);
                        left_entry.right_metadata = Util::SliceInt128FromBytes(left_buf, entry_size_bytes,
                                                                               k + kExtraBits + pos_size
                                                                                 + kOffsetSize + 128,
                                                                               metadata_size - 128);
                    }
                }
                // This is not the pos that was read from disk,but the position of the entry we read, within L table.
                left_entry.pos = pos;

                end_of_table = (left_entry.y == 0 && left_entry.left_metadata == 0 && left_entry.right_metadata == 0);
                uint64_t y_bucket = left_entry.y / kBC;

                // Keep reading left entries into bucket_L and R, until we run out of things
                if (y_bucket == bucket) {
                    bucket_L.emplace_back(std::move(left_entry));
                } else if (y_bucket == bucket + 1) {
                    bucket_R.emplace_back(std::move(left_entry));
                } else {
                    // This is reached when we have finished adding stuff to bucket_R and bucket_L,
                    // so now we can compare entries in both buckets to find matches. If two entries match,
                    // the result is written to the right table.
                    if (bucket_L.size() > 0 && bucket_R.size() > 0) {
                        // Compute all matches between the two buckets, and return indeces into each bucket
                        std::vector<std::pair<uint16_t, uint16_t> > match_indexes = f.FindMatches(bucket_L, bucket_R);
                        for (auto& indeces : match_indexes) {
                            PlotEntry& L_entry = bucket_L[std::get<0>(indeces)];
                            PlotEntry& R_entry = bucket_R[std::get<1>(indeces)];
                            std::pair<Bits, Bits> f_output;

                            // Computes the output pair (fx, new_metadata)
                            if (metadata_size <= 128) {
                                f_output = f.CalculateBucket(Bits(L_entry.y, k + kExtraBits),
                                                             Bits(R_entry.y, k + kExtraBits),
                                                             Bits(L_entry.left_metadata, metadata_size),
                                                             Bits(R_entry.left_metadata, metadata_size));
                            } else {
                                // Metadata does not fit into 128 bits
                                f_output = f.CalculateBucket(Bits(L_entry.y, k + kExtraBits),
                                                             Bits(R_entry.y, k + kExtraBits),
                                                             Bits(L_entry.left_metadata, 128)
                                                              + Bits(L_entry.right_metadata, metadata_size - 128),
                                                             Bits(R_entry.left_metadata, 128)
                                                              + Bits(R_entry.right_metadata, metadata_size - 128));
                            }
                            // fx/y, which will be used for sorting and matching
                            Bits& new_entry = std::get<0>(f_output);
                            ++matches;
                            ++total_table_entries;

                            if (table_index + 1 == 7) {
                                // We only need k instead of k + kExtraBits bits for the last table
                                new_entry = new_entry.Slice(0, k);
                            }
                            // Position in the previous table
                            new_entry += Bits(L_entry.pos, pos_size);
                            // Offset for matching entry
                            if (R_entry.pos - L_entry.pos > 2000) {
                                std::cout << "Offset: " <<  R_entry.pos - L_entry.pos << std::endl;
                            }
                            new_entry.AppendValue(R_entry.pos - L_entry.pos, kOffsetSize);
                            // New metadata which will be used to compute the next f
                            new_entry += std::get<1>(f_output);
                            // Fill with 0s if entry is not long enough
                            new_entry.AppendValue(0, right_entry_size_bytes * 8 - new_entry.GetSize());
                            new_entry.ToBytes(right_buf);
                            // Writes the new entry into the right table
                            right_writer.write(reinterpret_cast<char*>(right_buf), right_entry_size_bytes);

                            // Computes sort bucket, so we can sort the table by y later, more easily
                            right_bucket_sizes[SortOnDiskUtils::ExtractNum(right_buf, right_entry_size_bytes, 0,
                                                                            floor(log2(kNumSortBuckets)))] += 1;
                        }
                    }
                    if (y_bucket == bucket + 2) {
                        // We saw a bucket that is 2 more than the current, so we just set L = R, and R = [entry]
                        bucket_L = bucket_R;
                        bucket_R = std::vector<PlotEntry>();
                        bucket_R.emplace_back(std::move(left_entry));
                        ++bucket;
                    } else {
                        // We saw a bucket that >2 more than the current, so we just set L = [entry], and R = []
                        bucket = y_bucket;
                        bucket_L = std::vector<PlotEntry>();
                        bucket_L.emplace_back(std::move(left_entry));
                        bucket_R = std::vector<PlotEntry>();
                    }
                }
                // Increase the read pointer in the left table, by one
                ++pos;
            }

            // Total matches found in the left table
            std::cout << "\tTotal matches: " << matches << ". Per bucket: "
                      << (matches / num_buckets) << std::endl;

            // Writes the 0 entry (EOT)
            memset(right_buf, 0, right_entry_size_bytes);
            Bits(0, right_entry_size_bytes * 8).ToBytes(right_buf);
            right_writer.write(reinterpret_cast<char*>(right_buf), right_entry_size_bytes);

            // Writes the start of the table to the header, so we can resume plotting if it
            // interrups.
            right_writer.seekp(header_size - 8 * (12 - table_index));
            uint8_t pointer_buf[8];
            Bits(begin_byte_next, 8*8).ToBytes(pointer_buf);
            right_writer.write(reinterpret_cast<char*>(pointer_buf), 8);

            // Resets variables
            plot_table_begin_pointers[table_index + 1] = begin_byte_next;
            begin_byte = begin_byte_next;
            bucket_sizes = right_bucket_sizes;
            right_bucket_sizes = std::vector<uint64_t>(kNumSortBuckets, 0);

            left_reader.close();
            right_writer.close();
            delete[] left_buf;
            delete[] right_buf;

            computation_pass_timer.PrintElapsed("\tComputation pass time:");
            table_timer.PrintElapsed("Forward propagation table time:");
        }
        // Pointer to the end of the last table + 1, used for spare space for disk sorting
        plot_table_begin_pointers[8] = plot_table_begin_pointers[7] +
                                       (right_entry_size_bytes * (total_table_entries + 1));
        delete[] memory;
        std::cout << "Final plot table begin pointers: " << std::endl;
        for (uint8_t i = 1; i <= 8; i++) {
            std::cout << "\tTable " << int{i} << " 0x"
                      << std::hex << plot_table_begin_pointers[i] << std::dec << std::endl;
        }

        return plot_table_begin_pointers;
    }

    // Backpropagate takes in as input, a file on which forward propagation has been done.
    // The purpose of backpropagate is to eliminate any dead entries that don't contribute
    // to final values in f7, to minimize disk usage. A sort on disk is applied to each table,
    // so that they are sorted by position.
    void Backpropagate(std::string filename, std::string plot_filename, uint8_t k,
                       uint8_t* id, uint8_t* memo, uint32_t memo_len, const std::vector<uint64_t>& results) {
        std::vector<uint64_t> plot_table_begin_pointers = results;

        // An extra bit is used, since we may have more than 2^k entries in a table. (After pruning, each table will
        // have 0.8*2^k or less entries).
        uint8_t pos_size = k + 1;

        std::vector<uint64_t> bucket_sizes_pos(kNumSortBuckets, 0);

        // The end of the table 7, is spare space that we can use for sorting
        uint64_t spare_pointer = plot_table_begin_pointers[8];

        // Memory to be used for sorting
        uint8_t* memory = new uint8_t[kMemorySize];

        // Iterates through each table (with a left and right pointer), starting at 6 & 7.
        for (uint8_t table_index = 7; table_index > 1; --table_index) {
            Timer table_timer;

            // We will have reader and writer for both tables.
            std::ifstream left_reader(plot_filename, std::ios::in | std::ios::binary);
            std::ofstream left_writer(plot_filename, std::ios::in | std::ios::out | std::ios::binary);
            std::ifstream right_reader(plot_filename, std::ios::in | std::ios::binary);
            std::ofstream right_writer(plot_filename, std::ios::in | std::ios::out | std::ios::binary);

            std::cout << "Backpropagating on table " << int{table_index} << std::endl;

            std::vector<uint64_t> new_bucket_sizes_pos(kNumSortBuckets, 0);

            uint16_t left_metadata_size = kVectorLens[table_index] * k;

            // The entry that we are reading (includes metadata)
            uint16_t left_entry_size_bytes = GetMaxEntrySize(k, table_index - 1, true);

            // The entry that we are writing (no metadata)
            uint16_t new_left_entry_size_bytes = GetMaxEntrySize(k, table_index - 1, false);

            // The right entries which we read and write (the already have no metadata, since they have
            // been pruned in previous iteration)
            uint16_t right_entry_size_bytes = GetMaxEntrySize(k, table_index, false);

            left_writer.flush();
            right_writer.flush();

            // Doesn't sort table 7, since it's already sorted by pos6 (position into table 6).
            // The reason we sort, is so we can iterate through both tables at once. For example,
            // if we read a right entry (pos, offset) = (456, 2), the next one might be (458, 19),
            // and in the left table, we are reading entries around pos 450, etc..
            if (table_index != 7) {
                std::cout << "\tSorting table " << int{table_index} << " starting at "
                          << plot_table_begin_pointers[table_index] << std::endl;
                Timer sort_timer;
                FileDisk d(plot_filename);
                Sorting::SortOnDisk(d, plot_table_begin_pointers[table_index], spare_pointer,
                                    right_entry_size_bytes,
                                    0, bucket_sizes_pos, memory, kMemorySize);
                d.Close();
                sort_timer.PrintElapsed("\tSort time:");
            }
            Timer computation_pass_timer;

            left_reader.seekg(plot_table_begin_pointers[table_index - 1]);
            left_writer.seekp(plot_table_begin_pointers[table_index - 1]);
            right_reader.seekg(plot_table_begin_pointers[table_index]);
            right_writer.seekp(plot_table_begin_pointers[table_index]);
            left_writer.flush();
            right_writer.flush();

            // We will divide by 2, so it must be even.
            assert(kCachedPositionsSize % 2 == 0);

            // Used positions will be used to mark which posL are present in table R, the rest will be pruned
            bool used_positions[kCachedPositionsSize];
            memset(used_positions, 0, sizeof(used_positions));

            bool should_read_entry = true;

            // Cache for when we read a right entry that is too far forward
            uint64_t cached_entry_sort_key = 0;  // For table_index == 7, y is here
            uint64_t cached_entry_pos = 0;
            uint64_t cached_entry_offset = 0;

            uint64_t left_entry_counter = 0;  // Total left entries written

            // Sliding window map, from old position to new position (after pruning)
            uint64_t new_positions[kCachedPositionsSize];

            // Sort keys represent the ordering of entries, sorted by (y, pos, offset),
            // but using less bits (only k+1 instead of 2k + 9, etc.)
            // This is a map from old position to array of sort keys (one for each R entry with this pos)
            Bits old_sort_keys[kReadMinusWrite][kMaxMatchesSingleEntry];
            // Map from old position to other positions that it matches with
            uint64_t old_offsets[kReadMinusWrite][kMaxMatchesSingleEntry];
            // Map from old position to count (number of times it appears)
            uint16_t old_counters[kReadMinusWrite];

            for (uint32_t i = 0; i < kReadMinusWrite; i++) {
                old_counters[i] = 0;
            }

            bool end_of_right_table = false;
            uint64_t current_pos = 0;  // This is the current pos that we are looking for in the L table
            uint64_t end_of_table_pos = 0;
            uint64_t greatest_pos = 0;  // This is the greatest position we have seen in R table

            // Buffers for reading and writing to disk
            uint8_t* left_entry_buf = new uint8_t[left_entry_size_bytes];
            uint8_t* new_left_entry_buf = new uint8_t[new_left_entry_size_bytes];
            uint8_t* right_entry_buf = new uint8_t[right_entry_size_bytes];

            // Go through all right entries, and keep going since write pointer is behind read pointer
            while (!end_of_right_table || (current_pos - end_of_table_pos <= kReadMinusWrite)) {
                old_counters[current_pos % kReadMinusWrite] = 0;

                // Resets used positions after a while, so we use little memory
                if ((current_pos - kReadMinusWrite) % (kCachedPositionsSize / 2) == 0) {
                    if ((current_pos - kReadMinusWrite) % kCachedPositionsSize == 0) {
                        for (uint32_t i = kCachedPositionsSize / 2; i < kCachedPositionsSize; i++) {
                            used_positions[i] = false;
                        }
                    } else {
                        for (uint32_t i = 0; i < kCachedPositionsSize / 2; i++) {
                            used_positions[i] = false;
                        }
                    }
                }
                // Only runs this code if we are still reading the right table, or we still need to read
                // more left table entries (current_pos <= greatest_pos), otherwise, it skips to the
                // writing of the final R table entries
                if (!end_of_right_table || current_pos <= greatest_pos) {
                    uint64_t entry_sort_key = 0;
                    uint64_t entry_pos = 0;
                    uint64_t entry_offset = 0;

                    while (!end_of_right_table) {
                        if (should_read_entry) {
                            // Need to read another entry at the current position
                            right_reader.read(reinterpret_cast<char *>(right_entry_buf),
                                              right_entry_size_bytes);
                            if (table_index == 7) {
                                // This is actually y for table 7
                                entry_sort_key = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                           0, k);
                                entry_pos = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                      k, pos_size);
                                entry_offset = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                         k + pos_size, kOffsetSize);
                            } else {
                                entry_pos = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                      0, pos_size);
                                entry_offset = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                         pos_size, kOffsetSize);
                                entry_sort_key = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                           pos_size + kOffsetSize, k + 1);
                            }
                        } else if (cached_entry_pos == current_pos) {
                            // We have a cached entry at this position
                            entry_sort_key = cached_entry_sort_key;
                            entry_pos = cached_entry_pos;
                            entry_offset = cached_entry_offset;
                        } else {
                            // The cached entry is at a later pos, so we don't read any more R entries,
                            // read more L entries instead.
                            break;
                        }

                        should_read_entry = true;  // By default, read another entry
                        if (entry_pos + entry_offset > greatest_pos) {
                            // Greatest L pos that we should look for
                            greatest_pos = entry_pos + entry_offset;
                        }
                        if (entry_sort_key == 0 && entry_pos == 0 && entry_offset == 0) {
                            // Table R has ended, don't read any more (but keep writing)
                            end_of_right_table = true;
                            end_of_table_pos = current_pos;
                            break;
                        } else if (entry_pos == current_pos) {
                            // The current L position is the current R entry
                            // Marks the two matching entries as used (pos and pos+offset)
                            used_positions[entry_pos % kCachedPositionsSize] = true;
                            used_positions[(entry_pos + entry_offset) % kCachedPositionsSize] = true;

                            uint64_t old_write_pos = entry_pos % kReadMinusWrite;
                            if (table_index == 7) {
                                // Stores the sort key for this R entry, which is just y (so k bits)
                                old_sort_keys[old_write_pos][old_counters[old_write_pos]] = Bits(entry_sort_key, k);
                            } else {
                                // Stores the sort key for this R entry
                                old_sort_keys[old_write_pos][old_counters[old_write_pos]] = Bits(entry_sort_key, k + 1);
                            }
                            // Stores the other matching pos for this R entry (pos6 + offset)
                            old_offsets[old_write_pos][old_counters[old_write_pos]] = entry_pos + entry_offset;
                            ++old_counters[old_write_pos];
                        } else {
                            // Don't read any more right entries for now, because we haven't caught up on the
                            // left table yet
                            should_read_entry = false;
                            cached_entry_sort_key = entry_sort_key;
                            cached_entry_pos = entry_pos;
                            cached_entry_offset = entry_offset;
                            break;
                        }
                    }
                    // Reads a left entry
                    left_reader.read(reinterpret_cast<char *>(left_entry_buf),
                                     left_entry_size_bytes);

                    // If this left entry is used, we rewrite it. If it's not used, we ignore it.
                    if (used_positions[current_pos % kCachedPositionsSize]) {
                        uint64_t entry_y = Util::SliceInt64FromBytes(left_entry_buf, left_entry_size_bytes,
                                                                    0, k + kExtraBits);
                        uint64_t entry_metadata;

                        if (table_index > 2) {
                            // For tables 2-6, the entry is: f, pos, offset metadata
                            entry_pos = Util::SliceInt64FromBytes(left_entry_buf, left_entry_size_bytes,
                                                                k + kExtraBits, pos_size);
                            entry_offset = Util::SliceInt64FromBytes(left_entry_buf, left_entry_size_bytes,
                                                                    k + kExtraBits + pos_size, kOffsetSize);
                        } else {
                            // For table1, the entry is: f, metadata
                            entry_metadata = Util::SliceInt128FromBytes(left_entry_buf, left_entry_size_bytes,
                                                                        k + kExtraBits, left_metadata_size);
                        }
                        Bits new_left_entry;
                        if (table_index > 2) {
                            // The new left entry is slightly different. Metadata is dropped, to save space,
                            // and the counter of the entry is written (sort_key). We use this instead of
                            // (y + pos + offset) since its smaller.
                            new_left_entry += Bits(entry_pos, pos_size);
                            new_left_entry += Bits(entry_offset, kOffsetSize);
                            new_left_entry += Bits(left_entry_counter, k + 1);

                            // If we are not taking up all the bits, make sure they are zeroed
                            if (Util::ByteAlign(new_left_entry.GetSize()) < new_left_entry_size_bytes * 8) {
                                memset(new_left_entry_buf, 0, new_left_entry_size_bytes);
                            }
                        } else {
                            // For table one entries, we don't care about sort key, only y and x.
                            new_left_entry += Bits(entry_y, k + kExtraBits);
                            new_left_entry += Bits(entry_metadata, left_metadata_size);
                            // std::cout << "Writing X:" << entry_metadata.GetValue() << std::endl;
                        }
                        new_left_entry.ToBytes(new_left_entry_buf);
                        left_writer.write(reinterpret_cast<char *>(new_left_entry_buf), new_left_entry_size_bytes);

                        new_bucket_sizes_pos[SortOnDiskUtils::ExtractNum(new_left_entry_buf, new_left_entry_size_bytes,
                                                                        0, floor(log2(kNumSortBuckets)))] += 1;
                        // Mapped positions, so we can rewrite the R entry properly
                        new_positions[current_pos % kCachedPositionsSize] = left_entry_counter;

                        // Counter for new left entries written
                        ++left_entry_counter;
                    }
                }
                // Write pointer lags behind the read pointer
                int64_t write_pointer_pos = current_pos - kReadMinusWrite + 1;

                // Only write entries for write_pointer_pos, if we are above 0, and there are actually R entries
                // for that pos.
                if (write_pointer_pos >= 0 && used_positions[write_pointer_pos % kCachedPositionsSize]) {
                    uint64_t new_pos = new_positions[write_pointer_pos % kCachedPositionsSize];
                    Bits new_pos_bin(new_pos, pos_size);
                    // There may be multiple R entries that share the write_pointer_pos, so write all of them
                    for (uint32_t counter = 0; counter < old_counters[write_pointer_pos % kReadMinusWrite]; counter++) {
                        // Creates and writes the new right entry, with the cached data
                        uint64_t new_offset_pos = new_positions[old_offsets[write_pointer_pos % kReadMinusWrite]
                                                                [counter] % kCachedPositionsSize];

                        Bits& new_right_entry = old_sort_keys[write_pointer_pos % kReadMinusWrite][counter];
                        new_right_entry += new_pos_bin;
                        new_right_entry.AppendValue(new_offset_pos - new_pos, kOffsetSize);
                        if (Util::ByteAlign(new_right_entry.GetSize()) < right_entry_size_bytes * 8) {
                            memset(right_entry_buf, 0, right_entry_size_bytes);
                        }
                        new_right_entry.ToBytes(right_entry_buf);
                        right_writer.write(reinterpret_cast<char*>(right_entry_buf),
                                            right_entry_size_bytes);
                    }
                }
                ++current_pos;
            }

            std::cout << "\tWrote left entries: " <<  left_entry_counter << std::endl;
            computation_pass_timer.PrintElapsed("\tComputation pass time:");
            table_timer.PrintElapsed("Total backpropagation time::");

            Bits(0, right_entry_size_bytes * 8).ToBytes(right_entry_buf);
            right_writer.write(reinterpret_cast<char*>(right_entry_buf), right_entry_size_bytes);
            Bits(0, new_left_entry_size_bytes * 8).ToBytes(new_left_entry_buf);
            left_writer.write(reinterpret_cast<char*>(new_left_entry_buf), new_left_entry_size_bytes);

            left_reader.close();
            left_writer.close();
            right_reader.close();
            right_writer.close();

            bucket_sizes_pos = new_bucket_sizes_pos;

            delete[] left_entry_buf;
            delete[] new_left_entry_buf;
            delete[] right_entry_buf;
        }
        delete[] memory;
    }

    // This writes a number of entries into a file, in the final, optimized format. The park contains
    // a checkpoint value (whicch is a 2k bits line point), as well as EPP (entries per park) entries.
    // These entries are each divded into stub and delta section. The stub bits are encoded as is, but
    // the delta bits are optimized into a variable encoding scheme. Since we have many entries in each
    // park, we can approximate how much space each park with take.
    // Format is: [2k bits of first_line_point]  [EPP-1 stubs] [Deltas size] [EPP-1 deltas]....  [first_line_point] ...
    void WriteParkToFile(std::ofstream &writer, uint64_t table_start, uint64_t park_index, uint32_t park_size_bytes,
                         uint128_t first_line_point, const std::vector<uint8_t>& park_deltas,
                         const std::vector<uint64_t>& park_stubs, uint8_t k, uint8_t table_index) {
        // Parks are fixed size, so we know where to start writing. The deltas will not go over
        // into the next park.
        writer.seekp(table_start + park_index * park_size_bytes);
        Bits first_line_point_bits(first_line_point, 2*k);
        memset(first_line_point_bytes, 0, CalculateLinePointSize(k));
        first_line_point_bits.ToBytes(first_line_point_bytes);
        writer.write((const char*)first_line_point_bytes, CalculateLinePointSize(k));

        // We use ParkBits insted of Bits since it allows storing more data
        ParkBits park_stubs_bits;
        for (uint64_t stub : park_stubs) {
            park_stubs_bits.AppendValue(stub, (k - kStubMinusBits));
        }
        uint32_t stubs_size = CalculateStubsSize(k);
        memset(park_stubs_bytes, 0, stubs_size);
        park_stubs_bits.ToBytes(park_stubs_bytes);
        writer.write((const char*)park_stubs_bytes, stubs_size);

        // The stubs are random so they don't need encoding. But deltas are more likely to
        // be small, so we can compress them
        double R = kRValues[table_index - 1];
        ParkBits deltas_bits = Encoding::ANSEncodeDeltas(park_deltas, R);
        deltas_bits.ToBytes(park_deltas_bytes);

        uint16_t encoded_size = deltas_bits.GetSize() / 8;
        if (encoded_size + 2 > CalculateMaxDeltasSize(k, table_index))
            std::cout << encoded_size + 2 << " " << CalculateMaxDeltasSize(k, table_index) << "\n";
        assert(encoded_size + 2 < CalculateMaxDeltasSize(k, table_index));
        writer.write((const char*)&encoded_size, 2);
        writer.write((const char*)park_deltas_bytes, encoded_size);
    }

    // Compresses the plot file tables into the final file. In order to do this, entries must be
    // reorganized from the (pos, offset) bucket sorting order, to a more free line_point sorting
    // order. In (pos, offset ordering), we store two pointers two the previous table, (x, y) which
    // are very close together, by storing  (x, y-x), or (pos, offset), which can be done in about k + 8 bits,
    // since y is in the next bucket as x. In order to decrease this, We store the actual entries from the
    // previous table (e1, e2), instead of pos, offset pointers, and sort the entire table by (e1,e2).
    // Then, the deltas between each (e1, e2) can be stored, which require around k bits.

    // Converting into this format requires a few passes and sorts on disk. It also assumes that the
    // backpropagation step happened, so there will be no more dropped entries. See the design
    // document for more details on the algorithm.
    Phase3Results CompressTables(uint8_t k, vector<uint64_t> plot_table_begin_pointers, std::string filename,
                                 std::string plot_filename, uint8_t* id, uint8_t* memo, uint32_t memo_len,
                                 std::vector<uint64_t>& extra_metadata) {
        // In this phase we open a new file, where the final contents of the plot will be stored.
        std::ofstream header_writer(filename, std::ios::out | std::ios::trunc | std::ios::binary);
        if (!header_writer.is_open()) {
            throw std::string("Final file not opened correct");
        }
        uint32_t header_size = WriteHeader(header_writer, k, id, memo, memo_len);

        uint8_t pos_size = k + 1;


        std::vector<uint64_t> final_table_begin_pointers(12, 0);
        final_table_begin_pointers[1] = header_size;

        header_writer.seekp(header_size - 10*8);
        uint8_t table_1_pointer_bytes[8*8];
        Bits(final_table_begin_pointers[1], 8*8).ToBytes(table_1_pointer_bytes);
        header_writer.write((const char*)table_1_pointer_bytes, 8);
        header_writer.close();

        uint64_t spare_pointer = plot_table_begin_pointers[8];

        uint8_t* memory = new uint8_t[kMemorySize];

        uint64_t final_entries_written = 0;
        uint32_t right_entry_size_bytes = 0;

        // Iterates through all tables, starting at 1, with L and R pointers.
        // For each table, R entries are rewritten with line points. Then, the right table is
        // sorted by line_point. After this, the right table entries are rewritten as (sort_key, new_pos),
        // where new_pos is the position in the table, where it's sorted by line_point, and the line_points
        // are written to disk to a final table. Finally, table_i is sorted by sort_key. This allows us to
        // compare to the next table.
        F1Calculator f1(k, id);
        f1.ReloadKey();
        for (uint8_t table_index = 1; table_index < 7; table_index++) {
            Timer table_timer;
            Timer computation_pass_1_timer;
            std::cout << "Compressing tables " << int{table_index} << " and " << int{table_index + 1} << std::endl;
            std::ifstream left_reader(plot_filename, std::ios::in | std::ios::binary);
            std::ifstream right_reader(plot_filename, std::ios::in | std::ios::binary);
            std::ofstream right_writer(plot_filename, std::ios::in | std::ios::out | std::ios::binary);

            // The park size must be constant, for simplicity, but must be big enough to store EPP entries.
            // entry deltas are encoded with variable length, and thus there is no guarantee that they
            // won't override into the next park. It is only different (larger) for table 1
            uint32_t park_size_bytes = CalculateParkSize(k, table_index);

            std::vector<uint64_t> bucket_sizes(kNumSortBuckets, 0);

            uint32_t left_y_size = k + kExtraBits;

            // Sort key for table 7 is just y, which is k bits. For all other tables it can
            // be higher than 2^k and therefore k+1 bits are used.
            uint32_t right_sort_key_size = table_index == 6 ? k : k + 1;

            uint32_t left_entry_size_bytes = GetMaxEntrySize(k, table_index, false);
            right_entry_size_bytes = GetMaxEntrySize(k, table_index + 1, false);

            left_reader.seekg(plot_table_begin_pointers[table_index]);
            right_reader.seekg(plot_table_begin_pointers[table_index + 1]);
            right_writer.seekp(plot_table_begin_pointers[table_index + 1]);

            bool should_read_entry = true;
            std::vector<uint64_t> left_new_pos(kCachedPositionsSize);

            Bits old_sort_keys[kReadMinusWrite][kMaxMatchesSingleEntry];
            uint64_t old_offsets[kReadMinusWrite][kMaxMatchesSingleEntry];
            uint16_t old_counters[kReadMinusWrite];
            for (uint32_t i = 0; i < kReadMinusWrite; i++) {
                old_counters[i] = 0;
            }
            bool end_of_right_table = false;
            uint64_t current_pos = 0;
            uint64_t end_of_table_pos = 0;
            uint64_t greatest_pos = 0;

            uint8_t* right_entry_buf = new uint8_t[right_entry_size_bytes];
            uint8_t* left_entry_disk_buf = new uint8_t[left_entry_size_bytes];
            uint64_t entry_sort_key, entry_pos, entry_offset;
            uint64_t cached_entry_sort_key = 0;
            uint64_t cached_entry_pos = 0;
            uint64_t cached_entry_offset = 0;

            // Similar algorithm as Backprop, to read both L and R tables simultaneously
            while (!end_of_right_table || (current_pos - end_of_table_pos <= kReadMinusWrite)) {
                old_counters[current_pos % kReadMinusWrite] = 0;

                if (end_of_right_table || current_pos <= greatest_pos) {
                    while (!end_of_right_table) {
                        if (should_read_entry) {
                            // The right entries are in the format from backprop, (sort_key, pos, offset)
                            right_reader.read(reinterpret_cast<char *>(right_entry_buf),
                                            right_entry_size_bytes);
                            entry_sort_key = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                       0, right_sort_key_size);
                            entry_pos = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                  right_sort_key_size, pos_size);
                            entry_offset = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                     right_sort_key_size + pos_size, kOffsetSize);
                        } else if (cached_entry_pos == current_pos) {
                            entry_sort_key = cached_entry_sort_key;
                            entry_pos = cached_entry_pos;
                            entry_offset = cached_entry_offset;
                        } else {
                            break;
                        }

                        should_read_entry = true;

                        if (entry_pos + entry_offset > greatest_pos) {
                            greatest_pos = entry_pos + entry_offset;
                        }
                        if (entry_sort_key == 0 && entry_pos == 0 && entry_offset == 0) {
                            end_of_right_table = true;
                            end_of_table_pos = current_pos;
                            break;
                        } else if (entry_pos == current_pos) {
                            uint64_t old_write_pos = entry_pos % kReadMinusWrite;
                            old_sort_keys[old_write_pos][old_counters[old_write_pos]]
                                = Bits(entry_sort_key, right_sort_key_size);
                            old_offsets[old_write_pos][old_counters[old_write_pos]] = (entry_pos + entry_offset);
                            ++old_counters[old_write_pos];
                        } else {
                            should_read_entry = false;
                            cached_entry_sort_key = entry_sort_key;
                            cached_entry_pos = entry_pos;
                            cached_entry_offset = entry_offset;
                            break;
                        }
                    }
                    // The left entries are in the new format: (sort_key, new_pos), except for table 1: (y, x).
                    left_reader.read(reinterpret_cast<char *>(left_entry_disk_buf), left_entry_size_bytes);
                    // We read the "new_pos" from the L table, which for table 1 is just x. For other tables,
                    // the new_pos
                    if (table_index == 1) {
                        // Only k bits, since this is x
                        left_new_pos[current_pos % kCachedPositionsSize]
                                = Util::SliceInt64FromBytes(left_entry_disk_buf, left_entry_size_bytes, left_y_size, k);
                    } else if (table_index == 2) {
                        left_new_pos[current_pos % kCachedPositionsSize]
                                = Util::SliceInt64FromBytes(left_entry_disk_buf, left_entry_size_bytes, k + 1,
                                                            k);
                    } else {
                        // k+1 bits in case it overflows
                        left_new_pos[current_pos % kCachedPositionsSize]
                                = Util::SliceInt64FromBytes(left_entry_disk_buf, left_entry_size_bytes, k + 1,
                                                            pos_size);
                    }
                }

                uint64_t write_pointer_pos = current_pos - kReadMinusWrite + 1;

                // Rewrites each right entry as (line_point, sort_key)
                if (current_pos + 1 >= kReadMinusWrite) {
                    uint64_t left_new_pos_1 = left_new_pos[write_pointer_pos % kCachedPositionsSize];
                    for (uint32_t counter = 0; counter < old_counters[write_pointer_pos % kReadMinusWrite]; counter++) {
                        uint64_t left_new_pos_2 = left_new_pos[old_offsets[write_pointer_pos % kReadMinusWrite][counter]
                                                % kCachedPositionsSize];

                        // A line point is an encoding of two k bit values into one 2k bit value.
                        uint128_t line_point = Encoding::SquareToLinePoint(left_new_pos_1, left_new_pos_2);

                        if (left_new_pos_1 > ((uint64_t)1 << k) || left_new_pos_2 > ((uint64_t)1 << k)) {
                            std::cout << "left and right positions too large" << std::endl;
                            std::cout << (line_point > ((uint128_t)1 << (2*k)));
                            if ((line_point > ((uint128_t)1 << (2*k)))) {
                                std::cout << "L, R: " << left_new_pos_1 <<  " " << left_new_pos_2 << std::endl;
                                std::cout << "Line point: " << line_point << std::endl;
                                abort();
                            }
                        }
                        Bits to_write = Bits(line_point, 2*k);
                        to_write += old_sort_keys[write_pointer_pos % kReadMinusWrite][counter];

                        to_write.ToBytes(right_entry_buf);
                        right_writer.write((const char*)right_entry_buf, right_entry_size_bytes);
                        bucket_sizes[SortOnDiskUtils::ExtractNum(right_entry_buf, right_entry_size_bytes, 0,
                                                                 floor(log2(kNumSortBuckets)))] += 1;
                    }
                }
                current_pos += 1;
            }
            memset(right_entry_buf, 0, right_entry_size_bytes);
            right_writer.write(reinterpret_cast<char*>(right_entry_buf),
                               right_entry_size_bytes);

            left_reader.close();
            right_writer.close();
            right_reader.close();

            computation_pass_1_timer.PrintElapsed("\tFirst computation pass time:");
            Timer sort_timer;
            std::cout << "\tSorting table " << int{table_index + 1} << std::endl;

            FileDisk d = FileDisk(plot_filename);
            Sorting::SortOnDisk(d, plot_table_begin_pointers[table_index + 1], spare_pointer,
                                right_entry_size_bytes, 0, bucket_sizes, memory, kMemorySize, /*quicksort=*/1);
            d.Close();
            sort_timer.PrintElapsed("\tSort time:");
            Timer computation_pass_2_timer;

            std::ifstream right_reader_2(plot_filename, std::ios::in | std::ios::binary);
            std::ofstream right_writer_2(plot_filename, std::ios::in | std::ios::out | std::ios::binary);
            right_reader_2.seekg(plot_table_begin_pointers[table_index + 1]);
            right_writer_2.seekp(plot_table_begin_pointers[table_index + 1]);

            std::ofstream final_table_writer(filename, std::ios::in | std::ios::out | std::ios::binary);
            final_table_writer.seekp(final_table_begin_pointers[table_index]);
            final_entries_written = 0;

            std::vector<uint64_t> new_bucket_sizes(kNumSortBuckets, 0);
            std::vector<uint8_t> park_deltas;
            std::vector<uint64_t> park_stubs;
            uint128_t checkpoint_line_point = 0;
            uint128_t last_line_point = 0;
            uint64_t park_index = 0;

            uint64_t total_r_entries = 0;
            for (auto x : bucket_sizes) {
                total_r_entries += x;
            }
            // Now we will write on of the final tables, since we have a table sorted by line point. The final
            // table will simply store the deltas between each line_point, in fixed space groups(parks), with a
            // checkpoint in each group.
            Bits right_entry_bits;
            for (uint64_t index = 0; index < total_r_entries; index++) {
                right_reader_2.read(reinterpret_cast<char *>(right_entry_buf),
                                right_entry_size_bytes);
                // Right entry is read as (line_point, sort_key)
                uint128_t line_point = Util::SliceInt128FromBytes(right_entry_buf, right_entry_size_bytes,
                                                                  0, 2*k);
                uint64_t sort_key = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes,
                                                              2*k, right_sort_key_size);

                // Write the new position (index) and the sort key
                Bits to_write = Bits(sort_key, right_sort_key_size);
                if (table_index > 1) {
                    to_write += Bits(index, k + 1);
                } else {
                    auto x1x2 = Encoding::LinePointToSquare(line_point);
                    Bits y1 = f1.CalculateF(Bits(x1x2.first, k));
                    Bits y2 = f1.CalculateF(Bits(x1x2.second, k));
                    if (y1 < y2)
                        to_write += Bits(x1x2.first, k);
                    else
                        to_write += Bits(x1x2.second, k);
                }
                memset(right_entry_buf, 0, right_entry_size_bytes);
                to_write.ToBytes(right_entry_buf);
                right_writer_2.write(reinterpret_cast<char*>(right_entry_buf), right_entry_size_bytes);

                new_bucket_sizes[SortOnDiskUtils::ExtractNum(right_entry_buf, right_entry_size_bytes, 0,
                                                             floor(log2(kNumSortBuckets)))] += 1;
                // Every EPP entries, writes a park
                if (table_index > 1) {
                    if (index % kEntriesPerPark == 0) {
                        if (index != 0) {
                            WriteParkToFile(final_table_writer, final_table_begin_pointers[table_index],
                                            park_index, park_size_bytes, checkpoint_line_point, park_deltas,
                                            park_stubs, k, table_index);
                            park_index += 1;
                            final_entries_written += (park_stubs.size() + 1);
                        }
                        park_deltas.clear();
                        park_stubs.clear();

                        checkpoint_line_point = line_point;
                    }
                    uint128_t big_delta = line_point - last_line_point;

                    // Since we have approx 2^k line_points between 0 and 2^2k, the average
                    // space between them when sorted, is k bits. Much more efficient than storing each
                    // line point. This is diveded into the stub and delta. The stub is the least
                    // significant (k-kMinusStubs) bits, and largely random/incompressible. The small delta is the rest,
                    // which can be efficiently encoded since it's usually very small.

                    uint64_t stub = big_delta % (((uint128_t)1) << (uint128_t)(k - kStubMinusBits));
                    uint64_t small_delta = (big_delta - stub) >> (k - kStubMinusBits);

                    assert(small_delta < 256);

                    if ((index % kEntriesPerPark != 0)) {
                        park_deltas.push_back(small_delta);
                        park_stubs.push_back(stub);
                    }
                    last_line_point = line_point;
                }
            }
            right_reader_2.close();
            right_writer_2.close();

            if (park_deltas.size() > 0) {
                // Since we don't have a perfect multiple of EPP entries, this writes the last ones
                WriteParkToFile(final_table_writer, final_table_begin_pointers[table_index],
                                park_index, park_size_bytes, checkpoint_line_point, park_deltas,
                                park_stubs, k, table_index);
                final_entries_written += (park_stubs.size() + 1);
            }

            if (table_index > 1) {
                std::cout << "\tWrote " << final_entries_written << " entries" << std::endl;
                final_table_begin_pointers[table_index + 1] = final_table_begin_pointers[table_index]
                                                          + (park_index + 1) * park_size_bytes;
            } else {
                final_entries_written = 0;
                uint8_t metadata_len = Util::ByteAlign(k) / 8;
                uint8_t buf[metadata_len];
                Bits num_entries(extra_metadata.size(), k);
                num_entries.ToBytes(buf);
                final_table_writer.write((const char*)buf, metadata_len);
                for (auto metadata: extra_metadata) {
                    Bits to_write(metadata, k);
                    to_write.ToBytes(buf);
                    final_table_writer.write((const char*)buf, metadata_len);
                    final_entries_written++;
                }
                std::cout << "\tWrote " << final_entries_written << " entries" << std::endl;
                final_table_begin_pointers[table_index + 1] = final_table_begin_pointers[table_index]
                                                              + (final_entries_written + 2) * metadata_len;
            }
            final_table_writer.seekp(header_size - 8 * (10 - table_index));
            uint8_t table_pointer_bytes[8*8];
            Bits(final_table_begin_pointers[table_index + 1], 8*8).ToBytes(table_pointer_bytes);
            final_table_writer.write(reinterpret_cast<char*>(table_pointer_bytes), 8);

            final_table_writer.close();

            computation_pass_2_timer.PrintElapsed("\tSecond computation pass time:");
            Timer sort_timer_2;
            std::cout << "\tRe-Sorting table " << int{table_index + 1} << std::endl;
            FileDisk d_2 = FileDisk(plot_filename);
            // This sort is needed so that in the next iteration, we can iterate through both tables
            // at ones. Note that sort_key represents y ordering, and the pos, offset coordinates from
            // forward/backprop represent positions in y ordered tables.
            Sorting::SortOnDisk(d_2, plot_table_begin_pointers[table_index + 1], spare_pointer,
                                right_entry_size_bytes, 0, new_bucket_sizes, memory, kMemorySize);
            d_2.Close();
            sort_timer_2.PrintElapsed("\tSort time:");

            delete[] right_entry_buf;
            delete[] left_entry_disk_buf;

            table_timer.PrintElapsed("Total compress table time:");
        }

        delete[] memory;

        // These results will be used to write table P7 and the checkpoint tables in phase 4.
        return Phase3Results{plot_table_begin_pointers, final_table_begin_pointers, final_entries_written,
                             right_entry_size_bytes * 8, header_size};
    }

    // Writes the checkpoint tables. The purpose of these tables, is to store a list of ~2^k values
    // of size k (the proof of space outputs from table 7), in a way where they can be looked up for
    // proofs, but also efficiently. To do this, we assume table 7 is sorted by f7, and we write the
    // deltas between each f7 (which will be mostly 1s and 0s), with a variable encoding scheme (C3).
    // Furthermore, we create C1 checkpoints along the way.  For example, every 10,000 f7 entries,
    // we can have a C1 checkpoint, and a C3 delta encoded entry with 10,000 deltas.

    // Since we can't store all the checkpoints in
    // memory for large plots, we create checkpoints for the checkpoints (C2), that are meant to be
    // stored in memory during proving. For example, every 10,000 C1 entries, we can have a C2 entry.

    // The final table format for the checkpoints will be:
    // C1 (checkpoint values)
    // C2 (checkpoint values into)
    // C3 (deltas of f7s between C1 checkpoints)
    void WriteCTables(uint8_t k, uint8_t pos_size, std::string filename, std::string plot_filename,
                      Phase3Results& res) {
        std::ofstream final_file_writer_1(filename, std::ios::in | std::ios::out | std::ios::binary);
        std::ofstream final_file_writer_2(filename, std::ios::in | std::ios::out | std::ios::binary);
        std::ofstream final_file_writer_3(filename, std::ios::in | std::ios::out | std::ios::binary);
        std::ifstream plot_file_reader(plot_filename, std::ios::in | std::ios::binary);

        uint32_t P7_park_size = Util::ByteAlign((k+1) * kEntriesPerPark)/8;
        uint64_t number_of_p7_parks = ((res.final_entries_written == 0 ? 0 : res.final_entries_written - 1)
                                       / kEntriesPerPark) + 1;

        uint64_t begin_byte_C1 = res.final_table_begin_pointers[7] + number_of_p7_parks * P7_park_size;

        uint64_t total_C1_entries = ceil(res.final_entries_written /
                                         static_cast<double>(kCheckpoint1Interval));
        uint64_t begin_byte_C2 = begin_byte_C1 + (total_C1_entries + 1) * (Util::ByteAlign(k) / 8);
        uint64_t total_C2_entries = ceil(total_C1_entries / static_cast<double>(kCheckpoint2Interval));
        uint64_t begin_byte_C3 = begin_byte_C2 + (total_C2_entries + 1) * (Util::ByteAlign(k) / 8);

        uint32_t size_C3 = CalculateC3Size(k);
        uint64_t end_byte = begin_byte_C3 + (total_C1_entries) * size_C3;

        res.final_table_begin_pointers[8] = begin_byte_C1;
        res.final_table_begin_pointers[9] = begin_byte_C2;
        res.final_table_begin_pointers[10] = begin_byte_C3;
        res.final_table_begin_pointers[11] = end_byte;

        plot_file_reader.seekg(res.plot_table_begin_pointers[7]);
        final_file_writer_1.seekp(begin_byte_C1);
        final_file_writer_2.seekp(begin_byte_C3);
        final_file_writer_3.seekp(res.final_table_begin_pointers[7]);

        uint64_t prev_y = 0;
        std::vector<Bits> C2;
        uint64_t num_C1_entries = 0;
        vector<uint8_t> deltas_to_write;
        uint32_t right_entry_size_bytes = res.right_entry_size_bits / 8;

        uint8_t* right_entry_buf = new uint8_t[right_entry_size_bytes];
        uint8_t* C1_entry_buf = new uint8_t[Util::ByteAlign(k) / 8];
        uint8_t* C3_entry_buf = new uint8_t[size_C3];
        uint8_t* P7_entry_buf = new uint8_t[P7_park_size];

        std::cout << "\tStarting to write C1 and C3 tables" << std::endl;

        ParkBits to_write_p7;

        // We read each table7 entry, which is sorted by f7, but we don't need f7 anymore. Instead,
        // we will just store pos6, and the deltas in table C3, and checkpoints in tables C1 and C2.
        for (uint64_t f7_position = 0; f7_position < res.final_entries_written; f7_position++) {
            plot_file_reader.read(reinterpret_cast<char*>(right_entry_buf),
                                  right_entry_size_bytes);
            uint64_t entry_y = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes, 0, k);
            uint64_t entry_new_pos = Util::SliceInt64FromBytes(right_entry_buf, right_entry_size_bytes, k, pos_size);

            Bits entry_y_bits = Bits(entry_y, k);

            if (f7_position % kEntriesPerPark == 0 && f7_position > 0) {
                memset(P7_entry_buf, 0, P7_park_size);
                to_write_p7.ToBytes(P7_entry_buf);
                final_file_writer_3.write(reinterpret_cast<char*>(P7_entry_buf), P7_park_size);
                to_write_p7 = ParkBits();
            }

            to_write_p7 += ParkBits(entry_new_pos, k+1);

            if (f7_position % kCheckpoint1Interval == 0) {
                entry_y_bits.ToBytes(C1_entry_buf);
                final_file_writer_1.write(reinterpret_cast<char*>(C1_entry_buf),
                                          Util::ByteAlign(k) / 8);
                if (num_C1_entries > 0) {
                    final_file_writer_2.seekp(begin_byte_C3 + (num_C1_entries - 1) * size_C3);
                    ParkBits to_write = Encoding::ANSEncodeDeltas(deltas_to_write, kC3R);

                    // We need to be careful because deltas are variable sized, and they need to fit
                    uint64_t num_bytes = (Util::ByteAlign(to_write.GetSize()) / 8) + 2;
                    assert(size_C3 * 8 > num_bytes);

                    // Write the size, and then the data
                    Bits(to_write.GetSize() / 8, 16).ToBytes(C3_entry_buf);
                    to_write.ToBytes(C3_entry_buf + 2);

                    final_file_writer_2.write(reinterpret_cast<char*>(C3_entry_buf), num_bytes);
                }
                prev_y = entry_y;
                if (f7_position % (kCheckpoint1Interval * kCheckpoint2Interval) == 0) {
                    C2.emplace_back(std::move(entry_y_bits));
                }
                deltas_to_write.clear();
                ++num_C1_entries;
            } else {
                if (entry_y == prev_y) {
                    deltas_to_write.push_back(0);
                } else {
                    deltas_to_write.push_back(entry_y - prev_y);
                }
                prev_y = entry_y;
            }
        }

        // Writes the final park to disk
        memset(P7_entry_buf, 0, P7_park_size);
        to_write_p7.ToBytes(P7_entry_buf);

        final_file_writer_3.write(reinterpret_cast<char*>(P7_entry_buf), P7_park_size);

        if (deltas_to_write.size() != 0) {
            ParkBits to_write = Encoding::ANSEncodeDeltas(deltas_to_write, kC3R);
            memset(C3_entry_buf, 0, size_C3);
            final_file_writer_2.seekp(begin_byte_C3 + (num_C1_entries - 1) * size_C3);

            // Writes the size, and then the data
            Bits(to_write.GetSize() / 8, 16).ToBytes(C3_entry_buf);
            to_write.ToBytes(C3_entry_buf + 2);


            final_file_writer_2.write(reinterpret_cast<char*>(C3_entry_buf), size_C3);
        }

        Bits(0, Util::ByteAlign(k)).ToBytes(C1_entry_buf);
        final_file_writer_1.write(reinterpret_cast<char*>(C1_entry_buf),
                                  Util::ByteAlign(k)/8);
        std::cout << "\tFinished writing C1 and C3 tables" << std::endl;
        std::cout << "\tWriting C2 table" << std::endl;

        for (Bits& C2_entry : C2) {
            C2_entry.ToBytes(C1_entry_buf);
            final_file_writer_1.write(reinterpret_cast<char*>(C1_entry_buf),
                                      Util::ByteAlign(k)/8);
        }
        Bits(0, Util::ByteAlign(k)).ToBytes(C1_entry_buf);
        final_file_writer_1.write(reinterpret_cast<char*>(C1_entry_buf),
                                  Util::ByteAlign(k)/8);
        std::cout << "\tFinished writing C2 table" << std::endl;

        delete[] C3_entry_buf;
        delete[] C1_entry_buf;
        delete[] P7_entry_buf;
        delete[] right_entry_buf;

        final_file_writer_1.seekp(res.header_size - 8 * 3);
        uint8_t table_pointer_bytes[8*8];

        // Writes the pointers to the start of the tables, for proving
        Bits(res.final_table_begin_pointers[8], 8*8).ToBytes(table_pointer_bytes);
        final_file_writer_1.write(reinterpret_cast<char*>(table_pointer_bytes), 8);
        Bits(res.final_table_begin_pointers[9], 8*8).ToBytes(table_pointer_bytes);
        final_file_writer_1.write(reinterpret_cast<char*>(table_pointer_bytes), 8);
        Bits(res.final_table_begin_pointers[10], 8*8).ToBytes(table_pointer_bytes);
        final_file_writer_1.write(reinterpret_cast<char*>(table_pointer_bytes), 8);

        plot_file_reader.close();
        final_file_writer_1.close();
        final_file_writer_2.close();
        final_file_writer_3.close();

        std::cout << "\tFinal table pointers:" << std::endl;

        std::cout << "\tP1: 0x" << std::hex << res.final_table_begin_pointers[1] << std::endl;
        std::cout << "\tP2: 0x" << res.final_table_begin_pointers[2] << std::endl;
        std::cout << "\tP3: 0x" << res.final_table_begin_pointers[3] << std::endl;
        std::cout << "\tP4: 0x" << res.final_table_begin_pointers[4] << std::endl;
        std::cout << "\tP5: 0x" << res.final_table_begin_pointers[5] << std::endl;
        std::cout << "\tP6: 0x" << res.final_table_begin_pointers[6] << std::endl;
        std::cout << "\tP7: 0x" << res.final_table_begin_pointers[7] << std::endl;
        std::cout << "\tC1: 0x" << res.final_table_begin_pointers[8] << std::endl;
        std::cout << "\tC2: 0x" << res.final_table_begin_pointers[9] << std::endl;
        std::cout << "\tC3: 0x" << res.final_table_begin_pointers[10] << std::dec << std::endl;
    }

    void BuildExtraStorage(int k, uint8_t* id, string filename, std::vector<uint64_t>& extra_metadata) {
        Attacker attacker(pow(2, ((double)k * 2 / 3)), pow(2, ((double)k / 3)), (1LL << k), 5, id);

        std::ofstream filename_stream(filename, std::ios::out | std::ios::trunc | std::ios::binary);
        if (!filename_stream.is_open()) {
            throw std::string("File not opened correct");
        }
        filename_stream.close();

        attacker.BuildTable();
        std::cout << "Hellman table complete" << std::endl;
        attacker.BuildDiskExtraStorage(filename, extra_metadata);
        std::cout << "Disk Extra storage complete" << std::endl;
    }
};

#endif  // SRC_CPP_PLOTTER_DISK_HPP_
