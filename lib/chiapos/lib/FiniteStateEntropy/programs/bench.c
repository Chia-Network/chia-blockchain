/*
    bench.c - Demo module to benchmark open-source compression algorithm
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
    - FSE source repository : https://github.com/Cyan4973/FiniteStateEntropy
    - Public forum : https://groups.google.com/forum/#!forum/lz4c
*/


/*-************************************
*  Tuning parameters
***************************************/
#define NBLOOPS    4
#define TIMELOOP   (CLOCKS_PER_SEC * 2)


/*-************************************
*  Compiler Options
***************************************/
/* Disable some Visual warning messages */
#define _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_DEPRECATE     /* VS2005 */

/* Unix Large Files support (>4GB) */
#define _FILE_OFFSET_BITS 64
#if (defined(__sun__) && (!defined(__LP64__)))   /* Sun Solaris 32-bits requires specific definitions */
#  define _LARGEFILE_SOURCE
#elif ! defined(__LP64__)                        /* No point defining Large file for 64 bit */
#  define _LARGEFILE64_SOURCE
#endif

/* S_ISREG & gettimeofday() are not supported by MSVC */
#if defined(_MSC_VER) || defined(_WIN32)
#  define BMK_LEGACY_TIMER 1
#endif


/*-************************************
*  Includes
***************************************/
#include <stdlib.h>     /* malloc, free */
#include <stdio.h>      /* fprintf, fopen, ftello64 */
#include <string.h>     /* strcat */
#include <sys/types.h>  /* stat64 */
#include <sys/stat.h>   /* stat64 */
#include <time.h>       /* clock_t */
#include <assert.h>     /* assert */

#include "mem.h"
#include "bench.h"
#include "fileio.h"
#include "hist.h"
#include "fse.h"
#include "fseU16.h"
#include "zlibh.h"
#include "huf.h"
#include "xxhash.h"


/*-*************************************
*  Compiler specifics
***************************************/
#if !defined(S_ISREG)
#  define S_ISREG(x) (((x) & S_IFMT) == S_IFREG)
#endif

#if defined(_MSC_VER)   /* Visual */
#  pragma warning(disable : 4127)        /*disable: C4127: conditional expression is constant */
#  include <intrin.h>
#endif

/*-************************************
*  Constants
***************************************/
#define KB *(1U<<10)
#define MB *(1U<<20)
#define GB *(1U<<30)

#define KNUTH               2654435761U
#define MAX_MEM             ((sizeof(void*)==4) ? (2 GB - 64 MB) : (9ULL GB))
#define DEFAULT_CHUNKSIZE   (32 KB)


/*-************************************
*  Display macros
***************************************/
#define DISPLAY(...) fprintf(stderr, __VA_ARGS__)


/*-************************************
*  Benchmark Parameters
***************************************/
static U32 chunkSize = DEFAULT_CHUNKSIZE;
static int nbIterations = NBLOOPS;
static int BMK_byteCompressor = 1;
static int BMK_tableLog = 12;

void BMK_SetByteCompressor(int id) { BMK_byteCompressor = id; }

void BMK_SetBlocksize(U32 bsize) { chunkSize = bsize; DISPLAY("- Blocks %u KB -\n", chunkSize>>10); }

void BMK_SetTableLog(int tableLog) { BMK_tableLog = 5 + tableLog; }

void BMK_SetNbIterations(int nbLoops)
{
    nbIterations = nbLoops;
    DISPLAY("- %i iterations -\n", nbIterations);
}

typedef struct
{
    unsigned id;
    char*  origBuffer;
    size_t origSize;
    char*  compressedBuffer;
    size_t compressedSize;
    char*  destBuffer;
    size_t destSize;
} chunkParameters_t;


/*-*******************************************************
*  local functions
*********************************************************/

static clock_t BMK_clockSpan(clock_t start)
{
    return clock() - start;   /* works even if overflow; max duration ~ 30mn */
}

