#include "include.h"

#include "parameters.h"

#include "bit_manipulation.h"
#include "double_utility.h"
#include "integer.h"

#include "asm_main.h"

#include "vdf_original.h"

#include "vdf_new.h"
#include "picosha2.h"

#include "gpu_integer.h"
#include "gpu_integer_divide.h"

#include "gcd_base_continued_fractions.h"
//#include "gcd_base_divide_table.h"
#include "gcd_128.h"
#include "gcd_unsigned.h"

#include "gpu_integer_gcd.h"

#include "asm_types.h"

#include "threading.h"
#include "nucomp.h"
#include "vdf_fast.h"

#include "vdf_test.h"
#include <map>
#include <algorithm>

#include <thread>
#include <future>

#include <chrono>

#include "ClassGroup.h"
#include "Reducer.h"

#include <boost/asio.hpp>

bool warn_on_corruption_in_production=false;

using boost::asio::ip::tcp;


struct akashnil_form {
    // y = ax^2 + bxy + y^2
    mpz_t a;
    mpz_t b;
    mpz_t c;
    // mpz_t d; // discriminant
};

const int64_t THRESH = 1UL<<31;
const int64_t EXP_THRESH = 31;

std::vector<form> forms;

//always works
void repeated_square_original(vdf_original &vdfo, form& f, const integer& D, const integer& L, uint64 base, uint64 iterations, INUDUPLListener *nuduplListener) {
    vdf_original::form f_in,*f_res;
    f_in.a[0]=f.a.impl[0];
    f_in.b[0]=f.b.impl[0];
    f_in.c[0]=f.c.impl[0];
    f_res=&f_in;
    
    for (uint64_t i=0; i < iterations; i++) {
        f_res = vdfo.square(*f_res);
        
        if(nuduplListener!=NULL)
            nuduplListener->OnIteration(NL_FORM,f_res,base+i);
    }
    
    mpz_set(f.a.impl, f_res->a);
    mpz_set(f.b.impl, f_res->b);
    mpz_set(f.c.impl, f_res->c);
}

class WesolowskiCallback :public INUDUPLListener {
public:
    uint64_t kl;

    //struct form *forms;
    form result;

    bool deferred;
    int64_t switch_iters = -1;
    int64_t switch_index;
    int64_t iterations = 0; // This must be intialized to zero at start

    integer D;
    integer L;

    ClassGroupContext *t;
    Reducer *reducer;
    
    vdf_original* vdfo;

    WesolowskiCallback(uint64_t expected_space) {
        vdfo = new vdf_original();
        t=new ClassGroupContext(4096);
        reducer=new Reducer(*t);
    }

    ~WesolowskiCallback() {
        delete(vdfo);
        delete(reducer);
        delete(t);
    }

    void reduce(form& inf) {
#if 0
        // Old reduce from Sundersoft form
        inf.reduce();
#else
        // Pulmark reduce based on Akashnil reduce
        mpz_set(t->a, inf.a.impl);
        mpz_set(t->b, inf.b.impl);
        mpz_set(t->c, inf.c.impl);
    
        reducer->run();
    
        mpz_set(inf.a.impl, t->a);
        mpz_set(inf.b.impl, t->b);
        mpz_set(inf.c.impl, t->c);
#endif
    }

    void IncreaseConstants(int num_iters) {
        kl = 100;
        switch_iters = num_iters;
        switch_index = num_iters / 10;
    }

    int GetPosition(int power) {
        if (switch_iters == -1 || power < switch_iters) {
            return power / 10;
        } else {
            return (switch_index + (power - switch_iters) / 100);
        }
    }

    form *GetForm(int power) {
        return &(forms[GetPosition(power)]);
    }
    
