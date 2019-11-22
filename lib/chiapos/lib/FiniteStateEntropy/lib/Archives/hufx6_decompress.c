/* ******************************************************************
   Huffman decoder, part of New Generation Entropy library
   Copyright (C) 2013-2016, Yann Collet.

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
   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

    You can contact the author at :
    - FSE+HUF source repository : https://github.com/Cyan4973/FiniteStateEntropy
    - Public forum : https://groups.google.com/forum/#!forum/lz4c
****************************************************************** */

/* **************************************************************
*  Compiler specifics
****************************************************************/
#if defined (__cplusplus) || (defined (__STDC_VERSION__) && (__STDC_VERSION__ >= 199901L) /* C99 */)
/* inline is defined */
#elif defined(_MSC_VER)
#  define inline __inline
#else
#  define inline /* disable inline */
#endif


#ifdef _MSC_VER    /* Visual Studio */
#  define FORCE_INLINE static __forceinline
#  pragma warning(disable : 4127)        /* disable: C4127: conditional expression is constant */
#else
#  ifdef __GNUC__
#    define FORCE_INLINE static inline __attribute__((always_inline))
#  else
#    define FORCE_INLINE static inline
#  endif
#endif


/* **************************************************************
*  Includes
****************************************************************/
#include <string.h>     /* memcpy, memset */
#include <stdio.h>      /* printf (debug) */
#include "bitstream.h"
#include "fse.h"        /* header compression */
#include "hufx6.h"


/* **************************************************************
*  Error Management
****************************************************************/
#define HUF_STATIC_ASSERT(c) { enum { HUF_static_assert = 1/(int)(!!(c)) }; }   /* use only *after* variable declarations */


/* ********************************/
/* quad-symbol decoding           */
/* ********************************/
typedef struct { BYTE nbBits; BYTE nbBytes; } HUF_DDescX6;
typedef union { BYTE byte[4]; U32 sequence; } HUF_DSeqX6;

/* recursive, up to level 3; may benefit from <template>-like strategy to nest each level inline */
static void HUF_fillDTableX6LevelN(HUF_DDescX6* DDescription, HUF_DSeqX6* DSequence, int sizeLog,
                           const rankVal_t rankValOrigin, const U32 consumed, const int minWeight, const U32 maxWeight,
                           const sortedSymbol_t* sortedSymbols, const U32 sortedListSize, const U32* rankStart,
                           const U32 nbBitsBaseline, HUF_DSeqX6 baseSeq, HUF_DDescX6 DDesc)
{
    const int scaleLog = nbBitsBaseline - sizeLog;   /* note : targetLog >= (nbBitsBaseline-1), hence scaleLog <= 1 */
    const int minBits  = nbBitsBaseline - maxWeight;
    const U32 level = DDesc.nbBytes;
    U32 rankVal[HUF_TABLELOG_ABSOLUTEMAX + 1];
    U32 symbolStartPos, s;

    /* local rankVal, will be modified */
    memcpy(rankVal, rankValOrigin[consumed], sizeof(rankVal));

    /* fill skipped values */
    if (minWeight>1) {
        U32 i;
        const U32 skipSize = rankVal[minWeight];
        for (i = 0; i < skipSize; i++) {
            DSequence[i] = baseSeq;
            DDescription[i] = DDesc;
    }   }

    /* fill DTable */
    DDesc.nbBytes++;
    symbolStartPos = rankStart[minWeight];
    for (s=symbolStartPos; s<sortedListSize; s++) {
        const BYTE symbol = sortedSymbols[s].symbol;
        const U32  weight = sortedSymbols[s].weight;   /* >= 1 (sorted) */
        const int  nbBits = nbBitsBaseline - weight;   /* >= 1 (by construction) */
        const int  totalBits = consumed+nbBits;
        const U32  start  = rankVal[weight];
        const U32  length = 1 << (sizeLog-nbBits);
        baseSeq.byte[level] = symbol;
        DDesc.nbBits = (BYTE)totalBits;

        if ((level<3) && (sizeLog-totalBits >= minBits)) {  /* enough room for another symbol */
            int nextMinWeight = totalBits + scaleLog;
            if (nextMinWeight < 1) nextMinWeight = 1;
            HUF_fillDTableX6LevelN(DDescription+start, DSequence+start, sizeLog-nbBits,
                           rankValOrigin, totalBits, nextMinWeight, maxWeight,
                           sortedSymbols, sortedListSize, rankStart,
                           nbBitsBaseline, baseSeq, DDesc);   /* recursive (max : level 3) */
        } else {
            U32 i;
            const U32 end = start + length;
            for (i = start; i < end; i++) {
                DDescription[i] = DDesc;
                DSequence[i] = baseSeq;
        }   }
        rankVal[weight] += length;
    }
}


