/*
  fileio.c - simple generic file i/o handler
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
/*
  Note : this is stand-alone program.
  It is not part of FSE compression library, it is a user program of the FSE library.
  The license of FSE library is BSD.
  The license of this library is GPLv2.
*/

/*-************************************
*  Compiler Options
**************************************/
/* Disable some Visual warning messages */
#ifdef _MSC_VER
#  define _CRT_SECURE_NO_WARNINGS
#  define _CRT_SECURE_NO_DEPRECATE     /* VS2005 */
#  pragma warning(disable : 4127)      /* disable: C4127: conditional expression is constant */
#endif

#define GCC_VERSION (__GNUC__ * 100 + __GNUC_MINOR__)

#define _FILE_OFFSET_BITS 64   /* Large file support on 32-bits unix */
#define _POSIX_SOURCE 1        /* enable fileno() within <stdio.h> on unix */


/*-************************************
*  Includes
**************************************/
#include <stdio.h>    /* fprintf, fopen, fread, _fileno, stdin, stdout */
#include <stdlib.h>   /* malloc, free */
#include <string.h>   /* strcmp, strlen */
#include <time.h>     /* clock */
#include <assert.h>   /* assert */
#include "fileio.h"
#include "fse.h"
#include "huf.h"
#include "zlibh.h"    /*ZLIBH_compress */
#define XXH_STATIC_LINKING_ONLY
#include "xxhash.h"


/*-************************************
*  OS-specific Includes
**************************************/
#if defined(MSDOS) || defined(OS2) || defined(WIN32) || defined(_WIN32) || defined(__CYGWIN__)
#  include <fcntl.h>    // _O_BINARY
#  include <io.h>       // _setmode, _isatty
#  ifdef __MINGW32__
   int _fileno(FILE *stream);   // MINGW somehow forgets to include this windows declaration into <stdio.h>
#  endif
#  define SET_BINARY_MODE(file) { int unused = _setmode(_fileno(file), _O_BINARY); (void)unused; }
#  define IS_CONSOLE(stdStream) _isatty(_fileno(stdStream))
#else
#  include <unistd.h>   // isatty
#  define SET_BINARY_MODE(file)
#  define IS_CONSOLE(stdStream) isatty(fileno(stdStream))
#endif


/*-************************************
*  Basic Types
**************************************/
#if defined (__STDC_VERSION__) && __STDC_VERSION__ >= 199901L   /* C99 */
# include <stdint.h>
typedef uint8_t  BYTE;
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


/*-************************************
*  Constants
**************************************/
#define KB *(1U<<10)
#define MB *(1U<<20)
#define GB *(1U<<30)

#define _1BIT  0x01
#define _2BITS 0x03
#define _3BITS 0x07
#define _4BITS 0x0F
#define _6BITS 0x3F
#define _8BITS 0xFF

#define BIT5  0x20
#define BIT6  0x40
#define BIT7  0x80

#define FIO_magicNumber_fse   0x183E2309
#define FIO_magicNumber_huf   0x183E3309
#define FIO_magicNumber_zlibh 0x183E4309
static const unsigned FIO_maxBlockSizeID = 6;   /* => 64 KB block */
static const unsigned FIO_maxBlockHeaderSize = 5;

#define FIO_FRAMEHEADERSIZE 5        /* as a define, because needed to allocated table on stack */
#define FIO_BLOCKSIZEID_DEFAULT  5   /* as a define, because needed to init static g_blockSizeId */
#define FSE_CHECKSUM_SEED        0

#define CACHELINE 64


/*-************************************
*  Complex types
**************************************/
typedef enum { bt_compressed, bt_raw, bt_rle, bt_crc } bType_t;


/*-************************************
*  Memory operations
**************************************/
static void FIO_writeLE32(void* memPtr, U32 val32)
{
    BYTE* p = (BYTE*)memPtr;
    p[0] = (BYTE)val32;
    p[1] = (BYTE)(val32>>8);
    p[2] = (BYTE)(val32>>16);
    p[3] = (BYTE)(val32>>24);
}

