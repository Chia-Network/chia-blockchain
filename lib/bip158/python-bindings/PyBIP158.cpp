// Copyright 2018 Chia Network Inc
  
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at

//    http://www.apache.org/licenses/LICENSE-2.0

// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "PyBIP158.h"

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

PyBIP158::PyBIP158(std::vector< unsigned char > & encoded_filter)
{
    filter=new GCSFilter({0, 0, 20, 1 << 20}, encoded_filter);
}

const std::vector<unsigned char>& PyBIP158::GetEncoded()
{
    return filter->GetEncoded();
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
