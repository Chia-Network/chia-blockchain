/*
fseDist.c
Universal length FSE coder
Copyright (C) Yann Collet 2012-2014
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
*/

//**************************************
// Compiler Options
//**************************************
#if defined(_MSC_VER)
#  define _CRT_SECURE_NO_WARNINGS
#  define _CRT_SECURE_NO_DEPRECATE     // VS2005
#  pragma warning(disable : 4127)      // disable: C4127: conditional expression is constant
#  include <intrin.h>
#endif


//**************************************
// Includes
//**************************************
#include <stdlib.h>   // malloc
#include <stdio.h>    // fprintf, fopen, ftello64
#include <string.h>   // memcpy
#define FSE_STATIC_LINKING_ONLY
#include "fse.h"


//**************************************
// Compiler specifics
//**************************************
#ifdef __GNUC__
#  define GCC_VERSION (__GNUC__ * 100 + __GNUC_MINOR__)
#endif


//**************************************
// Basic Types
//**************************************
#if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 199901L   // C99
# include <stdint.h>
typedef uint8_t  BYTE;
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


//**************************************
// Constants
//**************************************
#define KB *(1U<<10)
#define MB *(1U<<20)
#define GB *(1U<<30)


//**************************************
// Macros
//**************************************
#define DISPLAY(...) fprintf(stderr, __VA_ARGS__)


//*********************************************************
//  Common internal functions
//*********************************************************
static int FSED_highbit (register U32 val)
{
#   if defined(_MSC_VER)   // Visual
    unsigned long r;
    _BitScanReverse ( &r, val );
    return (int) r;
#   elif defined(__GNUC__) && (GCC_VERSION >= 304)   // GCC Intrinsic
    return 31 - __builtin_clz (val);
#   else   // Software version
    static const int DeBruijnClz[32] = { 0, 9, 1, 10, 13, 21, 2, 29, 11, 14, 16, 18, 22, 25, 3, 30, 8, 12, 20, 28, 15, 17, 24, 7, 19, 27, 23, 6, 26, 5, 4, 31 };
    U32 v = val;
    int r;
    v |= v >> 1;
    v |= v >> 2;
    v |= v >> 4;
    v |= v >> 8;
    v |= v >> 16;
    r = DeBruijnClz[ (U32) (v * 0x07C4ACDDU) >> 27];
    return r;
#   endif
}


//*********************************************************
//  U16 Compression functions
//*********************************************************
int FSED_countU16 (unsigned int* count, const U16* source, int sourceSize)
{
    const U16* ip = source;
    const U16* const iend = source+sourceSize;
    int   i;

    U32   Counting1[16] = {0};
    U32   Counting2[16] = {0};
    U32   Counting3[16] = {0};
    U32   Counting4[16] = {0};

    // Init checks
    if (!sourceSize) return -1;                              // Error : no input

    while (ip < iend-3)
    {
        Counting1[FSED_highbit(*ip++)]++;
        Counting2[FSED_highbit(*ip++)]++;
        Counting3[FSED_highbit(*ip++)]++;
        Counting4[FSED_highbit(*ip++)]++;
    }
    while (ip<iend) Counting1[FSED_highbit(*ip++)]++;

    for (i=0; i<16; i++) count[i] = Counting1[i] + Counting2[i] + Counting3[i] + Counting4[i];

    {
        int max = 15;
        while (!count[max]) max--;
        return max;
    }
}


int FSED_noCompressU16(void* dest, const U16* source, int sourceSize)
{
    BYTE* header = (BYTE*)dest;
    *header=0;
    memcpy(header+1, source, sourceSize*2);
    return sourceSize*2 + 1;
}


int FSED_writeSingleU16(void* dest, U16 distance)
{
    BYTE* header = (BYTE*) dest;
    U16* value = (U16*)(header+1);
    *header=1;
    *value = distance;
    return 3;
}


static void FSED_encodeU16(FSE_CState_t* statePtr, FSE_CStream_t* bitC, U16 value)
{
    BYTE nbBits = (BYTE) FSED_highbit(value);
    FSE_addBits(bitC, (size_t)value, nbBits);
    FSE_encodeByte(bitC, statePtr, nbBits);
}


