/* ******************************************************************
ZLIBH : Zlib based Huffman coder
Copyright (C) 1995-2012 Jean-loup Gailly
BSD 2-Clause License (http://www.opensource.org/licenses/bsd-license.php)

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

* Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
* Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF Sunsigned char DAMAGE.

You can contact the author at :
- Public forum : https://groups.google.com/forum/#!forum/lz4c
****************************************************************** */


/****************************************************************
*  Tuning parameters
****************************************************************/
// MEMORY_USAGE :
// Memory usage formula : N->2^N Bytes (examples : 10 -> 1KB; 12 -> 4KB ; 16 -> 64KB; 20 -> 1MB; etc.)
// Increasing memory usage improves compression ratio
// Reduced memory usage can improve speed, due to cache effect
// Default value is 14, for 16KB, which nicely fits into Intel x86 L1 cache
#define ZLIBH_MEMORY_USAGE 14

// ZLIBH_ILP
// Instruction Level Parallelism : improve performance on modern CPU featuring multiple ALU and OoO capabilities
#define ZLIBH_ILP 1

// ZLIBH_DEBUG
// Enable verification code, which checks table construction and state values (munsigned char slower, for debug purpose only)
#define ZLIBH_DEBUG 0


/****************************************************************
*  Includes
****************************************************************/
#include "zlibh.h"
#include <string.h>    // memcpy, memset
#include <stdio.h>     // printf (debug)

#ifdef _MSC_VER    // Visual Studio
#  pragma warning(disable : 4701)        // disable: C4701: variable potentially uninitialized
#  pragma warning(disable : 4131)        // disable: C4131: obsolete declarator
#endif

#ifdef __GNUC__    // GCC
#  pragma GCC diagnostic ignored "-Wstrict-prototypes"
#endif

/*
* Maximums for allocations and loops.  It is not useful to change these --
* they are fixed by the deflate format.
*/

#define ZLIBH_MAX_BITS    15    /* maximum bits in a code */
#define ZLIBH_MAX_BL_BITS  7    /* maximum bits in a length code code */
#define ZLIBH_MAXCODES   257    /* maximum codes lengths to read */
#define ZLIBH_FIXLCODES  288    /* number of fixed literal/length codes */

#define ZLIBH_LITERALS   256    /* number of literal bytes 0..255 */
#define END_BLOCK        256    /* End of Block code */
#define ZLIBH_L_CODES    257    /* number of literal including the END_BLOCK code */
#define ZLIBH_BL_CODES    19    /* number of codes used to transfer the bit lengths */
#define ZLIBH_HEAP_SIZE (2*ZLIBH_L_CODES+1)  /* maximum heap size */

#define REP_3_6      16
/* repeat previous bit length 3-6 times (2 bits of repeat count) */

#define REPZ_3_10    17
/* repeat a zero length 3-10 times  (3 bits of repeat count) */

#define REPZ_11_138  18
/* repeat a zero length 11-138 times  (7 bits of repeat count) */


/* Data structure describing a single value and its code string. */
typedef struct ct_data_s {
    union {
        unsigned short  freq;       /* frequency count */
        unsigned short  code;       /* bit string */
    } fc;
    union {
        unsigned short  dad;        /* father node in Huffman tree */
        unsigned short  len;        /* length of bit string */
    } dl;
} ct_data;

#define Freq fc.freq
#define Code fc.code
#define Dad  dl.dad
#define Len  dl.len


typedef struct static_tree_desc_s {
    const ct_data *static_tree;  /* static tree or NULL */
    const int *extra_bits;       /* extra bits for each code or NULL */
    int     extra_base;          /* base index for extra_bits */
    int     elems;               /* max number of elements in the tree */
    int     max_length;          /* max bit length for the codes */
} static_tree_desc;

typedef struct tree_desc_s {
    ct_data          *dyn_tree;  /* the dynamic tree */
    int              max_code;   /* largest code with non zero frequency */
    unsigned long    *comp_size; /* computed size */
    static_tree_desc *stat_desc; /* the corresponding static tree */
} tree_desc;

static const unsigned char bl_order[]
= {16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15};
/* The lengths of the bit length codes are sent in order of decreasing
* probability, to avoid transmitting the lengths for unused bit length codes.
*/

static const int extra_lbits[]   /* extra bits for each length code */
= {0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0};

static const int extra_blbits[]  /* extra bits for each bit length code */
= {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,3,7};

static const ct_data static_ltree[] = {
    {{ 12},{  8}}, {{140},{  8}}, {{ 76},{  8}}, {{204},{  8}}, {{ 44},{  8}},
    {{172},{  8}}, {{108},{  8}}, {{236},{  8}}, {{ 28},{  8}}, {{156},{  8}},
    {{ 92},{  8}}, {{220},{  8}}, {{ 60},{  8}}, {{188},{  8}}, {{124},{  8}},
    {{252},{  8}}, {{  2},{  8}}, {{130},{  8}}, {{ 66},{  8}}, {{194},{  8}},
    {{ 34},{  8}}, {{162},{  8}}, {{ 98},{  8}}, {{226},{  8}}, {{ 18},{  8}},
    {{146},{  8}}, {{ 82},{  8}}, {{210},{  8}}, {{ 50},{  8}}, {{178},{  8}},
    {{114},{  8}}, {{242},{  8}}, {{ 10},{  8}}, {{138},{  8}}, {{ 74},{  8}},
    {{202},{  8}}, {{ 42},{  8}}, {{170},{  8}}, {{106},{  8}}, {{234},{  8}},
    {{ 26},{  8}}, {{154},{  8}}, {{ 90},{  8}}, {{218},{  8}}, {{ 58},{  8}},
    {{186},{  8}}, {{122},{  8}}, {{250},{  8}}, {{  6},{  8}}, {{134},{  8}},
    {{ 70},{  8}}, {{198},{  8}}, {{ 38},{  8}}, {{166},{  8}}, {{102},{  8}},
    {{230},{  8}}, {{ 22},{  8}}, {{150},{  8}}, {{ 86},{  8}}, {{214},{  8}},
    {{ 54},{  8}}, {{182},{  8}}, {{118},{  8}}, {{246},{  8}}, {{ 14},{  8}},
    {{142},{  8}}, {{ 78},{  8}}, {{206},{  8}}, {{ 46},{  8}}, {{174},{  8}},
    {{110},{  8}}, {{238},{  8}}, {{ 30},{  8}}, {{158},{  8}}, {{ 94},{  8}},
    {{222},{  8}}, {{ 62},{  8}}, {{190},{  8}}, {{126},{  8}}, {{254},{  8}},
    {{  1},{  8}}, {{129},{  8}}, {{ 65},{  8}}, {{193},{  8}}, {{ 33},{  8}},
    {{161},{  8}}, {{ 97},{  8}}, {{225},{  8}}, {{ 17},{  8}}, {{145},{  8}},
    {{ 81},{  8}}, {{209},{  8}}, {{ 49},{  8}}, {{177},{  8}}, {{113},{  8}},
    {{241},{  8}}, {{  9},{  8}}, {{137},{  8}}, {{ 73},{  8}}, {{201},{  8}},
    {{ 41},{  8}}, {{169},{  8}}, {{105},{  8}}, {{233},{  8}}, {{ 25},{  8}},
    {{153},{  8}}, {{ 89},{  8}}, {{217},{  8}}, {{ 57},{  8}}, {{185},{  8}},
    {{121},{  8}}, {{249},{  8}}, {{  5},{  8}}, {{133},{  8}}, {{ 69},{  8}},
    {{197},{  8}}, {{ 37},{  8}}, {{165},{  8}}, {{101},{  8}}, {{229},{  8}},
    {{ 21},{  8}}, {{149},{  8}}, {{ 85},{  8}}, {{213},{  8}}, {{ 53},{  8}},
    {{181},{  8}}, {{117},{  8}}, {{245},{  8}}, {{ 13},{  8}}, {{141},{  8}},
    {{ 77},{  8}}, {{205},{  8}}, {{ 45},{  8}}, {{173},{  8}}, {{109},{  8}},
    {{237},{  8}}, {{ 29},{  8}}, {{157},{  8}}, {{ 93},{  8}}, {{221},{  8}},
    {{ 61},{  8}}, {{189},{  8}}, {{125},{  8}}, {{253},{  8}}, {{ 19},{  9}},
    {{275},{  9}}, {{147},{  9}}, {{403},{  9}}, {{ 83},{  9}}, {{339},{  9}},
    {{211},{  9}}, {{467},{  9}}, {{ 51},{  9}}, {{307},{  9}}, {{179},{  9}},
    {{435},{  9}}, {{115},{  9}}, {{371},{  9}}, {{243},{  9}}, {{499},{  9}},
    {{ 11},{  9}}, {{267},{  9}}, {{139},{  9}}, {{395},{  9}}, {{ 75},{  9}},
    {{331},{  9}}, {{203},{  9}}, {{459},{  9}}, {{ 43},{  9}}, {{299},{  9}},
    {{171},{  9}}, {{427},{  9}}, {{107},{  9}}, {{363},{  9}}, {{235},{  9}},
    {{491},{  9}}, {{ 27},{  9}}, {{283},{  9}}, {{155},{  9}}, {{411},{  9}},
    {{ 91},{  9}}, {{347},{  9}}, {{219},{  9}}, {{475},{  9}}, {{ 59},{  9}},
    {{315},{  9}}, {{187},{  9}}, {{443},{  9}}, {{123},{  9}}, {{379},{  9}},
    {{251},{  9}}, {{507},{  9}}, {{  7},{  9}}, {{263},{  9}}, {{135},{  9}},
    {{391},{  9}}, {{ 71},{  9}}, {{327},{  9}}, {{199},{  9}}, {{455},{  9}},
    {{ 39},{  9}}, {{295},{  9}}, {{167},{  9}}, {{423},{  9}}, {{103},{  9}},
    {{359},{  9}}, {{231},{  9}}, {{487},{  9}}, {{ 23},{  9}}, {{279},{  9}},
    {{151},{  9}}, {{407},{  9}}, {{ 87},{  9}}, {{343},{  9}}, {{215},{  9}},
    {{471},{  9}}, {{ 55},{  9}}, {{311},{  9}}, {{183},{  9}}, {{439},{  9}},
    {{119},{  9}}, {{375},{  9}}, {{247},{  9}}, {{503},{  9}}, {{ 15},{  9}},
    {{271},{  9}}, {{143},{  9}}, {{399},{  9}}, {{ 79},{  9}}, {{335},{  9}},
    {{207},{  9}}, {{463},{  9}}, {{ 47},{  9}}, {{303},{  9}}, {{175},{  9}},
    {{431},{  9}}, {{111},{  9}}, {{367},{  9}}, {{239},{  9}}, {{495},{  9}},
    {{ 31},{  9}}, {{287},{  9}}, {{159},{  9}}, {{415},{  9}}, {{ 95},{  9}},
    {{351},{  9}}, {{223},{  9}}, {{479},{  9}}, {{ 63},{  9}}, {{319},{  9}},
    {{191},{  9}}, {{447},{  9}}, {{127},{  9}}, {{383},{  9}}, {{255},{  9}},
    {{511},{  9}}, {{  0},{  7}}, {{ 64},{  7}}, {{ 32},{  7}}, {{ 96},{  7}},
    {{ 16},{  7}}, {{ 80},{  7}}, {{ 48},{  7}}, {{112},{  7}}, {{  8},{  7}},
    {{ 72},{  7}}, {{ 40},{  7}}, {{104},{  7}}, {{ 24},{  7}}, {{ 88},{  7}},
    {{ 56},{  7}}, {{120},{  7}}, {{  4},{  7}}, {{ 68},{  7}}, {{ 36},{  7}},
    {{100},{  7}}, {{ 20},{  7}}, {{ 84},{  7}}, {{ 52},{  7}}, {{116},{  7}},
    {{  3},{  8}}, {{131},{  8}}, {{ 67},{  8}}, {{195},{  8}}, {{ 35},{  8}},
    {{163},{  8}}, {{ 99},{  8}}, {{227},{  8}}
};

