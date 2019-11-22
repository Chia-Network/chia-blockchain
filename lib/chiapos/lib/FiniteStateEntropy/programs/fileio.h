/*
  fileio.h - simple generic file i/o handler
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
#pragma once

#if defined (__cplusplus)
extern "C" {
#endif


/**************************************
*  Special i/o constants
**************************************/
#define NULL_OUTPUT "null"
static char const stdinmark[] = "stdin";
static char const stdoutmark[] = "stdout";
#ifdef _WIN32
#  define nulmark "nul"
#else
#  define nulmark "/dev/null"
#endif


/**************************************
*  Parameters
**************************************/
typedef enum { FIO_fse, FIO_huf, FIO_zlibh } FIO_compressor_t;
void FIO_setCompressor(FIO_compressor_t c);
void FIO_setDisplayLevel(int dlevel);
void FIO_overwriteMode(void);


/**************************************
*  Stream/File functions
**************************************/
unsigned long long FIO_compressFilename (const char* outfilename, const char* infilename);
unsigned long long FIO_decompressFilename (const char* outfilename, const char* infilename);
/*
FIO_compressFilename :
    result : size of compressed file

FIO_decompressFilename :
    result : size of regenerated file
*/



#if defined (__cplusplus)
}
#endif
