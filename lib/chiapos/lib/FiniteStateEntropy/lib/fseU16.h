/* ******************************************************************
   FSEU16 : Finite State Entropy coder for 16-bits input
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
   - FSE source repository : https://github.com/Cyan4973/FiniteStateEntropy
   - Public forum : https://groups.google.com/forum/#!forum/lz4c
****************************************************************** */
#ifndef FSE_U16_H_30982039483
#define FSE_U16_H_30982039483

#if defined (__cplusplus)
extern "C" {
#endif


/*-*****************************************
*  Tuning parameters
*******************************************/
/* FSE_MAX_SYMBOL_VALUE :
*  Maximum nb of symbol values authorized.
*  Required for allocation purposes */
#ifndef FSEU16_MAX_SYMBOL_VALUE
#  define FSEU16_MAX_SYMBOL_VALUE 286   /* This is just an example, typical value for zlib */
#endif
#ifdef FSE_MAX_SYMBOL_VALUE
#  undef FSE_MAX_SYMBOL_VALUE
#endif
#define FSE_MAX_SYMBOL_VALUE FSEU16_MAX_SYMBOL_VALUE

/*-*****************************************
*  Includes
*******************************************/
#include <stddef.h>    /* size_t, ptrdiff_t */


/* *****************************************
*  FSE U16 functions
*******************************************/

/*!FSE_compressU16() :
   data is presented or regenerated as a table of unsigned short (2 bytes per symbol),
   which is useful for alphabet size > 256.
   Important ! All symbol values within input table must be <= 'maxSymbolValue'.
   Maximum allowed 'maxSymbolValue' is controlled by constant FSE_MAX_SYMBOL_VALUE
   Special values : if result == 0, data is not compressible => Nothing is stored within cSrc !!
                    if result == 1, data is one constant element x srcSize times. Use RLE compression.
                    if FSE_isError(result), it's an error code.*/
size_t FSE_compressU16(void* dst, size_t dstCapacity,
       const unsigned short* src, size_t srcSize,
       unsigned maxSymbolValue, unsigned tableLog);

size_t FSE_decompressU16(unsigned short* dst, size_t dstCapacity, const void* cSrc, size_t cSrcSize);



#if defined (__cplusplus)
}
#endif

#endif  /* FSE_U16_H_30982039483 */