static static_tree_desc  static_l_desc =
{static_ltree, extra_lbits, ZLIBH_LITERALS+1, ZLIBH_L_CODES, ZLIBH_MAX_BITS};

static static_tree_desc  static_bl_desc =
{(const ct_data *)0, extra_blbits, 0, ZLIBH_BL_CODES, ZLIBH_MAX_BL_BITS};


#define SMALLEST 1
/* Index within the heap array of least frequent node in the Huffman tree */


/* ===========================================================================
* Remove the smallest element from the heap and recreate the heap with
* one less element. Updates heap and huf_heap[0].
*/
#define pqremove(tree, huf_heap, depth, top) \
{\
    top = huf_heap[SMALLEST]; \
    huf_heap[SMALLEST] = huf_heap[huf_heap[0]--]; \
    pqdownheap(tree, huf_heap, depth, SMALLEST); \
}

/* ===========================================================================
* Compares to subtrees, using the tree depth as tie breaker when
* the subtrees have equal frequency. This minimizes the worst case length.
*/
#define smaller(tree, n, m, depth) \
    (tree[n].Freq < tree[m].Freq || (tree[n].Freq == tree[m].Freq && depth[n] <= depth[m]))

/* ===========================================================================
* Restore the heap property by moving down the tree starting at node k,
* exchanging a node with the smallest of its two sons if necessary, stopping
* when the heap property is re-established (each father smaller than its
* two sons).
*/
static void pqdownheap(ct_data *tree, int *huf_heap, unsigned char *depth, int k)
{
    int v = huf_heap[k];
    int j = k << 1;  /* left son of k */
    while (j <= huf_heap[0]) {
        /* Set j to the smallest of the two sons: */
        if (j < huf_heap[0] &&
            smaller(tree, huf_heap[j+1], huf_heap[j], depth)) {
                j++;
        }
        /* Exit if v is smaller than both sons */
        if (smaller(tree, v, huf_heap[j], depth)) break;

        /* Exchange v with the smallest son */
        huf_heap[k] = huf_heap[j];  k = j;

        /* And continue down the tree, setting j to the left son of k */
        j <<= 1;
    }
    huf_heap[k] = v;
}


/****************************************************************
*  Basic Types
****************************************************************/
#if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 199901L   // C99
# include <stdint.h>
typedef  uint8_t BYTE;
typedef uint16_t U16;
typedef uint32_t U32;
typedef  int32_t S32;
typedef uint64_t U64;
#else
typedef unsigned char       BYTE;
typedef unsigned short      U16;
typedef unsigned int        U32;
typedef   signed int        S32;
typedef unsigned long long  U64;
#endif

typedef U32 bitContainer_t;


/****************************************************************
*  Constants
****************************************************************/
#define MAX_NB_SYMBOLS 257
#define ZLIBH_MAX_TABLELOG  (ZLIBH_MEMORY_USAGE-2)
#define ZLIBH_MAX_TABLESIZE (1U<<ZLIBH_MAX_TABLELOG)
#define ZLIBH_MAXTABLESIZE_MASK (ZLIBH_MAX_TABLESIZE-1)

#define ZLIBH_VIRTUAL_LOG   30
#define ZLIBH_VIRTUAL_RANGE (1U<<ZLIBH_VIRTUAL_LOG)
#define ZLIBH_VIRTUAL_SCALE (ZLIBH_VIRTUAL_LOG-ZLIBH_MAX_TABLELOG)
#define ZLIBH_VIRTUAL_STEP  (1U << ZLIBH_VIRTUAL_SCALE)

#if ZLIBH_MAX_TABLELOG>15
#error "ZLIBH_MAX_TABLELOG>15 isn't supported"
#endif

#if ZLIBH_DEBUG
static long long nbBlocks = 0;     // debug
static long long toCheck  = -1;    // debug
static long long nbDBlocks = 0;    // debug
#endif


/****************************************************************
*  Compiler specifics
****************************************************************/
#ifdef _MSC_VER    // Visual Studio
#  define FORCE_INLINE static __forceinline
#  include <intrin.h>                    // For Visual 2005
#  pragma warning(disable : 4127)        // disable: C4127: conditional expression is constant
#else
#  define GCC_VERSION (__GNUC__ * 100 + __GNUC_MINOR__)
#  ifdef __GNUC__
#    define FORCE_INLINE static inline __attribute__((always_inline))
#  else
#    define FORCE_INLINE static inline
#  endif
#endif


/****************************
*  ZLIBH Compression Code
****************************/

/* If not enough room in bi_buf, use (valid) bits from bi_buf and
* (16 - bi_valid) bits from value, leaving (width - (16-bi_valid))
* unused bits in value.
*/
#define SENDBITS() \
    do { \
    if (bi_valid > (16U - length)) { \
    bi_buf |= value << bi_valid; \
    *op++=(unsigned char)(bi_buf & 0xff); \
    *op++=(unsigned char)(bi_buf >> 8); \
    bi_buf = value >> (16 - bi_valid); \
    bi_valid += length - 16; \
    } else { \
    bi_buf |= value << bi_valid; \
    bi_valid += length; \
    } \
    } while (0)