static U32 FIO_readLE32(const void* memPtr)
{
    const BYTE* p = (const BYTE*)memPtr;
    return (U32)((U32)p[0] + ((U32)p[1]<<8) + ((U32)p[2]<<16) + ((U32)p[3]<<24));
}


/*-************************************
*  Macros
**************************************/
#define DISPLAY(...)         fprintf(stderr, __VA_ARGS__)

static int g_displayLevel = 2;   /* 0 : no display;   1: errors;   2 : + result + interaction + warnings;   3 : + progression;   4 : + information */
#define DISPLAYLEVEL(l, ...) if (g_displayLevel>=l) { DISPLAY(__VA_ARGS__); }

#define DISPLAYUPDATE(l, ...) if (g_displayLevel>=l) { \
            if ((FIO_GetMilliSpan(g_time) > refreshRate) || (g_displayLevel>=4)) \
            { g_time = clock(); DISPLAY(__VA_ARGS__); \
            if (g_displayLevel>=4) fflush(stdout); } }
static const unsigned refreshRate = 150;
static clock_t g_time = 0;


/*-************************************
*  Local Parameters
**************************************/
static U32 g_overwrite = 0;
static U32 g_blockSizeId = FIO_BLOCKSIZEID_DEFAULT;
FIO_compressor_t g_compressor = FIO_fse;

void FIO_overwriteMode(void) { g_overwrite=1; }
void FIO_setCompressor(FIO_compressor_t c) { g_compressor = c; }
void FIO_setDisplayLevel(int dlevel) { g_displayLevel = dlevel; }


/*-************************************
*  Exceptions
**************************************/
#define DEBUG 0
#define DEBUGOUTPUT(...) if (DEBUG) DISPLAY(__VA_ARGS__);
#define EXM_THROW(error, ...)                                             \
{                                                                         \
    DEBUGOUTPUT("Error defined at %s, line %i : \n", __FILE__, __LINE__); \
    DISPLAYLEVEL(1, "Error %i : ", error);                                \
    DISPLAYLEVEL(1, __VA_ARGS__);                                         \
    DISPLAYLEVEL(1, "\n");                                                \
    exit(error);                                                          \
}


/*-************************************
*  Version modifiers
**************************************/
#define DEFAULT_COMPRESSOR    FSE_compress
#define DEFAULT_DECOMPRESSOR  FSE_decompress


/*-************************************
*  Functions
**************************************/
static unsigned FIO_GetMilliSpan(clock_t nPrevious)
{
    clock_t nCurrent = clock();
    unsigned nSpan = (unsigned)(((nCurrent - nPrevious) * 1000) / CLOCKS_PER_SEC);
    return nSpan;
}

static int FIO_blockID_to_blockSize (int id) { return (1 << id) KB; }


static void get_fileHandle(const char* input_filename, const char* output_filename, FILE** pfinput, FILE** pfoutput)
{
    if (!strcmp (input_filename, stdinmark)) {
        DISPLAYLEVEL(4,"Using stdin for input\n");
        *pfinput = stdin;
        SET_BINARY_MODE(stdin);
    } else {
        *pfinput = fopen(input_filename, "rb");
    }

    if (*pfinput == 0) EXM_THROW(12, "Pb opening %s", input_filename);

    if (!strcmp (output_filename, stdoutmark)) {
        DISPLAYLEVEL(4,"Using stdout for output\n");
        *pfoutput = stdout;
        SET_BINARY_MODE(stdout);
    } else {
        /* Check if destination file already exists */
        *pfoutput=0;
        if (strcmp(output_filename,nulmark)) *pfoutput = fopen( output_filename, "rb" );
        if (*pfoutput!=0) {
            fclose(*pfoutput);
            if (!g_overwrite) {
                char ch;
                if (g_displayLevel <= 1)   /* No interaction possible */
                    EXM_THROW(11, "Operation aborted : %s already exists", output_filename);
                DISPLAYLEVEL(2, "Warning : %s already exists\n", output_filename);
                DISPLAYLEVEL(2, "Overwrite ? (Y/N) : ");
                ch = (char)getchar();
                if ((ch!='Y') && (ch!='y')) EXM_THROW(11, "Operation aborted : %s already exists", output_filename);
        }   }
        *pfoutput = fopen( output_filename, "wb" );
    }

    if ( *pfoutput==0) EXM_THROW(13, "Pb opening %s", output_filename);
}