static size_t BMK_findMaxMem(U64 requiredMem)
{
    size_t step = (64 MB);
    BYTE* testmem=NULL;

    requiredMem = (((requiredMem >> 26) + 1) << 26);
    requiredMem += 2*step;
    if (requiredMem > MAX_MEM) requiredMem = MAX_MEM;

    while (!testmem) {
        requiredMem -= step;
        if (requiredMem <= step) {
            requiredMem = step+64;
            break;
        }
        testmem = (BYTE*) malloc ((size_t)requiredMem);
    }

    free (testmem);
    return (size_t) (requiredMem - step);
}


static U64 BMK_GetFileSize(const char* infilename)
{
    int r;
#if defined(_MSC_VER)
    struct _stat64 statbuf;
    r = _stat64(infilename, &statbuf);
#else
    struct stat statbuf;
    r = stat(infilename, &statbuf);
#endif
    if (r || !S_ISREG(statbuf.st_mode)) return 0;   /* No good... */
    return (U64)statbuf.st_size;
}


/*-*******************************************************
*  Public function
*********************************************************/

void BMK_benchMem285(chunkParameters_t* chunkP, int nbChunks, const char* inFileName, int benchedSize,
                  U64* totalCompressedSize, double* totalCompressionTime, double* totalDecompressionTime,
                  int memLog)
{
    int loopNb, chunkNb;
    size_t cSize=0;
    double fastestC = 100000000., fastestD = 100000000.;
    double ratio=0.;
    U32 crcCheck=0;
    U32 crcOrig;

    /* Init */
    crcOrig = XXH32(chunkP[0].origBuffer, benchedSize,0);

    DISPLAY("\r%79s\r", "");
    for (loopNb = 1; loopNb <= nbIterations; loopNb++) {
        int nbLoops;
        clock_t clockStart, clockDuration;

        /* Compression benchmark */
        DISPLAY("%1i-%-14.14s : %9i ->\r", loopNb, inFileName, benchedSize);
        { int i; for (i=0; i<benchedSize; i++) chunkP[0].compressedBuffer[i]=(char)i; }     /* warmimg up memory */

        nbLoops = 0;
        clockStart = clock();
        while(clock() == clockStart);
        clockStart = clock();
        while(BMK_clockSpan(clockStart) < TIMELOOP) {
            for (chunkNb=0; chunkNb<nbChunks; chunkNb++) {
                const void* rawPtr = chunkP[chunkNb].origBuffer;
                const U16* U16chunkPtr = (const U16*) rawPtr;
                chunkP[chunkNb].compressedSize = FSE_compressU16(chunkP[chunkNb].compressedBuffer, chunkP[chunkNb].origSize, U16chunkPtr, chunkP[chunkNb].origSize/2, 0, memLog);
            }
            nbLoops++;
        }
        clockDuration = BMK_clockSpan(clockStart);

        if ((double)clockDuration < fastestC*nbLoops) fastestC = (double)clockDuration/nbLoops;
        cSize=0; for (chunkNb=0; chunkNb<nbChunks; chunkNb++) cSize += chunkP[chunkNb].compressedSize;
        ratio = (double)cSize/(double)benchedSize*100.;

        DISPLAY("%1i-%-14.14s : %9i -> %9i (%5.2f%%),%7.1f MB/s\r",
                loopNb, inFileName, (int)benchedSize,
                (int)cSize, ratio,
                (double)benchedSize / fastestC / 1000.);

        //DISPLAY("\n"); continue;   // skip decompression
        // Decompression
        //{ size_t i; for (i=0; i<benchedSize; i++) orig_buff[i]=0; }     // zeroing area, for CRC checking

        nbLoops = 0;
        clockStart = clock();
        while(clock() == clockStart);
        clockStart = clock();
        while(BMK_clockSpan(clockStart) < TIMELOOP) {
            for (chunkNb=0; chunkNb<nbChunks; chunkNb++) {
                void* rawPtr = chunkP[chunkNb].destBuffer;
                U16* U16dstPtr = (U16*)rawPtr;
                chunkP[chunkNb].compressedSize = FSE_decompressU16(U16dstPtr, chunkP[chunkNb].origSize/2, chunkP[chunkNb].compressedBuffer, chunkP[chunkNb].compressedSize);
            }
            nbLoops++;
        }
        clockDuration = BMK_clockSpan(clockStart);

        if ((double)clockDuration < fastestC*nbLoops) fastestC = (double)clockDuration/nbLoops;
        DISPLAY("%1i-%-14.14s : %9i -> %9i (%5.2f%%),%7.1f MB/s ,%7.1f MB/s\r",
                loopNb, inFileName, (int)benchedSize,
                (int)cSize, ratio,
                (double)benchedSize / fastestC / 1000.,
                (double)benchedSize / fastestD / 1000.);

        /* CRC Checking */
        crcCheck = XXH32(chunkP[0].destBuffer, benchedSize,0);
        if (crcOrig!=crcCheck) {
            const char* src = chunkP[0].origBuffer;
            const char* fin = chunkP[0].destBuffer;
            const char* const srcStart = src;
            while (*src==*fin) src++, fin++;
            DISPLAY("\n!!! %14s : Invalid Checksum !!! pos %i/%i\n", inFileName, (int)(src-srcStart), benchedSize);
            break;
    }   }

    if (crcOrig==crcCheck) {
        if (ratio<100.)
            DISPLAY("%-16.16s : %9i -> %9i (%5.2f%%),%7.1f MB/s ,%7.1f MB/s\n",
                    inFileName, (int)benchedSize,
                    (int)cSize, ratio,
                    (double)benchedSize / fastestC / 1000.,
                    (double)benchedSize / fastestD / 1000.);
        else
            DISPLAY("%-16.16s : %9i -> %9i (%5.1f%%),%7.1f MB/s ,%7.1f MB/s \n",
                    inFileName, (int)benchedSize,
                    (int)cSize, ratio,
                    (double)benchedSize / fastestC / 1000.,
                    (double)benchedSize / fastestD / 1000.);
    }
    *totalCompressedSize    += cSize;
    *totalCompressionTime   += fastestC;
    *totalDecompressionTime += fastestD;
}


