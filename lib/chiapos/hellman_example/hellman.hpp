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

#ifndef TRACK3_HELLMAN_HPP_
#define TRACK3_HELLMAN_HPP_

#include <random>
#include <set>
#include <vector>
#include "pos_constants.hpp"
#include "calculate_bucket.hpp"
#include "sort_on_disk.hpp"
#include "bits.hpp"
#include "util.hpp"

using namespace std;

class Attacker {
   public:
    Attacker(uint64_t attack_space, uint64_t attack_time, uint64_t n, int num_tables, uint8_t id[]);

    vector<uint64_t> InvertRealY(uint64_t y);

    vector<uint64_t> Invert(uint64_t y);

    uint64_t EvaluateForward(uint64_t x);

    uint64_t GetBucket(uint64_t x);

    // Given attack_space and attack_time from the constructor, it builds the tables.
    void BuildTable();

    void BuildExtraStorage();

    void BuildDiskExtraStorage(string filename, std::vector<uint64_t>& extra_metadata);

    void LoadExtraStorageFromDisk(string filename, uint64_t table1_pos);

    // Given a table and a value, sets lo and hi values to the lowest/highest rows
    // where the value appears.
    void FindTableEntry(uint64_t y, int t, int64_t &lo, int64_t &hi);

    int ShuffleBits(int perm_idx, int t, uint64_t x);

    // Returns -1 in case of a false alarm, otherwise returns the inverse, given the chain begin.
    int CheckChain(uint64_t root, uint64_t y, uint64_t expected_pos, uint64_t t);

    ~Attacker() {
        
    }
  
  private:

    uint8_t num_bits;
    uint64_t attack_space;
    uint64_t attack_time;
    uint64_t n;
    uint8_t num_tables;
    F1Calculator f1;
    vector <vector <pair <uint64_t, uint64_t> > > tables;
    vector <int> pad;
    vector <vector <int>> shuffle_permutation;
    vector <pair <uint64_t, uint64_t> > extra_storage_inverses;

    mt19937 rng;

    uint8_t GetNumBits(int n) {
        uint8_t num_bits;
        for (num_bits = 0; (1 << num_bits) < n; ++num_bits);
        return num_bits;
    }

};

Attacker::Attacker(uint64_t attack_space, uint64_t attack_time, uint64_t n, int num_tables, uint8_t id[]) : f1(GetNumBits(n), id),
                                                                                                            rng(12121) {
    this->attack_space = attack_space;
    this->attack_time = attack_time;
    this->num_tables = num_tables;
    this->n = n;
    num_bits = GetNumBits(n);

    for (int i = 0; i < attack_time; ++i) {
        vector <int> cur_perm;
        for (int i = 0; i < num_bits; ++i)
            cur_perm.push_back(i);
        shuffle(cur_perm.begin(), cur_perm.end(), rng);
        shuffle_permutation.push_back(cur_perm);
    }
}

uint64_t Attacker::EvaluateForward(uint64_t val) {
    Bits x(val, num_bits);
    f1.ReloadKey();
    Bits bucket = f1.CalculateF(x);
    return bucket.SliceBitsToInt(0, num_bits);
}

uint64_t Attacker::GetBucket(uint64_t val) {
    Bits x(val, num_bits);
    f1.ReloadKey();
    Bits bucket = f1.CalculateF(x);
    return bucket.GetValue() / kBC;
}

void Attacker::BuildTable() {
    std::uniform_int_distribution<int> dis(0, n);
    vector <uint64_t> table_begin;
    for (int i = 0; i < n; i += attack_space * num_tables) {
        int j = i + attack_space * num_tables;
        if (j > n - 1)
            j = n - 1;
        vector <uint64_t> perm;
        for (int k = i; k <= j; k++)
            perm.push_back(k);
        shuffle(perm.begin(), perm.end(), rng);
        uint64_t num_buckets = n / (attack_space * num_tables);
        uint64_t choose = attack_space * num_tables / num_buckets;
        for (int k = 0; k < choose; k++)
            table_begin.push_back(perm[k]);
    }
    std::cout << "Total distinct tables start elements: " << table_begin.size() << " Needed: " << attack_space * num_tables << "\n";
    int idx = 0;
    for (int i = 0; i < 2 * attack_time; ++i)
        pad.push_back(dis(rng));
    for (int t = 0; t < num_tables; ++t) {
        vector <pair <uint64_t, uint64_t> > table;
        for (int i = 0; i < attack_space; ++i) {
            int x_init = table_begin[idx++];
            if (idx == table_begin.size())
                idx = 0;
            int x_fin = x_init;
            for (int j = 0; j < attack_time; ++j) {
                x_fin = EvaluateForward(x_fin);
                x_fin = ShuffleBits(j, t, x_fin);
            }
            table.push_back({x_fin, x_init});
            //std::cout << x_init << " " << x_fin << "\n";
        }
        sort(table.begin(), table.end());
        tables.push_back(table);
    }
}

