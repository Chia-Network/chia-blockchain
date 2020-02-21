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

#ifndef BIP158_H
#define BIP158_H

#include <blockfilter.h>

class PyBIP158
{
public:
    GCSFilter *filter;

public:

    PyBIP158(std::vector< std::vector< unsigned char > >& hashes);
    PyBIP158(std::vector< unsigned char > & encoded_filter);
    const std::vector<unsigned char>& GetEncoded();
    ~PyBIP158();
    
    bool Match(std::vector< unsigned char >& hash);
    bool MatchAny(std::vector< std::vector< unsigned char > >& hashes);
};

#endif // BIP158_H
