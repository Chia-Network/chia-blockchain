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

#include <set>
#include <stdio.h>
#include "../lib/include/catch.hpp"
#include "../lib/include/picosha2.hpp"

#include "calculate_bucket.hpp"
#include "plotter_disk.hpp"
#include "sort_on_disk.hpp"
#include "prover_disk.hpp"
#include "verifier.hpp"
#include "encoding.hpp"

using namespace std;

uint8_t plot_id_1[] = {35, 2, 52, 4, 51, 55, 23, 84, 91, 10, 111, 12, 13,
                       222, 151, 16, 228, 211, 254, 45, 92, 198, 204, 10, 9, 10,
                       11, 129, 139, 171, 15, 23};

uint8_t plot_id_3[] = {5, 104, 52, 4, 51, 55, 23, 84, 91, 10, 111, 12, 13,
                       222, 151, 16, 228, 211, 254, 45, 92, 198, 204, 10, 9, 10,
                       11, 129, 139, 171, 15, 23};

vector<unsigned char> intToBytes(uint32_t paramInt, uint32_t numBytes) {
    vector<unsigned char> arrayOfByte(numBytes, 0);
    for (uint32_t i = 0; paramInt > 0; i++) {
        arrayOfByte[numBytes - i - 1] = paramInt & 0xff;
        paramInt >>= 8;
    }
    return arrayOfByte;
}

TEST_CASE("Util") {
    SECTION("Increment and decrement") {
        uint8_t bytes[3] = {45, 172, 225};
        REQUIRE(Util::SliceInt64FromBytes(bytes, 3, 2, 19) == 374172);
        uint8_t bytes2[1] = {213};
        REQUIRE(Util::SliceInt64FromBytes(bytes2, 1, 1, 5) == 21);
    }
}

TEST_CASE("Bits") {
    SECTION("Increment and decrement") {
        Bits a = Bits(5, 3);
        Bits b = Bits(2, 10);
        cout << "A is: " << a << endl;
        cout << "B is: " << b << endl;

        ++b;
        ++b;
        ++b;
        ++b;

        cout << "B is: " << b << endl;

        ++a;
        cout << "A is: " << a << endl;
        ++a;
        cout << "A is: " << a << endl;

        cout << a + b + a << endl;
        --a;
        cout << "A is: " << a << endl;
        Bits c = a++;
        cout << "C is: " << c << endl;
        cout << "A is: " << a << endl;
        Bits d = a--;
        cout << "D is: " << d << endl;
        cout << "A is: " << a << endl;

        Bits e;
        Bits f = Bits(3, 5);
        cout << e + f + e + d << endl;
    }

    SECTION("Slicing and manipulating") {
        Bits g = Bits(13271, 15);
        cout << "G: " << g << endl;
        cout << "G Slice: " << g.Slice(4, 9) << endl;
        cout << "G Slice: " << g.Slice(0, 9) << endl;
        cout << "G Slice: " << g.Slice(9, 10) << endl;
        cout << "G Slice: " << g.Slice(9, 15) << endl;
        cout << "G Slice: " << g.Slice(9, 9) << endl;
        REQUIRE(g.Slice(9, 9) == Bits());

        uint8_t bytes[2];
        g.ToBytes(bytes);
        cout << "bytes: " << static_cast<int>(bytes[0]) << " " << static_cast<int>(bytes[1]) << endl;
        cout << "Back to Bits: " << Bits(bytes, 2, 16) << endl;

        Bits(256, 9).ToBytes(bytes);
        cout << "bytes: " << static_cast<int>(bytes[0]) << " " << static_cast<int>(bytes[1]) << endl;
        cout << "Back to Bits: " << Bits(bytes, 2, 16) << endl;

        cout << Bits(640, 11) << endl;
        Bits(640, 11).ToBytes(bytes);
        cout << "bytes: " << static_cast<int>(bytes[0]) << " " << static_cast<int>(bytes[1]) << endl;

        Bits h = Bits(bytes, 2, 16);
        Bits i = Bits(bytes, 2, 17);
        cout << "H: " << h << endl;
        cout << "I: " << i << endl;

        Bits j = Bits(11, 5);
        Bits k1 = Bits(7, 5);

        cout << "j" << j << endl;
        cout << "k" << k1 << endl;
        cout << "Xor:" << (j ^ k1) << endl;

        cout << "G: " << g << endl;
        cout << "size: " << g.GetSize() << endl;

        Bits shifted = (g << 150);

        REQUIRE(shifted.GetSize() == 15);
        REQUIRE(shifted.ToString() == "000000000000000");

        Bits large = Bits(13271, 200);
        REQUIRE(large == ((large << 160)) >> 160);
        REQUIRE((large << 160).GetSize() == 200);

        Bits l = Bits(123287490, 20);
        l = l + Bits(0, 5);

        Bits m = Bits(5, 3);
        uint8_t buf[1];
        m.ToBytes(buf);
        REQUIRE(buf[0] == (5 << 5));
    }
    SECTION("Park Bits") {
        uint32_t num_bytes = 16000;
        uint8_t* buf = new uint8_t[num_bytes];
        uint8_t* buf_2 = new uint8_t[num_bytes];
        Util::GetRandomBytes(buf, num_bytes);
        ParkBits my_bits = ParkBits(buf, num_bytes, num_bytes*8);
        my_bits.ToBytes(buf_2);
        for (uint32_t i = 0; i < num_bytes; i++) {
            REQUIRE(buf[i] == buf_2[i]);
        }
        delete[] buf;
        delete[] buf_2;
    }

    SECTION("Large Bits") {
        uint32_t num_bytes = 200000;
        uint8_t* buf = new uint8_t[num_bytes];
        uint8_t* buf_2 = new uint8_t[num_bytes];
        Util::GetRandomBytes(buf, num_bytes);
        LargeBits my_bits = LargeBits(buf, num_bytes, num_bytes*8);
        my_bits.ToBytes(buf_2);
        for (uint32_t i = 0; i < num_bytes; i++) {
            REQUIRE(buf[i] == buf_2[i]);
        }
        delete[] buf;
        delete[] buf_2;
    }
}

