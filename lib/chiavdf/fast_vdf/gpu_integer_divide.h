//unsigned
template<class type, int size> void normalize_divisor(fixed_integer<type, size>& b, int& shift_limbs, int& shift_bits) {
    shift_limbs=0;
    //todo //make this a variable shift (could have done it on the gpu through shared memory; oh well)
    for (int x=0;x<size;++x) {
        if (b[size-1]==0) {
            ++shift_limbs;
            b.left_shift_limbs(1);
        } else {
            break;
        }
    }

    shift_bits=clz(b[size-1]);
    b<<=shift_bits;
}

//result is >= the actual reciprocal; max result is 2^63
uint64 calculate_reciprocal(uint32 high, uint32 low) {
    assert((high>>31)!=0); //should be normalized

    //bit 63 set
    uint64 both_source=uint64(low) | (uint64(high)<<32);

    uint64 both=both_source;

    //bit 52 set
    both>>=2*32-53;

    //clears bit 52
    both&=~(1ull<<52);

    uint64 res;

    if (both<=1) {
        res=1ull<<63;
    } else {
        --both;

        uint64 bits=both;
        bits|=1023ull<<52;

        double bits_double=*(double*)&bits;
        bits_double=1.0/(bits_double);
        bits=*(uint64*)&bits_double;

        bits&=(1ull<<52)-1;

        res=bits;
        ++res;

        res|=1ull<<52;
        res<<=(62-52);
    }

    return res;
}

//result is >= the actual quotient
uint32 calculate_quotient(uint32 high, uint32 low, uint64 reciprocal, uint32 b) {
    uint64 both=uint64(low) | (uint64(high)<<32);

    uint64 product_high=(uint128(both)*uint128(reciprocal))>>64;
    ++product_high;

    uint64 res=product_high>>(32-2);

    if (res>=1ull<<32) {
        res=(1ull<<32)-1;
    }

    return uint32(res);
}

fixed_integer<uint64, 2> calculate_reciprocal(uint64 high, uint64 low);
uint64 calculate_quotient(uint64 high, uint64 low, fixed_integer<uint64, 2> reciprocal, uint64 b);

//should pad a by 1 limb then left shift it by num_bits
//all integers are unsigned
template<class type, int size_a, int size_b>
void divide_integers_impl(
    fixed_integer<type, size_a> a, fixed_integer<type, size_b> b, int b_shift_limbs,
    fixed_integer<type, size_a-1>& q, fixed_integer<type, size_b>& r
) {
    const int max_quotient_size=size_a-1;
    fixed_integer<type, max_quotient_size> res;

    auto reciprocal=calculate_reciprocal(b[size_b-1], (size_b>=2)? b[size_b-2] : 0);

    fixed_integer<type, size_a> b_shifted;
    b_shifted=b;
    b_shifted.left_shift_limbs(size_a-size_b-1); //it is already left shifted by b_shift_limbs

    int quotient_size=size_a-(size_b-b_shift_limbs);

    for (int x=0;x<max_quotient_size;++x) {
        //this is more efficient than having an if statement without a break because of the compiler
        if (x>=quotient_size) {
            break;
        }
        {
            type qj=calculate_quotient(a[size_a-1-x], a[size_a-2-x], reciprocal, b[size_b-1]);

            //this is slower than using the doubles even though the doubles waste half the registers
            //ptxas generates horrible code which isn't scheduled properly
            //uint64 qj_64=((uint64(a[size_a-1-x])<<32) | uint64(a[size_a-2-x])) / uint64(b[size_b-1]);
            //uint32 qj=uint32(min( qj_64, uint64(~uint32(0)) ));

            auto a_start=a;
            type qj_start=qj;

            auto b_shifted_qj=b_shifted;
            b_shifted_qj*=qj;
            a-=b_shifted_qj;

            while (a.is_negative()) {
                //todo print( "slow division" );

                --qj;
                a+=b_shifted;
            }

            b_shifted.right_shift_limbs(1);

            res[max_quotient_size-1-x]=qj;
        }
    }

    //todo //get rid of this; use variable shifts
    for (int x=0;x<max_quotient_size;++x) {
        if (quotient_size>=max_quotient_size) {
            break;
        }

        res.right_shift_limbs(1);
        ++quotient_size;
    }

    q=res;
    r=a;

    //todo print( "====" );
}