/* note : same preparation as X4 */
size_t HUF_readDTableX6 (U32* DTable, const void* src, size_t srcSize)
{
    BYTE weightList[HUF_SYMBOLVALUE_MAX + 1];
    sortedSymbol_t sortedSymbol[HUF_SYMBOLVALUE_MAX + 1];
    U32 rankStats[HUF_TABLELOG_ABSOLUTEMAX + 1] = { 0 };
    U32 rankStart0[HUF_TABLELOG_ABSOLUTEMAX + 2] = { 0 };
    U32* const rankStart = rankStart0+1;
    U32 tableLog, maxW, sizeOfSort, nbSymbols;
    rankVal_t rankVal;
    const U32 memLog = DTable[0];
    size_t iSize;

    if (memLog > HUF_TABLELOG_ABSOLUTEMAX) return ERROR(tableLog_tooLarge);
    //memset(weightList, 0, sizeof(weightList));   /* is not necessary, even though some analyzer complain ... */

    iSize = HUF_readStats(weightList, HUF_SYMBOLVALUE_MAX + 1, rankStats, &nbSymbols, &tableLog, src, srcSize);
    if (HUF_isError(iSize)) return iSize;

    /* check result */
    if (tableLog > memLog) return ERROR(tableLog_tooLarge);   /* DTable is too small */

    /* find maxWeight */
    for (maxW = tableLog; maxW && rankStats[maxW]==0; maxW--) {}  /* necessarily finds a solution before 0 */

    /* Get start index of each weight */
    {   U32 w, nextRankStart = 0;
        for (w=1; w<maxW+1; w++) {
            U32 current = nextRankStart;
            nextRankStart += rankStats[w];
            rankStart[w] = current;
        }
        rankStart[0] = nextRankStart;   /* put all 0w symbols at the end of sorted list*/
        sizeOfSort = nextRankStart;
    }

    /* sort symbols by weight */
    {   U32 s;
        for (s=0; s<nbSymbols; s++) {
            U32 w = weightList[s];
            U32 r = rankStart[w]++;
            sortedSymbol[r].symbol = (BYTE)s;
            sortedSymbol[r].weight = (BYTE)w;
        }
        rankStart[0] = 0;   /* forget 0w symbols; this is beginning of weight(1) */
    }

    /* Build rankVal */
    {   const U32 minBits = tableLog+1 - maxW;
        U32 nextRankVal = 0;
        U32 w, consumed;
        const int rescale = (memLog-tableLog) - 1;   /* tableLog <= memLog */
        U32* rankVal0 = rankVal[0];
        for (w=1; w<maxW+1; w++) {
            U32 current = nextRankVal;
            nextRankVal += rankStats[w] << (w+rescale);
            rankVal0[w] = current;
        }
        for (consumed = minBits; consumed <= memLog - minBits; consumed++) {
            U32* rankValPtr = rankVal[consumed];
            for (w = 1; w < maxW+1; w++) {
                rankValPtr[w] = rankVal0[w] >> consumed;
    }   }   }

    /* fill tables */
    {   void* ddPtr = DTable+1;
        HUF_DDescX6* DDescription = (HUF_DDescX6*)ddPtr;
        void* dsPtr = DTable + 1 + ((size_t)1<<(memLog-1));
        HUF_DSeqX6* DSequence = (HUF_DSeqX6*)dsPtr;
        HUF_DSeqX6 DSeq;
        HUF_DDescX6 DDesc;
        DSeq.sequence = 0;
        DDesc.nbBits = 0;
        DDesc.nbBytes = 0;
        HUF_fillDTableX6LevelN(DDescription, DSequence, memLog,
                       (const U32 (*)[HUF_TABLELOG_ABSOLUTEMAX + 1])rankVal, 0, 1, maxW,
                       sortedSymbol, sizeOfSort, rankStart0,
                       tableLog+1, DSeq, DDesc);
    }

    return iSize;
}


