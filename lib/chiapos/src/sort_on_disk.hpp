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

#ifndef SRC_CPP_SORT_ON_DISK_HPP_
#define SRC_CPP_SORT_ON_DISK_HPP_

#define BUF_SIZE 262144

#include <vector>
#include <iostream>
#include <fstream>
#include <string>
#include <algorithm>
#include "./util.hpp"

class SortOnDiskUtils {
 public:
    /*
     * Given an array of bytes, extracts an unsigned 64 bit integer from the given
     * index, to the given index.
     */
    inline static uint64_t ExtractNum(uint8_t* bytes, uint32_t len_bytes, uint32_t begin_bits, uint32_t take_bits) {
        uint32_t start_index = begin_bits / 8;
        uint32_t end_index;
        if ((begin_bits + take_bits) / 8 > len_bytes - 1) {
            take_bits = (len_bytes * 8) - begin_bits;
        }
        end_index = (begin_bits + take_bits) / 8;

        assert(take_bits <= 64);
        uint64_t sum = bytes[start_index] & ((1 << (8 - (begin_bits % 8))) - 1);
        for (uint32_t i = start_index + 1; i <= end_index; i++) {
            sum = (sum << 8) + bytes[i];
        }
        return sum >> (8 - ((begin_bits + take_bits) % 8));
    }

    /*
     * Like memcmp, but only compares starting at a certain bit.
     */
    inline static int MemCmpBits(uint8_t* left_arr, uint8_t* right_arr, uint32_t len, uint32_t bits_begin) {
        uint32_t start_byte = bits_begin / 8;
        uint8_t mask = ((1 << (8 - (bits_begin % 8))) - 1);
        if ((left_arr[start_byte] & mask) != (right_arr[start_byte] & mask)) {
            return (left_arr[start_byte] & mask) - (right_arr[start_byte] & mask);
        }

        for (uint32_t i = start_byte + 1; i < len; i++) {
            if (left_arr[i] != right_arr[i])
                return left_arr[i] - right_arr[i];
        }
        return 0;
    }

    // The number of memory entries required to do the custom SortInMemory algorithm, given the total number of entries to be sorted.
    inline static uint64_t RoundSize(uint64_t size) {
        size *= 2;
        uint64_t result = 1;
        while (result < size)
            result *= 2;
        return result + 50;
    }

    inline static bool IsPositionEmpty(uint8_t* memory, uint32_t entry_len) {
        for (uint32_t i = 0; i < entry_len; i++)
            if (memory[i] != 0)
                return false;
        return true;
    }
};

class Disk {
 public:
    virtual void Read(uint64_t begin, uint8_t* memcache, uint32_t length) = 0;
    virtual void Write(uint64_t begin, uint8_t* memcache, uint32_t length) = 0;
    virtual std::iostream* ReadHandle(uint64_t begin) = 0;
    virtual std::iostream* WriteHandle(uint64_t begin) = 0;
};

class FileDisk : public Disk {
 public:
    inline explicit FileDisk(std::string filename) {
        Initialize(filename);
    }

    inline void Close() {
        f_.close();
    }

    inline void Read(uint64_t begin, uint8_t* memcache, uint32_t length) {
        // Seek, read, and replace into memcache
        f_.seekg(begin);
        f_.read(reinterpret_cast<char*>(memcache), length);
    }

    inline void Write(uint64_t begin, uint8_t* memcache, uint32_t length) {
        // Seek and write from memcache
        f_.seekp(begin);
        f_.write(reinterpret_cast<char*>(memcache), length);
    }

    /**
     * Returns a read handle at the specified byte offset from the beginning
     */
    inline std::iostream* ReadHandle(uint64_t begin) {
        f_.seekg(begin);
        return &f_;
    }

    inline std::iostream* WriteHandle(uint64_t begin) {
        f_.seekp(begin);
        return &f_;
    }

    inline std::string GetFileName() const {
        return filename_;
    }

