/*
    fullbench.c - Demo program to benchmark open-source compression algorithm
    Copyright (C) Yann Collet 2012-2015

    GPL v2 License

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License along
    with this program; if not, write to the Free Software Foundation, Inc.,
    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

    You can contact the author at :
    - public forum : https://groups.google.com/forum/#!forum/lz4c
    - website : http://fastcompression.blogspot.com/
*/

/*=====   Compiler's specifics   =====*/
#define _CRT_SECURE_NO_WARNINGS   /* Remove Visual warning */


/*_************************************
*  Includes
**************************************/
#include <stdlib.h>      /* malloc */
#include <stdio.h>       /* fprintf, fopen, ftello64 */
#include <string.h>      /* strcmp */
#include <time.h>        /* clock_t, clock, CLOCKS_PER_SEC */

#include "cpu.h"        /* ZSTD_cpuid_bmi2, ZSTD_cpuid */
#include "mem.h"
#include "hist.h"
#define FSE_STATIC_LINKING_ONLY
#include "fse.h"
#define HUF_STATIC_LINKING_ONLY
#include "huf.h"
#include "xxhash.h"


/*_************************************
*  Constants
**************************************/
#define PROGRAM_DESCRIPTION "FSE speed analyzer"
#ifndef FSE_VERSION
#  define FSE_VERSION ""
#endif
#define AUTHOR "Yann Collet"
#define WELCOME_MESSAGE "*** %s %s %i-bits, by %s (%s) ***\n", PROGRAM_DESCRIPTION, FSE_VERSION, (int)(sizeof(void*)*8), AUTHOR, __DATE__

#define NBLOOPS    6
#define TIMELOOP_S 2
#define TIMELOOP   (TIMELOOP_S * CLOCKS_PER_SEC)
#define BENCHCLOCK_MIN (CLOCKS_PER_SEC / 4)
#define PROBATABLESIZE 2048

#define KB *(1<<10)
#define MB *(1<<20)
#define GB *(1<<30)

#define PRIME1   2654435761U
#define PRIME2   2246822519U
#define DEFAULT_BLOCKSIZE (32 KB)
#define DEFAULT_PROBA 20


/*_************************************
*  Macros
***************************************/
#define DISPLAY(...)  fprintf(stderr, __VA_ARGS__)
#define PROGRESS(...) no_prompt ? 0 : DISPLAY(__VA_ARGS__)


/*_************************************
*  Benchmark Parameters
***************************************/
static U32 no_prompt = 0;


/*_*******************************************************
*  Private functions
**********************************************************/
static clock_t BMK_clockSpan( clock_t clockStart )
{
    return clock() - clockStart;   /* works even if overflow, span limited to <= ~30mn */
}

static U32 BMK_rand (U32* seed)
{
    *seed =  ( (*seed) * PRIME1) + PRIME2;
    return (*seed) >> 11;
}

static void BMK_genData(void* buffer, size_t buffSize, double p)
{
    char table[PROBATABLESIZE] = {0};
    int remaining = PROBATABLESIZE;
    unsigned pos = 0;
    unsigned s = 0;
    char* op = (char*) buffer;
    char* oend = op + buffSize;
    unsigned seed = 1;
    static unsigned done = 0;

    if (p<0.01) p = 0.005;
    if (p>1.) p = 1.;
    if (!done) {
        done = 1;
        DISPLAY("Generating %i KB with P=%.2f%%\n", (int)(buffSize >> 10), p*100);
    }

    /* Build Table */
    while (remaining) {
        unsigned n = (unsigned)(remaining * p);
        unsigned end;
        if (!n) n=1;
        end = pos + n;
        while (pos<end) table[pos++]=(char)s;
        s++;
        if (s==255) s=0;   /* for compatibility with count254 test */
        remaining -= n;
    }

    /* Fill buffer */
    while (op<oend) {
        const unsigned r = BMK_rand(&seed) & (PROBATABLESIZE-1);
        *op++ = table[r];
    }
}


/*_*******************************************************
*  Benchmark function
**********************************************************/
static int local_trivialCount(void* dst, size_t dstSize, const void* src, size_t srcSize)
{

    U32 count[256] = {0};
    const BYTE* ip = (const BYTE*)src;
    const BYTE* const end = ip + srcSize;

    (void)dst; (void)dstSize;
    while (ip<end) count[*ip++]++;
    return (int)count[ip[-1]];
}


static int local_count8(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
#define NBT 8
    U32 count[NBT][256];
    const BYTE* ip = (const BYTE*)src;
    const BYTE* const end = ip + srcSize - (NBT-1);

    (void)dst; (void)dstSize;
    memset(count, 0, sizeof(count));
    while (ip<end) {
        unsigned idx;
        for (idx=0; idx<NBT; idx++)
            count[idx][*ip++]++;
    }
    {   unsigned n;
        for (n=0; n<256; n++) {
            unsigned idx;
            for (idx=1; idx<NBT; idx++)
                count[0][n] += count[idx][n];
    }   }
    return (int)count[0][ip[-1]];
}