/* ===========================================================================
* Send the block data compressed using the given Huffman trees
*/
static void ZLIBH_compress_block(const unsigned char* ip, unsigned char* op, const ct_data * ltree, const ct_data * bltree, unsigned int ip_len)
{
    unsigned int bi_buf;    /* bit buffer */
    unsigned int bi_valid;  /* bits used in bit_buf */
    unsigned int lx = 0;    /* running index in l_buf */
    unsigned int value;     /* value to send */
    unsigned short length;  /* number of bits to send */

    if  (ltree != static_ltree) {  /* write dynamic Huffman header first */
        /* send_tree is merged here */
        int prevlen = -1;            /* last emitted length */
        int nextlen = ltree[0].Len;  /* length of next code */
        int count = 0;               /* repeat count of the current code */
        int max_count = 7;           /* max repeat count */
        int min_count = 4;           /* min repeat count */
        unsigned int max_code = 256;
        unsigned int blcodes;
        unsigned int n;

        bi_valid = 5;
        blcodes = op[0];
        bi_buf = (unsigned int)((blcodes-4)<<1);
        length = 3;
        for (n = 0; n < blcodes; n++) {
            value = bltree[bl_order[n]].Len;
            SENDBITS();
        }

        if (nextlen == 0) max_count = 138, min_count = 3;

        for (n = 0; n <= max_code; n++) {
            int curlen;                  /* length of current code */
            curlen = nextlen; nextlen = ltree[n+1].Len;
            if (++count < max_count && curlen == nextlen) {
                continue;
            } else if (count < min_count) {
                do {
                    value = bltree[curlen].Code;
                    length = bltree[curlen].Len;
                    SENDBITS();
                } while (--count != 0);

            } else if (curlen != 0) {
                if (curlen != prevlen) {
                    value = bltree[curlen].Code;
                    length = bltree[curlen].Len;
                    SENDBITS();
                    count--;
                }
                value = bltree[REP_3_6].Code;
                length = bltree[REP_3_6].Len;
                SENDBITS();

                length = 2;
                value = count-3;
                SENDBITS();

            } else if (count < 11) {
                value = bltree[REPZ_3_10].Code;
                length = bltree[REPZ_3_10].Len;
                SENDBITS();

                length = 3;
                value = count-3;
                SENDBITS();

            } else {
                value = bltree[REPZ_11_138].Code;
                length = bltree[REPZ_11_138].Len;
                SENDBITS();

                length = 7;
                value = count-11;
                SENDBITS();

            }
            count = 0; prevlen = curlen;
            if (nextlen == 0) {
                max_count = 138, min_count = 3;
            } else if (curlen == nextlen) {
                max_count = 6, min_count = 3;
            } else {
                max_count = 7, min_count = 4;
            }
        }
    }
    else {            /* static case only identified by a single one bit */
        bi_valid = 1;
        bi_buf = 1;
    }
    lx = 1;
    do {
        unsigned int t_index;
        t_index = *ip++;
        value = (unsigned int)ltree[t_index].Code;
        length = ltree[t_index].Len;
        if (bi_valid > (16U - length)) {
            bi_buf |= value << bi_valid;
            *op++=(unsigned char)(bi_buf & 0xff);
            *op++=(unsigned char)(bi_buf >> 8);
            bi_buf = value >> (16 - bi_valid);
            bi_valid += length - 16;
        } else {
            bi_buf |= value << bi_valid;
            bi_valid += length;
        }
    } while (lx++ < ip_len);

    value = (unsigned int)ltree[END_BLOCK].Code;   /* send End of Block */
    length = ltree[END_BLOCK].Len;
    if (bi_valid > (16U - length)) {
        bi_buf |= value << bi_valid;
        *op++=(unsigned char)(bi_buf & 0xff);
        *op++=(unsigned char)(bi_buf >> 8);
        bi_buf = value >> (16 - bi_valid);
        bi_valid += length - 16;
    } else {
        bi_buf |= value << bi_valid;
        bi_valid += length;
    }

    if (bi_valid > 8) {                             /* flush bit_buf */
        *op++=(unsigned char)(bi_buf & 0xff);
        *op++=(unsigned char)(bi_buf >> 8);
    }
    else if (bi_valid > 0) {
        *op++=(unsigned char)bi_buf;
    }
}

/* ===========================================================================
* Merge the literal and distance tree and scan the resulting tree to determine
* the frequencies of the codes in the bit length tree.
*/
static void feed_bltree(tree_desc * ltree_desc, tree_desc * bltree_desc)
{
    ct_data *ltree  = ltree_desc->dyn_tree;
    ct_data *bltree = bltree_desc->dyn_tree;
    int lmax_code   = ltree_desc->max_code;
    int n = 0;                  /* iterates over all tree elements */
    int prevlen = -1;           /* last emitted length */
    int nextlen = ltree[0].Len; /* length of next code */
    int count = 0;              /* repeat count of the current code */
    int max_count = 7;          /* max repeat count */
    int min_count = 4;          /* min repeat count */

    if (nextlen == 0) max_count = 138, min_count = 3;
    ltree[lmax_code+1].Len = (unsigned short)0xffff;   /* guard */

    n = 0;
    do {
        bltree[n++].Freq = 0;
    } while (n < 19);

    for (n = 0; n <= lmax_code; n++) {
        int curlen;                 /* length of current code */
        curlen = nextlen; nextlen = ltree[n+1].Len;
        if (++count < max_count && curlen == nextlen) {
            continue;
        } else if (count < min_count) {
            bltree[curlen].Freq += (unsigned short)count;
        } else if (curlen != 0) {
            if (curlen != prevlen) bltree[curlen].Freq++;
            bltree[REP_3_6].Freq++;
        } else if (count <= 10) {
            bltree[REPZ_3_10].Freq++;
        } else {
            bltree[REPZ_11_138].Freq++;
        }
        count = 0; prevlen = curlen;
        if (nextlen == 0) {
            max_count = 138, min_count = 3;
        } else if (curlen == nextlen) {
            max_count = 6, min_count = 3;
        } else {
            max_count = 7, min_count = 4;
        }
    }
}


/* ===========================================================================
* Reverse the first len bits of a code, using straightforward code (a faster
* method would use a table)
* IN assertion: 1 <= len <= 15
*/
static unsigned bi_reverse(unsigned code, int len)
{
    register unsigned res = 0;
    do {
        res |= code & 1;
        code >>= 1, res <<= 1;
    } while (--len > 0);
    return res >> 1;
}


/* ===========================================================================
* Generate the codes for a given tree and bit counts (which need not be
* optimal).
* IN assertion: the array bl_count contains the bit length statistics for
* the given tree and the field len is set for all tree elements.
* OUT assertion: the field code is set for all tree elements of non
*     zero code length.
*/
static void gen_codes(ct_data* tree, unsigned int max_code, unsigned short* bl_count)
{
    unsigned short next_code[ZLIBH_MAX_BITS+1];  /* next code value for each bit length */
    unsigned short code = 0;               /* running code value */
    unsigned int   bits;                   /* bit index */
    unsigned int   n;                      /* code index */

    /* The distribution counts are first used to generate the code values
    * without bit reversal.
    */
    for (bits = 1; bits <= ZLIBH_MAX_BITS; bits++) {
        next_code[bits] = code = (unsigned short)((code + bl_count[bits-1]) << 1);
    }

    for (n = 0;  n <= max_code; n++) {
        int len = tree[n].Len;
        if (len == 0) continue;
        tree[n].Code = (unsigned short)bi_reverse(next_code[len]++, len);   /* Now reverse the bits */
    }
}


/* ===========================================================================
* Compute the optimal bit lengths for a tree and update the total bit length
* for the current block.
* IN assertion: the fields .Freq and dad are set, heap[heap_max] and
*    above are the tree nodes sorted by increasing frequency.
* OUT assertions: the field .Len is set to the optimal bit length, the
*     array bl_count contains the frequencies for each bit length.
*     The length os_len[0] is updated; os_len[1] is also updated if stree is
*     not null.
*/
static void gen_bitlen(tree_desc* desc, int* huf_heap, int heap_max, unsigned short* bl_count)
{
    ct_data *tree        = desc->dyn_tree;
    int max_code         = desc->max_code;
    const ct_data *stree = desc->stat_desc->static_tree;
    const int *extra     = desc->stat_desc->extra_bits;
    int base             = desc->stat_desc->extra_base;
    int max_length       = desc->stat_desc->max_length;
    unsigned long *csize = desc->comp_size;
    int h;              /* heap index */
    int n, m;           /* iterate over the tree elements */
    int bits;           /* bit length */
    int xbits;          /* extra bits */
    unsigned short f;   /* frequency */
    int overflow = 0;   /* number of elements with bit length too large */

    for (bits = 0; bits <= ZLIBH_MAX_BITS; bits++) bl_count[bits] = 0;

    /* In a first pass, compute the optimal bit lengths (which may
    * overflow in the case of the bit length tree).
    */
    tree[huf_heap[heap_max]].Len = 0; /* root of the heap */

    for (h = heap_max+1; h < ZLIBH_HEAP_SIZE; h++) {
        n = huf_heap[h];
        bits = tree[tree[n].Dad].Len + 1;
        if (bits > max_length) bits = max_length, overflow++;
        tree[n].Len = (unsigned short)bits;
        /* We overwrite tree[n].Dad which is no longer needed */

        if (n > max_code) continue; /* not a leaf node */

        bl_count[bits]++;
        xbits = 0;
        if (n >= base) xbits = extra[n-base];
        f = tree[n].Freq;
        csize[0] += (unsigned long)f * (bits + xbits);
        if (stree) csize[1] += (unsigned long)f * (stree[n].Len + xbits);
    }
    if (overflow == 0) return;

    //    fprintf(stderr,"\nbit length overflow\n");
    /* This happens for example on obj2 and pic of the Calgary corpus */

    /* Find the first bit length which could increase: */
    do {
        bits = max_length-1;
        while (bl_count[bits] == 0) bits--;
        bl_count[bits]--;      /* move one leaf down the tree */
        bl_count[bits+1] += 2; /* move one overflow item as its brother */
        bl_count[max_length]--;
        /* The brother of the overflow item also moves one step up,
        * but this does not affect bl_count[max_length]
        */
        overflow -= 2;
    } while (overflow > 0);

    /* Now recompute all bit lengths, scanning in increasing frequency.
    * h is still equal to ZLIBH_HEAP_SIZE. (It is simpler to reconstruct all
    * lengths instead of fixing only the wrong ones. This idea is taken
    * from 'ar' written by Haruhiko Okumura.)
    */
    for (bits = max_length; bits != 0; bits--) {
        n = bl_count[bits];
        while (n != 0) {
            m = huf_heap[--h];
            if (m > max_code) continue;
            if ((unsigned) tree[m].Len != (unsigned) bits) {
                //                fprintf(stderr,"code %d bits %d->%d\n", m, tree[m].Len, bits);
                csize[0] += ((long)bits - (long)tree[m].Len)*(long)tree[m].Freq;
                tree[m].Len = (unsigned short)bits;
            }
            n--;
        }
    }
}


