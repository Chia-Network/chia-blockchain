/*
Fuzzer.c
Automated test program for FSE
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
#define _CRT_SECURE_NO_WARNINGS   /* Visual warning */


/******************************
*  Include
*******************************/
#include <stdlib.h>     /* malloc, abs */
#include <stdio.h>      /* printf */
#include <string.h>     /* memset */
#include <sys/timeb.h>  /* timeb */
#include "mem.h"
#include "hist.h"
#define FSE_STATIC_LINKING_ONLY
#include "fse.h"
#include "xxhash.h"


/***************************************************
*  Constants
***************************************************/
#define KB *(1<<10)
#define MB *(1<<20)
#define BUFFERSIZE ((1 MB) - 1)
#define FUZ_NB_TESTS  (128 KB)
#define PROBATABLESIZE (4 KB)
#define FUZ_UPDATERATE  200
#define PRIME1   2654435761U
#define PRIME2   2246822519U


/***************************************************
*  Macros
***************************************************/
#define DISPLAY(...)         fprintf(stderr, __VA_ARGS__)
#define DISPLAYLEVEL(l, ...) if (displayLevel>=l) { DISPLAY(__VA_ARGS__); }
static unsigned displayLevel = 2;   // 0 : no display  // 1: errors  // 2 : + result + interaction + warnings ;  // 3 : + progression;  // 4 : + information


/***************************************************
*  local functions
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


static void generate (void* buffer, size_t buffSize, double p, U32* seed)
{
    char table[PROBATABLESIZE] = {0};
    int remaining = PROBATABLESIZE;
    int pos = 0;
    int s = 0;
    char* op = (char*) buffer;
    char* oend = op + buffSize;

    /* Build Table */
    while (remaining)
    {
        int n = (int) (remaining * p);
        int end;
        if (!n) n=1;
        end = pos + n;
        while (pos<end) table[pos++]= (char) s;
        s++;
        remaining -= n;
    }

    /* Fill buffer */
    while (op<oend)
    {
        const int r = FUZ_rand (seed) & (PROBATABLESIZE-1);
        *op++ = table[r];
    }
}


static void generateNoise (void* buffer, size_t buffSize, U32* seed)
{
    BYTE* op = (BYTE*)buffer;
    BYTE* const oend = op + buffSize;
    while (op<oend) *op++ = (BYTE)FUZ_rand(seed);
}


static int FUZ_checkCount (short* normalizedCount, int tableLog, int maxSV)
{
    int total = 1<<tableLog;
    int count = 0;
    int i;
    if (tableLog > 20) return -1;
    for (i=0; i<=maxSV; i++)
        count += abs(normalizedCount[i]);
    if (count != total) return -1;
    return 0;
}


#define CHECK(cond, ...) if (cond) { DISPLAY("Error => "); DISPLAY(__VA_ARGS__); \
                         DISPLAY(" (seed %u, test nb %u)  \n", seed, testNb); exit(-1); }