 private:
    void Initialize(std::string filename) {
        filename_ = filename;

        // Creates the file if it does not exist
        std::fstream f;

        f.open(filename, std::fstream::out | std::fstream::app);
        f << std::flush;
        f.close();

        // Opens the file for reading and writing
        f_.open(filename, std::fstream::out | std::fstream::in | std::fstream::binary);

        // Sets the buffer for batched reading and writing
        f_.rdbuf()->pubsetbuf(buf_, BUF_SIZE);

        if (!f_.is_open()) {
            std::cout << "Fialed to open" << std::endl;
            throw std::string("File not opened correct");
        }
    }

    std::string filename_;
    char buf_[BUF_SIZE];
    std::fstream f_;
};

// Store values bucketed by their leading bits into an array-like memcache.
// The memcache stores stacks of values, one for each bucket.
// The stacks are broken into segments, where each segment has content
// all from the same bucket, and a 4 bit pointer to its previous segment.
// The most recent segment is the head segment of that bucket.
// Additionally, empty segments form a linked list: 4 bit pointers of
// empty segments point to the next empty segment in the memcache.
// Each segment has size entries_per_seg * entry_len + 4, and consists of:
// [4 bit pointer to segment id] + [entries of length entry_len]*

class BucketStore {
 public:
    inline BucketStore(uint8_t* mem, uint64_t mem_len, uint32_t entry_len,
                       uint32_t bits_begin, uint32_t bucket_log, uint64_t entries_per_seg) {
        mem_ = mem;
        mem_len_ = mem_len;
        entry_len_ = entry_len;
        bits_begin_ = bits_begin;
        bucket_log_ = bucket_log;
        entries_per_seg_ = entries_per_seg;

        for (uint64_t i = 0; i < pow(2, bucket_log); i++) {
            bucket_sizes_.push_back(0);
        }

        seg_size_ = 4 + entry_len_ * entries_per_seg;

        length_ = floor(mem_len / seg_size_);

        // Initially, all the segments are empty, store them as a linked list,
        // where a segment points to the next empty segment.
        for (uint64_t i = 0; i < length_; i++) {
            SetSegmentId(i, i + 1);
        }

        // The head of the empty segments list.
        first_empty_seg_id_ = 0;

        // Initially, all bucket lists contain no segments in it.
        for (uint64_t i = 0; i < bucket_sizes_.size(); i++) {
            bucket_head_ids_.push_back(length_);
            bucket_head_counts_.push_back(0);
        }
    }

    inline void SetSegmentId(uint64_t i, uint64_t v) {
        Util::IntToFourBytes(mem_ + i * seg_size_, v);
    }

    inline uint64_t GetSegmentId(uint64_t i) {
        return Util::FourBytesToInt(mem_ + i * seg_size_);
    }

    // Get the first empty position from the head segment of bucket b.
    inline uint64_t GetEntryPos(uint64_t b) {
        return bucket_head_ids_[b] * seg_size_ + 4
               + bucket_head_counts_[b] * entry_len_;
    }

    inline void Audit() {
        uint64_t count = 0;
        uint64_t pos = first_empty_seg_id_;

        while (pos != length_) {
            ++count;
            pos = GetSegmentId(pos);
        }
        for (uint64_t pos2 : bucket_head_ids_) {
            while (pos2 != length_) {
                ++count;
                pos2 = GetSegmentId(pos2);
            }
        }
        assert(count == length_);
    }

    inline uint64_t NumFree() {
        uint64_t used = GetSegmentId(first_empty_seg_id_);
        return (bucket_sizes_.size() - used) * entries_per_seg_;
    }

    inline bool IsEmpty() {
        for (uint64_t s : bucket_sizes_) {
            if (s > 0) return false;
        }
        return true;
    }

    inline bool IsFull() {
        return first_empty_seg_id_ == length_;
    }