/* U64 version */
static int local_count8v2(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    U32 count[8][256+16];
    const U64* ptr = (const U64*) src;
    const U64* end = ptr + (srcSize >> 3);
    U64 next = *ptr++;

    (void)dst; (void)dstSize;
    memset(count, 0, sizeof(count));

    while (ptr != end) {
        register U64 bs = next;
        next = *ptr++;

        count[ 0][(BYTE)bs] ++;
        count[ 1][(BYTE)(bs>>8)] ++;
        count[ 2][(BYTE)(bs>>16)] ++;
        count[ 3][(BYTE)(bs>>24)] ++;
        count[ 4][(BYTE)(bs>>32)] ++;
        count[ 5][(BYTE)(bs>>40)] ++;
        count[ 6][(BYTE)(bs>>48)] ++;
        count[ 7][(BYTE)(bs>>56)] ++;
    }

    {   unsigned u;
        for (u = 0; u < 256; u++) {
            unsigned idx;
            for (idx=1; idx<8; idx++)
                count[0][u] += count[idx][u];
    }   }

    return count[0][0];
}


/* hist_X_Y function from https://github.com/powturbo/turbohist */
static int local_hist_4_32(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
//#define NU 8
  #define NU 16
  int i;
  U32 count[256]={0};
  U32 c0[256]={0},c1[256]={0},c2[256]={0},c3[256]={0};
  const U32* ip32 = (const U32*)src;
  const U32* const ip32end = ip32 + (srcSize >> 2);
  const BYTE* ip = (const BYTE*)src;
  const BYTE* const iend = ip + srcSize;
  U32 cp = *ip32;

  (void)dst; (void)dstSize;

  for(; ip32 != ip32end; )
  {
    U32 c = cp; ip32++; cp = *ip32;
    c0[(unsigned char)c      ]++;
    c1[(unsigned char)(c>>8) ]++;
    c2[(unsigned char)(c>>16)]++;
    c3[c>>24                 ]++;

        c = cp; ip32++; cp = *ip32;
    c0[(unsigned char)c      ]++;
    c1[(unsigned char)(c>>8) ]++;
    c2[(unsigned char)(c>>16)]++;
    c3[c>>24                 ]++;

      #if NU == 16
        c = cp; ip32++; cp = *ip32;
    c0[(unsigned char)c      ]++;
    c1[(unsigned char)(c>>8) ]++;
    c2[(unsigned char)(c>>16)]++;
    c3[c>>24                 ]++;

        c = cp; ip32++; cp = *ip32;
    c0[(unsigned char)c      ]++;
    c1[(unsigned char)(c>>8) ]++;
    c2[(unsigned char)(c>>16)]++;
    c3[c>>24                 ]++;
      #endif
  }
  ip = (const BYTE*)ip32;
  while(ip < iend) c0[*ip++]++;
  for(i = 0; i < 256; i++)
    count[i] = c0[i]+c1[i]+c2[i]+c3[i];

  return count[0];
}


static int local_hist_4_32v2(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
  U32 c0[256]={0},c1[256]={0},c2[256]={0},c3[256]={0};
  const U32* ip32 = (const U32*)src;
  const U32* const ip32end = ip32 + (srcSize>>2);
  const BYTE* ip = (const BYTE*)src;
  const BYTE* const iend = ip + srcSize;
  U32 cp = *ip32;
  int i;


  (void)dst; (void)dstSize;

  while (ip32 <= ip32end-4)
  {
    U32 c = cp,	d = *(++ip32); cp = *(++ip32);
    c0[(BYTE) c    ]++;
    c1[(BYTE) d    ]++;
    c2[(BYTE)(c>>8)]++; c>>=16;
    c3[(BYTE)(d>>8)]++; d>>=16;
    c0[(BYTE) c    ]++;
    c1[(BYTE) d    ]++;
    c2[ 	  c>>8 ]++;
    c3[ 	  d>>8 ]++;

    c = cp;	d = *(++ip32); cp = *(++ip32);
    c0[(BYTE) c    ]++;
    c1[(BYTE) d    ]++;
    c2[(BYTE)(c>>8)]++; c>>=16;
    c3[(BYTE)(d>>8)]++; d>>=16;
    c0[(BYTE) c    ]++;
    c1[(BYTE) d    ]++;
    c2[ 	  c>>8 ]++;
    c3[ 	  d>>8 ]++;
  }

  ip = (const BYTE*)ip32;
  while(ip < iend) c0[*ip++]++;

  for(i = 0; i < 256; i++) c0[i] += c1[i]+c2[i]+c3[i];

  return c0[0];
}


#define PAD 8

