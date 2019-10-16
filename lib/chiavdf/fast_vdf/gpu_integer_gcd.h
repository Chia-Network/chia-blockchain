template<int size> struct fixed_gcd_res {
    fixed_integer<uint64, size> gcd; //unsigned; final value of a
    fixed_integer<uint64, size> gcd_2; //unsigned; final value of b. this is 0 for a normal gcd
    fixed_integer<uint64, size> s; //signed
    fixed_integer<uint64, size> t; //signed
    fixed_integer<uint64, size> s_2; //signed
    fixed_integer<uint64, size> t_2; //signed
};

//threshold is 0 to calculate the normal gcd
//this calculates either s (u) or t (v)
template<int size> fixed_gcd_res<size> gcd(
    fixed_integer<uint64, size> a_signed, fixed_integer<uint64, size> b_signed, fixed_integer<uint64, size> threshold,
    bool calculate_u
) {
    assert(!threshold.is_negative());

    bool a_negative=a_signed.is_negative();
    bool b_negative=b_signed.is_negative();
    assert(!b_negative);

    array<fixed_integer<uint64, size>, 2> ab; //unsigned
    ab[0]=a_signed;
    ab[0].set_negative(false);

    ab[1]=b_signed;
    ab[1].set_negative(false);

    array<fixed_integer<uint64, size>, 2> uv; //unsigned

    int parity;

    if (ab[0]<ab[1]) {
        //swap components of u and v
        //also negate the parity

        auto a_copy=ab[0];
        ab[0]=ab[1];
        ab[1]=a_copy;

        if (calculate_u) {
            uv[0]=integer(0u);
            uv[1]=integer(1u);
        } else {
            uv[0]=integer(1u);
            uv[1]=integer(0u);
        }

        parity=-1;
    }  else {
        if (calculate_u) {
            uv[0]=integer(1u);
            uv[1]=integer(0u);
        } else {
            uv[0]=integer(0u);
            uv[1]=integer(1u);
        }

        parity=1;
    }

    gcd_unsigned(ab, uv, parity, threshold);

    // sa+bt=g ; all nonnegative
    // (-s)(-a)+bt=g
    // sa+(-b)(-t)=g
    // (-s)(-a)+(-b)(-t)=g
    // sign of each cofactor is the sign of the input

    fixed_gcd_res<size> res;
    res.gcd=ab[0];
    res.gcd_2=ab[1];

    //if a was negative, negate the parity
    //if the parity is -1, negate the parity and negate the result u/v values. the parity is now 1
    //for u, u0 is positive and u1 is negative
    //for v, v0 is negative and u1 is positive
    if (calculate_u) {
        res.s=uv[0];
        res.s.set_negative(a_negative != (parity==-1));

        res.s_2=uv[1];
        res.s_2.set_negative(a_negative != (parity==1));
    } else {
        res.t=uv[0];
        res.t.set_negative(a_negative != (parity==1));

        res.t_2=uv[1];
        res.t_2.set_negative(a_negative != (parity==-1));
    }

    if (threshold.is_zero()) {
        auto expected_gcd_res=gcd(integer(a_signed), integer(b_signed));
        assert(expected_gcd_res.gcd==integer(res.gcd));

        if (calculate_u) {
            assert(expected_gcd_res.s==integer(res.s));
        } else {
            assert(expected_gcd_res.t==integer(res.t));
        }
    } else {
        //integer a_copy(a_signed);
        //integer b_copy(a_signed);
        //integer u_copy;
        //integer v_copy;
        //xgcd_partial(u_copy, v_copy, a_copy, b_copy, integer(threshold));

        //assert(a_copy==res.gcd);
        //assert(b_copy==res.gcd_2);

        //if (calculate_t) {
            //assert(u_copy==-res.t);
            //assert(v_copy==-res.t_2);
        //}
    }

    return res;
}