size_t BMK_ZLIBH_compress(void* dst, size_t dstSize, const void* src, size_t srcSize, unsigned nbSymbols, unsigned tableLog)
{ (void)nbSymbols; (void)tableLog; (void)dstSize; return ZLIBH_compress((char*)dst, (const char*)src, (int)srcSize); }

size_t BMK_ZLIBH_decompress(void* dest, size_t originalSize, const void* compressed, size_t cSize)
{ (void)cSize; ZLIBH_decompress((char*)dest, (const char*)compressed); return originalSize; }


/* BMK_benchMem() :
 * chunkP is expected to be correctly filled */
void BMK_benchMem(chunkParameters_t* chunkP, int nbChunks,
                  const char* inFileName, int benchedSize,
                  U64* totalCompressedSize, double* totalCompressionTime, double* totalDecompressionTime,
                  int nbSymbols, int memLog)
{
    int trial, chunkNb;
    size_t cSize = 0;
    double fastestC = 100000000., fastestD = 100000000.;
    double ratio = 0.;
    U32 crcCheck = 0;
    int nbDecodeLoops = ((100 MB) / (benchedSize+1)) + 1;
    U32 const crcOrig = XXH32(chunkP[0].origBuffer, benchedSize,0);
    size_t (*compressor)(void* dst, size_t, const void* src, size_t, unsigned, unsigned);
    size_t (*decompressor)(void* dst, size_t maxDstSize, const void* cSrc, size_t cSrcSize);
    size_t const nameLength = strlen(inFileName);

    /* Init */
    if (nameLength > 17) inFileName += nameLength-17;   /* display last 17 characters */
    if (nbSymbols == 3) {   /* switch to special mode */
        BMK_benchMem285 (chunkP, nbChunks, inFileName, benchedSize, totalCompressedSize, totalCompressionTime, totalDecompressionTime, memLog);
        return;
    }
    switch(BMK_byteCompressor)
    {
    default:
    case 1:
        compressor = FSE_compress2;
        decompressor = FSE_decompress;
        break;
    case 2:
        compressor = HUF_compress2;
        decompressor = HUF_decompress;
        break;
    case 3:
        compressor = BMK_ZLIBH_compress;
        decompressor = BMK_ZLIBH_decompress;
        break;
    }

    DISPLAY("\r%79s\r", "");
    for (trial = 1; trial <= nbIterations; trial++) {
        int nbLoops = 0;
        clock_t clockStart, clockDuration;

        /* Compression */
        DISPLAY("%1i-%-15.15s : %9i ->\r", trial, inFileName, benchedSize);
        { int i; for (i=0; i<benchedSize; i++) chunkP[0].compressedBuffer[i]=(char)i; }    /* warmimg up memory */

        clockStart = clock();
        while(clock() == clockStart);
        clockStart = clock();
        while(BMK_clockSpan(clockStart) < TIMELOOP) {
            for (chunkNb=0; chunkNb<nbChunks; chunkNb++) {
                size_t const cBSize = compressor(
                            chunkP[chunkNb].compressedBuffer, FSE_compressBound(chunkP[chunkNb].origSize),
                            chunkP[chunkNb].origBuffer, chunkP[chunkNb].origSize,
                            nbSymbols, memLog);
                if (FSE_isError(cBSize)) {
                    DISPLAY("!!! Error compressing block %i  !!!!  => %s   \n",
                            chunkNb, FSE_getErrorName(cBSize));
                    return;
                }
                chunkP[chunkNb].compressedSize = cBSize;
            }
            nbLoops++;
        }
        clockDuration = BMK_clockSpan(clockStart);
        clockDuration += !clockDuration;  /* to avoid division by zero */

        if ((double)clockDuration < fastestC * nbLoops * CLOCKS_PER_SEC)
            fastestC = (double) clockDuration / CLOCKS_PER_SEC / nbLoops;
        cSize=0;
        for (chunkNb=0; chunkNb<nbChunks; chunkNb++)
            cSize += chunkP[chunkNb].compressedSize ? chunkP[chunkNb].compressedSize : chunkP[chunkNb].origSize;
        ratio = (double)cSize / (double)benchedSize * 100.;

        DISPLAY("%1i-%-15.15s : %9i -> %9i (%5.2f%%),%7.1f MB/s\r",
                 trial, inFileName, (int)benchedSize,
                 (int)cSize, ratio,
                 (double)benchedSize / (1 MB) / fastestC);

        //if (loopNb == nbIterations) DISPLAY("\n"); continue;   /* skip decompression */
        /* Decompression */
        { int i; for (i=0; i<benchedSize; i++) chunkP[0].destBuffer[i]=0; }     /* zeroing area, for CRC checking */

        clockStart = clock();
        while(clock() == clockStart);
        clockStart = clock();
        for (nbLoops=0; nbLoops < nbDecodeLoops; nbLoops++) {
            for (chunkNb=0; chunkNb<nbChunks; chunkNb++) {
                size_t regenSize;

                switch(chunkP[chunkNb].compressedSize)
                {
                case 0:   /* not compressed block; just memcpy() it */
                    regenSize = chunkP[chunkNb].origSize;
                    memcpy(chunkP[chunkNb].destBuffer, chunkP[chunkNb].origBuffer, regenSize);
                    break;
                case 1:   /* single value byte; just memset() it */
                    regenSize = chunkP[chunkNb].origSize;
                    memset(chunkP[chunkNb].destBuffer, chunkP[chunkNb].origBuffer[0], chunkP[chunkNb].origSize);
                    break;
                default:
                    regenSize = decompressor(chunkP[chunkNb].destBuffer, chunkP[chunkNb].origSize,
                                             chunkP[chunkNb].compressedBuffer, chunkP[chunkNb].compressedSize);
                }

                if (0) {  /* debugging => look for wrong bytes */
                    const char* src = chunkP[chunkNb].origBuffer;
                    const char* regen = chunkP[chunkNb].destBuffer;
                    size_t origSize = chunkP[chunkNb].origSize;
                    size_t n;
                    for (n=0; (n<origSize) && (src[n]==regen[n]); n++);
                    if (n<origSize) {
                        DISPLAY("\n!!! %15s : Invalid block %i !!! pos %u/%u\n",
                                inFileName, chunkNb, (U32)n, (U32)origSize);
                        break;
                }   }

                if (regenSize != chunkP[chunkNb].origSize) {
                    DISPLAY("!! Error decompressing block %i of cSize %u !! => (%s)  \n",
                             chunkNb, (U32)chunkP[chunkNb].compressedSize, FSE_getErrorName(regenSize));
                    return;
            }   }
        }
        clockDuration = BMK_clockSpan(clockStart);

        if (clockDuration > 0) {
            if ((double)clockDuration < fastestD * nbDecodeLoops * CLOCKS_PER_SEC)
                fastestD = (double)clockDuration / CLOCKS_PER_SEC / nbDecodeLoops;
            assert(fastestD > 1./1000000000);   /* avoid overflow */
            nbDecodeLoops = (U32)(1. / fastestD) + 1;   /* aims for ~1sec */
        } else {
            assert(nbDecodeLoops < 20000000);  /* avoid overflow */
            nbDecodeLoops *= 100;
        }
        DISPLAY("%1i-%-15.15s : %9i -> %9i (%5.2f%%),%7.1f MB/s ,%7.1f MB/s\r",
                 trial, inFileName, (int)benchedSize,
                 (int)cSize, ratio,
                 (double)benchedSize / (1 MB) / fastestC,
                 (double)benchedSize / (1 MB) / fastestD);

        /* CRC Checking */
        crcCheck = XXH32(chunkP[0].destBuffer, benchedSize, 0);
        if (crcOrig!=crcCheck) {
            const char* src = chunkP[0].origBuffer;
            const char* fin = chunkP[0].destBuffer;
            const char* const srcStart = src;
            while (*src==*fin)
                src++, fin++;
            DISPLAY("\n!!! %15s : Invalid Checksum !!! pos %i/%i\n",
                    inFileName, (int)(src-srcStart), benchedSize);
            break;
    }   }

    if (crcOrig==crcCheck) {
        if (ratio<100.)
            DISPLAY("%-17.17s : %9i -> %9i (%5.2f%%),%7.1f MB/s ,%7.1f MB/s\n",
                     inFileName, (int)benchedSize,
                     (int)cSize, ratio,
                     (double)benchedSize / (1 MB) / fastestC,
                     (double)benchedSize / (1 MB) / fastestD);
        else
            DISPLAY("%-17.17s : %9i -> %9i (%5.1f%%),%7.1f MB/s ,%7.1f MB/s \n",
                     inFileName, (int)benchedSize,
                     (int)cSize, ratio,
                     (double)benchedSize / (1 MB) / fastestC,
                     (double)benchedSize / (1 MB) / fastestD);
    }
    else DISPLAY("\n");
    *totalCompressedSize    += cSize;
    *totalCompressionTime   += fastestC;
    *totalDecompressionTime += fastestD;
}


