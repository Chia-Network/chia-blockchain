#include "include.h"
#include "create_discriminant.h"
#include "integer_common.h"
#include "vdf_new.h"
#include "nucomp.h"
#include "picosha2.h"
#include "proof_common.h"


// TODO: Refactor to use 'Prover' class once new_vdf is merged in.

void ApproximateParameters(uint64_t T, int& l, int& k) {
    double log_memory = 23.25349666;
    double log_T = log2(T);
    l = 1;
    if (log_T - log_memory > 0.000001) {
        l = ceil(pow(2, log_memory - 20));
    }
    double intermediate = T * (double)0.6931471 / (2.0 * l);
    k = std::max(std::round(log(intermediate) - log(log(intermediate)) + 0.25), 1.0);
}

uint64_t GetBlock(uint64_t i, uint64_t k, uint64_t T, integer& B) {
    integer res = FastPow(2, T - k * (i + 1), B);
    mpz_mul_2exp(res.impl, res.impl, k);
    res = res / B;
    auto res_vector = res.to_vector();
    return res_vector[0];
}

form GenerateWesolowski(form &y, form &x_init, 
                        integer &D, PulmarkReducer& reducer, 
                        std::vector<form>& intermediates,
                        uint64_t num_iterations, 
                        uint64_t k, uint64_t l) {
    integer B = GetB(D, x_init, y);
    integer L=root(-D, 4);

    uint64_t k1 = k / 2;
    uint64_t k0 = k - k1;

    form x = form::identity(D);

    for (int64_t j = l - 1; j >= 0; j--) {
        x = FastPowFormNucomp(x, D, integer(1 << k), L, reducer);

        std::vector<form> ys((1 << k));
        for (uint64_t i = 0; i < (1 << k); i++)
            ys[i] = form::identity(D);

        form *tmp;
        for (uint64_t i = 0; i < ceil(1.0 * num_iterations / (k * l)); i++) {
            if (num_iterations >= k * (i * l + j + 1)) {
                uint64_t b = GetBlock(i*l + j, k, num_iterations, B);
                tmp = &intermediates[i];
                nucomp_form(ys[b], ys[b], *tmp, D, L);
            }
        }
        for (uint64_t b1 = 0; b1 < (1 << k1); b1++) {
            form z = form::identity(D);
            for (uint64_t b0 = 0; b0 < (1 << k0); b0++) {
                nucomp_form(z, z, ys[b1 * (1 << k0) + b0], D, L);
            }
            z = FastPowFormNucomp(z, D, integer(b1 * (1 << k0)), L, reducer);
            nucomp_form(x, x, z, D, L);
        }
        for (uint64_t b0 = 0; b0 < (1 << k0); b0++) {
            form z = form::identity(D);
            for (uint64_t b1 = 0; b1 < (1 << k1); b1++) {
                nucomp_form(z, z, ys[b1 * (1 << k0) + b0], D, L);
            }
            z = FastPowFormNucomp(z, D, integer(b0), L, reducer);
            nucomp_form(x, x, z, D, L);
        }
    }

    reducer.reduce(x);
    return x;
}

std::vector<uint8_t> ProveSlow(std::vector<uint8_t>& challenge_hash, int discriminant_size_bits,
                           uint64_t num_iterations) {
    integer D = CreateDiscriminant(challenge_hash, discriminant_size_bits);
    integer L = root(-D, 4);
    PulmarkReducer reducer;
    form y = form::generator(D);
    std::vector<form> intermediates;
    int k, l;
    int int_size = (D.num_bits() + 16) >> 4;

    ApproximateParameters(num_iterations, l, k);
    for (int i = 0; i < num_iterations; i++) {
        if (i % (k * l) == 0) {
            intermediates.push_back(y);
        }
        nudupl_form(y, y, D, L);
        reducer.reduce(y);
    } 
    form x = form::generator(D);
    form proof = GenerateWesolowski(y, x, D, reducer, intermediates, num_iterations, k, l);
    std::vector<uint8_t> result = SerializeForm(y, int_size);
    std::vector<uint8_t> proof_bytes = SerializeForm(proof, int_size);
    result.insert(result.end(), proof_bytes.begin(), proof_bytes.end());
    return result;
}
