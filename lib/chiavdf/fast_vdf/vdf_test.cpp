#include "include.h"

#include "parameters.h"

#include "bit_manipulation.h"
#include "double_utility.h"
#include "integer.h"

#include "asm_main.h"

#include "vdf_original.h"

#include "vdf_new.h"

#include "gpu_integer.h"
#include "gpu_integer_divide.h"

#include "gcd_base.h"
#include "gpu_integer_gcd.h"

#include "vdf_test.h"

#if VDF_MODE==0
    const bool test_correctness=false;
    const bool assert_on_rollback=false;
    const bool debug_rollback=false;
    const int repeated_square_checkpoint_interval=1<<10; //should be a power of 2
#endif

#if VDF_MODE==1
    const bool test_correctness=true;
    const bool assert_on_rollback=true;
    const bool debug_rollback=false;
    const int repeated_square_checkpoint_interval=1<<10;
#endif

using namespace std;
//using simd_integer_namespace::track_cycles_test;

//each thread updates a sequence number. the write is atomic on x86
//it also has an array of outputs that is append-only
//it will generate an output, do a mfence, then increment the sequence number non-atomically (since it is the only writer)
//it can also wait for another thread's outputs by spinning on its sequence number (with a timeout)
//error states:
//-any thread can change its sequence number to "error" which is the highest uint64 value
//-it will do this if any operation fails or if it spins too long waiting for another thread's output
//-also, the spin loop will error out if the other thread's sequence number is "error". this will make the spinning thread's sequence
// number also be "error"
//-once a thread has become "error", it will exit the code. the slave threads will wait on the barrier and the main thread will just
// exit the squaring function with a "false" output
//-the error state is the global sequence number with the msb set. this allows the sequence number to not be reset across calls
//will just make every state have a 48 bit global sequence number (enough for 22 years) plus a 16 bit local sequence number
//-the last local sequence number is the error state
//-there is no finish state since each state update will change the sequence number to a new, unique sequence number
//to start the squaring, the main thread will output A and B then increase its sequence number to the next global sequence number
//-slave threads will wait on this when they are done squaring or have outputted the error state
//-is is assumed that the main thread synchronizes with each slave thread to consume its output
//can probably write the synchronization code in c++ then because of how simple it is
//this is trivial to implement and should be reliable
//if the gcd generates too many matricies (more than 32 or so), it should generate an error
//need to write each output to a separate cache line
//will use the slave core for: cofactors for both gcds, calculate C at the start of the squaring, calculate (-v2*c)%a as the v2
// cofactor is being generated. this will use <0,-c> as the initial state instead of <0,1> and will also reduce everything modulo a
// after each matrix multiplication. it will also calculate C first.
//the slave core will then calculate the partial gcd and the master core will calculate the cofactors
//once the master core has calculated all of the cofactors, it will also know the final values of a_copy and k_copy from the
// slave core. the slave core is done now
//the master core will calculate the new values of A and B on its own. this can't be parallelized

//-have an asm gcd. nothing else is asm. will use gmp for everything else
//-the asm gcd takes unsigned inputs where a>=b. it returns unsigned outputs. its inputs are zero-padded to a fixed size
//-it modifes its inputs and returns a sequence of cofactor matricies
//-gmp has some utility functions to make this work easily. gmp can also calculate the new size. the resulting sign is always +
//--the sequence is outputted to a fixed size array of cache lines. there is also an output counter which should initially be 0
//-- and can be any pointer. the msb of the output counter is used to indicate the last output
//-the slave core is still used
//-gmp is close to optimal for the pentium machine so will just use it. for the fast machine, can use avx-512 if i have time. the gmp
//- division is still used but only to find the approximate inverse. the result quotient should be >= the actual quotient for exact
//- division to still work

//generic_stats track_cycles_total;

void square_original(form& f) {
    vdf_original::form f_in;
    f_in.a[0]=f.a.impl[0];
    f_in.b[0]=f.b.impl[0];
    f_in.c[0]=f.c.impl[0];

    vdf_original::form& f_res=*vdf_original::square(f_in);

    mpz_set(f.a.impl, f_res.a);
    mpz_set(f.b.impl, f_res.b);
    mpz_set(f.c.impl, f_res.c);
}