int BMK_benchFiles(const char** fileNamesTable, int nbFiles)
{
    int fileIdx=0;
    U64 totalSourceSize = 0;
    U64 totalCompressedSize = 0;
    double totalc = 0.;
    double totald = 0.;

    while (fileIdx<nbFiles) {
        const char* const inFileName = fileNamesTable[fileIdx++];
        FILE* const inFile = fopen( inFileName, "rb" );
        U64    inFileSize;
        size_t benchedSize;
        char* orig_buff;
        int nbChunks;
        int maxCompressedChunkSize;
        size_t readSize;
        char* compressedBuffer; int compressedBuffSize;
        char* destBuffer;
        chunkParameters_t* chunkP;

        /* Check file existence */
        if (inFile==NULL) { DISPLAY( "Pb opening %s\n", inFileName); return 11; }

        /* Memory size evaluation */
        inFileSize = BMK_GetFileSize(inFileName);
        if (inFileSize==0) { DISPLAY( "file is empty\n"); fclose(inFile); return 11; }
        benchedSize = (size_t) BMK_findMaxMem(inFileSize * 3) / 3;
        if ((U64)benchedSize > inFileSize) benchedSize = (size_t)inFileSize;
        if (benchedSize < inFileSize)
            DISPLAY("Not enough memory for '%s' full size; testing %i MB only...\n",
                    inFileName, (int)(benchedSize>>20));

        /* Allocation */
        chunkP = (chunkParameters_t*) malloc(((benchedSize / chunkSize)+1) * sizeof(chunkParameters_t));
        orig_buff = (char*)malloc((size_t )benchedSize);
        nbChunks = (int) (benchedSize / chunkSize) + 1;
        maxCompressedChunkSize = (int)FSE_compressBound(chunkSize);
        compressedBuffSize = nbChunks * maxCompressedChunkSize;
        compressedBuffer = (char*)malloc((size_t )compressedBuffSize);
        destBuffer = (char*)malloc((size_t )benchedSize);

        if (!orig_buff || !compressedBuffer || !destBuffer || !chunkP) {
            DISPLAY("\nError: not enough memory!\n");
            free(orig_buff);
            free(compressedBuffer);
            free(destBuffer);
            free(chunkP);
            fclose(inFile);
            return 12;
        }

        /* Init chunks */
        {   int i;
            size_t remaining = benchedSize;
            char* in = orig_buff;
            char* out = compressedBuffer;
            char* dst = destBuffer;
            for (i=0; i<nbChunks; i++) {
                chunkP[i].id = i;
                chunkP[i].origBuffer = in; in += chunkSize;
                if (remaining > chunkSize) {
                    chunkP[i].origSize = chunkSize;
                    remaining -= chunkSize;
                } else {
                    chunkP[i].origSize = (int)remaining;
                    remaining = 0;
                }
                chunkP[i].compressedBuffer = out; out += maxCompressedChunkSize;
                chunkP[i].compressedSize = 0;
                chunkP[i].destBuffer = dst; dst += chunkSize;
        }   }

        /* Fill input buffer */
        DISPLAY("Loading %s...       \r", inFileName);
        readSize = fread(orig_buff, 1, benchedSize, inFile);
        fclose(inFile);

        if (readSize != benchedSize) {
            DISPLAY("\nError: problem reading file '%s' (%i read, should be %i) !!    \n",
                    inFileName, (int)readSize, (int)benchedSize);
            free(orig_buff);
            free(compressedBuffer);
            free(destBuffer);
            free(chunkP);
            return 13;
        }

        /* Bench */
        BMK_benchMem(chunkP, nbChunks,
                     inFileName, (int)benchedSize,
                     &totalCompressedSize, &totalc, &totald,
                     255, BMK_tableLog);
        totalSourceSize += benchedSize;

        free(orig_buff);
        free(compressedBuffer);
        free(destBuffer);
        free(chunkP);
    }

    if (nbFiles > 1)
        DISPLAY("%-17.17s :%10llu ->%10llu (%5.2f%%), %6.1f MB/s , %6.1f MB/s\n", "  TOTAL",
                (long long unsigned int)totalSourceSize, (long long unsigned int)totalCompressedSize,
                (double)totalCompressedSize/(double)totalSourceSize*100.,
                (double)totalSourceSize/totalc/CLOCKS_PER_SEC,
                (double)totalSourceSize/totald/CLOCKS_PER_SEC);

    return 0;
}



