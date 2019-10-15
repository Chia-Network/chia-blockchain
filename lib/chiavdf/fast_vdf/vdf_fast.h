typedef mpz< 9, 14> mpz_9 ; //2 cache lines
typedef mpz<17, 22> mpz_17; //3 cache lines
typedef mpz<25, 30> mpz_25; //4 cache lines
typedef mpz<33, 38> mpz_33; //5 cache lines

static_assert(sizeof(mpz_9 )==2*64);
static_assert(sizeof(mpz_17)==3*64);
static_assert(sizeof(mpz_25)==4*64);
static_assert(sizeof(mpz_33)==5*64);

//these all have at least 64 extra bits before they reallocate
//x is the discriminant number of bits divided by 4
typedef mpz_9 int1x;
typedef mpz_17 int2x;
typedef mpz_25 int3x;
typedef mpz_33 int4x;

typedef gcd_results_type<int2x> gcd_results_int2x;

//this is accessed by both threads
//all divisions are exact
struct square_state_type {
    int pairindex;

    //running the gcd will advance the counter value by this much on both the master and slave threads
    //it is then advanced by 1 after the gcd results are consumed
    static const int gcd_num_counter=gcd_results_int2x::num_counter;

    //these are constants so they don't need to be prefetched
    struct phase_constant_type {
        int4x D; // D>=0
        int1x L; // L>=0
        alignas(64) array<uint64, gcd_size> gcd_zero;
        alignas(64) array<uint64, gcd_size> gcd_L;
    } phase_constant;

    //the master assigns the new values of A and B
    struct phase_start_type {
        //int2x wjba;
        //int2x wjbb;
        
        int2x as[2]; // a>=0
        int2x bs[2]; // b>=0
        alignas(64) int ab_index=0; //index of the start a/b values. the new values will be written to the other slot in this array
        alignas(8) bool b_higher_magnitude_than_a=false; //also true if b==a
        alignas(8) uint64 num_valid_iterations=0;
        alignas(8) bool corruption_flag=false; //the slave thread will set this if c is invalid

        int2x& a() { return as[ab_index]; }
        int2x& b() { return bs[ab_index]; }
        int2x& A() { return as[1-ab_index]; }
        int2x& B() { return bs[1-ab_index]; }
    } phase_start;

    static const int counter_start_phase_0=0;
    static const int counter_start_phase_1=counter_start_phase_0+gcd_num_counter+1;
    static const int counter_start_phase_2=counter_start_phase_1+gcd_num_counter+1;
    static const int counter_start_phase_3=counter_start_phase_2+1;
    static const int counter_start_phase_4=counter_start_phase_3+1;
    static const int counter_start_phase_5=counter_start_phase_4+1;

    //
    //

    struct phase_0_master_d_type {
        gcd_results_int2x gcd_1_0; // gcd(b,a,0); a'=1; b'=0 ; U0*b + V0*a = 1 ; U1*b + V1*a = 0
    } phase_0_master_d;

    struct phase_0_slave_d_type {
        int4x b_b; // b_b_D=b^2
        int2x a_4; // a_4=4a=a<<2
        int4x b_b_D; // b_b_D=b^2-D
        int4x c; // c=(b^2-D)/(4a)
        int4x c_remainder; //only assigned if c is being validated

        //initially:
        //U0=-c ; U1=0
        //if |b|<|a|: swap(U0, U1) ; <U0,U1>*=-1
        //if b<0: <U0,U1>*=-1
        //
        //to apply a matrix Z*[X0 -Y0 ; -X1 Y1] where Z=local parity (-1 or 1) ; X=local u (unsigned) ; Y=local v (unsigned):
        //-do the matrix multiplication by the column vector <U0,U1>
        //-reduce each component of the result modulo a. this can be delayed until more matrix multiplications have happened if necessary
        int4x U0s[2];
        int4x U1s[2];
        alignas(64) int k_index=0; // k=(-U0*c)%a ; k>=0 ; k<a ; k=U0[k_index]

        int4x& k() { return U0s[k_index]; }
    } phase_0_slave_d;


    //
    //

    struct phase_1_master_d_type {
        //initially, v0=0 ; v1=1
        //the matrix is applied like before but with no modulo
        // S = -1 if v1<=0, else 1
        int1x v0s[2];
        int1x v1s[2];
        alignas(64) int v_index=0; // v0=v0[v_index] ; v1=v1[v_index]