    void OnIteration(int type, void *data, uint64 iteration)
    {
        iteration++;
        
        //cout << iteration << " " << maxiterations << endl;
        if(iteration%kl==0)
        {
            form *mulf=GetForm(iteration);
            // Initialize since it is raw memory
            // mpz_inits(mulf->a.impl,mulf->b.impl,mulf->c.impl,NULL);
            
            switch(type)
            {
                case NL_SQUARESTATE:
                {
                    //cout << "NL_SQUARESTATE" << endl;
                    uint64 res;
                
                    square_state_type *square_state=(square_state_type *)data;
                    
                    if(!square_state->assign(mulf->a, mulf->b, mulf->c, res))
                        cout << "square_state->assign failed" << endl;
                    break;
                }
                case NL_FORM:
                {
                    //cout << "NL_FORM" << endl;
                    
                    vdf_original::form *f=(vdf_original::form *)data;
           
                    mpz_set(mulf->a.impl, f->a);
                    mpz_set(mulf->b.impl, f->b);
                    mpz_set(mulf->c.impl, f->c);
                    break;
                }
                default:
                    cout << "Unknown case" << endl;
            }
            reduce(*mulf);
            
            iterations=iteration; // safe to access now
        }
    }
};

void ApproximateParameters(uint64_t T, uint64_t& L, uint64_t& k, uint64_t& w) {
    double log_memory = 23.25349666;
    double log_T = log2(T);
    L = 1;
    if (log_T - log_memory > 0.000001) {
        L = ceil(pow(2, log_memory - 20));
    }
    double intermediate = T * (double)0.6931471 / (2.0 * L);
    k = std::max(std::round(log(intermediate) - log(log(intermediate)) + 0.25), 1.0);
    //w = floor((double) T / ((double) T/k + L * (1 << (k+1)))) - 2;
    w = 2;
}

// thread safe; but it is only called from the main thread
void repeated_square(form f, const integer& D, const integer& L, WesolowskiCallback &weso, bool& stopped) {
    #ifdef VDF_TEST
        uint64 num_calls_fast=0;
        uint64 num_iterations_fast=0;
        uint64 num_iterations_slow=0;
    #endif

    uint64_t num_iterations = 0;

    while (!stopped) {
        uint64 c_checkpoint_interval=checkpoint_interval;

        if (weso.iterations >= 500000) {
            std::cout << "Stopping weso at 500000 iterations!\n";
            return ;
        }
        
        #ifdef VDF_TEST
            form f_copy;
            form f_copy_3;
            bool f_copy_3_valid=false;
            if (vdf_test_correctness) {
                f_copy=f;
                c_checkpoint_interval=1;

                f_copy_3=f;
                f_copy_3_valid=square_fast_impl(f_copy_3, D, L, num_iterations);
            }
        #endif

        uint64 batch_size=c_checkpoint_interval;

        #ifdef ENABLE_TRACK_CYCLES
            print( "track cycles enabled; results will be wrong" );
            repeated_square_original(*weso.vdfo, f, D, L, 100); //randomize the a and b values
        #endif

        // This works single threaded
        square_state_type square_state;
        square_state.pairindex=0;
        
        uint64 actual_iterations=repeated_square_fast(square_state, f, D, L, num_iterations, batch_size, &weso);
        
        #ifdef VDF_TEST
            ++num_calls_fast;
            if (actual_iterations!=~uint64(0)) num_iterations_fast+=actual_iterations;
        #endif

        #ifdef ENABLE_TRACK_CYCLES
            print( "track cycles actual iterations", actual_iterations );
            return; //exit the program
        #endif

        if (actual_iterations==~uint64(0)) {
            //corruption; f is unchanged. do the entire batch with the slow algorithm
            repeated_square_original(*weso.vdfo, f, D, L, num_iterations, batch_size, &weso);
            actual_iterations=batch_size;

            #ifdef VDF_TEST
                num_iterations_slow+=batch_size;
            #endif

            if (warn_on_corruption_in_production) {
                print( "!!!! corruption detected and corrected !!!!" );
            }
        }

        if (actual_iterations<batch_size) {
            //the fast algorithm terminated prematurely for whatever reason. f is still valid
            //it might terminate prematurely again (e.g. gcd quotient too large), so will do one iteration of the slow algorithm
            //this will also reduce f if the fast algorithm terminated because it was too big
            repeated_square_original(*weso.vdfo, f, D, L, num_iterations+actual_iterations, 1, &weso);

#ifdef VDF_TEST
                ++num_iterations_slow;
                if (vdf_test_correctness) {
                    assert(actual_iterations==0);
                    print( "fast vdf terminated prematurely", num_iterations );
                }
            #endif

            ++actual_iterations;
        }

        num_iterations+=actual_iterations;
        
        #ifdef VDF_TEST
            if (vdf_test_correctness) {
                form f_copy_2=f;
                weso.reduce(f_copy_2);

                repeated_square_original(&weso.vdfo, f_copy, D, L, actual_iterations);
                assert(f_copy==f_copy_2);
            }
        #endif
    }

    #ifdef VDF_TEST
        print( "fast average batch size", double(num_iterations_fast)/double(num_calls_fast) );
        print( "fast iterations per slow iteration", double(num_iterations_fast)/double(num_iterations_slow) );
    #endif
}