bool square_fast(form& f, const integer& d, const integer& L, int current_iteration) {
    form f_copy;
    if (test_correctness) {
        f_copy=f;
    }

    bool success=false;

    const int max_bits_ab=max_bits_base + num_extra_bits_ab;
    const int max_bits_c=max_bits_base + num_extra_bits_c;

    //sometimes the nudupl code won't reduce the output all the way. if it has too many bits it will get reduced by calling
    // square_original
    if (f.a.num_bits()<max_bits_ab && f.b.num_bits()<max_bits_ab && f.c.num_bits()<max_bits_c) {
        if (square_fast_impl(f, d, L, current_iteration)) {
            success=true;
        }
    }

    if (!success) {
        //this also reduces it
        print( "===square original===" );
        square_original(f);
    }

    if (test_correctness) {
        square_original(f_copy);
        form f_copy_2=f;
        f_copy_2.reduce();
        assert(f_copy_2==f_copy);
    }

    return true;
}

void output_error(form start, int location) {
    print( "=== error ===" );
    print(start.a.to_string());
    print(start.b.to_string());
    print(start.c.to_string());
    print(location);
    assert(false);
}

struct repeated_square {
    integer d;
    integer L;

    int64 checkpoint_iteration=0;
    form checkpoint;

    int64 current_iteration=0;
    form current;

    int64 num_iterations=0;

    bool error_mode=false;

    bool is_checkpoint() {
        return
            current_iteration==num_iterations ||
            (current_iteration & (repeated_square_checkpoint_interval-1)) == 0
        ;
    }

    void advance_fast(bool& did_rollback) {
        bool is_error=false;

        if (!square_fast(current, d, L, int(current_iteration))) {
            is_error=true;
        }

        if (!is_error) {
            ++current_iteration;
            if (is_checkpoint() && !current.check_valid(d)) {
                is_error=true;
            }
        }

        if (is_error) {
            if (debug_rollback) {
                print( "Rollback", current_iteration, " -> ", checkpoint_iteration );
            }

            current_iteration=checkpoint_iteration;
            current=checkpoint;
            error_mode=true;
            did_rollback=true;
            assert(!assert_on_rollback);
        }
    }

    void advance_error() {
        square_original(current);
        ++current_iteration;
    }

    void advance() {
        bool did_rollback=false;
        if (error_mode) {
            advance_error();
        } else {
            advance_fast(did_rollback);
        }

        if (!did_rollback && is_checkpoint()) {
            checkpoint_iteration=current_iteration;
            checkpoint=current;
            error_mode=false;
        }
    }

    repeated_square(integer t_d, form initial, int64 t_num_iterations) {
        d=t_d;
        L=root(-d, 4);
        //L=integer(1)<<512;

        checkpoint=initial;
        current=initial;
        num_iterations=t_num_iterations;

        while (current_iteration<num_iterations) {
            //todo if (current_iteration%10000==0) print(current_iteration);

            advance();
        }

        //required if reduce isn't done after each iteration
        current.reduce();
    }
};