    inline void Store(uint8_t* new_val, uint64_t new_val_len) {
        assert(new_val_len == entry_len_);
        assert(first_empty_seg_id_ != length_);
        uint64_t b = SortOnDiskUtils::ExtractNum(new_val, new_val_len, bits_begin_, bucket_log_);
        bucket_sizes_[b] += 1;

        // If bucket b contains no segments, or the head segment of bucket b is full, append a new segment.
        if (bucket_head_ids_[b] == length_ ||
                bucket_head_counts_[b] == entries_per_seg_) {
            uint64_t old_seg_id = bucket_head_ids_[b];
            // Set the head of the bucket b with the first empty segment (thus appending a new segment to the bucket b).
            bucket_head_ids_[b] = first_empty_seg_id_;
            // Move the first empty segment to the next empty one
            // (which is linked with the first empty segment using id, since empty segments
            // form a linked list).
            first_empty_seg_id_ = GetSegmentId(first_empty_seg_id_);
            // Link the head of bucket b to the previous head (in the linked list,
            // the segment that will follow the new head will be the previous head).
            SetSegmentId(bucket_head_ids_[b], old_seg_id);
            bucket_head_counts_[b] = 0;
        }

        // Get the first empty position inside the head segment and write the entry there.
        uint64_t pos = GetEntryPos(b);
        memcpy(mem_ + pos, new_val, entry_len_);
        bucket_head_counts_[b] += 1;
    }

    inline uint64_t MaxBucket() {
        uint64_t max_bucket_size = bucket_sizes_[0];
        uint64_t max_index = 0;
        for (uint64_t i = 1; i < bucket_sizes_.size(); i++) {
            if (bucket_sizes_[i] > max_bucket_size) {
                max_bucket_size = bucket_sizes_[i];
                max_index = i;
            }
        }
        return max_index;
    }

    inline std::vector<uint64_t> BucketsBySize() {
        // Lukasz Wiklendt (https://stackoverflow.com/questions/1577475/c-sorting-and-keeping-track-of-indexes)
        std::vector<uint64_t> idx(bucket_sizes_.size());
        iota(idx.begin(), idx.end(), 0);
        sort(idx.begin(), idx.end(),
             [this](uint64_t i1, uint64_t i2) {return bucket_sizes_[i1] > bucket_sizes_[i2];});
        return idx;
    }

    // Similar to how 'Bits' class works, appends an entry to the entries list, such as all entries are stored into 128-bit blocks.
    // Bits class was avoided since it consumes more time than a uint128_t array.
    void AddBucketEntry(uint8_t* big_endian_bytes, uint64_t num_bytes, uint16_t size_bits, uint128_t* entries, uint64_t& cnt) {
        assert(size_bits / 8 >= num_bytes);
        uint16_t extra_space = size_bits - num_bytes * 8;
        uint64_t init_cnt = cnt;
        uint16_t last_size = 0;
        while (extra_space >= 128) {
            extra_space -= 128;
            entries[cnt++] = 0;
            last_size = 128;
        }
        if (extra_space > 0) {
            entries[cnt++] = 0;
            last_size = extra_space;
        }
        for (uint64_t i = 0; i < num_bytes; i += 16) {
            uint128_t val = 0;
            uint8_t bucket_size = 0;
            for (uint64_t j = i; j < i + 16 && j < num_bytes; j++) {
                val = (val << 8) + big_endian_bytes[j];
                bucket_size += 8;
            }
            if (cnt == init_cnt || last_size == 128) {
                entries[cnt++] = val;
                last_size = bucket_size;
            } else {
                uint8_t free_space = 128 - last_size;
                if (free_space >= bucket_size) {
                    entries[cnt - 1] = (entries[cnt - 1] << bucket_size) + val;
                    last_size += bucket_size;
                } else {
                    uint8_t suffix_size = bucket_size - free_space;
                    uint128_t mask = (static_cast<uint128_t>(1)) << suffix_size;
                    mask--;
                    uint128_t suffix = (val & mask);
                    uint128_t prefix = (val >> suffix_size);
                    entries[cnt - 1] = (entries[cnt - 1] << free_space) + prefix;
                    entries[cnt++] = suffix;
                    last_size = suffix_size;
                }
            }
        }
    }