class FakeDisk : public Disk {
 public:
    explicit FakeDisk(uint32_t size) : s(size, 'a') {
        f_ = std::stringstream(s, std::ios_base::in | std::ios_base::out);
    }

    void Read(uint64_t begin, uint8_t* memcache, uint32_t length) {
        f_.seekg(begin);
        f_.read(reinterpret_cast<char*>(memcache), length);
    }

    void Write(uint64_t begin, uint8_t* memcache, uint32_t length) {
        f_.seekp(begin);
        f_.write(reinterpret_cast<char*>(memcache), length);
    }

    std::iostream* ReadHandle(uint64_t begin) {
        f_.seekg(begin);
        return &f_;
    }

    std::iostream* WriteHandle(uint64_t begin) {
        f_.seekp(begin);
        return &f_;
    }

 private:
    std::string s;
    std::stringstream f_;
};

bool CheckMatch(int64_t yl, int64_t yr) {
    int64_t bl = yl / kBC;
    int64_t br = yr / kBC;
    if (bl + 1 != br) return false;  // Buckets don't match
    for (int64_t m = 0; m < kExtraBitsPow; m++) {
        if ((((yr % kBC) / kC - ((yl % kBC) / kC)) - m) % kB == 0) {
            if ((((yr % kBC) % kC - ((yl % kBC) % kC)) - (int64_t)(pow((double)(2*m + (bl%2)), (double)2))) % kC == 0) {
                return true;
            }
        }
    }
    return false;
}

