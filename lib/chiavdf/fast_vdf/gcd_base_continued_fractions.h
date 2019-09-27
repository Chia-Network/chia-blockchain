typedef array<double, 2> vector2;
typedef array<vector2, 2> matrix2;

matrix2 identity_matrix() {
    return {
        vector2{1, 0},
        vector2{0, 1}
    };
}

matrix2 quotient_matrix(double q) {
    assert(int64(q)==q);

    return {
        vector2{0,  1},
        vector2{1, -q}
    };
}

bool range_check(double v) {
    //this is the smallest value where you can add 1 exactly
    //if you add 2, you get the same value as if you added 1
    //if two floats are added/subtracted and there is a loss of precision, the absolute value of the result will be greater than this
    //same with multiplication and fma
    //(all of the doubles are integers whether they are exact or not)
    return abs(v)<=double((1ull<<53)-1);
}

bool dot_product_exact(vector2 a, vector2 b, double& v, bool result_always_in_range=false) {
    v=a[0]*b[0];
    if (!range_check(v)) {
        return false;
    }

    if (enable_fma_in_c_code) {
        v=fma(a[1], b[1], v);
    } else {
        double v2=a[1]*b[1];
        if (!range_check(v2)) {
            return false;
        }

        v+=v2;
    }

    if (result_always_in_range) {
        //still need the first range_check since the intermediate value might not be in range
        assert(range_check(v));
    }

    return range_check(v);
}

//result_always_in_range ignored
bool dot_product_exact(array<uint64,2> a, array<uint64,2> b, uint64& v, bool result_always_in_range=false) {
    uint64 t1;
    if (__builtin_mul_overflow(a[0], b[0], &t1)) {
        return false;
    }

    uint64 t2;
    if (__builtin_mul_overflow(a[1], b[1], &t2)) {
        return false;
    }

    return !__builtin_add_overflow(t1, t2, &v);
}

template<class type> bool multiply_exact(
    array<array<type,2>,2> a, array<type,2> b, array<type,2>& v, bool result_always_in_range=false) {
    return
        dot_product_exact(a[0], b, v[0], result_always_in_range) &&
        dot_product_exact(a[1], b, v[1], result_always_in_range)
    ;
}

template<class type> bool multiply_exact(
    array<array<type,2>,2> a, array<array<type,2>,2> b, array<array<type,2>,2>& v, bool result_always_in_range=false
) {
    return
        dot_product_exact(a[0], array<type,2>{b[0][0], b[1][0]}, v[0][0], result_always_in_range) &&
        dot_product_exact(a[0], array<type,2>{b[0][1], b[1][1]}, v[0][1], result_always_in_range) &&
        dot_product_exact(a[1], array<type,2>{b[0][0], b[1][0]}, v[1][0], result_always_in_range) &&
        dot_product_exact(a[1], array<type,2>{b[0][1], b[1][1]}, v[1][1], result_always_in_range)
    ;
}

struct continued_fraction {
    vector<int> values;

    matrix2 get_matrix() {
        matrix2 res=identity_matrix();

        for (int i : values) {
            bool is_exact=multiply_exact(quotient_matrix(i), res, res);
            assert(is_exact);
        }

        return res;
    }

    bool truncate(double max_matrix_value) {
        bool res=false;

        while (true) {
            matrix2 m=get_matrix();
            double max_value=max(
                max(abs(m[0][0]), abs(m[0][1])),
                max(abs(m[1][0]), abs(m[1][1]))
            );

            if (max_value>max_matrix_value) {
                assert(!values.empty());
                values.pop_back();
                res=true;
            } else {
                break;
            }
        }

        return res;
    }

    bool is_superset_of(continued_fraction& targ) {
        if (values.size()>targ.values.size()) {
            return false;
        }

        for (int x=0;x<values.size();++x) {
            if (values[x]!=targ.values[x]) {
                return false;
            }
        }

        return true;
    }