void Attacker::FindTableEntry(uint64_t y, int t, int64_t &lo, int64_t &hi) {
    int64_t left = 0, right = tables[t].size() - 1;
    lo = -1, hi = -1;
    while (left <= right) {
        int middle = (left + right) / 2;
        if (tables[t][middle].first == y) {
            lo = middle;
            right = middle - 1;
            continue;
        }
        if (tables[t][middle].first < y)
            left = middle + 1;
        else
            right = middle - 1;
    }
    if (lo == -1)
        return ;
    left = 0; right = tables[t].size() - 1;
    while (left <= right) {
        int64_t middle = (left + right) / 2;
        if (tables[t][middle].first == y) {
            hi = middle;
            left = middle + 1;
            continue;
        }
        if (tables[t][middle].first < y)
            left = middle + 1;
        else
            right = middle - 1;
    }
}

int Attacker::CheckChain(uint64_t root, uint64_t y, uint64_t expected_pos, uint64_t t) {
    for (int i = 0; i <= expected_pos; ++i) {
        int ant = root;
        root = EvaluateForward(root);
        root = ShuffleBits(i, t, root);
        if (root == y && i == expected_pos) {
            return ant;
        }
    }
    return -1;
}

vector<uint64_t> Attacker::InvertRealY(uint64_t y) {
    vector<uint64_t> results;
    for (int64_t i = attack_time - 1; i >= 0; --i) {
        for (int64_t t = 0; t < num_tables; ++t) {
            int64_t y_fin = ShuffleBits(i, t, y);
            for (uint64_t j = i + 1; j < attack_time; ++j) {
                y_fin = EvaluateForward(y_fin);
                y_fin = ShuffleBits(j, t, y_fin);
            }
            int64_t lo, hi;
            FindTableEntry(y_fin, t, lo, hi);
            if (lo != -1) {
                for (int row = lo; row <= hi; ++row) {
                    int inv = CheckChain(tables[t][row].second, ShuffleBits(i, t, y), i, t);
                    if (inv != -1) {
                        results.push_back(inv);
                    }
                }
            }
        }
    } 
    return results;
}

vector<uint64_t> Attacker::Invert(uint64_t y) {
    vector<uint64_t> results;
    set<uint64_t> fount;
    int64_t left = 0, right = extra_storage_inverses.size() - 1, low = -1;
    f1.ReloadKey();
    while (left <= right) {
        uint64_t med = (left + right) / 2;
        if (extra_storage_inverses[med].first == y) {
            right = med - 1;
            low = med;
        }
        if (extra_storage_inverses[med].first < y) {
            left = med + 1;
        }
        if (extra_storage_inverses[med].first > y) {
            right = med - 1;
        }
    }
    if (low != -1) {
        for (uint64_t i = low; extra_storage_inverses[i].first == y; ++i) {
            uint64_t x = extra_storage_inverses[i].second;
            results.push_back(x);               
        }
    }
    
    // Cut the extra bits.
    uint64_t real_y = y >> 5;
    vector<uint64_t> sols = InvertRealY(real_y);
    for (auto val : sols) {
        if (fount.find(val) == fount.end()) {
            fount.insert(val);
            if (f1.CalculateF(Bits(val, num_bits)).GetValue() == y)
                results.push_back(val);
        }
    }
    return results;
}

int Attacker::ShuffleBits(int perm_idx, int t, uint64_t x) {
    int res = 0;
    for (int i = 0; i < num_bits; ++i)
        if (x & (1 << i)) {
            int pos = shuffle_permutation[perm_idx][i];
            res |= (1 << pos);
        }
    return res ^ pad[perm_idx xor t];
}

void Attacker::BuildExtraStorage() {
    for (uint64_t low = 0; low < n; low += attack_space * num_tables) {
        int high = min(n - 1, low + attack_space * num_tables - 1);
        vector <bool> found_x(attack_space * num_tables);
        for (uint64_t t = 0; t < num_tables; ++t) {
            for (uint64_t row = 0; row < attack_space; ++row) {
                int x_fin = tables[t][row].second;
                for (uint64_t j = 0; j < attack_time; ++j) {
                    if (low <= x_fin && x_fin <= high)
                        found_x[x_fin - low] = true;
                    x_fin = EvaluateForward(x_fin);
                    x_fin = ShuffleBits(j, t, x_fin);
                }
            }
        }
        for (int j = low; j <= high; ++j) {
            if (!found_x[j - low]) 
                extra_storage_inverses.push_back({f1.CalculateF(Bits(j, num_bits)).GetValue(), j});
        }
        cout << "Done one bucket of extra storage using size = " << attack_space * num_tables << "\n";
    }
    std::cout << "Number of bits:" << (int) num_bits << "\n";
    sort(extra_storage_inverses.begin(), extra_storage_inverses.end());
    cout << "Extra elements stored: " << extra_storage_inverses.size() << "\n";
    cout << "Hellman table accuracy = " << ((double)((1LL << num_bits) - extra_storage_inverses.size())) / (1LL << num_bits) << "\n";
}

