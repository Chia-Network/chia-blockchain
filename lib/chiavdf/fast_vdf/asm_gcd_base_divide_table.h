namespace asm_code {


//regs: 1x scalar (RAX) + 4x scalar arguments (r==RDX)
//todo //test hit rate
void divide_table(reg_alloc regs, reg_scalar a, reg_scalar b, reg_scalar q, reg_scalar r) {
    EXPAND_MACROS_SCOPE;

    regs.get_scalar(reg_rax);

    m.bind(a, "a");
    m.bind(b, "b");
    m.bind(q, "q");
    assert(r.value==reg_rdx.value);

    static bool outputted_table=false;

    if (!outputted_table) {
#ifdef CHIAOSX
        APPEND_M(str( ".text " ));
#else
        APPEND_M(str( ".text 1" ));
#endif
        APPEND_M(str( ".balign 64" ));
        APPEND_M(str( "divide_table:" ));

        const int expected_size=1<<divide_table_index_bits;

        const int max_index=bit_sequence(0, divide_table_index_bits);
        assert(max_index>=1);

        int num=0;
        auto add=[&](uint64 v) {
            APPEND_M(str( ".quad #", to_hex(v) ));
            ++num;
        };

        add(0);
        for (int index=1;index<=max_index;++index) {
            uint128 v = (~uint128(0)) / uint128(index);
            v>>=64;
            add(v);
        }

        assert(num==expected_size);

        APPEND_M(str( ".text" ));

        outputted_table=true;
    }

    string b_shift_label=m.alloc_label();
    APPEND_M(str( "BSR `q, `b" )); // b_shift = bsr(b)
    APPEND_M(str( "SUB `q, #", to_hex(divide_table_index_bits-1) )); // b_shift = bsr(b)-(divide_table_index_bits-1)
    APPEND_M(str( "JNB #", b_shift_label ));
    APPEND_M(str( "XOR `q, `q" )); // if (b_shift<0) b_shift=0
    APPEND_M(str( "#:", b_shift_label ));

    APPEND_M(str( "SARX RAX, `b, `q" )); // b_approx = b>>b_shift
    APPEND_M(str( "MOV RAX, [divide_table+RAX*8]" )); // b_approx_inverse = divide_table[b_approx]

    APPEND_M(str( "IMUL `a" )); // q = (b_approx_inverse*a)>>64
    APPEND_M(str( "SARX `q, RDX, `q" )); // q = q>>b_shift

    string wrong_remainder_label=m.alloc_label();
    APPEND_M(str( "MOV RAX, `q" ));
    APPEND_M(str( "IMUL RAX, `b" )); // r = q*b
    APPEND_M(str( "JO #", wrong_remainder_label )); // overflow
    APPEND_M(str( "MOV RDX, `a" ));
    APPEND_M(str( "SUB RDX, RAX" )); // r = a-q*b
    APPEND_M(str( "JO #", wrong_remainder_label )); // overflow

    APPEND_M(str( "CMP RDX, `b" ));
    APPEND_M(str( "JAE #", wrong_remainder_label )); // !(r>=0 && r<b)

    string end_label=m.alloc_label();
    APPEND_M(str( "JMP #", end_label ));

    const bool asm_output_common_case_only=false;
    if (!asm_output_common_case_only) {
        APPEND_M(str( "#:", wrong_remainder_label ));

        APPEND_M(str( "MOV RDX, `a" ));
        APPEND_M(str( "SAR RDX, #", to_hex(63) )); //all 1s if negative, all 0s if nonnegative

        APPEND_M(str( "MOV RAX, `a" ));
        APPEND_M(str( "IDIV `b" )); // RAX=a/b ; RDX=r=a%b
        APPEND_M(str( "MOV `q, RAX" ));
        APPEND_M(str( "CMP RDX, 0" ));
        APPEND_M(str( "JGE #", end_label )); // r>=0
        APPEND_M(str( "ADD RDX, `b" )); // r+=b
        APPEND_M(str( "DEC `q" ));
    }

    APPEND_M(str( "#:", end_label ));
}

const array<uint64, 2> gcd_mask_approximate={1ull<<63, 1ull<<63};
const array<uint64, 2> gcd_mask_exact={0, 0};

//regs: 3x scalar, 3x vector, 2x scalar argument, 2x vector argument
//uv[0] is: u[0], v[0]. int64
//uv[1] is: u[1], v[1]
//c_gcd_mask is gcd_mask_approximate or gcd_mask_exact
//a is int64
void gcd_64_iteration(
    reg_alloc regs, reg_vector c_gcd_mask, array<reg_scalar, 2> a, array<reg_vector, 2> uv, reg_scalar ab_threshold,
    string early_exit_label
) {
    EXPAND_MACROS_SCOPE;

    m.bind(c_gcd_mask, "c_gcd_mask");
    m.bind(a, "a");
    m.bind(uv, "uv");
    m.bind(ab_threshold, "ab_threshold");

    reg_scalar q=regs.bind_scalar(m, "q");
    reg_scalar r=regs.bind_scalar(m, "r", reg_rdx);

    reg_scalar tmp_a=regs.bind_scalar(m, "tmp_a");

    //new_uv_0 = uv[1]
    reg_vector new_uv_1=regs.bind_vector(m, "new_uv_1");
    reg_vector tmp_1=regs.bind_vector(m, "tmp_1");
    reg_vector tmp_2=regs.bind_vector(m, "tmp_2");

    APPEND_M(str( "CMP `a_1, `ab_threshold" ));
    APPEND_M(str( "JBE #", early_exit_label ));

    divide_table(regs, a[0], a[1], q, r);
    APPEND_M(str( "MOV `tmp_a, `q" ));
    APPEND_M(str( "SHL `tmp_a, #", to_hex(63-gcd_num_quotient_bits) ));
    APPEND_M(str( "SAR `tmp_a, #", to_hex(63-gcd_num_quotient_bits) ));
    APPEND_M(str( "CMP `tmp_a, `q" ));
    APPEND_M(str( "JNE #", early_exit_label )); //quotient is too big

    APPEND_M(str( "MOV `a_0, `a_1" ));
    APPEND_M(str( "MOV `a_1, `r" ));

    APPEND_M(str( "VMOVQ `new_uv_1_128, `q" ));
    APPEND_M(str( "VPBROADCASTQ `new_uv_1, `new_uv_1_128" )); // new_uv_1 = q

    APPEND_M(str( "VPMULDQ `new_uv_1, `new_uv_1, `uv_1" )); // new_uv_1 = q*uv[1]
    APPEND_M(str( "VPSUBQ `new_uv_1, `uv_0, `new_uv_1" )); // new_uv_1 = uv[0] - q*uv[1]

    //overflow checking:
    //-the carry_mask bits must be all 0s or all 1s for each 64-bit entry
    //-if 1<<data_size is added, the carry_mask bits must be all 0s (negative) or 1<<data_size with the rest 0 (nonnegative)
    //-can add 1<<data_size, then check the carry_mask except the last bit
    APPEND_M(str( "VPADDQ `tmp_1, `new_uv_1, #", constant_address_uint64(1ull<<data_size, 1ull<<data_size) ));
    APPEND_M(str( "VPTEST `tmp_1, #", constant_address_uint64(carry_mask & (~(1ull<<data_size)), carry_mask & (~(1ull<<data_size))) ));
    APPEND_M(str( "JNZ #", early_exit_label ));

    {
        APPEND_M(str( "VMOVQ `tmp_1_128, `a_0" ));
        APPEND_M(str( "VPBROADCASTQ `tmp_1, `tmp_1_128" )); // tmp_1 = a[0]
        APPEND_M(str( "VPADDQ `tmp_1, `tmp_1, `uv_1" )); // tmp_1 = a[0]+new_uv[0]

        APPEND_M(str( "VMOVQ `tmp_2_128, `a_1" ));
        APPEND_M(str( "VPBROADCASTQ `tmp_2, `tmp_2_128" )); // tmp_2 = a[1]
        APPEND_M(str( "VPADDQ `tmp_2, `tmp_2, `new_uv_1" )); // tmp_2 = a[1]+new_uv[1]

        APPEND_M(str( "VPSUBQ `tmp_1, `tmp_1, `tmp_2" )); // tmp_1 = a[0]+new_uv[0]-(a[1]+new_uv[1])

        APPEND_M(str( "VPOR `tmp_1, `tmp_1, `tmp_2" )); // sign is 1 if tmp_1<0 or tmp_2<0

        //approximate: ZF set if both signs of tmp_1 are 0 (i.e tmp_1>=0 and tmp_2>=0 for both lanes)
        //exact: ZF set always
        APPEND_M(str( "VPTEST `tmp_1, `c_gcd_mask" ));

        APPEND_M(str( "JNZ #", early_exit_label )); //taken if ZF==0

        //int64 delta=new_a[0]-new_a[1];
        //if (new_a[1]<-new_uv[1]) goto early_exit_label
        //if (delta<new_uv[1]-new_uv[0]) goto early_exit_label
        //if (new_a[1]+new_uv[1]<0) goto early_exit_label
        //if (new_a[0]+new_uv[0]-(new_a[1]+new_uv[1])<0) goto early_exit_label
    }

    APPEND_M(str( "VMOVDQU `uv_0, `uv_1" )); //>= ab_threshold
    APPEND_M(str( "VMOVDQU `uv_1, `new_uv_1" ));
}


}