static U32 HUF_decodeSymbolX6(void* op, BIT_DStream_t* DStream, const HUF_DDescX6* dd, const HUF_DSeqX6* ds, const U32 dtLog)
{
    size_t const val = BIT_lookBitsFast(DStream, dtLog);   /* note : dtLog >= 1 */
    memcpy(op, ds+val, sizeof(HUF_DSeqX6));
    BIT_skipBits(DStream, dd[val].nbBits);
    return dd[val].nbBytes;
}

static U32 HUF_decodeLastSymbolsX6(void* op, U32 const maxL, BIT_DStream_t* DStream,
                                  const HUF_DDescX6* dd, const HUF_DSeqX6* ds, const U32 dtLog)
{
    size_t const val = BIT_lookBitsFast(DStream, dtLog);   /* note : dtLog >= 1 */
    U32 const length = dd[val].nbBytes;
    if (length <= maxL) {
        memcpy(op, ds+val, length);
        BIT_skipBits(DStream, dd[val].nbBits);
        return length;
    }
    memcpy(op, ds+val, maxL);
    if (DStream->bitsConsumed < (sizeof(DStream->bitContainer)*8)) {
        BIT_skipBits(DStream, dd[val].nbBits);
        if (DStream->bitsConsumed > (sizeof(DStream->bitContainer)*8))
            DStream->bitsConsumed = (sizeof(DStream->bitContainer)*8);   /* ugly hack; works only because it's the last symbol. Note : can't easily extract nbBits from just this symbol */
    }
    return maxL;
}


#define HUF_DECODE_SYMBOLX6_0(ptr, DStreamPtr) \
    ptr += HUF_decodeSymbolX6(ptr, DStreamPtr, dd, ds, dtLog)

#define HUF_DECODE_SYMBOLX6_1(ptr, DStreamPtr) \
    if (MEM_64bits() || (HUF_TABLELOG_MAX<=12)) \
        HUF_DECODE_SYMBOLX6_0(ptr, DStreamPtr)

#define HUF_DECODE_SYMBOLX6_2(ptr, DStreamPtr) \
    if (MEM_64bits()) \
        HUF_DECODE_SYMBOLX6_0(ptr, DStreamPtr)

static inline size_t HUF_decodeStreamX6(BYTE* p, BIT_DStream_t* bitDPtr, BYTE* const pEnd, const U32* DTable, const U32 dtLog)
{
    const void* const ddPtr = DTable+1;
    const HUF_DDescX6* dd = (const HUF_DDescX6*)ddPtr;
    const void* const dsPtr = DTable + 1 + ((size_t)1<<(dtLog-1));
    const HUF_DSeqX6* ds = (const HUF_DSeqX6*)dsPtr;
    BYTE* const pStart = p;

    /* up to 16 symbols at a time */
    while ((BIT_reloadDStream(bitDPtr) == BIT_DStream_unfinished) && (p <= pEnd-16)) {
        HUF_DECODE_SYMBOLX6_2(p, bitDPtr);
        HUF_DECODE_SYMBOLX6_1(p, bitDPtr);
        HUF_DECODE_SYMBOLX6_2(p, bitDPtr);
        HUF_DECODE_SYMBOLX6_0(p, bitDPtr);
    }

    /* closer to the end, up to 4 symbols at a time */
    while ((BIT_reloadDStream(bitDPtr) == BIT_DStream_unfinished) && (p <= pEnd-4))
        HUF_DECODE_SYMBOLX6_0(p, bitDPtr);

    while ((BIT_reloadDStream(bitDPtr) <= BIT_DStream_endOfBuffer) && (p < pEnd))
        p += HUF_decodeLastSymbolsX6(p, (U32)(pEnd-p), bitDPtr, dd, ds, dtLog);

    return p-pStart;
}

size_t HUF_decompress1X6_usingDTable(
          void* dst,  size_t dstSize,
    const void* cSrc, size_t cSrcSize,
    const U32* DTable)
{
    const BYTE* const istart = (const BYTE*) cSrc;
    BYTE* const ostart = (BYTE*) dst;
    BYTE* const oend = ostart + dstSize;
    BIT_DStream_t bitD;

    /* Init */
    { size_t const errorCode = BIT_initDStream(&bitD, istart, cSrcSize);
      if (HUF_isError(errorCode)) return errorCode; }

    /* finish bitStreams one by one */
    { U32 const dtLog = DTable[0];
      HUF_decodeStreamX6(ostart, &bitD, oend, DTable, dtLog); }

    /* check */
    if (!BIT_endOfDStream(&bitD)) return ERROR(corruption_detected);

    /* decoded size */
    return dstSize;
}

