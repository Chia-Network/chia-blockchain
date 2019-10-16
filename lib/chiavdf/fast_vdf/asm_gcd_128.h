namespace asm_code {


typedef array<reg_scalar, 2> reg_scalar_128;

//v[0] is low, v[1] is high. amount is >=0 and <128. res can't alias with v
//preserves inputs. returns low part of result
//regs: RCX, 1x scalar
void shift_right(
    reg_alloc regs, array<reg_scalar, 2> v, reg_scalar amount, reg_scalar res,
    reg_scalar tmp_rcx, reg_scalar tmp_res_2
) {
    EXPAND_MACROS_SCOPE;

    m.bind(v, "v");
    m.bind(amount, "amount");
    m.bind(res, "res");

    assert(tmp_rcx.value==reg_rcx.value);
    m.bind(tmp_res_2, "res_2");

    //res=uint64([v[1]:v[0]] >> amount) ; undefined if amount>=64
    APPEND_M(str( "MOV RCX, `amount" ));
    APPEND_M(str( "MOV `res, `v_0" ));
    APPEND_M(str( "SHRD `res, `v_1, CL" ));

    //res_2=0
    APPEND_M(str( "XOR `res_2, `res_2" ));

    //RCX=amount-64
    APPEND_M(str( "SUB RCX, 64" ));

    //res=(amount>=64)? 0 : res
    //res_2=(amount>=64)? v[1] : 0
    APPEND_M(str( "CMOVAE `res, `res_2" ));
    APPEND_M(str( "CMOVAE `res_2, `v_1" ));

    //res_2=(amount>=64)? 0 : v[1]>>(amount-64)
    APPEND_M(str( "SHR `res_2, CL" ));

    //res=(amount>=64)? res_2 : res
    APPEND_M(str( "OR `res, `res_2" ));
}

//all inputs are unsigned
void dot_product_exact(reg_alloc regs, array<reg_scalar, 2> a, array<reg_scalar, 2> b, reg_scalar out, string overflow_label) {
    EXPAND_MACROS_SCOPE;
    m.bind(a, "a");
    m.bind(b, "b");
    m.bind(out, "out");

    reg_scalar rax=regs.bind_scalar(m, "rax", reg_rax);
    reg_scalar rdx=regs.bind_scalar(m, "rdx", reg_rdx);

    //out=a0*b0
    APPEND_M(str( "MOV RAX, `a_0" ));
    APPEND_M(str( "MUL `b_0" ));
    APPEND_M(str( "JC #", overflow_label ));
    APPEND_M(str( "MOV `out, RAX" ));

    //RAX=a1*b1
    APPEND_M(str( "MOV RAX, `a_1" ));
    APPEND_M(str( "MUL `b_1" ));
    APPEND_M(str( "JC #", overflow_label ));

    //out=a0*b0+a1*b1
    APPEND_M(str( "ADD `out, RAX" ));
    APPEND_M(str( "JC #", overflow_label ));
}

//ab and ab_threshold reg_spill are 16 bytes (lsb first), 8 byte aligned. all others are 8 bytes
//parity is 1 if odd, else 0
//is_lehmer is 1 if true, else 0
//u, v, and parity are outputs
//regs: 15x scalar, 16x vector (i.e. all of the registers except RSP)
void gcd_128(
    reg_alloc regs_parent,
    array<reg_spill, 2> spill_ab_start, array<reg_spill, 2> spill_u, array<reg_spill, 2> spill_v,
    reg_spill spill_parity, reg_spill spill_is_lehmer, reg_spill spill_ab_threshold,
    string no_progress_label
) {
    EXPAND_MACROS_SCOPE_PUBLIC;

    track_asm( "gcd_128" );

    m.bind(spill_ab_start[0], "spill_ab_start_0_0");
    m.bind(spill_ab_start[0]+8, "spill_ab_start_0_1");
    m.bind(spill_ab_start[1], "spill_ab_start_1_0");
    m.bind(spill_ab_start[1]+8, "spill_ab_start_1_1");

    m.bind(spill_u, "spill_u");
    m.bind(spill_v, "spill_v");

    m.bind(spill_parity, "spill_parity");
    m.bind(spill_is_lehmer, "spill_is_lehmer");
    m.bind(spill_ab_threshold, "spill_ab_threshold_0");
    m.bind(spill_ab_threshold+8, "spill_ab_threshold_1");

    reg_vector vector_ab=regs_parent.bind_vector(m, "vector_ab");
    reg_vector vector_u=regs_parent.bind_vector(m, "vector_u");
    reg_vector vector_v=regs_parent.bind_vector(m, "vector_v");
    reg_vector vector_is_lehmer=regs_parent.bind_vector(m, "vector_is_lehmer");
    reg_vector vector_ab_threshold=regs_parent.bind_vector(m, "vector_ab_threshold");

    reg_spill spill_iter=regs_parent.bind_spill(m, "spill_iter");

    APPEND_M(str( "MOV QWORD PTR `spill_u_0, 1" ));
    APPEND_M(str( "MOV QWORD PTR `spill_u_1, 0" ));
    APPEND_M(str( "MOV QWORD PTR `spill_v_0, 0" ));
    APPEND_M(str( "MOV QWORD PTR `spill_v_1, 1" ));
    APPEND_M(str( "MOV QWORD PTR `spill_parity, 0" ));
    APPEND_M(str( "MOV QWORD PTR `spill_iter, #", to_hex(gcd_128_max_iter) ));

    string start_label=m.alloc_label();
    string loop_label=m.alloc_label();
    string exit_label=m.alloc_label();
    string exit_iter_0_label=m.alloc_label();

    string start_assign_label=m.alloc_label();
    APPEND_M(str( "JMP #", start_assign_label ));

    APPEND_M(str( "#:", loop_label ));

    track_asm( "gcd_128 iter" );

    //4x scalar
    reg_scalar new_u_0=regs_parent.bind_scalar(m, "new_u_0"); //a
    reg_scalar new_u_1=regs_parent.bind_scalar(m, "new_u_1"); //b
    reg_scalar new_v_0=regs_parent.bind_scalar(m, "new_v_0"); //ab_threshold
    reg_scalar new_v_1=regs_parent.bind_scalar(m, "new_v_1"); //base iter

    if (use_divide_table) {
        string base_exit_label=m.alloc_label();
        string base_loop_label=m.alloc_label();

        APPEND_M(str( "MOV `new_v_1, #", to_hex(gcd_base_max_iter_divide_table) ));

        APPEND_M(str( "MOVDQA `vector_u, #", constant_address_uint64(1ull, 0ull) ));
        APPEND_M(str( "MOVDQA `vector_v, #", constant_address_uint64(0ull, 1ull) ));

        APPEND_M(str( "#:", base_loop_label ));

        gcd_64_iteration(regs_parent, vector_is_lehmer, {new_u_0, new_u_1}, {vector_u, vector_v}, new_v_0, base_exit_label);

        APPEND_M(str( "DEC `new_v_1" ));
        APPEND_M(str( "JNZ #", base_loop_label ));

        APPEND_M(str( "#:", base_exit_label ));
        APPEND_M(str( "CMP `new_v_1, #", to_hex(gcd_base_max_iter_divide_table) ));
        APPEND_M(str( "JE #", track_asm( "gcd_128 base no progress", exit_label ) ));
    } else {
        gcd_base_continued_fraction(
            regs_parent, vector_ab, vector_u, vector_v, vector_is_lehmer, vector_ab_threshold,
            track_asm( "gcd_128 base no progress", exit_label )
        );
    }

    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //12x scalar (including dot product exact which is 2x scalar)
        reg_scalar m_0_0=regs.bind_scalar(m, "m_0_0");
        reg_scalar m_0_1=regs.bind_scalar(m, "m_0_1");
        reg_scalar m_1_0=regs.bind_scalar(m, "m_1_0");
        reg_scalar m_1_1=regs.bind_scalar(m, "m_1_1");
        reg_scalar tmp_0=regs.bind_scalar(m, "tmp_0");
        reg_scalar tmp_1=regs.bind_scalar(m, "tmp_1");
        reg_vector tmp_a=regs.bind_vector(m, "tmp_a");
        reg_vector tmp_b=regs.bind_vector(m, "tmp_b");
        reg_vector tmp_c=regs.bind_vector(m, "tmp_c");
        reg_vector c_double_abs_mask=regs.bind_vector(m, "double_abs_mask");

        if (!use_divide_table) {
            APPEND_M(str( "MOVAPD `double_abs_mask, #", constant_address_uint64(double_abs_mask, double_abs_mask) ));
        }

        auto abs_tmp_a=[&]() {
            if (use_divide_table) {
                //tmp_b = int64 mask = int64(v)>>63;
                APPEND_M(str( "MOVDQA `tmp_b, `tmp_a" ));
                APPEND_M(str( "PSRAD `tmp_b, 32" )); //high 32 bits = sign bit ; low 32 bits = undefined
                APPEND_M(str( "PSHUFD `tmp_b, `tmp_b, #", to_hex( 0b11110101 ) )); //move high 32 bits to low 32 bits

                //abs_v=(v + mask) ^ mask;
                APPEND_M(str( "PADDQ `tmp_a, `tmp_b" ));
                APPEND_M(str( "PXOR `tmp_a, `tmp_b" ));
            } else {
                APPEND_M(str( "PAND `tmp_a, `double_abs_mask" ));
            }
        };

        auto mov_low_tmp_a=[&](string target) {
            if (use_divide_table) {
                APPEND_M(str( "MOVQ `#, `tmp_a", target ));
            } else {
                APPEND_M(str( "CVTTSD2SI `#, `tmp_a", target ));
            }
        };

        //<m_0_0, m_1_0>=<abs(vector_u[0]), abs(vector_u[1])>
        //for the divide table, this is u[0] and v[0]
        APPEND_M(str( "MOVAPD `tmp_a, `vector_u" ));
        abs_tmp_a();
        mov_low_tmp_a( (use_divide_table)? "m_0_0" : "m_0_0" );
        APPEND_M(str( "SHUFPD `tmp_a, `tmp_a, 3" ));
        mov_low_tmp_a( (use_divide_table)? "m_0_1" : "m_1_0" );

        //<m_1_0, m_1_1>=<abs(vector_v[0]), abs(vector_v[1])>
        //for the divide table, this is u[1] and v[1]
        APPEND_M(str( "MOVAPD `tmp_a, `vector_v" ));
        abs_tmp_a();
        mov_low_tmp_a( (use_divide_table)? "m_1_0" : "m_0_1" );
        APPEND_M(str( "SHUFPD `tmp_a, `tmp_a, 3" ));
        mov_low_tmp_a( (use_divide_table)? "m_1_1" : "m_1_1" );

        APPEND_M(str( "MOV `tmp_0, `spill_u_0" ));
        APPEND_M(str( "MOV `tmp_1, `spill_u_1" ));
        dot_product_exact(regs, {m_0_0, m_0_1}, {tmp_0, tmp_1}, new_u_0, track_asm( "gcd_128 uv overflow", exit_label ));
        dot_product_exact(regs, {m_1_0, m_1_1}, {tmp_0, tmp_1}, new_u_1, track_asm( "gcd_128 uv overflow", exit_label ));

        APPEND_M(str( "MOV `tmp_0, `spill_v_0" ));
        APPEND_M(str( "MOV `tmp_1, `spill_v_1" ));
        dot_product_exact(regs, {m_0_0, m_0_1}, {tmp_0, tmp_1}, new_v_0, track_asm( "gcd_128 uv overflow", exit_label ));
        dot_product_exact(regs, {m_1_0, m_1_1}, {tmp_0, tmp_1}, new_v_1, track_asm( "gcd_128 uv overflow", exit_label ));
    }

    //9x scalar
    reg_scalar new_ab_0_0=regs_parent.bind_scalar(m, "new_ab_0_0");
    reg_scalar new_ab_0_1=regs_parent.bind_scalar(m, "new_ab_0_1");
    reg_scalar new_ab_1_0=regs_parent.bind_scalar(m, "new_ab_1_0");
    reg_scalar new_ab_1_1=regs_parent.bind_scalar(m, "new_ab_1_1");
    reg_scalar new_parity=regs_parent.bind_scalar(m, "new_parity");

    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //15x scalar
        reg_scalar rax=regs.bind_scalar(m, "rax", reg_rax);
        reg_scalar rdx=regs.bind_scalar(m, "rdx", reg_rdx);
        reg_vector tmp_a=regs.bind_vector(m, "tmp_a");

        reg_scalar ab_start_0_0=regs.bind_scalar(m, "ab_start_0_0");
        reg_scalar ab_start_0_1=regs.bind_scalar(m, "ab_start_0_1");
        reg_scalar ab_start_1_0=regs.bind_scalar(m, "ab_start_1_0");
        reg_scalar ab_start_1_1=regs.bind_scalar(m, "ab_start_1_1");

        APPEND_M(str( "MOV `ab_start_0_0, `spill_ab_start_0_0" ));
        APPEND_M(str( "MOV `ab_start_0_1, `spill_ab_start_0_1" ));
        APPEND_M(str( "MOV `ab_start_1_0, `spill_ab_start_1_0" ));
        APPEND_M(str( "MOV `ab_start_1_1, `spill_ab_start_1_1" ));

        //RAX=(uv_double[1][1]<0)? 1 : 0=uv_double_parity
        //(this also works for integers with the divide table)
        APPEND_M(str( "MOVAPD `tmp_a, `vector_v" ));
        APPEND_M(str( "SHUFPD `tmp_a, `tmp_a, 3" ));
        APPEND_M(str( "MOVQ RAX, `tmp_a" ));
        APPEND_M(str( "SHR RAX, 63" ));

        //new_parity=spill_parity^uv_double_parity
        APPEND_M(str( "MOV `new_parity, `spill_parity" ));
        APPEND_M(str( "XOR `new_parity, RAX" ));

        //[out1:out0]=[a1:a0]*u - [b1:b0]*v
        auto dot_product_subtract=[&](string a0, string a1, string b0, string b1, string u, string v, string out0, string out1) {
            //[RDX:RAX]=a0*u
            APPEND_M(str( "MOV RAX, `#", a0 ));
            APPEND_M(str( "MUL `#", u ));

            //[out1:out0]=a0*u
            APPEND_M(str( "MOV `#, RAX", out0 ));
            APPEND_M(str( "MOV `#, RDX", out1 ));

            //[RDX:RAX]=a1*u
            APPEND_M(str( "MOV RAX, `#", a1 ));
            APPEND_M(str( "MUL `#", u ));

            //[out1:out0]=a0*u + (a1*u)<<64=a*u
            APPEND_M(str( "ADD `#, RAX", out1 ));

            //[RDX:RAX]=b0*v
            APPEND_M(str( "MOV RAX, `#", b0 ));
            APPEND_M(str( "MUL `#", v ));

            //[out1:out0]=a*u - b0*v
            APPEND_M(str( "SUB `#, RAX", out0 ));
            APPEND_M(str( "SBB `#, RDX", out1 ));

            //[RDX:RAX]=b1*v
            APPEND_M(str( "MOV RAX, `#", b1 ));
            APPEND_M(str( "MUL `#", v ));

            //[out1:out0]=a*u - b0*v - (b1*v)<<64=a*u - b*v
            APPEND_M(str( "SUB `#, RAX", out1 ));
        };

        // uint64 uv_00=uv_uint64_new[0][0];
        // uint64 uv_01=uv_uint64_new[0][1];
        // int128 a_new_1=ab_start[0]; a_new_1*=uv_00;
        // int128 a_new_2=ab_start[1]; a_new_2*=uv_01;
        // if (uv_uint64_parity_new!=0) swap(a_new_1, a_new_2);
        // int128 a_new_s=a_new_1-a_new_2;
        // uint128 a_new(a_new_s);
        dot_product_subtract(
            "ab_start_0_0", "ab_start_0_1",
            "ab_start_1_0", "ab_start_1_1",
            "new_u_0", "new_v_0",
            "new_ab_0_0", "new_ab_0_1"
        );

        // uint64 uv_10=uv_uint64_new[1][0];
        // uint64 uv_11=uv_uint64_new[1][1];
        // int128 b_new_1=ab_start[1]; b_new_1*=uv_11;
        // int128 b_new_2=ab_start[0]; b_new_2*=uv_10;
        // if (uv_uint64_parity_new!=0) swap(b_new_1, b_new_2);
        // int128 b_new_s=b_new_1-b_new_2;
        // uint128 b_new(b_new_s);
        dot_product_subtract(
            "ab_start_1_0", "ab_start_1_1",
            "ab_start_0_0", "ab_start_0_1",
            "new_v_1", "new_u_1",
            "new_ab_1_0", "new_ab_1_1"
        );

        APPEND_M(str( "MOV RAX, -1" ));
        APPEND_M(str( "ADD RAX, `new_parity" )); //rax=(new_parity==1)? 0 : ~0
        APPEND_M(str( "NOT RAX" )); //rax=(new_parity==1)? ~0 : 0

        //if (new_parity!=0) { [out1:out0]=-[out1:out0]; }
        auto conditional_negate=[&](string out0, string out1) {
            //flip all bits if new_parity==1
            APPEND_M(str( "XOR `#, RAX", out0 ));
            APPEND_M(str( "XOR `#, RAX", out1 ));

            //add 1 if new_parity==1
            APPEND_M(str( "ADD `#, `new_parity", out0 ));
            APPEND_M(str( "ADC `#, 0", out1 ));
        };

        conditional_negate( "new_ab_0_0", "new_ab_0_1" );
        conditional_negate( "new_ab_1_0", "new_ab_1_1" );
    }

    //11x scalar: new_ab, new_u, new_v, new_parity, ab_threshold
    reg_scalar ab_threshold_0=regs_parent.bind_scalar(m, "ab_threshold_0");
    reg_scalar ab_threshold_1=regs_parent.bind_scalar(m, "ab_threshold_1");

    //flags for [a1:a0]-[b1:b0]:
    //CMP a0,b0 ; sets CF if b0>a0. clears CF if b0==a0
    //SBB a1,b1 ; sets CF if b>a. sets ZF if b==a. may set ZF if b<a (e.g. a1==0; b1==0; b0<a0)
    //CF set: a<b
    //CF cleared: a>=b
    //need to swap the order for <= and >

    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //15x scalar
        reg_scalar ab_delta_0=regs.bind_scalar(m, "ab_delta_0");
        reg_scalar ab_delta_1=regs.bind_scalar(m, "ab_delta_1");
        reg_scalar b_new_min=regs.bind_scalar(m, "b_new_min");
        reg_scalar is_lehmer=regs.bind_scalar(m, "is_lehmer");

        APPEND_M(str( "MOV `is_lehmer, `spill_is_lehmer" ));

        //uint128 ab_delta=new_ab[0]-new_ab[1]
        APPEND_M(str( "MOV `ab_delta_0, `new_ab_0_0" ));
        APPEND_M(str( "MOV `ab_delta_1, `new_ab_0_1" ));
        APPEND_M(str( "SUB `ab_delta_0, `new_ab_1_0" ));
        APPEND_M(str( "SBB `ab_delta_1, `new_ab_1_1" ));

        // assert(a_new>=b_new);
        // uint128 ab_delta=a_new-b_new;
        //
        // even:
        // +uv_00 -uv_01
        // -uv_10 +uv_11
        //
        // uint128 v_delta=uint128(v_1)+uint128(v_0); //even: positive. odd: negative
        // uint128 u_delta=uint128(u_1)+uint128(u_0); //even: negative. odd: positive
        //
        // uv_10 is negative if even, positive if odd
        // uv_11 is positive if even, negative if odd
        // bool passed_even=(b_new>=uint128(u_1) && ab_delta>=v_delta);
        // bool passed_odd=(b_new>=uint128(v_1) && ab_delta>=u_delta);

        //uint64 uv_delta_0=(even)? new_v_1 : new_u_1;
        //uv_delta_0 stored in ab_threshold_0
        APPEND_M(str( "CMP `new_parity, 0" ));
        APPEND_M(str( "MOV `ab_threshold_0, `new_u_1" ));
        APPEND_M(str( "CMOVE `ab_threshold_0, `new_v_1" ));

        //uint64 uv_delta_1=(even)? new_v_0 : new_u_0;
        //uv_delta_1 stored in ab_threshold_1
        APPEND_M(str( "MOV `ab_threshold_1, `new_u_0" ));
        APPEND_M(str( "CMOVE `ab_threshold_1, `new_v_0" ));

        //uint64 b_new_min=(even)? new_u_1 : new_v_1;
        APPEND_M(str( "MOV `b_new_min, `new_v_1" ));
        APPEND_M(str( "CMOVE `b_new_min, `new_u_1" ));

        //if (!is_lehmer) uv_delta=0
        APPEND_M(str( "CMP `is_lehmer, 0" ));
        APPEND_M(str( "CMOVE `ab_threshold_0, `is_lehmer" )); //if moved, is_lehmer==0
        APPEND_M(str( "CMOVE `ab_threshold_1, `is_lehmer" ));

        //if (!is_lehmer) b_new_min=0
        APPEND_M(str( "CMOVE `b_new_min, `is_lehmer" ));

        //[uv_delta_1:uv_delta_0]=uv_delta_0 + uv_delta_1 //v_delta if even, else u_delta
        APPEND_M(str( "ADD `ab_threshold_0, `ab_threshold_1" ));
        APPEND_M(str( "MOV `ab_threshold_1, 0" ));
        APPEND_M(str( "ADC `ab_threshold_1, 0" ));

        //if (ab_delta<uv_delta) goto exit
        //clobbers ab_delta
        //uv_delta (ab_threshold) not needed anymore
        APPEND_M(str( "SUB `ab_delta_0, `ab_threshold_0" ));
        APPEND_M(str( "SBB `ab_delta_1, `ab_threshold_1" ));
        APPEND_M(str( "JC #", track_asm( "gcd_128 lehmer fail ab_delta<uv_delta", exit_label ) ));

        //if (new_ab[1]<b_new_min) goto exit
        //clobbers b_new_min
        APPEND_M(str( "CMP `new_ab_1_0, `b_new_min" ));
        APPEND_M(str( "MOV `b_new_min, `new_ab_1_1" ));
        APPEND_M(str( "SBB `b_new_min, 0" ));
        APPEND_M(str( "JC #", track_asm( "gcd_128 lehmer fail new_ab[1]<b_new_min", exit_label ) ));

        //
        //

        APPEND_M(str( "MOV `ab_threshold_0, `spill_ab_threshold_0" ));
        APPEND_M(str( "MOV `ab_threshold_1, `spill_ab_threshold_1" ));

        //if (ab_threshold>=new_ab[0]) goto exit;
        APPEND_M(str( "MOV `ab_delta_0, `ab_threshold_0" ));
        APPEND_M(str( "MOV `ab_delta_1, `ab_threshold_1" ));
        APPEND_M(str( "SUB `ab_delta_0, `new_ab_0_0" ));
        APPEND_M(str( "SBB `ab_delta_1, `new_ab_0_1" ));
        APPEND_M(str( "JNC #", track_asm( "gcd_128 went too far ab_threshold>=new_ab[0]", exit_label ) ));

        //u=new_u;
        APPEND_M(str( "MOV `spill_u_0, `new_u_0" ));
        APPEND_M(str( "MOV `spill_u_1, `new_u_1" ));

        //v=new_v;
        APPEND_M(str( "MOV `spill_v_0, `new_v_0" ));
        APPEND_M(str( "MOV `spill_v_1, `new_v_1" ));

        //parity=new_parity;
        APPEND_M(str( "MOV `spill_parity, `new_parity" ));

        track_asm( "gcd_128 good iter" );

        //--iter;
        //if (iter==0) goto exit;
        APPEND_M(str( "MOV `ab_delta_0, `spill_iter" ));
        APPEND_M(str( "DEC `ab_delta_0" ));
        APPEND_M(str( "MOV `spill_iter, `ab_delta_0" ));
        APPEND_M(str( "JZ #", track_asm( "gcd_128 good exit", exit_iter_0_label ) ));
    }

    APPEND_M(str( "#:", start_label ));
    //11x scalar: new_ab, new_u, new_v, new_parity, ab_threshold

    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //4x scalar
        reg_scalar tmp_0=regs.bind_scalar(m, "tmp_0", reg_rax);
        reg_scalar tmp_1=regs.bind_scalar(m, "tmp_1", reg_rdx);
        reg_scalar tmp_2=regs.bind_scalar(m, "tmp_2");
        reg_scalar tmp_3=regs.bind_scalar(m, "tmp_3", reg_rcx);

        reg_scalar ab_0_0=new_ab_0_0;
        reg_scalar ab_0_1=new_ab_0_1;
        reg_scalar ab_1_0=new_ab_1_0;
        reg_scalar ab_1_1=new_ab_1_1;

        m.bind(new_ab_0_0, "ab_0_0");
        m.bind(new_ab_0_1, "ab_0_1");
        m.bind(new_ab_1_0, "ab_1_0");
        m.bind(new_ab_1_1, "ab_1_1");

        m.bind(ab_threshold_0, "ab_threshold_0");
        m.bind(ab_threshold_1, "ab_threshold_1");

        //tmp_3=0
        APPEND_M(str( "XOR `tmp_3, `tmp_3" ));

        //tmp=ab_1-ab_threshold
        APPEND_M(str( "MOV `tmp_0, `ab_1_0" ));
        APPEND_M(str( "MOV `tmp_1, `ab_1_1" ));
        APPEND_M(str( "SUB `tmp_0, `ab_threshold_0" ));
        APPEND_M(str( "SBB `tmp_1, `ab_threshold_1" ));

        //if (ab[1]<ab_threshold) goto exit
        APPEND_M(str( "JC #", track_asm( "gcd_128 ab[1]<ab_threshold", exit_label ) ));

        //if (ab[1]==ab_threshold) goto exit
        APPEND_M(str( "MOV `tmp_2, `tmp_0" ));
        APPEND_M(str( "OR `tmp_2, `tmp_1" )); //ZF set if tmp_0==0 and tmp_1==0
        APPEND_M(str( "JZ #", track_asm( "gcd_128 ab[1]==ab_threshold", exit_label ) ));

        //tmp_0=(ab[0][1]==0)? ab[0][0] : ab[0][1]
        //tmp_1=(ab[0][1]==0)? 0 : 64
        //tmp_0 can't be 0
        APPEND_M(str( "MOV `tmp_0, `ab_0_1" ));
        APPEND_M(str( "MOV `tmp_1, 64" ));
        APPEND_M(str( "CMP `ab_0_1, 0" ));
