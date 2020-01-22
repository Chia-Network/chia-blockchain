#include "integer_common.h"
#include "xgcd_partial.c"

//a and b are nonnegative
void xgcd_partial(integer& u, integer& v, integer& a, integer& b, const integer& L) {
    mpz_t f_u; mpz_init(f_u);
    mpz_t f_v; mpz_init(f_v);
    mpz_t f_a; mpz_init(f_a);
    mpz_t f_b; mpz_init(f_b);
    mpz_t f_L; mpz_init(f_L);

    mpz_set(f_a, a.impl);
    mpz_set(f_b, b.impl);
    mpz_set(f_L, L.impl);

    mpz_xgcd_partial(f_u, f_v, f_a, f_b, f_L);

    mpz_set(u.impl, f_u);
    mpz_set(v.impl, f_v);
    mpz_set(a.impl, f_a);
    mpz_set(b.impl, f_b);

    mpz_clear(f_u);
    mpz_clear(f_v);
    mpz_clear(f_a);
    mpz_clear(f_b);
    mpz_clear(f_L);
}

void inject_error(mpz_struct* i) {
    if (!enable_random_error_injection) {
        return;
    }

    mark_vdf_test();

    double v=rand_integer(32).to_vector()[0]/double(1ull<<32);

    if (v<random_error_injection_rate) {
        print( "injected random error" );

        int pos=int(rand_integer(31).to_vector()[0]);
        pos%=mpz_sizeinbase(i, 2);
        mpz_combit(i, pos);
    }
}
