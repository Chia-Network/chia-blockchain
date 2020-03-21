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

#ifndef SRC_CPP_BITS_HPP_
#define SRC_CPP_BITS_HPP_

#include <vector>
#include <algorithm>
#include <limits>
#include <string>
#include <utility>
#include "./util.hpp"
#include "./stack_allocator.h"


#define kBufSize 5

// 128 * 2^16. 2^16 values, each value can store 128 bits.
#define kMaxSizeBits 8388608

// A stack vector of length 5, having the functions of std::vector needed for Bits.
struct SmallVector {
    typedef uint16_t size_type;

    SmallVector() noexcept {
        count_ = 0;
    }

    uint128_t& operator[] (const uint16_t index) {
        return v_[index];
    }

    uint128_t operator[] (const uint16_t index) const {
        return v_[index];
    }

    void push_back(uint128_t value) {
        v_[count_++] = value;
    }

    SmallVector& operator = (const SmallVector& other) {
        count_ = other.count_;
        for (size_type i = 0; i < other.count_; i++)
            v_[i] = other.v_[i];
        return (*this);
    }

    size_type size() const noexcept {
        return count_;
    }

 private:
    uint128_t v_[5];
    size_type count_;
};


// A stack vector of length 1024, having the functions of std::vector needed for Bits.
// The max number of Bits that can be stored is 1024 * 128
struct ParkVector {
    typedef uint32_t size_type;

    ParkVector() noexcept {
        count_ = 0;
    }

    uint128_t& operator[] (const uint32_t index) {
        return v_[index];
    }

    uint128_t operator[] (const uint32_t index) const {
        return v_[index];
    }

    void push_back(uint128_t value) {
        v_[count_++] = value;
    }

    ParkVector& operator = (const ParkVector& other) {
        count_ = other.count_;
        for (size_type i = 0; i < other.count_; i++)
            v_[i] = other.v_[i];
        return (*this);
    }

    size_type size() const noexcept {
        return count_;
    }

 private:
    uint128_t v_[1024];
    size_type count_;
};

/*
 * This class represents an array of bits. These are stored in an
 * array of integers, allowing for efficient bit manipulations. The Bits class provides
 * utilities to easily work with Bits, adding and slicing them, etc.
 * The class is a generic one, allowing any type of an array, as long as providing std::vector methods.
 * We currently use SmallVector (stack-array of length 5), ParkVector (stack-array of length 128) and
 * std::vector.
 * Conversion between two BitsGeneric<T> classes of different types can be done by using += operator, or converting
 * to bytes the first class, then using the bytes constructor of the second class (should be slower).
 * NOTE: CalculateBucket only accepts a BitsGeneric<SmallVector>, so in order to use that, you have to firstly convert
 * your BitsGeneric<T> object into a BitsGeneric<SmallVector>.
*/

