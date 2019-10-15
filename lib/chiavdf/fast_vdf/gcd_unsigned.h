//threshold is 0 to calculate the normal gcd
template<int size> void gcd_unsigned_slow(
    array<fixed_integer<uint64, size>, 2>& ab,
    array<fixed_integer<uint64, size>, 2>& uv,
    int& parity,
    fixed_integer<uint64, size> threshold=fixed_integer<uint64, size>(integer(0))
) {
    assert(ab[0]>threshold);

    while (ab[1]>threshold) {
        fixed_integer<uint64, size> q(ab[0]/ab[1]);
        fixed_integer<uint64, size> r(ab[0]%ab[1]);

        ab[0]=ab[1];
        ab[1]=r;

        //this is the absolute value of the cofactor matrix
        auto u1_new=uv[0] + q*uv[1];
        uv[0]=uv[1];
        uv[1]=u1_new;

        parity=-parity;
    }
}

//todo
//test this by making two numbers that have a specified quotient sequence. can add big quotients then
//to generate numbers with a certain quotient sequence:
//euclidean algorithm: q=a/b ; a'=b ; b'=a-q*b ; terminates when b'=0
//initially b'=0 and all qs are known
//first iteration: b'=a-q*b=0 ; a=q*b ; select some b and this will determine a
//next: b'=a-q*b ; a'=b ; b'=a-q*a' ; b'+q*a'=a