    // Extracts 'number_of_entries' from bucket b and empties memory of those from BucketStore.
    inline uint128_t* BucketHandle(uint64_t b, uint64_t number_of_entries, uint64_t& final_size) {
        uint32_t L = entry_len_;
        uint32_t entry_size = L / 16;
        if (L % 16)
            ++entry_size;
        uint64_t cnt = 0;
        uint64_t cnt_entries = 0;
        // Entry bytes will be compressed into uint128_t array.
        uint128_t* entries = new uint128_t[number_of_entries * entry_size];

        // As long as we have a head segment in bucket b...
        while (bucket_head_ids_[b] != length_) {
            // ...extract the entries from it.
            uint64_t start_pos = GetEntryPos(b) - L;
            uint64_t end_pos = start_pos - bucket_head_counts_[b] * L;
            for (uint64_t pos = start_pos; pos > end_pos + L; pos -=L) {
                bucket_sizes_[b] -= 1;
                bucket_head_counts_[b] -= 1;
                AddBucketEntry(mem_ + pos, L, L*8, entries, cnt);
                ++cnt_entries;
                if (cnt_entries == number_of_entries) {
                    final_size = cnt;
                    return entries;
                }
            }

            // Move to the next segment from bucket b.
            uint64_t next_full_seg_id = GetSegmentId(bucket_head_ids_[b]);
            // The processed segment becomes now an empty segment.
            SetSegmentId(bucket_head_ids_[b], first_empty_seg_id_);
            first_empty_seg_id_ = bucket_head_ids_[b];
            // Change the head of bucket b.
            bucket_head_ids_[b] = next_full_seg_id;

            if (next_full_seg_id == length_) {
                bucket_head_counts_[b] = 0;
            } else {
                bucket_head_counts_[b] = entries_per_seg_;
            }

            if (start_pos != end_pos) {
                bucket_sizes_[b] -= 1;
                AddBucketEntry(mem_ + end_pos + L, L, L*8, entries, cnt);
                ++cnt_entries;
                if (cnt_entries == number_of_entries) {
                    final_size = cnt;
                    return entries;
                }
            }
        }

        assert(bucket_sizes_[b] == 0);
        final_size = cnt;
        return entries;
    }

 private:
    uint8_t* mem_;
    uint64_t mem_len_;
    uint32_t bits_begin_;
    uint32_t entry_len_;
    uint32_t bucket_log_;
    uint64_t entries_per_seg_;
    std::vector<uint64_t> bucket_sizes_;
    uint64_t seg_size_;
    uint64_t length_;
    uint64_t first_empty_seg_id_;
    std::vector<uint64_t> bucket_head_ids_;
    std::vector<uint64_t> bucket_head_counts_;
};

class Sorting {
 public:
    static void EntryToBytes(uint128_t* entries, uint32_t start_pos, uint32_t end_pos, uint8_t last_size, uint8_t buffer[]) {
        uint8_t shift = Util::ByteAlign(last_size) - last_size;
        uint128_t val = entries[end_pos - 1] << (shift);
        uint16_t cnt = 0;
        uint8_t iterations = last_size / 8;
        if (last_size % 8)
            iterations++;
        for (uint8_t i = 0; i < iterations; i++) {
            buffer[cnt++] = (val & 0xff);
            val >>= 8;
        }

        if (end_pos - start_pos >= 2) {
            for (int32_t i = end_pos - 2; i >= (int32_t) start_pos; i--) {
                uint128_t val = entries[i];
                for (uint8_t j = 0; j < 16; j++) {
                    buffer[cnt++] = (val & 0xff);
                    val >>= 8;
                }
            }
        }
        uint32_t left = 0, right = cnt - 1;
        while (left <= right) {
            std::swap(buffer[left], buffer[right]);
            left++;
            right--;
        }
    }

