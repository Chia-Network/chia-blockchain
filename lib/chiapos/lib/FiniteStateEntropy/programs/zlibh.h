/* ******************************************************************
   FSE : Finite State Entropy coder
   header file
   Copyright (C) 2013-2015, Yann Collet.
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
   - Public forum : https://groups.google.com/forum/#!forum/lz4c
****************************************************************** */
#pragma once

#if defined (__cplusplus)
extern "C" {
#endif


/**************************************
*  Compiler Options
**************************************/
#if defined(_MSC_VER) && !defined(__cplusplus)   // Visual Studio
#  define inline __inline           // Visual C is not C99, but supports some kind of inline
#endif


/****************************
*  zlib simple functions
****************************/
int ZLIBH_compress   (char* dest, const char* source, int inputSize);
int ZLIBH_decompress (char* dest, const char* compressed);
/*
ZLIBH_compress():
    Will take a memory buffer as input (const char* source), of size int inputSize,
    and compress it using Huffman code from Zlib to destination buffer char* dest.
    Destination buffer must be already allocated, and sized to handle worst case situations.
    Use ZLIBH_compressBound() to determine this size.
    return : size of compressed data
ZLIBH_decompress():
    Will decompress into destination buffer char* dest, a compressed data.
    Destination buffer must be already allocated, and large enough to accommodate originalSize bytes.
    Compressed input must be pointed by const char* compressed.
    return : originalSize
*/


#define ZLIBH_COMPRESSBOUND(size) (size + 256)   // mostly headers
static inline int ZLIBH_compressBound(int size) { return ZLIBH_COMPRESSBOUND(size); }
/*
ZLIBH_compressBound():
    Gives the maximum (worst case) size that can be reached by function ZLIBH_compress.
    Used to know how much memory to allocate for destination buffer.
*/

int ZLIBH_getDistributionTotal(void);
int ZLIBH_encode(char* dest, const char* source, int inputSize);
/*
ZLIBH_encode():
    This version allows the use of customized format or rules to determine the distribution properties of 'source'.
    It will only compress 'inputSize' bytes from 'source'.
    **It will not calculate its distribution, nor generate any header.**
    The distribution of symbols **must be provided** using a table of unsigned int 'distribution'.
    The number of symbols (and therefore the size of 'distribution' table) must be provided as nbSymbols.
    **For a distribution to be valid, the total of all symbols must be strictly equal to ZLIBH_getDistributionTotal()**
    Destination buffer must be already allocated, and sized to handle worst case situations.
    Use ZLIBH_compressBound() to determine this size.
    return : size of compressed data (without header)
             or 0 if failed (typically, wrong distribution).
*/

int ZLIBH_decode(char* dest, int originalSize, const char* compressed, unsigned int* distribution);
/*
    This version allows the use of customized format or rules to determine the distribution properties.
    It will only decode compressed bitstream 'compressed' into 'dest', without reading any header.
    Distribution is expected to be provided using the table of unsigned int 'distribution'.
    Same rules as ZLIBH_encode() are valid.
    return : size of compressed data (without header)
             or 0 if failed (typically, wrong distribution).
*/


#if defined (__cplusplus)
}
#endif