    //rounds to 0; need to add 1 ulp to the fraction to get the possible range
    //if is_exact is true then the result is inside the continued fraction
    double get_bound(bool parity, bool& is_exact) {
        assert(!values.empty());

        bool first=true;
        mpq_class res=0;
        mpq_class one=1;

        for (int x=values.size()-1;x>=0;--x) {
            assert(values[x]>=1);

            if (first) {
                //the denominator of each fraction is between 1 and infinity
                //this is already canonicalized
                res=values[x] + (parity? 1 : 0);
            } else {
                //mpq_class(values[x]) is already canonicalized
                res=mpq_class(values[x]) + one/res;
            }

            first=false;
        }

        double res_double=res.get_d();
        {
            mpq_class res_double_mpq(res_double);
            res_double_mpq.canonicalize();

            is_exact=(res_double_mpq==res);
        }
        return res_double;
    }

    //everything inside the bound starts with this continued fraction
    //something outside the bound might also start with this continued fraction
    //>= first, < second
    pair<double, double> get_bound() {
        bool a_exact=false;
        double a=get_bound(false, a_exact);

        bool b_exact=false;
        double b=get_bound(true, b_exact);

        if (a>b) {
            swap(a, b);
            swap(a_exact, b_exact);
        }

        if (!a_exact) {
            //if a isn't exact, the next double value after a is inside the continued fraction (since it got rounded down). this assumes
            // the bound isn't so small that it is close to the double machine epsilon; this is checked later by the double_table code
            //if a is exact then it is inside the continued fraction
            a=nextafter(a, HUGE_VAL);
        }

        //if b isn't exact, then it got rounded down and the b value is inside the continued fraction. the next value after b will
        // be outside the continued fraction
        //if b is exact then it is also inside the continued fraction and the next value is outside
        b=nextafter(b, HUGE_VAL);

        return make_pair(a, b);
    }
};

//if you add 1 to the integer representation of a positive double, it will increase the value by 1 machine epsilon (assuming no overflow)
template<class type> struct double_table {
    vector<type> data; //data[x] is >= range_start+x*delta and < range_start+(x+1)*delta

    int exponent_bits;
    int fraction_bits;

    int64 range_start=0;
    int64 range_end=0;
    int64 delta=0;

    double range_start_double=0;
    double range_end_double=0;

    int right_shift_amount=0;
    uint64 range_start_shifted=0;
    uint64 range_end_shifted=0;

    //min value is 1
    double_table(int t_exponent_bits, int t_fraction_bits) {
        exponent_bits=t_exponent_bits;
        fraction_bits=t_fraction_bits;

        assert(exponent_bits>=0);
        assert(fraction_bits>=1);

        double_bits range_start_bits;
        range_start_bits.sign=false;
        range_start_bits.set_exponent(0);
        range_start_bits.fraction=0;
        range_start=range_start_bits.to_uint64();
        range_start_double=range_start_bits.to_double();

        double_bits range_end_bits;
        range_end_bits.sign=false;
        range_end_bits.set_exponent(1<<exponent_bits);
        range_end_bits.fraction=0;
        range_end=range_end_bits.to_uint64();
        range_end_double=range_end_bits.to_double();

        double_bits delta_bits;
        delta_bits.sign=false;
        delta_bits.exponent=0;
        delta_bits.fraction=1ull<<(double_bits::fraction_num_bits-fraction_bits);
        delta=delta_bits.to_uint64();

        assert(range_end>range_start);
        assert(range_start%delta==0);
        assert(range_end%delta==0);
        assert((range_end-range_start)/delta==1ull<<(exponent_bits+fraction_bits));

        data.resize(1ull<<(exponent_bits+fraction_bits));

        right_shift_amount=double_bits::fraction_num_bits-fraction_bits;
        range_start_shifted=uint64(range_start)>>right_shift_amount;
        range_end_shifted=uint64(range_end)>>right_shift_amount;
    }

    pair<double, double> index_range(int x) {
        int64 res_low=range_start+x*delta;
        int64 res_high=range_start+(x+1)*delta;
        return make_pair(*(double*)&res_low, *(double*)&res_high);
    }

    bool lookup(double v, type& res) {
        assert(v>=1);

        res=type();

        uint64 v_bits=*(uint64*)&v;
        uint64 v_bits_shifted=v_bits>>right_shift_amount;

        assert(v_bits_shifted>=range_start_shifted); //since v>=1
        if (v_bits_shifted<range_start_shifted || v_bits_shifted>=range_end_shifted) {
            return false;
        }

        //the table doesn't work if v is exactly between two slots
        //happens if the remainder is 0 for one of the quotients
        if (
            (v_bits & (delta-1)) == 0 ||
            (v_bits & (delta-1)) == delta-1
        ) {
            return false;
        }

        res=data.at(v_bits_shifted-range_start_shifted);
        return true;
    }

    //will assign all entries >= range.first and < range.second
    //returns true if the range is at least 0.5 entries wide (for that area of the table) and is within the table bounds
    bool assign(pair<double, double> range, type value, vector<type>& old_values) {
        old_values.clear();

        double start_double=range.first;
        double end_double=range.second;

        assert(start_double>0 && end_double>0 && end_double>=start_double && isfinite(start_double) && isfinite(end_double));

        if (end_double<range_start_double || start_double>range_end_double) {
            return false;
        }

        int64 start_bits=*(int64*)&start_double;
        int64 end_bits=*(int64*)&end_double;

        if (end_bits<=start_bits || 2*(end_bits-start_bits)<delta) {
            return false;
        }

        int64 start_pos=(start_bits-range_start)/delta;
        int64 end_pos=(end_bits-range_start)/delta + 1;
        assert(end_pos>=start_pos);

        if (start_pos<0) {
            start_pos=0;
        }

        if (end_pos>data.size()) {
            end_pos=data.size();
        }

        for (uint64 pos=start_pos;pos<end_pos;++pos) {
            pair<double, double> slot_range=index_range(pos);

            //if start_double==slot_range.first, then both ranges have the same starting double so that's fine
            //if end_double==slot_range.second, then both ranges have the same ending double which is also fine
            if (start_double<=slot_range.first && end_double>=slot_range.second) {
                old_values.push_back(data[pos]);
                data[pos]=value;
            }
        }

        return true;
    }
};

