/*
0   rax
1   rbx
2   rcx
3   rdx
rax, rcx, rdx, rbx, rsp, rbp, rsi, rdi, r8, r9, r10, r11, r12, r13, r14, r15
rsp - stack pointer (used by stack engine)
rax/rdx - output of multiplication and division; temporaries

notation:
-each name is either a 64 bit scalar register or a 256 bit ymm register
-for ymm registers, a "_128" suffix is used for the xmm register
-for scalar registers: "_32" is used for "eax/r8d/etc", "_16" is used for "ax/r8w/etc", "_8" is used for "al/r8b/etc"
-writing to a 32 bit register zero-extends the result to 64 bits. writing to a 8/16 bit register does not zero extend
***/

const int spill_bytes=1024;
const int comment_asm_line_size=40;

const vector<string> scalar_register_names_64={
    "RSP", //  0 - stack pointer; used by stack engine etc. not allocated
    "RAX", //  1 - temporary; used for mul/div/etc. this is allocated last
    "RDX", //  2 - temporary; used for mul/div/etc. allocated 2nd last
    "RCX", //  3 - temporary; used for shr/etc. allocated 3rd last
    "RBX", //  4
    "RBP", //  5
    "RSI", //  6
    "RDI", //  7
    "R8",  //  8
    "R9",  //  9
    "R10", // 10
    "R11", // 11
    "R12", // 12
    "R13", // 13
    "R14", // 14
    "R15"  // 15
};

const vector<string> scalar_register_names_32={
    "ESP" , "EAX" , "EDX" , "ECX" ,
    "EBX" , "EBP" , "ESI" , "EDI" ,
    "R8D" , "R9D" , "R10D", "R11D",
    "R12D", "R13D", "R14D", "R15D"
};

const vector<string> scalar_register_names_16={
    "SP"  , "AX"  , "DX"  , "CX"  ,
    "BX"  , "BP"  , "SI"  , "DI"  ,
    "R8W" , "R9W" , "R10W", "R11W",
    "R12W", "R13W", "R14W", "R15W"
};

const vector<string> scalar_register_names_8={
    "SPL" , "AL"  , "DL"  , "CL"  ,
    "BL"  , "BPL" , "SIL" , "DIL" ,
    "R8B" , "R9B" , "R10B", "R11B",
    "R12B", "R13B", "R14B", "R15B"
};

string to_hex(int128 i) {
    int128 i_abs=(i<0)? -i : i;
    assert(i_abs>=0);
    assert(uint64(i_abs)==i_abs);

    ostringstream ss;
    ss << ((i<0)? "-" : "") << "0x" << hex << uint64(i_abs);
    return ss.str();
}

void str_impl(vector<string>& out) {}

template<class type_a, class... types> void str_impl(
    vector<string>& out, const type_a& a, const types&... targs
) {
    out.push_back(to_string(a));
    str_impl(out, targs...);
}

template<class... types> string str(const string& t, const types&... targs) {
    vector<string> data;
    str_impl(data, targs...);

    string res;
    int next=0;
    for (char c : t) {
        if (c=='#') {
            res+=data.at(next);
            ++next;
        } else {
            res+=c;
        }
    }
    assert(next==data.size());

    return res;
}

struct expand_macros_recording {
    int start_pos=-1;
    int end_pos=-1;

    ~expand_macros_recording() {
        assert((start_pos==-1 && end_pos==-1) || (start_pos!=-1 && end_pos!=-1));
    }
};

struct expand_macros {
    struct scope_data {
        string scope_name;
        map<string, string> name_to_value;
        bool is_public=false;
    };

    vector<scope_data> scopes;
    map<string, set<pair<int, string>>> value_to_name; //int is scope

    vector<vector<string>> res_text; //first entry is tag

    int next_label_id=0;
    int next_error_label_id=1; //can't be 0 since the id is used as the return code
    int next_output_error_label_id=1;

    int num_active_recordings=0;

    vector<string> tag_stack;
    bool output_tags=false;

    void begin_recording(expand_macros_recording& res) {
        assert(res.start_pos==-1 && res.end_pos==-1);
        res.start_pos=res_text.size();
        ++num_active_recordings;
    }

    vector<vector<string>> end_recording(expand_macros_recording& res) {
        assert(res.start_pos!=-1 && res.end_pos==-1);
        res.end_pos=res_text.size();
        --num_active_recordings;

        vector<vector<string>> c_text;
        for (int x=res.start_pos;x<res.end_pos;++x) {
            c_text.push_back(res_text.at(x));
        }
        return c_text;
    }