template <class T> class BitsGeneric {
 public:
    template <class> friend class BitsGeneric;

    BitsGeneric<T>() noexcept {
        this->last_size_ = 0;
    }


    // Converts from unit128_t to Bits. If the number of bits of value is smaller than size, adds 0 bits at the beginning.
    // i.e. Bits(5, 10) = 0000000101
    BitsGeneric<T>(uint128_t value, uint32_t size) {
        // TODO(mariano) remove
        if (size < 128 && value > ((uint128_t)1 << size)) {
            std::cout << "TOO BIG FOR BITS" << std::endl;
            // abort();
        }
        this->last_size_ = 0;
        if (size > 128) {
            // Get number of extra 0s added at the beginning.
            uint32_t zeros = size - Util::GetSizeBits(value);
            // Add a full group of 0s (length 128)
            while (zeros > 128) {
                AppendValue(0, 128);
                zeros -= 128;
            }
            // Add the incomplete group of 0s and then the value.
            AppendValue(0, zeros);
            AppendValue(value, Util::GetSizeBits(value));
        } else {
            values_.push_back(value);
            this->last_size_ = size;
        }
    }

    // Copy the content of another Bits object. If the size of the other Bits object is smaller
    // than 'size', adds 0 bits at the beginning.
    BitsGeneric<T>(const BitsGeneric<T>& other, uint32_t size) {
        uint32_t total_size = other.GetSize();
        this->last_size_ = 0;
        assert(size >= total_size);
        // Add the extra 0 bits at the beginning.
        uint32_t extra_space = size - total_size;
        while (extra_space >= 128) {
            AppendValue(0, 128);
            extra_space -= 128;
        }
        if (extra_space > 0)
            AppendValue(0, extra_space);
        // Copy the Bits object element by element, and append it to the current Bits object.
        if (other.values_.size() > 0) {
            for (uint32_t i = 0; i < other.values_.size() - 1; i++)
                AppendValue(other.values_[i], 128);
            AppendValue(other.values_[other.values_.size() - 1], other.last_size_);
        }
    }

    // Converts bytes to bits.
    BitsGeneric<T>(const uint8_t* big_endian_bytes, uint32_t num_bytes, uint32_t size_bits)  {
        this->last_size_ = 0;
        uint32_t extra_space = size_bits - num_bytes * 8;
        // Add the extra 0 bits at the beginning.
        while (extra_space >= 128) {
            AppendValue(0, 128);
            extra_space -= 128;
        }
        if (extra_space > 0) {
            AppendValue(0, extra_space);
        }
        for (uint32_t i = 0; i < num_bytes; i += 16) {
            uint128_t val = 0;
            uint8_t bucket_size = 0;
            // Compress bytes together into uint128_t, either until we have 128 bits, or until we run out of bytes
            // in big_endian_bytes.
            for (uint32_t j = i; j < i + 16 && j < num_bytes; j++) {
                val = (val << 8) + big_endian_bytes[j];
                bucket_size += 8;
            }
            AppendValue(val, bucket_size);
        }
    }

    BitsGeneric<T>(const BitsGeneric<T>& other) noexcept :
        values_(other.values_),
        last_size_(other.last_size_)
    {
    }

    BitsGeneric<T>& operator = (const BitsGeneric<T>& other) {
        values_ = other.values_;
        last_size_ = other.last_size_;
        return *this;
    }

    // Concatenates two Bits objects together.
    BitsGeneric<T> operator+(const BitsGeneric<T>& b) const {
        if (GetSize() + b.GetSize() > kMaxSizeBits) {
            throw std::string("The number of bits exceeds the limit.");
        }
        BitsGeneric<T> result;
        if (values_.size() > 0) {
            for (typename T::size_type i = 0; i < values_.size() - 1; i++)
                result.AppendValue(values_[i], 128);
            result.AppendValue(values_[values_.size() - 1], last_size_);
        }
        if (b.values_.size() > 0) {
            for (typename T::size_type i = 0; i < b.values_.size() - 1; i++)
                result.AppendValue(b.values_[i], 128);
            result.AppendValue(b.values_[b.values_.size() - 1], b.last_size_);
        }
        return result;
    }

    // Appends one Bits object at the end of the first one.
    template <class T2>
    BitsGeneric<T>& operator += (const BitsGeneric<T2>& b) {
        if (b.values_.size() > 0) {
             for (typename T2::size_type i = 0; i < b.values_.size() - 1; i++)
                this->AppendValue(b.values_[i], 128);
            this->AppendValue(b.values_[b.values_.size() - 1], b.last_size_);
        }
        return *this;
    }  

    BitsGeneric<T>& operator++() {
        uint128_t limit = ((uint128_t)std::numeric_limits<uint64_t> :: max() << 64) +
                          (uint128_t)std::numeric_limits<uint64_t> :: max();
        uint128_t last_bucket_mask = (last_size_ == 128) ? limit : ((static_cast<uint128_t>(1) << last_size_) - 1);
        // If the last bucket isn't full of 1 bits, we can increment that by one.
        if (values_[values_.size() - 1] != last_bucket_mask) {
            values_[values_.size() - 1]++;
        } else {
            if (values_.size() > 1) {
                // Otherwise, search for the first bucket that isn't full of 1 bits.
                for (int16_t i = values_.size() - 2; i >= 0; i--)
                    if (values_[i] != limit) {
                        // Increment it.
                        values_[i]++;
                        // Buckets that were full of 1 bits turn all to 0 bits.
                        // (i.e. 10011111 + 1 = 10100000)
                        for (uint32_t j = i + 1; j < values_.size(); j++)
                            values_[j] = 0;
                        break;
                    }
            }
            // This isn't allowed, as the Bits size must remain constant during all the plotting process.
            assert(all_one == false);
        }
        return *this;
    }

    BitsGeneric<T> operator++(int) {
        BitsGeneric<T> result(*this);
        ++(*this);
        return result;
    }

    BitsGeneric<T>& operator--() {
        bool all_zero = true;
        // If the last bucket is not zero, we can derement it.
        if (values_[values_.size() - 1] != 0) {
            values_[values_.size() - 1]--;
            return *this;
        }
        
        if (values_.size() > 1) {
            // Search for the first bucket different than 0.
            for (int16_t i = values_.size() - 2; i >= 0; i--)
                if (values_[i] != 0) {
                    all_zero = false;
                    // Decrement it.
                    values_[i]--;
                    uint128_t limit = ((uint128_t)std::numeric_limits<uint64_t> :: max() << 64) +
                                      (uint128_t)std::numeric_limits<uint64_t> :: max();
                    // All buckets that were previously 0, now become full of 1s.
                    // (i.e. 1010000 - 1 = 1001111)
                    for (typename T::size_type j = i + 1; j < values_.size() - 1; j++)
                        values_[j] =  limit;
                    values_[values_.size() - 1] = (last_size_ == 128) ? limit :
                                                   ((static_cast<uint128_t>(1) << last_size_) - 1);
                    break;
                }
        }
        if (all_zero) {
            throw std::string("Overflow, negative number");
        }
        return *this;
    }

    BitsGeneric<T> operator--(int) {
        BitsGeneric<T> result(*this);
        --(*this);
        return result;
    }

    BitsGeneric<T> operator^(const BitsGeneric<T>& other) const {
        assert(GetSize() == other.GetSize());
        BitsGeneric<T> res;
        // Xoring individual bits is the same as xor-ing chunks of bits.
        for (uint32_t i = 0; i < values_.size(); i++)
            res.values_.push_back(values_[i] ^ other.values_[i]);
        res.last_size_ = last_size_;
        return res;
    }

    BitsGeneric<T> Slice(uint32_t start_index) const {
        return Slice(start_index, GetSize());
    }

    // Slices the bits from [start_index, end_index)
    BitsGeneric<T> Slice(uint32_t start_index, uint32_t end_index) const {
        if (end_index > GetSize()) {
            end_index = GetSize();
        }

        if (end_index == start_index) return BitsGeneric<T>();
        assert(end_index > start_index);
        uint32_t start_bucket = start_index / 128;
        uint32_t end_bucket = end_index / 128;
        if (start_bucket == end_bucket) {
            // Positions inside the bucket.
            start_index = start_index % 128;
            end_index = end_index % 128;
            uint8_t bucket_size = ((int)start_bucket == (int)(values_.size() - 1)) ? last_size_ : 128;
            uint128_t val = values_[start_bucket];
            // Cut the prefix [0, start_index)
            if (start_index != 0)
                val = val & ((static_cast<uint128_t>(1) << (bucket_size - start_index)) - 1);
            // Cut the suffix after end_index
            val = val >> (bucket_size - end_index);
            return BitsGeneric<T>(val, end_index - start_index);
        } else {
            BitsGeneric<T> result;
            uint128_t prefix, suffix;
            // Get the prefix from the last bucket.
            SplitNumberByPrefix(values_[start_bucket], 128, start_index % 128, &prefix, &suffix);
            result.AppendValue(suffix, 128 - start_index % 128);
            // Append all the in between buckets
            for (uint32_t i = start_bucket + 1; i < end_bucket; i++)
                result.AppendValue(values_[i], 128);
            uint8_t bucket_size = ((int)end_bucket == (int)(values_.size() - 1)) ? last_size_ : 128;
            // Get the suffix from the last bucket.
            SplitNumberByPrefix(values_[end_bucket], bucket_size, end_index % 128, &prefix, &suffix);
            result.AppendValue(prefix, end_index % 128);
            return result;
        }
    }

    // Same as 'Slice', but result fits into an uint64_t. Used for memory optimization.
    uint64_t SliceBitsToInt(uint32_t start_index, uint32_t end_index) const {
        /*if (end_index > GetSize()) {
            end_index = GetSize();
        }
        if (start_index < 0) {
            start_index = 0;
        } */
        if ((start_index >> 7) == (end_index >> 7)) {
            uint128_t res = values_[start_index >> 7];
            if ((start_index >> 7) == values_.size() - 1)
                res = res >> (last_size_ - (end_index & 127));
            else
                res = res >> (128 - (end_index & 127));
            res = res & (((uint128_t)1 << ((end_index & 127) - (start_index & 127))) - 1);
            return res;
        } else {
            assert((start_index >> 7) + 1 == (end_index >> 7));
            uint128_t prefix, suffix;
            SplitNumberByPrefix(values_[(start_index >> 7)], 128, start_index & 127, &prefix, &suffix);
            uint128_t result = suffix;
            uint8_t bucket_size = ((end_index >> 7) == values_.size() - 1) ? last_size_ : 128;
            SplitNumberByPrefix(values_[(end_index >> 7)], bucket_size, end_index & 127, &prefix, &suffix);
            result = (result << (end_index & 127)) + prefix;
            return result;
        }
    }

    void ToBytes(uint8_t buffer[]) const {
        // Return if nothing to work on
        if(values_.size()==0)
            return;

        // Append 0s to complete the last byte.
        uint8_t shift = Util::ByteAlign(last_size_) - last_size_;
        uint128_t val = values_[values_.size() - 1] << (shift);
        uint32_t cnt = 0;
        // Extract byte-by-byte from the last bucket.
        uint8_t iterations = last_size_ / 8;
        if (last_size_ % 8)
            iterations++;
        for (uint8_t i = 0; i < iterations; i++) {
            buffer[cnt++] = (val & 0xff);
            val >>= 8;
        }
        // Extract the full buckets, byte by byte.
        if (values_.size() >= 2) {
            for (int32_t i = values_.size() - 2; i >= 0; i--) {
                uint128_t val = values_[i];
                for (uint8_t j = 0; j < 16; j++) {
                    buffer[cnt++] = (val & 0xff);
                    val >>= 8;
                }
            }
        }

        if(cnt<=1)return;  // No need to reverse anything

        // Since we extracted from end to beginning, bytes are in reversed order. Reverse everything.
        uint32_t left = 0, right = cnt - 1;
        while (left < right) {
            std::swap(buffer[left], buffer[right]);
            left++;
            right--;
        }
    }

    std::string ToString() const {
        std::string str = "";
        for (typename T::size_type i = 0; i < values_.size(); i++) {
            uint128_t val = values_[i];
            typename T::size_type size = (i == values_.size() - 1) ? last_size_ : 128;
            std::string str_bucket = "";
            for (typename T::size_type i = 0; i < size; i++) {
                if (val % 2)
                    str_bucket = "1" + str_bucket;
                else
                    str_bucket = "0" + str_bucket;
                val /= 2;
            }
            str += str_bucket;
        }
        return str;
    }

    // If the bitarray fits into 128 bits, returns it as an uint128_t, otherwise throws error
    uint128_t GetValue() const {
        if (values_.size() != 1) {
            std::cout << "Number of values is: " << values_.size() << std::endl;
            std::cout << "Size of bits is: " << GetSize() << std::endl;
            throw std::string("Number doesn't fit into a 128-bit type.");
        }
        return values_[0];
    }

    uint32_t GetSize() const {
        if (values_.size() == 0) return 0;
        // Full buckets contain each 128 bits, last one contains only 'last_size_' bits.
        return ((uint32_t)values_.size() - 1) * 128 + last_size_;
    }

    void AppendValue(uint128_t value, uint8_t length) {
        // The last bucket is full or no bucket yet, create a new one.
        if (values_.size() == 0 || last_size_ == 128) {
            values_.push_back(value);
            last_size_ = length;
        } else {
            uint8_t free_bits = 128 - last_size_;
            // If the value fits into the last bucket, append it all there.
            if (length <= free_bits) {
                values_[values_.size() - 1] = (values_[values_.size() - 1] << length) + value;
                last_size_ += length;
            } else {
                // Otherwise, append the prefix into the last bucket, and create a new bucket for the suffix.
                uint128_t prefix, suffix;
                SplitNumberByPrefix(value, length, free_bits, &prefix, &suffix);
                values_[values_.size() - 1] = (values_[values_.size() - 1] << free_bits) + prefix;
                values_.push_back(suffix);
                last_size_ = length - free_bits;
            }
        }
    }

    template <class X>
    friend std::ostream &operator<<(std::ostream&, const BitsGeneric<X>&);
    template <class X>
    friend bool operator==(const BitsGeneric<X>& lhs, const BitsGeneric<X>& rhs);
    template <class X>
    friend bool operator<(const BitsGeneric<X>& lhs, const BitsGeneric<X>& rhs);
    template <class X>
    friend bool operator>(const BitsGeneric<X>& lhs, const BitsGeneric<X>& rhs);
    template <class X>
    friend BitsGeneric<X> operator<<(BitsGeneric<X> lhs, uint32_t shift_amount);
    template <class X>
    friend BitsGeneric<X> operator>>(BitsGeneric<X> lhs, uint32_t shift_amount);

 private:
    static void SplitNumberByPrefix(uint128_t number, uint8_t num_bits, uint8_t prefix_size, uint128_t* prefix,
                             uint128_t* suffix) {
        assert(num_bits >= prefix_size);
        if (prefix_size == 0) {
            *prefix = 0;
            *suffix = number;
            return;
        }
        uint8_t suffix_size = num_bits - prefix_size;
        uint128_t mask = (static_cast<uint128_t>(1)) << suffix_size;
        mask--;
        *suffix = number & mask;
        *prefix = number >> suffix_size;
    }

    T values_;
    uint8_t last_size_;
};