static int local_hist_8_32(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    U32 c0[256+PAD]={0},c1[256+PAD]={0},c2[256+PAD]={0},c3[256+PAD]={0},c4[256+PAD]={0},c5[256+PAD]={0},c6[256+PAD]={0},c7[256+PAD]={0};
    const U32* ip32 = (const U32*)src;
    const U32* const ip32end = ip32 + (srcSize >> 2);
    const BYTE* ip = (const BYTE*)src;
    const BYTE* const iend = (const BYTE*)src + srcSize;
    U32 cp = *(const U32*)src;
    int i;

    (void)dst; (void)dstSize;

    while( ip32 <= ip32end - 4 )
    {
        U32 c = cp,	d = *(++ip32); cp = *(++ip32);
        c0[(unsigned char) c ]++;
        c1[(unsigned char) d ]++;
        c2[(unsigned char)(c>>8)]++; c>>=16;
        c3[(unsigned char)(d>>8)]++; d>>=16;
        c4[(unsigned char) c ]++;
        c5[(unsigned char) d ]++;
        c6[ c>>8 ]++;
        c7[ d>>8 ]++;
        c = cp; d = *(++ip32); cp = *(++ip32);
        c0[(unsigned char) c ]++;
        c1[(unsigned char) d ]++;
        c2[(unsigned char)(c>>8)]++; c>>=16;
        c3[(unsigned char)(d>>8)]++; d>>=16;
        c4[(unsigned char) c ]++;
        c5[(unsigned char) d ]++;
        c6[ c>>8 ]++;
        c7[ d>>8 ]++;
    }

    ip = (const BYTE*) ip32;
    while(ip < iend) c0[*ip++]++;
    for(i = 0; i < 256; i++) c0[i] += c1[i]+c2[i]+c3[i]+c4[i]+c5[i]+c6[i]+c7[i];

    return c0[0];
}


/* Modified version of count2x64 by Nathan Kurz, using C instead of assembler */
#define C_INC_TABLES(src0, src1, count, i) \
        { \
            U64 byte0 = src0 & 0xFF;\
            U64 byte1 = src1 & 0xFF;\
            U64 byte2 = (src0 & 0xFF00) >> 8; \
            U64 byte3 = (src1 & 0xFF00) >> 8; \
            count[i+0][byte0]++;\
            count[i+1][byte1]++;\
            count[i+2][byte2]++; \
            count[i+3][byte3]++; \
        }

#define COUNT_SIZE (256+16)
static int local_count2x64v2(void* dst, size_t dstSize, const void* src0, size_t srcSize)
{
    const U64* src64 = (const U64*)src0;
    const U64* src64end = src64 + (srcSize>>3);
    const BYTE* src = (const BYTE*)src0;
    U64 remainder = srcSize;
    U64 next0, next1;

    U32 count[16][COUNT_SIZE];

   (void)dst; (void)dstSize;
    memset(count, 0, sizeof(count));
    if (srcSize < 32) goto handle_remainder;

    remainder = srcSize % 16;
    next0 = src64[0];
    next1 = src64[1];

    while (src64 != src64end)
    {
        U64 data0 = next0;
        U64 data1 = next1;

        src64 += 2;
        next0 = src64[0];
        next1 = src64[1];

        C_INC_TABLES(data0, data1, count, 0);

        data0 >>= 16;
        data1 >>= 16;
        C_INC_TABLES(data0, data1, count, 0);

        data0 >>= 16;
        data1 >>= 16;
        C_INC_TABLES(data0, data1, count, 0);

        data0 >>= 16;
        data1 >>= 16;
        C_INC_TABLES(data0, data1, count, 0);
    }


handle_remainder:
    {
        size_t i;
        for (i = 0; i < remainder; i++)
        {
            size_t byte = src[i];
            count[0][byte]++;
        }

        for (i = 0; i < 256; i++)
        {
            int idx;
            for (idx=1; idx < 16; idx++)
            {
                count[0][i] += count[idx][i];
            }
        }
    }

    return count[0][0];
}

static void histo_by8(U32* counts, const BYTE* rawArray, size_t rawLen)
{
    U32 countsArray[4][256];
    memset(countsArray,0,sizeof(countsArray));

    const BYTE* rawPtr = rawArray;
    const BYTE* const rawEnd = rawArray+rawLen;
    const BYTE* rawEndMul4 = rawArray+(rawLen&~3);

    while(rawPtr < rawEndMul4) {
        U64 x = MEM_read64(rawPtr);
        countsArray[0][x & 0xff]++; x >>= 8;
        countsArray[1][x & 0xff]++; x >>= 8;
        countsArray[2][x & 0xff]++; x >>= 8;
        countsArray[3][x & 0xff]++; x >>= 8;
        countsArray[0][x & 0xff]++; x >>= 8;
        countsArray[1][x & 0xff]++; x >>= 8;
        countsArray[2][x & 0xff]++; x >>= 8;
        countsArray[3][x] ++; // last one doesn't need to mask
        rawPtr += 8;
    }

    // finish the last few bytes (just throw them into array 0, doesn't matter)
    while(rawPtr < rawEnd)
        countsArray[0][ *rawPtr++ ] ++;

    // sum the countsarrays together
    {   U32 s;
        for (s=0; s<256; s++) {
            counts[s] = countsArray[0][s] + countsArray[1][s] + countsArray[2][s] + countsArray[3][s];
    }   }
}

static int local_histo_by8(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    U32 count[256];
    (void)dst;(void)dstSize;
    histo_by8(count, (const BYTE*)src, srcSize);
    return count[0];
}


static int local_FSE_count255(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    U32 count[256];
    U32 max = 255;
    (void)dst; (void)dstSize;
    return (int)HIST_count(count, &max, (const BYTE*)src, (U32)srcSize);
}