/* ===========================================================================
* Construct one Huffman tree and assigns the code bit strings and lengths.
* Update the total bit length for the current block.
* IN assertion: the field freq is set for all tree elements.
* OUT assertions: the fields len and code are set to the optimal bit length
*     and corresponding code. The length os_len[0] is updated; os_len[1] is
*     also updated if stree is not null. The field max_code is set.
*/
static void build_tree(tree_desc* desc)
{
    ct_data *tree         = desc->dyn_tree;
    const ct_data *stree  = desc->stat_desc->static_tree;
    int elems             = desc->max_code;
    unsigned long *csize  = desc->comp_size;
    int n;                              /* iterate over heap elements */
    int max_code = -1;                  /* largest code with non zero frequency */
    int huf_heap[2*ZLIBH_L_CODES+1];    /* heap used to build the Huffman trees */
    int heap_max;                       /* element of largest frequency */
    unsigned char depth[2*ZLIBH_L_CODES+1];
    /* Depth of each subtree used as tie breaker for trees of equal frequency */

    /* Construct the initial heap, with least frequent element in
    * huf_heap[SMALLEST]. The sons of huf_heap[n] are huf_heap[2*n] and huf_heap[2*n+1].
    * huf_heap[0] is used in replacement of heap_len (original Zlib).
    */

    huf_heap[0] = 0, heap_max = ZLIBH_HEAP_SIZE;

    for (n = 0; n <2*ZLIBH_L_CODES+1; n++)
        depth[n] = 0;

    for (n = 0; n < elems; n++) {
        if (tree[n].Freq != 0) {
            huf_heap[0]++;
            huf_heap[huf_heap[0]] = max_code = n;
            depth[n] = 0;
        } else {
            tree[n].Len = 0;
        }
    }

    /* The pkzip format requires that at least one distance code exists,
    * and that at least one bit should be sent even if there is only one
    * possible code.
    */

    if (huf_heap[0] > 1) {                /* at least two codes (non trivial tree) */
        int node;                           /* new node being created */
        unsigned short bl_count[ZLIBH_MAX_BITS+1];
        /* number of codes at each bit length for an optimal tree */

        desc->max_code = max_code;

        /* The elements huf_heap[huf_heap[0]/2+1 .. huf_heap[0]] are leaves of the tree,
        * establish sub-heaps of increasing lengths:
        */
        for (n = huf_heap[0]/2; n >= 1; n--) pqdownheap(tree, huf_heap, depth, n);

        /* Construct the Huffman tree by repeatedly combining the least two
        * frequent nodes.
        */
        node = elems;                          /* next internal node of the tree */
        do {
            int m;
            pqremove(tree, huf_heap, depth, n);  /* n = node of least frequency */
            m = huf_heap[SMALLEST];              /* m = node of next least frequency */

            huf_heap[--(heap_max)] = n;          /* keep the nodes sorted by frequency */
            huf_heap[--(heap_max)] = m;

            /* Create a new node father of n and m */
            tree[node].Freq = tree[n].Freq + tree[m].Freq;
            depth[node] = (unsigned char)((depth[n] >= depth[m] ? depth[n] : depth[m]) + 1);
            tree[n].Dad = tree[m].Dad = (unsigned short)node;

            /* and insert the new node in the heap */
            huf_heap[SMALLEST] = node++;
            pqdownheap(tree, huf_heap, depth, SMALLEST);

        } while (huf_heap[0] >= 2);

        huf_heap[--(heap_max)] = huf_heap[SMALLEST];

        /* At this point, the fields freq and dad are set. We can now
        * generate the bit lengths.
        */
        gen_bitlen((tree_desc *)desc, huf_heap, heap_max, bl_count);

        /* The field len is now set, we can generate the bit codes */
        gen_codes ((ct_data *)tree, max_code, bl_count);
    }
    else if (huf_heap[0] == 0) {     /* no code at all, create a single dummy zero code */
        desc->max_code = 0;
        tree[0].Len = 0;               // gen_bitlen shortcut
        tree[0].Code = 0;              // gen_codes shortcut (probably useless)
    }
    else {                           /* only one code, create a single one bit code */
        const int *extra     = desc->stat_desc->extra_bits;
        int base             = desc->stat_desc->extra_base;
        int xbits;                     /* extra bits */
        unsigned short f;              /* frequency */

        desc->max_code = max_code;
        for (n = 0; n < max_code; n++) {
            tree[n].Len = 0;
        }
        tree[max_code].Len = 1;        // gen_bitlen shortcut
        xbits = 0;
        if (max_code >= base) xbits = extra[max_code-base];
        f = tree[max_code].Freq;
        csize[0] += (unsigned long)f * (1 + xbits);
        if (stree) csize[1] += (unsigned long)f * (stree[max_code].Len + xbits);
        tree[max_code].Code = 0;       // gen_codes shortcut, not set earlier since it replaces .Freq
    }
}


int ZLIBH_compress (char* dest, const char* source, int inputSize)
{
    const unsigned char* ip = (const unsigned char*)source;
    const unsigned char* const bsourceend = ip+inputSize;
    const unsigned char* bsource = (const unsigned char*)source;
    unsigned char* op = (unsigned char*)dest;
    tree_desc ltree;
    ct_data dyn_ltree[ZLIBH_HEAP_SIZE];
    unsigned long ldata_compsize[2] = {0};
    tree_desc bltree;
    ct_data dyn_bltree[2*ZLIBH_BL_CODES+1];
    unsigned long bldata_compsize[2] = {0};
    int symbol;
    int max_blindex;
    int compressed_size;

    U32   freq_l[257]= {0};

    /* literal tree init */
    ltree.dyn_tree  = dyn_ltree;
    ltree.comp_size = ldata_compsize;
    ltree.max_code  = ZLIBH_L_CODES;
    ltree.stat_desc = &static_l_desc;

    /* bitlen tree init */
    bltree.dyn_tree  = dyn_bltree;
    bltree.comp_size = bldata_compsize;
    bltree.max_code  = ZLIBH_BL_CODES;
    bltree.stat_desc = &static_bl_desc;

    /* scan for stats */
    while (bsource < bsourceend) freq_l[*bsource++]++;
    freq_l[256]=1;

    symbol = 0;
    do {
        dyn_ltree[symbol].Freq = (unsigned short)freq_l[symbol];
        ++symbol;
    } while (symbol < 257);

    build_tree(&ltree);

    /* Determine the bit length frequencies for literal tree */
    feed_bltree(&ltree, &bltree);

    /* Build the bit length tree: */
    build_tree(&bltree);

    /* Determine the number of bit length codes to send. The pkzip format
    * requires that at least 4 bit length codes be sent.
    */
    for (max_blindex = ZLIBH_BL_CODES-1; max_blindex >= 3; max_blindex--) {
        if (dyn_bltree[bl_order[max_blindex]].Len != 0) break;
    }
    bldata_compsize[0] += 3*(max_blindex+1)+4;

    if ((bldata_compsize[0]+ldata_compsize[0]) < ldata_compsize[1]) {  /* write bloc using the dynamic tree */
        *op = (unsigned char)(max_blindex+1);
        ZLIBH_compress_block(ip, op, dyn_ltree, dyn_bltree, inputSize);
        compressed_size = (int)((bldata_compsize[0]+ldata_compsize[0]+8) >> 3);
    }
    else {                                                             /* write bloc using the static tree */
        ZLIBH_compress_block(ip, op, static_ltree, dyn_bltree, inputSize);
        compressed_size = (int)((ldata_compsize[1]+8) >> 3);
    }
    return compressed_size;
}

