// Copyright (c) 2018 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BIP158_H
#define BIP158_H

#include <blockfilter.h>

class PyBIP158
{
public:
    GCSFilter *filter;

public:

    PyBIP158(std::vector< std::vector< unsigned char > >& hashes);
    ~PyBIP158();
    
    bool Match(std::vector< unsigned char >& hash);
    bool MatchAny(std::vector< std::vector< unsigned char > >& hashes);
};

#endif // BIP158_H