template<class T>
std::ostream &operator<<(std::ostream & strm, BitsGeneric<T> const & v) {
    strm << "b" << v.ToString();
    return strm;
}

template <class T>
bool operator==(const BitsGeneric<T>& lhs, const BitsGeneric<T>& rhs) {
    if (lhs.GetSize() != rhs.GetSize()) {
        return false;
    }
    for (uint32_t i = 0; i < lhs.values_.size(); i++) {
        if (lhs.values_[i] != rhs.values_[i]) {
            return false;
        }
    }
    return true;
}

template <class T>
bool operator<(const BitsGeneric<T>& lhs, const BitsGeneric<T>& rhs) {
    if (lhs.GetSize() != rhs.GetSize())
        throw std::string("Different sizes!");
    for (uint32_t i = 0; i < lhs.values_.size(); i++) {
        if (lhs.values_[i] < rhs.values_[i])
            return true;
        if (lhs.values_[i] > rhs.values_[i])
            return false;
    }
    return false;
}

template <class T>
bool operator>(const BitsGeneric<T>& lhs, const BitsGeneric<T>& rhs) {
    if (lhs.GetSize() != rhs.GetSize())
        throw std::string("Different sizes!");
    for (uint32_t i = 0; i < lhs.values_.size(); i++) {
        if (lhs.values_[i] > rhs.values_[i])
            return true;
        if (lhs.values_[i] < rhs.values_[i])
            return false;
    }
    return false;
}

