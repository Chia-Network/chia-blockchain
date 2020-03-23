#ifndef PROOF_COMMON_H
#define PROOF_COMMON_H
#include "Reducer.h"

std::vector<unsigned char> ConvertIntegerToBytes(integer x, uint64_t num_bytes) {
    std::vector<unsigned char> bytes;
    bool negative = false;
    if (x < 0) {
        x = abs(x);
        x = x - integer(1);
        negative = true;
    }
    for (int iter = 0; iter < num_bytes; iter++) {
        auto byte = (x % integer(256)).to_vector();
        if (negative)
            byte[0] ^= 255;
        bytes.push_back(byte[0]);
        x = x / integer(256);
    }
    std::reverse(bytes.begin(), bytes.end());
    return bytes;
}

integer HashPrime(std::vector<unsigned char> s) {
    std::string prime = "prime";
    uint32_t j = 0;
    while (true) {
        std::vector<unsigned char> input(prime.begin(), prime.end());
        std::vector<unsigned char> j_to_bytes = ConvertIntegerToBytes(integer(j), 8);
        input.insert(input.end(), j_to_bytes.begin(), j_to_bytes.end());
        input.insert(input.end(), s.begin(), s.end());
        std::vector<unsigned char> hash(picosha2::k_digest_size);
        picosha2::hash256(input.begin(), input.end(), hash.begin(), hash.end());

        integer prime_integer;
        for (int i = 0; i < 16; i++) {
            prime_integer *= integer(256);
            prime_integer += integer(hash[i]);
        }
        if (prime_integer.prime()) {
            return prime_integer;
        }
        j++;
    }
}

std::vector<unsigned char> SerializeForm(form &y, int int_size) {
    y.reduce();
    std::vector<unsigned char> res = ConvertIntegerToBytes(y.a, int_size);
    std::vector<unsigned char> b_res = ConvertIntegerToBytes(y.b, int_size);
    res.insert(res.end(), b_res.begin(), b_res.end());
    return res;
}

integer FastPow(uint64_t a, uint64_t b, integer& c) {
    integer res, a1 = integer(a);
    mpz_powm_ui(res.impl, a1.impl, b, c.impl);
    return res;
}

integer GetB(const integer& D, form &x, form& y) {
    int int_size = (D.num_bits() + 16) >> 4;
    std::vector<unsigned char> serialization = SerializeForm(x, int_size);
    std::vector<unsigned char> serialization_y = SerializeForm(y, int_size);
    serialization.insert(serialization.end(), serialization_y.begin(), serialization_y.end());
    return HashPrime(serialization);
}

class PulmarkReducer {
    ClassGroupContext *t;
    Reducer *reducer;

  public:
    PulmarkReducer() {
        t=new ClassGroupContext(4096);
        reducer=new Reducer(*t);
    }

    ~PulmarkReducer() {
        delete(reducer);
        delete(t);
    }

    void reduce(form &f) {
        mpz_set(t->a, f.a.impl);
        mpz_set(t->b, f.b.impl);
        mpz_set(t->c, f.c.impl);

        reducer->run();

        mpz_set(f.a.impl, t->a);
        mpz_set(f.b.impl, t->b);
        mpz_set(f.c.impl, t->c);
    }
};

form FastPowFormNucomp(form x, integer &D, integer num_iterations, integer &L, PulmarkReducer& reducer)
{
    form res = form::identity(D);
    int D_size = D.impl->_mp_size;

    while (1) {
        if (num_iterations.get_bit(0)) {
            nucomp_form(res, res, x, D, L);
            if (res.a.impl->_mp_size > D_size) {
                // Reduce only when 'a' has more limbs than D
                reducer.reduce(res);
            }
        }

        num_iterations >>= 1;
        if (num_iterations == 0) {
            break;
        }

        nudupl_form(x, x, D, L);
        if (x.a.impl->_mp_size > D_size) {
            reducer.reduce(x);
        }
    }
    return res;
}

# endif // PROOF_COMMON_H