static void FUZ_tests (U32 seed, U32 totalTest, U32 startTestNb)
{
    BYTE* bufferP0    = (BYTE*) malloc (BUFFERSIZE+64);
    BYTE* bufferP1    = (BYTE*) malloc (BUFFERSIZE+64);
    BYTE* bufferP15   = (BYTE*) malloc (BUFFERSIZE+64);
    BYTE* bufferP90   = (BYTE*) malloc (BUFFERSIZE+64);
    BYTE* bufferP100  = (BYTE*) malloc (BUFFERSIZE+64);
    BYTE* bufferDst   = (BYTE*) malloc (BUFFERSIZE+64);
    BYTE* bufferVerif = (BYTE*) malloc (BUFFERSIZE+64);
    size_t bufferDstSize = BUFFERSIZE+64;
    unsigned testNb, maxSV, tableLog;
    const size_t maxTestSizeMask = 0x1FFFF;
    U32 rootSeed = seed;
    U32 time = FUZ_GetMilliStart();

    generateNoise (bufferP0, BUFFERSIZE, &rootSeed);
    generate (bufferP1  , BUFFERSIZE, 0.01, &rootSeed);
    generate (bufferP15 , BUFFERSIZE, 0.15, &rootSeed);
    generate (bufferP90 , BUFFERSIZE, 0.90, &rootSeed);
    memset(bufferP100, (BYTE)FUZ_rand(&rootSeed), BUFFERSIZE);

    if (startTestNb)
    {
        U32 i;
        for (i=0; i<startTestNb; i++)
            FUZ_rand (&rootSeed);
    }

    for (testNb=startTestNb; testNb<totalTest; testNb++)
    {
        BYTE* bufferTest;
        int tag=0;
        U32 roundSeed = rootSeed ^ 0xEDA5B371;
        FUZ_rand(&rootSeed);

        DISPLAYLEVEL (4, "\r test %5u  ", testNb);
        if (FUZ_GetMilliSpan (time) > FUZ_UPDATERATE)
        {
            DISPLAY ("\r test %5u  ", testNb);
            time = FUZ_GetMilliStart();
        }

        /* Compression / Decompression tests */
        {
            /* determine test sample */
            size_t sizeOrig = (FUZ_rand (&roundSeed) & maxTestSizeMask) + 1;
            size_t offset = (FUZ_rand(&roundSeed) % (BUFFERSIZE - 64 - maxTestSizeMask));
            size_t sizeCompressed;
            U32 hashOrig;

            if (FUZ_rand(&roundSeed) & 7) bufferTest = bufferP15 + offset;
            else
            {
                switch(FUZ_rand(&roundSeed) & 3)
                {
                    case 0: bufferTest = bufferP0 + offset; break;
                    case 1: bufferTest = bufferP1 + offset; break;
                    case 2: bufferTest = bufferP90 + offset; break;
                    default : bufferTest = bufferP100 + offset; break;
                }
            }
            DISPLAYLEVEL (4,"%3i ", tag++);;
            hashOrig = XXH32 (bufferTest, sizeOrig, 0);

            /* compress test */
            sizeCompressed = FSE_compress (bufferDst, bufferDstSize, bufferTest, sizeOrig);
            CHECK(FSE_isError(sizeCompressed), "Compression failed !");

            if (sizeCompressed > 1)   /* don't check uncompressed & rle corner cases */
            {
                /* failed compression test*/
                {
                    size_t errorCode;
                    void* tooSmallDBuffer = malloc(sizeCompressed-1);   /* overflows detected with Valgrind */
                    CHECK(tooSmallDBuffer==NULL, "Not enough memory for tooSmallDBuffer test");
                    errorCode = FSE_compress (tooSmallDBuffer, sizeCompressed-1, bufferTest, sizeOrig);
                    CHECK(errorCode!=0, "Compression should have failed : destination buffer too small");
                    free(tooSmallDBuffer);
                }

                /* decompression test */
                {
                    U32 hashEnd;
                    BYTE saved = (bufferVerif[sizeOrig] = 254);
                    size_t result = FSE_decompress (bufferVerif, sizeOrig, bufferDst, sizeCompressed);
                    CHECK(bufferVerif[sizeOrig] != saved, "Output buffer overrun (bufferVerif) : write beyond specified end");
                    CHECK(FSE_isError(result), "Decompression failed");
                    hashEnd = XXH32 (bufferVerif, sizeOrig, 0);
                    CHECK(hashEnd != hashOrig, "Decompressed data corrupted");
                }
            }
        }

        /* Attempt header decoding on bogus data */
        {
            short count[256];
            size_t result;
            DISPLAYLEVEL (4,"\b\b\b\b%3i ", tag++);
            maxSV = 255;
            result = FSE_readNCount (count, &maxSV, &tableLog, bufferTest, FSE_NCOUNTBOUND);
            if (!FSE_isError(result))   /* an error would be normal */
            {
                int checkCount;
                CHECK(result > FSE_NCOUNTBOUND, "FSE_readHeader() reads too far (buffer overflow)");
                CHECK(maxSV > 255, "count table overflow (%u)", maxSV+1);
                checkCount = FUZ_checkCount(count, tableLog, maxSV);
                CHECK(checkCount==-1, "symbol distribution corrupted");
            }
        }

        /* Attempt decompression on bogus data */
        {
            size_t maxDstSize = FUZ_rand (&roundSeed) & maxTestSizeMask;
            size_t sizeCompressed = FUZ_rand (&roundSeed) & maxTestSizeMask;
            BYTE saved = (bufferDst[maxDstSize] = 253);
            size_t result;
            DISPLAYLEVEL (4,"\b\b\b\b%3i ", tag++);;
            result = FSE_decompress (bufferDst, maxDstSize, bufferTest, sizeCompressed);
            CHECK(!FSE_isError(result) && (result > maxDstSize), "Decompression overran output buffer");
            CHECK(bufferDst[maxDstSize] != saved, "FSE_decompress on bogus data : bufferDst write overflow");
        }
    }

    /* exit */
    free (bufferP0);
    free (bufferP1);
    free (bufferP15);
    free (bufferP90);
    free (bufferP100);
    free (bufferDst);
    free (bufferVerif);
}