static int local_FSE_count254(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    U32 count[256];
    U32 max = 254;
    (void)dst; (void)dstSize;
    return (int)HIST_count(count, &max, (const BYTE*)src, (U32)srcSize);
}

static int local_FSE_countFast254(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    U32 count[256];
    U32 max = 254;
    (void)dst; (void)dstSize;
    return (int)HIST_countFast(count, &max, (const unsigned char*)src, srcSize);
}

static int local_FSE_compress(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    return (int)FSE_compress(dst, dstSize, src, srcSize);
}

static int local_HUF_compress(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    return (int)HUF_compress(dst, dstSize, src, srcSize);
}

static U32 fakeTree[256];
static void* const g_treeVoidPtr = fakeTree;
static HUF_CElt* g_tree;

static short  g_normTable[256];
static U32    g_countTable[256];
static U32    g_tableLog;
static U32    g_CTable[2350];
static U32    g_DTable[FSE_DTABLE_SIZE_U32(12)];
static U32    g_max;
static U32    g_bmi2 = 0;
static size_t g_skip;
static size_t g_cSize;
static size_t g_oSize;
#define DTABLE_LOG 12
HUF_CREATE_STATIC_DTABLEX2(g_huff_dtable, DTABLE_LOG);

static void BMK_init(void) {
    g_tree = (HUF_CElt*) g_treeVoidPtr;
    g_bmi2 = ZSTD_cpuid_bmi2(ZSTD_cpuid());
}

static int local_HUF_buildCTable(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)dstSize; (void)src; (void)srcSize;
    return (int)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
}

static int local_HUF_writeCTable(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)src; (void)srcSize;
    return (int)HUF_writeCTable(dst, dstSize, g_tree, g_max, g_tableLog);
}

static int local_HUF_compress4x_usingCTable(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    return (int)HUF_compress4X_usingCTable(dst, dstSize, src, srcSize, g_tree);
}

static unsigned huf4x_wksp[HUF_WORKSPACE_SIZE_U32];
static int local_HUF_compress4x_usingCTable_bmi2(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    HUF_repeat repeat = HUF_repeat_valid;
    return (int)HUF_compress4X_repeat(dst, dstSize, src, srcSize,
                                g_max, g_tableLog,
                                huf4x_wksp, sizeof(huf4x_wksp),
                                g_tree, &repeat, 1, g_bmi2);
}

static int local_FSE_normalizeCount(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)dstSize; (void)src;
    return (int)FSE_normalizeCount(g_normTable, 0, g_countTable, srcSize, g_max);
}

static int local_FSE_writeNCount(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)src; (void)srcSize;
    return (int)FSE_writeNCount(dst, dstSize, g_normTable, g_max, g_tableLog);
}

/*
static int local_FSE_writeHeader_small(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)src; (void)srcSize; (void)dstSize;
    return FSE_writeHeader(dst, 500, g_normTable, 255, g_tableLog);
}
*/

static int local_FSE_buildCTable(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)dstSize; (void)src; (void)srcSize;
    return (int)FSE_buildCTable(g_CTable, g_normTable, g_max, g_tableLog);
}

static int local_FSE_buildCTable_raw(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)dstSize; (void)src; (void)srcSize;
    return (int)FSE_buildCTable_raw(g_CTable, 6);
}

static int local_FSE_compress_usingCTable(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    return (int)FSE_compress_usingCTable(dst, dstSize, src, srcSize, g_CTable);
}

static int local_FSE_compress_usingCTable_tooSmall(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dstSize;
    return (int)FSE_compress_usingCTable(dst, FSE_BLOCKBOUND(srcSize)-1, src, srcSize, g_CTable);
}

static int local_FSE_readNCount(void* src, size_t srcSize, const void* initialBuffer, size_t initialBufferSize)
{
    short norm[256];
    (void)initialBuffer; (void)initialBufferSize;
    return (int)FSE_readNCount(norm, &g_max, &g_tableLog, src, srcSize);
}

static int local_FSE_buildDTable(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)dstSize; (void)src; (void)srcSize;
    return (int)FSE_buildDTable(g_DTable, g_normTable, g_max, g_tableLog);
}

static int local_FSE_buildDTable_raw(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)dstSize; (void)src; (void)srcSize;
    return (int)FSE_buildDTable_raw(g_DTable, 6);
}

static int local_FSE_decompress_usingDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize;
    return (int)FSE_decompress_usingDTable(dst, maxDstSize, (const BYTE*)src + g_skip, g_cSize, g_DTable);
}

static int local_FSE_decompress(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize;
    return (int)FSE_decompress(dst, maxDstSize, src, g_cSize);
}


static int local_HUF_decompress(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress(dst, g_oSize, src, g_cSize);
}

static int local_HUF_decompress4X1(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress4X1(dst, g_oSize, src, g_cSize);
}

static int local_HUF_decompress4X2(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress4X2(dst, g_oSize, src, g_cSize);
}

static int local_HUF_decompress1X1(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress1X1(dst, g_oSize, src, g_cSize);
}

static int local_HUF_decompress1X2(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress1X2(dst, g_oSize, src, g_cSize);
}