        int1x& v0() { return v0s[v_index]; }
        int1x& v1() { return v1s[v_index]; }

        bool S_negative() { return v1().sgn()<=0; }
    } phase_1_master_d;

    struct phase_1_slave_d_type {
        gcd_results_int2x gcd_s_t; // gcd(a,k,L) ; a'=s>L ; b'=t<=L ; u0*a + v0*k = s ; u1*a + v1*k = t
        // the final values of s and t fit in an int1x

        int2x& s() { return gcd_s_t.get_a_end(); }
        int2x& t() { return gcd_s_t.get_b_end(); }
    } phase_1_slave_d;


    //
    //

    struct phase_2_master_d_type {
        int3x c_v1; // c_v1 = c*v1
        int3x b_t; // b_t = b*t
        int3x b_t_c_v1; // b_t_c_v1 = b*t+c*v1
        int2x h; // h = S*(b*t+c*v1)/a
        int2x v1_h; // v1_h=v1*h
    } phase_2_master_d;

    struct phase_2_slave_d_type {
        int2x t_t_S; // t_t_S = t*t*S
        int1x v0_2; // v0_2 = 2*v0 = v0<<1
    } phase_2_slave_d;

    //
    //

    struct phase_3_master_d_type {
        // A = t*t*S + v1*h ; A=as[1-ab_index]
        int2x A_2; // A_2 = A*2 = A<<1
    } phase_3_master_d;

    struct phase_3_slave_d_type {
        int2x S_t_v0; // S_t_v0 = S*t*v0
        int2x a_S_t_v0; // a_S_t_v0 = a + S*t*v0
        int3x t_2_a_S_t_v0; // t_2_a_S_t_v0 = 2t*(a + S*t*v0)
        int1x t_2; // t_2 = 2t = t<<1
        int2x t_2_a_S_t_v0_v1; // t_2_a_S_t_v0_v1 = (2t*(a + S*t*v0))/v1
        int2x e; // e = -b - (2t*(a + S*t*v0))/v1
    } phase_3_slave_d;

    //
    //

    struct phase_4_master_d_type {
        int2x v0_2_h; // v0_2_h = 2*v0*h
        int2x f; // f = e - 2*v0*h
        // B = f % (2A)
        // A = |A|
        // assign b_higher_magnitude_than_a
    } phase_4_master_d;
    struct phase_4_slave_d_type {
    } phase_4_slave_d;


    //
    // ==========================================================================================================================
    //

