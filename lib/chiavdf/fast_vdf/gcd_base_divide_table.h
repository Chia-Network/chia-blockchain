const uint64 data_mask=bit_sequence(0, data_size);
const int carry_size=64-data_size;
const uint64 carry_mask=bit_sequence(data_size, carry_size);

namespace simd_integer_namespace {


int64 abs_int(int64 v) {
    return (v<0)? -v : v;
}

int divide_table_stats_calls=0;
int divide_table_stats_table=0;

//generic_stats gcd_64_num_iterations;

//used for both gcd and reduce
int64 divide_table_lookup(int64 index) {
    assert(index>=0 && index<=bit_sequence(0, divide_table_index_bits));

    uint128 res = (~uint128(0)) / uint128(max(uint64(index), uint64(1)));
    res>>=64;

    return res;
}

int64 divide_table_64(int64 a, int64 b, int64& q) {
    assert(b>0);

    q=a/b;
    int64 r=a%b;

    if (r<0) {
        r+=b;
        --q;
    }

    assert(r>=0 && r<b && q*b+r==a);

    return r;
}

//note: this floors the quotient instead of truncating it like the div instruction
int64 divide_table(int64 a, int64 b, int64& q) {
    const bool test_asm_funcs=false;

    ++divide_table_stats_calls;

    assert(b>0);

    //b_shift=(64-divide_table_index_bits) - lzcnt(b)
    //bsr(b)=63-lzcnt(b)
    //63-bsr(b)=lzcnt(b)
    //b_shift=(64-divide_table_index_bits) - 63-bsr(b)
    //b_shift=64-divide_table_index_bits - 63 + bsr(b)
    //b_shift=1-divide_table_index_bits + bsr(b)
    //b_shift=bsr(b) - (divide_table_index_bits-1)

    int b_shift = (64-divide_table_index_bits) - __builtin_clzll(b);
    if (b_shift<0) { //almost never happens
        b_shift=0;
    }

    int64 b_approx = b >> b_shift;
    int64 b_approx_inverse = divide_table_lookup(b_approx);

    q = (int128(a)*int128(b_approx_inverse)) >> 64; //high part of product
    q >>= b_shift;

    int128 qb_128=int128(q)*int128(b);
    int64 qb_64=int64(qb_128);

    int128 r_128=int128(a)-int128(qb_64);
    int64 r_64=int64(r_128);

    //int128 r=int128(a)-int128(q)*int128(b);
    //if (uint128(r)>=b) {

    bool invalid_1=(int128(qb_64)!=qb_128 || int128(r_64)!=r_128 || uint64(r_64)>=b);

    int128 r_2=int128(a)-int128(q)*int128(b);

    bool invalid_2=(uint128(r_2)>=b);

    assert(invalid_1==invalid_2);
    if (!invalid_2) {
        assert(r_64==int64(r_2));
    }

    int64 r=r_2;
    if (invalid_2) {
        r=divide_table_64(a, b, q);
    } else {
        ++divide_table_stats_table;
    }

    int64 q_expected;
    int64 r_expected=divide_table_64(a, b, q_expected);

    assert(q==q_expected);
    assert(r==r_expected);

    //if (test_asm_funcs) {
        //int64 q_asm;
        //int64 r_asm=divide_table_asm(a, b, q_asm);

        //assert(q_asm==q_expected);
        //assert(r_asm==r_expected);
    //}

    return r;
}

void gcd_64(
    array<int64, 2> start_a, pair<array<int64, 4>, array<int64, 2>>& res, int& num_iterations, bool approximate, int max_iterations
) {
    const bool test_asm_funcs=false;

    array<int64, 4> uv={1, 0, 0, 1};
    array<int64, 2> a=start_a;

    num_iterations=0;

    if (approximate && (start_a[0]==start_a[1] || start_a[1]==0)) {
        res=make_pair(uv, a);
        return;
    }

    int asm_num_iterations=0;
    array<int64, 4> uv_asm=uv;
    array<int64, 2> a_asm=a;

    while (true) {
        if (test_asm_funcs) {
            //if (gcd_64_iteration_asm(a_asm, uv_asm, approximate)) {
                //++asm_num_iterations;
            //}
        }

        if (a[1]==0) {
            break;
        }

        assert(a[0]>a[1] && a[1]>0);

        int64 q;
        int64 r=divide_table(a[0], a[1], q);
        {
            int shift_amount=63-gcd_num_quotient_bits;
            if ((q<<shift_amount)>>shift_amount!=q) {
                break;
            }
        }


        array<int64, 2> new_a={a[1], r};

        array<int64, 4> new_uv;
        for (int x=0;x<2;++x) {
            new_uv[0*2+x]=uv[1*2+x];
            new_uv[1*2+x]=uv[0*2+x] - q*uv[1*2+x];
        }

        bool valid=true;

        if (approximate) {
            assert(new_uv[1*2+0]!=0);
            bool is_even=(new_uv[1*2+0]<0);

            bool valid_exact;
            if (is_even) {
                valid_exact=(new_a[1]>=-new_uv[1*2+0] && new_a[0]-new_a[1]>=new_uv[1*2+1]-new_uv[0*2+1]);
            } else {
                valid_exact=(new_a[1]>=-new_uv[1*2+1] && new_a[0]-new_a[1]>=new_uv[1*2+0]-new_uv[0*2+0]);
            }

            //valid=valid_exact;
            valid=
                (new_a[1]>=-new_uv[1*2+0] && new_a[0]-new_a[1]>=new_uv[1*2+1]-new_uv[0*2+1]) &&
                (new_a[1]>=-new_uv[1*2+1] && new_a[0]-new_a[1]>=new_uv[1*2+0]-new_uv[0*2+0])
            ;

            assert(valid==valid_exact);

            if (valid) {
                assert(valid_exact);
            }
        }

        //have to do this even if approximate is false
        for (int x=0;x<4;++x) {
            if (abs_int(new_uv[x])>data_mask) {
                valid=false;
            }
        }

        if (!valid) {
            break;
        }

        uv=new_uv;
        a=new_a;
        ++num_iterations;

        if (test_asm_funcs) {
            assert(uv==uv_asm);
            assert(a==a_asm);
            assert(num_iterations==asm_num_iterations);
        }

        if (num_iterations>=max_iterations) {
            break;
        }
    }

    //gcd_64_num_iterations.add(num_iterations);

    for (int x=0;x<4;++x) {
        assert(abs_int(uv[x])<=data_mask);
    }

    if (test_asm_funcs) {
        assert(uv==uv_asm);
        //assert(a==a_asm); the asm code will update a even if it becomes invalid; fine since it's not used
        assert(num_iterations==asm_num_iterations);
    }

    res=make_pair(uv, a);
}


}