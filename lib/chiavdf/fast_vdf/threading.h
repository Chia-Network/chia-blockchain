#include <boost/align/aligned_alloc.hpp>

//mp_limb_t is an unsigned integer
static_assert(sizeof(mp_limb_t)==8, "");

static_assert(sizeof(unsigned long int)==8, "");
static_assert(sizeof(long int)==8, "");

#ifdef ENABLE_TRACK_CYCLES
    const int track_cycles_array_size=track_cycles_max_num*track_cycles_num_buckets;

    thread_local int track_cycles_next_slot=0;
    thread_local array<uint64, track_cycles_array_size> track_cycles_cycle_counters;
    thread_local array<uint64, track_cycles_array_size> track_cycles_call_counters;
    thread_local array<const char*, track_cycles_max_num> track_cycles_names;

    void track_cycles_init() {
        thread_local bool is_init=false;
        if (!is_init) {
            //print( &track_cycles_names );

            //track_cycles_cycle_counters=new uint64[];
            //track_cycles_call_counters=new uint64[track_cycles_max_num*track_cycles_num_buckets];
            //track_cycles_names=new const char*[track_cycles_max_num];

            for (int x=0;x<track_cycles_array_size;++x) {
                track_cycles_cycle_counters.at(x)=0;
                track_cycles_call_counters.at(x)=0;
            }

            for (int x=0;x<track_cycles_max_num;++x) {
                track_cycles_names.at(x)=nullptr;
            }
            is_init=true;
        }
    }

    void track_cycles_output_stats() {
        track_cycles_init();

        //print( &track_cycles_names );

        for (int x=0;x<track_cycles_next_slot;++x) {
            double total_calls=0;
            for (int y=0;y<track_cycles_num_buckets;++y) {
                total_calls+=track_cycles_call_counters.at(x*track_cycles_num_buckets + y);
            }

            if (total_calls==0) {
                continue;
            }

            print( "" );
            print( track_cycles_names.at(x), ":" );

            for (int y=0;y<track_cycles_num_buckets;++y) {
                double cycles=track_cycles_cycle_counters.at(x*track_cycles_num_buckets + y);
                double calls=track_cycles_call_counters.at(x*track_cycles_num_buckets + y);

                if (calls==0) {
                    continue;
                }

                print(str( "#%: #", int(calls/total_calls*100), int(cycles/calls) ));
            }
        }
    }

    struct track_cycles_impl {
        int slot=-1;
        uint64 start_time=0;
        bool is_aborted=false;

        static uint64 get_time() {
            // Returns the time in EDX:EAX.
            uint64 high;
            uint64 low;
            asm volatile(
                "lfence\n\t"
                "sfence\n\t"
                "rdtsc\n\t"
                "sfence\n\t"
                "lfence\n\t"
            : "=a"(low), "=d"(high) :: "memory");

            return (high<<32) | low;
        }

        track_cycles_impl(int t_slot) {
            slot=t_slot;
            assert(slot>=0 && slot<track_cycles_max_num);

            start_time=get_time();
        }

        void abort() {
            is_aborted=true;
        }

        ~track_cycles_impl() {
            uint64 end_time=get_time();

            if (is_aborted) {
                return;
            }

            uint64 delta=end_time-start_time;

            if (delta==0) {
                return;
            }

            int num_bits=64-__builtin_clzll(delta);
            if (num_bits>=track_cycles_num_buckets) {
                return;
            }

            assert(num_bits>=0 && num_bits<track_cycles_num_buckets);
            assert(slot>=0 && slot<track_cycles_max_num);

            int index=slot*track_cycles_num_buckets + num_bits;
            assert(index>=0 && index<track_cycles_max_num*track_cycles_num_buckets);

            track_cycles_cycle_counters.at(index)+=delta;
            ++track_cycles_call_counters.at(index);
        }
    };

    #define TO_STRING_IMPL(x) #x

    #define TO_STRING(x) TO_STRING_IMPL(x)

    #define TRACK_CYCLES \
        track_cycles_init();\
        thread_local int track_cycles_c_slot=-1;\
        if (track_cycles_c_slot==-1) {\
            track_cycles_c_slot=track_cycles_next_slot;\
            ++track_cycles_next_slot;\
            \
            track_cycles_names.at(track_cycles_c_slot)=__FILE__ ":" TO_STRING(__LINE__);\
        }\
        track_cycles_impl c_track_cycles_impl(track_cycles_c_slot);
    //

    #define TRACK_CYCLES_ABORT c_track_cycles_impl.abort();

    #define TRACK_CYCLES_OUTPUT_STATS track_cycles_output_stats();