std::vector<unsigned char> ConvertIntegerToBytes(integer x, uint64_t num_bytes) {
    std::vector<unsigned char> bytes;
    bool negative = false;
    if (x < 0) {
        x = abs(x);
        x = x - integer(1);
        negative = true;
    }
    for (int iter = 0; iter < num_bytes; iter++) {
        auto byte = (x % integer(256)).to_vector();
        if (negative)
            byte[0] ^= 255;
        bytes.push_back(byte[0]);
        x = x / integer(256);
    }
    std::reverse(bytes.begin(), bytes.end());
    return bytes;
}

integer HashPrime(std::vector<unsigned char> s) {
    std::string prime = "prime";
    uint32_t j = 0;
    while (true) {
        std::vector<unsigned char> input(prime.begin(), prime.end());
        std::vector<unsigned char> j_to_bytes = ConvertIntegerToBytes(integer(j), 8);
        input.insert(input.end(), j_to_bytes.begin(), j_to_bytes.end());
        input.insert(input.end(), s.begin(), s.end());
        std::vector<unsigned char> hash(picosha2::k_digest_size);
        picosha2::hash256(input.begin(), input.end(), hash.begin(), hash.end());
        
        integer prime_integer;
        for (int i = 0; i < 16; i++) {
            prime_integer *= integer(256);
            prime_integer += integer(hash[i]);
        }
        if (prime_integer.prime()) {
            return prime_integer;
        }
        j++;
    }
}

std::vector<unsigned char> SerializeForm(WesolowskiCallback &weso, form &y, int int_size) {
    //weso.reduce(y);
    y.reduce();
    std::vector<unsigned char> res = ConvertIntegerToBytes(y.a, int_size);
    std::vector<unsigned char> b_res = ConvertIntegerToBytes(y.b, int_size);
    res.insert(res.end(), b_res.begin(), b_res.end());
    return res;
}

integer GetB(WesolowskiCallback &weso, integer& D, form &x, form& y) {
    int int_size = (D.num_bits() + 16) >> 4;
    std::vector<unsigned char> serialization = SerializeForm(weso, x, int_size);
    std::vector<unsigned char> serialization_y = SerializeForm(weso, y, int_size);
    serialization.insert(serialization.end(), serialization_y.begin(), serialization_y.end());
    return HashPrime(serialization);
}

integer FastPow(uint64_t a, uint64_t b, integer& c) {
    if (b == 0)
        return integer(1);

    integer res = FastPow(a, b / 2, c);
    res = res * res;
    res = res % c;
    if (b % 2) {
        res = res * integer(a);
        res = res % c;
    }
    return res;
}

form FastPowForm(form &x, const integer& D, uint64_t num_iterations) {
    if (num_iterations == 0)
        return form::identity(D);
    
    form res = FastPowForm(x, D, num_iterations / 2);
    res = res * res;
    if (num_iterations % 2)
	res = res * x;
    return res;
}