/*-********************************************************************
*  BenchCore
**********************************************************************/

static void BMK_benchCore_Mem(char* dst,
                              char* src, unsigned benchedSize,
                              unsigned nbSymbols, unsigned tableLog, const char* inFileName,
                              U64* totalCompressedSize, double* totalCompressionTime, double* totalDecompressionTime)
{
    int loopNb;
    size_t cSize=0, dSize=0;
    double fastestC = 100000000., fastestD = 100000000.;
    double ratio=0.;
    U64 crcCheck=0;
    U64 crcOrig;
    U32 count[256];
    short norm[256];
    FSE_CTable* ct;
    FSE_DTable* dt;

    /* Init */
    crcOrig = XXH64(src, benchedSize,0);
    HIST_count(count, &nbSymbols, (BYTE*)src, benchedSize);
    tableLog = (U32)FSE_normalizeCount(norm, tableLog, count, benchedSize, nbSymbols);
    ct = FSE_createCTable(tableLog, nbSymbols);
    FSE_buildCTable(ct, norm, nbSymbols, tableLog);
    dt = FSE_createDTable(tableLog);
    FSE_buildDTable(dt, norm, nbSymbols, tableLog);

    DISPLAY("\r%79s\r", "");
    for (loopNb = 1; loopNb <= nbIterations; loopNb++) {
        int nbLoops;
        clock_t clockStart, clockDuration;

        /* Compression */
        DISPLAY("%1i-%-14.14s : %9u ->\r", loopNb, inFileName, benchedSize);
        { unsigned i; for (i=0; i<benchedSize; i++) dst[i]=(char)i; }     /* warmimg up memory */

        nbLoops = 0;
        clockStart = clock();
        while(clock() == clockStart);
        clockStart = clock();
        while(BMK_clockSpan(clockStart) < TIMELOOP) {
            cSize = FSE_compress_usingCTable(dst, FSE_compressBound(benchedSize), src, benchedSize, ct);
            nbLoops++;
        }
        clockDuration = BMK_clockSpan(clockStart);

        if (FSE_isError(cSize)) { DISPLAY("!!! Error compressing file %s !!!!    \n", inFileName); break; }

        if ((double)clockDuration < fastestC*nbLoops) fastestC = (double)clockDuration/nbLoops;
        ratio = (double)cSize/(double)benchedSize*100.;

        DISPLAY("%1i-%-14.14s : %9i -> %9i (%5.2f%%),%7.1f MB/s\r", loopNb, inFileName, (int)benchedSize, (int)cSize, ratio, (double)benchedSize / fastestC / 1000.);

        /* Decompression */
        { unsigned i; for (i=0; i<benchedSize; i++) src[i]=0; }     /* zeroing area, for CRC checking */

        nbLoops = 0;
        clockStart = clock();
        while(clock() == clockStart);
        clockStart = clock();
        while(BMK_clockSpan(clockStart) < TIMELOOP) {
            dSize = FSE_decompress_usingDTable(src, benchedSize, dst, cSize, dt);
            nbLoops++;
        }
        clockDuration = BMK_clockSpan(clockStart);

        if (FSE_isError(dSize)) { DISPLAY("\n!!! Error decompressing file %s !!!!    \n", inFileName); break; }
        if (dSize != benchedSize) { DISPLAY("\n!!! Error decompressing file %s !!!!    \n", inFileName); break; }

        if ((double)clockDuration < fastestD*nbLoops) fastestD = (double)clockDuration/nbLoops;
        DISPLAY("%1i-%-14.14s : %9i -> %9i (%5.2f%%),%7.1f MB/s ,%7.1f MB/s\r", loopNb, inFileName, (int)benchedSize, (int)cSize, ratio, (double)benchedSize / fastestC / 1000., (double)benchedSize / fastestD / 1000.);

        /* CRC Checking */
        crcCheck = XXH64(src, benchedSize, 0);
        if (crcOrig!=crcCheck) { DISPLAY("\n!!! WARNING !!! %14s : Invalid Checksum : %x != %x\n", inFileName, (unsigned)crcOrig, (unsigned)crcCheck); break; }
    }

    if (crcOrig==crcCheck) {
        if (ratio<100.)
            DISPLAY("%-16.16s : %9i -> %9i (%5.2f%%),%7.1f MB/s ,%7.1f MB/s\n", inFileName, (int)benchedSize, (int)cSize, ratio, (double)benchedSize / fastestC / 1000., (double)benchedSize / fastestD / 1000.);
        else
            DISPLAY("%-16.16s : %9i -> %9i (%5.1f%%),%7.1f MB/s ,%7.1f MB/s \n", inFileName, (int)benchedSize, (int)cSize, ratio, (double)benchedSize / fastestC / 1000., (double)benchedSize / fastestD / 1000.);
    }
    *totalCompressedSize    += cSize;
    *totalCompressionTime   += fastestC;
    *totalDecompressionTime += fastestD;

    free(ct);
    free(dt);
}


