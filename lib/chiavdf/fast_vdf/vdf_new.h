#ifndef VDF_NEW
#define VDF_NEW

void normalize(integer& a, integer& b, integer& c) {
    integer r = (a-b)/(a<<1);

    //todo print( "normalize r=", r.to_string() );

    integer A = a;
    integer B = b + ((r*a)<<1);
    integer C = a*r*r + b*r + c;

    // r=0:
    // A=a
    // B=b
    // C=c

    // r=1:
    // A=a
    // B=b+2a
    // C=a+b+c

    a=A;
    b=B;
    c=C;
}

void reduce_impl(integer& a, integer& b, integer& c) {
    integer s = (c+b)/(c<<1);

    //todo print( "reduce s=", s.to_string() );

    integer A = c;
    integer B = ((s*c)<<1) - b;
    integer C = c*s*s - b*s+a;

    a=A;
    b=B;
    c=C;
}

void reduce(integer& a, integer& b, integer& c) {
    /*TRACK_MAX(a); // 2
    TRACK_MAX(b); // 3
    TRACK_MAX(c); // 4
    */

    normalize(a, b, c);

    /*TRACK_MAX(a); // 2
    TRACK_MAX(b); // 2
    TRACK_MAX(c); // 2
    */

    int iter=0;
    while (a>c || (a==c && b<0)) {
        reduce_impl(a, b, c);
        ++iter;

        /*if (iter==1) {
            TRACK_MAX(a); // 2
            TRACK_MAX(b); // 2
            TRACK_MAX(c); // 2
        }*/
    }

    normalize(a, b, c);
}

void generator_for_discriminant(const integer& d, integer& a, integer& b, integer& c) {
    a=2;
    b=1;

    c = (b*b - d)/(a<<2);

    reduce(a, b, c);
}

void square(integer& a, integer& b, integer& c) {
    gcd_res r=gcd(b, a);

    integer u=(c/r.gcd*r.s)%a;

    integer A = a*a;
    integer B = b - ((a*u)<<1);
    integer C = u*u - (b*u-c)/a;

    a=A;
    b=B;
    c=C;
}

//reduced bounds:
// |b| <= a
// |a|< = sqrt(-d/3) <= sqrt(|d|)
// |c| = |(b^2-d)/(4a)| <= |b^2-d| = |b^2+|d|| <= |a^2+|d|| <= |-d/3+|d|| = ||d|/3+|d|| = |2/3*|d|| <= |d|
// a and b have half as many bits as d (rounded up). c can have as many bits as d (but it is usually half)
// |ac| = |(b^2-d)/(4)| <= |b^2-d| <= |d|
// |bc| <= |ac| <= |d|
// b is odd:
//  assume b=2n (even)
//  d = b^2-4ac = 4n^2 - 4ac = multiple of 4
//  d is prime so it is odd (contradiction)
struct form {
    integer a;
    integer b;
    integer c;

    static form from_abd(const integer& t_a, const integer& t_b, const integer& d) {
        form res;
        res.a=t_a;
        res.b=t_b;
        res.c=(t_b*t_b - d);

        if (t_a <= integer(0))
            throw std::runtime_error("Invalid form. Positive a");
        if (res.c % (t_a<<2) != integer(0))
            throw std::runtime_error("Invalid form. Can't find c.");

        res.c/=(t_a<<2);

        res.reduce();

        return res;
    }

    static form identity(const integer& d) {
        return from_abd(integer(1), integer(1), d);
    }

    static form generator(const integer& d) {
        return from_abd(integer(2), integer(1), d);
    }
    
    void reduce() {
        ::reduce(a, b, c);
    }

    form inverse() const {
        form res=*this;
        res.b=-res.b;
        res.reduce(); //doesn't do anything unless |a|==|b|
        return res;
    }

    bool check_valid(const integer& d) {
        return b*b-integer(4)*a*c==d;
    }

    void assert_valid(const integer& d) {
        assert(check_valid(d));
    }

    bool operator==(const form& f) const {
        return a==f.a && b==f.b && c==f.c;
    }

    bool operator<(const form& f) const {
        return make_tuple(a, b, c)<make_tuple(f.a, f.b, f.c);
    }

    //assumes this is normalized (c has the highest magnitude)
    //the inverse has the same hash
    int hash() const {
        uint64 res=c.to_vector()[0];
        return int((res>>4) & ((1ull<<31)-1)); //ignoring some of the lower bits because they might not be random enough
    }
};

integer generate_discriminant(int num_bits, int seed=-1) {
    integer res=rand_integer(num_bits, seed);
    while (true) {
        mpz_nextprime(res.impl, res.impl);
        if ((res % integer(8)) == integer(7)) {
            break;
        }
    }
    return -res;
}

form square(const form& f) {
    form res=f;
    square(res.a, res.b, res.c);
    res.reduce();
    return res;
}