/*****************************************************************
*  Unitary tests
*****************************************************************/
extern int FSE_countU16(unsigned* count, const unsigned short* source, unsigned sourceSize, unsigned* maxSymbolValuePtr);

#define TBSIZE (16 KB)
static void unitTest(void)
{
    BYTE* testBuff = (BYTE*)malloc(TBSIZE);
    BYTE* cBuff = (BYTE*)malloc(FSE_COMPRESSBOUND(TBSIZE));
    BYTE* verifBuff = (BYTE*)malloc(TBSIZE);
    size_t errorCode;
    U32 seed=0, testNb=0, lseed=0;
    U32 count[256];

    if ((!testBuff) || (!cBuff) || (!verifBuff))
    {
        DISPLAY("Not enough memory, exiting ... \n");
        free(testBuff);
        free(cBuff);
        free(verifBuff);
        return;
    }

    /* HIST_count */
    {   U32 max, i;
        for (i=0; i< TBSIZE; i++) testBuff[i] = (FUZ_rand(&lseed) & 63) + '0';
        max = '0' + 63;
        errorCode = HIST_count(count, &max, testBuff, TBSIZE);
        CHECK(FSE_isError(errorCode), "Error : FSE_count() should have worked");
        max -= 1;
        errorCode = HIST_count(count, &max, testBuff, TBSIZE);
        CHECK(!FSE_isError(errorCode), "Error : FSE_count() should have failed : value > max");
        max = 65000;
        errorCode = HIST_count(count, &max, testBuff, TBSIZE);
        CHECK(FSE_isError(errorCode), "Error : FSE_count() should have worked");
    }

    /* FSE_optimalTableLog */
    {   U32 max, i, tableLog=12;
        size_t testSize = 999;
        for (i=0; i< testSize; i++) testBuff[i] = (BYTE)FUZ_rand(&lseed);
        max = 256;
        HIST_count(count, &max, testBuff, testSize);
        tableLog = FSE_optimalTableLog(tableLog, testSize, max);
        CHECK(tableLog<=8, "Too small tableLog");
    }

    /* FSE_normalizeCount */
    {
        S16 norm[256];
        U32 max = 256;
        HIST_count(count, &max, testBuff, TBSIZE);
        errorCode = FSE_normalizeCount(norm, 10, count, TBSIZE, max);
        CHECK(FSE_isError(errorCode), "Error : FSE_normalizeCount() should have worked");
        errorCode = FSE_normalizeCount(norm, 8, count, TBSIZE, 256);
        CHECK(!FSE_isError(errorCode), "Error : FSE_normalizeCount() should have failed (max >= 1<<tableLog)");
        /* limit corner case : try to make internal rank overflow */
        {
            U32 i;
            U32 total = 0;
            count[0] =  940;
            count[1] =  910;
            count[2] =  470;
            count[3] =  190;
            count[4] =   90;
            for(i=5; i<=255; i++) count[i] = 6;
            for (i=0; i<=255; i++) total += count[i];
            errorCode = FSE_normalizeCount(norm, 10, count, total, 255);
            CHECK(FSE_isError(errorCode), "Error : FSE_normalizeCount() should have worked");
            count[0] =  300;
            count[1] =  300;
            count[2] =  300;
            count[3] =  300;
            count[4] =   50;
            for(i=5; i<=80; i++) count[i] = 4;
            total = 0; for (i=0; i<=80; i++) total += count[i];
            errorCode = FSE_normalizeCount(norm, 10, count, total, 80);
            CHECK(FSE_isError(errorCode), "Error : FSE_normalizeCount() should have worked");
        }
        /* corner case : try to make normalizeM2 divide by 0 */
        {
            U32 i = 0;
            for (i = 0; i < 22; i++) count[i] = 0;
            for (; i < 44; i++) count[i] = 1;
            errorCode = FSE_normalizeCount(norm, 5, count, 22, 43);
            CHECK(FSE_isError(errorCode), "Error : FSE_normalizeCount() should have worked");
        }
    }

    /* FSE_writeNCount, FSE_readNCount */
    {
        #define MAXNCOUNTSIZE 513
        S16 norm[129];
        BYTE header[513];
        U32 max, tableLog, i;
        size_t headerSize;

        for (i=0; i< TBSIZE; i++) testBuff[i] = i % 127;
        max = 128;
        errorCode = HIST_count(count, &max, testBuff, TBSIZE);
        CHECK(FSE_isError(errorCode), "Error : FSE_count() should have worked");
        tableLog = FSE_optimalTableLog(0, TBSIZE, max);
        errorCode = FSE_normalizeCount(norm, tableLog, count, TBSIZE, max);
        CHECK(FSE_isError(errorCode), "Error : FSE_normalizeCount() should have worked");

        headerSize = FSE_NCountWriteBound(max, tableLog);
        CHECK(headerSize > MAXNCOUNTSIZE, "Error : not enough memory for NCount");

        headerSize = FSE_writeNCount(header, headerSize, norm, max, tableLog);
        CHECK(FSE_isError(headerSize), "Error : FSE_writeNCount() should have worked");

        header[headerSize-1] = 0;
        errorCode = FSE_writeNCount(header, headerSize-1, norm, max, tableLog);
        CHECK(!FSE_isError(errorCode), "Error : FSE_writeNCount() should have failed");
        CHECK (header[headerSize-1] != 0, "Error : FSE_writeNCount() buffer overwrite");

        errorCode = FSE_writeNCount(header, headerSize+1, norm, max, tableLog);
        CHECK(FSE_isError(errorCode), "Error : FSE_writeNCount() should have worked");

        {   unsigned maxN = 128;
            size_t const err = FSE_readNCount(norm, &maxN, &tableLog, header, headerSize);
            CHECK(FSE_isError(err), "Error : FSE_readNCount() should have worked : (error %s)", FSE_getErrorName(err));
        }

        max = 64;
        errorCode = FSE_readNCount(norm, &max, &tableLog, header, headerSize);
        CHECK(!FSE_isError(errorCode), "Error : FSE_readNCount() should have failed (max too small)");

        max = 128;
        errorCode = FSE_readNCount(norm, &max, &tableLog, header, headerSize-1);
        CHECK(!FSE_isError(errorCode), "Error : FSE_readNCount() should have failed (size too small)");

        {
            void* smallBuffer = malloc(headerSize-1);   /* outbound read can be caught by valgrind */
            CHECK(smallBuffer==NULL, "Error : Not enough memory (FSE_readNCount unit test)");
            memcpy(smallBuffer, header, headerSize-1);
            max = 129;
            errorCode = FSE_readNCount(norm, &max, &tableLog, smallBuffer, headerSize-1);
            CHECK(!FSE_isError(errorCode), "Error : FSE_readNCount() should have failed (size too small)");
            free(smallBuffer);
        }
    }


    /* FSE_buildCTable_raw & FSE_buildDTable_raw */
    {
        U32 ct[FSE_CTABLE_SIZE_U32(8, 256)];
        U32 dt[FSE_DTABLE_SIZE_U32(8)];
        U64 crcOrig, crcVerif;
        size_t cSize, verifSize;

        U32 i;
        for (i=0; i< TBSIZE; i++) testBuff[i] = (FUZ_rand(&seed) & 63) + '0';
        crcOrig = XXH64(testBuff, TBSIZE, 0);

        errorCode = FSE_buildCTable_raw(ct, 8);
        CHECK(FSE_isError(errorCode), "FSE_buildCTable_raw should have worked");
        errorCode = FSE_buildDTable_raw(dt, 8);
        CHECK(FSE_isError(errorCode), "FSE_buildDTable_raw should have worked");

        cSize = FSE_compress_usingCTable(cBuff, FSE_COMPRESSBOUND(TBSIZE), testBuff, TBSIZE, ct);
        CHECK(FSE_isError(cSize), "FSE_compress_usingCTable should have worked using raw CTable");

        verifSize = FSE_decompress_usingDTable(verifBuff, TBSIZE, cBuff, cSize, dt);
        CHECK(FSE_isError(verifSize), "FSE_decompress_usingDTable should have worked using raw DTable");

        crcVerif = XXH64(verifBuff, verifSize, 0);
        CHECK(crcOrig != crcVerif, "Raw regenerated data is corrupted");
    }

    /* known corner case */
    {
        BYTE sample8[8] = { 0, 0, 0, 2, 0, 0, 0, 0 };
        BYTE* rBuff;
        errorCode = FSE_compress(cBuff, TBSIZE, sample8, 8);
        CHECK(FSE_isError(errorCode), "FSE_compress failed compressing sample8");
        rBuff = (BYTE*)malloc(errorCode);   /* in order to catch read overflow with Valgrind */
        CHECK(rBuff==NULL, "Not enough memory for rBuff");
        memcpy(rBuff, cBuff, errorCode);
        errorCode = FSE_decompress(verifBuff, sizeof(sample8), rBuff, errorCode);
        CHECK(errorCode != sizeof(sample8), "FSE_decompress failed regenerating sample8");
        free(rBuff);
    }

    free(testBuff);
    free(cBuff);
    free(verifBuff);
    DISPLAY("Unit tests completed\n");
}