uint64_t GetBlock(uint64_t i, uint64_t k, uint64_t T, integer& B) {
    integer res(1 << k);
    res *= FastPow(2, T - k * (i + 1), B);
    res = res / B;
    auto res_vector = res.to_vector();
    return res_vector[0];
}

std::string BytesToStr(const std::vector<unsigned char> &in)
{
    std::vector<unsigned char>::const_iterator from = in.cbegin();
    std::vector<unsigned char>::const_iterator to = in.cend();
    std::ostringstream oss;
    for (; from != to; ++from)
       oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(*from);
    return oss.str();
}

struct Proof {
    Proof() {

    }

    Proof(std::vector<unsigned char> y, std::vector<unsigned char> proof) {
        this->y = y;
        this->proof = proof;
    }

    string hex() {
        std::vector<unsigned char> bytes(y);
        bytes.insert(bytes.end(), proof.begin(), proof.end());
        return BytesToStr(bytes);
    }

    std::vector<unsigned char> y;
    std::vector<unsigned char> proof;
};

#define PULMARK 1

form GenerateProof(form &y, form &x_init, integer &D, uint64_t done_iterations, uint64_t num_iterations, uint64_t k, uint64_t l, WesolowskiCallback& weso, bool& stop_signal) {
    auto t1 = std::chrono::high_resolution_clock::now();

#if PULMARK
    ClassGroupContext *t;
    Reducer *reducer;
    
    t=new ClassGroupContext(4096);
    reducer=new Reducer(*t);
#endif
    
    integer B = GetB(weso, D, x_init, y);
    integer L=root(-D, 4);

    uint64_t k1 = k / 2;
    uint64_t k0 = k - k1;

    form x = form::identity(D);    

    for (int64_t j = l - 1; j >= 0; j--) {
        x=FastPowForm(x, D, (1 << k));
     
        std::vector<form> ys((1 << k));
        for (uint64_t i = 0; i < (1 << k); i++)
            ys[i] = form::identity(D);  

        form *tmp;
        for (uint64_t i = 0; !stop_signal && i < ceil(1.0 * num_iterations / (k * l)); i++) {
            if (num_iterations >= k * (i * l + j + 1)) {
                uint64_t b = GetBlock(i*l + j, k, num_iterations, B);
                tmp = weso.GetForm(done_iterations + i * k * l);
                nucomp_form(ys[b], ys[b], *tmp, D, L);
#if PULMARK
                // Pulmark reduce based on Akashnil reduce
                mpz_set(t->a, ys[b].a.impl);
                mpz_set(t->b, ys[b].b.impl);
                mpz_set(t->c, ys[b].c.impl);
                
                reducer->run();
                
                mpz_set(ys[b].a.impl, t->a);
                mpz_set(ys[b].b.impl, t->b);
                mpz_set(ys[b].c.impl, t->c);
#else
                ys[b].reduce();
#endif
            }
        }

        if (stop_signal)
            return form();

        for (uint64_t b1 = 0; b1 < (1 << k1) && !stop_signal; b1++) {
            form z = form::identity(D);    
            for (uint64_t b0 = 0; b0 < (1 << k0) && !stop_signal; b0++) {
                nucomp_form(z, z, ys[b1 * (1 << k0) + b0], D, L);
#if PULMARK
                // Pulmark reduce based on Akashnil reduce
                mpz_set(t->a, z.a.impl);
                mpz_set(t->b, z.b.impl);
                mpz_set(t->c, z.c.impl);
                
                reducer->run();
                
                mpz_set(z.a.impl, t->a);
                mpz_set(z.b.impl, t->b);
                mpz_set(z.c.impl, t->c);
#else
                z.reduce();
#endif
            }
            z = FastPowForm(z, D, b1 * (1 << k0));
            x = x * z;
        }

        for (uint64_t b0 = 0; b0 < (1 << k0) && !stop_signal; b0++) {
            form z = form::identity(D);    
            for (uint64_t b1 = 0; b1 < (1 << k1) && !stop_signal; b1++) {
                nucomp_form(z, z, ys[b1 * (1 << k0) + b0], D, L);
#if PULMARK
                // Pulmark reduce based on Akashnil reduce
                mpz_set(t->a, z.a.impl);
                mpz_set(t->b, z.b.impl);
                mpz_set(t->c, z.c.impl);
                
                reducer->run();
                
                mpz_set(z.a.impl, t->a);
                mpz_set(z.b.impl, t->b);
                mpz_set(z.c.impl, t->c);
#else
                z.reduce();
#endif
            }
            z = FastPowForm(z, D, b0);
            x = x * z;
        }

        if (stop_signal)
            return form();
    }

#if PULMARK
    // Pulmark reduce based on Akashnil reduce
    mpz_set(t->a, x.a.impl);
    mpz_set(t->b, x.b.impl);
    mpz_set(t->c, x.c.impl);
    
    reducer->run();
    
    mpz_set(x.a.impl, t->a);
    mpz_set(x.b.impl, t->b);
    mpz_set(x.c.impl, t->c);
    
    delete(reducer);
    delete(t);
#else
    x.reduce();
#endif
    
    auto t2 = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(t2 - t1).count();
    return x;
}