    void append_recording(vector<vector<string>> c_text) {
        for (auto& c : c_text) {
            res_text.push_back(c);
        }
    }

    string alloc_label() {
        assert(num_active_recordings==0);
        string res = "_label_" + to_string(next_label_id);
        ++next_label_id;
        return res;
    }

    string alloc_error_label() {
        assert(num_active_recordings==0);
        string res = "label_error_" + to_string(next_error_label_id);
        ++next_error_label_id;
        return res;
    }

    void begin_scope(string name, bool is_public=false) {
        scopes.emplace_back(scope_data());
        scopes.back().scope_name=name;
        scopes.back().is_public=is_public;
    }

    void end_scope() {
        assert(!scopes.empty());
        for (pair<const string, string>& n : scopes.back().name_to_value) {
            bool erase_res=value_to_name.at(n.second).erase(make_pair(scopes.size()-1, n.first));
            assert(erase_res);
        }
        scopes.pop_back();
    }

    void bind_impl(string name, string value) {
        assert(!scopes.empty());

        bool emplace_res_1=scopes.back().name_to_value.emplace(name, value).second;
        assert(emplace_res_1);

        bool emplace_res_2=value_to_name[value].emplace(scopes.size()-1, name).second;
        assert(emplace_res_2);
    }

    string lookup_value(string name) {
        for (int x=scopes.size()-1;x>=0;--x) {
            if (x!=scopes.size()-1 && !scopes[x].is_public) {
                continue;
            }

            auto i=scopes[x].name_to_value.find(name);
            if (i!=scopes[x].name_to_value.end()) {
                return i->second;
            }
        }

        assert(false);
        return "";
    }

    string describe_scope() {
        string res;
        for (auto& c : scopes) {
            if (!res.empty()) {
                res+="/";
            }
            res+=c.scope_name;
        }
        return res;
    }

    string describe_name(string name) {
        string value=lookup_value(name);

        set<pair<int, string>>& names=value_to_name.at(value);

        string res;
        res+=name;
        res+="=";
        res+=value;

        if (names.size()>=2) {
            res+="(";
            bool first=true;
            for (auto& c : names) {
                if (!first) {
                    res+=",";
                }
                if (c.second!=name) {
                    res+=c.second;
                    first=false;
                }
            }
            res+=")";
        }

        return res;
    }

    pair<string, vector<string>> expand(string s) {
        string res;
        vector<string> res_names;
        string buffer;
        bool in_name=false;

        s+='\0';
        for (char c : s) {
            if (in_name) {
                if ((c>='0' && c<='9') || (c>='A' && c<='Z') || (c>='a' && c<='z') || c=='_') {
                    buffer+=c;
                } else {
                    in_name=false;
                    res+=lookup_value(buffer);
                    res_names.push_back(buffer);
                    buffer.clear();
                }
            }

            if (!in_name) {
                if (c=='`') {
                    in_name=true;
                } else {
                    if (c!='\0') {
                        res+=c;
                    }
                }
            }
        }

        return make_pair(res, res_names);
    }

    void append(string s, int line, string file, string func) {
        bool add_comment=true;

        assert(!s.empty());

        auto r=expand(s);

        res_text.emplace_back();
        res_text.back().push_back((tag_stack.empty())? "" : tag_stack.back());
        res_text.back().push_back(r.first);

        if (add_comment) {
            res_text.back().push_back( " # " + scopes.back().scope_name + ":" + to_string(line) + "    " );
            res_text.back().push_back(s);
        }
    }

    template<class type> typename type::bindable bind(const type& a, string n) {
        a.bind_impl(*this, n);
    }

    template<class type> struct void_box {
        typedef void value;
    };

    template<class type> typename void_box<typename type::value_type>::value bind(
        const type& a, string n
    ) {
        int x=0;
        for (const auto& c : a) {
            bind(c, n + "_" + to_string(x));
            ++x;
        }
    }

    string format_res_text() {
        string res;
        vector<int> sizes;

        int next_line=1;
        for (vector<string>& c : res_text) {
            string c_tag=c.at(0);
            if (output_tags && !c_tag.empty()) {
                c_tag = "_" + c_tag;
            }
            c.at(1)=str( "Xx_##: ", next_line, c_tag ) + c.at(1);
            ++next_line;


            for (int x=1;x<c.size();++x) {
                while (sizes.size()<=x) {
                    sizes.push_back(0);
                }
                sizes[x]=max(sizes[x], int(c[x].size()));
            }
        }

        sizes.at(1)=comment_asm_line_size;

        for (vector<string>& c : res_text) {
            for (int x=1;x<c.size();++x) {
                res+=c[x];
                if (x!=c.size()-1) {
                    for (int y=c[x].size();y<sizes.at(x);++y) {
                        res+= " " ;
                    }
                }
            }
            res+= "\n" ;
        }

        return res;
    }
};