int ZLIBH_getDistributionTotal() { return ZLIBH_MAX_TABLESIZE; }


//****************************
// Decompression CODE
//****************************

/* Possible inflate modes between inflate() calls */
typedef enum {
    TYPEDO,     /* i: same, but skip check to exit inflate on new block */
    TABLE,      /* i: waiting for dynamic block table lengths */
    LEN,        /* i: waiting for length/lit/eob code */
    DONE,       /* finished check, done -- remain here until reset */
    BAD,        /* got a data error -- remain here until reset */
} inflate_mode;

#define ENOUGH_LENS 852
#define ENOUGH_DISTS 592
#define ENOUGH (ENOUGH_LENS+ENOUGH_DISTS)

typedef struct {
    unsigned char op;           /* operation, extra bits, table bits */
    unsigned char bits;         /* bits in this part of the code */
    unsigned short val;         /* offset in table or code value */
} code;

static const code lenfix[512] = {
    {96,7,0},{0,8,80},{0,8,16},{20,8,115},{18,7,31},{0,8,112},{0,8,48},
    {0,9,192},{16,7,10},{0,8,96},{0,8,32},{0,9,160},{0,8,0},{0,8,128},
    {0,8,64},{0,9,224},{16,7,6},{0,8,88},{0,8,24},{0,9,144},{19,7,59},
    {0,8,120},{0,8,56},{0,9,208},{17,7,17},{0,8,104},{0,8,40},{0,9,176},
    {0,8,8},{0,8,136},{0,8,72},{0,9,240},{16,7,4},{0,8,84},{0,8,20},
    {21,8,227},{19,7,43},{0,8,116},{0,8,52},{0,9,200},{17,7,13},{0,8,100},
    {0,8,36},{0,9,168},{0,8,4},{0,8,132},{0,8,68},{0,9,232},{16,7,8},
    {0,8,92},{0,8,28},{0,9,152},{20,7,83},{0,8,124},{0,8,60},{0,9,216},
    {18,7,23},{0,8,108},{0,8,44},{0,9,184},{0,8,12},{0,8,140},{0,8,76},
    {0,9,248},{16,7,3},{0,8,82},{0,8,18},{21,8,163},{19,7,35},{0,8,114},
    {0,8,50},{0,9,196},{17,7,11},{0,8,98},{0,8,34},{0,9,164},{0,8,2},
    {0,8,130},{0,8,66},{0,9,228},{16,7,7},{0,8,90},{0,8,26},{0,9,148},
    {20,7,67},{0,8,122},{0,8,58},{0,9,212},{18,7,19},{0,8,106},{0,8,42},
    {0,9,180},{0,8,10},{0,8,138},{0,8,74},{0,9,244},{16,7,5},{0,8,86},
    {0,8,22},{64,8,0},{19,7,51},{0,8,118},{0,8,54},{0,9,204},{17,7,15},
    {0,8,102},{0,8,38},{0,9,172},{0,8,6},{0,8,134},{0,8,70},{0,9,236},
    {16,7,9},{0,8,94},{0,8,30},{0,9,156},{20,7,99},{0,8,126},{0,8,62},
    {0,9,220},{18,7,27},{0,8,110},{0,8,46},{0,9,188},{0,8,14},{0,8,142},
    {0,8,78},{0,9,252},{96,7,0},{0,8,81},{0,8,17},{21,8,131},{18,7,31},
    {0,8,113},{0,8,49},{0,9,194},{16,7,10},{0,8,97},{0,8,33},{0,9,162},
    {0,8,1},{0,8,129},{0,8,65},{0,9,226},{16,7,6},{0,8,89},{0,8,25},
    {0,9,146},{19,7,59},{0,8,121},{0,8,57},{0,9,210},{17,7,17},{0,8,105},
    {0,8,41},{0,9,178},{0,8,9},{0,8,137},{0,8,73},{0,9,242},{16,7,4},
    {0,8,85},{0,8,21},{16,8,258},{19,7,43},{0,8,117},{0,8,53},{0,9,202},
    {17,7,13},{0,8,101},{0,8,37},{0,9,170},{0,8,5},{0,8,133},{0,8,69},
    {0,9,234},{16,7,8},{0,8,93},{0,8,29},{0,9,154},{20,7,83},{0,8,125},
    {0,8,61},{0,9,218},{18,7,23},{0,8,109},{0,8,45},{0,9,186},{0,8,13},
    {0,8,141},{0,8,77},{0,9,250},{16,7,3},{0,8,83},{0,8,19},{21,8,195},
    {19,7,35},{0,8,115},{0,8,51},{0,9,198},{17,7,11},{0,8,99},{0,8,35},
    {0,9,166},{0,8,3},{0,8,131},{0,8,67},{0,9,230},{16,7,7},{0,8,91},
    {0,8,27},{0,9,150},{20,7,67},{0,8,123},{0,8,59},{0,9,214},{18,7,19},
    {0,8,107},{0,8,43},{0,9,182},{0,8,11},{0,8,139},{0,8,75},{0,9,246},
    {16,7,5},{0,8,87},{0,8,23},{64,8,0},{19,7,51},{0,8,119},{0,8,55},
    {0,9,206},{17,7,15},{0,8,103},{0,8,39},{0,9,174},{0,8,7},{0,8,135},
    {0,8,71},{0,9,238},{16,7,9},{0,8,95},{0,8,31},{0,9,158},{20,7,99},
    {0,8,127},{0,8,63},{0,9,222},{18,7,27},{0,8,111},{0,8,47},{0,9,190},
    {0,8,15},{0,8,143},{0,8,79},{0,9,254},{96,7,0},{0,8,80},{0,8,16},
    {20,8,115},{18,7,31},{0,8,112},{0,8,48},{0,9,193},{16,7,10},{0,8,96},
    {0,8,32},{0,9,161},{0,8,0},{0,8,128},{0,8,64},{0,9,225},{16,7,6},
    {0,8,88},{0,8,24},{0,9,145},{19,7,59},{0,8,120},{0,8,56},{0,9,209},
    {17,7,17},{0,8,104},{0,8,40},{0,9,177},{0,8,8},{0,8,136},{0,8,72},
    {0,9,241},{16,7,4},{0,8,84},{0,8,20},{21,8,227},{19,7,43},{0,8,116},
    {0,8,52},{0,9,201},{17,7,13},{0,8,100},{0,8,36},{0,9,169},{0,8,4},
    {0,8,132},{0,8,68},{0,9,233},{16,7,8},{0,8,92},{0,8,28},{0,9,153},
    {20,7,83},{0,8,124},{0,8,60},{0,9,217},{18,7,23},{0,8,108},{0,8,44},
    {0,9,185},{0,8,12},{0,8,140},{0,8,76},{0,9,249},{16,7,3},{0,8,82},
    {0,8,18},{21,8,163},{19,7,35},{0,8,114},{0,8,50},{0,9,197},{17,7,11},
    {0,8,98},{0,8,34},{0,9,165},{0,8,2},{0,8,130},{0,8,66},{0,9,229},
    {16,7,7},{0,8,90},{0,8,26},{0,9,149},{20,7,67},{0,8,122},{0,8,58},
    {0,9,213},{18,7,19},{0,8,106},{0,8,42},{0,9,181},{0,8,10},{0,8,138},
    {0,8,74},{0,9,245},{16,7,5},{0,8,86},{0,8,22},{64,8,0},{19,7,51},
    {0,8,118},{0,8,54},{0,9,205},{17,7,15},{0,8,102},{0,8,38},{0,9,173},
    {0,8,6},{0,8,134},{0,8,70},{0,9,237},{16,7,9},{0,8,94},{0,8,30},
    {0,9,157},{20,7,99},{0,8,126},{0,8,62},{0,9,221},{18,7,27},{0,8,110},
    {0,8,46},{0,9,189},{0,8,14},{0,8,142},{0,8,78},{0,9,253},{96,7,0},
    {0,8,81},{0,8,17},{21,8,131},{18,7,31},{0,8,113},{0,8,49},{0,9,195},
    {16,7,10},{0,8,97},{0,8,33},{0,9,163},{0,8,1},{0,8,129},{0,8,65},
    {0,9,227},{16,7,6},{0,8,89},{0,8,25},{0,9,147},{19,7,59},{0,8,121},
    {0,8,57},{0,9,211},{17,7,17},{0,8,105},{0,8,41},{0,9,179},{0,8,9},
    {0,8,137},{0,8,73},{0,9,243},{16,7,4},{0,8,85},{0,8,21},{16,8,258},
    {19,7,43},{0,8,117},{0,8,53},{0,9,203},{17,7,13},{0,8,101},{0,8,37},
    {0,9,171},{0,8,5},{0,8,133},{0,8,69},{0,9,235},{16,7,8},{0,8,93},
    {0,8,29},{0,9,155},{20,7,83},{0,8,125},{0,8,61},{0,9,219},{18,7,23},
    {0,8,109},{0,8,45},{0,9,187},{0,8,13},{0,8,141},{0,8,77},{0,9,251},
    {16,7,3},{0,8,83},{0,8,19},{21,8,195},{19,7,35},{0,8,115},{0,8,51},
    {0,9,199},{17,7,11},{0,8,99},{0,8,35},{0,9,167},{0,8,3},{0,8,131},
    {0,8,67},{0,9,231},{16,7,7},{0,8,91},{0,8,27},{0,9,151},{20,7,67},
    {0,8,123},{0,8,59},{0,9,215},{18,7,19},{0,8,107},{0,8,43},{0,9,183},
    {0,8,11},{0,8,139},{0,8,75},{0,9,247},{16,7,5},{0,8,87},{0,8,23},
    {64,8,0},{19,7,51},{0,8,119},{0,8,55},{0,9,207},{17,7,15},{0,8,103},
    {0,8,39},{0,9,175},{0,8,7},{0,8,135},{0,8,71},{0,9,239},{16,7,9},
    {0,8,95},{0,8,31},{0,9,159},{20,7,99},{0,8,127},{0,8,63},{0,9,223},
    {18,7,27},{0,8,111},{0,8,47},{0,9,191},{0,8,15},{0,8,143},{0,8,79},
    {0,9,255}
};