size_t HUF_decompress1X6 (void* dst, size_t dstSize, const void* cSrc, size_t cSrcSize)
{
    HUF_CREATE_STATIC_DTABLEX6(DTable, HUF_TABLELOG_MAX);
    const BYTE* ip = (const BYTE*) cSrc;

    size_t const hSize = HUF_readDTableX6 (DTable, cSrc, cSrcSize);
    if (HUF_isError(hSize)) return hSize;
    if (hSize >= cSrcSize) return ERROR(srcSize_wrong);
    ip += hSize;
    cSrcSize -= hSize;

    return HUF_decompress1X6_usingDTable (dst, dstSize, ip, cSrcSize, DTable);
}


#define HUF_DECODE_ROUNDX6 \
            HUF_DECODE_SYMBOLX6_2(op1, &bitD1); \
            HUF_DECODE_SYMBOLX6_2(op2, &bitD2); \
            HUF_DECODE_SYMBOLX6_2(op3, &bitD3); \
            HUF_DECODE_SYMBOLX6_2(op4, &bitD4); \
            HUF_DECODE_SYMBOLX6_1(op1, &bitD1); \
            HUF_DECODE_SYMBOLX6_1(op2, &bitD2); \
            HUF_DECODE_SYMBOLX6_1(op3, &bitD3); \
            HUF_DECODE_SYMBOLX6_1(op4, &bitD4); \
            HUF_DECODE_SYMBOLX6_2(op1, &bitD1); \
            HUF_DECODE_SYMBOLX6_2(op2, &bitD2); \
            HUF_DECODE_SYMBOLX6_2(op3, &bitD3); \
            HUF_DECODE_SYMBOLX6_2(op4, &bitD4); \
            HUF_DECODE_SYMBOLX6_0(op1, &bitD1); \
            HUF_DECODE_SYMBOLX6_0(op2, &bitD2); \
            HUF_DECODE_SYMBOLX6_0(op3, &bitD3); \
            HUF_DECODE_SYMBOLX6_0(op4, &bitD4);