int FSED_compressU16_usingCTable (void* dest, const U16* source, int sourceSize, const void* CTable)
{
    const U16* const istart = source;
    const U16* ip;
    const U16* const iend = istart + sourceSize;

    BYTE* op = (BYTE*) dest;
    FSE_CStream_t bitC;
    FSE_CState_t state;

    // init
    FSE_initCStream(&bitC, op);
    FSE_initCState(&state, CTable);

    ip=iend-1;

    while (ip>istart)
    {
        FSED_encodeU16(&state, &bitC, *ip--);
        if (sizeof(size_t)>4)   // static test
            FSED_encodeU16(&state, &bitC, *ip--);
        FSE_flushBits(&bitC);
    }
    if (ip==istart) { FSED_encodeU16(&state, &bitC, *ip--); FSE_flushBits(&bitC); }

    FSE_flushCState(&bitC, &state);
    return (int)FSE_closeCStream(&bitC);
}


#define FSED_U16_MAXMEMLOG 10
int FSED_compressU16 (void* dest, const U16* source, unsigned sourceSize, unsigned tableLog)
{
    const U16* const istart = (const U16*) source;
    const U16* ip = istart;

    BYTE* const ostart = (BYTE*) dest;
    BYTE* op = ostart;

    unsigned maxSymbolValue = 15;
    U32 counting[16];
    S16 norm[16];
    U32 CTable[2 + 16 + (1<<FSED_U16_MAXMEMLOG)];


    if (tableLog > FSED_U16_MAXMEMLOG) return -1;
    // early out
    if (sourceSize <= 1) return FSED_noCompressU16 (ostart, istart, sourceSize);

    // Scan for stats
    maxSymbolValue = FSED_countU16 (counting, ip, sourceSize);

    // Normalize
    tableLog = FSE_optimalTableLog(tableLog, sourceSize, maxSymbolValue);
    tableLog = (U32)FSE_normalizeCount (norm, tableLog, counting, sourceSize, maxSymbolValue);
    if (tableLog==0) return FSED_writeSingleU16 (ostart, *source);   // only one distance in the set

    op += FSE_writeHeader (op, FSE_headerBound(maxSymbolValue, tableLog), norm, maxSymbolValue, tableLog);

    // Compress
    FSE_buildCTable (&CTable, norm, maxSymbolValue, tableLog);
    op += FSED_compressU16_usingCTable (op, ip, sourceSize, &CTable);

    // check compressibility
    if ( (size_t)(op-ostart) >= (size_t)(sourceSize*2-1) )
        return FSED_noCompressU16 (ostart, istart, sourceSize);

    return (int) (op-ostart);
}


//*********************************************************
//  U16 Decompression functions
//*********************************************************
int FSED_decompressRawU16 (U16* out, int osize, const BYTE* in)
{
    memcpy (out, in+1, osize*2);
    return osize*2+1;
}

int FSED_decompressSingleU16 (U16* out, int osize, U16 value)
{
    int i;
    for (i=0; i<osize; i++) *out++ = value;
    return 3;
}


int FSED_decompressU16_usingDTable (U16* dst, size_t maxDstSize,
                            const void* cSrc, size_t cSrcSize,
                            const void* DTable)
{
    U16* const ostart = dst;
    U16* op = ostart;
    FSE_DStream_t DStream;
    FSE_DState_t  DState;

    // Init
    (void)maxDstSize;
    FSE_initDStream(&DStream, cSrc, cSrcSize);
    FSE_initDState(&DState, &DStream, DTable);

    // Hot loop
    while (FSE_reloadDStream(&DStream))
    {
        int nbBits = FSE_decodeSymbol(&DState, &DStream);
        unsigned short value = (U16)FSE_readBits(&DStream, nbBits);
        value += 1<<nbBits;
        *op++ = value;
    }

    return (int)(op-ostart);
}


int FSED_decompressU16 (U16* dst, size_t maxDstSize,
                       const void* cSrc, size_t cSrcSize)
{
    const BYTE* const istart = (const BYTE*) cSrc;
    const BYTE* ip = istart;
    short norm[16];
    U32  DTable[FSE_DTABLE_SIZE_U32(FSED_U16_MAXMEMLOG)];
    unsigned  nbSymbols;
    unsigned  tableLog;
    int errorCode;
    size_t headerSize;

    // normal FSE decoding mode
    headerSize = FSE_readHeader (norm, &nbSymbols, &tableLog, istart, cSrcSize);
    ip += headerSize;
    cSrcSize -= headerSize;
    FSE_buildDTable (DTable, norm, nbSymbols, tableLog);
    errorCode = FSED_decompressU16_usingDTable (dst, maxDstSize, ip, cSrcSize, DTable);

    return (int) (errorCode);
}