//uv is <1,0> to calculate |u| and <0,1> to calculate |v|
//parity is negated for each quotient
template<int size> void gcd_unsigned(
    array<fixed_integer<uint64, size>, 2>& ab,
    array<fixed_integer<uint64, size>, 2>& uv,
    int& parity,
    fixed_integer<uint64, size> threshold=fixed_integer<uint64, size>(integer(0))
) {
    typedef fixed_integer<uint64, size> int_t;

    static int test_asm_counter=0;
    ++test_asm_counter;

    bool test_asm_run=true;
    bool test_asm_print=(test_asm_counter%1000==0);
    bool debug_output=false;

    assert(ab[0]>=ab[1] && !ab[1].is_negative());
    assert(!ab[0].is_negative() && !ab[1].is_negative());
    assert(!uv[0].is_negative() && !uv[1].is_negative());

    auto ab_start=ab;
    auto uv_start=uv;
    int parity_start=parity;
    int a_num_bits_old=-1;

    int iter=0;

    vector<array<array<uint64, 2>, 2>> matricies;
    vector<int> local_parities;
    bool valid=true;

    while (true) {
        assert(ab[0]>=ab[1] && !ab[1].is_negative());

        if (debug_output) {
            print( "" );
            print( "" );
            print( "====================================" );

            for (int x=0;x<size;++x) print( "a limb", x, ab[0][x] );
            print( "" );

            for (int x=0;x<size;++x) print( "b limb", x, ab[1][x] );
            print( "" );

            for (int x=0;x<size;++x) print( "threshold limb", x, threshold[x] );
            print( "" );
        }

        if (ab[0]<=threshold) {
            valid=false;
            print( "    gcd_unsigned slow 1" );
            break;
        }

        if (ab[1]<=threshold) {
            if (debug_output) print( "ab[1]<=threshold" );
            break;
        }

        //there is a cached num limbs for a. the num limbs for b and ab_threshold is smaller
        //to calculate the new cached num limbs:
        //-look at previous value. if limb is 0, go on to the next lowest limb. a cannot be 0 but should still tolerate this without crashing
        //-unroll this two times
        //-if more than 2 iterations are required, use a loop
        //-a can only decrease in size so its true size can't be larger
        //-this also calculates the head limb of a. need the top 3 head limbs. they are 0-padded if a is less than 3 nonzero limbs
        //-the 3 head limbs are used to do the shift
        //-this also truncates threshold and compares a[1] with the truncated value. it will exit if they are equal. this is not
        // exactly the same as the c++ code
        //-should probably implement this in c++ first then to make the two codes the same
        int a_num_bits=ab[0].num_bits();
        int shift_amount=a_num_bits-128; //todo //changed this to 128 bits
        if (shift_amount<0) {
            shift_amount=0;
        }

        //print( "gcd_unsigned", a_num_bits, a_num_bits_old-a_num_bits );
        a_num_bits_old=a_num_bits;

        array<uint128, 2> ab_head={
            uint128(ab[0].window(shift_amount)) | (uint128(ab[0].window(shift_amount+64))<<64),
            uint128(ab[1].window(shift_amount)) | (uint128(ab[1].window(shift_amount+64))<<64)
        };
        //assert((ab_head[0]>>127)==0);
        //assert((ab_head[1]>>127)==0);

        uint128 threshold_head=uint128(threshold.window(shift_amount)) | (uint128(threshold.window(shift_amount+64))<<64);
        //assert((threshold_head>>127)==0);

        //don't actually need to do this
        //it will compare threshold_head with > so it will already exit if they are equal
        //if (shift_amount!=0) {
        //    ++threshold_head;
        //}

        if (debug_output) print( "a_num_bits:", a_num_bits );
        if (debug_output) print( "a last index:", (a_num_bits+63/64)-1 );
        if (debug_output) print( "shift_amount:", shift_amount );
        if (debug_output) print( "ab_head[0]:", uint64(ab_head[0]), uint64(ab_head[0]>>64) );
        if (debug_output) print( "ab_head[1]:", uint64(ab_head[1]), uint64(ab_head[1]>>64) );
        if (debug_output) print( "threshold_head:", uint64(threshold_head), uint64(threshold_head>>64) );

        array<array<uint64, 2>, 2> uv_uint64;
        int local_parity; //1 if odd, 0 if even
        if (gcd_128(ab_head, uv_uint64, local_parity, shift_amount!=0, threshold_head)) {
            //int local_parity=(uv_double[1][1]<0)? 1 : 0; //sign bit
            bool even=(local_parity==0);

            if (debug_output) print( "u:", uv_uint64[0][0], uv_uint64[1][0] );
            if (debug_output) print( "v:", uv_uint64[0][1], uv_uint64[1][1] );
            if (debug_output) print( "local parity:", local_parity );

            uint64 uv_00=uv_uint64[0][0];
            uint64 uv_01=uv_uint64[0][1];
            uint64 uv_10=uv_uint64[1][0];
            uint64 uv_11=uv_uint64[1][1];

            //can use a_num_bits to make these smaller. this is at most a 2x speedup for these mutliplications which probably doesn't matter
            //can do this with an unsigned subtraction and just swap the pointers
            //
            //this is an unsigned subtraction with the input pointers swapped to make the result nonnegative
            //
            //this uses mulx/adox/adcx if available for the multiplication
            //will unroll the multiplication loop but early-exit based on the number of limbs in a (calculated before). this gives each
            //branch its own branch predictor entry. each branch is at a multiple of 4 limbs. don't need to pad a
            int_t a_new_1=ab[0]; a_new_1*=uv_00; a_new_1.set_negative(!even);
            int_t a_new_2=ab[1]; a_new_2*=uv_01; a_new_2.set_negative(even);
            int_t b_new_1=ab[0]; b_new_1*=uv_10; b_new_1.set_negative(even);
            int_t b_new_2=ab[1]; b_new_2*=uv_11; b_new_2.set_negative(!even);

            //both of these are subtractions; the signs determine the direction. the result is nonnegative
            int_t a_new;
            int_t b_new;
            if (!even) {
                a_new=int_t(a_new_2 + a_new_1);
                b_new=int_t(b_new_1 + b_new_2);
            } else {
                a_new=int_t(a_new_1 + a_new_2);
                b_new=int_t(b_new_2 + b_new_1);
            }

            //this allows the add function to be optimized
            assert(!a_new.is_negative());
            assert(!b_new.is_negative());

            //do not do any of this stuff; instead return an array of matricies
            //the array is processed while it is being generated so it is cache line aligned, has a counter, etc

            ab[0]=a_new;
            ab[1]=b_new;

            //bx and by are nonnegative
            auto dot=[&](uint64 ax, uint64 ay, int_t bx, int_t by) -> int_t {
                bx*=ax;
                by*=ay;
                return int_t(bx+by);
            };

            int_t new_uv_0=dot(uv_00, uv_01, uv[0], uv[1]);
            int_t new_uv_1=dot(uv_10, uv_11, uv[0], uv[1]);

            uv[0]=new_uv_0;
            uv[1]=new_uv_1;

            //local_parity is 0 even, 1 odd
            //want 1 even, -1 odd
            //todo: don't do this; just make it 0 even, 1 odd
            parity*=1-local_parity-local_parity;

            matricies.push_back(uv_uint64);
            local_parities.push_back(local_parity);
        } else {
            //can just make the gcd fail if this happens in the asm code
            print( "    gcd_unsigned slow" );
            //todo assert(false); //very unlikely to happen if there are no bugs

            valid=false;
            break;

            /*had_slow=true;

            fixed_integer<uint64, size> q(ab[0]/ab[1]);
            fixed_integer<uint64, size> r(ab[0]%ab[1]);

            ab[0]=ab[1];
            ab[1]=r;

            //this is the absolute value of the cofactor matrix
            auto u1_new=uv[0] + q*uv[1];
            uv[0]=uv[1];
            uv[1]=u1_new;

            parity=-parity;*/
        }

        ++iter;
    }

    {
        auto ab2=ab_start;
        auto uv2=uv_start;
        int parity2=parity_start;
        gcd_unsigned_slow(ab2, uv2, parity2, threshold);

        if (valid) {
            assert(integer(ab[0]) == integer(ab2[0]));
            assert(integer(ab[1]) == integer(ab2[1]));
            assert(integer(uv[0]) == integer(uv2[0]));
            assert(integer(uv[1]) == integer(uv2[1]));
            assert(parity==parity2);
        } else {
            ab=ab2;
            uv=uv2;
            parity=parity2;
        }
    }

    #ifdef TEST_ASM
    if (test_asm_run) {
        if (test_asm_print) {
            print( "test asm gcd_unsigned", test_asm_counter );
        }

        asm_code::asm_func_gcd_unsigned_data asm_data;

        const int asm_size=gcd_size;
        const int asm_max_iter=gcd_max_iterations;

        assert(size>=1 && size<=asm_size);

        fixed_integer<uint64, asm_size> asm_a(ab_start[0]);
        fixed_integer<uint64, asm_size> asm_b(ab_start[1]);
        fixed_integer<uint64, asm_size> asm_a_2;
        fixed_integer<uint64, asm_size> asm_b_2;
        fixed_integer<uint64, asm_size> asm_threshold(threshold);

        uint64 asm_uv_counter_start=1234;
        uint64 asm_uv_counter=asm_uv_counter_start;

        array<array<uint64, 8>, asm_max_iter+1> asm_uv;

        asm_data.a=&asm_a[0];
        asm_data.b=&asm_b[0];
        asm_data.a_2=&asm_a_2[0];
        asm_data.b_2=&asm_b_2[0];
        asm_data.threshold=&asm_threshold[0];

        asm_data.uv_counter_start=asm_uv_counter_start;
        asm_data.out_uv_counter_addr=&asm_uv_counter;
        asm_data.out_uv_addr=(uint64*)&asm_uv[1];
        asm_data.iter=-2; //uninitialized
        asm_data.a_end_index=size-1;

        int error_code=asm_code::asm_func_gcd_unsigned(&asm_data);

        auto asm_get_uv=[&](int i) {
            array<array<uint64, 2>, 2> res;
            res[0][0]=asm_uv[i+1][0];
            res[1][0]=asm_uv[i+1][1];
            res[0][1]=asm_uv[i+1][2];
            res[1][1]=asm_uv[i+1][3];
            return res;
        };

        auto asm_get_parity=[&](int i) {
            uint64 r=asm_uv[i+1][4];
            assert(r==0 || r==1);
            return bool(r);
        };

        auto asm_get_exit_flag=[&](int i) {
            uint64 r=asm_uv[i+1][5];
            assert(r==0 || r==1);
            return bool(r);
        };

        if (error_code==0) {
            assert(valid);

            assert(asm_data.iter>=0 && asm_data.iter<=asm_max_iter); //total number of iterations performed
            bool is_even=((asm_data.iter-1)&1)==0; //parity of last iteration (can be -1)

            fixed_integer<uint64, asm_size>& asm_a_res=(is_even)? asm_a_2 : asm_a;
            fixed_integer<uint64, asm_size>& asm_b_res=(is_even)? asm_b_2 : asm_b;

            assert(integer(asm_a_res) == integer(ab[0]));
            assert(integer(asm_b_res) == integer(ab[1]));

            for (int x=0;x<=matricies.size();++x) {
                assert( asm_get_exit_flag(x-1) == (x==matricies.size()) );

                if (x!=matricies.size()) {
                    assert(asm_get_parity(x)==local_parities[x]);
                    assert(asm_get_uv(x)==matricies[x]);
                }
            }

            assert(matricies.size()==asm_data.iter);
            assert(asm_uv_counter==asm_uv_counter_start+asm_data.iter-1); //the last iteration that updated the counter is iter-1
        } else {
            if (!valid) {
                print( "test asm gcd_unsigned error", error_code );
            }
        }
    }
    #endif

    assert(integer(ab[0])>integer(threshold));
    assert(integer(ab[1])<=integer(threshold));
}