int main(int argc, char* argv[]) {
    #if VDF_MODE!=0
        print( "=== Test mode ===" );
    #endif

    //integer ab_start_0(
        //"0x53098cff6d1cf3723235e44e397d7a7a77d254551ef35649381d0f2d192ab247d042d4d03005d188f0103aae267cc49515ae3d63b7513fb8d02da102ce2ff39c59a1e3ee9d4bbdb6011589d58f8e26a7c63fd342459fabefaa83ee65adbaf94d372ff6bbce71acdafb75aade3f39f5c7896490ff8b42b23ff337d414948adafb"
    //);
    //integer ab_start_1(
        //"0x1e38edea0e0b65dcd83702504bfa6ceb51df1774093a759280932d6f0097fb04f28dd6da814c2eb045621d9666271be86cf2dfbd1d630a3e4ccec0d2aeb5876100e4ca48783a601d65fc628e80b737f130f4f0c83d79a93738402fcd605b3c6f189cd0a99ff08fad6cd2d425d13284d1d121320261e7740aaab0b7a14718eeb7"
    //);
    //integer threshold(
        //"0xf68745a14f96317c568c660f2e4bcc3dbfd677e12911931303fb7afc4c5a6f637476e331f687ffdba09b7d51aa74f1caf416bcfa9532a1b911076302ac8f4ab8"
    //);

    //array<fixed_integer<uint64, 17>, 2> ab={fixed_integer<uint64, 17>(ab_start_0), fixed_integer<uint64, 17>(ab_start_1)};
    //array<fixed_integer<uint64, 17>, 2> uv;
    //int parity;
    //gcd_unsigned(
        //ab,
        //uv,
        //parity,
        //fixed_integer<uint64, 17>(threshold)
    //);

    //todo assert(false);

    //todo //set up thread affinity. make sure they are not hyperthreads on the same core if possible

    set_rounding_mode();

    vdf_original::init();

    integer d(argv[1]);
    int64 num_iterations=from_string<int64>(argv[2]);
    form d_initial=form::generator(d);

    //integer d(
        //"-0xaf0806241ecbc630fbbfd0c9d61c257c40a185e8cab313041cf029d6f070d58ecbc6c906df53ecf0dd4497b0753ccdbce2ebd9c80ae0032acce89096af642dd8c008403dd989ee5c1262545004fdcd7acf47908b983bc5fed17889030f0138e10787a8493e95ca86649ae8208e4a70c05772e25f9ac901a399529de12910a7a2c"
        //"3376292be9dba600fd89910aeccc14432b6e45c0456f41c177bb736915cad3332a74e25b3993f3e44728dc2bd13180132c5fb88f0490aeb96b2afca655c13dd9ab8874035e26dab16b6aad2d584a2d35ae0eaf00df4e94ab39fe8a3d5837dcab204c46d7a7b97b0c702d8be98c50e1bf8b649b5b6194fc3bae6180d2dd24d9f"
    //);
    //int64 num_iterations=1000;

    //form d_initial=form::from_abd(
        //integer(
            //"0x6a8f34028dad0dec9e765a5d761b9b041733e86d849b507ba346052f7b768a18d0283597b581e4b9e705dccc3d5197c66186940d5bdbee00784f51dc0f193cedf619e149a7b0fd48b8c4eb6d4bf925a9d634e138254f22007337415cea377655a0c2832592db32ce9b61d4937dcffd13c33bdf1ac5164a974cd9d61b14c81820"
        //),
        //integer(
            //"0x71c24869eed37be508e1751c21f49fcf16a68b42dec10cedf7376a036280f48a2c4b123d5f918ed4affa612a8dbacb4e6b5cdcaad439f3a5f0ab5a35ab6901025307c2ceaf54ab3bae5daae870817527dceb5fef9f7d6766a84bf843d9de74966fbd2bbad0200323876b90a3f4d9d135876a09f51225f126dd180412c658f4f"
        //),
        //d
    //);

    repeated_square c_square(d, d_initial, num_iterations);

    cout << c_square.current.a.impl << "\n";
    cout << c_square.current.b.impl;

    //track_max.output(512);

    //if (enable_track_cycles) {
        //print( "" );
        //print( "" );

        //for (int x=0;x<track_cycles_test.size();++x) {
            //if (track_cycles_test[x].entries.empty()) {
                //continue;
            //}
            //track_cycles_test[x].output(str( "track_cycles_test_#", x ));
        //}
    //}

    #ifdef GENERATE_ASM_TRACKING_DATA
    {
        using namespace asm_code;

        print( "" );

        map<string, double> tracking_data;

        for (int x=0;x<num_asm_tracking_data;++x) {
            if (!asm_tracking_data_comments[x]) {
                continue;
            }

            tracking_data[asm_tracking_data_comments[x]]=asm_tracking_data[x];
        }

        for (auto c : tracking_data) {
            string base_name;
            for (int x=0;x<c.first.size();++x) {
                if (c.first[x] == ' ') {
                    break;
                }
                base_name+=c.first[x];
            }

            auto base_i=tracking_data.find(base_name);
            double base=1;
            if (base_i!=tracking_data.end() && base_i->second!=0) {
                base=base_i->second;
            }

            print(c.first, c.second/base, "                                              ", base);
        }
    }
    #endif
}