//these are signed
//this has a bug if size_a<size_b and the quotient is nonzero. remainder is wrong. dont care
template<class type, int size_a, int size_b>
void divide_integers(
    fixed_integer<type, size_a> a, fixed_integer<type, size_b> b,
    fixed_integer<type, size_a>& q, fixed_integer<type, size_b>& r
) {
    int shift_limbs;
    int shift_bits;

    auto b_normalized=b;
    b_normalized.set_negative(false);
    normalize_divisor(b_normalized, shift_limbs, shift_bits);

    fixed_integer<type, size_a+1> a_shifted;
    a_shifted=a;
    a_shifted.set_negative(false);

    a_shifted<<=shift_bits;

    fixed_integer<type, size_a> q_unsigned;
    divide_integers_impl(a_shifted, b_normalized, shift_limbs, q_unsigned, r);

    r>>=shift_bits;

    if (a.is_negative()!=b.is_negative()) {
        if (r==fixed_integer<type, size_b>(integer(0u))) {
            q=q_unsigned;
            q=-q;
        } else {
            q=q_unsigned+fixed_integer<type, size_a>(integer(1u));
            q=-q; //q'=-q-1

            auto abs_b=b;
            abs_b.set_negative(false);
            r=abs_b-r;
        }
    } else {
        q=q_unsigned;
    }

    // qb+r=a ; b>0: 0<=r<b ; b<0: b<r<=0
    // b<0:
    // -qb-r=-a
    // R=-r ; 0<=R<-b
    // q(-b)+R=-a
    r.set_negative(b.is_negative());

    {
        integer a_int(a);
        integer b_int(b);

        integer q_expected=a_int/b_int;
        integer r_expected=a_int.fdiv_r(b_int);
        integer r_expected_2=a_int%b_int;

        integer q_actual=q;
        integer r_actual=r;
        assert(q_expected==q_actual);
        assert(r_expected==r_actual);

        //todo
        //r=r_expected;
    }
}

template<class type, int size_a, int size_b>
fixed_integer<type, size_a> operator/(
    fixed_integer<type, size_a> a, fixed_integer<type, size_b> b
) {
    fixed_integer<type, size_a> q;
    fixed_integer<type, size_b> r;
    divide_integers(a, b, q, r);
    return q;
}

template<class type, int size_a, int size_b>
fixed_integer<type, size_b> operator%(
    fixed_integer<type, size_a> a, fixed_integer<type, size_b> b
) {
    fixed_integer<type, size_a> q;
    fixed_integer<type, size_b> r;

    b.set_negative(false);
    divide_integers(a, b, q, r);
    return r;
}

fixed_integer<uint64, 2> calculate_reciprocal(uint64 high, uint64 low) {
    assert((high>>63)!=0); //normalized

    fixed_integer<uint32, 6> a;

    a[5]=1u<<31; // a=2^191 ; normalized

    fixed_integer<uint32, 3> b;
    b[0]=uint32(low>>32);
    b[1]=uint32(high);
    b[2]=uint32(high>>32);
    b-=fixed_integer<uint32, 3>(integer(1));

    return fixed_integer<uint64, 2>(to_uint64(a/b + fixed_integer<uint32, 6>(integer(1)))<<31);
}