    inline static void SortOnDisk(Disk& disk, uint64_t disk_begin, uint64_t spare_begin,
                                  uint32_t entry_len, uint32_t bits_begin, std::vector<uint64_t> bucket_sizes,
                                  uint8_t* mem, uint64_t mem_len, int quicksort = 0) {
        uint64_t length = floor(mem_len / entry_len);
        uint64_t total_size = 0;
        // bucket_sizes[i] represent how many entries start with the prefix i (from 0000 to 1111).
        // i.e. bucket_sizes[10] represents how many entries start with the prefix 1010.
        for (auto& n : bucket_sizes) total_size += n;
        uint64_t N_buckets = bucket_sizes.size();

        assert(disk_begin + total_size * entry_len <= spare_begin);

        if (bits_begin >= entry_len * 8) {
            return;
        }

        // If we have enough memory to sort the entries, do it.

        // How much an entry occupies in memory, without the common prefix, in SortInMemory algorithm.
        uint32_t entry_len_memory = entry_len - bits_begin / 8;

        // Are we in Compress phrase 1 (quicksort=1) or is it the last bucket (quicksort=2)? Perform quicksort if it
        // fits in the memory (SortInMemory algorithm won't always perform well).
        if (quicksort > 0 && total_size <= length) {
            disk.Read(disk_begin, mem, total_size * entry_len);
            QuickSort(mem, entry_len, total_size, bits_begin);
            disk.Write(disk_begin, mem, total_size * entry_len);
            return ;
        }
        // Do SortInMemory algorithm if it fits in the memory
        // (number of entries required * entry_len_memory) <= total memory available
        if (quicksort == 0 && SortOnDiskUtils::RoundSize(total_size) * entry_len_memory <= mem_len) {
            SortInMemory(disk, disk_begin, mem, entry_len, total_size, bits_begin);
            return;
        }

        std::vector<uint64_t> bucket_begins;
        bucket_begins.push_back(0);
        uint64_t total = 0;

        // The beginning of each bucket. The first entry from bucket i will always be written on disk on position
        // disk_begin + bucket_begins[i] * entry_len, the second one will be written on position
        // disk_begin + (bucket_begins[i] + 1) * entry_len and so on. This way, when all entries are written back
        // to disk, they will be sorted by the first 4 bits (the bucket) at the end.
        for (uint64_t i = 0; i < N_buckets - 1; i++) {
            total += bucket_sizes[i];
            bucket_begins.push_back(total);
        }

        uint32_t bucket_log = Util::GetSizeBits(N_buckets) - 1;

        // Move the beginning of each bucket into the spare.
        uint64_t spare_written = 0;
        std::vector<uint64_t> consumed_per_bucket(N_buckets, 0);

        // The spare stores about 5 * N_buckets * len(mem) entries.
        uint64_t unit = floor(length / static_cast<double>(N_buckets) * 5);

        for (uint32_t i = 0; i < bucket_sizes.size(); i++) {
            uint64_t b_size = bucket_sizes[i];
            uint64_t to_consume = std::min(unit, b_size);

            while (to_consume > 0) {
                uint64_t next_amount = std::min(length, to_consume);
                disk.Read(disk_begin + (bucket_begins[i] + consumed_per_bucket[i]) * entry_len,
                          mem, next_amount * entry_len);
                disk.Write(spare_begin + spare_written * entry_len,
                           mem, next_amount * entry_len);
                to_consume -= next_amount;
                spare_written += next_amount;
                consumed_per_bucket[i] += next_amount;
            }
        }

        uint64_t spare_consumed = 0;
        BucketStore bstore = BucketStore(mem, mem_len, entry_len, bits_begin, bucket_log, 100);
        std::iostream* handle = disk.ReadHandle(spare_begin);

        uint8_t* buf = new uint8_t[entry_len];

        // Populate BucketStore from spare.
        while (!bstore.IsFull() && spare_consumed < spare_written) {
            handle->read(reinterpret_cast<char*>(buf), entry_len);
            bstore.Store(buf, entry_len);
            spare_consumed += 1;
        }

        // subbuckets[i][j] represents how many entries starting with prefix i has the next prefix equal to j.
        // When we'll call recursively for all entries starting with the prefix i, bucket_sizes[] becomes
        // subbucket_sizes[i].
        std::vector<uint64_t> written_per_bucket(N_buckets, 0);
        std::vector<std::vector<uint64_t> > subbucket_sizes;
        for (uint64_t i = 0; i < N_buckets; i++) {
            std::vector<uint64_t> col(N_buckets, 0);
            subbucket_sizes.push_back(col);
        }

        while (!bstore.IsEmpty()) {
            // Write from BucketStore the heaviest buckets first (so it empties faster)
            for (uint64_t b : bstore.BucketsBySize()) {
                if (written_per_bucket[b] >= consumed_per_bucket[b]) {
                    continue;
                }
                // Write the content of the bucket in the right spot (beginning of the bucket + number of entries already written
                // in that bucket).
                handle = disk.WriteHandle(disk_begin + (bucket_begins[b] + written_per_bucket[b]) * entry_len);
                uint64_t size;
                // Don't extract from the bucket more entries than the difference between read and written entries (this avoids
                // overwritting entries that were not read yet).
                uint128_t* bucket_handle = bstore.BucketHandle(b, consumed_per_bucket[b] - written_per_bucket[b], size);
                uint32_t entry_size = entry_len / 16;
                uint8_t last_size = (entry_len * 8) % 128;
                if (last_size == 0)
                    last_size = 128;
                if (entry_len % 16)
                    ++entry_size;
                for (uint64_t i = 0; i < size; i += entry_size) {
                    EntryToBytes(bucket_handle, i, i + entry_size, last_size, buf);
                    handle->write(reinterpret_cast<char*>(buf), entry_len);
                    written_per_bucket[b] += 1;
                    subbucket_sizes[b][SortOnDiskUtils::ExtractNum(buf, entry_len, bits_begin +
                                                                   bucket_log, bucket_log)] += 1;
                }
                delete[] bucket_handle;
            }

            // Advance the read handle into buckets and move read entries to BucketStore. We read first from buckets
            // with the smallest difference between read and write handles. The goal is to increase the smaller differences.
            // The bigger the difference is, the better, as in the next step, we'll be able to extract more from the BucketStore.
            std::vector<uint64_t> idx(bucket_sizes.size());
            iota(idx.begin(), idx.end(), 0);
            sort(idx.begin(), idx.end(),
                [&consumed_per_bucket, &written_per_bucket](uint64_t i1, uint64_t i2) {
                    return (consumed_per_bucket[i1] - written_per_bucket[i1] <
                            consumed_per_bucket[i2] - written_per_bucket[i2]);
                 });

            bool broke = false;
            for (uint64_t i : idx) {
                if (consumed_per_bucket[i] == bucket_sizes[i]) {
                    continue;
                }
                std::iostream* handle2 = disk.ReadHandle(
                    disk_begin + (bucket_begins[i] + consumed_per_bucket[i]) * entry_len);
                while (!bstore.IsFull() && consumed_per_bucket[i] < bucket_sizes[i]) {
                    handle2->read(reinterpret_cast<char*>(buf), entry_len);
                    bstore.Store(buf, entry_len);
                    consumed_per_bucket[i] += 1;
                }
                if (bstore.IsFull()) {
                    broke = true;
                    break;
                }
            }

            // If BucketStore still isn't full and we've read all entries from buckets, start populating from the spare space.
            if (!broke) {
                std::iostream* handle3 = disk.ReadHandle(
                    spare_begin + spare_consumed * entry_len);
                while (!bstore.IsFull() && spare_consumed < spare_written) {
                    handle3->read(reinterpret_cast<char*>(buf), entry_len);
                    bstore.Store(buf, entry_len);
                    spare_consumed += 1;
                }
            }
        }
        delete[] buf;

        // The last bucket that contains at least one entry.
        uint8_t last_bucket = N_buckets - 1;
        while (last_bucket > 0) {
            bool all_zero = true;
            for (uint64_t i = 0; i < N_buckets; i++)
                if (subbucket_sizes[last_bucket][i] != 0)
                    all_zero = false;
            if (!all_zero)
                break;
            last_bucket--;
        }
        for (uint32_t i = 0; i < bucket_sizes.size(); i++) {
            // Do we have to do quicksort for the new partition?
            int new_quicksort;
            // If quicksort = 1, means all partitions must do the quicksort as their final step.
            // Preserve that for the new call.
            if (quicksort == 1) {
                new_quicksort = 1;
            } else {
                // If this is not the last bucket, we use the SortInMemoryAlgorithm
                if (i != last_bucket) {
                    new_quicksort = 0;
                } else {
                    // ..otherwise, do quicksort, as the last bucket isn't guaranteed to have uniform distribution.
                    new_quicksort = 2;
                }
            }
            // At this point, all entries are sorted in increasing order by their buckets (4 bits prefixes).
            // We recursively sort each chunk, this time starting with the next 4 bits to determine the buckets.
            // (i.e. firstly, we sort entries starting with 0000, then entries starting with 0001, ..., then entries
            // starting with 1111, at the end producing the correct ordering).
            SortOnDisk(disk, disk_begin + bucket_begins[i] * entry_len, spare_begin,
                       entry_len, bits_begin + bucket_log, subbucket_sizes[i], mem, mem_len, new_quicksort);
        }
    }