static int local_HUF_readStats(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    BYTE weights[HUF_SYMBOLVALUE_MAX+1];
    U32 ranks[HUF_TABLELOG_ABSOLUTEMAX+1];
    U32 nbSymbols=0, tableLog=0;
    (void)dst; (void)maxDstSize; (void)srcSize;
    return (int)HUF_readStats(weights, HUF_SYMBOLVALUE_MAX+1, ranks, &nbSymbols, &tableLog, src, g_cSize);
}

static int local_HUF_readDTableX2(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)maxDstSize; (void)srcSize;
    return (int)HUF_readDTableX2(g_huff_dtable, src, g_cSize);
}

static int local_HUF_readDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    return local_HUF_readDTableX2(dst, maxDstSize, src, srcSize);
}

static int local_HUF_readDTableX1(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)dst; (void)maxDstSize; (void)srcSize;
    return (int)HUF_readDTableX1(g_huff_dtable, src, g_cSize);
}

static int local_HUF_decompress4X1_usingDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress4X1_usingDTable(dst, g_oSize, src, g_cSize, g_huff_dtable);
}

static int local_HUF_decompress4X2_usingDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress4X2_usingDTable(dst, g_oSize, src, g_cSize, g_huff_dtable);
}

static int local_HUF_decompress_usingDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    return local_HUF_decompress4X2_usingDTable(dst, maxDstSize, src, srcSize);
}

static int local_HUF_decompress4X_usingDTable_bmi2(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress4X_usingDTable_bmi2(dst, g_oSize, src, g_cSize, g_huff_dtable, g_bmi2);
}

static int local_HUF_decompress1X1_usingDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress1X1_usingDTable(dst, g_oSize, src, g_cSize, g_huff_dtable);
}

static int local_HUF_decompress1X2_usingDTable(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress1X2_usingDTable(dst, g_oSize, src, g_cSize, g_huff_dtable);
}

static int local_HUF_decompress1X_usingDTable_bmi2(void* dst, size_t maxDstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)maxDstSize;
    return (int)HUF_decompress1X_usingDTable_bmi2(dst, g_oSize, src, g_cSize, g_huff_dtable, g_bmi2);
}



