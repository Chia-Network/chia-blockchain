struct double_bits {
    static const int exponent_num_bits=11;
    static const int fraction_num_bits=52;

    bool sign=false;
    int exponent=0; //11 bits; starting value is -1023
    uint64 fraction=0; //52 bits

    double_bits() {}
    double_bits(double v) {
        uint64 v_bits=*(uint64*)(&v);
        sign=extract_bits(v_bits, 63, 1);
        exponent=extract_bits(v_bits, 52, 11);
        fraction=extract_bits(v_bits, 0, 52);
    }

    void set_exponent(int v) {
        exponent=v+1023;
    }

    uint64 to_uint64() const {
        uint64 v_bits=0;
        v_bits=insert_bits(v_bits, sign, 63, 1);
        v_bits=insert_bits(v_bits, exponent, 52, 11);
        v_bits=insert_bits(v_bits, fraction, 0, 52);
        return v_bits;
    }

    double to_double() const {
        uint64 v_bits=to_uint64();
        return *((double*)&v_bits);
    }

    void output(ostream& out, bool decimal=false) const {
        out << (sign? "-" : "+");

        if (exponent==0 && fraction==0) {
            out << "0";
        }

        if (exponent==0b11111111111) {
            out << ((fraction==0)? "INF" : "NAN");
        }

        if (decimal) {
            uint64 v=fraction | (1ull<<52);
            out << v << "*2^" << exponent-1023-52;
        } else {
            out << ((exponent==0)? "0b0" : "0b1");
            output_bits(out, fraction, 52);
            out << "*2^" << exponent-1023-52;
        }
    }
};

void set_rounding_mode() {
    assert(fesetround(FE_TOWARDZERO)==0); //truncated rounding
}

double d_exp2(int i) {
    double_bits d;
    d.sign=false;
    d.set_exponent(i); //bit shift and integer add (either order)
    return d.to_double();
}

//the cpu has to handle values of i that are above 2^52-1 so the built in instruction is slower than doing it this way
//can make this add a shift easily
double double_from_int(uint64 i) {
    assert(i<(1ull<<52));

    //b>=1 && b<2
    double_bits b;
    b.set_exponent(0);
    b.fraction=i;

    //res_1>=0 && res_1<1
    double res_1=b.to_double(); //1 bitwise or (for the exponent)

    double res=fma(res_1, d_exp2(52), -d_exp2(52));

    //double_bits res_b=res_1-1;
    //res_b.exponent+=52; //can't overflow; 1 uint64 add without shifts. can also use a 32/16 bit add or a double multiply
    //double res=res_b.to_double();

    assert(res==i);
    return res;
}

//can make this handle shifted doubles easily
uint64 int_from_double(double v, bool exact=true) {
    if (exact) {
        uint64 v_test=v;
        assert(v_test==v);
        assert(v_test<(1ull<<52));
    }

    double res_1=fma(v, d_exp2(-52), 1); //one fma

    double_bits b(res_1);
    uint64 res=b.fraction; //1 bitwise and (for exponent)

    if (exact) {
        assert(res==v);
    }
    return res;
}

uint64 make_uint64(uint32 high, uint32 low) {
    return uint64(high)<<32 | uint32(low);
}

uint128 make_uint128(uint64 high, uint64 low) {
    return uint128(high)<<64 | uint128(low);
}