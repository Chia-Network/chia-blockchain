/*uint64 funnel_shift(uint64 low, uint64 high, int start, int size) {
    assert(start>=0 && size>0 && start+size<=128);

    uint128 v=(uint128(high)<<64) | uint128(low);
    v>>=start;
    v&=~(uint128(1)<<size);
    return uint64(v);
} */

constexpr uint64 extract_bits(uint64 t, int start, int size) {
    assert(start>=0 && start<64);
    assert(size>=0 && start+size<=64);

    t >>= start;
    t &= (1ull<<size)-1;
    return t;
}

constexpr uint64 insert_bits(uint64 t, uint64 bits, int start, int size) {
    assert(start>=0 && start<64);
    assert(size>=0 && start+size<=64);
    assert(
        ( bits & ~((1ull<<size)-1) )
        ==0
    );

    bits <<= start;

    uint64 mask = ((1ull<<size)-1) << start;

    t &= ~mask;
    t |= bits;

    return t;
}

void output_bits(ostream& out, uint64 bits, int size) {
    assert(size>0 && size<64);
    assert(
        ( bits & ~((1ull<<size)-1) )
        ==0
    );

    for (int x=size-1;x>=0;--x) {
        bool v=bits&(1ull<<x);
        out << (v? "1" : "0");
    }
}

constexpr uint64 bit_sequence(int start, int size) {
    return insert_bits(0, (1ull<<size)-1, start, size);
}