bool add_to_table(double_table<continued_fraction>& c_table, continued_fraction f) {
    vector<continued_fraction> old_values;
    if (!c_table.assign(f.get_bound(), f, old_values)) {
        return false;
    }

    for (continued_fraction& c : old_values) {
        assert(c.is_superset_of(f));
    }

    return true;
}

void add_children_to_table(double_table<continued_fraction>& c_table, continued_fraction f) {
    f.values.push_back(1);

    while (true) {
        if (!add_to_table(c_table, f)) {
            break;
        }

        add_children_to_table(c_table, f);

        assert(f.values.back()<INT_MAX);
        ++f.values.back();
    }
}

double_table<continued_fraction> generate_table(
    int exponent_bits, int fraction_bits, uint64 truncate_max_value=1ull<<53, bool output_stats=false, bool dump=false
) {
    double_table<continued_fraction> c_table(exponent_bits, fraction_bits);
    add_children_to_table(c_table, continued_fraction());

    bool any_truncated=false;
    for (continued_fraction& c : c_table.data) {
        assert(double(truncate_max_value)==truncate_max_value);
        any_truncated |= c.truncate(truncate_max_value);
    }

    //if the exponent has too many bits, some of the table entries will span multiple integers and won't have any entries
    //all of the full entries are at the start of the table, and all of the empty entires are at the end. they aren't interleaved
    //when setting up the table range checks, should truncate off all of the empty values so they won't affect cache coherency
    int num_empty=0;

    for (int x=0;x<c_table.data.size();++x) {
        if (dump) {
            cerr << c_table.index_range(x).first << ", " << c_table.index_range(x).second << " : ";
            for (int i : c_table.data[x].values) {
                cerr << i << ", ";
            }
            cerr << "\n";
        }

        bool is_empty=(c_table.data[x].values.empty());
        if (is_empty) {
            ++num_empty;
        } else {
            //all of the empty values are supposed to be before the non-empty values
            assert(num_empty==0);
        }
    }

    assert(num_empty==0); //gcd algorithm won't check for this

    if (output_stats) {
        print( "non-empty:", c_table.data.size()-num_empty, "; empty:", num_empty );
        if (any_truncated) {
            print( "truncated" );
        }
    }

    return c_table;
}