/*void square_fast_impl(square_state& _) {
    const int max_bits_ab=max_bits_base + num_extra_bits_ab;

    //all divisions are exact

    //sometimes the nudupl code won't reduce the output all the way. if it has too many bits it will get reduced by calling
    // square_original
    bool too_many_bits;
    too_many_bits=(_.a.num_bits()>max_bits_ab || _.b.num_bits()>max_bits_ab);
    if (too_many_bits) {
        return false;
    }

    //if a<=L then this will return false; usually a has twice as many limbs as L
    bool a_too_small;
    a_too_small=(_.a.num_limbs()<=_.L.num_limbs()+1);
    if (a_too_small) {
        return false;
    }

    //only b can be negative
    //neither a or b can be 0; d=b^2-4ac is prime. if b=0, then d=-4ac=composite. if a=0, then d=b^2; d>=0
    //no constraints on which is greater
    //the gcd result is 1 because d=b^2-4ac ; assume gcd(a,b)!=1 ; a=A*s ; b=B*s ; s=gcd(a,b)!=1 ; d = (Bs)^2-4Asc
    // d = B^2*s^2 - 4sac = s(B^2*s - 4ac) ; d is not prime. d is supposed to be prime so this can't happen
    //the quadratic form might not be reduced all the way so it's possible for |b|>a. need to swap the inputs then
    // (they are copied anyway)
    //
    // U0*b + V0*a = 1
    // U1*b + V1*a = 0
    //
    // U0*b === 1 mod a
    // U1*b === 0 mod a
    U0=gcd(b, a, 0).u0;

    c=(b*b-D)/(a<<2);

    //start with <0,c> or <c,0> which is padded to 18 limbs so that the multiplications by 64 bits are exact (same with sums)
    //once the new values of uv are calculated, need to reduce modulo a, which is 17 limbs and has been normalized already
    //-the normalization also left shifted c
    //reducing modulo a only looks at the first couple of limbs so it has the same efficiency as doing it at the end
    //the modulo result is always nonnegative
    //
    // k+q*a=-U0*c
    k=(-U0*c)%a;

    // a>L so at least one input is >L initially
    //when this terminates, one input is >L and one is <=L
    //k is reduced modulo a, so |k|<|a|
    //a is positive
    //the result of mpz_mod is always nonnegative so k is nonnegative
    //
    // u0*a + v0*k = s ; s>L
    // u1*a + v1*k = t ; t<=L
    // v0*k === s mod a
    // v1*k === t mod a
    auto gcd2=gcd(a, k, L);
    v0=gcd2.v0
    v1=gcd2.v1
    s=gcd2.a
    t=gcd2.b

    // b*t + c*v1 === b*v1*k + c*v1 === v1(b*k+c) === v1(-U0*c*b+c) === c*v1*(1-U0*b) === c*v1*(1-1) === 0 mod a
    // b*t + c*v1 = b*(u0*a + v1*k) + c*v1 = b*u0*a + v1(b*k + c) = b*u0*a + v1(c - b*(U0*c+q*a))
    // = b*u0*a + v1(c - b*U0*c - b*q*a) = b*u0*a + v1(c - (1-V0*a)*c - b*q*a) = b*u0*a + v1(V0*a*c - b*q*a)
    // = a*(b*u0 + v1(V0*c - b*q))
    // ((b*t+c*v1)/a) = b*u0 + v1(V0*c - b*q) ; this is slower
    //
    // S = -1 if v1<=0, else 1
    // h = S*(b*t+c*v1)/a
    // j = t*t*S
    //
    // A=t*t+v1*((b*t+c*v1)/a)
    // A = j + v1*h
    A=t*t+v1*((b*t+c*v1)/a);

    if (v1<=0) {
        A=-A;
    }

    // e = 2t*(a + S*t*v0)/v1
    // e' = b - e
    // f = e' - 2*v0*h
    //
    //   (2*a*t + 2*A*v0)/v1
    // = (2*a*t + 2*j*v0 + 2*v1*v0*h)/v1
    // = (2*a*t + 2*j*v0)/v1 + 2*v0*h
    // = (2*a*t + 2*S*t*t*v0)/v1 + 2*v0*h
    // = 2t*(a + S*t*v0)/v1 + 2*v0*h
    // = e + 2*v0*h
    //
    // B = ( b - ((a*t+A*v0)*2)/v1 )%(A*2)
    //   = ( b - e - 2*v0*h )%(A*2)
    //   = ( e' - 2*v0*h )%(A*2)
    //   = f % (2A)
    B=( b - ((a*t+A*v0)*2)/v1 )%(A*2);

    A=abs(A)

    return true;
} */