#else
    #define TRACK_CYCLES
    #define TRACK_CYCLES_ABORT
    #define TRACK_CYCLES_OUTPUT_STATS
#endif

//use realloc or free to free the memory
void* alloc_cache_line(size_t bytes) {
    //round up to the next multiple of 64
    size_t aligned_bytes=((bytes+63)>>6)<<6;

    void* res=boost::alignment::aligned_alloc(64, aligned_bytes); // aligned_alloc(64, aligned_bytes);
    assert((uint64(res)&63)==0); //must be aligned for correctness
    return res;
}

void* mp_alloc_func(size_t new_bytes) {
    void* res=alloc_cache_line(new_bytes);
    assert((uint64(res)&63)==0); //all memory used by gmp must be cache line aligned
    return res;
}

void mp_free_func(void* old_ptr, size_t old_bytes) {
    //either mp_alloc_func allocated old_ptr and it is 64-aligned, or it points to data in mpz and its address equals 16 modulo 64
    assert((uint64(old_ptr)&63)==0 || (uint64(old_ptr)&63)==16);

    if ((uint64(old_ptr)&63)==0) {
        //mp_alloc_func allocated this, so it can be freed with std::free
        boost::alignment::aligned_free(old_ptr); //free(old_ptr);
    } else {
        //this is part of the mpz struct defined below. it can't be freed, so do nothing
    }
}

void* mp_realloc_func(void* old_ptr, size_t old_bytes, size_t new_bytes) {
    void* res=mp_alloc_func(new_bytes);

    memcpy(res, old_ptr, (old_bytes<new_bytes)? old_bytes : new_bytes);

    mp_free_func(old_ptr, old_bytes);

    return res;
}

//must call this before calling any gmp functions
//(the mpz class constructor does not call any gmp functions)
void init_gmp() {
    mp_set_memory_functions(mp_alloc_func, mp_realloc_func, mp_free_func);
}

struct mpz_base {
    //16 bytes
    //int mpz._mp_alloc: number of limbs allocated
    //int mpz._mp_size: abs(_mp_size) is number of limbs in use; 0 if the integer is zero. it is negated if the integer is negative
    //mp_limb_t* mpz._mp_d: pointer to limbs
    //do not call mpz_swap on this. mpz_swap can be called on other gmp integers
    mpz_struct c_mpz;

    operator mpz_struct*() { return &c_mpz; }
    operator const mpz_struct*() const { return &c_mpz; }

    mpz_struct* _() { return &c_mpz; }
    const mpz_struct* _() const { return &c_mpz; }
};

