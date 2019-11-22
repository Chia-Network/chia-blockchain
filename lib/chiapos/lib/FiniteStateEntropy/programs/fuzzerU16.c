/*
    FuzzerU16.c
    Automated test program for FSE U16
    Copyright (C) Yann Collet 2013-2015

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
    - FSE source repository : https://github.com/Cyan4973/FiniteStateEntropy
    - Public forum : https://groups.google.com/forum/#!forum/lz4c
*/


/******************************
*  Compiler options
******************************/
#define _CRT_SECURE_NO_WARNINGS   /* remove Visual warning */


/******************************
*  Include
******************************/
#include <stdlib.h>    /* malloc, abs */
#include <stdio.h>     /* printf */
#include <string.h>    /* memset */
#include <sys/timeb.h> /* timeb */
#include "fse.h"       /* FSE_isError */
#include "fseU16.h"
#include "xxhash.h"


/****************************************************************
*  Basic Types
****************************************************************/
#if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 199901L   /* C99 */
# include <stdint.h>
typedef  uint8_t BYTE;
typedef uint16_t U16;
typedef  int16_t S16;
typedef uint32_t U32;
typedef  int32_t S32;
typedef uint64_t U64;
#else
typedef unsigned char       BYTE;
typedef unsigned short      U16;
typedef   signed short      S16;
typedef unsigned int        U32;
typedef   signed int        S32;
typedef unsigned long long  U64;
#endif


/*-****************************
*  Constants
******************************/
#define KB *(1<<10)
#define MB *(1<<20)
#define BUFFERSIZE ((1 MB) - 1)
#define FUZ_NB_TESTS  (32 KB)
#define PROBATABLESIZE (4 KB)
#define FUZ_UPDATERATE  200
#define PRIME1   2654435761U
#define PRIME2   2246822519U


/*-*************************************************
*  Macros
***************************************************/
#define DISPLAY(...)         fprintf(stderr, __VA_ARGS__)
#define DISPLAYLEVEL(l, ...) if (displayLevel>=l) { DISPLAY(__VA_ARGS__); }
static unsigned displayLevel = 2;   /* 0: no display;  1: errors;  2: + result + interaction + warnings;  3: + progression;  4: + information */


/*-*************************************************
*  Local functions
***************************************************/
static int FUZ_GetMilliStart(void)
{
    struct timeb tb;
    int nCount;
    ftime ( &tb );
    nCount = (int) (tb.millitm + (tb.time & 0xfffff) * 1000);
    return nCount;
}


static int FUZ_GetMilliSpan ( int nTimeStart )
{
    int nSpan = FUZ_GetMilliStart() - nTimeStart;
    if ( nSpan < 0 )
        nSpan += 0x100000 * 1000;
    return nSpan;
}


static unsigned FUZ_rand (unsigned* src)
{
    *src =  ( (*src) * PRIME1) + PRIME2;
    return (*src) >> 11;
}


static void generateU16 (U16* buffer, size_t buffSize,
                         U16 start, double p, U32 seedSrc)
{
    U16 tableU16[PROBATABLESIZE];
    U32 remaining = PROBATABLESIZE;
    U32 pos = 0;
    U16* op = buffer;
    U16* const oend = op + buffSize;
    U16 val16 = start;
    U16 max16 = FSE_MAX_SYMBOL_VALUE;
    U32 seed = seedSrc;

    /* Build Symbol Table */
    while (remaining) {
        const U32 n = (U32) (remaining * p) + 1;
        const U32 end = pos + n;
        while (pos<end) tableU16[pos++] = val16;
        val16++;
        if (val16 >= max16) val16 = 1;
        remaining -= n;
    }

    /* Fill buffer */
    while (op<oend) {
        const U32 v16 = FUZ_rand(&seed) & (PROBATABLESIZE-1);
        *op++ = tableU16[v16];
    }
}


#define CHECK(cond, ...)                                          \
    if (cond) {                                                   \
        DISPLAY("Error => ");                                     \
        DISPLAY(__VA_ARGS__);                                     \
        DISPLAY(" (seed %u, test nb %u)  \n", startSeed, testNb); \
        exit(-1);                                                 \
}