//inputs are: unsigned, unsigned, signed
integer three_gcd(integer a, integer b, integer c) {
    auto res1=gcd(a, b);
    auto res2=gcd(res1.gcd, c);
    return res2.gcd;
}

gcd_res test_gcd(integer a_signed, integer b_signed, int index=0) {
    bool a_negative=a_signed<integer(0);
    bool b_negative=b_signed<integer(0);

    integer a=abs(a_signed);
    integer b=abs(b_signed);

    integer u0;
    integer u1;
    int parity;

    if (a<b) {
        swap(a, b);
        u0=0;
        u1=1;
        parity=-1;
    }  else {
        u0=1;
        u1=0;
        parity=1;
    }

    int iter=0;
    while (b!=integer(0)) {
        /*if (iter==0 && index==0) {
            TRACK_MAX(a); // 2
            TRACK_MAX(b); // 2
            TRACK_MAX(u0); // 0.03
            TRACK_MAX(u1); // 0.03
        }
        if (iter==1 && index==0) {
            TRACK_MAX(a); // 2
            TRACK_MAX(b); // 2
            TRACK_MAX(u0); // 0.25
            TRACK_MAX(u1); // 0.55
        }
        if (iter==2 && index==0) {
            TRACK_MAX(a); // 2
            TRACK_MAX(b); // 2
            TRACK_MAX(u0); // 0.55
            TRACK_MAX(u1); // 0.60
        }
        if (iter==0 && index==1) {
            TRACK_MAX(a); // 2
            TRACK_MAX(b); // 1
            TRACK_MAX(u0); // 0.03
            TRACK_MAX(u1); // 0.03
        }
        if (iter==1 && index==1) {
            TRACK_MAX(a); // 1
            TRACK_MAX(b); // 1
            TRACK_MAX(u0); // 0.03
            TRACK_MAX(u1); // 0.25
        }
        if (iter==2 && index==1) {
            TRACK_MAX(a); // 1
            TRACK_MAX(b); // 1
            TRACK_MAX(u0); // 0.25
            TRACK_MAX(u1); // 0.28
        }*/

        integer q=a/b;
        integer r=a%b;

        a=b;
        b=r;

        integer u1_new=u0 + q*u1;

        u0=u1;
        u1=u1_new;
        parity=-parity;

        ++iter;
    }

    gcd_res res;
    res.gcd=a;
    res.s=u0;
    if (a_negative != (parity==-1)) {
        res.s=-res.s;
    }

    {
        auto expected_gcd_res=gcd(a_signed, b_signed);
        assert(expected_gcd_res.gcd==res.gcd);
        assert(expected_gcd_res.s==res.s);
    }

    return res;
}

//a and b are N bits and m is M bits; outputs are M bits
//a and b are signed and m is unsigned
//mu and v are unsigned
void solve_linear_congruence(const integer& a, const integer& b, const integer& m, integer& mu, integer& v, int index=0) {
    // g = gcd(a, m), and da + em = g
    //one round of the euclidean algorithm will equalize the sizes of the inputs; a is signed and m is unsigned

    gcd_res gcd_r;
    if (false) {
        gcd_r=test_gcd(a, m, index);
    } else {
        gcd_r=gcd(a, m);
    }
    integer g=gcd_r.gcd; //min(N,M) bits unsigned
    integer d=gcd_r.s; //max(N,M) bits signed

    // q = b/g, r = b % g
    integer q=b/g; //N bits ; signed/unsigned = signed
    integer r=b%g;
    assert(r==integer(0));

    mu=(q*d)%m; //N+M bits mod M bits => M bits ; signed*signed mod unsigned = unsigned
    v=m/g; //M bits unsigned
}

