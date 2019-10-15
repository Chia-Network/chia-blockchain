bool gcd_128(
    array<uint128, 2>& ab, array<array<uint64, 2>, 2>& uv_uint64, int& uv_uint64_parity, bool is_lehmer, uint128 ab_threshold=0
) {
    static int test_asm_counter=0;
    ++test_asm_counter;

    bool test_asm_run=true;
    bool test_asm_print=false; //(test_asm_counter%1000==0);
    bool debug_output=false;

    if (debug_output) {
        cerr.setf(ios::fixed, ios::floatfield);
        //cerr.setf(ios::showpoint);
    }

    assert(ab[0]>=ab[1] && ab[1]>=0);

    uv_uint64={
        array<uint64,2>{1, 0},
        array<uint64,2>{0, 1}
    };
    uv_uint64_parity=0;

    array<uint128, 2> ab_start=ab;

    bool progress=false;
    int iter=0;

    while (true) {
        if (debug_output) print(
            "======== 1:", iter,
            uint64(ab[0]), uint64(ab[0]>>64), uint64(ab[1]), uint64(ab[1]>>64),
            uint64(ab_threshold), uint64(ab_threshold>>64)
        );

        if (ab[1]<=ab_threshold) {
            break;
        }

        assert(ab[0]>=ab[1] && ab[1]>=0);

        int a_zeros=0;

        //this uses CMOV
        if ((ab[0]>>64)!=0) {
            uint64 a_high(ab[0]>>64);
            assert(a_high!=0);
            a_zeros=__builtin_clzll(a_high);
        } else {
            uint64 a_low(ab[0]);
            assert(a_low!=0);
            a_zeros=64+__builtin_clzll(a_low);
        }

        int a_num_bits=128-a_zeros;
        if (is_lehmer) {
            const int min_bits=96;
            if (a_num_bits<min_bits) {
                a_num_bits=min_bits;
            }
        }

        int shift_amount=a_num_bits-gcd_base_bits;
        if (shift_amount<0) {
            shift_amount=0;
        }

        if (debug_output) print( "2:", a_zeros, a_num_bits, shift_amount );

        //print( "    gcd_128", a_num_bits );

        vector2 ab_double{
            double(uint64(ab[0]>>shift_amount)),
            double(uint64(ab[1]>>shift_amount))
        };
        double ab_threshold_double(uint64(ab_threshold>>shift_amount));

        if (debug_output) print( "3:", ab_double[0], ab_double[1], ab_threshold_double, is_lehmer || (shift_amount!=0) );

        vector2 ab_double_2=ab_double;

        //this doesn't need to be exact
        //all of the comparisons with threshold are >, so this shouldn't be required
        //if (shift_amount!=0) {
        //    ++ab_threshold_double;
        //}

        //void gcd_64(vector2 start_a, pair<matrix2, vector2>& res, int& num_iterations, bool approximate, int max_iterations) {
        //}

        matrix2 uv_double;
        if (!gcd_base_continued_fraction(ab_double, uv_double, is_lehmer || (shift_amount!=0), ab_threshold_double)) {
            print( "        gcd_128 break 1" ); //this is fine
            break;
        }

        if (debug_output) print( "4:", uv_double[0][0], uv_double[1][0], uv_double[0][1], uv_double[1][1], ab_double[0], ab_double[1] );

        if (0) {
            matrix2 uv_double_2;
            if (!gcd_base_continued_fraction_2(ab_double_2, uv_double_2, is_lehmer || (shift_amount!=0), ab_threshold_double)) {
                print( "        gcd_128 break 2" );
                break;
            }

            assert(uv_double==uv_double_2);
            assert(ab_double==ab_double_2);
        }

        array<array<uint64,2>,2> uv_double_int={
            array<uint64,2>{uint64(abs(uv_double[0][0])), uint64(abs(uv_double[0][1]))},
            array<uint64,2>{uint64(abs(uv_double[1][0])), uint64(abs(uv_double[1][1]))}
        };

        int uv_double_parity=(uv_double[1][1]<0)? 1 : 0; //sign bit

        array<array<uint64, 2>, 2> uv_uint64_new;
        if (iter==0) {
            uv_uint64_new=uv_double_int;
        } else {
            if (!multiply_exact(uv_double_int, uv_uint64, uv_uint64_new)) {
                print( "        gcd_128 slow 1" ); //calculated a bunch of quotients and threw all of them away, which is bad
                break;
            }
        }

        int uv_uint64_parity_new=uv_uint64_parity^uv_double_parity;
        bool even=(uv_uint64_parity_new==0);

        if (debug_output) print(
            "5:", uv_uint64_new[0][0], uv_uint64_new[1][0], uv_uint64_new[0][1], uv_uint64_new[1][1], uv_uint64_parity_new
        );

        uint64 uv_00=uv_uint64_new[0][0];
        uint64 uv_01=uv_uint64_new[0][1];
        uint64 uv_10=uv_uint64_new[1][0];
        uint64 uv_11=uv_uint64_new[1][1];

        uint128 a_new_1=ab_start[0]; a_new_1*=uv_00; //a_new_1.set_negative(!even);
        uint128 a_new_2=ab_start[1]; a_new_2*=uv_01; //a_new_2.set_negative(even);
        uint128 b_new_1=ab_start[1]; b_new_1*=uv_11; //b_new_1.set_negative(!even);
        uint128 b_new_2=ab_start[0]; b_new_2*=uv_10; //b_new_2.set_negative(even);

        //CMOV
        //print( "        gcd_128 even", even );
        if (!even) {
            swap(a_new_1, a_new_2);
            swap(b_new_1, b_new_2);
        }

        uint128 a_new_s=a_new_1-a_new_2;
        uint128 b_new_s=b_new_1-b_new_2;

        //if this assert hit, one of the quotients is wrong. the base case is not supposed to return incorrect quotients
        //assert(a_new_s>=b_new_s && b_new_s>=0);
        //commenting this out because a and b can be 128 bits now

        //if (!(a_new_s>=b_new_s && b_new_s>=0)) {
            //print( "        gcd_128 slow 2" );
            //break;
        //}

        uint128 a_new(a_new_s);
        uint128 b_new(b_new_s);

        if (debug_output) print( "6:", uint64(a_new), uint64(a_new>>64), uint64(b_new), uint64(b_new>>64) );

        if (is_lehmer) {
            assert(a_new>=b_new);
            uint128 ab_delta=a_new-b_new;

            // even:
            // +uv_00 -uv_01
            // -uv_10 +uv_11

            uint128 u_delta=uint128(uv_10)+uint128(uv_00); //even: negative. odd: positive
            uint128 v_delta=uint128(uv_11)+uint128(uv_01); //even: positive. odd: negative

            // uv_10 is negative if even, positive if odd
            // uv_11 is positive if even, negative if odd
            bool passed_even=(b_new>=uint128(uv_10) && ab_delta>=v_delta);
            bool passed_odd=(b_new>=uint128(uv_11) && ab_delta>=u_delta);

            if (debug_output) print( "7:", passed_even, passed_odd );

            //CMOV
            if (!(even? passed_even : passed_odd)) {
                print( "        gcd_128 slow 5" ); //throwing away a bunch of quotients because the last one is bad
                break;
            }
        }

        if (a_new<=ab_threshold) {
            if (debug_output) print( "8:" );
            print( "        gcd_128 slow 6" ); //still throwing away quotients
            break;
        }

        ab={a_new, b_new};
        uv_uint64=uv_uint64_new;
        uv_uint64_parity=uv_uint64_parity_new;
        progress=true;

        ++iter;
        if (iter>=gcd_128_max_iter) {
            if (debug_output) print( "9:" );
            break; //this is the only way to exit the loop without wasting quotients
        }

        //todo break;
    }

    #ifdef TEST_ASM
    #ifndef GENERATE_ASM_TRACKING_DATA
    if (test_asm_run) {
        if (test_asm_print) {
            print( "test asm gcd_128", test_asm_counter );
        }

        asm_code::asm_func_gcd_128_data asm_data;

        asm_data.ab_start_0_0=uint64(ab_start[0]);
        asm_data.ab_start_0_8=uint64(ab_start[0]>>64);
        asm_data.ab_start_1_0=uint64(ab_start[1]);
        asm_data.ab_start_1_8=uint64(ab_start[1]>>64);

        asm_data.is_lehmer=uint64(is_lehmer);
        asm_data.ab_threshold_0=uint64(ab_threshold);
        asm_data.ab_threshold_8=uint64(ab_threshold>>64);

        int error_code=asm_code::asm_func_gcd_128(&asm_data);

        assert(error_code==0);
        assert(asm_data.u_0==uv_uint64[0][0]);
        assert(asm_data.u_1==uv_uint64[1][0]);
        assert(asm_data.v_0==uv_uint64[0][1]);
        assert(asm_data.v_1==uv_uint64[1][1]);
        assert(asm_data.parity==uv_uint64_parity);
        assert(asm_data.no_progress==int(!progress));
    }
    #endif
    #endif

    return progress;
}