template<class int_type> int_type add_carry(int_type a, int_type b, int carry_in, int& carry_out) {
    assert(carry_in==0 || carry_in==1);
    uint128 res=uint128(a) + uint128(b) + uint128(carry_in);

    carry_out=int(res >> (sizeof(int_type)*8));
    assert(carry_out==0 || carry_out==1);

    return int_type(res);
}

template<class int_type> int_type sub_carry(int_type a, int_type b, int carry_in, int& carry_out) {
    assert(carry_in==0 || carry_in==1);
    uint128 res=uint128(a) - uint128(b) - uint128(carry_in);

    carry_out=int(res >> (sizeof(int_type)*8)) & 1;
    assert(carry_out==0 || carry_out==1);

    return int_type(res);
}

template<class int_type> int clz(int_type a) {
    assert(sizeof(int_type)==4 || sizeof(int_type)==8);

    if (a==0) {
        return (sizeof(int_type)==4)? 32 : 64;
    } else {
        return (sizeof(int_type)==4)? __builtin_clz(uint32(a)) : __builtin_clzll(uint64(a));
    }
}

uint64 mul_high(uint64 a, uint64 b) {
    return uint64((uint128(a)*uint128(b))>>64);
}

uint32 mul_high(uint32 a, uint32 b) {
    return uint32((uint64(a)*uint64(b))>>32);
}

constexpr int max_constexpr(int a, int b) {
    if (a>b) {
        return a;
    } else {
        return b;
    }
}