int runBench(const void* buffer, size_t blockSize, U32 algNb, U32 nbBenchs)
{
    size_t benchedSize = blockSize;
    size_t cBuffSize = FSE_compressBound((unsigned)benchedSize);
    void* oBuffer = malloc(blockSize);
    void* cBuffer = malloc(cBuffSize);
    const char* funcName;
    int (*func)(void* dst, size_t dstSize, const void* src, size_t srcSize);

    /* Init */
    memcpy(oBuffer, buffer, blockSize);

    /* Bench selection */
    switch (algNb)
    {
    case 1:
        funcName = "HIST_count(255)";
        func = local_FSE_count255;
        break;

    case 2:
        funcName = "HIST_count(254)";
        func = local_FSE_count254;
        break;

    case 3:
        funcName = "HIST_countFast(254)";
        func = local_FSE_countFast254;
        break;

    case 4:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = FSE_optimalTableLog(g_tableLog, benchedSize, g_max);
            funcName = "FSE_normalizeCount";
            func = local_FSE_normalizeCount;
            break;
        }

    case 5:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = FSE_optimalTableLog(g_tableLog, benchedSize, g_max);
            FSE_normalizeCount(g_normTable, g_tableLog, g_countTable, benchedSize, g_max);
            funcName = "FSE_writeNCount";
            func = local_FSE_writeNCount;
            break;
        }

    case 6:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = FSE_optimalTableLog(g_tableLog, benchedSize, g_max);
            FSE_normalizeCount(g_normTable, g_tableLog, g_countTable, benchedSize, g_max);
            funcName = "FSE_buildCTable";
            func = local_FSE_buildCTable;
            break;
        }

    case 7:
        {
            U32 max=255;
            HIST_count(g_countTable, &max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)FSE_normalizeCount(g_normTable, g_tableLog, g_countTable, benchedSize, max);
            FSE_buildCTable(g_CTable, g_normTable, max, g_tableLog);
            funcName = "FSE_compress_usingCTable";
            func = local_FSE_compress_usingCTable;
            break;
        }

    case 8:
        {
            U32 max=255;
            HIST_count(g_countTable, &max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)FSE_normalizeCount(g_normTable, g_tableLog, g_countTable, benchedSize, max);
            FSE_buildCTable(g_CTable, g_normTable, max, g_tableLog);
            funcName = "FSE_compress_usingCTable_smallDst";
            func = local_FSE_compress_usingCTable_tooSmall;
            break;
        }

    case 9:
        funcName = "FSE_compress";
        func = local_FSE_compress;
        break;

    case 11:
        {
            FSE_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            g_max = 255;
            funcName = "FSE_readNCount";
            func = local_FSE_readNCount;
            break;
        }

    case 12:
        {
            FSE_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            g_max = 255;
            FSE_readNCount(g_normTable, &g_max, &g_tableLog, cBuffer, benchedSize);
            funcName = "FSE_buildDTable";
            func = local_FSE_buildDTable;
            break;
        }

    case 13:
        {
            g_cSize = FSE_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            g_max = 255;
            g_skip = FSE_readNCount(g_normTable, &g_max, &g_tableLog, oBuffer, g_cSize);
            g_cSize -= g_skip;
            FSE_buildDTable (g_DTable, g_normTable, g_max, g_tableLog);
            funcName = "FSE_decompress_usingDTable";
            func = local_FSE_decompress_usingDTable;
            break;
        }

    case 14:
        {
            g_cSize = FSE_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "FSE_decompress";
            func = local_FSE_decompress;
            break;
        }

    case 20:
        funcName = "HUF_compress";
        func = local_HUF_compress;
        break;

    case 21:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            funcName = "HUF_buildCTable";
            func = local_HUF_buildCTable;
            break;
        }

    case 22:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            funcName = "HUF_writeCTable";
            func = local_HUF_writeCTable;
            break;
        }

    case 23:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            funcName = "HUF_compress4x_usingCTable";
            func = local_HUF_compress4x_usingCTable;
            break;
        }

    case 24:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            funcName = "HUF_compress4x_usingCTable_bmi2";
            func = local_HUF_compress4x_usingCTable_bmi2;
            break;
        }

    case 30:
        {
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_decompress";
            func = local_HUF_decompress;
            break;
        }

    case 31:
        {
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_readStats";
            func = local_HUF_readStats;
            break;
        }

    case 32:
        {
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_readDTable";
            func = local_HUF_readDTable;
            break;
        }

    case 33:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            hSize = HUF_readDTableX2(g_huff_dtable, cBuffer, g_cSize);
            g_cSize -= hSize;
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);
            funcName = "HUF_decompress_usingDTable";
            func = local_HUF_decompress_usingDTable;
            break;
        }

    case 40:
        {
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_decompress4X1";
            func = local_HUF_decompress4X1;
            break;
        }


    case 41:
        {
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_readDTableX1";
            func = local_HUF_readDTableX1;
            break;
        }

    case 42:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            hSize = HUF_readDTableX1(g_huff_dtable, cBuffer, g_cSize);
            g_cSize -= hSize;
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);
            funcName = "HUF_decompress4X1_usingDTable";
            func = local_HUF_decompress4X1_usingDTable;
            break;
        }

    case 43:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            hSize = HUF_readDTableX1(g_huff_dtable, cBuffer, g_cSize);
            g_cSize -= hSize;
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);
            funcName = "HUF_decompress4X1_usingDTable_bmi2";
            func = local_HUF_decompress4X_usingDTable_bmi2;
            break;
        }

    case 45:
        {
            g_oSize = benchedSize;
            g_max = 255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            g_cSize = HUF_writeCTable(cBuffer, cBuffSize, g_tree, g_max, g_tableLog);
            g_cSize += HUF_compress1X_usingCTable(((BYTE*)cBuffer) + g_cSize, cBuffSize, oBuffer, benchedSize, g_tree);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_decompress1X1";
            func = local_HUF_decompress1X1;
            break;
        }

    case 46:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_max = 255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            hSize = HUF_writeCTable(cBuffer, cBuffSize, g_tree, g_max, g_tableLog);
            g_cSize = HUF_compress1X_usingCTable(((BYTE*)cBuffer) + hSize, cBuffSize, oBuffer, benchedSize, g_tree);

            hSize = HUF_readDTableX1(g_huff_dtable, cBuffer, g_cSize);
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);

            funcName = "HUF_decompress1X1_usingDTable";
            func = local_HUF_decompress1X1_usingDTable;
            break;
        }

    case 47:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_max = 255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            hSize = HUF_writeCTable(cBuffer, cBuffSize, g_tree, g_max, g_tableLog);
            g_cSize = HUF_compress1X_usingCTable(((BYTE*)cBuffer) + hSize, cBuffSize, oBuffer, benchedSize, g_tree);

            hSize = HUF_readDTableX1(g_huff_dtable, cBuffer, g_cSize);
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);

            funcName = "HUF_decompress1X1_usingDTable_bmi2";
            func = local_HUF_decompress1X_usingDTable_bmi2;
            break;
        }

    case 50:
        {
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_decompress4X2";
            func = local_HUF_decompress4X2;
            break;
        }

    case 51:
        {
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_readDTableX2";
            func = local_HUF_readDTableX2;
            break;
        }

    case 52:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            hSize = HUF_readDTableX2(g_huff_dtable, cBuffer, g_cSize);
            g_cSize -= hSize;
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);
            funcName = "HUF_decompress4X2_usingDTable";
            func = local_HUF_decompress4X2_usingDTable;
            break;
        }

    case 53:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_cSize = HUF_compress(cBuffer, cBuffSize, oBuffer, benchedSize);
            hSize = HUF_readDTableX2(g_huff_dtable, cBuffer, g_cSize);
            g_cSize -= hSize;
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);
            funcName = "HUF_decompress4X2_usingDTable_bmi2";
            func = local_HUF_decompress4X_usingDTable_bmi2;
            break;
        }

    case 55:
        {
            g_oSize = benchedSize;
            g_max = 255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            g_cSize = HUF_writeCTable(cBuffer, cBuffSize, g_tree, g_max, g_tableLog);
            g_cSize += HUF_compress1X_usingCTable(((BYTE*)cBuffer) + g_cSize, cBuffSize, oBuffer, benchedSize, g_tree);
            memcpy(oBuffer, cBuffer, g_cSize);
            funcName = "HUF_decompress1X2";
            func = local_HUF_decompress1X2;
            break;
        }

    case 56:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_max = 255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            hSize = HUF_writeCTable(cBuffer, cBuffSize, g_tree, g_max, g_tableLog);
            g_cSize = HUF_compress1X_usingCTable(((BYTE*)cBuffer) + hSize, cBuffSize, oBuffer, benchedSize, g_tree);

            hSize = HUF_readDTableX2(g_huff_dtable, cBuffer, g_cSize);
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);

            funcName = "HUF_decompress1X2_usingDTable";
            func = local_HUF_decompress1X2_usingDTable;
            break;
        }

    case 57:
        {
            size_t hSize;
            g_oSize = benchedSize;
            g_max = 255;
            HIST_count(g_countTable, &g_max, (const unsigned char*)oBuffer, benchedSize);
            g_tableLog = (U32)HUF_buildCTable(g_tree, g_countTable, g_max, 0);
            hSize = HUF_writeCTable(cBuffer, cBuffSize, g_tree, g_max, g_tableLog);
            g_cSize = HUF_compress1X_usingCTable(((BYTE*)cBuffer) + hSize, cBuffSize, oBuffer, benchedSize, g_tree);

            hSize = HUF_readDTableX2(g_huff_dtable, cBuffer, g_cSize);
            memcpy(oBuffer, ((char*)cBuffer)+hSize, g_cSize);

            funcName = "HUF_decompress1X2_usingDTable_bmi2";
            func = local_HUF_decompress1X_usingDTable_bmi2;
            break;
        }

    case 70:
        {
            funcName = "FSE_buildCTable_raw(6)";
            func = local_FSE_buildCTable_raw;
            break;
        }

    case 80:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, oBuffer, benchedSize);
            g_tableLog = FSE_optimalTableLog(10, benchedSize, g_max);
            FSE_normalizeCount(g_normTable, g_tableLog, g_countTable, benchedSize, g_max);
            funcName = "FSE_buildDTable(10)";
            func = local_FSE_buildDTable;
            break;
        }

    case 81:
        {
            g_max=255;
            HIST_count(g_countTable, &g_max, oBuffer, benchedSize);
            g_tableLog = FSE_optimalTableLog(9, benchedSize, g_max);
            FSE_normalizeCount(g_normTable, g_tableLog, g_countTable, benchedSize, g_max);
            funcName = "FSE_buildDTable(9)";
            func = local_FSE_buildDTable;
            break;
        }

    case 82:
        {
            funcName = "FSE_buildDTable_raw(6)";
            func = local_FSE_buildDTable_raw;
            break;
        }

    /* Specific test functions */
    case 100:
        funcName = "trivialCount";
        func = local_trivialCount;
        break;

    case 101:
        funcName = "count8";
        func = local_count8;
        break;

    case 102:
        funcName = "count8v2";
        func = local_count8v2;
        break;

    case 103:
        funcName = "local_hist_4_32";
        func = local_hist_4_32;
        break;

    case 104:
        funcName = "local_hist_4_32v2";
        func = local_hist_4_32v2;
        break;

    case 105:
        funcName = "local_hist_8_32";
        func = local_hist_8_32;
        break;

    case 106:
        funcName = "local_count2x64v2";
        func = local_count2x64v2;
        break;

    case 107:
        funcName = "local_histo_by8";
        func = local_histo_by8;
        break;

    default:
        goto _end;
    }

    /* Bench */
    DISPLAY("\r%79s\r", "");
    {   int nbLoops = ((100 MB) / (benchedSize+1)) + 1;   /* initial speed evaluation */
        double bestTimeS = 999.;
        U32 benchNb=1;
        DISPLAY("%2u-%-34.34s : \r", benchNb, funcName);
        for (benchNb=1; benchNb <= nbBenchs; benchNb++) {
            size_t resultCode = 0;

            clock_t clockStart = clock();
            while(clock() == clockStart);  /* wait beginning of next tick */
            clockStart = clock();

            {   int loopNb;
                for (loopNb=0; loopNb < nbLoops; loopNb++) {
                    resultCode = func(cBuffer, cBuffSize, oBuffer, benchedSize);
            }   }

            {   clock_t const benchClock = BMK_clockSpan(clockStart);
                double const averageTimeS = (double)benchClock / nbLoops / CLOCKS_PER_SEC;

                if (benchClock > 0) {
                    assert(averageTimeS != 0.0);
                    nbLoops = (U32)(1. / averageTimeS) + 1;   /*aim for 1sec*/
                } else {
                    assert(nbLoops < 20000000);  /* avoid overflow */
                    nbLoops *= 100;
                }

                if (benchClock < BENCHCLOCK_MIN) {
                    assert(benchNb > 0);
                    benchNb--;
                    continue;
                }

                if (averageTimeS < bestTimeS) bestTimeS = averageTimeS;
                DISPLAY("%2u-%-34.34s : %8.1f MB/s  (%6u) \r",
                        benchNb+1, funcName, (double)benchedSize / (1 MB) / bestTimeS, (U32)resultCode);
            }
        }
        DISPLAY("%2u#\n", algNb);
    }