//result is >= the actual reciprocal. it is approximately 2^127/((HIGH | LOW)/2^127)
//the max value is 2^127 + 2^31
/*fixed_integer<uint64, 2> calculate_reciprocal(uint64 high, uint64 low) {
    assert((high>>63)!=0); //normalized

    //fixed_integer<uint32, 6> a
    //a[5]=1u<<31; // a=2^191 ; normalized

    uint128 b=(uint128(high)<<32) | uint128(low>>32);

    uint64 reciprocal=calculate_reciprocal(uint32(high>>32), uint32(high));

    fixed_integer<type, size_a> b_shifted;
    b_shifted=b;
    b_shifted.left_shift_limbs(2);

    int quotient_size=3;

    for (int x=0;x<3;++x) {
        uint64 qj=calculate_quotient(a[5-x], a[4-x], reciprocal, b[1]);

        auto b_shifted_qj=b_shifted;
        b_shifted_qj*=qj;
        a-=b_shifted_qj;

        while (a.is_negative()) {
            //todo print( "slow division" );

            --qj;
            a+=b_shifted;
        }

        b_shifted.right_shift_limbs(1);

        res[5-1-x]=qj;
    }

    todo //get rid of this; use variable shifts
    for (int x=0;x<max_quotient_size;++x) {
        if (quotient_size>=max_quotient_size) {
            break;
        }

        res.right_shift_limbs(1);
        ++quotient_size;
    }

    q=res;
    r=a;

    //todo print( "====" );

    return fixed_integer<uint64, 2>(to_uint64(a/b + fixed_integer<uint32, 6>(integer(1)))<<31);
} */

//result is >= the actual quotient
uint64 calculate_quotient(uint64 high, uint64 low, fixed_integer<uint64, 2> reciprocal, uint64 b) {
    fixed_integer<uint64, 2> both;
    both[0]=low;
    both[1]=high;

    //approximately (high | low) * (2^127/((HIGH | LOW)/2^127))
    // = (2^(127*2)*(high | low)/((HIGH | LOW)/2^64)/2^64
    // = (2^(127*2-64) * (high | low)/((HIGH | LOW)/2^64)
    // = (2^190 * (high | low)/((HIGH | LOW)/2^64)
    //need to right shift by 190 then, which is 2*64+62
    //
    //max value of the product is (2^128-1)*(2^127 + 2^31) = 2^255 + 2^159 - 2^127 - 2^31

    integer both_int(both);
    integer reciprocal_int(reciprocal);
    integer product_both_int(both_int*reciprocal_int);

    fixed_integer<uint64, 4> product_both(both*reciprocal);
    assert(integer(product_both)==product_both_int);

    product_both.right_shift_limbs(2);

    product_both_int>>=128;
    assert(integer(product_both)==product_both_int);

    fixed_integer<uint64, 2> product_high(product_both);

    //this can't overflow because the max value of the product has e.g. bit 254 cleared
    product_high+=fixed_integer<uint64, 2>(integer(1));

    product_high>>=64-2;

    uint64 res;
    if (product_high[1]!=0) {
        res=~uint64(0);
    } else {
        res=product_high[0];
    }

    //uint128 qj_128=((uint128(high)<<64) | uint128(low)) / uint128(b);
    //uint64 qj=uint64(min( qj_128, uint128(~uint64(0)) ));

    //assert(res>=qj); this is wrong. res can be qj-1 sometimes
    //assert(res<=qj+1); //optional

    return res;
}

/*template<int size_a, int size_b>
fixed_integer<uint64, size_a> operator/(
    fixed_integer<uint64, size_a> a, fixed_integer<uint64, size_b> b
) {
    auto a_32=to_uint32(a);
    auto b_32=to_uint32(b);
    fixed_integer<uint32, size_a*2> q_32;
    fixed_integer<uint32, size_b*2> r_32;

    divide_integers(a_32, b_32, q_32, r_32);
    return to_uint64(q_32);
}

template<int size_a, int size_b>
fixed_integer<uint64, size_b> operator%(
    fixed_integer<uint64, size_a> a, fixed_integer<uint64, size_b> b
) {
    auto a_32=to_uint32(a);
    auto b_32=to_uint32(b);
    fixed_integer<uint32, size_a*2> q_32;
    fixed_integer<uint32, size_b*2> r_32;

    b_32.set_negative(false);
    divide_integers(a_32, b_32, q_32, r_32);
    return to_uint64(r_32);
}**/