//initial uv is the identity matrix
//parity is the number of quotients mod 2
//
//if uv is unsigned:
//-the parity is the sign of uv[1][1] (1 if negative)
//-to calculate the next uv, just multiply the unsigned matricies together. also add the parities modulo 2
//-to calculate ab from the starting ab, do a subtraction in the dot product instead of adding, then take the absolute value of the
// result. can also use the parity to decide what way to do the subtraction.
// - odd parity: b-a, a-b
// -even parity: a-b, b-a
// -can calculate assuming even parity. then sign extend the parity to 64 bits (from 1 bit) and use the parity as the carry in,
//  then xor the result by the sign extended parity and add the carry. this can also determine the parity if it is unknown
//
//  odd parity uv: { <=0 > 0
//                   > 0 < 0}
// even parity uv: { >=0 <=0s
//                   <=0 > 0}

//if this returns false then the new values are invalid and the old values are valid
//this works if u/v are unsigned, if v[1]-v[0] is replaced with |v[1]|+|v[0]| and -u[1] is replaced with |u1| etc
bool check_lehmer(array<int64, 2> a, array<int64, 2> u, array<int64, 2> v) {
    // a[0]-a[1] is always >= 0 ; also a[1]>=0
    // odd parity  ; u[0]<=0 ; u[1]> 0 ; v[0]> 0 ; v[1]< 0
    // even parity ; u[0]>=0 ; u[1]<=0 ; v[0]<=0 ; v[1]> 0
    return
        a[1]>=-u[1] && int128(a[0])-int128(a[1]) >= int128(v[1])-int128(v[0]) && // even parity
        a[1]>=-v[1] && int128(a[0])-int128(a[1]) >= int128(u[1])-int128(u[0])    //  odd parity
    ;
}