TEST_CASE("F functions") {
    SECTION("F1") {
        uint8_t test_k = 35;
        uint8_t test_key[] = {0, 2, 3, 4, 5, 5, 7, 8, 9, 10, 11, 12, 13,
                        14, 15, 16, 1, 2, 3, 41, 5, 6, 7, 8, 9, 10,
                        11, 12, 13, 11, 15, 16};
        F1Calculator f1(test_k, test_key);

        Bits L = Bits(525, test_k);
        pair<Bits, Bits> result1 = f1.CalculateBucket(L);
        Bits L2 = Bits(526, test_k);
        pair<Bits, Bits> result2 = f1.CalculateBucket(L2);
        Bits L3 = Bits(625, test_k);
        pair<Bits, Bits> result3 = f1.CalculateBucket(L3);

        vector<pair<Bits, Bits>> results = f1.CalculateBuckets(L, 101);
        REQUIRE(result1 == results[0]);
        REQUIRE(result2 == results[1]);
        REQUIRE(result3 == results[100]);

        test_k = 32;
        F1Calculator f1_2(test_k, test_key);
        L = Bits(192837491, test_k);
        result1 = f1_2.CalculateBucket(L);
        L2 = Bits(192837491 + 1, test_k);
        result2 = f1_2.CalculateBucket(L2);
        L3 = Bits(192837491 + 2, test_k);
        result3 = f1_2.CalculateBucket(L3);
        Bits L4 = Bits(192837491 + 490, test_k);
        pair<Bits, Bits> result4 = f1_2.CalculateBucket(L4);

        results = f1_2.CalculateBuckets(L, 491);
        REQUIRE(result1 == results[0]);
        REQUIRE(result2 == results[1]);
        REQUIRE(result3 == results[2]);
        REQUIRE(result4 == results[490]);
    }

    SECTION("F2") {
        uint8_t test_key_2[] = {20, 2, 5, 4, 51, 52, 23, 84, 91, 10, 111, 12, 13,
                            24, 151, 16, 228, 211, 254, 45, 92, 198, 204, 10, 9, 10,
                            11, 129, 139, 171, 15, 18};
        map<uint64_t, vector<pair<Bits, Bits>>> buckets;

        uint8_t k = 12;
        uint64_t num_buckets = pow(2, k + kExtraBits) / kBC + 1;
        Bits x = Bits(0, k);

        F1Calculator f1(k, test_key_2);
        for (uint32_t j=0; j < pow(2, k-4) + 1; j++) {
            for (auto pair : f1.CalculateBuckets(x, pow(2, 4))) {
                uint64_t bucket = std::get<0>(pair).GetValue() / kBC;
                if (buckets.find(bucket) == buckets.end()) {
                    buckets[bucket] = vector<std::pair<Bits, Bits>>();
                }
                buckets[bucket].push_back(pair);
                if (x.GetValue() + 1 > pow(2, k) - 1) {
                    break;
                }
                ++x;
            }
            if (x.GetValue() + 1 > pow(2, k) - 1) {
                break;
            }
        }

        FxCalculator f2(k, 2, test_key_2);
        int total_matches = 0;

        for (auto kv : buckets) {
            if (kv.first == num_buckets- 1) {
                continue;
            }
            auto bucket_elements_2 = buckets[kv.first + 1];
            vector<PlotEntry> left_bucket;
            vector<PlotEntry> right_bucket;
            for (auto yx1 : kv.second) {
                PlotEntry e;
                e.y = get<0>(yx1).GetValue();
                left_bucket.push_back(e);
            }
            for (auto yx2 : buckets[kv.first + 1]) {
                PlotEntry e;
                e.y = get<0>(yx2).GetValue();
                right_bucket.push_back(e);
            }
            sort(left_bucket.begin(), left_bucket.end(), [](const PlotEntry & a, const PlotEntry & b) -> bool {
                return a.y > b.y;
            });
            sort(right_bucket.begin(), right_bucket.end(), [](const PlotEntry & a, const PlotEntry & b) -> bool {
                return a.y > b.y;
            });

            vector<pair<uint16_t, uint16_t> > matches = f2.FindMatches(left_bucket, right_bucket);
            for (auto match : matches) {
                REQUIRE(CheckMatch(left_bucket[match.first].y, right_bucket[match.second].y));
            }
            total_matches += matches.size();
        }
        REQUIRE(total_matches == 3066);
    }
}

void HexToBytes(const string& hex, uint8_t* result) {
    for (unsigned int i = 0; i < hex.length(); i += 2) {
        string byteString = hex.substr(i, 2);
        uint8_t byte = (uint8_t) strtol(byteString.c_str(), NULL, 16);
        result[i/2] = byte;
  }
}