    inline static void SortInMemory(Disk& disk, uint64_t disk_begin, uint8_t* memory, uint32_t entry_len,
                                    uint64_t num_entries, uint32_t bits_begin) {
        uint32_t entry_len_memory = entry_len - bits_begin / 8;
        uint64_t memory_len = SortOnDiskUtils::RoundSize(num_entries) * entry_len_memory;
        uint8_t* swap_space = new uint8_t[entry_len];
        uint8_t* buffer = new uint8_t[BUF_SIZE];
        uint8_t* common_prefix = new uint8_t[bits_begin / 8];
        uint64_t bucket_length = 0;
        bool set_prefix = false;
        // The number of buckets needed (the smallest power of 2 greater than 2 * num_entries).
        while ((1ULL << bucket_length) < 2 * num_entries)
            bucket_length++;
        memset(memory, 0, sizeof(memory[0])*memory_len);

        std::iostream* read_handle = disk.ReadHandle(disk_begin);
        uint64_t buf_size = 0;
        uint64_t buf_ptr = 0;
        uint64_t swaps = 0;
        for (uint64_t i = 0; i < num_entries; i++) {
            if (buf_size == 0) {
                // If read buffer is empty, read from disk and refill it.
                buf_size = std::min((uint64_t) BUF_SIZE / entry_len, num_entries - i);
                buf_ptr = 0;
                read_handle->read(reinterpret_cast<char*>(buffer), buf_size * entry_len);
                if (set_prefix == false) {
                    // We don't store the common prefix of all entries in memory, instead just append it every time
                    // in write buffer.
                    memcpy(common_prefix, buffer, bits_begin / 8);
                    set_prefix = true;
                }
            }
            buf_size--;
            // First unique bits in the entry give the expected position of it in the sorted array.
            // We take 'bucket_length' bits starting with the first unique one.
            uint64_t pos = SortOnDiskUtils::ExtractNum(buffer + buf_ptr, entry_len, bits_begin, bucket_length) * entry_len_memory;
            // As long as position is occupied by a previous entry...
            while (SortOnDiskUtils::IsPositionEmpty(memory + pos, entry_len_memory) == false && pos < memory_len) {
                // ...store there the minimum between the two and continue to push the higher one.
                if (SortOnDiskUtils::MemCmpBits(memory + pos, buffer + buf_ptr + bits_begin / 8, entry_len_memory, 0) > 0) {
                    // We always store the entry without the common prefix.
                    memcpy(swap_space, memory + pos, entry_len_memory);
                    memcpy(memory + pos, buffer + buf_ptr + bits_begin / 8, entry_len_memory);
                    memcpy(buffer + buf_ptr + bits_begin / 8, swap_space, entry_len_memory);
                    swaps++;
                }
                pos += entry_len_memory;
            }
            // Push the entry in the first free spot.
            memcpy(memory + pos, buffer + buf_ptr + bits_begin / 8, entry_len_memory);
            buf_ptr += entry_len;
        }
        uint64_t entries_written = 0;
        buf_size = 0;
        memset(buffer, 0, BUF_SIZE);
        std::iostream* write_handle = disk.WriteHandle(disk_begin);
        // Search the memory buffer for occupied entries.
        for (uint64_t pos = 0; entries_written < num_entries && pos < memory_len; pos += entry_len_memory) {
            if (SortOnDiskUtils::IsPositionEmpty(memory + pos, entry_len_memory) == false) {
                // We've fount an entry.
                if (buf_size + entry_len >= BUF_SIZE) {
                    // Write buffer is full, write it and clean it.
                    write_handle->write(reinterpret_cast<char*>(buffer), buf_size);
                    entries_written += buf_size / entry_len;
                    buf_size = 0;
                }
                // Write first the common prefix of all entries.
                memcpy(buffer + buf_size, common_prefix, bits_begin / 8);
                // Then the stored entry itself.
                memcpy(buffer + buf_size + bits_begin / 8, memory + pos, entry_len_memory);
                buf_size += entry_len;
            }
        }
        // We still have some entries left in the write buffer, write them as well.
        if (buf_size > 0) {
            write_handle->write(reinterpret_cast<char*>(buffer), buf_size);
            entries_written += buf_size / entry_len;
        }
        assert(entries_written == num_entries);
        delete[] swap_space;
        delete[] buffer;
        delete[] common_prefix;
    }