void GenerateProofThreaded(std::promise<form> && form_promise, form y, form x_init, integer D, uint64_t done_iterations, uint64_t num_iterations, uint64_t
k, uint64_t l, WesolowskiCallback& weso, bool& stop_signal) {
    form proof = GenerateProof(y, x_init, D, done_iterations, num_iterations, k, l, weso, stop_signal);
    form_promise.set_value(proof);
}

Proof CreateProofOfTimeWesolowski(integer& D, form x, int64_t num_iterations, uint64_t done_iterations, WesolowskiCallback& weso, bool& stop_signal) {
    uint64_t l, k, w;
    form x_init = x;
    integer L=root(-D, 4);

    k = 10;
    w = 2;
    l = (num_iterations >= 10000000) ? 10 : 1;

    while (!stop_signal && weso.iterations < done_iterations + num_iterations) {
        std::this_thread::sleep_for (std::chrono::seconds(3));
    }

    if (stop_signal)
        return Proof();
    
    vdf_original vdfo_proof;
    
    uint64 checkpoint = (done_iterations + num_iterations) - (done_iterations + num_iterations) % 100;
    //mpz_init(y.a.impl);
    //mpz_init(y.b.impl);
    //mpz_init(y.c.impl);
    form y = forms[weso.GetPosition(checkpoint)];
    repeated_square_original(vdfo_proof, y, D, L, 0, (done_iterations + num_iterations) % 100, NULL);

    auto proof = GenerateProof(y, x_init, D, done_iterations, num_iterations, k, l, weso, stop_signal);

    if (stop_signal)
        return Proof();

    int int_size = (D.num_bits() + 16) >> 4;

    std::vector<unsigned char> y_bytes = SerializeForm(weso, y, 129);
    std::vector<unsigned char> proof_bytes = SerializeForm(weso, proof, int_size);
    Proof final_proof=Proof(y_bytes, proof_bytes);

    return final_proof;
}