//*********************************************************
//  U16Log2 Compression functions
//*********************************************************
// note : values MUST be >= (1<<LN)
#define LN 3
int FSED_Log2(U16 value)
{
    int hb = FSED_highbit(value>>LN);
    return (hb * (1<<LN)) + (value>>hb) - (1<<LN);
}


int FSED_countU16Log2 (unsigned int* count, const U16* source, int sourceSize)
{
    const U16* ip = source;
    const U16* const iend = source+sourceSize;
    int   i;

    U32   Counting1[64] = {0};
    U32   Counting2[64] = {0};
    U32   Counting3[64] = {0};
    U32   Counting4[64] = {0};

    // Init checks
    if (!sourceSize) return -1;                              // Error : no input

    while (ip < iend-3)
    {
        Counting1[FSED_Log2(*ip++)]++;
        Counting2[FSED_Log2(*ip++)]++;
        Counting3[FSED_Log2(*ip++)]++;
        Counting4[FSED_Log2(*ip++)]++;
    }
    while (ip<iend) Counting1[FSED_Log2(*ip++)]++;

    for (i=0; i<64; i++) count[i] = Counting1[i] + Counting2[i] + Counting3[i] + Counting4[i];

    {
        int max = 64;
        while (!count[max-1]) max--;
        return max;
    }
}


static void FSED_encodeU16Log2(FSE_CState_t* statePtr, FSE_CStream_t* bitC, U16 value)
{
    int nbBits = FSED_highbit(value>>LN);
    BYTE symbol = (BYTE)FSED_Log2(value);
    FSE_addBits(bitC, nbBits, (size_t)value);
    FSE_encodeByte(bitC, statePtr, symbol);
}


int FSED_compressU16Log2_usingCTable (void* dest, const U16* source, int sourceSize, const void* CTable)
{
    const U16* const istart = source;
    const U16* ip;
    const U16* const iend = istart + sourceSize;

    BYTE* op = (BYTE*) dest;

    const int memLog = ( (U16*) CTable) [0];

    FSE_CState_t state;
    FSE_CStream_t bitC;

    // init
    FSE_initCStream(&bitC, op);
    FSE_initCState(&state, CTable);
    ip=iend-1;

    while (ip>istart)
    {
        FSED_encodeU16Log2(&state, &bitC, *ip--);
        if (sizeof(size_t)>4)   // static test
            FSED_encodeU16Log2(&state, &bitC, *ip--);
        FSE_flushBits(&bitC);
    }
    if (ip==istart) { FSED_encodeU16Log2(&state, &bitC, *ip--); FSE_flushBits(&bitC); }

    // Finalize block
    FSE_addBits(&bitC, state.value, memLog);
    FSE_flushBits(&bitC);

    return (int)FSE_closeCStream(&bitC);
}


#define FSED_U16LOG2_MAXMEMLOG 11
int FSED_compressU16Log2 (void* dest, const U16* source, unsigned sourceSize, unsigned memLog)
{
    const U16* const istart = (const U16*) source;
    const U16* ip = istart;

    BYTE* const ostart = (BYTE*) dest;
    BYTE* op = ostart;

    int nbSymbols = 16;
    U32 counting[64];
    short norm[64];
    U32 CTable[2 + 16 + (1<<FSED_U16LOG2_MAXMEMLOG)];


    if (memLog > FSED_U16LOG2_MAXMEMLOG) return -1;
    // early out
    if (sourceSize <= 1) return FSED_noCompressU16 (ostart, istart, sourceSize);

    // Scan for stats
    nbSymbols = FSED_countU16Log2 (counting, ip, sourceSize);

    // Normalize
    memLog = (U32)FSE_normalizeCount (norm, memLog, counting, sourceSize, nbSymbols);
    if (memLog==0) return FSED_writeSingleU16 (ostart, *source);   // only one distance in the set

    op += FSE_writeHeader (op, FSE_headerBound(nbSymbols, memLog), norm, nbSymbols, memLog);

    // Compress
    FSE_buildCTable (&CTable, norm, nbSymbols, memLog);
    op += FSED_compressU16Log2_usingCTable (op, ip, sourceSize, &CTable);

    // check compressibility
    if ( (size_t)(op-ostart) >= (size_t)(sourceSize*2-1) )
        return FSED_noCompressU16 (ostart, istart, sourceSize);

    return (int) (op-ostart);
}