struct expand_macros_tag {
    expand_macros& m;
    expand_macros_tag(expand_macros& t_m, string name) : m(t_m) {
        m.tag_stack.push_back(name);
    }
    ~expand_macros_tag() {
        m.tag_stack.pop_back();
    }
};

struct expand_macros_scope {
    expand_macros& m;

    expand_macros_scope(expand_macros& t_m, string name, bool is_public=false) : m(t_m) {
        m.begin_scope(name, is_public);
    }

    ~expand_macros_scope() {
        m.end_scope();
    }
};

#define EXPAND_MACROS_SCOPE expand_macros_scope c_scope(m, __func__)
#define EXPAND_MACROS_SCOPE_PUBLIC expand_macros_scope c_scope(m, __func__, true)

struct reg_scalar {
    static const bool is_spill=false;

    int value=-1;

    reg_scalar() {}
    explicit reg_scalar(int i) : value(i) {}

    string name(int num_bits=64) const {
        assert(value>=0);

        const vector<string>* names=nullptr;
        if (num_bits==64) {
            names=&scalar_register_names_64;
        } else
        if (num_bits==32) {
            names=&scalar_register_names_32;
        } else
        if (num_bits==16) {
            names=&scalar_register_names_16;
        } else {
            assert(num_bits==8);
            names=&scalar_register_names_8;
        }

        if (value<names->size()) {
            return names->at(value);
        } else {
            return str( "PSEUDO_#_#", value, num_bits );
        }
    }

    typedef void bindable;
    void bind_impl(expand_macros& m, string n) const {
        m.bind_impl(n, name(64));
        m.bind_impl(n + "_32", name(32));
        m.bind_impl(n + "_16", name(16));
        m.bind_impl(n + "_8", name(8));
    }
};

const reg_scalar reg_rsp=reg_scalar(0);
const reg_scalar reg_rax=reg_scalar(1);
const reg_scalar reg_rdx=reg_scalar(2);
const reg_scalar reg_rcx=reg_scalar(3);
const reg_scalar reg_rbx=reg_scalar(4);
const reg_scalar reg_rbp=reg_scalar(5);
const reg_scalar reg_rsi=reg_scalar(6);
const reg_scalar reg_rdi=reg_scalar(7);
const reg_scalar reg_r8=reg_scalar(8);
const reg_scalar reg_r9=reg_scalar(9);
const reg_scalar reg_r10=reg_scalar(10);
const reg_scalar reg_r11=reg_scalar(11);
const reg_scalar reg_r12=reg_scalar(12);
const reg_scalar reg_r13=reg_scalar(13);
const reg_scalar reg_r14=reg_scalar(14);
const reg_scalar reg_r15=reg_scalar(15);

struct reg_vector {
    static const bool is_spill=false;

    int value=-1;

    reg_vector() {}
    explicit reg_vector(int i) : value(i) {}

    string name(int num_bits=512) const {
        assert(value>=0);

        string prefix;
        if (num_bits==512) {
            prefix = "Z";
        } else
        if (num_bits==256) {
            prefix = "Y";
        } else {
            assert(num_bits==128);
            prefix = "X";
        }

        if (value>=32 || (!enable_all_instructions && (value>=16 || num_bits!=128))) {
            prefix = "PSEUDO_" + prefix;
        }

        return str( "#MM#", prefix, value );
    }

    typedef void bindable;
    void bind_impl(expand_macros& m, string n) const {
        m.bind_impl(n, name(128));
        m.bind_impl(n + "_512", name(512));
        m.bind_impl(n + "_256", name(256));
        m.bind_impl(n + "_128", name(128));
    }
};

struct reg_spill {
    static const bool is_spill=true;

    int value=-1; //byte offset
    int size=-1;
    int alignment=-1; //power of 2, up to 64

    reg_spill() {}
    reg_spill(int t_value, int t_size, int t_alignment) : value(t_value), size(t_size), alignment(t_alignment) {}

    int get_rsp_offset() const {
        return value-spill_bytes;
    }

    //this is negative
    uint64 get_rsp_offset_uint64() const {
        return uint64(value-spill_bytes);
    }

