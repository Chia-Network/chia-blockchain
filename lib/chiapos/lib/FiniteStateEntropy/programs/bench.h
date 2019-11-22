/*
    bench.h - Demo program to benchmark open-source compression algorithm
    Copyright (C) Yann Collet 2012-2014
    GPLv2 License

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
    Public forum : https://groups.google.com/forum/#!forum/lz4c
*/
#pragma once

#if defined (__cplusplus)
extern "C" {
#endif


// bench functions
int BMK_benchFiles(const char** fileNamesTable, int nbFiles);
int BMK_benchCore_Files(const char** fileNamesTable, int nbFiles);
int BMK_benchFilesLZ4E(const char** fileNamesTable, int nbFiles, int algoNb);


// Parameters
void BMK_SetBlocksize(unsigned bsize);
void BMK_SetNbIterations(int nbLoops);
void BMK_SetByteCompressor(int id);
void BMK_SetTableLog(int tableLog);


#if defined (__cplusplus)
}
#endif