size_t FIO_ZLIBH_compress(void* dst, size_t dstSize, const void* src, size_t srcSize )
{
    (void)dstSize;
    return (size_t)ZLIBH_compress((char*)dst, (const char*)src, (int)srcSize);
}

/*
Compressed format : MAGICNUMBER - STREAMDESCRIPTOR - ( BLOCKHEADER - COMPRESSEDBLOCK ) - STREAMCRC
MAGICNUMBER - 4 bytes - Designates compression algo
STREAMDESCRIPTOR - 1 byte
    bits 0-3 : max block size, 2^value, from 0 to 6; min 0=>1KB, max 6=>64KB, typical 5=>32 KB
    bits 4-7 = 0 : reserved;
BLOCKHEADER - 1-5 bytes
    1st byte :
    bits 6-7 : blockType (compressed, raw, rle, crc (end of Frame)
    bit 5 : full block
    bits 0-4 : reserved
    ** if not full block **
    2nd & 3rd byte : regenerated size of block (big endian)
    ** if blockType==compressed **
    next 2 bytes : compressed size of block
COMPRESSEDBLOCK
    the compressed data itself.
STREAMCRC - 3 bytes (including 1-byte blockheader)
    22 bits (xxh32() >> 5) checksum of the original data, big endian
*/
unsigned long long FIO_compressFilename(const char* output_filename, const char* input_filename)
{
    U64 filesize = 0;
    U64 compressedfilesize = 0;
    FILE* finput;
    FILE* foutput;
    size_t const inputBlockSize = FIO_blockID_to_blockSize(g_blockSizeId);
    char* const in_buff = (char*)malloc(inputBlockSize);
    char* const out_buff = (char*)malloc(FSE_compressBound(inputBlockSize) + 5);
    XXH32_state_t xxhState;
    typedef size_t (*compressor_t) (void* dst, size_t dstSize, const void* src, size_t srcSize);
    compressor_t compressor;
    unsigned magicNumber;


    /* Init */
    if (!in_buff || !out_buff) EXM_THROW(21, "Allocation error : not enough memory");
    XXH32_reset (&xxhState, FSE_CHECKSUM_SEED);
    get_fileHandle(input_filename, output_filename, &finput, &foutput);
    switch (g_compressor)
    {
    case FIO_fse:
        compressor = FSE_compress;
        magicNumber = FIO_magicNumber_fse;
        break;
    case FIO_huf:
        compressor = HUF_compress;
        magicNumber = FIO_magicNumber_huf;
        break;
    case FIO_zlibh:
        compressor = FIO_ZLIBH_compress;
        magicNumber = FIO_magicNumber_zlibh;
        break;
    default :
        EXM_THROW(20, "unknown compressor selection");
    }

    /* Write Frame Header */
    FIO_writeLE32(out_buff, magicNumber);
    out_buff[4] = (char)g_blockSizeId;          /* Max Block Size descriptor */
    { size_t const sizeCheck = fwrite(out_buff, 1, FIO_FRAMEHEADERSIZE, foutput);
      if (sizeCheck!=FIO_FRAMEHEADERSIZE) EXM_THROW(22, "Write error : cannot write header"); }
    compressedfilesize += FIO_FRAMEHEADERSIZE;

    /* Main compression loop */
    while (1) {
        /* Fill input Buffer */
        size_t cSize;
        size_t const inSize = fread(in_buff, (size_t)1, (size_t)inputBlockSize, finput);
        DISPLAYLEVEL(6, "reading %zu bytes from input (%s)\n",
                        inSize, input_filename);
        if (inSize==0) break;
        filesize += inSize;
        XXH32_update(&xxhState, in_buff, inSize);
        DISPLAYUPDATE(2, "\rRead : %u MB   ", (U32)(filesize>>20));

        /* Compress Block */
        cSize = compressor(out_buff + FIO_maxBlockHeaderSize, FSE_compressBound(inputBlockSize), in_buff, inSize);
        if (FSE_isError(cSize)) EXM_THROW(23, "Compression error : %s ", FSE_getErrorName(cSize));

        /* Write cBlock */
        switch(cSize)
        {
        size_t headerSize;
        case 0: /* raw */
            DISPLAYLEVEL(6, "packing uncompressed block, of size %zu \n", inSize);
            if (inSize == inputBlockSize) {
                out_buff[0] = (BYTE)((bt_raw << 6) + BIT5);
                headerSize = 1;
            } else {
                out_buff[0] = (BYTE)(bt_raw << 6);
                out_buff[1] = (BYTE)(inSize >> 8);
                out_buff[2] = (BYTE)inSize;
                headerSize = 3;
            }
            { size_t const sizeCheck = fwrite(out_buff, 1, headerSize, foutput);
              if (sizeCheck!=headerSize) EXM_THROW(24, "Write error : cannot write block header"); }
            { size_t const sizeCheck = fwrite(in_buff, 1, inSize, foutput);
              if (sizeCheck!=(size_t)(inSize)) EXM_THROW(25, "Write error : cannot write block"); }
            compressedfilesize += inSize + headerSize;
            break;
        case 1: /* rle */
            DISPLAYLEVEL(6, "packing RLE block, of size %zu \n", inSize);
            if (inSize == inputBlockSize) {
                out_buff[0] = (BYTE)((bt_rle << 6) + BIT5);
                headerSize = 1;
            } else {
                out_buff[0] = (BYTE)(bt_rle << 6);
                out_buff[1] = (BYTE)(inSize >> 8);
                out_buff[2] = (BYTE)inSize;
                headerSize = 3;
            }
            out_buff[headerSize] = in_buff[0];
            { size_t const sizeCheck = fwrite(out_buff, 1, headerSize+1, foutput);
              if (sizeCheck!=(headerSize+1)) EXM_THROW(26, "Write error : cannot write rle block"); }
            compressedfilesize += headerSize + 1;
            break;
        default : /* compressed */
            DISPLAYLEVEL(6, "packing compressed block, of size %zu, into %zu bytes \n",
                            inSize, cSize);
            if (inSize == inputBlockSize) {
                out_buff[2] = (BYTE)((bt_compressed << 6) + BIT5);
                DISPLAYLEVEL(7, "generated block descriptor : %u \n", out_buff[2]);
                out_buff[3] = (BYTE)(cSize >> 8);
                out_buff[4] = (BYTE)cSize;
                headerSize = 3;
            } else {
                out_buff[0] = (BYTE)(bt_compressed << 6);
                out_buff[1] = (BYTE)(inSize >> 8);
                out_buff[2] = (BYTE)inSize;
                out_buff[3] = (BYTE)(cSize >> 8);
                out_buff[4] = (BYTE)cSize;
                headerSize = FIO_maxBlockHeaderSize;
            }
            { size_t const sizeCheck = fwrite(out_buff+(FIO_maxBlockHeaderSize-headerSize), 1, headerSize+cSize, foutput);
              if (sizeCheck!=(headerSize+cSize)) EXM_THROW(27, "Write error : cannot write rle block"); }
            compressedfilesize += headerSize + cSize;
            break;
        }

        DISPLAYUPDATE(2, "\rRead : %u MB  ==> %.2f%%   ", (U32)(filesize>>20), (double)compressedfilesize/filesize*100);
    }

    /* Checksum */
    {   U32 checksum = XXH32_digest(&xxhState);
        checksum = (checksum >> 5) & ((1U<<22)-1);
        out_buff[2] = (BYTE)checksum;
        out_buff[1] = (BYTE)(checksum >> 8);
        out_buff[0] = (BYTE)((checksum >> 16) + (bt_crc << 6));
        { size_t const sizeCheck = fwrite(out_buff, 1, 3, foutput);
          if (sizeCheck!=3) EXM_THROW(28, "Write error : cannot write checksum"); }
        compressedfilesize += 3;
    }

    /* Status */
    DISPLAYLEVEL(2, "\r%79s\r", "");
    DISPLAYLEVEL(2,"Compressed %llu bytes into %llu bytes ==> %.2f%%\n",
        (unsigned long long) filesize, (unsigned long long) compressedfilesize, (double)compressedfilesize/filesize*100);

    /* clean */
    free(in_buff);
    free(out_buff);
    fclose(finput);
    fclose(foutput);

    return compressedfilesize;
}