static const code distfix[32] = {
    {16,5,1},{23,5,257},{19,5,17},{27,5,4097},{17,5,5},{25,5,1025},
    {21,5,65},{29,5,16385},{16,5,3},{24,5,513},{20,5,33},{28,5,8193},
    {18,5,9},{26,5,2049},{22,5,129},{64,5,0},{16,5,2},{23,5,385},
    {19,5,25},{27,5,6145},{17,5,7},{25,5,1537},{21,5,97},{29,5,24577},
    {16,5,4},{24,5,769},{20,5,49},{28,5,12289},{18,5,13},{26,5,3073},
    {22,5,193},{64,5,0}
};

/* state maintained between inflate() calls.  Approximately 10K bytes. */
struct inflate_state {
    inflate_mode mode;          /* current inflate mode */
    int last;                   /* true if processing last block */
    int wrap;                   /* bit 0 true for zlib, bit 1 true for gzip */
    int havedict;               /* true if dictionary provided */
    int flags;                  /* gzip header method and flags (0 if zlib) */
    unsigned dmax;              /* zlib header max distance (INFLATE_STRICT) */
    unsigned long check;        /* protected copy of check value */
    unsigned long total;        /* protected copy of output count */
    /* sliding window */
    unsigned wbits;             /* log base 2 of requested window size */
    unsigned wsize;             /* window size or zero if not using window */
    unsigned whave;             /* valid bytes in the window */
    unsigned wnext;             /* window write index */
    unsigned char *window;  /* allocated sliding window, if needed */
    /* bit accumulator */
    unsigned long hold;         /* input bit accumulator */
    unsigned bits;              /* number of bits in "in" */
    /* for string and stored block copying */
    unsigned length;            /* literal or length of data to copy */
    unsigned offset;            /* distance back to copy string from */
    /* for table and code decoding */
    unsigned extra;             /* extra bits needed */
    /* fixed and dynamic code tables */
    code const *lencode;    /* starting table for length/literal codes */
    code const *distcode;   /* starting table for distance codes */
    unsigned lenbits;           /* index bits for lencode */
    unsigned distbits;          /* index bits for distcode */
    /* dynamic table building */
    unsigned ncode;             /* number of code length code lengths */
    unsigned nlen;              /* number of length code lengths */
    unsigned ndist;             /* number of distance code lengths */
    unsigned have;              /* number of code lengths in lens[] */
    code *next;             /* next available space in codes[] */
    unsigned short lens[320];   /* temporary storage for code lengths */
    unsigned short work[288];   /* work area for code table building */
    code codes[ENOUGH];         /* space for code tables */
    int sane;                   /* if false, allow invalid distance too */
    int back;                   /* bits back of last unprocessed length/lit */
    unsigned was;               /* initial length of match */
};

static void fixedtables(struct inflate_state *state)
{
    state->lencode = lenfix;
    state->lenbits = 9;
    state->distcode = distfix;
    state->distbits = 5;
}

/* op values as set by inflate_table():
00000000 - literal
0000tttt - table link, tttt != 0 is the number of table index bits
0001eeee - length or distance, eeee is the number of extra bits
01100000 - end of block
01000000 - invalid code
*/

/* Maximum size of the dynamic table.  The maximum number of code structures is
1444, which is the sum of 852 for literal/length codes and 592 for distance
codes.  These values were found by exhaustive searches using the program
examples/enough.c found in the zlib distribtution.  The arguments to that
program are the number of symbols, the initial root table size, and the
maximum bit length of a code.  "enough 286 9 15" for literal/length codes
returns returns 852, and "enough 30 6 15" for distance codes returns 592.
The initial root table size (9 or 6) is found in the fifth argument of the
inflate_table() calls in inflate.c and infback.c.  If the root table size is
changed, then these maximum sizes would be need to be recalculated and
updated. */

/* Type of code to build for inflate_table() */
typedef enum {
    CODES,
    LENS,
    DISTS
} codetype;

/* Macros for inflate(): */

/* check function to use adler32() for zlib or crc32() for gzip */
#ifdef GUNZIP
#  define UPDATE(check, buf, len) \
    (state.flags ? crc32(check, buf, len) : adler32(check, buf, len))
#else
#  define UPDATE(check, buf, len) adler32(check, buf, len)
#endif

/* check macros for header crc */
#ifdef GUNZIP
#  define CRC2(check, word) \
    do { \
    hbuf[0] = (unsigned char)(word); \
    hbuf[1] = (unsigned char)((word) >> 8); \
    check = crc32(check, hbuf, 2); \
    } while (0)

#  define CRC4(check, word) \
    do { \
    hbuf[0] = (unsigned char)(word); \
    hbuf[1] = (unsigned char)((word) >> 8); \
    hbuf[2] = (unsigned char)((word) >> 16); \
    hbuf[3] = (unsigned char)((word) >> 24); \
    check = crc32(check, hbuf, 4); \
    } while (0)
#endif

/* Load registers with state in inflate() for speed */
#define LOAD() \
    do { \
    put = strm->next_out; \
    left = strm->avail_out; \
    next = strm->next_in; \
    have = strm->avail_in; \
    hold = state.hold; \
    bits = state.bits; \
    } while (0)

/* Restore state from registers in inflate() */
#define RESTORE() \
    do { \
    strm->next_out = put; \
    strm->avail_out = left; \
    strm->next_in = next; \
    strm->avail_in = have; \
    state.hold = hold; \
    state.bits = bits; \
    } while (0)


/* Get a byte of input into the bit accumulator, or return from inflate()
if there is no input available. */
#define PULLBYTE() \
    do { \
    hold += (unsigned long)(*next++) << bits; \
    bits += 8; \
    } while (0)

/* Assure that there are at least n bits in the bit accumulator.  If there is
not enough available input to do that, then return from inflate(). */
#define NEEDBITS(n) \
    do { \
    while (bits < (unsigned)(n)) \
    PULLBYTE(); \
    } while (0)

/* Return the low n bits of the bit accumulator (n < 16) */
#define BITS(n) \
    ((unsigned)hold & ((1U << (n)) - 1))

/* Remove n bits from the bit accumulator */
#define DROPBITS(n) \
    do { \
    hold >>= (n); \
    bits -= (unsigned)(n); \
    } while (0)

/* Remove zero to seven bits as needed to go to a byte boundary */
#define BYTEBITS() \
    do { \
    hold >>= bits & 7; \
    bits -= bits & 7; \
    } while (0)