Proof CreateProofOfTimeNWesolowski(integer& D, form x, int64_t num_iterations, 
                                   uint64_t done_iterations, WesolowskiCallback& weso, int depth_limit, int depth, bool& stop_signal) {
    uint64_t l, k, w;
    int64_t iterations1, iterations2;
    integer L=root(-D, 4);
    form x_init = x;
    
    k = 10;
    w = 2;
    l = (num_iterations >= 10000000) ? 10 : 1;
    iterations1 = num_iterations * w / (w + 1);
    
    // NOTE(Florin): This is still suboptimal,  
    // some work can still be lost if weso iterations is in between iterations1 and num_iterations.
    if (weso.iterations >= done_iterations + num_iterations) {
        iterations1 = (done_iterations + num_iterations) / 3;
    }

    iterations1 = iterations1 - iterations1 % 100;
    iterations2 = num_iterations - iterations1;

    while (!stop_signal && weso.iterations < done_iterations + iterations1) {
        std::this_thread::sleep_for (std::chrono::seconds(3));
    }

    if (stop_signal)
        return Proof();    

    form y1 = *weso.GetForm(done_iterations + iterations1);

    std::promise<form> form_promise;
    auto form_future = form_promise.get_future();

    std::thread t(&GenerateProofThreaded, std::move(form_promise), y1, x_init, D, done_iterations, iterations1, k, l, std::ref(weso), std::ref(stop_signal));

    Proof proof2;
    if (depth < depth_limit - 1) {
        proof2 = CreateProofOfTimeNWesolowski(D, y1, iterations2, done_iterations + iterations1, weso, depth_limit, depth + 1, stop_signal);
    } else {
        proof2 = CreateProofOfTimeWesolowski(D, y1, iterations2, done_iterations + iterations1, weso, stop_signal);
    }

    t.join();
    if (stop_signal)    
        return Proof();
    form proof = form_future.get();

    int int_size = (D.num_bits() + 16) >> 4;
    Proof final_proof;
    final_proof.y = proof2.y;
    std::vector<unsigned char> proof_bytes(proof2.proof);
    std::vector<unsigned char> tmp = ConvertIntegerToBytes(integer(iterations1), 8);
    proof_bytes.insert(proof_bytes.end(), tmp.begin(), tmp.end());
    tmp.clear();
    tmp = SerializeForm(weso, y1, int_size);
    proof_bytes.insert(proof_bytes.end(), tmp.begin(), tmp.end());
    tmp.clear();
    tmp = SerializeForm(weso, proof, int_size);
    proof_bytes.insert(proof_bytes.end(), tmp.begin(), tmp.end());
    final_proof.proof = proof_bytes;
    return final_proof;
} 

std::mutex socket_mutex;

void NWesolowskiMain(integer D, form x, int64_t num_iterations, WesolowskiCallback& weso, bool& stop_signal, tcp::socket& sock) {
    Proof result = CreateProofOfTimeNWesolowski(D, x, num_iterations, 0, weso, 2, 0, stop_signal);
    if (stop_signal == true) {
        std::cout << "Got stop signal before completing the proof!\n";
        return ;
    }
    std::vector<unsigned char> bytes = ConvertIntegerToBytes(integer(num_iterations), 8);
    bytes.insert(bytes.end(), result.y.begin(), result.y.end());
    bytes.insert(bytes.end(), result.proof.begin(), result.proof.end());  
    std::string str_result = BytesToStr(bytes);  
    std::lock_guard<std::mutex> lock(socket_mutex);
    std::cout << "Generated proof = " << str_result << "\n";
    boost::asio::write(sock, boost::asio::buffer(str_result.c_str(), str_result.size()));
}

void PollTimelord(tcp::socket& sock, bool& got_iters) {
    // Wait for 60s, if no iters come, poll each 15 seconds the timelord.
    int seconds = 0;
    while (!got_iters) {
        std::this_thread::sleep_for (std::chrono::seconds(1));
        seconds++;
        if (seconds >= 60 && (seconds - 60) % 15 == 0) {
            socket_mutex.lock();
            boost::asio::write(sock, boost::asio::buffer("POLL", 4));
            socket_mutex.unlock();
        }
    }
}

const int max_length = 2048;