//all "=" operators truncate ; all operators that return a separate result will pad the result as necessary
template<class type, int size> struct fixed_integer {
    static const type positive_sign=0;
    static const type negative_sign=~type(0);

    type data[size+1]; //little endian; sign is first

    fixed_integer() {
        for (int x=0;x<size+1;++x) {
            data[x]=0;
        }
    }

    fixed_integer(const integer& i) : fixed_integer() {
        assert(i.num_bits()<=size*sizeof(type)*8);
        if (i<0) {
            data[0]=negative_sign;
        }

        mpz_export(data+1, nullptr, -1, sizeof(type), -1, 0, i.impl);
    }

    operator integer() const {
        integer res;
        mpz_import(res.impl, size, -1, sizeof(type), -1, 0, data+1);

        if (data[0]==negative_sign) {
            res=-res;
        }

        return res;
    }

    USED integer to_integer() const {
        return integer(*this);
    }

    //truncation
    template<int t_size> explicit fixed_integer(fixed_integer<type, t_size> t) {
        for (int x=0;x<size+1;++x) {
            data[x]=(x<t_size+1)? t.data[x] : 0;
        }
    }

    fixed_integer& operator=(const integer& v) { return *this=fixed_integer(v); }
    template<int t_size> fixed_integer& operator=(fixed_integer<type, t_size> t) { return *this=fixed_integer(t); }

    bool is_negative() const {
        return !is_zero() && data[0]==negative_sign;
    }

    void set_negative(bool t_negative) {
        data[0]=(t_negative)? negative_sign : positive_sign;
    }

    type& operator[](int pos) {
        assert(pos>=0 && pos<size);
        return data[pos+1];
    }

    const type& operator[](int pos) const {
        assert(pos>=0 && pos<size);
        return data[pos+1];
    }

    //the result is -1 if a<b, 0 if a==b, and 1 if a>b
    //there is also a fast comparison in the add function, but it has a slow path
    static int compare(
        const type* a, int size_a, type sign_a,
        const type* b, int size_b, type sign_b
    ) {
        int carry=0;
        type zero=0;

        //this calculates |a|-|b|. all of the resulted are or'ed together in zero
        for (int x=0;x<max(size_a, size_b);++x) {
            type v_a=(x<size_a)? a[x] : 0;
            type v_b=(x<size_b)? b[x] : 0;

            zero|=sub_carry(v_a, v_b, carry, carry);
        }

        //if the final carry is 1, |a|<|b|
        //if the final carry is 0 and zero==0, |a|==|b| (|a|-|b| is 0)
        //if the final carry is 0 and zero!=0, |a|>|b| (|a|-|b| is positive)

        //same sign, positive: use res
        //same sign, negative: negate res
        //opposite signs: use res if 0, otherwise 1 if sign_a is positive, -1 if sign_a is negative

        int res=0;
        if (zero!=0) res=1;
        if (carry==1) res=-1;

        //todo //get rid of branches
        //this is used to implement exactly one comparison with a binary result, so that should get rid of all of these branches
        if (sign_a==sign_b) {
            if (sign_a==negative_sign) {
                res=-res;
            }
        } else {
            if (res!=0) {
                res=(sign_a==negative_sign)? -1 : 1;
            }
        }

        return res;
    }

    template<int b_size> int compare(fixed_integer<type, b_size> b) const {
        return compare(
            data+1, size, data[0],
            b.data+1, size, b.data[0]
        );
    }

    //a, b, and res can alias with each other but only if the pointers are equal
    //the sign is not present in a/b/res
    static void add(
        const type* a, int size_a, type sign_a,
        const type* b, int size_b, type sign_b,
        type* res, int size_res, type& sign_res
    ) {
        if (size_b>size_a) {
            swap(a, b);
            swap(size_a, size_b);
            swap(sign_a, sign_b);
        }

        assert(size_res>=size_a && size_a>=size_b && size_b>=1);

        type mask=sign_a ^ sign_b; //all 1s if opposite signs, else all 0s. this isn't affected by swapping

        type swap_mask=positive_sign;

        if (size_a==size_b) {
            //carry flag
            int size_ab=size_a;
            bool a_less_than_b=a[size_ab-1]<b[size_ab-1];
            if (a[size_ab-1]==b[size_ab-1] && size_ab>=2) {
                a_less_than_b=a[size_ab-2]<b[size_ab-2];
            }

            const type* tmp=b;
            if (a_less_than_b) b=a; //CMOVB
            if (a_less_than_b) a=tmp; //CMOVB

            if (a_less_than_b) sign_a=sign_b; //CMOVB
            //sign_b isn't used anymore
            sign_b=0;

            //if (a_less_than_b) swap_mask=negative_sign; //CMOVB
        }

        int carry;
        add_carry(mask, type(1), 0, carry); //carry set if opposite signs, else cleared

        //if the ints were swapped, size_a==size_b
        for (int x=0;x<size_res;++x) {
            type v_a=(x<size_a)? a[x] : 0;
            type v_b=(x<size_b)? b[x] : 0;

            //print(x, v_a, v_b, mask, carry);

            //this calculates a-b if they had opposite signs, or a+b if they had the same sign
            res[x]=add_carry(v_a, v_b^mask, carry, carry);
        }

        //print(carry, "===");

        //the final sign is a's sign since it has a higher magnitude than b
        //however, if a subtraction was done and a and b were swapped, then this should be negated
        sign_res=sign_a^(swap_mask & mask);

        //todo //figure out how often this happens
        //a subtraction was done and there was a carry out. since the subtraction is unsigned, this means it was done in the wrong order
        //this almost never happens if the numbers are random and don't have excessive padding
        //the subtraction was done in the wrong order if the result is negative
        //the result is negative if each input were padded with 0, and the result limb was ~0 instead of 0
        //the result limb is: add_carry(0, mask, carry, carry);
        //carry in is 0: result is all 1s (bad)
        //carry in is 1: result is all 0s and carry out is 1 (good)
        //need to check for a carry out of 0 then, not 1

        if (carry==0 && mask!=0) {
            carry=0;
            for (int x=0;x<size_res;++x) {
                //print(x, ~res[x], type((x==0)? 1 : 0), carry);

                //calculate the two's complement of the result
                res[x]=add_carry(~res[x], type((x==0)? 1 : 0), carry, carry);
            }

            //print(carry, "===");

            //todo print("slow add");
            //assert(false);

            //negate the sign since the subtraction order was flipped
            sign_res=~sign_res;
        }
    }

    fixed_integer operator-() const {
        fixed_integer res=*this;
        res.data[0]=~data[0];
        return res;
    }

    void operator+=(fixed_integer b) {
        add(
            data+1, size, data[0],
            b.data+1, size, b.data[0],
            data+1, size, data[0]
        );
    }

    void operator-=(fixed_integer b) {
        add(
            data+1, size, data[0],
            b.data+1, size, negative_sign^b.data[0],
            data+1, size, data[0]
        );
    }

    template<int b_size>
    fixed_integer<type, max_constexpr(size, b_size)+1> operator+(
        fixed_integer<type, b_size> b
    ) const {
        const int output_size=max_constexpr(size, b_size)+1;

        fixed_integer<type, output_size> res;

        add(
            data+1, size, data[0],
            b.data+1, b_size, b.data[0],
            res.data+1, output_size, res.data[0]
        );

        return res;
    }

    template<int b_size>
    fixed_integer<type, max_constexpr(size, b_size)+1> operator-(
        fixed_integer<type, b_size> b
    ) const {
        const int output_size=max_constexpr(size, b_size)+1;

        fixed_integer<type, output_size> res;

        add(
            data+1, size, data[0],
            b.data+1, b_size, negative_sign^b.data[0],
            res.data+1, output_size, res.data[0]
        );

        return res;
    }

    //res=a*b+c
    //res can alias with c if the pointers are equal. can't alias with a
    //if c is null then it is all 0s
    static void mad(
        const type* a, int size_a,
        type b,
        const type* c, int size_c,
        type* res, int size_res
    ) {
        assert(size_res>=size_c && size_c>=size_a && size_a>=1);

        type previous_high=0;
        int carry_mul=0;
        int add_mul=0;

        for (int x=0;x<size_res;++x) {
            type this_a=(x>=size_a)? 0 : a[x];

            type this_low=this_a*b;
            type this_high=mul_high(this_a, b);

            type mul_res=add_carry(this_low, previous_high, carry_mul, carry_mul);

            if (x==0) {
                assert(mul_res==this_low && carry_mul==0);
            } else
            if (x==size_a) {
                assert(carry_mul==0);
            } else
            if (x>size_a) {
                assert(mul_res==0 && carry_mul==0);
            }

            type this_c=(x>=size_c || c==nullptr)? 0 : c[x];
            type add_res=add_carry(mul_res, this_c, add_mul, add_mul);

            res[x]=add_res;

            previous_high=this_high;
        }
    }

    //can't overflow
    //two of these can implement a 1024x512 mul. for 1024x1024, need to do 2x 1024x512 in separate buffers then add them
    static void mad_8x8(array<type, 8> a, array<type, 8> b, array<type, 8> c, array<type, 16>& res) {
        for (int x=0;x<8;++x) {
            res[x]=c[x];
        }
        for (int x=8;x<16;++x) {
            res[x]=0;
        }

        for (int x=0;x<8;++x) {
            //this uses a sliding window for the 8 res registers (no spilling)
            //-the lowest register is finished after the first addition in mad. the this_low,previous_high addition is skipped
            //-the highest register does not need to be loaded until the last multiplication in mad. actually this would always load 0
            // so it is not done
            //-the total number of registers is therefore 7
            //there is one register for b
            //the 8 a values are in registers but some or all may be spilled
            //need 2 registers to store the MULX result
            //need 1 register to store the previous high result (this is initially 0)
            //the this_low,previous_high add result goes into one of those registers
            //the mul_res,this_c result goes into the c register
            //total registers is 18 then; 2 are spilled
            //address registers:
            //-will just use a static 32-bit address space for most of the code. can store the stack pointer there then
            //-address registers are only used for b and res if the addresses are not static
            //-the addresses are only used at the end of the loop, so there are spare registers to load the address registers from static
            // memory. probably the addresses will be static though
            mad(&a[0], 8, b[x], &res[x], 8, &res[x], 8);
        }
    }

    void operator*=(type v) {
        mad(
            data+1, size,
            v,
            nullptr, size,
            data+1, size
        );
    }

    template<int t_size, int this_size>
    static fixed_integer<type, t_size> subset(
        fixed_integer<type, this_size> this_v, int start
    ) {
        const int end=start+t_size;

        fixed_integer<type, t_size> res;
        res.data[0]=this_v.data[0];

        for (int x=start;x<end;++x) {
            int pos=x-start;
            res[x]=(pos>=0 && pos<this_size)? this_v[x] : 0;
        }

        return res;
    }

    void left_shift_limbs(int amount) {
        for (int x=size-1;x>=0;--x) {
            int pos=x-amount;
            (*this)[x] = (pos>=0 && pos<size)? (*this)[pos] : 0;
        }
    }

    void right_shift_limbs(int amount) {
        for (int x=0;x<size;++x) {
            int pos=x+amount;
            (*this)[x] = (pos>=0 && pos<size)? (*this)[pos] : 0;
        }
    }

    void operator<<=(int amount) {
        if (amount==0) {
            //not sure if intel works with the "previous>>64" statement. might wrap around
            return;
        }

        const int bits_per_limb=sizeof(type)*8;
        assert(amount>0 && amount<bits_per_limb);

        for (int x=size-1;x>=0;--x) {
            type previous=(x==0)? 0 : (*this)[x-1];
            (*this)[x] = ((*this)[x]<<amount) | (previous>>(bits_per_limb-amount));
        }
    }

    void operator>>=(int amount) {
        if (amount==0) {
            return;
        }

        const int bits_per_limb=sizeof(type)*8;
        assert(amount>0 && amount<bits_per_limb);

        for (int x=0;x<size;++x) {
            type next=(x==size-1)? 0 : (*this)[x+1];
            (*this)[x] = ((*this)[x]>>amount) | (next<<(bits_per_limb-amount));
        }
    }

    template<int b_size>
    fixed_integer<type, size+b_size> operator*(
        fixed_integer<type, b_size> b
    ) const {
        const int output_size=size+b_size;
        fixed_integer<type, output_size> res;

        for (int x=0;x<b_size;++x) {
            auto r=subset<output_size>(*this, 0);
            r.data[0]=positive_sign;

            integer b_x_int(vector<uint64>{b[x]});

            r*=b[x];
            //auto r2=subset<output_size+2>(r, 0);
            //r2*=b[x];
            //r=r2;

            integer r_int(r);
            integer this_int(abs(*this));
            integer expected_r_int=this_int*b_x_int;
            assert(r_int==expected_r_int);

            r.left_shift_limbs(x);
            r_int<<=x*sizeof(type)*8;
            assert(r_int==integer(r));

            integer res_old_int(res);

            //todo //figure out why this doesn't work. might have something to do with the msb being set?
            res+=r; //unsigned
            /*auto res3=res;
            res3+=r;

            auto res2=res+r;
            fixed_integer<type, output_size> res4(res2);*/

            /*if (integer(res3)!=integer(res4)) {
                print( "========" );

                res3=res;
                res3+=r;

                //print( "========" );

                auto res2_copy=res+r;

                assert(false);
            }*/

            //res=res4;

            integer res_new_int(res);

            assert(res_new_int==res_old_int+r_int);
        }

        res.data[0]=data[0] ^ b.data[0];
        return res;
    }

    fixed_integer<type, size+1> operator<<(int num) const {
        auto res=subset<size+1>(*this, 0);
        res<<=num;
        return res;
    }

    //this rounds to 0 so it is different from division unless the input is divisible by 2^num
    fixed_integer<type, size> operator>>(int num) const {
        auto res=subset<size>(*this, 0);
        res>>=num;
        return res;
    }

    bool is_zero() const {
        for (int x=0;x<size;++x) {
            if (data[x+1]!=0) {
                return false;
            }
        }
        return true;
    }

    template<int b_size>
    bool operator>=(fixed_integer<type, b_size> b) const {
        return compare(b)>=0;
    }

    template<int b_size>
    bool operator==(fixed_integer<type, b_size> b) const {
        return compare(b)==0;
    }

    template<int b_size>
    bool operator<(fixed_integer<type, b_size> b) const {
        return compare(b)<0;
    }

    template<int b_size>
    bool operator<=(fixed_integer<type, b_size> b) const {
        return compare(b)<=0;
    }

    template<int b_size>
    bool operator>(fixed_integer<type, b_size> b) const {
        return compare(b)>0;
    }

    template<int b_size>
    bool operator!=(fixed_integer<type, b_size> b) const {
        return compare(b)!=0;
    }

    //"0" has 1 bit
    int num_bits() const {
        type v=0;
        int num_full=0;

        for (int x=size-1;x>=0;--x) {
            if (v==0) {
                v=(*this)[x];
                num_full=x;
            }
        }

        int v_bits;
        if (v==0) {
            v_bits=1;
            assert(num_full==0);
        } else
        if (sizeof(v)==8) {
            v_bits=64-__builtin_clzll(v);
        } else{
            assert(sizeof(v)==4);
            v_bits=32-__builtin_clz(v);
        }

        return num_full*sizeof(type)*8 + v_bits;
    }

    type window(int start_bit) const {
        int bits_per_limb_log2=(sizeof(type)==8)? 6 : 5;
        int bits_per_limb=1<<bits_per_limb_log2;

        int start_limb=start_bit>>bits_per_limb_log2;
        int start_offset=start_bit&(bits_per_limb-1);

        auto get_limb=[&](int pos) -> type {
            assert(pos>=0);
            return (pos>=size)? type(0) : (*this)[pos];
        };

        type start=get_limb(start_limb)>>(start_offset);

        //the shift is undefined for start_offset==0
        type end=get_limb(start_limb+1)<<(bits_per_limb-start_offset);

        return (start_offset==0)? start : (start | end);
    }
};

template<class type, int size> fixed_integer<type, size> abs(fixed_integer<type, size> v) {
    v.set_negative(false);
    return v;
}

template<int size> fixed_integer<uint64, (size+1)/2> to_uint64(fixed_integer<uint32, size> v) {
    fixed_integer<uint64, (size+1)/2> res;
    res.set_negative(v.is_negative()); //sign extend data[0]. can just make data[0] 64 bits if i actually have to do this

    //this just copies the bytes over
    for (int x=0;x<size;x+=2) {
        uint32 low=v[x];
        uint32 high=(x==size-1)? 0 : v[x+1];
        res[x>>1]=uint64(high)<<32 | uint64(low);
    }

    return res;
}

template<int size> fixed_integer<uint32, size*2> to_uint32(fixed_integer<uint64, size> v) {
    fixed_integer<uint32, size*2> res;
    res.set_negative(v.is_negative()); //lower 32 bits of data[0]

    for (int x=0;x<size;++x) {
        res[2*x]=uint32(v[x]);
        res[2*x+1]=uint32(v[x]>>32);
    }

    return res;
}