#ifndef CREATE_DISCRIMINANT_H
#define CREATE_DISCRIMINANT_H

const int m = 8 * 3 * 5 * 7 * 11 * 13;

std::vector<int> OddPrimesBelowM() {
    const int limit = (1 << 16);
    int low_prime[limit + 1];
    memset(low_prime, 0, sizeof(low_prime));
    std::vector<int> primes;
    for (int i = 2; i <= limit; i++) {
        if (low_prime[i] == 0) {
            low_prime[i] = i;
            primes.push_back(i);
        }
        for (int j = 0; j < primes.size(); j++) {
            if (primes[j] > low_prime[i]) 
                break;
            if (primes[j] * i > limit)
                break;
            low_prime[primes[j] * i] = primes[j];
        }
    }
    return primes;
}

std::vector<int> BuildResidues() {
    std::vector<int> primes({3, 5, 7, 11, 13});
    std::vector<int> res;
    for (int i = 7; i <= m; i += 8) {
        bool all = true;
        for (int j = 0; j < primes.size(); j++)
            if (i % primes[j] == 0) {
                all = false;
                break;
            }
        if (all)
            res.push_back(i);
    }
    return res;
}

std::vector<pair<int, int>> BuildSieveInfo(std::vector<int>& primes) {
    std::vector <pair<int, int>> res;
    for (int p: primes) {
        if (p <= 13)
            continue;
        int a = m % p;
        int b = p - 2;
        int c = 1;
        while (b) {
            if (b % 2) {
                c = (long long) c * a % p;
            }
            a = (long long) a * a % p;
            b /= 2;
        }
        res.push_back({p, c});
    }
    return res;
}

std::vector<uint8_t> EntropyFromSeed(std::vector<uint8_t>& seed, int byte_count) {
    std::vector<uint8_t> blob;
    std::vector<uint8_t> seed_copy = seed;
    int size = seed_copy.size();
    seed_copy.push_back(0);
    seed_copy.push_back(0);
    
    int extra = 0;
    while (blob.size() < byte_count) {
        int copy_extra = extra;
        for (int i = 0; i < 2; i++) {
            seed_copy[size + 1 - i] = copy_extra % 256;
            copy_extra /= 256;
        }
        std::vector<unsigned char> hash(picosha2::k_digest_size);
        picosha2::hash256(seed_copy.begin(), seed_copy.end(), hash.begin(), hash.end());
        blob.insert(blob.end(), hash.begin(), hash.end());
        extra++;
    }

    while (blob.size() > byte_count)
        blob.pop_back();
    return blob;
}

integer CreateDiscriminant(std::vector<uint8_t>& seed, int length = 1024) {
    static bool is_init = false;
    static std::vector<int> residues;
    static std::vector<pair<int, int>> sieve_info;

    if (!is_init) {
        auto primes = OddPrimesBelowM();
        residues = BuildResidues();
        sieve_info = BuildSieveInfo(primes);
        is_init = true;
    }

    int extra = length % 8;
    int size = (length >> 3) + (extra == 0 ? 2 : 3);
    auto entropy = EntropyFromSeed(seed, size);
    integer n(0);
    for (int i = 0; i < size - 2; i++) {
        n = n * integer(256);
        n = n + integer(entropy[i]);
    }
    int shift = (extra == 0 ? 0 : (8 - extra));
    n >>= shift;
    n.set_bit(length - 1, 1);
    integer remainder(n);
    remainder %= integer(m);
    n = n - remainder;
    int residue_index = 0;
    for (int i = size - 2; i < size; i++) 
        residue_index = residue_index * 256 + entropy[i];
    n = n + integer(residues[residue_index % residues.size()]);
    
    while (true) {
        bool sieve[(1 << 16)];
        memset(sieve, 0, sizeof(sieve));
        for (int i = 0; i < sieve_info.size(); i++) {
            int p = sieve_info[i].first;
            int q = sieve_info[i].second;
            integer minus_n(n);
            minus_n %= integer(p);
            auto tmp = minus_n.to_vector();
            auto index = tmp[0];
            index = -index + p;
            index = index * q % p;
            while (index < (1 << 16)) {
                sieve[index] = true;
                index += p;
            }
        }
        for (int j = 0; j < (1 << 16); j++) {
            if (sieve[j] == true)
                continue;
            integer candidate(n);
            candidate = candidate + integer((long long)m * j);
            if (candidate.prime()) {
                candidate = candidate * integer(-1);
                return candidate;
            }
        }
        n = n + integer((long long)m * (1 << 16));
    }
}

#endif // CREATE_DISCRIMINANT_H