template <class T>
BitsGeneric<T> operator<<(BitsGeneric<T> lhs, uint32_t shift_amount) {
    if (lhs.GetSize() == 0) {
        return BitsGeneric<T>();
    }
    BitsGeneric<T> result;
    // Shifts are cyclic, shifting by the number of bits gives the same number.
    int num_blocks_shift = static_cast<int>(shift_amount / 128);
    uint32_t shift_remainder = shift_amount % 128;
    for (uint32_t i = 0; i < lhs.values_.size(); i++) {
        uint128_t new_value = 0;
        if (i + num_blocks_shift < lhs.values_.size()) {
            new_value += (lhs.values_[i + num_blocks_shift] << shift_remainder);
        }
        if (i + num_blocks_shift + 1 < lhs.values_.size()) {
            new_value += (lhs.values_[i + num_blocks_shift + 1] >> (128 - shift_remainder));
        }
        uint8_t new_length;
        if (i == (uint32_t)lhs.values_.size() - 1) {
            new_length = lhs.last_size_;
        } else {
            new_length = 128;
        }
        result.AppendValue(new_value, new_length);
    }
    return result;
}

template <class T>
BitsGeneric<T> operator>>(BitsGeneric<T> lhs, uint32_t shift_amount) {
    if (lhs.GetSize() == 0) {
        return BitsGeneric<T>();
    }
    BitsGeneric<T> result;

    int num_blocks_shift = static_cast<int>(shift_amount / 128);
    uint32_t shift_remainder = shift_amount % 128;

    for (int i = 0; i < lhs.values_.size(); i++) {
        uint128_t new_value = 0;
        if (i - num_blocks_shift >= 0) {
            new_value += (lhs.values_[i - num_blocks_shift] >> shift_remainder);
        }
        if (i - num_blocks_shift - 1 >= 0) {
            new_value += (lhs.values_[i - num_blocks_shift - 1] << (128 - shift_remainder));
        }
        uint8_t new_length;
        if (i == lhs.values_.size() - 1) {
            new_length = lhs.last_size_;
        } else {
            new_length = 128;
        }
        result.AppendValue(new_value, new_length);
    }
    return result;
}


typedef std::vector<uint128_t> LargeVector;
using Bits = BitsGeneric<SmallVector>;
using ParkBits = BitsGeneric<ParkVector>;
using LargeBits = BitsGeneric<LargeVector>;

#endif  // SRC_CPP_BITS_HPP_