#ifdef CHIAOSX
        string cmoveq_label1=m.alloc_label();
        APPEND_M(str( "JNE #", cmoveq_label1));
        APPEND_M(str( "MOV `tmp_0, `ab_0_0" ));
        APPEND_M(str("#:", cmoveq_label1));

        string cmoveq_label2=m.alloc_label();
        APPEND_M(str( "JNE #", cmoveq_label2));
        APPEND_M(str( "MOV `tmp_1, `tmp_3" ));
        APPEND_M(str("#:", cmoveq_label2));
#else
        APPEND_M(str( "CMOVEQ `tmp_0, `ab_0_0" ));
        APPEND_M(str( "CMOVEQ `tmp_1, `tmp_3" ));
#endif

        //tmp_0=[first set bit index in tmp_0]
        APPEND_M(str( "BSR `tmp_0, `tmp_0" ));

        //tmp_0=[number of bits in ab[0]]=a_num_bits
        APPEND_M(str( "ADD `tmp_1, `tmp_0" ));
        APPEND_M(str( "INC `tmp_1" ));

        //if (is_lehmer) {
        //    const int min_bits=96;
        //    if (a_num_bits<min_bits) {
        //        a_num_bits=min_bits;
        //    }
        //}

        //tmp_2=spill_is_lehmer
        //tmp_0=((spill_is_lehmer)? 96 : 0)=min_bits
        APPEND_M(str( "XOR `tmp_0, `tmp_0" ));
        APPEND_M(str( "MOV `tmp_2, `spill_is_lehmer" ));
        APPEND_M(str( "CMP `tmp_2, 0" ));
        APPEND_M(str( "MOV `tmp_3, 96" ));
        APPEND_M(str( "CMOVNE `tmp_0, `tmp_3" ));
        APPEND_M(str( "XOR `tmp_3, `tmp_3" ));

        //if (a_num_bits<min_bits) a_num_bits=min_bits;
        APPEND_M(str( "CMP `tmp_1, `tmp_0" ));
        APPEND_M(str( "CMOVB `tmp_1, `tmp_0" ));

        //int shift_amount=a_num_bits-gcd_base_bits; [shift amount can't exceed 128-gcd_base_bits]
        //if (shift_amount<0) {
        //    shift_amount=0;
        //}

        //tmp_1=a_num_bits-gcd_base_bits
        APPEND_M(str( "SUB `tmp_1, #", to_hex(gcd_base_bits) ));

        //if (a_num_bits<gcd_base_bits) tmp_1=0
        //tmp_1=shift_amount
        APPEND_M(str( "CMOVB `tmp_1, `tmp_3" ));

        //vector_is_lehmer=((spill_is_lehmer | shift_amount)!=0)? <~0, ~0> : <0, 0>
        APPEND_M(str( "OR `tmp_2, `tmp_1" ));
        if (!use_divide_table) {
#ifdef CHIAOSX
            APPEND_M(str( "LEA `tmp_3, [RIP+#]", constant_address_uint64(0ull, 0ull, false) ));
            APPEND_M(str( "LEA `tmp_0, [RIP+#]", constant_address_uint64(~(0ull), ~(0ull), false) ));
#else
            APPEND_M(str( "MOV `tmp_3, OFFSET FLAT:#", constant_address_uint64(0ull, 0ull, false) ));
            APPEND_M(str( "MOV `tmp_0, OFFSET FLAT:#", constant_address_uint64(~(0ull), ~(0ull), false) ));
#endif
        } else {
#ifdef CHIAOSX
            APPEND_M(str( "LEA `tmp_3, [RIP+#]", constant_address_uint64(gcd_mask_exact[0], gcd_mask_exact[1], false) ));
            APPEND_M(str( "LEA `tmp_0, [RIP+#]", constant_address_uint64(gcd_mask_approximate[0], gcd_mask_approximate[1], false) ));
#else
            APPEND_M(str( "MOV `tmp_3, OFFSET FLAT:#", constant_address_uint64(gcd_mask_exact[0], gcd_mask_exact[1], false) ));
            APPEND_M(str( "MOV `tmp_0, OFFSET FLAT:#", constant_address_uint64(gcd_mask_approximate[0], gcd_mask_approximate[1], false) ));
#endif
        }
        APPEND_M(str( "CMOVZ `tmp_0, `tmp_3" ));
        APPEND_M(str( "MOVAPD `vector_is_lehmer, [`tmp_0]" ));

        //vector2 ab_double{
        //    double(uint64(ab[0]>>shift_amount)),
        //    double(uint64(ab[1]>>shift_amount))
        //};
        //double ab_threshold_double(uint64(ab_threshold>>shift_amount));
        //if (shift_amount!=0) {
        //    ++ab_threshold_double; [can do this with integers because the shifted ab_threshold has to fit in a double exactly]
        //    a is larger than ab_threshold
        //}

        //vector_ab=<ab_1>>shift_amount, undefined>
        //also store integer in new_u_1
        shift_right(regs, {ab_1_0, ab_1_1}, tmp_1, new_u_1, tmp_3, tmp_2);
        if (!use_divide_table) {
            APPEND_M(str( "CVTSI2SD `vector_ab, `new_u_1" ));
        }

        //vector_ab=<ab_1>>shift_amount, ab_1>>shift_amount>
        if (!use_divide_table) {
            APPEND_M(str( "SHUFPD `vector_ab, `vector_ab, 0" ));
        }

        //vector_ab=<ab_0>>shift_amount, ab_1>>shift_amount>
        //also store integer in new_u_1
        shift_right(regs, {ab_0_0, ab_0_1}, tmp_1, new_u_0, tmp_3, tmp_2);
        if (!use_divide_table) {
            APPEND_M(str( "CVTSI2SD `vector_ab, `new_u_0" ));
        }

        //tmp_0=(ab_threshold>>shift_amount)
        //also store integer in new_v_0
        shift_right(regs, {ab_threshold_0, ab_threshold_1}, tmp_1, new_v_0, tmp_3, tmp_2);

        //vector_ab_threshold=<ab_threshold_double, ab_threshold_double>
        if (!use_divide_table) {
            APPEND_M(str( "CVTSI2SD `vector_ab_threshold, `new_v_0" ));
            APPEND_M(str( "SHUFPD `vector_ab_threshold, `vector_ab_threshold, 0" ));
        }
    }

    APPEND_M(str( "JMP #", loop_label ));

    //
    //

    APPEND_M(str( "#:", exit_label ));
    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        reg_scalar tmp=regs.bind_scalar(m, "tmp");

        //if (iter==gcd_128_max_iter) goto no_progress
        APPEND_M(str( "MOV `tmp, `spill_iter" ));
        APPEND_M(str( "CMP `tmp, #", to_hex(gcd_128_max_iter) ));
        APPEND_M(str( "JE #", track_asm( "gcd_128 no progress", no_progress_label ) ));
    }
    APPEND_M(str( "JMP #", track_asm( "gcd_128 premature exit", exit_iter_0_label ) ));

    //
    //

    APPEND_M(str( "#:", start_assign_label ));

    APPEND_M(str( "MOV `new_ab_0_0, `spill_ab_start_0_0" ));
    APPEND_M(str( "MOV `new_ab_0_1, `spill_ab_start_0_1" ));
    APPEND_M(str( "MOV `new_ab_1_0, `spill_ab_start_1_0" ));
    APPEND_M(str( "MOV `new_ab_1_1, `spill_ab_start_1_1" ));
    APPEND_M(str( "MOV `ab_threshold_0, `spill_ab_threshold_0" ));
    APPEND_M(str( "MOV `ab_threshold_1, `spill_ab_threshold_1" ));

    APPEND_M(str( "JMP #", start_label ));

    //
    //

    APPEND_M(str( "#:", exit_iter_0_label ));
}


}