    string name() const {
        assert(value>=0 && size>=1 && alignment>=1);
        assert(value%alignment==0);
        assert(value+size<=spill_bytes);

        return str( "[RSP+#]", to_hex(value-spill_bytes) );
    }

    typedef void bindable;
    void bind_impl(expand_macros& m, string n) const {
        m.bind_impl(n, name());
        m.bind_impl(n + "_rsp_offset", to_hex(value-spill_bytes));
    }

    reg_spill operator+(int byte_offset) const {
        reg_spill res=*this;
        res.value+=byte_offset;
        res.size-=byte_offset;
        res.alignment=1;
        return res;
    }
};

struct reg_alloc {
    vector<int> order_to_scalar;
    vector<int> scalar_to_order;

    set<int> scalars;
    set<int> vectors;
    vector<bool> spills;

    reg_alloc() {}

    void add(reg_scalar s) {
        bool insert_res=scalars.insert(scalar_to_order.at(s.value)).second;
        assert(insert_res);
    }

    void init() {
        const int num=32; //defines how many pseudo-registers to have

        order_to_scalar.resize(num, -1);
        scalar_to_order.resize(num, -1);

        int next_order=0;
        auto add_scalar=[&](reg_scalar scalar_reg) {
            int scalar=scalar_reg.value;

            int order=next_order;
            ++next_order;

            assert(order_to_scalar.at(order)==-1);
            order_to_scalar.at(order)=scalar;

            assert(scalar_to_order.at(scalar)==-1);
            scalar_to_order.at(scalar)=order;

            add(reg_scalar(scalar));
        };

        add_scalar(reg_rbx);
        add_scalar(reg_rbp);
        add_scalar(reg_rsi);
        add_scalar(reg_rdi);
        add_scalar(reg_r8);
        add_scalar(reg_r9);
        add_scalar(reg_r10);
        add_scalar(reg_r11);
        add_scalar(reg_r12);
        add_scalar(reg_r13);
        add_scalar(reg_r14);
        add_scalar(reg_r15);

        add_scalar(reg_rcx);
        add_scalar(reg_rdx);
        add_scalar(reg_rax);

        for (int x=16;x<num;++x) {
            reg_scalar r;
            r.value=x;
            add_scalar(r);
        }

        for (int x=0;x<num;++x) {
            vectors.insert(x);
        }
        for (int x=0;x<spill_bytes;++x) {
            spills.push_back(true);
        }
    }

    reg_scalar get_scalar(reg_scalar t_reg=reg_scalar()) {
        assert(!scalars.empty());

        int res=(t_reg.value==-1)? *scalars.begin() : scalar_to_order.at(t_reg.value);
        bool erase_res=scalars.erase(res);
        assert(erase_res);

        return reg_scalar(order_to_scalar.at(res));
    }

    reg_vector get_vector() {
        assert(!vectors.empty());

        int res=*vectors.begin();
        bool erase_res=vectors.erase(res);
        assert(erase_res);
        return reg_vector(res);
    }

    reg_spill get_spill(int size=8, int alignment=-1) {
        if (alignment==-1) {
            alignment=size;
        }

        assert(alignment==1 || alignment==2 || alignment==4 || alignment==8 || alignment==16 || alignment==32 || alignment==64);

        for (int x=0;x<spills.size();++x) {
            if (x%alignment!=0) {
                continue;
            }

            bool valid=true;

            for (int y=0;y<size;++y) {
                if (x+y>=spills.size() || !spills[x+y]) {
                    valid=false;
                    break;
                }
            }

            if (valid) {
                for (int y=0;y<size;++y) {
                    spills.at(x+y)=false;
                }

                reg_spill res;
                res.value=x;
                res.size=size;
                res.alignment=alignment;
                return res;
            }
        }

        assert(false);
        return reg_spill();
    }

    reg_scalar bind_scalar(expand_macros& m, string name, reg_scalar t_reg=reg_scalar()) {
        reg_scalar res=get_scalar(t_reg);
        m.bind(res, name);
        return res;
    }

    reg_vector bind_vector(expand_macros& m, string name) {
        reg_vector res=get_vector();
        m.bind(res, name);
        return res;
    }

    reg_spill bind_spill(expand_macros& m, string name, int size=8, int alignment=-1) {
        reg_spill res=get_spill(size, alignment);
        m.bind(res, name);
        return res;
    }
};

namespace asm_code {
    expand_macros m;
    #define APPEND_M(data) m.append(data, __LINE__, __FILE__, __func__)
}