bool gcd_base_continued_fraction(vector2& ab, matrix2& uv, bool is_lehmer, double ab_threshold=0) {
    static double_table<continued_fraction> c_table=generate_table(gcd_table_num_exponent_bits, gcd_table_num_fraction_bits);

    static int test_asm_counter=0;
    ++test_asm_counter;

    bool test_asm_run=true;
    bool test_asm_print=false; //(test_asm_counter%1000==0);
    bool debug_output=false;

    assert(ab[0]>=ab[1] && ab[1]>=0);

    uv=identity_matrix();

    auto ab_start=ab;

    bool progress=false;
    bool enable_table=true;

    int iter=0;
    int iter_table=0;
    int iter_slow=0;

    if (debug_output) {
        cerr.setf(ios::fixed, ios::floatfield);
        //cerr.setf(ios::showpoint);
    }

    while (true) {
        if (debug_output) print( "======== 1:", iter, ab[1], ab_threshold);

        if (ab[1]<=ab_threshold) {
            if (debug_output) print( "1.5:" );
            break;
        }

        //print( "        gcd_base", uint64(ab[0]) );

        assert(ab[0]>=ab[1] && ab[1]>=0);

        double q=ab[0]/ab[1];

        if (debug_output) print( "2:", q );

        vector2 new_ab;
        matrix2 new_uv;

        bool used_table=false;

        continued_fraction f;
        if (enable_table && c_table.lookup(q, f)) {
            assert(!f.values.empty()); //table should be set up not to have empty values

            if (debug_output) print( "3:", f.get_matrix()[0][0], f.get_matrix()[1][0], f.get_matrix()[0][1], f.get_matrix()[1][1] );

            bool new_ab_valid=multiply_exact(f.get_matrix(), ab, new_ab, true); //a and b can only be reduced in magnitude
            bool new_uv_valid=multiply_exact(f.get_matrix(), uv, new_uv);
            bool new_a_valid=(new_ab[0]>ab_threshold);

            if (debug_output) print( "4:", new_ab_valid, new_uv_valid, new_a_valid );
            if (debug_output) print( "5:", new_ab[0], new_ab[1], new_uv[0][0], new_uv[1][0], new_uv[0][1], new_uv[1][1] );

            if (new_ab_valid && new_uv_valid && new_a_valid) {
                used_table=true;
                ++iter_table;
            } else {
                //this should be disabled to make the output the same as the non-table version
                //this is disabled in the asm version
                //if (is_lehmer && ab_threshold==0) {
                    //can also bypass the table but it is probably slower
                    //if ab_threshold is not 0, need to keep going since the partial gcd is about to terminate
                    //break;
                //}
            }
        }

        if (!used_table) {
            //the native instruction is as fast as adding then subtracting some magic number
            q=floor(q);
            ++iter_slow;

            if (debug_output) print( "6:", q );

            matrix2 m=quotient_matrix(q);

            bool new_ab_valid=multiply_exact(m, ab, new_ab, true);
            bool new_uv_valid=multiply_exact(m, uv, new_uv);

            if (debug_output) print( "6.5:", new_ab[0], new_ab[1], new_uv[0][0], new_uv[1][0], new_uv[0][1], new_uv[1][1] );

            if (!new_ab_valid || !new_uv_valid) {
                if (debug_output) print( "7:" );
                break;
            }

            //double new_b=fma(-q, ab[1], ab[0]);

            //double new_u;
            //double new_v;

            //iter 0 is unrolled separately
            //can probably just unroll all 6 iterations
            //if (iter==0) {
                //new_u=1;
                //new_v=-q;
            //} else {//}

            //new_u=fma(-q, uv[1][0], uv[0][0]);
            //new_v=fma(-q, uv[1][1], uv[0][1]);

            //if (debug_output) print( "6:", q, new_b, new_u, new_v );

            //if (!range_check(new_u) || !range_check(new_v)) {
                //if (debug_output) print( "7" );
                //break;
            //}

            //assert(range_check(new_b)); //a and b can only be reduced in magnitude

            //new_ab={ab[1], new_b};
            //new_uv={
                //vector2{uv[1][0], uv[1][1]},
                //vector2{   new_u,    new_v}
            //};
        }

        //this has to be checked on the first iteration if the table is not used (since there could be a giant quotient e.g. a=b)
        //will check it even if the table is used. shouldn't affect performance
        if (is_lehmer) {
            double ab_delta=new_ab[0]-new_ab[1];
            assert(range_check(ab_delta)); //both are nonnegative so the subtraction can't increase the magnitude
            assert(ab_delta>=0); //ab[0] has to be greater

            //the magnitudes add for these
            //however, the comparison is ab_delta >= u_delta or v_delta, and ab_delta>=0, so the values of u_delta and v_delta can
            // be increased. if the calculation is not exact, the values will be ceil'ed so they are exact or increased; never reduced
            //double u_delta=uv[1][0]-uv[0][0];
            //double v_delta=uv[1][1]-uv[0][1];

            //even parity:
            //don't care what the result of the odd comparison is as far as correctness goes. for performance, it has to be true most
            // of the time
            // uv[0][1]<=0 ; uv[1][1]>=0
            //ab_delta+uv[0][1] is exact because the signs are opposite
            //ab_delta+uv[0][0] is <= the true value so the comparison might return false wrongly. should be fine

            bool even=(new_uv[1][1]>=0);

            if (even) {
                assert(range_check(ab_delta+new_uv[0][1]));
            } else {
                assert(range_check(ab_delta+new_uv[0][0]));
            }

            bool passed=
                new_ab[1]>=-new_uv[1][0] && ab_delta+new_uv[0][1]>=new_uv[1][1] && // even parity. for odd parity this is always true
                new_ab[1]>=-new_uv[1][1] && ab_delta+new_uv[0][0]>=new_uv[1][0]    //  odd parity. for even parity this is always true
            ;

            if (debug_output) print( "8:", new_ab[1], new_uv[1][0], ab_delta, new_uv[0][1], new_uv[1][1] );
            if (debug_output) print( "9:", new_ab[1], new_uv[1][1], ab_delta, new_uv[0][0], new_uv[1][0] );
            if (debug_output) print( "10:", passed );

            if (!passed) {
                if (debug_output) print( "11:" );

                if (enable_table) {
                    //this will make the table not change the output of the algorithm
                    //can just do a break in the actual code
                    //enable_table=false; continue;

                    break;
                } else {
                    break;
                }
            }
        }

        ab=new_ab;
        uv=new_uv;
        progress=true;
        ++iter;

        //print( "            gcd_base quotient", q );

        //print( "foo" );
        {
            //this would overflow a double; it works with modular arithmetic
            int64 a_expected=int64(uv[0][0])*int64(ab_start[0]) + int64(uv[0][1])*int64(ab_start[1]);
            int64 b_expected=int64(uv[1][0])*int64(ab_start[0]) + int64(uv[1][1])*int64(ab_start[1]);
            assert(int64(ab[0])==a_expected);
            assert(int64(ab[1])==b_expected);
        }

        if (iter>=gcd_base_max_iter) {
            break;
        }

        //todo break;
    }

    //print( "        gcd_base", iter_table+iter_slow, iter_table, iter_slow );

    #ifdef TEST_ASM
    #ifndef GENERATE_ASM_TRACKING_DATA
    if (test_asm_run) {
        if (test_asm_print) {
            print( "test asm gcd_base", test_asm_counter );
        }

        double asm_ab[]={ab_start[0], ab_start[1]};
        double asm_u[2];
        double asm_v[2];
        uint64 asm_is_lehmer[2]={(is_lehmer)? ~0ull : 0ull, (is_lehmer)? ~0ull : 0ull};
        double asm_ab_threshold[2]={ab_threshold, ab_threshold};
        uint64 asm_no_progress;
        int error_code=asm_code::asm_func_gcd_base(asm_ab, asm_u, asm_v, asm_is_lehmer, asm_ab_threshold, &asm_no_progress);

        assert(error_code==0);
        assert(asm_ab[0]==ab[0]);
        assert(asm_ab[1]==ab[1]);
        assert(asm_u[0]==uv[0][0]);
        assert(asm_u[1]==uv[1][0]);
        assert(asm_v[0]==uv[0][1]);
        assert(asm_v[1]==uv[1][1]);
        assert(asm_no_progress==int(!progress));
    }
    #endif
    #endif

    return progress;
}