int BMK_benchCore_Files(const char** fileNamesTable, int nbFiles)
{
    int fileIdx=0;

    U64 totals = 0;
    U64 totalz = 0;
    double totalc = 0.;
    double totald = 0.;

    // Loop for each file
    while (fileIdx<nbFiles) {
        FILE*  inFile;
        const char* inFileName;
        U64    inFileSize;
        size_t benchedSize;
        int nbChunks;
        size_t maxCompressedChunkSize;
        size_t readSize;
        char* orig_buff;
        char* compressedBuffer; size_t compressedBuffSize;

        /* Check file existence */
        inFileName = fileNamesTable[fileIdx++];
        inFile = fopen( inFileName, "rb" );
        if (inFile==NULL) { DISPLAY( "Pb opening %s\n", inFileName); return 11; }

        /* Memory allocation & restrictions */
        inFileSize = BMK_GetFileSize(inFileName);
        if (inFileSize==0) { DISPLAY( "%s is empty\n", inFileName); return 11; }
        benchedSize = 256 MB;
        if ((U64)benchedSize > inFileSize) benchedSize = (size_t)inFileSize;
        else DISPLAY("FSE Core Loop speed evaluation, testing %i KB ...\n", (int)(benchedSize>>10));

        /* Alloc */
        orig_buff = (char*)malloc(benchedSize);
        nbChunks = 1;
        maxCompressedChunkSize = FSE_compressBound((int)benchedSize);
        compressedBuffSize = nbChunks * maxCompressedChunkSize;
        compressedBuffer = (char*)malloc(compressedBuffSize);

        if (!orig_buff || !compressedBuffer) {
            DISPLAY("\nError: not enough memory!\n");
            free(orig_buff);
            free(compressedBuffer);
            fclose(inFile);
            return 12;
        }

        /* Fill input buffer */
        DISPLAY("Loading %s...       \r", inFileName);
        readSize = fread(orig_buff, 1, benchedSize, inFile);
        fclose(inFile);

        if (readSize != benchedSize) {
            DISPLAY("\nError: problem reading file '%s' (%i read, should be %i) !!    \n", inFileName, (int)readSize, (int)benchedSize);
            free(orig_buff);
            free(compressedBuffer);
            return 13;
        }

        /* Bench */
        BMK_benchCore_Mem(compressedBuffer, orig_buff, (int)benchedSize, 255, BMK_tableLog, inFileName, &totalz, &totalc, &totald);
        totals += benchedSize;

        free(orig_buff);
        free(compressedBuffer);
    }

    if (nbFiles > 1)
        DISPLAY("%-16.16s :%10llu ->%10llu (%5.2f%%), %6.1f MB/s , %6.1f MB/s\n", "  TOTAL", (long long unsigned int)totals, (long long unsigned int)totalz, (double)totalz/(double)totals*100., (double)totals/totalc/1000., (double)totals/totald/1000.);

    return 0;
}
