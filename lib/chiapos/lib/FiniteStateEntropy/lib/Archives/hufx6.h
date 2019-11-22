/* ******************************************************************
   Huffman coder, part of New Generation Entropy library
   header file
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
   - Source repository : https://github.com/Cyan4973/FiniteStateEntropy
****************************************************************** */
#ifndef HUF_H_2342354
#define HUF_H_2342354

#if defined (__cplusplus)
extern "C" {
#endif


/* *** Dependencies *** */
#include <stddef.h>    /* size_t */
#define HUF_STATIC_LINKING_ONLY
#include "huf.h"


/* *** Static allocation *** */
#define HUF_CREATE_STATIC_DTABLEX6(DTable, maxTableLog) \
        unsigned int DTable[HUF_DTABLE_SIZE(maxTableLog) * 3 / 2] = { maxTableLog }


/* *** Advanced decompression functions *** */
size_t HUF_decompress4X6 (void* dst, size_t dstSize, const void* cSrc, size_t cSrcSize);   /* quad-symbols decoder, only works for dstSize >= 64 */


/* *** HUF detailed API *** */
size_t HUF_readDTableX6 (unsigned* DTable, const void* src, size_t srcSize);
size_t HUF_decompress4X6_usingDTable(void* dst, size_t maxDstSize, const void* cSrc, size_t cSrcSize, const unsigned* DTable);


/* single stream variants */
size_t HUF_decompress1X6 (void* dst, size_t dstSize, const void* cSrc, size_t cSrcSize);   /* quad-symbols decoder, only works for dstSize >= 64 */
size_t HUF_decompress1X6_usingDTable(void* dst, size_t maxDstSize, const void* cSrc, size_t cSrcSize, const unsigned* DTable);


#if defined (__cplusplus)
}
#endif

#endif   /* HUF_H_2342354 */