size_t FIO_ZLIBH_decompress(void* dst, size_t dstSize, const void* src, size_t srcSize)
{
    (void)srcSize; (void)dstSize;
    return (size_t) ZLIBH_decompress ((char*)dst, (const char*)src);
}

/*
Compressed format : MAGICNUMBER - STREAMDESCRIPTOR - ( BLOCKHEADER - COMPRESSEDBLOCK ) - STREAMCRC
MAGICNUMBER - 4 bytes - Designates compression algo
STREAMDESCRIPTOR - 1 byte
    bits 0-3 : max block size, 2^value, from 0 to 6; min 0=>1KB, max 6=>64KB, typical 5=>32 KB
    bits 4-7 = 0 : reserved;
BLOCKHEADER - 1-5 bytes
    1st byte :
    bits 6-7 : blockType (compressed, raw, rle, crc (end of Frame)
    bit 5 : full block
    bits 0-4 : reserved
    ** if not full block **
    2nd & 3rd byte : regenerated size of block (big endian)
    ** if blockType==compressed **
    next 2 bytes : compressed size of block
COMPRESSEDBLOCK
    the compressed data itself.
STREAMCRC - 3 bytes (including 1-byte blockheader)
    22 bits (xxh32() >> 5) checksum of the original data, big endian
*/
unsigned long long FIO_decompressFilename(const char* output_filename, const char* input_filename)
{
    FILE* finput, *foutput;
    U64   filesize = 0;
    BYTE* in_buff;
    BYTE* out_buff;
    BYTE* ip;
    U32   blockSize;
    XXH32_state_t xxhState;
    typedef size_t (*decompressor_t) (void* dst, size_t dstSize, const void* src, size_t srcSize);
    decompressor_t decompressor = FSE_decompress;

    /* Init */
    XXH32_reset(&xxhState, FSE_CHECKSUM_SEED);
    get_fileHandle(input_filename, output_filename, &finput, &foutput);

    /* check header */
    {   BYTE header[FIO_FRAMEHEADERSIZE];

        { size_t const sizeCheck = fread(header, (size_t)1, FIO_FRAMEHEADERSIZE, finput);
          if (sizeCheck != FIO_FRAMEHEADERSIZE) EXM_THROW(30, "Read error : cannot read header\n"); }

        switch(FIO_readLE32(header))   /* magic number */
        {
        case FIO_magicNumber_fse:
            DISPLAYLEVEL(5, "compressed with fse \n");
            decompressor = FSE_decompress;
            break;
        case FIO_magicNumber_huf:
            DISPLAYLEVEL(5, "compressed with huff0 \n");
            decompressor = HUF_decompress;
            break;
        case FIO_magicNumber_zlibh:
            DISPLAYLEVEL(5, "compressed with zlib's huffman \n");
            decompressor = FIO_ZLIBH_decompress;
            break;
        default :
            EXM_THROW(31, "Wrong file type : unknown header\n");
        }

        {   U32 const blockSizeId = header[4];
            if (blockSizeId > FIO_maxBlockSizeID)
                EXM_THROW(32, "Wrong version : unknown header flags\n");
            blockSize = FIO_blockID_to_blockSize(blockSizeId);
    }   }

    /* Allocate Memory */
    in_buff  = (BYTE*)malloc(blockSize + FIO_maxBlockHeaderSize);
    out_buff = (BYTE*)malloc(blockSize);
    if (!in_buff || !out_buff) EXM_THROW(33, "Allocation error : not enough memory");

    /* read first block header */
    { size_t const sizeCheck = fread(in_buff, 1, 1, finput);
      if (sizeCheck != 1) EXM_THROW(34, "Read error : cannot read header\n");
      ip = in_buff;
    }

    /* Main Loop */
    while (1) {
        size_t rSize=blockSize, cSize;

        /* Decode header */
        int const bType = (ip[0] & (BIT7+BIT6)) >> 6;
        DISPLAYLEVEL(6, "next block type == %i \n", bType);
        DISPLAYLEVEL(7, "read block descriptor : %u \n", ip[0]);
        if (bType == bt_crc) break;   /* end - frame content CRC */

        {   int const fullBlock = ip[0] & BIT5;
            DISPLAYLEVEL(6, "next block is full ? ==> %i \n", !!fullBlock);
            if (!fullBlock) {
                size_t const sizeCheck = fread(in_buff, 1, 2, finput);
                if (sizeCheck != 2) EXM_THROW(35, "Read error : cannot read header\n");
                rSize = (in_buff[0]<<8) + in_buff[1];
        }   }

        switch(bType)
        {
          case bt_compressed :
            {   size_t const sizeCheck = fread(in_buff, 1, 2, finput);
                if (sizeCheck != 2) EXM_THROW(36, "Read error : cannot read header\n");
                cSize = (in_buff[0]<<8) + in_buff[1];
                break;
            }
          case bt_raw :
            cSize = rSize;
            break;
          case bt_rle :
            cSize = 1;
            break;
          default :
          case bt_crc :
            cSize = 0;
            assert(0);   /* supposed already eliminated at this stage */
        }

        DISPLAYLEVEL(6, "next block has a compressed size of %zu, and an original size of %zu \n",
                        cSize, rSize);

        /* Fill input buffer */
        {   size_t const toReadSize = cSize + 1;
            size_t const readSize = fread(in_buff, 1, toReadSize, finput);
            if (readSize != toReadSize) EXM_THROW(38, "Read error");
            ip = in_buff + cSize;   /* end - 1 */
        }

        /* Decode block */
        switch(bType)
        {
          case bt_compressed :
            rSize = decompressor(out_buff, rSize, in_buff, cSize);
            if (FSE_isError(rSize))
                EXM_THROW(39, "Decoding error : %s", FSE_getErrorName(rSize));
            break;
          case bt_raw :
            /* will read directly from in_buff, so no need to memcpy */
            break;
          case bt_rle :
            memset(out_buff, in_buff[0], rSize);
            break;
          default :
          case bt_crc :
            assert(0);   /* supposed already eliminated at this stage */
        }

        /* Write block */
        switch(bType)
        {
          case bt_compressed :
          case bt_rle :
            { size_t const writeSizeCheck = fwrite(out_buff, 1, rSize, foutput);
              if (writeSizeCheck != rSize) EXM_THROW(41, "Write error : unable to write data block to destination file"); }
            XXH32_update(&xxhState, out_buff, rSize);
            filesize += rSize;
            break;
          case bt_raw :
            { size_t const writeSizeCheck = fwrite(in_buff, 1, cSize, foutput);
              if (writeSizeCheck != cSize) EXM_THROW(42, "Write error : unable to write data block to destination file"); }
            XXH32_update(&xxhState, in_buff, cSize);
            filesize += cSize;
            break;
          default :
          case bt_crc :
            assert(0);   /* supposed already eliminated at this stage */
        }
    }

    /* CRC verification */
    { size_t const sizeCheck = fread(ip+1, 1, 2, finput);
      if (sizeCheck != 2) EXM_THROW(43, "Read error"); }
    {   U32 const CRCsaved = ip[2] + (ip[1]<<8) + ((ip[0] & _6BITS) << 16);
        U32 const CRCcalculated = (XXH32_digest(&xxhState) >> 5) & ((1U<<22)-1);
        if (CRCsaved != CRCcalculated) EXM_THROW(44, "CRC error : wrong checksum, corrupted data");
    }

    DISPLAYLEVEL(2, "\r%79s\r", "");
    DISPLAYLEVEL(2, "Decoded %llu bytes\n", (long long unsigned)filesize);

    /* clean */
    free(in_buff);
    free(out_buff);
    fclose(finput);
    fclose(foutput);

    return filesize;
}