void TestProofOfSpace(std::string filename, uint32_t iterations, uint8_t k, uint8_t* plot_id,
                      uint32_t expected_success) {
        DiskProver prover(filename);
        uint8_t* proof_data = new uint8_t[8 * k];
        uint32_t success = 0;
        for (uint32_t i = 0; i < iterations; i++) {
            vector<unsigned char> hash_input = intToBytes(i, 4);
            vector<unsigned char> hash(picosha2::k_digest_size);
            picosha2::hash256(hash_input.begin(), hash_input.end(), hash.begin(), hash.end());
            vector<LargeBits> qualities = prover.GetQualitiesForChallenge(hash.data());
            Verifier verifier = Verifier();
            for (uint32_t index = 0; index < qualities.size(); index++) {
                LargeBits proof = prover.GetFullProof(hash.data(), index);
                proof.ToBytes(proof_data);

                LargeBits quality = verifier.ValidateProof(plot_id, k, hash.data(), proof_data, k*8);
                REQUIRE(quality.GetSize() == 256);
                REQUIRE(quality == qualities[index]);
                success += 1;

                // Tests invalid proof
                proof_data[0] = (proof_data[0] + 1) % 256;
                LargeBits quality_2 = verifier.ValidateProof(plot_id, k, hash.data(), proof_data, k*8);
                REQUIRE(quality_2.GetSize() == 0);
            }
        }
        std::cout << "Success: " << success << "/" << iterations << " " << (100* ((double)success/(double)iterations))
                                 << "%" << std::endl;
        REQUIRE(success == expected_success);
        delete[] proof_data;
}


void PlotAndTestProofOfSpace(std::string filename, uint32_t iterations, uint8_t k, uint8_t* plot_id,
                             uint32_t expected_success) {
        DiskPlotter plotter = DiskPlotter();
        uint8_t memo[5] = {1, 2, 3, 4, 5};
        plotter.CreatePlotDisk(".", ".", filename, k, memo, 5, plot_id, 32);
        TestProofOfSpace(filename, iterations, k, plot_id, expected_success);
        REQUIRE(remove(filename.c_str()) == 0);
}


TEST_CASE("Plotting") {
    SECTION("Disk plot 1") {
        PlotAndTestProofOfSpace("cpp-test-plot.dat", 100, 16, plot_id_1, 42);
    }
    SECTION("Disk plot 2") {
        PlotAndTestProofOfSpace("cpp-test-plot.dat", 500, 17, plot_id_3, 273);
    }
    SECTION("Disk plot 3") {
        PlotAndTestProofOfSpace("cpp-test-plot.dat", 5000, 21, plot_id_3, 4647);
    }
}

TEST_CASE("Invalid plot") {
    SECTION("File gets deleted") {
        DiskPlotter plotter = DiskPlotter();
        uint8_t memo[5] = {1, 2, 3, 4, 5};
        string filename = "invalid-plot.dat";
        uint8_t k = 22;
        plotter.CreatePlotDisk(".", ".", filename, k, memo, 5, plot_id_1, 32);
        DiskProver prover(filename);
        uint8_t* proof_data = new uint8_t[8 * k];
        uint8_t challenge[32];
        memset(challenge, 155, 32);
        vector<LargeBits> qualities = prover.GetQualitiesForChallenge(challenge);
        Verifier verifier = Verifier();
        REQUIRE(qualities.size() > 0);
        for (uint32_t index = 0; index < qualities.size(); index++) {
            LargeBits proof = prover.GetFullProof(challenge, index);
            proof.ToBytes(proof_data);
            LargeBits quality = verifier.ValidateProof(plot_id_1, k, challenge, proof_data, k*8);
            REQUIRE(quality == qualities[index]);
        }
        REQUIRE(remove(filename.c_str()) == 0);
        REQUIRE_THROWS_WITH([&](){
            DiskProver p(filename);
        }(), "Invalid file " + filename);
        delete[] proof_data;
    }
}