void session(tcp::socket sock) {
    try {
        char disc[350];
        char disc_size[5];
        boost::system::error_code error;

        memset(disc,0x00,sizeof(disc)); // For null termination
        memset(disc_size,0x00,sizeof(disc_size)); // For null termination
        
        boost::asio::read(sock, boost::asio::buffer(disc_size, 3), error);
        int disc_int_size = atoi(disc_size);

        boost::asio::read(sock, boost::asio::buffer(disc, disc_int_size), error);

        integer D(disc);

        std::cout << "Discriminant = " << D.impl << "\n";

        // Init VDF the discriminant...

        if (error == boost::asio::error::eof)
            return ; // Connection closed cleanly by peer.
        else if (error)
            throw boost::system::system_error(error); // Some other error.

        if (getenv( "warn_on_corruption_in_production" )!=nullptr) {
            warn_on_corruption_in_production=true;
        }
        if (is_vdf_test) {
            print( "=== Test mode ===" );
        }
        if (warn_on_corruption_in_production) {
            print( "=== Warn on corruption enabled ===" );
        }
        assert(is_vdf_test); //assertions should be disabled in VDF_MODE==0
        init_gmp();
        allow_integer_constructor=true; //make sure the old gmp allocator isn't used
        set_rounding_mode();

        integer L=root(-D, 4);
        form f=form::generator(D);

        bool stop_signal = false;
        std::set<uint64_t> seen_iterations;

        std::vector<std::thread> threads;
        WesolowskiCallback weso(1000000);
        
        //mpz_init(weso.forms[0].a.impl);
        //mpz_init(weso.forms[0].b.impl);
        //mpz_init(weso.forms[0].c.impl);
        
        forms[0]=f;
        weso.D = D;
        weso.L = L;
        weso.kl = 10;

        bool stopped = false;
        bool got_iters = false;
        std::thread vdf_worker(repeated_square, f, D, L, std::ref(weso), std::ref(stopped));
        std::thread poll_thread(PollTimelord, std::ref(sock), std::ref(got_iters));

        // Tell client that I'm ready to get the challenges. 
        boost::asio::write(sock, boost::asio::buffer("OK", 2));
        char data[10];

        while (!stopped) {
            memset(data, 0, sizeof(data));
            boost::asio::read(sock, boost::asio::buffer(data, 1), error);
            int size = data[0] - '0';
            memset(data, 0, sizeof(data));
            boost::asio::read(sock, boost::asio::buffer(data, size), error);
            int iters = atoi(data);
            std::cout << "Got iterations " << iters << "\n";
            got_iters = true;
            if (seen_iterations.size() > 0 && *seen_iterations.begin() <= iters) {
                std::cout << "Ignoring..." << iters << "\n";
                continue;
            }

            if (seen_iterations.size() > 2 && iters != 0) {
                std::cout << "Ignoring..." << iters << "\n";
                continue;
            }

            if (iters == 0) {
                stopped = true;
                poll_thread.join();
                for (int t = 0; t < threads.size(); t++) {
                    threads[t].join();
                }
                vdf_worker.join();
            } else {
                if (seen_iterations.find(iters) == seen_iterations.end()) {
                    seen_iterations.insert(iters);
                    threads.push_back(std::thread(NWesolowskiMain, D, f, iters, std::ref(weso), std::ref(stopped), 
                                                  std::ref(sock)));
                }
            }
        }
        // Tell client I've stopped everything, wait for ACK and close.
        std::lock_guard<std::mutex> lock(socket_mutex);
        boost::asio::write(sock, boost::asio::buffer("STOP", 4));
        std::cout << "Stopped everything! Ready for the next challenge.\n";

        char ack[5];
        memset(ack,0x00,sizeof(ack));
        boost::asio::read(sock, boost::asio::buffer(ack, 3), error);
        assert (strncmp(ack, "ACK", 3) == 0);
    } catch (std::exception& e) {
        std::cerr << "Exception in thread: " << e.what() << "\n";
    }
}

void server(boost::asio::io_context& io_context, unsigned short port)
{
  tcp::acceptor a(io_context, tcp::endpoint(tcp::v4(), port));
  for (;;)
  {
    std::thread t(session, a.accept());
    t.join();
  }
}

int main(int argc, char* argv[])
{ 
  forms.reserve(1000000);
  for (int i = 0; i < 1000000; i++) {
      mpz_inits(forms[i].a.impl, forms[i].b.impl, forms[i].c.impl, NULL);
  }
  try
  {
    if (argc != 2)
    {
      std::cerr << "Usage: blocking_tcp_echo_server <port>\n";
      return 1;
    }

    boost::asio::io_context io_context;

    server(io_context, std::atoi(argv[1]));
  }
  catch (std::exception& e)
  {
    std::cerr << "Exception: " << e.what() << "\n";
  }

  return 0;
}