    inline static void QuickSort(uint8_t* memory, uint32_t entry_len,
                                uint64_t num_entries, uint32_t bits_begin) {
        uint64_t memory_len = (uint64_t)entry_len * num_entries;
        uint8_t * pivot_space = new uint8_t[entry_len];
        QuickSortInner(memory, memory_len, entry_len, bits_begin, 0, num_entries, pivot_space);
        delete[] pivot_space;
    }

    inline static void CheckSortOnDisk(Disk& disk, uint64_t disk_begin, uint64_t spare_begin,
                                  uint32_t entry_len, uint32_t bits_begin, std::vector<uint64_t> bucket_sizes,
                                  uint8_t* mem, uint64_t mem_len, bool quicksort = false) {
        uint64_t length = floor(mem_len / entry_len);
        uint64_t total_size = 0;
        for (auto& n : bucket_sizes) total_size += n;

        cout << "CheckSortOnDisk entry_len: " << entry_len << " length: " << length << " total size: " << total_size << endl;
        for(uint64_t chunkindex=0;chunkindex<(total_size+length-1)/length;chunkindex++)
        {
            disk.Read(disk_begin+(chunkindex*length*entry_len), mem, length * entry_len);
            uint64_t i=1;
            while(((chunkindex*length+i)<total_size)&&(i<length))
            {
                if((chunkindex*length+i)%1000000==0)
                    cout << (chunkindex*length+i) << ": " << Util::HexStr(mem + i * entry_len, entry_len) << endl;
                if(SortOnDiskUtils::MemCmpBits(mem + (i - 1) * entry_len, mem + i * entry_len, entry_len, 0) >= 0)
                {
                    cout << "Bad sort!" << endl;
                }
                i++;
            }
        }
        cout << "CheckSortOnDisk OK" << endl;
    }