//*********************************************************
//  U32 Compression functions
//*********************************************************
#define FSED_MAXBITS_U32 26
int FSED_countU32 (unsigned int* count, const U32* source, int sourceSize)
{
    const U32* ip = source;
    const U32* const iend = source+sourceSize;
    int   i;

    U32   Counting1[FSED_MAXBITS_U32] = {0};
    U32   Counting2[FSED_MAXBITS_U32] = {0};
    U32   Counting3[FSED_MAXBITS_U32] = {0};
    U32   Counting4[FSED_MAXBITS_U32] = {0};

    // Init checks
    if (!sourceSize) return -1;                              // Error : no input

    while (ip < iend-3)
    {
        Counting1[FSED_highbit(*ip++)]++;
        Counting2[FSED_highbit(*ip++)]++;
        Counting3[FSED_highbit(*ip++)]++;
        Counting4[FSED_highbit(*ip++)]++;
    }
    while (ip<iend) Counting1[FSED_highbit(*ip++)]++;

    for (i=0; i<FSED_MAXBITS_U32; i++) count[i] = Counting1[i] + Counting2[i] + Counting3[i] + Counting4[i];

    {
        int max = FSED_MAXBITS_U32-1;
        while (!count[max]) max--;
        return max;
    }
}


int FSED_noCompressU32(void* dest, const U32* source, int sourceSize)
{
    BYTE* header = (BYTE*)dest;
    *header=0;
    memcpy(header+1, source, sourceSize*4);
    return (sourceSize*4) + 1;
}


int FSED_writeSingleU32(void* dest, const U32* source, unsigned sourceSize)
{
    BYTE* header = (BYTE*) dest;
    U32 val = *source;
    const unsigned nb_bits = FSED_highbit(val);
    size_t container = 1 + (nb_bits<<2);   // header 1 (2 bits) : singleU32
    unsigned pos=7;
    const unsigned mask = (1<<(nb_bits))-1;
    const unsigned max = (sizeof(size_t)*8) - nb_bits;
    unsigned i=0;

    while (i<sourceSize)
    {
        val = *source++;
        container += (size_t)(val & mask) << pos;
        pos += nb_bits;
        if (pos >= max)   // Note : avoid filling container entirely, because container >> 64 == container (!= 0)
        {
            const unsigned nb_bytes = pos >> 3;
            *(size_t*)header = container;
            container >>= (nb_bytes*8);
            pos -= (nb_bytes*8);
            header += nb_bytes;
        }
        i++;
    }

    {
        const unsigned nb_bytes = (pos+7) >> 3;
        *(size_t*)header = container;
        header += nb_bytes;
    }

    return (int)(header-(BYTE*)dest);
}


void FSED_encodeU32(FSE_CStream_t* bitC, FSE_CState_t* statePtr, U32 value)
{
    //BYTE nbBits = (BYTE) FSED_highbit((value>>3)+1);
    //FSE_addBits(bitC, (size_t)value, nbBits+3);
    BYTE nbBits = (BYTE) FSED_highbit(value);
    FSE_addBits(bitC, (size_t)value, nbBits);
    if (sizeof(size_t)==4)   // static test
        FSE_flushBits(bitC);
    FSE_encodeByte(bitC, statePtr, nbBits);
}


int FSED_compressU32_usingCTable (void* dest, const U32* source, int sourceSize, const void* CTable)
{
    const U32* const istart = source;
    const U32* ip;
    const U32* const iend = istart + sourceSize;

    BYTE* op = (BYTE*) dest;
    int tableLog = *(U16*)CTable;
    FSE_CStream_t bitC;
    FSE_CState_t state;

    // init
    FSE_initCStream(&bitC, op);
    FSE_initCState(&state, CTable);
    ip=iend;

    while (ip>istart)
    {
        FSED_encodeU32(&bitC, &state, *--ip);
        FSE_flushBits(&bitC);
    }

    FSE_addBits(&bitC, state.value, tableLog); FSE_flushBits(&bitC);
    return (int)FSE_closeCStream(&bitC);
}