size_t HUF_decompress4X6_usingDTable(
          void* dst,  size_t dstSize,
    const void* cSrc, size_t cSrcSize,
    const U32* DTable)
{
    /* Check */
    if (cSrcSize < 10) return ERROR(corruption_detected);   /* strict minimum : jump table + 1 byte per stream */
    if (dstSize  < 64) return ERROR(dstSize_tooSmall);      /* only work for dstSize >= 64 */

    {   const BYTE* const istart = (const BYTE*) cSrc;
        BYTE* const ostart = (BYTE*) dst;
        BYTE* const oend = ostart + dstSize;

        const U32 dtLog = DTable[0];
        const void* const ddPtr = DTable+1;
        const HUF_DDescX6* dd = (const HUF_DDescX6*)ddPtr;
        const void* const dsPtr = DTable + 1 + ((size_t)1<<(dtLog-1));
        const HUF_DSeqX6* ds = (const HUF_DSeqX6*)dsPtr;

        /* Init */
        BIT_DStream_t bitD1;
        BIT_DStream_t bitD2;
        BIT_DStream_t bitD3;
        BIT_DStream_t bitD4;
        const size_t length1 = MEM_readLE16(istart);
        const size_t length2 = MEM_readLE16(istart+2);
        const size_t length3 = MEM_readLE16(istart+4);
        size_t length4;
        const BYTE* const istart1 = istart + 6;  /* jumpTable */
        const BYTE* const istart2 = istart1 + length1;
        const BYTE* const istart3 = istart2 + length2;
        const BYTE* const istart4 = istart3 + length3;
        const size_t segmentSize = (dstSize+3) / 4;
        BYTE* const opStart2 = ostart + segmentSize;
        BYTE* const opStart3 = opStart2 + segmentSize;
        BYTE* const opStart4 = opStart3 + segmentSize;
        BYTE* op1 = ostart;
        BYTE* op2 = opStart2;
        BYTE* op3 = opStart3;
        BYTE* op4 = opStart4;
        U32 endSignal;

        length4 = cSrcSize - (length1 + length2 + length3 + 6);
        if (length4 > cSrcSize) return ERROR(corruption_detected);   /* overflow */
        { size_t const errorCode = BIT_initDStream(&bitD1, istart1, length1);
          if (HUF_isError(errorCode)) return errorCode; }
        { size_t const errorCode = BIT_initDStream(&bitD2, istart2, length2);
          if (HUF_isError(errorCode)) return errorCode; }
        { size_t const errorCode = BIT_initDStream(&bitD3, istart3, length3);
          if (HUF_isError(errorCode)) return errorCode; }
        { size_t const errorCode = BIT_initDStream(&bitD4, istart4, length4);
          if (HUF_isError(errorCode)) return errorCode; }

        /* 4-64 symbols per loop (1-16 symbols per stream) */
        endSignal = BIT_reloadDStream(&bitD1) | BIT_reloadDStream(&bitD2) | BIT_reloadDStream(&bitD3) | BIT_reloadDStream(&bitD4);
        if (endSignal==BIT_DStream_unfinished) {
            HUF_DECODE_ROUNDX6;
            if (sizeof(bitD1.bitContainer)==4) {   /* need to decode at least 4 bytes per stream */
                    endSignal = BIT_reloadDStream(&bitD1) | BIT_reloadDStream(&bitD2) | BIT_reloadDStream(&bitD3) | BIT_reloadDStream(&bitD4);
                    HUF_DECODE_ROUNDX6;
            }
            {   U32 const saved2 = MEM_read32(opStart2);   /* saved from overwrite */
                U32 const saved3 = MEM_read32(opStart3);
                U32 const saved4 = MEM_read32(opStart4);
                endSignal = BIT_reloadDStream(&bitD1) | BIT_reloadDStream(&bitD2) | BIT_reloadDStream(&bitD3) | BIT_reloadDStream(&bitD4);
                for ( ; (op3 <= opStart4) && (endSignal==BIT_DStream_unfinished) && (op4<=(oend-16)) ; ) {
                    HUF_DECODE_ROUNDX6;
                    endSignal = BIT_reloadDStream(&bitD1) | BIT_reloadDStream(&bitD2) | BIT_reloadDStream(&bitD3) | BIT_reloadDStream(&bitD4);
                }
                MEM_write32(opStart2, saved2);
                MEM_write32(opStart3, saved3);
                MEM_write32(opStart4, saved4);
        }   }

        /* check corruption */
        if (op1 > opStart2) return ERROR(corruption_detected);
        if (op2 > opStart3) return ERROR(corruption_detected);
        if (op3 > opStart4) return ERROR(corruption_detected);
        /* note : op4 already verified within main loop */

        /* finish bitStreams one by one */
        HUF_decodeStreamX6(op1, &bitD1, opStart2, DTable, dtLog);
        HUF_decodeStreamX6(op2, &bitD2, opStart3, DTable, dtLog);
        HUF_decodeStreamX6(op3, &bitD3, opStart4, DTable, dtLog);
        HUF_decodeStreamX6(op4, &bitD4, oend,     DTable, dtLog);

        /* check */
        endSignal = BIT_endOfDStream(&bitD1) & BIT_endOfDStream(&bitD2) & BIT_endOfDStream(&bitD3) & BIT_endOfDStream(&bitD4);
        if (!endSignal) return ERROR(corruption_detected);

        /* decoded size */
        return dstSize;
    }
}


size_t HUF_decompress4X6 (void* dst, size_t dstSize, const void* cSrc, size_t cSrcSize)
{
    HUF_CREATE_STATIC_DTABLEX6(DTable, HUF_TABLELOG_MAX);
    const BYTE* ip = (const BYTE*) cSrc;

    size_t const hSize = HUF_readDTableX6 (DTable, cSrc, cSrcSize);
    if (HUF_isError(hSize)) return hSize;
    if (hSize >= cSrcSize) return ERROR(srcSize_wrong);
    ip += hSize;
    cSrcSize -= hSize;

    return HUF_decompress4X6_usingDTable (dst, dstSize, ip, cSrcSize, DTable);
}