void Attacker::BuildDiskExtraStorage(string filename, std::vector<uint64_t>& extra_metadata) {
    std::ofstream writer(filename, std::ios::in | std::ios::out | std::ios::binary);
    uint8_t entry_len = Util::ByteAlign(num_bits) / 8;
    uint8_t buf[entry_len];
    std::vector<uint64_t> bucket_sizes(kNumSortBuckets, 0);
    uint64_t entries_written = 0;
    uint8_t* memory = new uint8_t[kMemorySize];
    uint32_t bucket_log = floor(log2(kNumSortBuckets));

    for (uint64_t t = 0; t < num_tables; ++t) {
        for (uint64_t row = 0; row < attack_space; ++row) {
            uint64_t x_fin = tables[t][row].second;
            for (uint64_t j = 0; j < attack_time; ++j) {
                Bits to_write(x_fin, num_bits);
                to_write.ToBytes(buf);
                writer.write((const char*)buf, entry_len);
                x_fin = EvaluateForward(x_fin);
                x_fin = ShuffleBits(j, t, x_fin);
                bucket_sizes[SortOnDiskUtils::ExtractNum(buf, entry_len, 0, bucket_log)] += 1;
                entries_written++;
            }
        }
    }

    writer.flush();
    writer.close();

    FileDisk d(filename);
    uint64_t begin_byte = 0;
    uint64_t spare_begin = begin_byte + (entry_len * (entries_written + 1));
    Sorting::SortOnDisk(d, begin_byte, spare_begin, entry_len,
                        0, bucket_sizes, memory, kMemorySize, /*quicksort=*/2);
    d.Close();

    std::ifstream reader(filename, std::fstream::in | std::fstream::binary);
    uint64_t prev_x;
    for (uint64_t i = 0; i < entries_written; i++) {
        reader.read(reinterpret_cast<char*>(buf), entry_len);
        uint64_t cur_x = Util::SliceInt64FromBytes(buf, entry_len, 0, num_bits);
        if (i == 0) {
            for (int j = 0; j < cur_x; j++)
                extra_metadata.push_back(j);
            prev_x = cur_x;
            continue;
        }
        for (uint64_t j = prev_x + 1; j < cur_x; j++)   
            extra_metadata.push_back(j);
        assert(cur_x >= prev_x);
        prev_x = cur_x;
    }
    uint64_t max_x = (1LL << num_bits) - 1;
    if (prev_x != max_x)
        for (uint64_t i = prev_x + 1; i <= max_x; i++)
            extra_metadata.push_back(i);
    std::cout << "Disk Extra Storage count = " << extra_metadata.size() << "\n";
    std::cout << "Hellman table accuracy = " << ((double)((1LL << num_bits) - extra_metadata.size())) / (1LL << num_bits) << "\n";

    delete[] memory;
    reader.close();
}

void Attacker::LoadExtraStorageFromDisk(string filename, uint64_t table1_pos) {
    std::ifstream reader(filename, std::fstream::in | std::fstream::binary);
    reader.seekg(table1_pos);
    uint8_t entry_len = Util::ByteAlign(num_bits) / 8;
    uint8_t buf[entry_len];
    reader.read(reinterpret_cast<char*>(buf), entry_len);
    uint64_t count = Util::SliceInt64FromBytes(buf, entry_len, 0, num_bits);
    f1.ReloadKey();
    for (uint64_t i = 0; i < count; i++) {
        reader.read(reinterpret_cast<char*>(buf), entry_len);
        uint64_t x = Util::SliceInt64FromBytes(buf, entry_len, 0, num_bits);
        extra_storage_inverses.push_back({f1.CalculateF(Bits(x, num_bits)).GetValue(), x});
    }
    std::cout << "Done loading " << extra_storage_inverses.size() << " elements into Extra Storage memory!\n";
    std::sort(extra_storage_inverses.begin(), extra_storage_inverses.end());
}

#endif  // TRACK3_HELLMAN_HPP_