#define FSED_U32_MAXTABLELOG 11
size_t FSED_compressU32 (void* dst, size_t maxDstSize, const U32* src, size_t srcSize, unsigned tableLog)
{
    const U32* const istart = (const U32*) src;
    const U32* ip = istart;

    BYTE* const ostart = (BYTE*) dst;
    BYTE* op = ostart;

    int nbSymbols = FSED_MAXBITS_U32;
    U32 counting[FSED_MAXBITS_U32];
    short norm[FSED_MAXBITS_U32];
    U32 CTable[2 + FSED_MAXBITS_U32 + (1<<FSED_U32_MAXTABLELOG)];


    /* safety checks */
    (void)maxDstSize;
    if (tableLog > FSED_U32_MAXTABLELOG) return (size_t)-FSE_ERROR_GENERIC;
    /* early out */
    if (srcSize <= 1) return FSED_noCompressU32 (ostart, src, srcSize);

    /* Scan for stats */
    nbSymbols = FSED_countU32 (counting, ip, srcSize);

    /* Normalize */
    tableLog = (U32)FSE_normalizeCount (norm, tableLog, counting, srcSize, nbSymbols);
    if (tableLog==0) return FSED_writeSingleU32 (ostart, src, srcSize);

    op += FSE_writeHeader (op, FSE_headerBound(nbSymbols, tableLog), norm, nbSymbols, tableLog);

    /* Compress */
    FSE_buildCTable (&CTable, norm, nbSymbols, tableLog);
    op += FSED_compressU32_usingCTable (op, ip, srcSize, &CTable);

    /* check compressibility */
    if ( (size_t)(op-ostart) >= (size_t)(srcSize*4-1) )
        return FSED_noCompressU32 (ostart, istart, srcSize);

    return (int) (op-ostart);
}


/*********************************************************
    U32 Decompression functions
*********************************************************/
int FSED_decompressRawU32 (U32* out, int osize, const BYTE* in)
{
    memcpy (out, in+1, osize*4);
    return osize*4+1;
}

int FSED_decompressSingleU32 (U32* out, unsigned osize, const BYTE* istart)
{
    const BYTE* header = istart;
    size_t container = (*(size_t*)header) >> 2;   // assumption : *istart&3==1;
    const unsigned nb_bits = container & 31;
    unsigned pos=7;
    const unsigned prefix = 1<<nb_bits;
    const unsigned mask = prefix-1;
    const unsigned max = (sizeof(size_t)*8) - nb_bits;
    unsigned i=0;

    container >>= 5;

    while (i<osize)
    {
        U32 val = container & mask;
        pos += nb_bits;
        val += prefix;
        container >>= nb_bits;
        *out++ = val;
        if (pos > max)
        {
            const unsigned nb_bytes = pos >> 3;
            header += nb_bytes;
            pos &= 7;
            container = *(size_t*)header;
            container >>= pos;
        }
        i++;
    }

    {
        const unsigned nb_bytes = (pos+7) >> 3;
        header += nb_bytes;
    }

    return (int)(header-istart);
}



int FSED_decompressU32_usingDTable (U32* dst, size_t maxDstSize,
                              const void* cSrc, size_t cSrcSize,
                              const void* DTable)
{
    U32* const ostart = dst;
    U32* op = ostart;
    FSE_DStream_t DStream;
    FSE_DState_t  DState;

    /* Init */
    (void)maxDstSize;
    FSE_initDStream(&DStream, cSrc, cSrcSize);
    FSE_initDState(&DState, &DStream, DTable);

    // Hot loop
    while (FSE_reloadDStream(&DStream)<2)
    {
        int nbBits = FSE_decodeSymbol(&DState, &DStream);
        bitD_t value;
        FSE_reloadDStream(&DStream);
        value = FSE_readBits(&DStream, nbBits);
        value += (bitD_t)1<<nbBits;
        *op++ = (U32)value;
    }

    return (int)(op-ostart);
}


int FSED_decompressU32 (U32* dst, size_t maxDstSize,
                       const void* cSrc, size_t cSrcSize)
{
    const BYTE* const istart = (const BYTE*) cSrc;
    const BYTE* ip = istart;
    short norm[FSED_MAXBITS_U32];
    U32  DTable[1<<FSED_U32_MAXTABLELOG];
    unsigned  nbSymbols;
    unsigned  tableLog;
    size_t headerSize;

    headerSize = FSE_readHeader (norm, &nbSymbols, &tableLog, istart, cSrcSize);
    ip += headerSize;
    cSrcSize -= headerSize;
    FSE_buildDTable (DTable, norm, nbSymbols, tableLog);
    return FSED_decompressU32_usingDTable (dst, maxDstSize, ip, cSrcSize, DTable);
}
