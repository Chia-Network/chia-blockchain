namespace asm_code {


struct asm_integer {
    //if a sign limb exists, it is one qword before this address. the data limbs are after this address
    reg_scalar addr_base;

    //the asm_integer functions only use addr_base. this is used to assign addr_base if it needs to be allocated
    reg_spill addr_base_spill;

    int addr_offset=0;

    bool is_signed=false;
    int size=0; //limbs. lsb limb is first. this is a multiple of 4

    asm_integer() {}
    asm_integer(reg_spill t_spill, int t_size) {
        addr_base_spill=t_spill;
        size=t_size;
    }

    string operator[](int pos) {
        assert(pos>=0 && pos<size);
        return str( "[#+#]", addr_base.name(), to_hex(addr_offset+pos*8) );
    }

    bool is_null() {
        return size==0;
    }

    //end_index will return the number of nonzero limbs minus 1
    //end_index should initially be >= the number nonzero of limbs minus 1, but not more than size-1
    //if the integer is 0, end_index should initially be at least 0 and the returned end_index is 0
    //regs: 3x scalar
    void update_end_index(reg_alloc regs, reg_scalar end_index) {
        EXPAND_MACROS_SCOPE;

        assert(size%4==0);
        assert(addr_offset==0); //can temporarily modify addr_base if this is false

        m.bind(end_index, "end_index");
        m.bind(addr_base, "addr_base");
        reg_scalar tmp_value=regs.bind_scalar(m, "tmp_value");
        reg_scalar tmp_0=regs.bind_scalar(m, "tmp_0");
        reg_scalar tmp_8=regs.bind_scalar(m, "tmp_8");

        //convert index to address
        APPEND_M(str( "LEA `end_index, [`addr_base+`end_index*8]" ));

        APPEND_M(str( "XOR `tmp_0, `tmp_0" ));
        APPEND_M(str( "MOV `tmp_8, 8" ));

        string loop_label=m.alloc_label();

        const int num_unroll=2;
        assert(num_unroll>=1);

        for (int x=0;x<num_unroll;++x) {
            if (x==num_unroll-1) {
                APPEND_M(str( "#:", loop_label ));
            }

            APPEND_M(str( "MOV `tmp_value, [`end_index]" ));

            //tmp_value=(tmp_value==0)? 8 : 0
            //(8 if the last limb is 0, else 0)
            APPEND_M(str( "CMP `tmp_value, `tmp_0" ));
            APPEND_M(str( "MOV `tmp_value, `tmp_0" ));
            APPEND_M(str( "CMOVE `tmp_value, `tmp_8" ));

            //if (end_index==end_addr) tmp_value=0
            //(sets tmp_value to 0 if there is only 1 limb left)
            APPEND_M(str( "CMP `end_index, `addr_base" ));
            APPEND_M(str( "CMOVE `tmp_value, `tmp_0" ));

            //if tmp_value==8, go to the next lowest limb
            //if tmp_value==0, do nothing
            APPEND_M(str( "SUB `end_index, `tmp_value" ));

            if (x==1) {
                //keep looping until end_index stops changing
                APPEND_M(str( "CMP `tmp_value, `tmp_0" ));
                APPEND_M(str( "JNE #", track_asm( "update_end_index loop", loop_label ) ));
            }
        }

        //convert address to index
        APPEND_M(str( "SUB `end_index, `addr_base" ));
        APPEND_M(str( "SHR `end_index, 3" ));
    }

    //end_index=(end_index<2)? 0 : end_index-2
    //regs: 1x scalar
    void calculate_head_start(reg_alloc regs, reg_scalar end_index) {
        EXPAND_MACROS_SCOPE;

        assert(size%4==0);

        m.bind(end_index, "end_index");

        reg_scalar tmp=regs.bind_scalar(m, "tmp");

        APPEND_M(str( "XOR `tmp, `tmp" ));
        APPEND_M(str( "SUB `end_index, 2" ));
        APPEND_M(str( "CMOVB `end_index, `tmp" ));
    }

    //this is the same as extract_head, except that extracts at nonzero_size
    //nonzero_size should be >= the actual nonzero size to avoid truncation
    //regs: 1x scalar
    void extract_head_at(reg_alloc regs, reg_scalar head_start, array<reg_scalar, 3> res) {
        EXPAND_MACROS_SCOPE;

        assert(size%4==0);

        m.bind(addr_base, "addr_base");
        m.bind(head_start, "head_start");
        m.bind(res, "res");

        reg_scalar tmp_addr=regs.bind_scalar(m, "tmp_addr");

        APPEND_M(str( "LEA `tmp_addr, [`addr_base+`head_start*8+#]", to_hex(addr_offset) ));
        APPEND_M(str( "MOV `res_0, [`tmp_addr]" ));
        APPEND_M(str( "MOV `res_1, [`tmp_addr+8]" ));
        APPEND_M(str( "MOV `res_2, [`tmp_addr+16]" ));
    }

    void mul_add_bmi(
        reg_alloc regs, asm_integer a, reg_scalar b, asm_integer c, bool invert_output, bool carry_in_is_1
    ) {
        EXPAND_MACROS_SCOPE;

        m.bind(b, "b");

        //5x scalar
        reg_scalar mul_low_0=regs.bind_scalar(m, "mul_low_0");
        reg_scalar mul_low_1=regs.bind_scalar(m, "mul_low_1");
        reg_scalar mul_high_0=regs.bind_scalar(m, "mul_high_0");
        reg_scalar mul_high_1=regs.bind_scalar(m, "mul_high_1");
        reg_scalar rdx=regs.bind_scalar(m, "rdx", reg_rdx);

        //clears OF and CF
        APPEND_M(str( "XOR RDX, RDX" ));

        if (carry_in_is_1) {
            APPEND_M(str( "STC" ));
        }

        APPEND_M(str( "MOV RDX, `b" ));

        for (int pos=0;pos<size;pos+=2) {
            bool first=(pos==0);

            //mul_low=mul_low+mul_high>>64
            APPEND_M(str( "MULX `mul_high_0, `mul_low_0, #", a[pos] ));

            if (!first) {
                APPEND_M(str( "ADOX `mul_low_0, `mul_high_1" ));
            }

            APPEND_M(str( "MULX `mul_high_1, `mul_low_1, #", a[pos+1] ));
            APPEND_M(str( "ADOX `mul_low_1, `mul_high_0" ));

            if (!c.is_null()) {
                APPEND_M(str( "ADCX `mul_low_0, #", c[pos] ));
                APPEND_M(str( "ADCX `mul_low_1, #", c[pos+1] ));
            }

            if (invert_output) {
                APPEND_M(str( "NOT `mul_low_0" ));
                APPEND_M(str( "NOT `mul_low_1" ));
            }

            APPEND_M(str( "MOV #, `mul_low_0", (*this)[pos] ));
            APPEND_M(str( "MOV #, `mul_low_1", (*this)[pos+1] ));
        }
    }

    void mul_add_slow(
        reg_alloc regs, asm_integer a, reg_scalar b, asm_integer c, bool invert_output, bool carry_in_is_1
    ) {
        EXPAND_MACROS_SCOPE;

        m.bind(b, "b");

        //11x scalar
        reg_scalar mul_carry=regs.bind_scalar(m, "mul_carry");
        reg_scalar add_carry=regs.bind_scalar(m, "add_carry");
        reg_scalar mul_high_4_previous=regs.bind_scalar(m, "mul_high_4_previous");
        reg_scalar mul_low_0=regs.bind_scalar(m, "mul_low_0");
        reg_scalar mul_low_1=regs.bind_scalar(m, "mul_low_1");
        reg_scalar mul_low_2=regs.bind_scalar(m, "mul_low_2");
        reg_scalar mul_low_3=regs.bind_scalar(m, "mul_low_3", reg_rax);
        reg_scalar mul_high_0=regs.bind_scalar(m, "mul_high_0");
        reg_scalar mul_high_1=regs.bind_scalar(m, "mul_high_1");
        reg_scalar mul_high_2=regs.bind_scalar(m, "mul_high_2");
        reg_scalar mul_high_3=regs.bind_scalar(m, "mul_high_3", reg_rdx);

        for (int pos=0;pos<size;pos+=4) {
            bool first=(pos==0);
            bool last=(pos==size-4);

            //multiply 4 values of a by b
            for (int x=0;x<4;++x) {
                //mul_low_3=RAX
                //mul_high_3=RDX
                APPEND_M(str( "MOV RAX, `b" ));
                APPEND_M(str( "MUL QWORD PTR #", a[pos+x] ));

                if (x==3) {
                    assert(mul_low_3.value==reg_rax.value);
                    assert(mul_high_3.value==reg_rdx.value);
                } else {
                    APPEND_M(str( "MOV `mul_low_#, RAX", x ));
                    APPEND_M(str( "MOV `mul_high_#, RDX", x ));
                }
            }

            //mul_low=mul_low+mul_high>>64
            if (first) {
                //mul_carry==0 ; mul_high_4_previous==0
                APPEND_M(str( "ADD `mul_low_1, `mul_high_0" ));
            } else {
                APPEND_M(str( "ADD `mul_carry, 1" )); // CF=(mul_carry==-1)? 1 : 0
                APPEND_M(str( "ADC `mul_low_0, `mul_high_4_previous" ));
                APPEND_M(str( "ADC `mul_low_1, `mul_high_0" ));
            }

            APPEND_M(str( "ADC `mul_low_2, `mul_high_1" ));
            APPEND_M(str( "ADC `mul_low_3, `mul_high_2" ));

            if (!last) {
                APPEND_M(str( "MOV `mul_high_4_previous, `mul_high_3" ));
                APPEND_M(str( "SBB `mul_carry, `mul_carry" )); // mul_carry=(CF)? -1 : 0
            }

            if (!c.is_null()) {
                //mul_low=mul_low+c
                //output mul_low

                if (first) {
                    if (carry_in_is_1) {
                        APPEND_M(str( "STC" ));
                        APPEND_M(str( "ADC `mul_low_0, #", c[pos] ));
                    } else {
                        APPEND_M(str( "ADD `mul_low_0, #", c[pos] ));
                    }
                } else {
                    APPEND_M(str( "ADD `add_carry, 1" )); // CF=(add_carry==-1)? 1 : 0
                    APPEND_M(str( "ADC `mul_low_0, #", c[pos] ));
                }

                for (int x=1;x<4;++x) {
                    APPEND_M(str( "ADC `mul_low_#, #", x, c[pos+x] ));
                }

                if (!last) {
                    APPEND_M(str( "SBB `add_carry, `add_carry" )); // add_carry=(CF)? -1 : 0
                }
            }

            for (int x=0;x<4;++x) {
                if (invert_output) {
                    APPEND_M(str( "NOT `mul_low_#", x ));
                }
                APPEND_M(str( "MOV #, `mul_low_#", (*this)[pos+x], x ));
            }
        }
    }

    // (*this)=a*b+c+(carry_in_is_1? 1 : 0)
    // if (invert_output) (*this)=~(*this)
    //all of the integers must have the same size (which is a multiple of 4)
    //a or c can alias with *this (as long as the aliasing is not partial)
    //regs: 11x scalar
    //
    //to calculate a*b-c*d:
    //-first calculate ~(c*d)
    //-then calculate a*b+(~(c*d))+1
    void mul_add(
        reg_alloc regs, asm_integer a, reg_scalar b, asm_integer c, bool invert_output, bool carry_in_is_1
    ) {
        EXPAND_MACROS_SCOPE;

        assert(!carry_in_is_1 || !c.is_null());
        assert(size%4==0);
        assert(size==a.size && (c.is_null() || size==c.size));

        if (enable_all_instructions) {
            mul_add_bmi(regs, a, b, c, invert_output, carry_in_is_1);
        } else {
            mul_add_slow(regs, a, b, c, invert_output, carry_in_is_1);
        }
    }
};

//sets res to the right shift amount required for the uppermost limb to be 0. this is between 0 and 64 inclusive
//regs: 1x scalar
void calculate_shift_amount(reg_alloc regs, array<reg_scalar, 3> limbs, reg_scalar res) {
    EXPAND_MACROS_SCOPE;

    m.bind(limbs, "limbs");
    m.bind(res, "res");

    reg_scalar tmp=regs.bind_scalar(m, "tmp");

    //res=[first set bit index in limbs_2]+1
    APPEND_M(str( "BSR `res, `limbs_2" ));
    APPEND_M(str( "INC `res" ));

    //res=num bits of limbs_2 [which is also the right shift amount]
    //(this is 0 if limbs_2 is 0)
    APPEND_M(str( "XOR `tmp, `tmp" ));
    APPEND_M(str( "CMP `limbs_2, `tmp" ));
    APPEND_M(str( "CMOVE `res, `tmp" ));
}

//amount must be >=0 and <=64
//this only calculates the lower 2 limbs of the result
//regs: 1x scalar
//in-place
void shift_right(reg_alloc regs, array<reg_scalar, 3> limbs, reg_scalar amount) {
    EXPAND_MACROS_SCOPE;

    m.bind(limbs, "limbs");
    m.bind(amount, "amount");

    regs.get_scalar(reg_rcx);

    APPEND_M(str( "MOV RCX, `amount" ));

    // if (amount<64) res[0]=[limbs[1]:limbs[0]]>>amount
    // if (amount==64) no-op
    APPEND_M(str( "SHRD `limbs_0, `limbs_1, CL" ));

    // if (amount<64) res[1]=[limbs[2]:limbs[1]]>>amount
    // if (amount==64) no-op
    APPEND_M(str( "SHRD `limbs_1, `limbs_2, CL" ));

    APPEND_M(str( "CMP `amount, 64" ));
    APPEND_M(str( "CMOVE `limbs_0, `limbs_1" ));
    APPEND_M(str( "CMOVE `limbs_1, `limbs_2" ));
}

//this must be true: a>=b; a>=threshold
//
//all of the integers should have spilled addresses with offsets of 0. all of their sizes should be the same
//the input a and b values should go into spill_a and spill_b. spill_a_2 and spill_b_2 should be uninitialized
//spill_iter will be between -1 and max_iterations
//the final a value is in spill_a if spill_iter is odd, otherwise is is in a_2. same with b
//
//for each iteration, including iteration -1, the following will happen:
//-64 bytes of data is written to *(spill_out_uv_addr + iter*64)
//-then, *spill_uv_counter_addr is set to spill_uv_counter_start+iter
//
//the data has the following format: [u0] [u1] [v0] [v1] [parity] [exit_flag]
//-each entry is 8 bytes
//-if iter is -1, only exit_flag is initialized and the rest have undefined values
//-if exit_flag is 1, this is the final result
//
//no more than max_iterations+1 results will be outputted. there will be an error if there are more results than this
//(this includes iteration -1)
//
//spill_a_end_index must be < a's size and >= 0. any limbs past this must be 0 for a, b, and threshold, but only up to the next
// multiple of 4 limbs. (e.g. if spill_a_end_index is 6, there are 7 limbs so the 8th limb must be 0 and the rest can be uninitialized)
//
//the return value of iter is the total number of iterations performed, which is at least 0. iter-1 is the parity of the last iteration
void gcd_unsigned(
    reg_alloc regs_parent,
    asm_integer spill_a, asm_integer spill_b, asm_integer spill_a_2, asm_integer spill_b_2, asm_integer spill_threshold,
    reg_spill spill_uv_counter_start, reg_spill spill_out_uv_counter_addr, reg_spill spill_out_uv_addr,
    reg_spill spill_iter, reg_spill spill_a_end_index, int max_iterations
) {
    EXPAND_MACROS_SCOPE_PUBLIC;

    track_asm( "gcd_unsigned" );

    int int_size=spill_a.size;
    assert(spill_a.addr_offset==0 && spill_b.addr_offset==0 && spill_threshold.addr_offset==0);
    assert(spill_a.addr_base.value==-1 && spill_b.addr_base.value==-1 && spill_threshold.addr_base.value==-1);
    assert(spill_a_2.addr_offset==0 && spill_b_2.addr_offset==0);
    assert(spill_a_2.addr_base.value==-1 && spill_b_2.addr_base.value==-1);
    assert(spill_a.size==int_size && spill_b.size==int_size && spill_threshold.size==int_size);
    assert(spill_a_2.size==int_size && spill_b_2.size==int_size);

    m.bind(spill_a.addr_base_spill, "spill_a_addr_base");
    m.bind(spill_a_2.addr_base_spill, "spill_a_2_addr_base");

    m.bind(spill_b.addr_base_spill, "spill_b_addr_base");
    m.bind(spill_b_2.addr_base_spill, "spill_b_2_addr_base");

    m.bind(spill_threshold.addr_base_spill, "spill_threshold_addr_base");

    m.bind(spill_iter, "spill_iter");
    m.bind(spill_uv_counter_start, "spill_uv_counter_start");
    m.bind(spill_out_uv_addr, "spill_out_uv_addr");
    m.bind(spill_out_uv_counter_addr, "spill_out_uv_counter_addr");
    m.bind(spill_a_end_index, "spill_a_end_index");

    reg_spill spill_u_0=regs_parent.bind_spill(m, "spill_u_0");
    reg_spill spill_u_1=regs_parent.bind_spill(m, "spill_u_1");
    reg_spill spill_v_0=regs_parent.bind_spill(m, "spill_v_0");
    reg_spill spill_v_1=regs_parent.bind_spill(m, "spill_v_1");
    reg_spill spill_parity=regs_parent.bind_spill(m, "spill_parity");
    reg_spill spill_is_lehmer=regs_parent.bind_spill(m, "spill_is_lehmer");

    reg_spill spill_a_128=regs_parent.bind_spill(m, "spill_a_128", 16, 8);
    reg_spill spill_b_128=regs_parent.bind_spill(m, "spill_b_128", 16, 8);
    reg_spill spill_threshold_128=regs_parent.bind_spill(m, "spill_threshold_128", 16, 8);

    m.bind(spill_a_128+8, "spill_a_128_8");
    m.bind(spill_b_128+8, "spill_b_128_8");
    m.bind(spill_threshold_128+8, "spill_threshold_128_8");

    APPEND_M(str( "MOV QWORD PTR `spill_iter, -1" ));

    string loop_start=m.alloc_label();
    string loop=m.alloc_label();
    string loop_exit=m.alloc_label();

    APPEND_M(str( "JMP #", loop_start ));

    APPEND_M(str( "#:", loop ));

    //iter even: old_a=a  , old_b=b   ; new_a=a_2, new_b=b_2
    //iter odd:  old_a=a_2, old_b=b_2 ; new_a=a  , new_b=b

    gcd_128(
        regs_parent,
        {spill_a_128, spill_b_128}, {spill_u_0, spill_u_1}, {spill_v_0, spill_v_1},
        spill_parity, spill_is_lehmer, spill_threshold_128,
        track_asm( "gcd_unsigned error: gcd 128 stuck", m.alloc_error_label() )
    );

    string exit_multiply_uv=m.alloc_label();

    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        reg_scalar tmp=regs.bind_scalar(m, "tmp");

        string jump_table_label=m.alloc_label();

#ifdef CHIAOSX
        APPEND_M(str( ".text " ));
#else
        APPEND_M(str( ".text 1" ));
#endif
        APPEND_M(str( ".balign 8" ));
        APPEND_M(str( "#:", jump_table_label ));

#ifdef CHIAOSX
        APPEND_M(str( ".text" ));

        APPEND_M(str( "MOV `tmp, `spill_a_end_index" ));

        for (int end_index=0;end_index<int_size;++end_index) {
            int size=end_index+1;

            int mapped_size=size;
            while (mapped_size==0 || mapped_size%4!=0) {
                ++mapped_size;
            }

            APPEND_M(str( "CMP `tmp, #", size ));
            APPEND_M(str( "JE multiply_uv_size_#", mapped_size ));
        }
#else
        for (int end_index=0;end_index<int_size;++end_index) {
            int size=end_index+1;
            
            int mapped_size=size; 
            while (mapped_size==0 || mapped_size%4!=0) {
                ++mapped_size;
            }

            APPEND_M(str( ".quad multiply_uv_size_#", mapped_size ));
        }
        APPEND_M(str( ".text" ));

        APPEND_M(str( "MOV `tmp, `spill_a_end_index" ));
        APPEND_M(str( "JMP QWORD PTR [#+`tmp*8]", jump_table_label ));
#endif
    }
    for (int size=4;size<=int_size;size+=4) {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        APPEND_M(str( "multiply_uv_size_#:", size ));
        track_asm(str( "gcd_unsigned multiply uv size #", size ));

        //reg_scalar t=regs.bind_scalar(m, "t");

        // even:
        // new_a=a*u_0 - b*v_0;
        // new_a=b*v_1 - a*u_1;
        //
        // tmp0=b*v_0
        // tmp1=a*u_1
        // new_a=a*u_0 - tmp0
        // new_b=b*v_1 - tmp1
        //
        // odd:
        // new_a=b*v_0 - a*u_0;
        // new_b=a*u_1 - b*v_1;
        //
        // tmp0=a*u_0
        // tmp1=b*v_1
        // new_a=b*v_0 - tmp0
        // new_b=a*u_1 - tmp1
        //
        // in general:
        // tmp0=(even?b:a)*(even?v_0:u_0)
        // tmp1=(even?a:b)*(even?u_1:v_1)
        // new_a=(even?a:b)*(even?u_0:v_0) - tmp0
        // new_b=(even?b:a)*(even?v_1:u_1) - tmp1

        reg_scalar addr_a=regs.bind_scalar(m, "addr_a");
        reg_scalar addr_b=regs.bind_scalar(m, "addr_b");
        reg_scalar addr_new=regs.bind_scalar(m, "addr_new");
        reg_scalar tmp=regs.bind_scalar(m, "tmp");

        reg_spill spill_mod_u_0=regs.bind_spill(m, "spill_mod_u_0");
        reg_spill spill_mod_u_1=regs.bind_spill(m, "spill_mod_u_1");
        reg_spill spill_mod_v_0=regs.bind_spill(m, "spill_mod_v_0");
        reg_spill spill_mod_v_1=regs.bind_spill(m, "spill_mod_v_1");

        reg_spill spill_addr_b_new=regs.bind_spill(m, "spill_addr_b_new");

        APPEND_M(str( "MOV `tmp, `spill_parity" ));
        APPEND_M(str( "CMP `tmp, 0" ));

        for (int x=0;x<2;++x) {
            APPEND_M(str( "MOV `addr_a, `spill_u_#", x ));
            APPEND_M(str( "MOV `addr_b, `spill_v_#", x ));

            //if (spill_parity!=0) swap(u[x], v[x])
            APPEND_M(str( "MOV `addr_new, `addr_a" ));
            APPEND_M(str( "CMOVNE `addr_a, `addr_b" ));
            APPEND_M(str( "CMOVNE `addr_b, `addr_new" ));

            APPEND_M(str( "MOV `spill_mod_u_#, `addr_a", x ));
            APPEND_M(str( "MOV `spill_mod_v_#, `addr_b", x ));
        }

        APPEND_M(str( "MOV `addr_new, `spill_iter" ));
        APPEND_M(str( "TEST `addr_new, 1" )); // ZF=even iteration

        //addr_a=(even iteration)? &a : &a_2
        APPEND_M(str( "MOV `addr_a, `spill_a_addr_base" ));
        APPEND_M(str( "CMOVNZ `addr_a, `spill_a_2_addr_base" ));

        //addr_b=(even iteration)? &b : &b_2
        APPEND_M(str( "MOV `addr_b, `spill_b_addr_base" ));
        APPEND_M(str( "CMOVNZ `addr_b, `spill_b_2_addr_base" ));

        //if (spill_parity!=0) swap(addr_a, addr_b)
        APPEND_M(str( "CMP `tmp, 0" ));
        APPEND_M(str( "MOV `addr_new, `addr_a" ));
        APPEND_M(str( "CMOVNE `addr_a, `addr_b" ));
        APPEND_M(str( "CMOVNE `addr_b, `addr_new" ));

        //done using tmp (spill_parity)

        //spill_addr_b_new=(even iteration)? &b_2 : &b
        APPEND_M(str( "MOV `addr_new, `spill_iter" ));
        APPEND_M(str( "TEST `addr_new, 1" )); // ZF=even iteration
        APPEND_M(str( "MOV `addr_new, `spill_b_2_addr_base" ));
        APPEND_M(str( "CMOVNZ `addr_new, `spill_b_addr_base" ));
        APPEND_M(str( "MOV `spill_addr_b_new, `addr_new" ));

        //addr_new=(even iteration)? &a_2 : &a
        APPEND_M(str( "MOV `addr_new, `spill_a_2_addr_base" ));
        APPEND_M(str( "CMOVNZ `addr_new, `spill_a_addr_base" ));

        //this can be a, a_2, b, or b_2 depending on iter and parity
        asm_integer a;
        a.size=int_size;
        a.addr_base=addr_a;

        asm_integer b;
        b.size=int_size;
        b.addr_base=addr_b;

        //initially new_a
        asm_integer new_ab;
        new_ab.size=int_size;
        new_ab.addr_base=addr_new;

        reg_spill tmp0_spill=regs.get_spill(int_size*8, 8);
        asm_integer tmp0;
        tmp0.size=int_size;
        tmp0.addr_base=reg_rsp;
        tmp0.addr_offset=tmp0_spill.get_rsp_offset();

        reg_spill tmp1_spill=regs.get_spill(int_size*8, 8);
        asm_integer tmp1;
        tmp1.size=int_size;
        tmp1.addr_base=reg_rsp;
        tmp1.addr_offset=tmp1_spill.get_rsp_offset();

        // tmp0=(even?b:a)*(even?v_0:u_0)
        APPEND_M(str( "MOV `tmp, `spill_mod_v_0" ));
        tmp0.mul_add(regs, b, tmp, asm_integer(), true, false);

        // tmp1=(even?a:b)*(even?u_1:v_1)
        APPEND_M(str( "MOV `tmp, `spill_mod_u_1" ));
        tmp1.mul_add(regs, a, tmp, asm_integer(), true, false);

        // new_a=(even?a:b)*(even?u_0:v_0) - tmp0
        APPEND_M(str( "MOV `tmp, `spill_mod_u_0" ));
        new_ab.mul_add(regs, a, tmp, tmp0, false, true);

        // new_b=(even?b:a)*(even?v_1:u_1) - tmp1
        APPEND_M(str( "MOV `addr_new, `spill_addr_b_new" ));
        APPEND_M(str( "MOV `tmp, `spill_mod_v_1" ));
        new_ab.mul_add(regs, b, tmp, tmp1, false, true);

        APPEND_M(str( "JMP #", exit_multiply_uv ));
    }
    APPEND_M(str( "#:", exit_multiply_uv ));

    //8x
    reg_scalar iter=regs_parent.bind_scalar(m, "iter");
    reg_scalar is_lehmer=regs_parent.bind_scalar(m, "is_lehmer");
    reg_scalar a_head_0=regs_parent.bind_scalar(m, "a_head_0");
    reg_scalar a_head_1=regs_parent.bind_scalar(m, "a_head_1");
    reg_scalar b_head_0=regs_parent.bind_scalar(m, "b_head_0");
    reg_scalar b_head_1=regs_parent.bind_scalar(m, "b_head_1");
    reg_scalar a_head_start=regs_parent.bind_scalar(m, "a_head_start");
    reg_scalar shift_right_amount=regs_parent.bind_scalar(m, "shift_right_amount");

    APPEND_M(str( "#:", loop_start ));
    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //6x + 3x from called functions
        reg_scalar addr_a=regs.bind_scalar(m, "addr_a", reg_rax);
        reg_scalar addr_b=regs.bind_scalar(m, "addr_b", reg_rdx);
        reg_scalar b_head_2=regs.bind_scalar(m, "b_head_2");
        reg_scalar a_head_2=regs.bind_scalar(m, "a_head_2");

        APPEND_M(str( "MOV `iter, `spill_iter" ));

        //addr_a=(even iteration)? &a_2 : &a
        APPEND_M(str( "TEST `iter, 1" )); // ZF=even iteration
        APPEND_M(str( "MOV `addr_a, `spill_a_2_addr_base" ));
        APPEND_M(str( "CMOVNZ `addr_a, `spill_a_addr_base" ));

        //addr_b=(even iteration)? &b_2 : &b
        APPEND_M(str( "MOV `addr_b, `spill_b_2_addr_base" ));
        APPEND_M(str( "CMOVNZ `addr_b, `spill_b_addr_base" ));

        asm_integer a;
        a.size=int_size;
        a.addr_base=addr_a;

        asm_integer b;
        b.size=int_size;
        b.addr_base=addr_b;

        APPEND_M(str( "MOV `a_head_start, `spill_a_end_index" ));
        a.update_end_index(regs, a_head_start);
        APPEND_M(str( "MOV `spill_a_end_index, `a_head_start" ));

        //is_lehmer=(a_end_index>=2)
        //(a_end_index is stored in a_head_start)
        APPEND_M(str( "XOR `is_lehmer, `is_lehmer" ));
        APPEND_M(str( "CMP `a_head_start, 2" ));
        APPEND_M(str( "SETAE `is_lehmer_8" ));
        APPEND_M(str( "MOV `spill_is_lehmer, `is_lehmer" ));

        a.calculate_head_start(regs, a_head_start);

        a.extract_head_at(regs, a_head_start, {a_head_0, a_head_1, a_head_2});
        calculate_shift_amount(regs, {a_head_0, a_head_1, a_head_2}, shift_right_amount);
        shift_right(regs, {a_head_0, a_head_1, a_head_2}, shift_right_amount);

        b.extract_head_at(regs, a_head_start, {b_head_0, b_head_1, b_head_2});
        shift_right(regs, {b_head_0, b_head_1, b_head_2}, shift_right_amount);

        APPEND_M(str( "MOV `spill_a_128, `a_head_0" ));
        APPEND_M(str( "MOV `spill_a_128_8, `a_head_1" ));

        APPEND_M(str( "MOV `spill_b_128, `b_head_0" ));
        APPEND_M(str( "MOV `spill_b_128_8, `b_head_1" ));
    }

    //9x
    //iter, is_lehmer, b_head_0, b_head_1, a_head_start, shift_right_amount
    reg_scalar exit_flag=regs_parent.bind_scalar(m, "exit_flag");

    //clobbers is_lehmer
    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //4x + 1x from called functions
        reg_scalar addr_threshold=regs.bind_scalar(m, "addr_threshold", reg_rax);
        reg_scalar threshold_head_0=regs.bind_scalar(m, "threshold_head_0", reg_rdx);
        reg_scalar threshold_head_1=regs.bind_scalar(m, "threshold_head_1");
        reg_scalar threshold_head_2=regs.bind_scalar(m, "threshold_head_2");

        //addr_threshold=&threshold
        APPEND_M(str( "MOV `addr_threshold, `spill_threshold_addr_base" ));

        asm_integer threshold;
        threshold.size=int_size;
        threshold.addr_base=addr_threshold;

        threshold.extract_head_at(regs, a_head_start, {threshold_head_0, threshold_head_1, threshold_head_2});
        shift_right(regs, {threshold_head_0, threshold_head_1, threshold_head_2}, shift_right_amount);

        APPEND_M(str( "MOV `spill_threshold_128, `threshold_head_0" ));
        APPEND_M(str( "MOV `spill_threshold_128_8, `threshold_head_1" ));

        //if (a_head<=threshold_head) goto error
        APPEND_M(str( "MOV `addr_threshold, `threshold_head_0" ));
        APPEND_M(str( "MOV `threshold_head_2, `threshold_head_1" ));
        APPEND_M(str( "SUB `addr_threshold, `a_head_0" ));
        APPEND_M(str( "SBB `threshold_head_2, `a_head_1" ));
        APPEND_M(str( "JNC #", track_asm( "gcd_unsigned error: a_head<=threshold_head", m.alloc_error_label() ) ));

        //threshold_head' = threshold_head-b_head
        APPEND_M(str( "XOR `exit_flag, `exit_flag" ));
        APPEND_M(str( "SUB `threshold_head_0, `b_head_0" ));
        APPEND_M(str( "SBB `threshold_head_1, `b_head_1" ));
        APPEND_M(str( "SETNC `exit_flag_8" )); //exit_flag = (threshold_head>=b_head)

        //if (b_head==threshold_head && is_lehmer) goto error
        APPEND_M(str( "OR `threshold_head_0, `threshold_head_1" ));
        APPEND_M(str( "DEC `is_lehmer" )); // is_lehmer'=(is_lehmer)? 0 : ~0
        APPEND_M(str( "OR `threshold_head_0, `is_lehmer" )); //ZF = (threshold_head'==0 && is_lehmer)
        APPEND_M(str( "JZ #", track_asm( "gcd_unsigned error: b_head==threshold_head and is_lehmer", m.alloc_error_label() ) ));
    }

    //9x

    {
        EXPAND_MACROS_SCOPE;
        reg_alloc regs=regs_parent;

        //2x
        reg_scalar out_uv_addr=regs.bind_scalar(m, "out_uv_addr");
        reg_scalar tmp=regs.bind_scalar(m, "tmp");

        //out_uv_addr = spill_out_uv_addr + iter*64
        //note: iter can be -1
        APPEND_M(str( "MOV `out_uv_addr, `iter" ));
        APPEND_M(str( "SHL `out_uv_addr, 6" ));
        APPEND_M(str( "ADD `out_uv_addr, `spill_out_uv_addr" ));

        APPEND_M(str( "MOV `tmp, `spill_u_0" ));
        APPEND_M(str( "MOV [`out_uv_addr], `tmp" ));

        APPEND_M(str( "MOV `tmp, `spill_u_1" ));
        APPEND_M(str( "MOV [`out_uv_addr+8], `tmp" ));

        APPEND_M(str( "MOV `tmp, `spill_v_0" ));
        APPEND_M(str( "MOV [`out_uv_addr+16], `tmp" ));

        APPEND_M(str( "MOV `tmp, `spill_v_1" ));
        APPEND_M(str( "MOV [`out_uv_addr+24], `tmp" ));

        APPEND_M(str( "MOV `tmp, `spill_parity" ));
        APPEND_M(str( "MOV [`out_uv_addr+32], `tmp" ));

        APPEND_M(str( "MOV [`out_uv_addr+40], `exit_flag" ));

        //done assigning the data; can now increment the counter. this is not atomic because only this thread can write to the counter
        //(the counter must be 8-aligned)
        //x86 uses acq_rel ordering on all of the loads and stores so no fences are required
        APPEND_M(str( "MOV `tmp, `spill_uv_counter_start" ));
        APPEND_M(str( "ADD `tmp, `iter" ));
        APPEND_M(str( "MOV `out_uv_addr, `spill_out_uv_counter_addr" ));
        APPEND_M(str( "MOV [`out_uv_addr], `tmp" ));

        APPEND_M(str( "INC `iter" ));
        APPEND_M(str( "MOV `spill_iter, `iter" ));

        APPEND_M(str( "CMP `exit_flag, 0" ));
        APPEND_M(str( "JNE #", loop_exit ));

        APPEND_M(str( "CMP `iter, #", to_hex(max_iterations) )); //signed
        APPEND_M(str( "JGE #", track_asm( "gcd_unsigned error: max_iterations exceeded", m.alloc_error_label() ) ));
    }

    APPEND_M(str( "JMP #", loop ));

    APPEND_M(str( "#:", loop_exit ));
}


}