_end:
    free(oBuffer);
    free(cBuffer);

    return 0;
}


static int fullbench(const char* filename, double p, size_t blockSize, U32 algNb, U32 nbLoops)
{
    int result = 0;
    void* buffer = malloc(blockSize);

    if (filename==NULL)
        BMK_genData(buffer, blockSize, p);
    else {
        FILE* f = fopen( filename, "rb" );
        if (f==NULL) { DISPLAY( "Pb opening %s\n", filename); return 11; }
        blockSize = fread(buffer, 1, blockSize, f);
        DISPLAY("Loading %u bytes from %s \n", (U32)blockSize, filename);
        fclose(f);
    }

    if (algNb==0) {
        U32 u;
        for (u=1; u<=99; u++)
            result += runBench(buffer, blockSize, u, nbLoops);
    }
    else
        result = runBench(buffer, blockSize, algNb, nbLoops);

    free(buffer);
    return result;
}


static int benchMultipleFiles(const char** fnTable, int nbFn, int startFn, double p, size_t blockSize, U32 algNb, U32 nbLoops)
{
    if (startFn==0) return fullbench(NULL, p, blockSize, algNb, nbLoops);

    {   int i, result=0;
        for (i=startFn; i<nbFn; i++)
            result += fullbench(fnTable[i], p, blockSize, algNb, nbLoops);
        return result;
    }
}