/*****************************************************************
*  Command line
*****************************************************************/

int badUsage(const char* exename)
{
    (void) exename;
    DISPLAY("wrong parameter\n");
    return 1;
}


int main (int argc, char** argv)
{
    U32 seed, startTestNb=0, pause=0, totalTest = FUZ_NB_TESTS;
    int argNb;

    seed = FUZ_GetMilliStart() % 10000;
    DISPLAYLEVEL (1, "FSE (%2i bits) automated test\n", (int)sizeof(void*)*8);
    for (argNb=1; argNb<argc; argNb++)
    {
        char* argument = argv[argNb];
        if (argument[0]=='-')
        {
            argument++;
            while (argument[0]!=0)
            {
                switch (argument[0])
                {
                /* seed setting */
                case 's':
                    argument++;
                    seed=0;
                    while ((*argument>='0') && (*argument<='9'))
                    {
                        seed *= 10;
                        seed += *argument - '0';
                        argument++;
                    }
                    break;

                /* total tests */
                case 'i':
                    argument++;
                    totalTest=0;
                    while ((*argument>='0') && (*argument<='9'))
                    {
                        totalTest *= 10;
                        totalTest += *argument - '0';
                        argument++;
                    }
                    break;

                /* jump to test nb */
                case 't':
                    argument++;
                    startTestNb=0;
                    while ((*argument>='0') && (*argument<='9'))
                    {
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
                    return badUsage(argv[0]);
                }
            }
        }
    }

    if (startTestNb == 0) unitTest();

    DISPLAY("Fuzzer seed : %u \n", seed);
    FUZ_tests (seed, totalTest, startTestNb);

    DISPLAY ("\rAll %u tests passed               \n", totalTest);
    if (pause)
    {
        int unused;
        DISPLAY("press enter ...\n");
        unused = getchar();
        (void)unused;
    }
    return 0;
}