TEST_CASE("Sort on disk") {
    SECTION("ExtractNum") {
        for (int i=0; i < 15*8 - 5; i++) {
            uint8_t buf[15];
            Bits((uint128_t)27 << i, 15*8).ToBytes(buf);

            REQUIRE(SortOnDiskUtils::ExtractNum(buf, 15, 15*8 - 4 - i, 3) == 5);
        }
        uint8_t buf[16];
        Bits((uint128_t)27 << 5, 128).ToBytes(buf);
        REQUIRE(SortOnDiskUtils::ExtractNum(buf, 16, 100, 200) == 864);
    }

    SECTION("MemCmpBits") {
        uint8_t left[3];
        left[0] = 12;
        left[1] = 10;
        left[2] = 100;

        uint8_t right[3];
        right[0] = 12;
        right[1] = 10;
        right[2] = 100;

        REQUIRE(SortOnDiskUtils::MemCmpBits(left, right, 3, 0) == 0);
        REQUIRE(SortOnDiskUtils::MemCmpBits(left, right, 3, 10) == 0);

        right[1] = 11;
        REQUIRE(SortOnDiskUtils::MemCmpBits(left, right, 3, 0) < 0);
        REQUIRE(SortOnDiskUtils::MemCmpBits(left, right, 3, 16) == 0);

        right[1] = 9;
        REQUIRE(SortOnDiskUtils::MemCmpBits(left, right, 3, 0) > 0);

        right[1] = 10;

        // Last bit differs
        right[2] = 101;
        REQUIRE(SortOnDiskUtils::MemCmpBits(left, right, 3, 0) < 0);
    }

    SECTION("Quicksort") {
        uint32_t iters = 100;
        vector<string> hashes;
        uint8_t* hashes_bytes = new uint8_t[iters * 16];
        memset(hashes_bytes, 0, iters * 16);

        uint32_t random_state = 0;
        for (uint32_t i = 0; i < iters; i++) {
            string to_insert = std::to_string(rand_r(&random_state));
            while (to_insert.length() < 16) {
                to_insert += "0";
            }
            hashes.push_back(to_insert);
            memcpy(hashes_bytes + i * 16, to_insert.data(), to_insert.length());
        }
        sort(hashes.begin(), hashes.end());
        Sorting::QuickSort(hashes_bytes, 16, iters, 0);

        for (uint32_t i = 0; i < iters; i++) {
            std::string str(reinterpret_cast<char*>(hashes_bytes) + i * 16, 16);
            REQUIRE(str.compare(hashes[i]) == 0);
        }
        delete[] hashes_bytes;
    }

    SECTION("Fake disk") {
        FakeDisk d = FakeDisk(10000);
        uint8_t buf[5] = {1, 2, 3, 5, 7};
        d.Write(250, buf, 5);

        uint8_t read_buf[5];
        d.Read(250, read_buf, 5);

        REQUIRE(memcmp(buf, read_buf, 5) == 0);
    }

    SECTION("File disk") {
        FileDisk d = FileDisk("test_file.bin");
        uint8_t buf[5] = {1, 2, 3, 5, 7};
        d.Write(250, buf, 5);

        uint8_t read_buf[5];
        d.Read(250, read_buf, 5);

        REQUIRE(memcmp(buf, read_buf, 5) == 0);
        remove("test_file.bin");
    }

    SECTION("Bucket store") {
        uint32_t iters = 10000;
        uint32_t size = 16;
        vector<Bits> input;

        for (uint32_t i = 0; i < iters; i++) {
            uint8_t rand_arr[size];
            for (uint32_t i = 0; i < size; i++) {
                rand_arr[i] = rand() % 256;
            }
            input.push_back(Bits(rand_arr, size, size*8));
        }

        set<Bits> iset(input.begin(), input.end());
        uint32_t input_index = 0;
        vector<Bits> output;

        uint8_t* mem = new uint8_t[iters];
        BucketStore bs = BucketStore(mem, iters, 16, 0, 4, 5);
        bs.Audit();

        uint8_t buf[size];
        while (true) {
            while (!bs.IsFull() && input_index != input.size()) {
                input[input_index].ToBytes(buf);
                bs.Store(buf, size);
                bs.Audit();
                input_index += 1;
            }
            uint32_t m = bs.MaxBucket();
            uint64_t final_size;
            uint128_t* bucket_handle = bs.BucketHandle(m, 1000000, final_size);
            uint32_t entry_size = size / 16;
            uint8_t last_size = (size * 8) % 128;
            if (last_size == 0)
                last_size = 128;
            for (uint32_t i = 0; i < final_size; i += entry_size) {
                Sorting::EntryToBytes(bucket_handle, i, i + entry_size, last_size, buf);
                Bits x(buf, size, size*8);
                REQUIRE(iset.find(x) != iset.end());
                REQUIRE(SortOnDiskUtils::ExtractNum((uint8_t*)buf, size, 0, 4) == m);
                output.push_back(x);
            }
            if (bs.IsEmpty()) {
                delete[] bucket_handle;
                break;
            }
            delete[] bucket_handle;
        }
        sort(input.begin(), input.end());
        sort(output.begin(), output.end());

        set<Bits> output_set(output.begin(), output.end());
        REQUIRE(output_set.size() == output.size());
        for (uint32_t i = 0; i < output.size(); i++) {
            REQUIRE(input[i] == output[i]);
        }

        delete[] mem;
    }

    SECTION("Sort on disk") {
        uint32_t iters = 100000;
        uint32_t size = 32;
        vector<Bits> input;
        uint32_t begin = 1000;
        FakeDisk disk = FakeDisk(5000000);

        for (uint32_t i = 0; i < iters; i ++) {
            vector<unsigned char> hash_input = intToBytes(i, 4);
            vector<unsigned char> hash(picosha2::k_digest_size);
            picosha2::hash256(hash_input.begin(), hash_input.end(), hash.begin(), hash.end());

            disk.Write(begin + i * size, hash.data(), size);
            input.emplace_back(Bits(hash.data(), size, size*8));
        }

        vector<uint64_t> bucket_sizes(16, 0);
        uint8_t buf[size];
        for (Bits& x : input) {
            x.ToBytes(buf);
            bucket_sizes[SortOnDiskUtils::ExtractNum(buf, size, 0, 4)] += 1;
        }

        const uint32_t memory_len = 100000;
        uint8_t* memory = new uint8_t[memory_len];
        Sorting::SortOnDisk(disk, begin, 3600000, size, 0, bucket_sizes, memory, memory_len);


        sort(input.begin(), input.end());

        uint8_t buf2[size];
        for (uint32_t i = 0; i < iters; i++) {
            disk.Read(begin + i * size, buf2, size);
            input[i].ToBytes(buf);
            REQUIRE(memcmp(buf, buf2, size) == 0);
        }

        delete[] memory;
    }

    SECTION("Sort in Memory") {
        uint32_t iters = 100000;
        uint32_t size = 32;
        vector<Bits> input;
        uint32_t begin = 1000;
        FakeDisk disk = FakeDisk(5000000);

        for (uint32_t i = 0; i < iters; i ++) {
            vector<unsigned char> hash_input = intToBytes(i, 4);
            vector<unsigned char> hash(picosha2::k_digest_size);
            picosha2::hash256(hash_input.begin(), hash_input.end(), hash.begin(), hash.end());
            hash[0] = hash[1] = 0;
            disk.Write(begin + i * size, hash.data(), size);
            input.emplace_back(Bits(hash.data(), size, size*8));
        }

        const uint32_t memory_len = SortOnDiskUtils::RoundSize(iters) * 30;
        uint8_t* memory = new uint8_t[memory_len];
        Sorting::SortInMemory(disk, begin, memory, size, iters, 16);

        sort(input.begin(), input.end());
        uint8_t buf[size];
        uint8_t buf2[size];
        for (uint32_t i = 0; i < iters; i++) {
            disk.Read(begin + i * size, buf2, size);
            input[i].ToBytes(buf);
            REQUIRE(memcmp(buf, buf2, size) == 0);
        }

        delete[] memory;
    }

}