bool gcd_base_continued_fraction_2(vector2& ab_double, matrix2& uv_double, bool is_lehmer, double ab_threshold_double=0) {
    int64 a_int=int64(ab_double[0]);
    int64 b_int=int64(ab_double[1]);
    int64 threshold_int=int64(ab_threshold_double);

    assert(a_int>b_int && b_int>0);

    array<int64, 2> ab={a_int, b_int};
    array<int64, 2> u={1, 0};
    array<int64, 2> v={0, 1};

    auto apply=[&](int64 q, array<int64, 2> x) -> array<int64, 2> {
        return {
            x[1],
            x[0]-q*x[1]
        };
    };

    vector<uint64> res;

    int num_iter=0;
    int num_quotients=0;

    while (ab[1]>threshold_int) {
        //print( "        gcd_base_2", ab[0] );

        int64 q=ab[0]/ab[1];
        assert(q>=0);

        array<int64, 2> new_ab=apply(q, ab);
        array<int64, 2> new_u=apply(q, u);
        array<int64, 2> new_v=apply(q, v);

        ++num_iter;

        if (is_lehmer && !check_lehmer(new_ab, new_u, new_v)) {
            break;
        }

        //print(num_iter, u[0], u[1], v[0], v[1]);

        auto ab_double_new=ab_double;
        auto uv_double_new=uv_double;

        ab_double_new[0]=double(new_ab[0]);
        ab_double_new[1]=double(new_ab[1]);
        uv_double_new[0][0]=double(new_u[0]);
        uv_double_new[0][1]=double(new_v[0]);
        uv_double_new[1][0]=double(new_u[1]);
        uv_double_new[1][1]=double(new_v[1]);

        if (
            int64(ab_double_new[0])!=new_ab[0] ||
            int64(ab_double_new[1])!=new_ab[1] ||
            int64(uv_double_new[0][0])!=new_u[0] ||
            int64(uv_double_new[0][1])!=new_v[0] ||
            int64(uv_double_new[1][0])!=new_u[1] ||
            int64(uv_double_new[1][1])!=new_v[1]
        ) {
            break;
        }

        ab=new_ab;
        u=new_u;
        v=new_v;

        ab_double=ab_double_new;
        uv_double=uv_double_new;

        //print( "            gcd_base_2 quotient", q );

        res.push_back(q);
        ++num_quotients;

        //todo break;
    }

    return num_quotients!=0;
}