//f1.a,f1.b,f2.a,f2.b are N bits and f1.c,f2.c are 2N bits. a/c are unsigned and b is signed
form multiply(const form& f1, const form& f2) {
    form f3;

    integer g = (f2.b + f1.b) / integer(2); //N bits signed; sum is odd+odd which is even
    integer h = (f2.b - f1.b) / integer(2); //N bits signed; sum is odd-odd which is even

    integer w = three_gcd(f1.a, f2.a, g); //N bits unsigned

    integer j = w; //N bits unsigned
    //integer r = 0;
    integer s = f1.a / w; //N bits unsigned
    integer t = f2.a / w; //N bits unsigned
    integer u = g / w; //N bits signed

    integer k_temp;
    integer constant_factor;
    solve_linear_congruence(
        t * u,            //2N bits signed
        h * u + s * f1.c, // f1.a * f1.c is 2N bits; 2N+1 bits; signed+unsigned = signed
        s * t,            //2N bits unsigned
        k_temp,           //2N bits (same as m argument); unsigned
        constant_factor,  //2N bits (same as m argument); unsigned
        0
    );

    integer n;
    integer constant_factor_2;
    solve_linear_congruence(
        t * constant_factor,    //3N bits signed
        h - t * k_temp,         //3N bits signed - unsigned = signed
        s,                      //N bits unsigned
        n,                      //N bits unsigned
        constant_factor_2,      //N bits unsigned
        1
    );

    integer k = k_temp + constant_factor * n; //4N bits unsigned
    integer l = (t*k - h) / s; //5N bits signed / unsigned = signed
    integer m = (t*u*k - h*u - s*f1.c) / (s*t); //6N bits divided by 2N bits => 6N bits ; signed / unsigned = signed

    f3.a = s*t; //2N bits unsigned
    f3.b = (j*u) - (k*t + l*s); //6N bits signed
    f3.c = k*l - j*m; //9N bits unsigned (result must be nonnegative)

    //experimental values (multiplies of d/2 bits)
    //with 100 bits d:
    // 50 bits - 2x 32-bit words
    //100 bits - 4x 32-bit words
    //150 bits - 5x 32-bit words
    //200 bits - 7x 32-bit words
    /*
    TRACK_MAX(g);                               // 1
    TRACK_MAX(h);                               // 1
    TRACK_MAX(w);                               // 1
    TRACK_MAX(s);                               // 1
    TRACK_MAX(t);                               // 1
    TRACK_MAX(u);                               // 1
    TRACK_MAX(t*u);                             // 2
    TRACK_MAX(s * f1.c);                        // 2
    TRACK_MAX(h * u + s * f1.c);                // 2
    TRACK_MAX(s*t);                             // 2
    TRACK_MAX(k_temp);                          // 2
    TRACK_MAX(constant_factor);                 // 1
    TRACK_MAX(n);                               // 1
    TRACK_MAX(constant_factor_2);               // 1
    TRACK_MAX(t * constant_factor);             // 2
    TRACK_MAX(t * k_temp);                      // 3
    TRACK_MAX(h - t * k_temp);                  // 3
    TRACK_MAX(constant_factor * n);             // 2
    TRACK_MAX(k_temp + constant_factor * n);    // 2
    TRACK_MAX(t*k);                             // 3
    TRACK_MAX(t*k - h);                         // 3
    TRACK_MAX((t*k - h) / s);                   // 2
    TRACK_MAX(t*u);                             // 2
    TRACK_MAX(u*k);                             // 3
    TRACK_MAX(t*k);                             // 3
    TRACK_MAX(t*u*k);                           // 4
    TRACK_MAX(h*u);                             // 2
    TRACK_MAX(s*f1.c);                          // 2
    TRACK_MAX(t*u*k - h*u - s*f1.c);            // 4
    TRACK_MAX(s*t);                             // 2
    TRACK_MAX((t*u*k - h*u - s*f1.c) / (s*t));  // 2
    TRACK_MAX(s*t);                             // 2
    TRACK_MAX(j*u);                             // 1
    TRACK_MAX(k*t);                             // 3
    TRACK_MAX(l*s);                             // 3
    TRACK_MAX((j*u) - (k*t + l*s));             // 3
    TRACK_MAX(k*l);                             // 4
    TRACK_MAX(j*m);                             // 2
    TRACK_MAX(k*l - j*m);                       // 4
    TRACK_MAX(f3.a);                            // 2
    TRACK_MAX(f3.b);                            // 3
    TRACK_MAX(f3.c);                            // 4
    */

    f3.reduce();
    return f3;
}

form operator*(const form& a, const form& b) {
    if (&a==&b) {
        return square(a);
    } else {
        return multiply(a, b);
    }
}

/*integer arg_discriminant;
int arg_iterations;

void parse_args(int argc, char** argv) {
    arg_discriminant=integer(
        "-0xdc2a335cd2b355c99d3d8d92850122b3d8fe20d0f5360e7aaaecb448960d57bcddfee12a229bbd8d370feda5a17466fc725158ebb78a2a7d37d0a226d89b54434db9c3be9a9bb6ba2c2cd079221d873a17933ceb81a37b0665b9b7e247e8df66bdd45eb15ada12326db01e26c861adf0233666c01dec92bbb547df7369aed3b1fbdff867cfc670511cc270964fbd98e5c55fbe0947ac2b9803acbfd935f3abb8d9be6f938aa4b4cc6203f53c928a979a2f18a1ff501b2587a93e95a428a107545e451f0ac6c7f520a7e99bf77336b1659a2cb3dd1b60e0c6fcfffc05f74cfa763a1d0af7de9994b6e35a9682c4543ae991b3a39839230ef84dae63e88d90f457"
    );
    arg_iterations=1000;

    if (argc==1) {
    } else
    if (argc==2) {
        arg_iterations=from_string<int>(argv[1]);
    } else
    if (argc==3) {
        arg_discriminant=integer(argv[1]);
        arg_iterations=from_string<int>(argv[2]);
    } else {
        assert(false);
    }
}**/

#endif // VDF_NEW
