#ifdef GENERATE_ASM_TRACKING_DATA
    const bool generate_asm_tracking_data=true;
#else
    const bool generate_asm_tracking_data=false;
#endif

namespace asm_code {


string track_asm(string comment, string jump_to = "") {
    if (!generate_asm_tracking_data) {
        return jump_to;
    }

    mark_vdf_test();

    static map<string, int> id_map;
    static int next_id=1;

    int& id=id_map[comment];
    if (id==0) {
        id=next_id;
        ++next_id;
    }

    assert(id>=1 && id<=num_asm_tracking_data);

    //
    //

    static bool init=false;
    if (!init) {
        APPEND_M(str( ".data" ));
        APPEND_M(str( ".balign 8" ));

        APPEND_M(str( "track_asm_rax: .quad 0" ));

        //APPEND_M(str( ".global asm_tracking_data" ));
        //APPEND_M(str( "asm_tracking_data:" ));
        //for (int x=0;x<num_asm_tracking_data;++x) {
            //APPEND_M(str( ".quad 0" ));
        //}

        //APPEND_M(str( ".global asm_tracking_data_comments" ));
        //APPEND_M(str( "asm_tracking_data_comments:" ));
        //for (int x=0;x<num_asm_tracking_data;++x) {
            //APPEND_M(str( ".quad 0" ));
        //}

        APPEND_M(str( ".text" ));

        init=true;
    }

    string comment_label=m.alloc_label();
#ifdef CHIAOSX
    APPEND_M(str( ".text " ));
#else
    APPEND_M(str( ".text 1" ));
#endif
    APPEND_M(str( "#:", comment_label ));
    APPEND_M(str( ".string \"#\"", comment ));
    APPEND_M(str( ".text" ));

    string skip_label;
    if (!jump_to.empty()) {
        skip_label=m.alloc_label();
        APPEND_M(str( "JMP #", skip_label ));
    }

    string c_label;

    if (!jump_to.empty()) {
        c_label=m.alloc_label();
        APPEND_M(str( "#:", c_label ));
    }

    assert(!enable_threads); //this code isn't atomic

    APPEND_M(str( "MOV [track_asm_rax], RAX" ));
    APPEND_M(str( "MOV RAX, [asm_tracking_data+#]", to_hex(8*(id-1)) ));
    APPEND_M(str( "LEA RAX, [RAX+1]" ));
    APPEND_M(str( "MOV [asm_tracking_data+#], RAX", to_hex(8*(id-1)) ));
#ifdef CHIAOSX
    APPEND_M(str( "LEA RAX, [RIP+comment_label] " ));
#else
    APPEND_M(str( "MOV RAX, OFFSET FLAT:#", comment_label ));
#endif
    APPEND_M(str( "MOV [asm_tracking_data_comments+#], RAX", to_hex(8*(id-1)) ));
    APPEND_M(str( "MOV RAX, [track_asm_rax]" ));

    if (!jump_to.empty()) {
        APPEND_M(str( "JMP #", jump_to ));
        APPEND_M(str( "#:", skip_label ));
    }

    return c_label;
}

//16-byte aligned; value is in both lanes
string constant_address_uint64(uint64 value_bits_0, uint64 value_bits_1, bool use_brackets=true) {
    static map<pair<uint64, uint64>, string> constant_map;
    string& name=constant_map[make_pair(value_bits_0, value_bits_1)];

    if (name.empty()) {
        name=m.alloc_label();

#ifdef CHIAOSX
        APPEND_M(str( ".text " ));
#else
        APPEND_M(str( ".text 1" ));
#endif
        APPEND_M(str( ".balign 16" ));
        APPEND_M(str( "#:", name ));
        APPEND_M(str( ".quad #", to_hex(value_bits_0) )); //lane 0
        APPEND_M(str( ".quad #", to_hex(value_bits_1) )); //lane 1
        APPEND_M(str( ".text" ));
    }
#ifdef CHIAOSX
    return (use_brackets)? str( "[RIP+#]", name ) : name;
#else
    return (use_brackets)? str( "[#]", name ) : name;
#endif
}

string constant_address_double(double value_0, double value_1, bool use_brackets=true) {
    uint64 value_bits_0=*(uint64*)&value_0;
    uint64 value_bits_1=*(uint64*)&value_1;
    return constant_address_uint64(value_bits_0, value_bits_1, use_brackets);
}


}