//gmp can dynamically reallocate this
//the number of cache lines used is (padded_size+2)/8 rounded up
//1 cache line :  6 limbs
//2 cache lines: 14 limbs
//3 cache lines: 22 limbs
//4 cache lines: 30 limbs
//5 cache lines: 38 limbs
template<int d_expected_size, int d_padded_size> struct alignas(64) mpz : public mpz_base {
    static const int expected_size=d_expected_size;
    static const int padded_size=d_padded_size;

    static_assert(expected_size>=1 && expected_size<=padded_size, "");

    uint64 data[padded_size]; //must not be cache line aligned

    bool was_reallocated() const {
        return c_mpz._mp_d!=data;
    }

    //can't call any mpz functions here because it is global
    mpz() {
        c_mpz._mp_size=0;
        c_mpz._mp_d=(mp_limb_t *)data;
        c_mpz._mp_alloc=padded_size;

        //this is supposed to be cache line aligned so that the next assert works
        assert((uint64(this)&63)==0);

        //mp_free_func uses this to decide whether to free or not
        assert((uint64(c_mpz._mp_d)&63)==16);
    }

    ~mpz() {
        if (is_vdf_test) {
            //don't want this to happen for performance reasons
            assert(!was_reallocated());
        }

        //if c_mpz.data wasn't reallocated, it has to point to this instance's data and not some other instance's data
        //if mpz_swap was used, this might be violated
        assert((uint64(c_mpz._mp_d)&63)==0 || c_mpz._mp_d==data);
        mpz_clear(&c_mpz);
    }

    mpz(const mpz& t)=delete;
    mpz(mpz&& t)=delete;

    mpz& operator=(const mpz_struct* t) {
        mpz_set(*this, t);
        return *this;
    }

    mpz& operator=(const mpz& t) {
        mpz_set(*this, t);
        return *this;
    }

    mpz& operator=(mpz&& t) {
        mpz_set(*this, t); //do not use mpz_swap
        return *this;
    }

    /*mpz& operator=(const mpz_base& t) {
        mpz_set(*this, t);
        return *this;
    }

    mpz& operator=(mpz_base&& t) {
        mpz_set(*this, t); //do not use mpz_swap
        return *this;
    }*/

    mpz& operator=(uint64 i) {
        mpz_set_ui(*this, i);
        return *this;
    }

    mpz& operator=(int64 i) {
        mpz_set_si(*this, i);
        return *this;
    }

    mpz& operator=(const string& s) {
        int res=mpz_set_str(*this, s.c_str(), 0);
        assert(res==0);
        return *this;
    }

    USED string to_string() const {
        char* res_char=mpz_get_str(nullptr, 16, *this);
        string res_string = "0x";
        res_string+=res_char;

        if (res_string.substr(0, 3) == "0x-") {
            res_string.at(0)='-';
            res_string.at(1)='0';
            res_string.at(2)='x';
        }

        free(res_char);
        return res_string;
    }

    USED string to_string_dec() const {
        char* res_char=mpz_get_str(nullptr, 10, *this);
        string res_string=res_char;
        free(res_char);
        return res_string;
    }

    //sets *this to a+b
    void set_add(const mpz_struct* a, const mpz_struct* b) {
        mpz_add(*this, a, b);
    }

    void set_add(const mpz_struct* a, uint64 b) {
        mpz_add_ui(*this, a, b);
    }

    mpz& operator+=(const mpz_struct* t) {
        set_add(*this, t);
        return *this;
    }

    mpz& operator+=(uint64 t) {
        set_add(*this, t);
        return *this;
    }

    void set_sub(const mpz_struct* a, const mpz_struct* b) {
        mpz_sub(*this, a, b);
    }

    void set_sub(const mpz_struct* a, uint64 b) {
        mpz_sub_ui(*this, a, b);
    }

    template<class mpz_b> void set_sub(uint64 a, const mpz_b& b) {
        mpz_ui_sub(*this, a, b);
    }

    mpz& operator-=(const mpz_struct* t) {
        set_sub(*this, t);
        return *this;
    }

    void set_mul(const mpz_struct* a, const mpz_struct* b) {
        mpz_mul(*this, a, b);
    }

    void set_mul(const mpz_struct* a, int64 b) {
        mpz_mul_si(*this, a, b);
    }

    void set_mul(const mpz_struct* a, uint64 b) {
        mpz_mul_ui(*this, a, b);
    }

    mpz& operator*=(const mpz_struct* t) {
        set_mul(*this, t);
        return *this;
    }

    mpz& operator*=(int64 t) {
        set_mul(*this, t);
        return *this;
    }

    mpz& operator*=(uint64 t) {
        set_mul(*this, t);
        return *this;
    }

    void set_left_shift(const mpz_struct* a, int i) {
        assert(i>=0);
        mpz_mul_2exp(*this, a, i);
    }

    mpz& operator<<=(int i) {
        set_left_shift(*this, i);
        return *this;
    }

    //*this+=a*b
    void set_add_mul(const mpz_struct* a, const mpz_struct* b) {
        mpz_addmul(*this, a, b);
    }

    void set_add_mul(const mpz_struct* a, uint64 b) {
        mpz_addmul_ui(*this, a, b);
    }

    //*this-=a*b
    void set_sub_mul(const mpz_struct* a, const mpz_struct* b) {
        mpz_submul(*this, a, b);
    }

    void set_sub_mul(const mpz_struct* a, uint64 b) {
        mpz_submul_ui(*this, a, b);
    }

    void negate() {
        mpz_neg(*this, *this);
    }

    void abs() {
        mpz_abs(*this, *this);
    }

    void set_divide_floor(const mpz_struct* a, const mpz_struct* b) {
        if (mpz_sgn(b)==0) {
            assert(false);
            return;
        }

        mpz_fdiv_q(*this, a, b);
    }

    void set_divide_floor(const mpz_struct* a, const mpz_struct* b, mpz_struct* remainder) {
        if (mpz_sgn(b)==0) {
            assert(false);
            return;
        }

        mpz_fdiv_qr(*this, remainder, a, b);
    }

    void set_divide_exact(const mpz_struct* a, const mpz_struct* b) {
        if (mpz_sgn(b)==0) {
            assert(false);
            return;
        }

        mpz_divexact(*this, a, b);
    }

    void set_mod(const mpz_struct* a, const mpz_struct* b) {
        if (mpz_sgn(b)==0) {
            assert(false);
            return;
        }

        mpz_mod(*this, a, b);
    }

    mpz& operator%=(const mpz_struct* t) {
        set_mod(*this, t);
        return *this;
    }

    bool divisible_by(const mpz_struct* a) const {
        if (mpz_sgn(a)==0) {
            assert(false);
            return false;
        }

        return mpz_divisible_p(*this, a);
    }

    void set_right_shift(const mpz_struct* a, int i) {
        assert(i>=0);
        mpz_tdiv_q_2exp(*this, *this, i);
    }

    //note: this uses truncation rounding
    mpz& operator>>=(int i) {
        set_right_shift(*this, i);
        return *this;
    }

    bool operator<(const mpz_struct* t) const { return mpz_cmp(*this, t)<0; }
    bool operator<=(const mpz_struct* t) const { return mpz_cmp(*this, t)<=0; }
    bool operator==(const mpz_struct* t) const { return mpz_cmp(*this, t)==0; }
    bool operator>=(const mpz_struct* t) const { return mpz_cmp(*this, t)>=0; }
    bool operator>(const mpz_struct* t) const { return mpz_cmp(*this, t)>0; }
    bool operator!=(const mpz_struct* t) const { return mpz_cmp(*this, t)!=0; }

    bool operator<(int64 i) const { return mpz_cmp_si(*this, i)<0; }
    bool operator<=(int64 i) const { return mpz_cmp_si(*this, i)<=0; }
    bool operator==(int64 i) const { return mpz_cmp_si(*this, i)==0; }
    bool operator>=(int64 i) const { return mpz_cmp_si(*this, i)>=0; }
    bool operator>(int64 i) const { return mpz_cmp_si(*this, i)>0; }
    bool operator!=(int64 i) const { return mpz_cmp_si(*this, i)!=0; }

    bool operator<(uint64 i) const { return mpz_cmp_ui(_(), i)<0; }
    bool operator<=(uint64 i) const { return mpz_cmp_ui(_(), i)<=0; }
    bool operator==(uint64 i) const { return mpz_cmp_ui(_(), i)==0; }
    bool operator>=(uint64 i) const { return mpz_cmp_ui(_(), i)>=0; }
    bool operator>(uint64 i) const { return mpz_cmp_ui(_(), i)>0; }
    bool operator!=(uint64 i) const { return mpz_cmp_ui(_(), i)!=0; }

    int compare_abs(const mpz_struct* t) const {
        return mpz_cmpabs(*this, t);
    }

    int compare_abs(uint64 t) const {
        return mpz_cmpabs_ui(*this, t);
    }

    //returns 0 if *this==0
    int sgn() const {
        return mpz_sgn(_());
    }

    int num_bits() const {
        return mpz_sizeinbase(*this, 2);
    }

    //0 if this is 0
    int num_limbs() const {
        return mpz_size(*this);
    }

    const uint64* read_limbs() const {
        return (uint64*)mpz_limbs_read(*this);
    }

    //limbs are uninitialized. call finish
    uint64* write_limbs(int num) {
        return (uint64*)mpz_limbs_write(*this, num);
    }

    //limbs are zero padded to the specified size. call finish
    uint64* modify_limbs(int num) {
        int old_size=num_limbs();

        uint64* res=(uint64*)mpz_limbs_modify(*this, num);

        //gmp doesn't do this
        for (int x=old_size;x<num;++x) {
            res[x]=0;
        }

        return res;
    }

    //num is whatever was passed to write_limbs or modify_limbs
    //it can be less than that as long as it is at least the number of nonzero limbs
    //it can be 0 if the result is 0
    void finish(int num, bool negative=false) {
        mpz_limbs_finish(*this, (negative)? -num : num);
    }

    template<int size> array<uint64, size> to_array() const {
        assert(size>=num_limbs());

        array<uint64, size> res;
        for (int x=0;x<size;++x) {
            res[x]=0;
        }

        for (int x=0;x<num_limbs();++x) {
            res[x]=read_limbs()[x];
        }

        return res;
    }
};