static void FUZ_tests (const U32 startSeed, U32 totalTest, U32 startTestNb)
{
    size_t const bufferDstSize = BUFFERSIZE*sizeof(U16) + 64;
    U16* const  bufferP8    = (U16*) malloc (bufferDstSize);
    U16* const  bufferP80   = (U16*) malloc (bufferDstSize);
    void* const bufferDst   =        malloc (bufferDstSize);
    U16* const  bufferVerif = (U16*) malloc (bufferDstSize);
    const size_t maxTestSizeMask = 0x1FFFF;
    U32 time = FUZ_GetMilliStart();
    U32 seed = startSeed;
    unsigned testNb;

    if (!bufferP8 || !bufferP80 || !bufferDst || !bufferVerif) {
        DISPLAY("memory allocation error \n");
        exit(1);
    }
    generateU16 (bufferP8,  BUFFERSIZE, 240, 0.08, seed);
    generateU16 (bufferP80, BUFFERSIZE, 257, 0.80, seed+1);

    if (startTestNb) {   /* sync random seed */
        U32 u;
        for (u=0; u<startTestNb; u++)
            FUZ_rand (&seed);
    }

    for (testNb=startTestNb; testNb<totalTest; testNb++) {
        int tag=0;
        U32 roundSeed = seed ^ 0xEDA5B371;
        FUZ_rand(&seed);

        DISPLAYLEVEL (4, "\r test %5u      ", testNb);
        if (FUZ_GetMilliSpan (time) > FUZ_UPDATERATE) {
            DISPLAY ("\r test %5u      ", testNb);
            time = FUZ_GetMilliStart();
        }

        /* Compression / Decompression tests */
        {   size_t const sizeOrig = (FUZ_rand (&roundSeed) & maxTestSizeMask) + 1;
            size_t const offset = (FUZ_rand(&roundSeed) % (BUFFERSIZE - 64 - maxTestSizeMask));
            const U16* const bufferSrc = (FUZ_rand(&roundSeed) & 0x1FF) ? bufferP8 : bufferP80;
            const U16* const bufferTest = bufferSrc + offset;

            U64 const hashOrig = XXH64 (bufferTest, sizeOrig * sizeof(U16), 0);
            size_t const sizeCompressed = FSE_compressU16(
                                                bufferDst, bufferDstSize,
                                                bufferTest, sizeOrig,
                                                FSE_MAX_SYMBOL_VALUE, 12);
            CHECK(FSE_isError(sizeCompressed), "\r test %5u : FSE_compressU16 failed !", testNb);
            DISPLAYLEVEL (4,"\b\b\b\b%3i ", tag++);

            if (sizeCompressed > 1) {  /* don't check uncompressed & rle corner cases */
                U16 const guardValue = 1024 + 250;

                /* basic decompression test : should work */
                DISPLAYLEVEL (4,"\b\b\b\b%3i ", tag++);
                bufferVerif[sizeOrig] = guardValue;
                {   size_t const dSize = FSE_decompressU16 (bufferVerif, sizeOrig, bufferDst, sizeCompressed);
                    CHECK(bufferVerif[sizeOrig] != guardValue,
                        "\r test %5u : FSE_decompressU16 overrun output buffer (write beyond specified end) !",
                        testNb);
                    CHECK(FSE_isError(dSize),
                        "\r test %5u : FSE_decompressU16 failed : %s ! (origSize = %u shorts, cSize = %u bytes)",
                        testNb, FSE_getErrorName(dSize), (U32)sizeOrig, (U32)sizeCompressed);
                    {   U64 const hashEnd = XXH64 (bufferVerif, dSize * sizeof(U16), 0);
                        CHECK(hashEnd != hashOrig,
                            "\r test %5u : Decompressed data corrupted !!",
                            testNb);
                }   }

                /* larger output buffer than necessary : should work */
                DISPLAYLEVEL (4,"\b\b\b\b%3i ", tag++);
                {   size_t const dSize = FSE_decompressU16(
                        bufferVerif, sizeOrig + (FUZ_rand(&roundSeed) & 31) + 1,
                        bufferDst, sizeCompressed);
                    CHECK(FSE_isError(dSize),
                        "\r test %5u : FSE_decompressU16 failed : %s ! (origSize = %u shorts, cSize = %u bytes)",
                        testNb, FSE_getErrorName(dSize), (U32)sizeOrig, (U32)sizeCompressed);
                    {   U64 const hashEnd = XXH64 (bufferVerif, dSize * sizeof(U16), 0);
                        CHECK(hashEnd != hashOrig,
                            "\r test %5u : Decompressed data corrupted !!",
                            testNb);
                }   }

                /* smaller output buffer than required : should fail */
                DISPLAYLEVEL (4,"\b\b\b\b%3i ", tag++);
                {   size_t const missing = (FUZ_rand(&roundSeed) & 31) + 1;
                    size_t const missing_fixed = (missing>=sizeOrig) ? 1 : missing;
                    size_t const dstSize = sizeOrig - missing_fixed;
                    bufferVerif[dstSize] = guardValue;
                    {   size_t const dSize = FSE_decompressU16(
                                                    bufferVerif, dstSize,
                                                    bufferDst, sizeCompressed);
                        CHECK(bufferVerif[dstSize] != guardValue,
                            "\r test %5u : FSE_decompressU16 overrun output buffer (write beyond specified end) !",
                            testNb);
                        CHECK(!FSE_isError(dSize),
                            "\r test %5u : FSE_decompressU16 should have failed ! (origSize = %u shorts, dstSize = %u bytes)",
                            testNb, (U32)sizeOrig, (U32)dstSize);
    }   }   }   }   }

    /* clean */
    free (bufferP8);
    free (bufferP80);
    free (bufferDst);
    free (bufferVerif);
}