    bool phase_0_master() {
        {
            TRACK_CYCLES //100
            if (!c_thread_state.fence(counter_start_phase_0)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        {
            //overhead of track_cycles
            TRACK_CYCLES //60
        }

        prefetch_write(phase_0_master_d);
        prefetch_write(phase_1_master_d);
        prefetch_write(phase_2_master_d);
        prefetch_write(phase_3_master_d);
        prefetch_write(phase_4_master_d);
        prefetch_write(phase_start.A());
        prefetch_write(phase_start.B());

        const auto& gcd_zero=phase_constant.gcd_zero;
        const auto& L=phase_constant.L;

        const auto& a=phase_start.a(); prefetch_read(a);
        const auto& b=phase_start.b(); prefetch_read(b);

        const int max_bits_ab=max_bits_base + num_extra_bits_ab;

        //sometimes the nudupl code won't reduce the output all the way. if it has too many bits it will get reduced by calling
        // square_original
        bool ab_valid;
        {
            TRACK_CYCLES //185
            ab_valid=(a.num_bits()<=max_bits_ab && b.num_bits()<=max_bits_ab && a.sgn()>=0);
        }
        if (!ab_valid) {
            return false;
        }

        //a>L if this is true (both are nonnegative)
        //usually a has twice as many limbs as L
        bool a_high_enough;
        {
            TRACK_CYCLES //102
            a_high_enough=(a.num_limbs()>L.num_limbs());
        }
        if (!a_high_enough) {
            return false;
        }

        auto& gcd_1_0=phase_0_master_d.gcd_1_0;

        {
            TRACK_CYCLES //345
            gcd_1_0.get_a_start()=(phase_start.b_higher_magnitude_than_a)? b : a;
            gcd_1_0.get_b_start()=(phase_start.b_higher_magnitude_than_a)? a : b;
        }

        {
            TRACK_CYCLES //16070 (critical path 1)
            if (!gcd_unsigned(counter_start_phase_0, gcd_1_0, gcd_zero)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        return true;
    }

    bool phase_0_slave() {
        {
            TRACK_CYCLES //1698 (doesn't matter)
            if (!c_thread_state.fence(counter_start_phase_0)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        prefetch_write(phase_0_slave_d);
        prefetch_write(phase_1_slave_d);
        prefetch_write(phase_2_slave_d);
        prefetch_write(phase_3_slave_d);
        prefetch_write(phase_4_slave_d);

        const auto& D=phase_constant.D;

        const auto& a=phase_start.a(); prefetch_read(a);
        const auto& b=phase_start.b(); prefetch_read(b);

        const auto& gcd_1_0=phase_0_master_d.gcd_1_0;

        auto& b_b               =phase_0_slave_d.b_b;
        auto& a_4               =phase_0_slave_d.a_4;
        auto& b_b_D             =phase_0_slave_d.b_b_D;
        auto& c                 =phase_0_slave_d.c;
        auto& c_remainder       =phase_0_slave_d.c_remainder;
        auto& U0s               =phase_0_slave_d.U0s;
        auto& U1s               =phase_0_slave_d.U1s;
        auto& k_index           =phase_0_slave_d.k_index;

        {
            thread_local int validate_iter=0;
            ++validate_iter;
            bool validate_c=(validate_iter&(validate_interval-1))==0 && validate_interval!=-1;

            {
                TRACK_CYCLES //606
                b_b.set_mul(b, b);
            }
            {
                TRACK_CYCLES //193
                a_4.set_left_shift(a, 2);
            }
            {
                TRACK_CYCLES //385
                b_b_D.set_sub(b_b, D);
            }

            if (!validate_c) {
                TRACK_CYCLES //747
                c.set_divide_exact(b_b_D, a_4);
            } else {
                TRACK_CYCLES //1309; latency is hidden by gcd being slow
                c.set_divide_floor(b_b_D, a_4, c_remainder);
                if (c_remainder.sgn()!=0) {
                    assert(!is_vdf_test); //should never have corruption unless there are bugs
                    phase_start.corruption_flag=true; //bad
                    return false;
                }
            }

            {
                TRACK_CYCLES //100
                if (a.sgn()<0 || c.sgn()<0) {
                    assert(!is_vdf_test);
                    phase_start.corruption_flag=true;
                    return false;
                }
            }
        }

        //
        //

        int k_index_local=0;

        //calculating gcd(b,a).u, so bu+av=g
        //if b is negative, then u is negated: (-b)(-u)+av=g
        //if a and b are swapped, will calculate v but the negation is unchanged

        {
            //if |b|<|a|: swap(U0, U1)
            auto& c_U0=(phase_start.b_higher_magnitude_than_a? U0s[0] : U1s[0]);
            auto& c_U1=(phase_start.b_higher_magnitude_than_a? U1s[0] : U0s[0]);

            if (calculate_k_repeated_mod) {
                TRACK_CYCLES //176
                assert(calculate_k_repeated_mod_interval>=1);

                //U0=-c ; U1=0
                c_U0=c;
                c_U0.negate();
                c_U1=uint64(0ull);
            } else {
                TRACK_CYCLES
                //U0=1 ; U1=0
                c_U0=uint64(1ull);
                c_U1=uint64(0ull);
            }
        }

        //if |b|<|a|: <U0,U1>*=-1
        /*if (!phase_start.b_higher_magnitude_than_a) {
            TRACK_CYCLES
            U0s[0].negate();
            U1s[0].negate();
        }*/

        {
            TRACK_CYCLES //206
            //if b<0: <U0,U1>*=-1
            if (b.sgn()<0) {
                U0s[0].negate();
                U1s[0].negate();
            }
        }

        bool mod_pending=true; //have to calculate -c%a even if no work is done
        int num_multiplications=0;

        int gcd_index=0;
        while (true) {
            const gcd_uv_entry* c_entry=nullptr;
            {
                TRACK_CYCLES //357
                if (!gcd_1_0.get_entry(counter_start_phase_0, gcd_index, &c_entry)) {
                    TRACK_CYCLES_ABORT
                    return false;
                }
            }

            if (gcd_index!=0) {
                auto& in_U0=U0s[k_index_local];
                auto& in_U1=U1s[k_index_local];

                auto& out_U0=U0s[1-k_index_local];
                auto& out_U1=U1s[1-k_index_local];

                {
                    TRACK_CYCLES //325
                    c_entry->matrix_multiply(in_U0, in_U1, out_U0, out_U1);
                    ++num_multiplications;
                    mod_pending=true;
                }

                if (calculate_k_repeated_mod && num_multiplications==calculate_k_repeated_mod_interval) {
                    TRACK_CYCLES //650 with calculate_k_repeated_mod_interval==1
                    out_U0%=a;
                    out_U1%=a;
                    mod_pending=false;
                    num_multiplications=0;
                }

                k_index_local=1-k_index_local;
            }

            ++gcd_index;

            if (c_entry->exit_flag) {
                break;
            }
        }

        if (calculate_k_repeated_mod && mod_pending) {
            TRACK_CYCLES //2612 with calculate_k_repeated_mod_interval infinite;
            U0s[k_index_local]%=a;
            U1s[k_index_local]%=a;
            mod_pending=false;
        }

        if (!calculate_k_repeated_mod) {
            TRACK_CYCLES //1825 (critical path 2)
            // k=(-U0*c)%a
            auto& in_U0=U0s[k_index_local];

            in_U0.set_mul(in_U0, c);
            in_U0.negate();
            in_U0.set_mod(in_U0, a);
        }

        inject_error(U0s[k_index_local]);

        k_index=k_index_local;

        return true;
    }

    //
    // ==========================================================================================================================
    //

    bool phase_1_master() {
        {
            TRACK_CYCLES //3335 (this stall doesn't matter since this thread is slower than the slave thread in this phase)
            if (!c_thread_state.fence(counter_start_phase_1)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& c=phase_0_slave_d.c; prefetch_read(c);

        auto& v0s=phase_1_master_d.v0s;
        auto& v1s=phase_1_master_d.v1s;
        auto& v_index=phase_1_master_d.v_index;

        const auto& gcd_s_t=phase_1_slave_d.gcd_s_t;

        int v_index_local=0;

        v0s[0]=uint64(0ull);
        v1s[0]=uint64(1ull);

        int gcd_index=0;
        while (true) {
            const gcd_uv_entry* c_entry=nullptr;
            {
                TRACK_CYCLES //396
                if (!gcd_s_t.get_entry(counter_start_phase_1, gcd_index, &c_entry)) {
                    TRACK_CYCLES_ABORT
                    return false;
                }
            }

            if (gcd_index!=0) {
                TRACK_CYCLES //206

                int1x& in_v0=v0s[v_index_local];
                int1x& in_v1=v1s[v_index_local];

                int1x& out_v0=v0s[1-v_index_local];
                int1x& out_v1=v1s[1-v_index_local];

                c_entry->matrix_multiply(in_v0, in_v1, out_v0, out_v1);

                v_index_local=1-v_index_local;
            }

            ++gcd_index;

            if (c_entry->exit_flag) {
                break;
            }
        }

        inject_error(v0s[v_index_local]);
        inject_error(v1s[v_index_local]);

        v_index=v_index_local;

        return true;
    }

    bool phase_1_slave() {
        {
            TRACK_CYCLES //78
            if (!c_thread_state.fence(counter_start_phase_0)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& gcd_L=phase_constant.gcd_L;

        const auto& a=phase_start.a();

        const auto& k=phase_0_slave_d.k();

        auto& gcd_s_t=phase_1_slave_d.gcd_s_t;

        {
            TRACK_CYCLES //323
            gcd_s_t.get_a_start()=a;
            gcd_s_t.get_b_start()=k;
        }

        {
            TRACK_CYCLES //8551 (critical path 3)
            if (!gcd_unsigned(counter_start_phase_1, gcd_s_t, gcd_L)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        return true;
    }

    //
    // ==========================================================================================================================
    //

    bool phase_2_master() {
        {
            TRACK_CYCLES //76
            if (!c_thread_state.fence(counter_start_phase_1)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& a=phase_start.a();
        const auto& b=phase_start.b();
        const auto& c=phase_0_slave_d.c;

        const auto& v1=phase_1_master_d.v1();

        bool S_negative=phase_1_master_d.S_negative();

        auto& c_v1      =phase_2_master_d.c_v1;
        auto& b_t       =phase_2_master_d.b_t;
        auto& b_t_c_v1  =phase_2_master_d.b_t_c_v1;
        auto& h         =phase_2_master_d.h;
        auto& v1_h      =phase_2_master_d.v1_h;

        {
            TRACK_CYCLES //453
            c_v1.set_mul(c, v1);
        }

        {
            TRACK_CYCLES //97
            if (!c_thread_state.fence(counter_start_phase_2)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }
        const auto& t=phase_1_slave_d.t(); prefetch_read(t);

        {
            TRACK_CYCLES //426
            b_t.set_mul(b, t);
        }

        {
            TRACK_CYCLES //212
            b_t_c_v1.set_add(b_t, c_v1);
        }

        {
            TRACK_CYCLES //439
            h.set_divide_exact(b_t_c_v1, a);
        }

        {
            TRACK_CYCLES //98
            if (S_negative) {
                h.negate();
            }
        }

        {
            TRACK_CYCLES //324
            v1_h.set_mul(v1, h);
        }

        return true;
    }

    bool phase_2_slave() {
        {
            TRACK_CYCLES //97
            if (!c_thread_state.fence(counter_start_phase_1)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& t=phase_1_slave_d.t();

        auto& t_t_S     =phase_2_slave_d.t_t_S;
        auto& v0_2      =phase_2_slave_d.v0_2;

        {
            TRACK_CYCLES //198
            t_t_S.set_mul(t, t);
        }

        {
            TRACK_CYCLES //812
            if (!c_thread_state.fence(counter_start_phase_2)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& v0=phase_1_master_d.v0(); prefetch_read(v0);
        const auto& v1=phase_1_master_d.v1(); prefetch_read(v1);

        bool S_negative;
        {
            TRACK_CYCLES //189
            S_negative=phase_1_master_d.S_negative();
        }

        {
            TRACK_CYCLES //91
            if (S_negative) {
                t_t_S.negate();
            }
        }

        {
            TRACK_CYCLES //102
            v0_2.set_left_shift(v0, 1);
        }

        return true;
    }

    //
    // ==========================================================================================================================
    //

    bool phase_3_master() {
        {
            TRACK_CYCLES //116
            if (!c_thread_state.fence(counter_start_phase_3)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& v1_h      =phase_2_master_d.v1_h;

        const auto& t_t_S     =phase_2_slave_d.t_t_S; prefetch_read(t_t_S);
        const auto& v0_2      =phase_2_slave_d.v0_2; prefetch_read(v0_2);

        auto& A=phase_start.A();
        auto& A_2=phase_3_master_d.A_2;

        {
            TRACK_CYCLES //223
            A.set_add(t_t_S, v1_h);
        }

        {
            TRACK_CYCLES //180
            A_2.set_left_shift(A, 1);
        }

        return true;
    }
    bool phase_3_slave() {
        {
            TRACK_CYCLES //78
            if (!c_thread_state.fence(counter_start_phase_2)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& a=phase_start.a();
        const auto& b=phase_start.b();

        const auto& t=phase_1_slave_d.t();
        const auto& v0=phase_1_master_d.v0();
        const auto& v1=phase_1_master_d.v1();
        bool S_negative=phase_1_master_d.S_negative();

        auto& S_t_v0            =phase_3_slave_d.S_t_v0;
        auto& a_S_t_v0          =phase_3_slave_d.a_S_t_v0;
        auto& t_2_a_S_t_v0      =phase_3_slave_d.t_2_a_S_t_v0;
        auto& t_2               =phase_3_slave_d.t_2;
        auto& t_2_a_S_t_v0_v1   =phase_3_slave_d.t_2_a_S_t_v0_v1;
        auto& e                 =phase_3_slave_d.e;

        {
            TRACK_CYCLES //244
            S_t_v0.set_mul(t, v0);
        }

        {
            TRACK_CYCLES //60
            if (S_negative) {
                S_t_v0.negate();
            }
        }

        {
            TRACK_CYCLES //299
            a_S_t_v0.set_add(a, S_t_v0);
        }

        {
            TRACK_CYCLES //101
            t_2.set_left_shift(t, 1);
        }

        {
            TRACK_CYCLES //384
            t_2_a_S_t_v0.set_mul(t_2, a_S_t_v0);
        }

        {
            TRACK_CYCLES //666
            t_2_a_S_t_v0_v1.set_divide_exact(t_2_a_S_t_v0, v1);
        }

        {
            TRACK_CYCLES //353
            e.set_add(b, t_2_a_S_t_v0_v1);
            e.negate();
        }

        return true;
    }

    //
    // ==========================================================================================================================
    //

    bool phase_4_master() {
        {
            TRACK_CYCLES //79
            if (!c_thread_state.fence(counter_start_phase_3)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }

        const auto& v0_2=phase_2_slave_d.v0_2;
        const auto& h=phase_2_master_d.h;
        const auto& A_2=phase_3_master_d.A_2;

        auto& v0_2_h=phase_4_master_d.v0_2_h;
        auto& f     =phase_4_master_d.f;
        auto& A     =phase_start.A();
        auto& B     =phase_start.B();
        auto& b_higher_magnitude_than_a=phase_start.b_higher_magnitude_than_a;
        auto& ab_index=phase_start.ab_index;
        auto& num_valid_iterations=phase_start.num_valid_iterations;

        {
            TRACK_CYCLES //177

            auto& gcd_1_0=phase_0_master_d.gcd_1_0;

            if (gcd_1_0.get_a_end()!=uint64(1ull)) {
                assert(!is_vdf_test);
                phase_start.corruption_flag=true;
                return false;
            }

            if (gcd_1_0.get_b_end().sgn()!=0) {
                assert(!is_vdf_test);
                phase_start.corruption_flag=true;
                return false;
            }
        }

        {
            TRACK_CYCLES //318
            v0_2_h.set_mul(v0_2, h);
        }

        {
            TRACK_CYCLES //211
            if (!c_thread_state.fence(counter_start_phase_4)) {
                TRACK_CYCLES_ABORT
                return false;
            }
        }
        const auto& e=phase_3_slave_d.e; prefetch_read(e);

        {
            TRACK_CYCLES //192
            f.set_sub(e, v0_2_h);
        }

        {
            TRACK_CYCLES //430
            B.set_mod(f, A_2);
        }
        
        {
            TRACK_CYCLES //80
            A.abs();
        }
        
        {
            TRACK_CYCLES //94
            b_higher_magnitude_than_a=(B.compare_abs(A)>=0);
        }

        ab_index=1-ab_index;
        ++num_valid_iterations;
        
        //phase_start.wjba=phase_start.a();
        //phase_start.wjbb=phase_start.b();

        return true;
    }
    bool phase_4_slave() {
        
        return true;
    }

    //
    // ==========================================================================================================================
    //

    static const int num_phases=5;
    static const int counter_end=counter_start_phase_5; //added to counter_start to get the next counter

    void init(const integer& t_D, const integer& t_L, const integer& t_a, const integer& t_b) {
        int2x zero;
        zero=uint64(0ull);

        phase_constant.D=t_D.impl;
        phase_constant.L=t_L.impl;
        phase_constant.gcd_zero=zero.to_array<gcd_size>();
        phase_constant.gcd_L=phase_constant.L.to_array<gcd_size>();

        phase_start.ab_index=0;
        phase_start.num_valid_iterations=0;
        phase_start.corruption_flag=false;

        auto& a=phase_start.a();
        auto& b=phase_start.b();

        a=t_a.impl;
        b=t_b.impl;

        phase_start.b_higher_magnitude_than_a=(b.compare_abs(a)>=0);
    }

    int get_counter_start(int phase) {
        int res[]={counter_start_phase_0, counter_start_phase_1, counter_start_phase_2, counter_start_phase_3, counter_start_phase_4};
        return res[phase];
    }

    bool call_phase(int phase, bool is_slave) {
        decltype(&square_state_type::phase_0_master) funcs_master[]={
            &square_state_type::phase_0_master,
            &square_state_type::phase_1_master,
            &square_state_type::phase_2_master,
            &square_state_type::phase_3_master,
            &square_state_type::phase_4_master
        };

        decltype(&square_state_type::phase_0_slave) funcs_slave[]={
            &square_state_type::phase_0_slave,
            &square_state_type::phase_1_slave,
            &square_state_type::phase_2_slave,
            &square_state_type::phase_3_slave,
            &square_state_type::phase_4_slave
        };

        return (this->*((is_slave)? funcs_slave : funcs_master)[phase])();
    }

    bool single_thread_master_first(int phase) {
        //for gcds, the thread calling gcd_unsigned has to go first
        return phase!=1;
    }

    //if this returns false then there is corruption and the inputs are unchanged
    //if it returns true, the inputs have been advanced by num_iterations
    //num_iterations can be less than the requested number if there was an error (e.g. large gcd quotient, thread spun for too long, etc)
    //this will set num_iterations to ~uint64(0) if the return value is false
    bool assign(integer& t_a, integer& t_b, integer& t_c, uint64& num_iterations) {
        num_iterations=phase_start.num_valid_iterations;

        if (phase_start.corruption_flag) {
            assert(!is_vdf_test);
            num_iterations=~uint64(0);
            return false;
        }

        const auto& a=phase_start.a();
        const auto& b=phase_start.b();

        const auto& D=phase_constant.D;

        auto& b_b               =phase_0_slave_d.b_b;
        auto& a_4               =phase_0_slave_d.a_4;
        auto& b_b_D             =phase_0_slave_d.b_b_D;
        auto& c                 =phase_0_slave_d.c;
        auto& c_remainder       =phase_0_slave_d.c_remainder;

        b_b.set_mul(b, b);
        a_4.set_left_shift(a, 2);
        b_b_D.set_sub(b_b, D);

        c.set_divide_floor(b_b_D, a_4, c_remainder);
        if (c_remainder.sgn()!=0 || a.sgn()<0 || c.sgn()<0) {
            assert(!is_vdf_test);
            num_iterations=~uint64(0);
            return false;
        }

        mpz_set(t_a.impl, a);
        mpz_set(t_b.impl, b);
        mpz_set(t_c.impl, c);

        return true;
    }
    /*
    bool assignwjb(integer& t_a, integer& t_b, integer& t_c, uint64& num_iterations) {

        int4x b_b; // b_b_D=b^2
        int2x a_4; // a_4=4a=a<<2
        int4x b_b_D; // b_b_D=b^2-D
        int4x c; // c=(b^2-D)/(4a)
        int4x c_remainder; //only assigned if c is being validated

        num_iterations=phase_start.num_valid_iterations;
        
        if (phase_start.corruption_flag) {
            assert(!is_vdf_test);
            num_iterations=~uint64(0);
            return false;
        }
        
        const auto& a=phase_start.wjba;
        const auto& b=phase_start.wjbb;
        
        const auto& D=phase_constant.D;
   
        b_b.set_mul(b, b);
        a_4.set_left_shift(a, 2);
        b_b_D.set_sub(b_b, D);
        
        c.set_divide_floor(b_b_D, a_4, c_remainder);
        if (c_remainder.sgn()!=0 || a.sgn()<0 || c.sgn()<0) {
            assert(!is_vdf_test);
            num_iterations=~uint64(0);
            return false;
        }
        
        mpz_set(t_a.impl, a);
        mpz_set(t_b.impl, b);
        mpz_set(t_c.impl, c);
        
        return true;
    }*/
};

#define NL_SQUARESTATE 1
#define NL_FORM 2

class INUDUPLListener{
public:
    virtual void OnIteration(int type, void *data, uint64 iteration)=0;
};

//this should never have an infinite loop
//the gcd loops all have maximum counters after which they'll error out, and the thread_state loops also have a maximum spin counter
void repeated_square_fast_work(square_state_type &square_state,bool is_slave, uint64 base, uint64 iterations, INUDUPLListener *nuduplListener) {
    c_thread_state.reset();
    c_thread_state.is_slave=is_slave;
    c_thread_state.pairindex=square_state.pairindex;

    bool has_error=false;

    for (uint64 iter=0;iter<iterations;++iter) {
        TRACK_CYCLES //master: 35895; slave: 35905

        for (int phase=0;phase<square_state_type::num_phases;++phase) {
            if (!c_thread_state.advance(square_state.get_counter_start(phase))) {
                c_thread_state.raise_error();
                has_error=true;
                break;
            }

            if (!square_state.call_phase(phase, is_slave)) {
                c_thread_state.raise_error();
                has_error=true;
                break;
            }
        }

        if (has_error) {
            break;
        }
        
        c_thread_state.counter_start+=square_state_type::counter_end;
        
        if(!is_slave)
        {
            if(nuduplListener!=NULL)
                nuduplListener->OnIteration(NL_SQUARESTATE,&square_state,base+iter);
        }
    }

    #ifdef ENABLE_TRACK_CYCLES
        {
            if (is_slave) {
                sleep(1);
            }

            print( "track cycles is_slave:", is_slave );
            TRACK_CYCLES_OUTPUT_STATS
            print( "" );
            print( "" );
            print( "" );
        }
    #endif
}

uint64 repeated_square_fast_multithread(square_state_type &square_state, form& f, const integer& D, const integer& L, uint64 base, uint64 iterations, INUDUPLListener *nuduplListener) {
    master_counter[square_state.pairindex].reset();
    slave_counter[square_state.pairindex].reset();

    square_state.init(D, L, f.a, f.b);
    memory_barrier();

    thread slave_thread(repeated_square_fast_work, std::ref(square_state), false, base, iterations, std::ref(nuduplListener));

    repeated_square_fast_work(square_state, true, base, iterations, nuduplListener);

    slave_thread.join(); //slave thread can't get stuck; is supposed to error out instead
    memory_barrier();

    uint64 res;
    square_state.assign(f.a, f.b, f.c, res);

    return res;
}

uint64 repeated_square_fast_single_thread(square_state_type &square_state, form& f, const integer& D, const integer& L, uint64 base, uint64 iterations, INUDUPLListener *nuduplListener) {
    master_counter[square_state.pairindex].reset();
    slave_counter[square_state.pairindex].reset();

    square_state.init(D, L, f.a, f.b);

    thread_state thread_state_master;
    thread_state thread_state_slave;

    thread_state_master.reset();
    thread_state_master.is_slave=false;
    thread_state_master.pairindex=square_state.pairindex;

    thread_state_slave.reset();
    thread_state_slave.is_slave=true;
    thread_state_slave.pairindex=square_state.pairindex;

    bool has_error=false;

    for (uint64 iter=0;iter<iterations;++iter) {
        TRACK_CYCLES

        for (int phase=0;phase<square_state_type::num_phases;++phase) {
            if (!thread_state_master.advance(square_state.get_counter_start(phase))) {
                thread_state_master.raise_error();
                has_error=true;
                break;
            }

            if (!thread_state_slave.advance(square_state.get_counter_start(phase))) {
                thread_state_slave.raise_error();
                has_error=true;
                break;
            }

            bool master_first=square_state.single_thread_master_first(phase);

            for (bool is_slave : {!master_first, master_first}) {
                c_thread_state=(is_slave)? thread_state_slave : thread_state_master;

                if (!square_state.call_phase(phase, is_slave)) {
                    c_thread_state.raise_error();
                    has_error=true;
                    break;
                }
            }

            if (has_error) {
                break;
            }
        }

        if (has_error) {
            break;
        }

        thread_state_master.counter_start+=square_state_type::counter_end;
        thread_state_slave.counter_start+=square_state_type::counter_end;
        
        if(nuduplListener!=NULL)
            nuduplListener->OnIteration(NL_SQUARESTATE,&square_state,base+iter);
    }

    uint64 res;
    square_state.assign(f.a, f.b, f.c, res); //sets res to ~uint64(0) and leaves f unchanged if there is corruption

    #ifdef ENABLE_TRACK_CYCLES
        print( "stats both threads:" );
        TRACK_CYCLES_OUTPUT_STATS
    #endif

    return res;
}

//returns number of iterations performed
//if this returns ~0, the discriminant was invalid and the inputs are unchanged
uint64 repeated_square_fast(square_state_type &square_state,form& f, const integer& D, const integer& L, uint64 base, uint64 iterations, INUDUPLListener *nuduplListener) {
    
    if (enable_threads) {
        return repeated_square_fast_multithread(square_state, f, D, L, base, iterations, nuduplListener);
    } else {
        return repeated_square_fast_single_thread(square_state, f, D, L, base, iterations, nuduplListener);
    }
}