template<class type> struct cache_line_ptr {
    type* ptr=nullptr;

    cache_line_ptr() {}
    cache_line_ptr(cache_line_ptr& t)=delete;
    cache_line_ptr(cache_line_ptr&& t) { swap(ptr, t.ptr); }

    cache_line_ptr& operator=(cache_line_ptr& t)=delete;
    cache_line_ptr& operator=(cache_line_ptr&& t) { swap(ptr, t.ptr); }

    ~cache_line_ptr() {
        if (ptr) {
            ptr->~type();
            boost::alignment::aligned_free(ptr); // wjb free(ptr);
            ptr=nullptr;
        }
    }

    type& operator*() const { return *ptr; }
    type* operator->() const { return ptr; }
};

template<class type, class... arg_types> cache_line_ptr<type> make_cache_line(arg_types&&... args) {
    cache_line_ptr<type> res;
    res.ptr=(type*)alloc_cache_line(sizeof(type));
    new(res.ptr) type(forward<arg_types>(args)...);
    return res;
}

template<bool is_write, class type> void prefetch(const type& p) {
    //write prefetching lowers performance but read prefetching increases it
    if (is_write) return;

    for (int x=0;x<sizeof(p);x+=64) {
        __builtin_prefetch(((char*)&p)+x, (is_write)? 1 : 0);
    }
}