/*-***************************************************************
*  Unitary tests
*****************************************************************/

extern size_t FSE_countU16(unsigned* count, unsigned* maxSymbolValuePtr,
               const unsigned short* source, size_t sourceSize);

#define TBSIZE (16 KB)
static void unitTest(void)
{
    U16 testBuffU16[TBSIZE];
    U32 startSeed=0, testNb=0;   /* just to re-use CHECK */

    /* FSE_countU16 */
    U32 table[FSE_MAX_SYMBOL_VALUE+2];
    U32 u;

    for (u=0; u< TBSIZE; u++)
        testBuffU16[u] = u % (FSE_MAX_SYMBOL_VALUE+1);

    { U32 max = FSE_MAX_SYMBOL_VALUE;
      size_t const errC = FSE_countU16(table, &max, testBuffU16, TBSIZE);
      CHECK(FSE_isError(errC), "FSE_countU16() should have worked"); }

    { U32 max = FSE_MAX_SYMBOL_VALUE-1;
      size_t const errC = FSE_countU16(table, &max, testBuffU16, TBSIZE);
      CHECK(!FSE_isError(errC),
            "FSE_countU16() should have failed : max too low"); }

    DISPLAY("Unit tests completed\n");
}


/*****************************************************************
*  Command line
*****************************************************************/
int main (int argc, const char** argv)
{
    U32 startTestNb=0, pause=0, totalTest = FUZ_NB_TESTS;
    int argNb;

    U32 seed = FUZ_GetMilliStart() % 10000;
    DISPLAYLEVEL(1, "FSE U16 (%2i bits) automated test\n",(int)sizeof(void*)*8);
    for (argNb=1; argNb<argc; argNb++) {
        const char* argument = argv[argNb];
        if (argument[0]=='-') {
            argument++;
            while (*argument!=0) {
                switch (*argument)
                {
                /* seed setting */
                case 's':
                    argument++;
                    seed=0;
                    while ((*argument>='0') && (*argument<='9')) {
                        seed *= 10;
                        seed += *argument - '0';
                        argument++;
                    }
                    break;

                /* total nb fuzzer tests */
                case 'i':
                    argument++;
                    totalTest=0;
                    while ((*argument>='0') && (*argument<='9')) {
                        totalTest *= 10;
                        totalTest += *argument - '0';
                        argument++;
                    }
                    break;

                /* jump to test nb */
                case 't':
                    argument++;
                    startTestNb=0;
                    while ((*argument>='0') && (*argument<='9')) {
                        startTestNb *= 10;
                        startTestNb += *argument - '0';
                        argument++;
                    }
                    break;

                /* verbose mode */
                case 'v':
                    argument++;
                    displayLevel=4;
                    break;

                /* pause (hidden) */
                case 'p':
                    argument++;
                    pause=1;
                    break;

                default:
                    ;
                }
    }   }   }   /* for (argNb=1; argNb<argc; argNb++) */

    unitTest();

    DISPLAY("Fuzzer seed : %u \n", seed);
    FUZ_tests (seed, totalTest, startTestNb);

    DISPLAY ("\rAll %u tests passed               \n", totalTest);
    if (pause) {
        DISPLAY("press enter ...\n");
        getchar();
    }
    return 0;
}
