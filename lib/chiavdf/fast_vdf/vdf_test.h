bool square_fast_impl(form& f, const integer& D, const integer& L, int current_iteration) {
    const int max_bits_ab=max_bits_base + num_extra_bits_ab;
    const int max_bits_c=max_bits_base + num_extra_bits_ab*2;

    //sometimes the nudupl code won't reduce the output all the way. if it has too many bits it will get reduced by calling
    // square_original
    if (!(f.a.num_bits()<max_bits_ab && f.b.num_bits()<max_bits_ab && f.c.num_bits()<max_bits_c)) {
        return false;
    }

    print("f");

    integer a=f.a;
    integer b=f.b;
    integer c=f.c;

    fixed_integer<uint64, 17> a_int(a);
    fixed_integer<uint64, 17> b_int(b);
    fixed_integer<uint64, 17> c_int(c);
    fixed_integer<uint64, 17> L_int(L); //actual size is 8 limbs; padded to 17
    fixed_integer<uint64, 33> D_int(D); //padded by an extra limb

    //2048 bit D, basis is 512; one limb is 0.125; one bit is 0.002
    //TRACK_MAX(a); // a, 2.00585 <= bits (multiple of basis), 0 <= is negative
    //TRACK_MAX(b); // b, 2.00585, 0
    //TRACK_MAX(c); // c, 2.03125, 0

    //can just look at the top couple limbs of a for this
    assert((a<=L)==(a_int<=L_int));
    if (a_int<=L_int) {
        return false;
    }

    integer v2;
    fixed_integer<uint64, 17> v2_int;
    {
        gcd_res g=gcd(b, a);
        assert(g.gcd==1);
        v2=g.s;

        //only b can be negative
        //neither a or b can be 0; d=b^2-4ac is prime. if b=0, then d=-4ac=composite. if a=0, then d=b^2; d>=0
        //no constraints on which is greater
        v2_int=gcd(b_int, a_int, fixed_integer<uint64, 17>(), true).s;
        assert(integer(v2_int)==v2);
    }
    //TRACK_MAX(v2); // v2, 2.00195, 1

    //todo
    //start with <0,c> or <c,0> which is padded to 18 limbs so that the multiplications by 64 bits are exact (same with sums)
    //once the new values of uv are calculated, need to reduce modulo a, which is 17 limbs and has been normalized already
    //-the normalization also left shifted c
    //reducing modulo a only looks at the first couple of limbs so it has the same efficiency as doing it at the end
    //-it does require computing the inverse of a a bunch of times which is slow. this will probably slow it down by 2x-4x
    //--can avoid this by only reducing every couple of iterations
    integer k=(-v2*c)%a;
    fixed_integer<uint64, 17> k_int=fixed_integer<uint64, 33>(-v2_int*c_int)%a_int;
    assert(integer(k_int)==k);

    //print( "v2", v2.to_string() );
    //print( "k", k.to_string() );

    //TRACK_MAX(v2*c); // v2*c, 4.0039, 1
    //TRACK_MAX(k); // k, 2.0039, 0

    integer a_copy=a;
    integer k_copy=k;
    integer co2;
    integer co1;
    xgcd_partial(co2, co1, a_copy, k_copy, L); //neither input is negative

    const bool same_cofactors=false; //gcd and xgcd_parital can return slightly different results

    fixed_integer<uint64, 9> co2_int;
    fixed_integer<uint64, 9> co1_int;
    fixed_integer<uint64, 9> a_copy_int;
    fixed_integer<uint64, 9> k_copy_int;
    {
        // a>L so at least one input is >L initially
        //when this terminates, one input is >L and one is <=L
        auto g=gcd(a_int, k_int, L_int, false);
        co2_int=-g.t;
        co1_int=-g.t_2;
        a_copy_int=g.gcd;
        k_copy_int=g.gcd_2;

        if (same_cofactors) {
            assert(integer(co2_int)==co2);
            assert(integer(co1_int)==co1);
            assert(integer(a_copy_int)==a_copy);
            assert(integer(k_copy_int)==k_copy);
        }
    }

    //print( "co2", co2_int.to_integer().to_string() );
    //print( "co1", co1_int.to_integer().to_string() );
    //print( "a_copy", a_copy_int.to_integer().to_string() );
    //print( "k_copy", k_copy_int.to_integer().to_string() );

    //todo
    //can speed the following operations up with simd (including calculating C but it is done on the slave core)
    //division by a can be replaced by multiplication by a inverse. this takes the top N bits of the numerator and denominator inverse
    // where N is the number of bits in the result
    //if this is done correctly, the calculated result withh be >= the actual result, and it will be == almost all of the time
    //to detect if it is >, can calculate the remainder and see if it is too high. this can be done by the slave core during the
    // next iteration
    //most of the stuff is in registers for avx-512
    //the slave core will precalculate a inverse. it is already dividing by a to calculate c
    //this would get rid of the 8x8 batched multiply but not the single limb multiply, since that is still needed for gcd
    //for the cofactors which are calculated on the slave core, can use a tree matrix multiplication with the avx-512 code
    //for the pentium processor, the adox instruction is banned so the single limb multiply needs to be changed
    //the slave core can calculate the inverse of co1 while the master core is calculating A
    //for the modulo, the quotient has about 15 bits. can probably calculate the inverse on the master core then since the division
    // base case already calculates it with enough precision
    //this should work for scalar code also

    //TRACK_MAX(co2); // co2, 1.00195, 1
    //TRACK_MAX(co1); // co1, 1.0039, 1
    //TRACK_MAX(a_copy); // a_copy, 1.03906, 0
    //TRACK_MAX(k_copy); // k_copy, 1, 0

    //TRACK_MAX(k_copy*k_copy); // k_copy*k_copy, 2, 0
    //TRACK_MAX(b*k_copy); // b*k_copy, 3.0039, 0
    //TRACK_MAX(c*co1); // c*co1, 3.0039, 1
    //TRACK_MAX(b*k_copy-c*co1); // b*k_copy-c*co1, 3.00585, 1
    //TRACK_MAX((b*k_copy-c*co1)/a); // (b*k_copy-c*co1)/a, 1.02539, 1
    //TRACK_MAX(co1*((b*k_copy-c*co1)/a)); // co1*((b*k_copy-c*co1)/a), 2.00585, 1

    integer A=k_copy*k_copy-co1*((b*k_copy-c*co1)/a); // [exact]
    //TRACK_MAX(A); // A, 2.00585, 0

    fixed_integer<uint64, 17> A_int;
    {
        fixed_integer<uint64, 17> k_copy_k_copy(k_copy_int*k_copy_int);
        fixed_integer<uint64, 25> b_k_copy(b_int*k_copy_int);
        fixed_integer<uint64, 25> c_co1(c_int*co1_int);
        fixed_integer<uint64, 25> b_k_copy_c_co1(b_k_copy-c_co1);
        fixed_integer<uint64, 9> t1(b_k_copy_c_co1/a_int);
        fixed_integer<uint64, 17> t2(co1_int*t1);
        A_int=k_copy_k_copy-t2;

        if (same_cofactors) {
            assert(integer(A_int)==A);
        }
    }

    if (co1>=0) {
        A=-A;
    }

    if (!co1_int.is_negative()) {
        A_int=-A_int;
    }

    if (same_cofactors) {
        assert(integer(A_int)==A);
    }

    //TRACK_MAX(A); // A, 2.00585, 1
    //TRACK_MAX(a*k_copy); // a*k_copy, 3.0039, 0
    //TRACK_MAX(A*co2); // A*co2, 3.0039, 0
    //TRACK_MAX((a*k_copy-A*co2)*integer(2)); // (a*k_copy-A*co2)*integer(2), 3.00585, 1
    //TRACK_MAX(((a*k_copy-A*co2)*integer(2))/co1); // ((a*k_copy-A*co2)*integer(2))/co1, 2.03515, 1
    //TRACK_MAX(((a*k_copy-A*co2)*integer(2))/co1 - b); // ((a*k_copy-A*co2)*integer(2))/co1 - b, 2.03515, 1

    integer B=( ((a*k_copy-A*co2)*integer(2))/co1 - b )%(A*integer(2)); //[exact]
    //TRACK_MAX(B); // B, 2.00585, 0

    fixed_integer<uint64, 17> B_int;
    {
        fixed_integer<uint64, 25> a_k_copy(a_int*k_copy_int);
        fixed_integer<uint64, 25> A_co2(A_int*co2_int);
        fixed_integer<uint64, 25> t1((a_k_copy-A_co2)<<1);
        fixed_integer<uint64, 17> t2(t1/co1_int);
        fixed_integer<uint64, 17> t3(t2-b_int);

        //assert(integer(a_k_copy) == a*k_copy);
        //assert(integer(A_co2) == A*co2);
        //assert(integer(a_k_copy-A_co2) == (a*k_copy-A*co2));

        //print(integer(a_k_copy-A_co2).to_string());
        //print(integer(fixed_integer<uint64, 30>(a_k_copy-A_co2)<<8).to_string());

        //assert(integer((a_k_copy-A_co2)<<1) == ((a*k_copy-A*co2)*integer(2)));
        //assert(integer(t2) == ((a*k_copy-A*co2)*integer(2))/co1);
        //assert(integer(t3) == ( ((a*k_copy-A*co2)*integer(2))/co1 - b ));
        //assert(integer(A_int<<1) == (A*integer(2)));
        B_int=t3%fixed_integer<uint64, 17>(A_int<<1);

        if (same_cofactors) {
            assert(integer(B_int)==B);
        }
    }

    //TRACK_MAX(B*B); // B*B, 4.01171, 0
    //TRACK_MAX(B*B-D); // B*B-D, 4.01171, 0

    integer C=((B*B-D)/A)>>2; //[division is exact; right shift is truncation towards 0; can be negative. right shift is exact]

    fixed_integer<uint64, 17> C_int;
    {
        fixed_integer<uint64, 33> B_B(B_int*B_int);
        fixed_integer<uint64, 33> B_B_D(B_B-D_int);

        //calculated at the same time as the division
        if (!(B_B_D%A_int).is_zero()) {
            //todo //test random error injection
            print( "discriminant error" );
            return false;
        }

        fixed_integer<uint64, 17> t1(B_B_D/A_int);

        //assert(integer(B_B)==B*B);
        //assert(integer(B_B_D)==B*B-D);

        //print(integer(t1).to_string());
        //print(((B*B-D)/A).to_string());

        //assert(integer(t1)==((B*B-D)/A));

        C_int=t1>>2;

        if (same_cofactors) {
            assert(integer(C_int)==C);
        }
    }

    //TRACK_MAX(C); // C, 2.03125, 1

    if (A<0) {
        A=-A;
        C=-C;
    }

    A_int.set_negative(false);
    C_int.set_negative(false);

    //print( "A", A_int.to_integer().to_string() );
    //print( "B", B_int.to_integer().to_string() );

    if (same_cofactors) {
        assert(integer(A_int)==A);
        assert(integer(B_int)==B);
        assert(integer(C_int)==C);
    }

    //TRACK_MAX(A); // A, 2.00585, 0
    //TRACK_MAX(C); // C, 2.03125, 0

    f.a=A;
    f.b=B;
    f.c=C;

    //print( "" );
    //print( "" );
    //print( "==========================================" );
    //print( "" );
    //print( "" );

    //
    //

    integer s=integer(a_copy_int);
    integer t=integer(k_copy_int);
    integer v0=-integer(co2_int);
    integer v1=-integer(co1_int);
    bool S_negative=(v1<=0);

    integer c_v1=c*v1;
    integer b_t=b*t;
    integer b_t_c_v1=b_t+c_v1;
    integer h=(b*t+c*v1)/a;
    if (S_negative) {
        h=-h;
    }

    integer v1_h=v1*h;
    integer t_t_S=t*t;
    if (S_negative) {
        t_t_S=-t_t_S;
    }

    integer v0_2=v0<<1;
    integer A_=t_t_S+v1_h;
    integer A_2=A_<<1;
    integer S_t_v0=t*v0;
    if (S_negative) {
        S_t_v0=-S_t_v0;
    }

    // B=( -((a*t+A*v0)*2)/v1 - b )%(A*2)
    // B=( -((a*t+(t*t*S+v1*h)*v0)*2)/v1 - b )%(A*2)
    // B=( -((a*t*2 + t*t*S*v0*2 + v1*v0*h*2))/v1 - b )%(A*2)
    // B=( -(a*t*2 + t*t*S*v0*2)/v1 - v0*h*2 - b )%(A*2)
    // B=( -(t*2(a + t*S*v0))/v1 - v0*h*2 - b )%(A*2)

    integer a_S_t_v0=a+S_t_v0;
    integer t_2=t<<1;
    integer t_2_a_S_t_v0=t_2*a_S_t_v0;

    integer t_2_a_S_t_v0_v1=t_2_a_S_t_v0/v1;

    //integer t_2_a_S_t_v0_v1=t_2*a_S_t_v0_v1;

    integer e=-t_2_a_S_t_v0_v1-b;
    integer v0_2_h=v0_2*h;
    integer f_=e-v0_2_h; // -(t*2*((a+S*t*v0)/v1)) - v0*h*2 - b
    integer B_=f_%A_2;
    A_=abs(A_);

    //print( "A_", A_.to_string() );
    //print( "B_", B_.to_string() );

    return true;
}