template<class type> void prefetch_write(const type& p) { prefetch<true>(p); }
template<class type> void prefetch_read(const type& p) { prefetch<false>(p); }

void memory_barrier() {
    asm volatile( "" ::: "memory" );
}

struct alignas(64) thread_counter {
    uint64 counter_value=0; //updated atomically since only one thread can write to it
    uint64 error_flag=0;

    void reset() {
        memory_barrier();
        counter_value=0;
        error_flag=0;
        memory_barrier();
    }

    thread_counter() {
        assert((uint64(this)&63)==0);
    }
};

thread_counter master_counter[100];
thread_counter slave_counter[100];

struct thread_state {
    int pairindex;
    bool is_slave=false;
    uint64 counter_start=0;
    uint64 last_fence=0;

    void reset() {
        is_slave=false;
        counter_start=0;
        last_fence=0;
    }

    thread_counter& this_counter() {
        return (is_slave)? slave_counter[pairindex] : master_counter[pairindex];
    }

    thread_counter& other_counter() {
        return (is_slave)? master_counter[pairindex] : slave_counter[pairindex];
    }

    void raise_error() {
        //if (is_vdf_test) {
            //print( "raise_error", is_slave );
        //}

        memory_barrier();
        this_counter().error_flag=1;
        other_counter().error_flag=1;
        memory_barrier();
    }

    const uint64 v() {
        return this_counter().counter_value;
    }

    //waits for the other thread to have at least this counter value
    //returns false if an error has been raised
    bool fence_absolute(uint64 t_v) {
        if (last_fence>=t_v) {
            return true;
        }

        memory_barrier();

        uint64 spin_counter=0;
        while (other_counter().counter_value < t_v) {
            if (this_counter().error_flag || other_counter().error_flag) {
                raise_error();
                break;
            }

            if (spin_counter>max_spin_counter) {
                if (is_vdf_test) {
                    print( "spin_counter too high", is_slave );
                }

                raise_error();
                break;
            }

            ++spin_counter;
            memory_barrier();
        }

        memory_barrier();

        if (!(this_counter().error_flag)) {
            last_fence=t_v;
        }

        return !(this_counter().error_flag);
    }

    bool fence(int delta) {
        return fence_absolute(counter_start+uint64(delta));
    }

    //increases this thread's counter value. it can only be increased
    //returns false if an error has been raised
    bool advance_absolute(uint64 t_v) {
        if (t_v==v()) {
            return true;
        }

        memory_barrier(); //wait for all writes to finish (on x86 this doesn't do anything but the compiler still needs it)

        assert(t_v>=v());

        if (this_counter().error_flag) {
            raise_error();
        }

        this_counter().counter_value=t_v;

        memory_barrier(); //want the counter writes to be low latency so prevent the compiler from caching it
        return !(this_counter().error_flag);
    }

    bool advance(int delta) {
        return advance_absolute(counter_start+uint64(delta));
    }

    bool has_error() {
        return this_counter().error_flag;
    }

    /*void wait_for_error_to_be_cleared() {
        assert(is_slave && enable_threads);
        while (this_counter().error_flag) {
            memory_barrier();
        }
    }

    void clear_error() {
        assert(!is_slave);

        memory_barrier();
        this_counter().error_flag=0;
        other_counter().error_flag=0;
        memory_barrier();
    }*/
};

thread_local thread_state c_thread_state;

struct alignas(64) gcd_uv_entry {
    //these are uninitialized for the first entry
    uint64 u_0;
    uint64 u_1;
    uint64 v_0;
    uint64 v_1;
    uint64 parity; //1 if odd, 0 if even

