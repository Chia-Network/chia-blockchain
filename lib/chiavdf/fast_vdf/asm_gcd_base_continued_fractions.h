namespace asm_code {


const double range_check_range=double((1ull<<53)-1);
const uint64 double_sign_mask=(1ull<<63);
const uint64 double_abs_mask=~double_sign_mask;

//clobbers v
void range_check(
    reg_vector v, reg_vector range, reg_vector c_double_abs_mask,
    string out_of_range_label
) {
    EXPAND_MACROS_SCOPE;

    m.bind(range, "range");
    m.bind(c_double_abs_mask, "double_abs_mask");

    m.bind(v, "tmp");

    //tmp=abs(tmp)
    APPEND_M(str( "ANDPD `tmp, `double_abs_mask" ));

    //tmp all 0s if (abs(tmp0)<=range && abs(tmp1)<=range)
    APPEND_M(str( "CMPNLEPD `tmp, `range" ));

    //todo //can replace this with POR into an accumulator then use a single PTEST
    //todo //can compile the code twice for is_leher being true and false, then branch to the appropriate version
    //todo //can probably get rid of the uv range checks if is_lehmer is true
    //todo //can get rid of the ab range checks if the table is used and each table uv value has a magnitude less than a certain amount
    APPEND_M(str( "PTEST `tmp, `tmp" ));
    APPEND_M(str( "JNZ #", out_of_range_label ));
}

//clobbers b
//this calculates the dot product of each lane separately and puts the result in that lane
void dot_product_exact(
    array<reg_vector, 2> a, array<reg_vector, 2> b, reg_vector v, reg_vector range, reg_vector c_double_abs_mask,
    string out_of_range_label, bool result_always_in_range=false
) {
    EXPAND_MACROS_SCOPE;

    m.bind(a, "a");
    m.bind(b, "b");
    m.bind(v, "v");

    APPEND_M(str( "MULPD `b_0, `a_0" ));
    APPEND_M(str( "MOVAPD `v, `b_0" ));
    //todo //for avx, can get rid of a lot of the MOVs by using the 3-operand versions of the instructions
    range_check(b[0], range, c_double_abs_mask, out_of_range_label);

    if (enable_all_instructions) {
        APPEND_M(str( "VFMADD231PD `v, `b_1, `a_1" ));
    } else {
        APPEND_M(str( "MULPD `b_1, `a_1" ));
        APPEND_M(str( "ADDPD `v, `b_1" ));
        range_check(b[1], range, c_double_abs_mask, out_of_range_label);
    }

    if (!result_always_in_range) {
        APPEND_M(str( "MOVAPD `b_0, `v" ));
        range_check(b[0], range, c_double_abs_mask, out_of_range_label);
    }
}

//ab_threshold is the same for both lanes
//is_lehmer is all 1s if lehmer, else all 0s
//will assign u and v
void gcd_base_continued_fraction(
    reg_alloc regs,
    reg_vector ab, reg_vector u, reg_vector v, reg_vector is_lehmer, reg_vector ab_threshold,
    string no_progress_label
) {
    EXPAND_MACROS_SCOPE;

    track_asm( "gcd_base" );

    static double_table<continued_fraction> c_table=generate_table(gcd_table_num_exponent_bits, gcd_table_num_fraction_bits);
    static bool outputted_table=false;

    if (!outputted_table) {
#ifdef CHIAOSX
        APPEND_M(str( ".text " ));
#else
        APPEND_M(str( ".text 1" ));
#endif
        APPEND_M(str( ".balign 64" ));
        APPEND_M(str( "gcd_base_table:" ));

        string table_data;
        auto out_double=[&](double v) {
            if (!table_data.empty()) {
                table_data += ", ";
            }

            table_data+=to_hex(*(uint64*)&v);
        };

        //each entry is 32 bytes, 32-aligned
        for (continued_fraction c : c_table.data) {
            matrix2 mat=c.get_matrix();
            out_double(mat[0][0]); //lane 0
            out_double(mat[1][0]); //lane 1
            out_double(mat[0][1]); //lane 0
            out_double(mat[1][1]); //lane 1

            APPEND_M(str( ".quad #", table_data ));
            table_data.clear();
        }

        APPEND_M(str( ".text" ));

        outputted_table=true;
    }

    //5x vector
    m.bind(ab, "ab");
    m.bind(u, "u");
    m.bind(v, "v");
    m.bind(is_lehmer, "is_lehmer");
    m.bind(ab_threshold, "ab_threshold");

    //11x vector
    reg_vector m_0=regs.bind_vector(m, "m_0");
    reg_vector m_1=regs.bind_vector(m, "m_1");
    reg_vector new_ab=regs.bind_vector(m, "new_ab");
    reg_vector new_ab_1=regs.bind_vector(m, "new_ab_1");
    reg_vector tmp=regs.bind_vector(m, "tmp");
    reg_vector tmp2=regs.bind_vector(m, "tmp2");
    reg_vector new_u=regs.bind_vector(m, "new_u");
    reg_vector new_v=regs.bind_vector(m, "new_v");
    reg_vector q=regs.bind_vector(m, "q");
    reg_vector c_range_check_range=regs.bind_vector(m, "range_check_range");
    reg_vector c_double_abs_mask=regs.bind_vector(m, "double_abs_mask");

    reg_scalar q_scalar=regs.bind_scalar(m, "q_scalar");
    reg_scalar q_scalar_2=regs.bind_scalar(m, "q_scalar_2");
    reg_scalar q_scalar_3=regs.bind_scalar(m, "q_scalar_3");
    reg_scalar loop_counter=regs.bind_scalar(m, "loop_counter");

    reg_scalar c_table_delta_minus_1=regs.bind_scalar(m, "c_table_delta_minus_1");
    APPEND_M(str( "MOV `c_table_delta_minus_1, #", constant_address_uint64(c_table.delta-1, c_table.delta-1) ));

    string exit_label=m.alloc_label();
    string loop_label=m.alloc_label();

    APPEND_M(str( "MOV `loop_counter, #", to_hex(gcd_base_max_iter) ));

    APPEND_M(str( "MOVAPD `u, #", constant_address_double(1.0, 0.0) ));
    APPEND_M(str( "MOVAPD `v, #", constant_address_double(0.0, 1.0) ));
    APPEND_M(str( "MOVAPD `range_check_range, #", constant_address_double(range_check_range, range_check_range) ));
    APPEND_M(str( "MOVAPD `double_abs_mask, #", constant_address_uint64(double_abs_mask, double_abs_mask) ));

    // q[0]=ab[0]/ab[1]
    APPEND_M(str( "MOVAPD `tmp, `ab" ));
    APPEND_M(str( "SHUFPD `tmp, `tmp, 3" )); // tmp=<ab[1], ab[1]>
    APPEND_M(str( "MOVAPD `q, `ab" ));
    APPEND_M(str( "DIVSD `q, `tmp" ));

    {
        APPEND_M(str( "#:", loop_label ));

        track_asm( "gcd_base iter" );

        string no_table_label=m.alloc_label();

        APPEND_M( "#gcd_base loop start" );

        //q_scalar=q_scalar_2=to_uint64(ab[0]/ab[1])
        APPEND_M(str( "MOVQ `q_scalar, `q" ));
        APPEND_M(str( "MOV `q_scalar_2, `q_scalar" ));
        APPEND_M(str( "MOV `q_scalar_3, `q_scalar" ));

        //q_scalar=(to_uint64(ab_0/ab_1)>>c_table.right_shift_amount)<<5
        assert(c_table.right_shift_amount>5);
        APPEND_M(str( "SHR `q_scalar, #", to_hex(c_table.right_shift_amount-5) ));
        APPEND_M(str( "AND `q_scalar, -32" ));

        // q_scalar-=c_table.range_start_shifted<<5
        // if (q_scalar<0 || q_scalar>=(c_table.range_end_shifted-c_table.range_start_shifted)<<5) goto no_table_label
        //this bypasses the "ab[1]<=ab_threshold" check so we need to do it again in no_table_label
        APPEND_M(str( "SUB `q_scalar, #", to_hex(c_table.range_start_shifted<<5) ));
        APPEND_M(str( "JB #", track_asm( "gcd_base below table start", no_table_label ) ));
        APPEND_M(str( "CMP `q_scalar, #", to_hex((c_table.range_end_shifted-c_table.range_start_shifted)<<5) ));
        APPEND_M(str( "JAE #", track_asm( "gcd_base after table end", no_table_label ) ));

        //m_0: column 0
        //m_1: column 1
#ifdef CHIAOSX
        APPEND_M(str( "LEA RSI,[RIP+gcd_base_table]"));
        APPEND_M(str( "MOVAPD `m_0, [`q_scalar+RSI]" ));
        APPEND_M(str( "MOVAPD `m_1, [16+`q_scalar+RSI]" ));
#else
        APPEND_M(str( "MOVAPD `m_0, [gcd_base_table+`q_scalar]" ));
        APPEND_M(str( "MOVAPD `m_1, [gcd_base_table+16+`q_scalar]" ));
#endif

        //if (ab[1]<=ab_threshold) goto exit_label
        //this also tests ab[0], which is >= ab[1] so this does nothing
        APPEND_M(str( "MOVAPD `tmp, `ab" ));
        APPEND_M(str( "CMPLEPD `tmp, `ab_threshold" )); // tmp all 0s if (ab[0]>ab_threshold[0] && ab[1]>ab_threshold[1])
        APPEND_M(str( "PTEST `tmp, `tmp" ));
        APPEND_M(str( "JNZ #", track_asm( "gcd_base ab[1]<=ab_threshold", exit_label ) ));

        //if ( (q_scalar_2&(c_table.delta-1))==0 || (q_scalar_2&(c_table.delta-1))==c_table.delta-1 ) goto no_table_label
        APPEND_M(str( "AND `q_scalar_2, `c_table_delta_minus_1" ));
        APPEND_M(str( "JZ #", track_asm( "gcd_base on slot boundary", no_table_label ) ));
        APPEND_M(str( "CMP `q_scalar_2, `c_table_delta_minus_1" ));
        APPEND_M(str( "JE #", track_asm( "gcd_base on slot boundary", no_table_label ) ));

        //assigns: new_ab, new_ab_1, q, new_u, new_v
        //reads: m, ab, u, v
        //clobbers: tmp
        auto calculate_using_m=[&](string fail_label) {
            APPEND_M(str( "MOVAPD `tmp, `ab" ));
            APPEND_M(str( "SHUFPD `tmp, `tmp, 0" ));

            APPEND_M(str( "MOVAPD `tmp2, `ab" ));
            APPEND_M(str( "SHUFPD `tmp2, `tmp2, 3" ));

            dot_product_exact(
                {m_0, m_1}, {tmp, tmp2}, new_ab, c_range_check_range, c_double_abs_mask,
                track_asm( "gcd_base ab range check failed", fail_label),
                true
            );

            APPEND_M(str( "MOVAPD `new_ab_1, `new_ab" ));
            APPEND_M(str( "SHUFPD `new_ab_1, `new_ab_1, 3" )); // new_ab_1=<new_ab[1], new_ab[1]>

            // q[0]=new_ab[0]/new_ab[1]
            // this clobbers q if the table is not used
            APPEND_M(str( "MOVAPD `q, `new_ab" ));
            APPEND_M(str( "DIVSD `q, `new_ab_1" ));

            APPEND_M(str( "MOVAPD `tmp, `u" ));
            APPEND_M(str( "SHUFPD `tmp, `tmp, 0" ));

            APPEND_M(str( "MOVAPD `tmp2, `u" ));
            APPEND_M(str( "SHUFPD `tmp2, `tmp2, 3" ));

            dot_product_exact(
                {m_0, m_1}, {tmp, tmp2}, new_u, c_range_check_range, c_double_abs_mask,
                track_asm( "gcd_base uv range check failed", fail_label)
            );

            //todo //for avx, can replace some shuffles with broadcasts. can make a macro that expands to the proper instructions
            APPEND_M(str( "MOVAPD `tmp, `v" ));
            APPEND_M(str( "SHUFPD `tmp, `tmp, 0" ));

            APPEND_M(str( "MOVAPD `tmp2, `v" ));
            APPEND_M(str( "SHUFPD `tmp2, `tmp2, 3" ));

            dot_product_exact(
                {m_0, m_1}, {tmp, tmp2}, new_v, c_range_check_range, c_double_abs_mask,
                track_asm( "gcd_base uv range check failed", fail_label)
            );
        };
        calculate_using_m(no_table_label);

        //if (new_ab[0]<=ab_threshold) goto no_table_label
        APPEND_M(str( "UCOMISD `new_ab, `ab_threshold" ));
        APPEND_M(str( "JBE #", track_asm( "gcd_base new_ab[0]<=ab_threshold for table", no_table_label ) ));

        string lehmer_label=m.alloc_label();
        APPEND_M(str( "JMP #", lehmer_label ));

        APPEND_M(str( "#:", no_table_label ));
        APPEND_M( "#gcd_base no table" );
        {
            track_asm( "gcd_base iter no table" );

            //have to do this check here because it might have been skipped: if (ab[1]<=ab_threshold) goto exit_label
            APPEND_M(str( "MOVAPD `tmp, `ab" ));
            APPEND_M(str( "CMPLEPD `tmp, `ab_threshold" )); // tmp all 0s if (ab[0]>ab_threshold[0] && ab[1]>ab_threshold[1])
            APPEND_M(str( "PTEST `tmp, `tmp" ));
            APPEND_M(str( "JNZ #", track_asm( "gcd_base ab[1]<=ab_threshold", exit_label ) ));

            //q is clobbered, so need to restore it
            APPEND_M(str( "MOVQ `q, `q_scalar_3" ));

            // q=floor(q);
            //this requires SSE4. if not present, can also add and subtract a magic number
            APPEND_M(str( "ROUNDSD `q, `q, 1" )); //floor

            // m=[0 1]
            //    1 -q]
            // m_0=<0,1> [column 0]
            // m_1=<1,-q> [column 1]
            APPEND_M(str( "MOVAPD `m_0, #", constant_address_double(0.0, 1.0) ));
            APPEND_M(str( "MOVAPD `m_1, `m_0" )); // m_1=<0,1>
            APPEND_M(str( "SUBSD `m_1, `q" )); //m_1=<-q,1>
            APPEND_M(str( "SHUFPD `m_1, `m_1, 1" )); //m_1=<1,-q>

            calculate_using_m(exit_label);
        }

        APPEND_M(str( "#:", lehmer_label ));
        APPEND_M( "#gcd_base end no table" );

        // new_ab_0=<new_ab[0], new_ab[0]>
        // new_ab_1=<new_ab[1], new_ab[1]>
        // ab_delta=new_ab_0-new_ab_1

        // new_uv_0=<new_u[0], new_v[0]>
        // new_uv_1=<new_u[1], new_v[1]>

        //bool passed=
        //    new_ab_1[0]>=-new_uv_1[0] && ab_delta[0]+new_uv_0[0]>=new_uv_1[0] &&
        //    new_ab_1[1]>=-new_uv_1[1] && ab_delta[1]+new_uv_0[1]>=new_uv_1[1]
        //;

        //bool passed=
        //    new_ab_1[0]>=-new_uv_1[0] && ab_delta[0]+new_vu_0[0]>=new_vu_1[0] &&
        //    new_ab_1[1]>=-new_uv_1[1] && ab_delta[1]+new_vu_0[1]>=new_vu_1[1]
        //;

        //bool passed=
        //    new_ab[1]>=-new_u[1] && ab_delta[0]+new_v[0]>=new_v[1] &&
        //    new_ab[1]>=-new_v[1] && ab_delta[0]+new_u[0]>=new_u[1]
        //;

        //m_0=new_uv_0=<new_u[0], new_v[0]>
        APPEND_M(str( "MOVAPD `m_0, `new_u" ));
        APPEND_M(str( "SHUFPD `m_0, `new_v, 0" ));

        //m_1=new_uv_1=<new_u[1], new_v[1]>
        APPEND_M(str( "MOVAPD `m_1, `new_u" ));
        APPEND_M(str( "SHUFPD `m_1, `new_v, 3" ));

        //tmp=new_ab_0=<new_ab[0], new_ab[0]>
        APPEND_M(str( "MOVAPD `tmp, `new_ab" ));
        APPEND_M(str( "SHUFPD `tmp, `tmp, 0" ));

        //tmp=ab_delta=new_ab_0-new_ab_1
        APPEND_M(str( "SUBPD `tmp, `new_ab_1" ));

        //tmp=ab_delta+new_uv_0
        APPEND_M(str( "ADDPD `tmp, `m_0" ));

        //tmp all 0s if (ab_delta[0]+new_uv_0[0]>=new_uv_1[0] && ab_delta[1]+new_uv_0[1]>=new_uv_1[1])
        APPEND_M(str( "CMPLTPD `tmp, `m_1" ));

        //m_1=-new_uv_1
        APPEND_M(str( "XORPD `m_1, #", constant_address_uint64(double_sign_mask, double_sign_mask) ));

        //new_ab_1 all 0s if (new_ab_1[0]>=-new_uv_1[0] && new_ab_1[1]>=-new_uv_1[1])
        APPEND_M(str( "CMPLTPD `new_ab_1, `m_1" ));

        //if (is_lehmer && !(ab_delta[0]+new_uv_0[0]>=new_uv_1[0] && ab_delta[1]+new_uv_0[1]>=new_uv_1[1])) goto exit_label
        //if (is_lehmer && !(new_ab_1[0]>=-new_uv_1[0] && new_ab_1[1]>=-new_uv_1[1])) goto exit_label
        APPEND_M(str( "ORPD `tmp, `new_ab_1" )); //tmp all 0s if passed is true
        APPEND_M(str( "ANDPD `tmp, `is_lehmer" )); //tmp all 0s if passed||(!is_lehmer) is true
        APPEND_M(str( "PTEST `tmp, `tmp" ));
        APPEND_M(str( "JNZ #", track_asm( "gcd_base lehmer failed", exit_label ) ));

        APPEND_M(str( "MOVAPD `ab, `new_ab" ));
        APPEND_M(str( "MOVAPD `u, `new_u" ));
        APPEND_M(str( "MOVAPD `v, `new_v" ));
        track_asm( "gcd_base good iter" );

        APPEND_M(str( "DEC `loop_counter" ));
        APPEND_M(str( "JNZ #", loop_label ));

        APPEND_M( "#gcd_base loop end" );
    }

    track_asm( "gcd_base good exit" );

    APPEND_M(str( "#:", exit_label ));

    APPEND_M(str( "CMP `loop_counter, #", to_hex(gcd_base_max_iter) ));
    APPEND_M(str( "JE #", track_asm( "gcd_base no progress", no_progress_label ) ));
}


}