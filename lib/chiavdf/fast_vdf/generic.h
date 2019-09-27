#include "generic_macros.h"
#include <fstream>

#ifndef ILYA_SHARED_HEADER_GENERIC
#define ILYA_SHARED_HEADER_GENERIC

namespace generic {
using namespace std;


template<class type_a> void print_impl(ostream& out, const type_a& a) {}

template<class type_b> void print_impl(ostream& out, const char* a, const type_b& b) {
    out << " " << b;
}

template<class type_a, class type_b> void print_impl(ostream& out, const type_a& a, const type_b& b) {
    out << ", " << b;
}

template<class type_a, class type_b, class... types> void print_impl(ostream& out, const type_a& a, const type_b& b, const types&... targs) {
    print_impl(out, a, b);
    print_impl(out, b, targs...);
}

template<class type_a, class... types> void print_to(ostream& out, const type_a& a, const types&... targs) {
    out << a;
    print_impl(out, a, targs...);
    out << "\n";
}

template<class type_a, class... types> void print(const type_a& a, const types&... targs) {
    print_to(cerr, a, targs...);
}

//if buffer is not null, will return an empty string
string getstream(istream& targ, int block_size=10, string* buffer=nullptr) {
    string new_buffer;
    string& res=(buffer!=nullptr)? *buffer : new_buffer;
    res.clear();
    
    while(1) {
        res.resize(res.size()+block_size);
        targ.read(&(res[res.size()-block_size]), block_size);
        int c=targ.gcount();
        if (c!=block_size) {
            res.resize(res.size()-block_size+c);
            assert(targ.eof());
            return new_buffer;
        }
    }
}

string getfile(const string& name, bool binary=0, int block_size=1024) {
    ifstream in(name, binary? ios::binary|ios_base::in : ios_base::in);
    assert(in.good());
    return getstream(in, block_size);
}

struct less_ptr {
    template<class ptr_type> bool operator()(ptr_type a, ptr_type b) {
        return *a<*b;
    }
};

template<class type> type instance_of();

template<class type> std::string to_string(std::ostringstream& s, const type& targ) {
    s.clear();
    s.str("");
    s << targ;
    return s.str();
}
template<class type> std::string to_string(const type& targ) {
    static std::ostringstream s;
    return to_string(s, targ);
}

template<class type> pair<type, bool> checked_from_string(std::istringstream& s, const std::string& targ) {
    s.clear();
    s.str(targ);
    type res;
    s >> res;
    return make_pair(res, s.eof() && !s.fail());
}
template<class type> type from_string(std::istringstream& s, const std::string& targ) {
    return checked_from_string<type>(s, targ).first;
}
template<class type> type from_string(const std::string& targ) {
    static std::istringstream s;
    return from_string<type>(s, targ);
}
template<class type> pair<type, bool> checked_from_string(const std::string& targ) {
    static std::istringstream s;
    return checked_from_string<type>(s, targ);
}

template<class type> type assert_from_string(const std::string& targ) {
    auto res=checked_from_string<type>(targ);
    assert(res.second);
    return res.first;
}

template<class type, class... types> unique_ptr<type> make_unique_ptr(types&&... targs) {
    return unique_ptr<type>(new type(forward<types>(targs)...));
}

template<class type, int size> int array_size(type(&)[size]) {
    return size;
}

template<class type> std::ostream& print_as_number(std::ostream& out, const type& targ) { out << targ; return out; }
template<> std::ostream& print_as_number<unsigned char>(std::ostream& out, const unsigned char& targ) { out << int(targ); return out; }
template<> std::ostream& print_as_number<signed char>(std::ostream& out, const signed char& targ) { out << int(targ); return out; }
template<> std::ostream& print_as_number<char>(std::ostream& out, const char& targ) { out << int(targ); return out; }

//

template<bool n, class type> struct only_if {};
template<class type> struct only_if<1, type> { typedef type good; };
template<bool n> typename only_if<n, void>::good assert_true() {}

template<class a, class b, class type> struct only_if_same_types {};
template<class a, class type> struct only_if_same_types<a, a, type> { typedef type good; };
template<class a, class b> typename only_if_same_types<a, b, void>::good assert_same_types() {}

template<class a, class b, class type> struct only_if_not_same_types { typedef type good; };
template<class a, class type> struct only_if_not_same_types<a, a, type> {};
template<class a, class b> typename only_if_not_same_types<a, b, void>::good assert_not_same_types() {}

template<int n> struct static_abs { static const int res=n<0? -n : n; };
template<int n> struct static_sgn { static const int res=n<0? -1 : (n>0? 1 : 0); };
template<int a, int b> struct static_max { static const int res=a>b? a : b; };
template<int a, int b> struct static_min { static const int res=a<b? a : b; };

template<class type> class wrap_type { typedef type res; };

//

template<class type_a, class type_b> class union_pair {
    template<class, class> friend class union_pair;
    static const size_t size_bytes=static_max<sizeof(type_a), sizeof(type_b)>::res;
    static const size_t alignment_bytes=static_max<alignof(type_a), alignof(type_b)>::res;
    typename aligned_storage<size_bytes, alignment_bytes>::type buffer;
    bool t_is_first;
    
    public:
    union_pair() : t_is_first(1) { new(&buffer) type_a(); }
    union_pair(int, int) : t_is_first(0) { new(&buffer) type_b(); }
    union_pair(const type_a& targ) : t_is_first(1) { new(&buffer) type_a(targ); }
    union_pair(const type_b& targ) : t_is_first(0) { new(&buffer) type_b(targ); }
    union_pair(type_a&& targ) : t_is_first(1) { new(&buffer) type_a(move(targ)); }
    union_pair(type_b&& targ) : t_is_first(0) { new(&buffer) type_b(move(targ)); }
    union_pair(const union_pair& targ) : t_is_first(targ.t_is_first) {
        if (t_is_first) new(&buffer) type_a(targ.first()); else new(&buffer) type_b(targ.second());
    }
    union_pair(const union_pair<type_b, type_a>& targ) : t_is_first(!targ.t_is_first) {
        if (t_is_first) new(&buffer) type_a(targ.second()); else new(&buffer) type_b(targ.first());
    }
    union_pair(union_pair&& targ) : t_is_first(targ.t_is_first) {
        if (t_is_first) new(&buffer) type_a(move(targ.first())); else new(&buffer) type_b(move(targ.second()));
    }
    union_pair(union_pair<type_b, type_a>&& targ) : t_is_first(!targ.t_is_first) {
        if (t_is_first) new(&buffer) type_a(move(targ.second())); else new(&buffer) type_b(move(targ.first()));
    }
    
    union_pair& operator=(const type_a& targ) {
        if (is_first()) first()=targ; else set_first(targ);
        return *this;
    }
    union_pair& operator=(const type_b& targ) {
        if (is_second()) second()=targ; else set_second(targ);
        return *this;
    }
    
    union_pair& operator=(type_a&& targ) {
        if (is_first()) first()=move(targ); else set_first(move(targ));
        return *this;
    }
    union_pair& operator=(type_b&& targ) {
        if (is_second()) second()=move(targ); else set_second(move(targ));
        return *this;
    }
    
    union_pair& operator=(const union_pair& targ) {
        if (targ.is_first()) {
            return *this=targ.first();
        } else {
            return *this=targ.second();
        }
    }
    union_pair& operator=(const union_pair<type_b, type_a>& targ) {
        if (targ.is_first()) {
            return *this=targ.first();
        } else {
            return *this=targ.second();
        }
    }
    
    union_pair& operator=(union_pair&& targ) {
        if (targ.is_first()) {
            return *this=move(targ.first());
        } else {
            return *this=move(targ.second());
        }
    }
    union_pair& operator=(union_pair<type_b, type_a>&& targ) {
        if (targ.is_first()) {
            return *this=move(targ.first());
        } else {
            return *this=move(targ.second());
        }
    }
    
    typedef type_a first_type;
    typedef type_b second_type;
    
    bool is_first() const { return t_is_first; }
    bool is_second() const { return !t_is_first; }
    //
    type_a& first() { return *reinterpret_cast<type_a*>(&buffer); }
    const type_a& first() const { return *reinterpret_cast<const type_a*>(&buffer); }
    type_b& second() { return *reinterpret_cast<type_b*>(&buffer); }
    const type_b& second() const { return *reinterpret_cast<const type_b*>(&buffer); }
    //
    template<class... types> type_a& set_first(types&&... targs) {
        if (!t_is_first) {
            second().~type_b();
            t_is_first=1;
        } else {
            first().~type_a();
        }
        return *(new(&buffer) type_a(forward<types>(targs)...));
    }
    template<class... types> type_b& set_second(types&&... targs) {
        if (t_is_first) {
            first().~type_a();
            t_is_first=0;
        } else {
            second().~type_b();
        }
        return *(new(&buffer) type_b(forward<types>(targs)...));
    }
    
    ~union_pair() {
        if (t_is_first) first().~type_a(); else second().~type_b();
    }
};

}

#endif
