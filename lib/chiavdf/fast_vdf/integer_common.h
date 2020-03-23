#ifndef INTEGER_COMMON_H
#define INTEGER_COMMON_H

//note: gmp already has c++ bindings so could have just used those. oh well

//const bool output_stats=false;
/*struct generic_stats {
    vector<int> entries;

    void add(int i) {
        if (!output_stats) {
            return;
        }

        entries.push_back(i);
    }

    void output(string name) {
        if (!output_stats) {
            return;
        }

        sort(entries.begin(), entries.end());
        vector<double> percentiles={0, 0.01, 0.1, 1, 10, 25, 50, 75, 90, 99, 99.9, 99.99, 100};

        print( "::", name );
        print( "    num =", entries.size() );

        if (entries.empty()) {
            return;
        }

        for (double c : percentiles) {
            int i=(c/100)*entries.size();
            if (i<0) {
                i=0;
            }
            if (i>=entries.size()) {
                i=entries.size()-1;
            }

            print( "    ", c, "    ->    ", entries.at(i) );
        }

        double total=0;
        for (int c : entries) {
            total+=c;
        }

        print( "    ", "avg", "    ->    ", total/double(entries.size()) );
    }
};*/

/*struct track_cycles {
    generic_stats& stats;
    uint64 start_time;
    bool is_aborted=false;

    track_cycles(generic_stats& t_stats) : stats(t_stats) {
        if (!enable_track_cycles) {
            return;
        }

        start_time=__rdtsc();
    }

    void abort() {
        if (!enable_track_cycles) {
            return;
        }

        is_aborted=true;
    }

    ~track_cycles() {
        if (!enable_track_cycles) {
            return;
        }

        if (is_aborted) {
            return;
        }

        uint64 end_time=__rdtsc();
        uint64 delta=end_time-start_time;
        int delta_int=delta;
        if (delta_int==delta) {
            stats.add(delta_int);
        } else {
            stats.add(INT_MAX);
        }
    }
};*/

struct track_max_type {
    map<pair<int, string>, pair<int, bool>> data;

    void add(int line, string name, int value, bool negative) {
        auto& v=data[make_pair(line, name)];
        v.first=max(v.first, value);
        v.second|=negative;
    }

    void output(int basis_bits) {
        print( "== track max ==" );
        for (auto c : data) {
            print(c.first.second, double(c.second.first)/basis_bits, c.second.second);
        }
    }
};
track_max_type track_max;
//#define TRACK_MAX(data) track_max.add(#data " {" __func__ ":" "__LINE__" ")", (data).num_bits())
#define TRACK_MAX(data) track_max.add(__LINE__, #data, (data).num_bits(), (data)<0)

//typedef __mpz_struct mpz_t[1];
typedef __mpz_struct mpz_struct;

int mpz_num_bits_upper_bound(mpz_struct* v) {
    return mpz_size(v)*sizeof(mp_limb_t)*8;
}

static bool allow_integer_constructor=false; //don't want static integers because they use the wrong allocator

struct integer {
    mpz_struct impl[1];

    ~integer() {
        mpz_clear(impl);
    }

    integer() {
        assert(allow_integer_constructor);
        mpz_init(impl);
    }

    integer(const integer& t) {
        mpz_init(impl);
        mpz_set(impl, t.impl);
    }

    integer(integer&& t) {
        mpz_init(impl);
        mpz_swap(impl, t.impl);
    }

    explicit integer(int64 i) {
        mpz_init(impl);
        mpz_set_si(impl, i);
    }

    explicit integer(const string& s) {
        mpz_init(impl);
        int res=mpz_set_str(impl, s.c_str(), 0);
        assert(res==0);
    }

    //lsb first
    explicit integer(const vector<uint64>& data) {
        mpz_init(impl);
        mpz_import(impl, data.size(), -1, 8, 0, 0, &data[0]);
    }

    //lsb first
    vector<uint64> to_vector() const {
        vector<uint64> res;
        res.resize(mpz_sizeinbase(impl, 2)/64 + 1, 0);

        size_t count;
        mpz_export(&res[0], &count, -1, 8, 0, 0, impl);
        res.resize(count);

        return res;
    }

    integer& operator=(const integer& t) {
        mpz_set(impl, t.impl);
        return *this;
    }

    integer& operator=(integer&& t) {
        mpz_swap(impl, t.impl);
        return *this;
    }

    integer& operator=(int64 i) {
        mpz_set_si(impl, i);
        return *this;
    }

    integer& operator=(const string& s) {
        int res=mpz_set_str(impl, s.c_str(), 0);
        assert(res==0);
        return *this;
    }

    void set_bit(int index, bool value) {
        if (value) {
            mpz_setbit(impl, index);
        } else {
            mpz_clrbit(impl, index);
        }
    }

    bool get_bit(int index) {
        return mpz_tstbit(impl, index);
    }

    USED string to_string() const {
        char* res_char=mpz_get_str(nullptr, 16, impl);
        string res_string="0x";
        res_string+=res_char;

        if (res_string.substr(0, 3)=="0x-") {
            res_string.at(0)='-';
            res_string.at(1)='0';
            res_string.at(2)='x';
        }

        free(res_char);
        return res_string;
    }