/*
Build a set of tables to decode the provided canonical Huffman code.
The code lengths are lens[0..codes-1].  The result starts at *table,
whose indices are 0..2^bits-1.  work is a writable array of at least
lens shorts, which is used as a work area.  type is the type of code
to be generated, CODES, LENS, or DISTS.  On return, zero is success,
-1 is an invalid code, and +1 means that ENOUGH isn't enough.  table
on return points to the next available entry's address.  bits is the
requested root table index bits, and on return it is the actual root
table index bits.  It will differ if the request is greater than the
longest code or if it is less than the shortest code.
*/
int inflate_table(codetype type, unsigned short * lens, unsigned codes, code * *table, unsigned *bits, unsigned short *work)
{
    unsigned len;               /* a code's length in bits */
    unsigned sym;               /* index of code symbols */
    unsigned min, max;          /* minimum and maximum code lengths */
    unsigned root;              /* number of index bits for root table */
    unsigned curr;              /* number of index bits for current table */
    unsigned drop;              /* code bits to drop for sub-table */
    int left;                   /* number of prefix codes available */
    unsigned used;              /* code entries in table used */
    unsigned huff;              /* Huffman code */
    unsigned incr;              /* for incrementing code, index */
    unsigned low;               /* low bits for current root entry */
    unsigned mask;              /* mask for low root bits */
    code here;                  /* table entry for duplication */
    code *next;             /* next available space in table */
    const unsigned short *base;     /* base value table to use */
    const unsigned short *extra;    /* extra bits table to use */
    int end;                    /* use base and extra for symbol > end */
    unsigned short count[ZLIBH_MAX_BITS+1];    /* number of codes of each length */
    unsigned short offs[ZLIBH_MAX_BITS+1];     /* offsets in table for each length */
    static const unsigned short lbase[31] = { /* Length codes 257..285 base */
        3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
        35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258, 0, 0};
    static const unsigned short lext[31] = { /* Length codes 257..285 extra */
        16, 16, 16, 16, 16, 16, 16, 16, 17, 17, 17, 17, 18, 18, 18, 18,
        19, 19, 19, 19, 20, 20, 20, 20, 21, 21, 21, 21, 16, 72, 78};
    static const unsigned short dbase[32] = { /* Distance codes 0..29 base */
        1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
        257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
        8193, 12289, 16385, 24577, 0, 0};
    static const unsigned short dext[32] = { /* Distance codes 0..29 extra */
        16, 16, 16, 16, 17, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22, 22,
        23, 23, 24, 24, 25, 25, 26, 26, 27, 27,
        28, 28, 29, 29, 64, 64};

    /*
    Process a set of code lengths to create a canonical Huffman code.  The
    code lengths are lens[0..codes-1].  Each length corresponds to the
    symbols 0..codes-1.  The Huffman code is generated by first sorting the
    symbols by length from short to long, and retaining the symbol order
    for codes with equal lengths.  Then the code starts with all zero bits
    for the first code of the shortest length, and the codes are integer
    increments for the same length, and zeros are appended as the length
    increases.  For the deflate format, these bits are stored backwards
    from their more natural integer increment ordering, and so when the
    decoding tables are built in the large loop below, the integer codes
    are incremented backwards.

    This routine assumes, but does not check, that all of the entries in
    lens[] are in the range 0..ZLIBH_MAX_BITS.  The caller must assure this.
    1..ZLIBH_MAX_BITS is interpreted as that code length.  zero means that that
    symbol does not occur in this code.

    The codes are sorted by computing a count of codes for each length,
    creating from that a table of starting indices for each length in the
    sorted table, and then entering the symbols in order in the sorted
    table.  The sorted table is work[], with that space being provided by
    the caller.

    The length counts are used for other purposes as well, i.e. finding
    the minimum and maximum length codes, determining if there are any
    codes at all, checking for a valid set of lengths, and looking ahead
    at length counts to determine sub-table sizes when building the
    decoding tables.
    */

    /* accumulate lengths for codes (assumes lens[] all in 0..ZLIBH_MAX_BITS) */
    for (len = 0; len <= ZLIBH_MAX_BITS; len++)
        count[len] = 0;
    for (sym = 0; sym < codes; sym++)
        count[lens[sym]]++;

    /* bound code lengths, force root to be within code lengths */
    root = *bits;
    for (max = ZLIBH_MAX_BITS; max >= 1; max--)
        if (count[max] != 0) break;
    if (root > max) root = max;
    if (max == 0) {                     /* no symbols to code at all */
        here.op = (unsigned char)64;    /* invalid code marker */
        here.bits = (unsigned char)1;
        here.val = (unsigned short)0;
        *(*table)++ = here;             /* make a table to force an error */
        *(*table)++ = here;
        *bits = 1;
        return 0;     /* no symbols, but wait for decoding to report error */
    }
    for (min = 1; min < max; min++)
        if (count[min] != 0) break;
    if (root < min) root = min;

    /* check for an over-subscribed or incomplete set of lengths */
    left = 1;
    for (len = 1; len <= ZLIBH_MAX_BITS; len++) {
        left <<= 1;
        left -= count[len];
        if (left < 0) return -1;        /* over-subscribed */
    }
    if (left > 0 && (type == CODES || max != 1))
        return -1;                      /* incomplete set */

    /* generate offsets into symbol table for each length for sorting */
    offs[1] = 0;
    for (len = 1; len < ZLIBH_MAX_BITS; len++)
        offs[len + 1] = offs[len] + count[len];

    /* sort symbols by length, by symbol order within each length */
    for (sym = 0; sym < codes; sym++)
        if (lens[sym] != 0) work[offs[lens[sym]]++] = (unsigned short)sym;

    /*
    Create and fill in decoding tables.  In this loop, the table being
    filled is at next and has curr index bits.  The code being used is huff
    with length len.  That code is converted to an index by dropping drop
    bits off of the bottom.  For codes where len is less than drop + curr,
    those top drop + curr - len bits are incremented through all values to
    fill the table with replicated entries.

    root is the number of index bits for the root table.  When len exceeds
    root, sub-tables are created pointed to by the root entry with an index
    of the low root bits of huff.  This is saved in low to check for when a
    new sub-table should be started.  drop is zero when the root table is
    being filled, and drop is root when sub-tables are being filled.

    When a new sub-table is needed, it is necessary to look ahead in the
    code lengths to determine what size sub-table is needed.  The length
    counts are used for this, and so count[] is decremented as codes are
    entered in the tables.

    used keeps track of how many table entries have been allocated from the
    provided *table space.  It is checked for LENS and DIST tables against
    the constants ENOUGH_LENS and ENOUGH_DISTS to guard against changes in
    the initial root table size constants.  See the comments in inftrees.h
    for more information.

    sym increments through all symbols, and the loop terminates when
    all codes of length max, i.e. all codes, have been processed.  This
    routine permits incomplete codes, so another loop after this one fills
    in the rest of the decoding tables with invalid code markers.
    */

    /* set up for code type */
    switch (type) {
    case CODES:
        base = extra = work;    /* dummy value--not used */
        end = 19;
        break;
    case LENS:
        base = lbase;
        base -= 257;
        extra = lext;
        extra -= 257;
        end = 256;
        break;
    case DISTS:
    default:            /* DISTS */
        base = dbase;
        extra = dext;
        end = -1;
    }

    /* initialize state for loop */
    huff = 0;                   /* starting code */
    sym = 0;                    /* starting code symbol */
    len = min;                  /* starting code length */
    next = *table;              /* current table to fill in */
    curr = root;                /* current table index bits */
    drop = 0;                   /* current bits to drop from code for index */
    low = (unsigned)(-1);       /* trigger new sub-table when len > root */
    used = 1U << root;          /* use root table entries */
    mask = used - 1;            /* mask for comparing low */

    /* check available table space */
    if ((type == LENS && used > ENOUGH_LENS) ||
        (type == DISTS && used > ENOUGH_DISTS))
        return 1;

    /* process all codes and make table entries */
    for (;;) {
        unsigned fill;              /* index for replicating entries */

        /* create table entry */
        here.bits = (unsigned char)(len - drop);
        if ((int)(work[sym]) < end) {
            here.op = (unsigned char)0;
            here.val = work[sym];
        }
        else if ((int)(work[sym]) > end) {
            here.op = (unsigned char)(extra[work[sym]]);
            here.val = base[work[sym]];
        }
        else {
            here.op = (unsigned char)(32 + 64);         /* end of block */
            here.val = 0;
        }

        /* replicate for those indices with low len bits equal to huff */
        incr = 1U << (len - drop);
        fill = 1U << curr;
        min = fill;                 /* save offset to next table */
        do {
            fill -= incr;
            next[(huff >> drop) + fill] = here;
        } while (fill != 0);

        /* backwards increment the len-bit code huff */
        incr = 1U << (len - 1);
        while (huff & incr)
            incr >>= 1;
        if (incr != 0) {
            huff &= incr - 1;
            huff += incr;
        }
        else
            huff = 0;

        /* go to next symbol, update count, len */
        sym++;
        if (--(count[len]) == 0) {
            if (len == max) break;
            len = lens[work[sym]];
        }

        /* create new sub-table if needed */
        if (len > root && (huff & mask) != low) {
            /* if first time, transition to sub-tables */
            if (drop == 0)
                drop = root;

            /* increment past last table */
            next += min;            /* here min is 1 << curr */

            /* determine length of next table */
            curr = len - drop;
            left = (int)(1 << curr);
            while (curr + drop < max) {
                left -= count[curr + drop];
                if (left <= 0) break;
                curr++;
                left <<= 1;
            }

            /* check for enough space */
            used += 1U << curr;
            if ((type == LENS && used > ENOUGH_LENS) ||
                (type == DISTS && used > ENOUGH_DISTS))
                return 1;

            /* point entry in root table to sub-table */
            low = huff & mask;
            (*table)[low].op = (unsigned char)curr;
            (*table)[low].bits = (unsigned char)root;
            (*table)[low].val = (unsigned short)(next - *table);
        }
    }

    /* fill in remaining table entry if code is incomplete (guaranteed to have
    at most one remaining entry, since if the code is incomplete, the
    maximum code length that was allowed to get this far is one bit) */
    if (huff != 0) {
        here.op = (unsigned char)64;            /* invalid code marker */
        here.bits = (unsigned char)(len - drop);
        here.val = (unsigned short)0;
        next[huff] = here;
    }

    /* set return parameters */
    *table += used;
    *bits = root;
    return 0;
}