 private:
    inline static void QuickSortInner(uint8_t* memory, uint64_t memory_len,
                                         uint32_t L, uint32_t bits_begin,
                                         uint64_t begin, uint64_t end, uint8_t* pivot_space) {
        if (end - begin <= 5) {
            for (uint64_t i = begin + 1; i < end; i++) {
                uint64_t j = i;
                memcpy(pivot_space, memory + i * L, L);
                while (j > begin && SortOnDiskUtils::MemCmpBits(memory + (j - 1) * L, pivot_space, L, bits_begin) > 0) {
                    memcpy(memory + j * L, memory + (j - 1) * L, L);
                    j--;
                }
                memcpy(memory + j * L, pivot_space, L);
            }
            return ;
        }

        uint64_t lo = begin;
        uint64_t hi = end - 1;

        memcpy(pivot_space, memory + (hi * L), L);
        bool left_side = true;

        while (lo < hi) {
            if (left_side) {
                if (SortOnDiskUtils::MemCmpBits(memory + lo * L, pivot_space, L, bits_begin) < 0) {
                    ++lo;
                } else {
                    memcpy(memory + hi * L, memory + lo * L, L);
                    --hi;
                    left_side = false;
                }
            } else {
                if (SortOnDiskUtils::MemCmpBits(memory + hi * L, pivot_space, L, bits_begin) > 0) {
                    --hi;
                } else {
                    memcpy(memory + lo * L, memory + hi * L, L);
                    ++lo;
                    left_side = true;
                }
            }
        }
        memcpy(memory + lo * L, pivot_space, L);
        if (lo - begin <= end - lo) {
            QuickSortInner(memory, memory_len, L, bits_begin, begin, lo, pivot_space);
            QuickSortInner(memory, memory_len, L, bits_begin, lo + 1, end, pivot_space);
        } else {
            QuickSortInner(memory, memory_len, L, bits_begin, lo + 1, end, pivot_space);
            QuickSortInner(memory, memory_len, L, bits_begin, begin, lo, pivot_space);
        }
    }
};

#endif  // SRC_CPP_SORT_ON_DISK_HPP_