    string to_string_dec() const {
        char* res_char=mpz_get_str(nullptr, 10, impl);
        string res_string=res_char;
        free(res_char);
        return res_string;
    }

    integer& operator+=(const integer& t) {
        mpz_add(impl, impl, t.impl);
        return *this;
    }

    integer operator+(const integer& t) const {
        integer res;
        mpz_add(res.impl, impl, t.impl);
        return res;
    }

    integer& operator-=(const integer& t) {
        mpz_sub(impl, impl, t.impl);
        return *this;
    }

    integer operator-(const integer& t) const {
        integer res;
        mpz_sub(res.impl, impl, t.impl);
        return res;
    }

    integer& operator*=(const integer& t) {
        mpz_mul(impl, impl, t.impl);
        return *this;
    }

    integer operator*(const integer& t) const {
        integer res;
        mpz_mul(res.impl, impl, t.impl);
        return res;
    }

    integer& operator<<=(int i) {
        assert(i>=0);
        mpz_mul_2exp(impl, impl, i);
        return *this;
    }

    integer operator<<(int i) const {
        assert(i>=0);
        integer res;
        mpz_mul_2exp(res.impl, impl, i);
        return res;
    }

    integer operator-() const {
        integer res;
        mpz_neg(res.impl, impl);
        return res;
    }

    integer& operator/=(const integer& t) {
        mpz_fdiv_q(impl, impl, t.impl);
        return *this;
    }

    integer operator/(const integer& t) const {
        integer res;
        mpz_fdiv_q(res.impl, impl, t.impl);
        return res;
    }

    integer& operator>>=(int i) {
        assert(i>=0);
        mpz_fdiv_q_2exp(impl, impl, i);
        return *this;
    }

    integer operator>>(int i) const {
        assert(i>=0);
        integer res;
        mpz_fdiv_q_2exp(res.impl, impl, i);
        return res;
    }

    //this is different from mpz_fdiv_r because it ignores the sign of t
    integer& operator%=(const integer& t) {
        mpz_mod(impl, impl, t.impl);
        return *this;
    }

    integer operator%(const integer& t) const {
        integer res;
        mpz_mod(res.impl, impl, t.impl);
        return res;
    }

    integer fdiv_r(const integer& t) const {
        integer res;
        mpz_fdiv_r(res.impl, impl, t.impl);
        return res;
    }

    bool prime() const {
        return mpz_probab_prime_p(impl, 50)!=0;
    }

    bool operator<(const integer& t) const {
        return mpz_cmp(impl, t.impl)<0;
    }

    bool operator<=(const integer& t) const {
        return mpz_cmp(impl, t.impl)<=0;
    }

    bool operator==(const integer& t) const {
        return mpz_cmp(impl, t.impl)==0;
    }

    bool operator>=(const integer& t) const {
        return mpz_cmp(impl, t.impl)>=0;
    }

    bool operator>(const integer& t) const {
        return mpz_cmp(impl, t.impl)>0;
    }

    bool operator!=(const integer& t) const {
        return mpz_cmp(impl, t.impl)!=0;
    }

    bool operator<(int i) const {
        return mpz_cmp_si(impl, i)<0;
    }

    bool operator<=(int i) const {
        return mpz_cmp_si(impl, i)<=0;
    }

    bool operator==(int i) const {
        return mpz_cmp_si(impl, i)==0;
    }

    bool operator>=(int i) const {
        return mpz_cmp_si(impl, i)>=0;
    }

    bool operator>(int i) const {
        return mpz_cmp_si(impl, i)>0;
    }

    bool operator!=(int i) const {
        return mpz_cmp_si(impl, i)!=0;
    }

    int num_bits() const {
        return mpz_sizeinbase(impl, 2);
    }
};

integer abs(const integer& t) {
    integer res;
    mpz_abs(res.impl, t.impl);
    return res;
}

integer root(const integer& t, int n) {
    integer res;
    mpz_root(res.impl, t.impl, n);
    return res;
}

struct gcd_res {
    integer gcd;
    integer s;
    integer t;
};

//a*s + b*t = gcd ; gcd>=0
// abs(s) < abs(b) / (2 gcd)
// abs(t) < abs(a) / (2 gcd)
//(except if |s|<=1 or |t|<=1)
gcd_res gcd(const integer& a, const integer& b) {
    gcd_res res;

    mpz_gcdext(res.gcd.impl, res.s.impl, res.t.impl, a.impl, b.impl);

    return res;
}

integer rand_integer(int num_bits, int seed=-1) {
    thread_local gmp_randstate_t state;
    thread_local bool is_init=false;

    if (!is_init) {
        gmp_randinit_mt(state);
        gmp_randseed_ui(state, 0);
        is_init=true;
    }

    if (seed!=-1) {
        gmp_randseed_ui(state, seed);
    }

    integer res;
    assert(num_bits>=0);
    mpz_urandomb(res.impl, state, num_bits);
    return res;
}


USED string to_string(mpz_struct* t) {
    integer t_int;
    mpz_set(t_int.impl, t);
    return t_int.to_string();
}

#endif // INTEGER_COMMON_H