/*
inflate() uses a state machine to process as much input data and generate as
much output data as possible before returning.  The state machine is
structured roughly as follows:

for (;;) switch (state) {
...
case STATEn:
if (not enough input data or output space to make progress)
return;
... make progress ...
state = STATEm;
break;
...
}

so when inflate() is called again, the same case is attempted again, and
if the appropriate resources are provided, the machine proceeds to the
next state.  The NEEDBITS() macro is usually the way the state evaluates
whether it can proceed or should return.  NEEDBITS() does the return if
the requested bits are not available.  The typical use of the BITS macros
is:

NEEDBITS(n);
... do something with BITS(n) ...
DROPBITS(n);

where NEEDBITS(n) either returns from inflate() if there isn't enough
input left to load n bits into the accumulator, or it continues.  BITS(n)
gives the low n bits in the accumulator.  When done, DROPBITS(n) drops
the low n bits off the accumulator.  INITBITS() clears the accumulator
and sets the number of available bits to zero.  BYTEBITS() discards just
enough bits to put the accumulator on a byte boundary.  After BYTEBITS()
and a NEEDBITS(8), then BITS(8) would return the next byte in the stream.

NEEDBITS(n) uses PULLBYTE() to get an available byte of input, or to return
if there is no input available.  The decoding of variable length codes uses
PULLBYTE() directly in order to pull just enough bytes to decode the next
code, and no more.

Some states loop until they get enough input, making sure that enough
state information is maintained to continue the loop where it left off
if NEEDBITS() returns in the loop.  For example, want, need, and keep
would all have to actually be part of the saved state in case NEEDBITS()
returns:

case STATEw:
while (want < need) {
NEEDBITS(n);
keep[want++] = BITS(n);
DROPBITS(n);
}
state = STATEx;
case STATEx:

As shown above, if the next state is also the next case, then the break
is omitted.

A state may also return if there is not enough output space available to
complete that state.  Those states are copying stored data, writing a
literal byte, and copying a matching string.

When returning, a "goto inf_leave" is used to update the total counters,
update the check value, and determine whether any progress has been made
during that inflate() call in order to return the proper return code.
Progress is defined as a change in either strm->avail_in or strm->avail_out.
When there is a window, goto inf_leave will update the window with the last
output written.  If a goto inf_leave occurs in the middle of decompression
and there is no window currently, goto inf_leave will create one and copy
output to the window for the next call of inflate().

In this implementation, the flush parameter of inflate() only affects the
return code (per zlib.h).  inflate() always writes as much as possible to
strm->next_out, given the space available and the provided input--the effect
documented in zlib.h of Z_SYNC_FLUSH.  Furthermore, inflate() always defers
the allocation of and copying into a sliding window until necessary, which
provides the effect documented in zlib.h for Z_FINISH when the entire input
stream available.  So the only thing the flush parameter actually does is:
when flush is set to Z_FINISH, inflate() cannot return Z_OK.  Instead it
will return Z_BUF_ERROR if it has not reached the end of the stream.
*/

int ZLIBH_inflate(unsigned char* dest, const unsigned char* compressed)
{
    const unsigned char *next = (const unsigned char*)compressed;   /* next input */
    unsigned char *put  = (unsigned char*)dest;         /* next output */
    unsigned hold;              /* bit buffer */
    unsigned bits;              /* bits in bit buffer */
    unsigned copy;              /* number of stored or match bytes to copy */
    code here;                  /* current decoding table entry */
    unsigned len;               /* length to copy for repeats, bits to drop */
    int ret;                    /* return code */
    struct inflate_state state;
    static const unsigned short order[19] = /* permutation of code lengths */
    {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    code const *lcode;
    unsigned lmask;             /* mask for first level of length codes */
    unsigned codebits;          /* code bits, operation, was op */

    state.mode = TYPEDO;      /* skip check */

    /* Clear the input bit accumulator */
    hold = 0;
    bits = 0;
    for (;;)
        switch (state.mode) {
        case TYPEDO:
            NEEDBITS(1);
            switch (BITS(1)) {
            case 0:                             /* dynamic block */
                state.mode = TABLE;
                break;

            case 1:                             /* fixed block */
                fixedtables(&state);
                state.mode = LEN;             /* decode codes */
                break;
            }
            DROPBITS(1);
            break;

        case TABLE:
            NEEDBITS(4);
            state.nlen = 257;
            state.ndist = 0;
            state.ncode = BITS(4) + 4;
            DROPBITS(4);

            state.have = 0;

            while (state.have < state.ncode) {
                NEEDBITS(3);
                state.lens[order[state.have++]] = (unsigned short)BITS(3);
                DROPBITS(3);
            }
            while (state.have < 19)
                state.lens[order[state.have++]] = 0;
            state.next = state.codes;
            state.lencode = (const code *)(state.next);
            state.lenbits = 7;
            ret = inflate_table(CODES, state.lens, 19, &(state.next),
                &(state.lenbits), state.work);
            if (ret) {
                state.mode = BAD;
                break;
            }
            state.have = 0;

            while (state.have < state.nlen) {
                for (;;) {
                    here = state.lencode[BITS(state.lenbits)];
                    if ((unsigned)(here.bits) <= bits) break;
                    PULLBYTE();
                }
                if (here.val < 16) {
                    DROPBITS(here.bits);
                    state.lens[state.have++] = here.val;
                }
                else {
                    if (here.val == 16) {
                        NEEDBITS(here.bits + 2);
                        DROPBITS(here.bits);
                        if (state.have == 0) {
                            state.mode = BAD;
                            break;
                        }
                        len = state.lens[state.have - 1];
                        copy = 3 + BITS(2);
                        DROPBITS(2);
                    }
                    else if (here.val == 17) {
                        NEEDBITS(here.bits + 3);
                        DROPBITS(here.bits);
                        len = 0;
                        copy = 3 + BITS(3);
                        DROPBITS(3);
                    }
                    else {
                        NEEDBITS(here.bits + 7);
                        DROPBITS(here.bits);
                        len = 0;
                        copy = 11 + BITS(7);
                        DROPBITS(7);
                    }
                    if (state.have + copy > state.nlen) {
                        state.mode = BAD;
                        break;
                    }
                    while (copy--)
                        state.lens[state.have++] = (unsigned short)len;
                }
            }

            /* handle error breaks in while */
            if (state.mode == BAD) break;

            /* check for end-of-block code (better have one) */
            if (state.lens[256] == 0) {
                state.mode = BAD;
                break;
            }

            /* build code tables -- note: do not change the lenbits or distbits
            values here (9 and 6) without reading the comments in inftrees.h
            concerning the ENOUGH constants, which depend on those values */
            state.next = state.codes;
            state.lencode = (const code *)(state.next);
            state.lenbits = 9;
            ret = inflate_table(LENS, state.lens, state.nlen, &(state.next),
                &(state.lenbits), state.work);
            if (ret) {
                state.mode = BAD;
                break;
            }
            state.mode = LEN;
            /* fallthrough */

        case LEN:
            lcode = state.lencode;
            lmask = (1U << state.lenbits) - 1;
            do {
                if (bits < 15) {
                    hold += (unsigned long)(*next++) << bits;
                    bits += 8;
                    hold += (unsigned long)(*next++) << bits;
                    bits += 8;
                }
                here = lcode[hold & lmask];
dolen:
                codebits = (unsigned)(here.bits);
                hold >>= codebits;
                bits -= codebits;
                codebits = (unsigned)(here.op);
                if (codebits == 0) {                          /* literal */
                    *put++ = (unsigned char)(here.val);
                }
                else if ((codebits & 64) == 0) {              /* 2nd level length code */
                    here = lcode[here.val + (hold & ((1U << codebits) - 1))];
                    goto dolen;
                }
                else if (codebits & 32) {                     /* end-of-block */
                    //len = bits >> 3;                        /* restitute unused bytes */
                    //next -= len;
                    break;
                }
            } while (1);
            state.mode = DONE;

        case DONE:
            goto inf_leave;
        case BAD:
            return 0;
    }
inf_leave:
    //return (int)(next-compressed);   // compressed size
    return (int)(put-dest);          // original size
}

int ZLIBH_decompress (char* dest, const char* compressed)
{
    const unsigned char* ip = (const unsigned char*)compressed;
    unsigned char* op = (unsigned char*)dest;
    return ZLIBH_inflate(op, ip);
}
