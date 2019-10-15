namespace asm_code {


string vpermq_mask(array<int, 4> lanes) {
    int res=0;
    for (int x=0;x<4;++x) {
        int lane=lanes[x];
        assert(lane>=0 && lane<4);
        res|=lane << (2*x);
    }
    return to_hex(res);
}

string vpblendd_mask_4(array<int, 4> lanes) {
    int res=0;
    for (int x=0;x<4;++x) {
        int lane=lanes[x];
        assert(lane>=0 && lane<2);
        res|=((lane==1)? 3 : 0) << (2*x);
    }
    return to_hex(res);
}

string vpblendd_mask_8(array<int, 8> lanes) {
    int res=0;
    for (int x=0;x<8;++x) {
        int lane=lanes[x];
        assert(lane>=0 && lane<2);
        res|=((lane==1)? 1 : 0) << x;
    }
    return to_hex(res);
}

struct asm_function {
    string name;

    //this excludes the argument regs (if any). can add them after they are done being used
    reg_alloc regs;

    vector<reg_scalar> args;

    vector<reg_scalar> pop_regs;
    const vector<reg_scalar> all_save_regs={reg_rbp, reg_rbx, reg_r12, reg_r13, reg_r14, reg_r15};
    const vector<reg_scalar> all_arg_regs={reg_rdi, reg_rsi, reg_rdx, reg_rcx, reg_r8, reg_r9};

    //the scratch area ends at RSP (i.e. the last byte is at address RSP-1)
    //RSP is 64-byte aligned
    //RSP must be preserved but all other registers can be changed
    //
    //the arguments are stored in: RDI, RSI, RDX, RCX, R8, R9
    //each argument is up to 8 bytes
    asm_function(string t_name, int num_args=0, int num_regs=15) {
        EXPAND_MACROS_SCOPE;

        static bool outputted_header=false;
        if (!outputted_header) {
            APPEND_M(str( ".intel_syntax noprefix" ));
            outputted_header=true;
        }

        name=t_name;

#ifdef CHIAOSX
        APPEND_M(str( ".global _asm_func_#", t_name ));
        APPEND_M(str( "_asm_func_#:", t_name ));
#else
        APPEND_M(str( ".global asm_func_#", t_name ));
        APPEND_M(str( "asm_func_#:", t_name ));
#endif

        assert(num_regs<=15);
        regs.init();

        for (int x=0;x<num_args;++x) {
            reg_scalar r=all_arg_regs.at(x);
            regs.get_scalar(r);
            args.push_back(r);
        }

        //takes 6 cycles max if nothing else to do
        int num_available_regs=15-all_save_regs.size();
        for (reg_scalar s : all_save_regs) {
            if (num_regs>num_available_regs) {
                APPEND_M(str( "PUSH #", s.name() ));
                pop_regs.push_back(s);
                ++num_available_regs;
            } else {
                regs.get_scalar(s);
            }
        }
        assert(num_available_regs==num_regs);

        // RSP'=RSP&(~63) ; this makes it 64-aligned and can only reduce its value
        // RSP''=RSP'-64 ; still 64-aligned but now there is at least 64 bytes of unused stuff
        // [RSP'']=RSP ; store old value in unused area
        APPEND_M(str( "MOV RAX, RSP" ));
        APPEND_M(str( "AND RSP, -64" )); //-64 equals ~63
        APPEND_M(str( "SUB RSP, 64" ));
        APPEND_M(str( "MOV [RSP], RAX" ));
    }

    //the return value is the error code (0 if no error). it is put in RAX
    ~asm_function() {
        EXPAND_MACROS_SCOPE;

        //default return value of 0
        APPEND_M(str( "MOV RAX, 0" ));

        string end_label=m.alloc_label();
        APPEND_M(str( "#:", end_label ));
        //this takes 4 cycles including ret, if there is nothing else to do
        APPEND_M(str( "MOV RSP, [RSP]" ));
        for (int x=pop_regs.size()-1;x>=0;--x) {
            APPEND_M(str( "POP #", pop_regs[x].name() ));
        }
        APPEND_M(str( "RET" ));

        while (m.next_output_error_label_id<m.next_error_label_id) {
            APPEND_M(str( "label_error_#:", m.next_output_error_label_id ));

            assert(m.next_output_error_label_id!=0);
            APPEND_M(str( "MOV RAX, #", to_hex(m.next_output_error_label_id) ));
            APPEND_M(str( "JMP #", end_label ));

            ++m.next_output_error_label_id;
        }
    }
};


}