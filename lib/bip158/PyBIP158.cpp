// Copyright (c) 2018 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php./Users/bill/downloads/gene/chia-blockchain/lib/bip158

#include <bip158.h>

PyBIP158::PyBIP158(std::vector< std::vector< unsigned char > >& hashes)
{
    GCSFilter::ElementSet elements;
    for (int i = 0; i < hashes.size(); ++i)
    {
        GCSFilter::Element element(hashes[i].size());
        for(int j=0;j<hashes[i].size();j++)
        {
            element[j] = hashes[i][j];
        }
        elements.insert(std::move(element));
    }
    filter=new GCSFilter({0, 0, 20, 1 << 20},elements);
}

PyBIP158::~PyBIP158()
{
    delete filter;
}

bool PyBIP158::Match(std::vector< unsigned char >& hash)
{
    GCSFilter::Element element(hash.size());
    for(int j=0;j<hash.size();j++)
    {
        element[j] = hash[j];
    }

    return filter->Match(element);
}

bool PyBIP158::MatchAny(std::vector< std::vector< unsigned char > >& hashes)
{
    GCSFilter::ElementSet elements;
    
    for (int i = 0; i < hashes.size(); ++i)
    {
        GCSFilter::Element element(hashes[i].size());
        for(int j=0;j<hashes[i].size();j++)
        {
            element[j] = hashes[i][j];
        }
        elements.insert(std::move(element));
    }
    
    return filter->MatchAny(elements);
}