    uint64 exit_flag; //1 if last, else 0

    uint64 unused_0;
    uint64 unused_1;

    template<class mpz_type> void matrix_multiply(const mpz_type& in_a, const mpz_type& in_b, mpz_type& out_a, mpz_type& out_b) const {
        out_a.set_mul((parity==0)? in_a : in_b, (parity==0)? u_0 : v_0);
        out_a.set_sub_mul((parity==0)? in_b : in_a, (parity==0)? v_0 : u_0);

        out_b.set_mul((parity==0)? in_b : in_a, (parity==0)? v_1 : u_1);
        out_b.set_sub_mul((parity==0)? in_a : in_b, (parity==0)? u_1 : v_1);
    }
};
static_assert(sizeof(gcd_uv_entry)==64, "");

template<class mpz_type> struct alignas(64) gcd_results_type {
    mpz_type as[2];
    mpz_type bs[2];

    static const int num_counter=gcd_max_iterations+1; //one per outputted entry

    array<gcd_uv_entry, gcd_max_iterations+1> uv_entries;

    int end_index=0;

    mpz_type& get_a_start() {
        return as[0];
    }

    mpz_type& get_b_start() {
        return bs[0];
    }

    mpz_type& get_a_end() {
        assert(end_index>=0 && end_index<2);
        return as[end_index];
    }

    mpz_type& get_b_end() {
        assert(end_index>=0 && end_index<2);
        return bs[end_index];
    }

    //this will increase the counter value and wait until the result at index is available
    //index 0 only has exit_flag initialized
    bool get_entry(int counter_start_delta, int index, const gcd_uv_entry** res) const {
        *res=nullptr;

        if (index>=gcd_max_iterations+1) {
            c_thread_state.raise_error();
            return false;
        }

        assert(index>=0);

        if (!c_thread_state.fence(counter_start_delta + index+1)) {
            return false;
        }

        *res=&uv_entries[index];
        return true;
    }
};

//a and b in c_results should be initialized
//returns false if the gcd failed
//this assumes that all inputs are unsigned, a>=b, and a>=threshold
//this will increase the counter value as results are generated
template<class mpz_type> bool gcd_unsigned(
    int counter_start_delta, gcd_results_type<mpz_type>& c_results, const array<uint64, gcd_size>& threshold
) {
    if (c_thread_state.has_error()) {
        return false;
    }

    int a_limbs=c_results.get_a_start().num_limbs();
    int b_limbs=c_results.get_b_start().num_limbs();

    if (a_limbs>gcd_size || b_limbs>gcd_size) {
        c_thread_state.raise_error();
        return false;
    }

    asm_code::asm_func_gcd_unsigned_data data;
    data.a=c_results.as[0].modify_limbs(gcd_size);
    data.b=c_results.bs[0].modify_limbs(gcd_size);
    data.a_2=c_results.as[1].write_limbs(gcd_size);
    data.b_2=c_results.bs[1].write_limbs(gcd_size);
    data.threshold=(uint64*)&threshold[0];

    data.uv_counter_start=c_thread_state.counter_start+counter_start_delta+1;
    data.out_uv_counter_addr=&(c_thread_state.this_counter().counter_value);
    data.out_uv_addr=(uint64*)&(c_results.uv_entries[1]);
    data.iter=-1;
    data.a_end_index=(a_limbs==0)? 0 : a_limbs-1;

    if (is_vdf_test) {
        assert((uint64(data.out_uv_addr)&63)==0); //should be cache line aligned
    }

    memory_barrier();
    int error_code=asm_code::asm_func_gcd_unsigned(&data);
    memory_barrier();

    if (error_code!=0) {
        c_thread_state.raise_error();
        return false;
    }

    assert(data.iter>=0 && data.iter<=gcd_max_iterations); //total number of iterations performed
    bool is_even=((data.iter-1)&1)==0; //parity of last iteration (can be -1)

    c_results.end_index=(is_even)? 1 : 0;

    c_results.as[0].finish(gcd_size);
    c_results.as[1].finish(gcd_size);
    c_results.bs[0].finish(gcd_size);
    c_results.bs[1].finish(gcd_size);

    inject_error(c_results.as[0]);
    inject_error(c_results.as[1]);
    inject_error(c_results.bs[0]);
    inject_error(c_results.bs[1]);

    if (!c_thread_state.advance(counter_start_delta+gcd_results_type<mpz_type>::num_counter)) {
        return false;
    }

    return true;
}