static int usage(const char* exename)
{
    DISPLAY( "Usage :\n");
    DISPLAY( "      %s [arg] [filename]\n", exename);
    DISPLAY( "Arguments :\n");
    DISPLAY( " -b#    : select function to benchmark (default : 0 ==  all)\n");
    DISPLAY( " -H/-h  : Help (this text + advanced options)\n");
    return 0;
}

static int usage_advanced(const char* exename)
{
    usage(exename);
    DISPLAY( "\nAdvanced options :\n");
    DISPLAY( " -i#    : iteration loops [1-9] (default : %i)\n", NBLOOPS);
    DISPLAY( " -B#    : block size, in bytes (default : %i)\n", DEFAULT_BLOCKSIZE);
    DISPLAY( " -P#    : probability curve, in %% (default : %i%%)\n", DEFAULT_PROBA);
    return 0;
}

static int badusage(const char* exename)
{
    DISPLAY("Wrong parameters\n");
    usage(exename);
    return 1;
}

int main(int argc, const char** argv)
{
    const char* exename = argv[0];
    U32 proba = DEFAULT_PROBA;
    U32 nbLoops = NBLOOPS;
    U32 pause = 0;
    U32 algNb = 0;
    U32 blockSize = DEFAULT_BLOCKSIZE;
    int i;
    int result;
    int fnStart=0;

    BMK_init();

    /* Welcome message */
    DISPLAY(WELCOME_MESSAGE);
    if (argc<1) return badusage(exename);

    for(i=1; i<argc; i++) {
        const char* argument = argv[i];

        if(!argument) continue;   // Protection if argument empty
        if (!strcmp(argument, "--no-prompt")) { no_prompt = 1; continue; }

        // Decode command (note : aggregated commands are allowed)
        if (*argument=='-') {
            argument ++;
            while (*argument!=0) {

                switch(*argument)
                {
                case '-':   // valid separator
                    argument++;
                    break;

                    // Display help on usage
                case 'h' :
                case 'H': return usage_advanced(exename);

                    // Select Algo nb
                case 'b':
                    argument++;
                    algNb=0;
                    while ((*argument >='0') && (*argument <='9')) {
                        algNb*=10; algNb += *argument++ - '0';
                    }
                    break;

                    // Modify Nb loops
                case 'i':
                    argument++;
                    nbLoops=0;
                    while ((*argument >='0') && (*argument <='9')) {
                        nbLoops*=10; nbLoops += *argument++ - '0';
                    }
                    break;

                    // Modify data probability
                case 'P':
                    argument++;
                    proba=0;
                    while ((*argument >='0') && (*argument <='9')) {
                        proba*=10; proba += *argument++ - '0';
                    }
                    break;

                    // Modify block size
                case 'B':
                    argument++;
                    blockSize=0;
                    while ((*argument >='0') && (*argument <='9')) {
                        blockSize*=10; blockSize += *argument++ - '0';
                    }
                    if (argument[0]=='K') { blockSize<<=10; argument++; }  /* allows using KB notation */
                    if (argument[0]=='M') { blockSize<<=20; argument++; }
                    if (argument[0]=='B') argument++;
                    break;

                    // Pause at the end (hidden option)
                case 'p':
                    pause=1;
                    argument++;
                    break;

                    // Unknown command
                default : return badusage(exename);
                }
            }
            continue;
        }

        /* note : non-commands are filenames; all filenames should be at end of line */
        if (fnStart==0) fnStart = i;
    }

    result = benchMultipleFiles(argv, argc, fnStart, (double)proba / 100, blockSize, algNb, nbLoops);

    if (pause) { DISPLAY("press enter...\n"); getchar(); }

    return result;
}
