#ifndef INCLUDE_H
#define INCLUDE_H

#ifdef NDEBUG
    #undef NDEBUG
#endif

#if VDF_MODE==0
    #define NDEBUG
#endif

#include <iostream>
#include <string>
#include <vector>
#include <cstdio>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <array>
#include <sstream>
#include <fstream>
#include <unistd.h>
#include <cassert>
#include <iomanip>
#include <set>
#include <random>
#include <limits>
#include <cstdlib>
#include <map>
#include <functional>
#include <algorithm>
#include <cstdint>
#include <deque>
#include <cfenv>
#include <ctime>
#include <thread>
#include "generic.h"
#include <gmpxx.h>

using namespace std;
using namespace generic;

typedef uint8_t uint8;
typedef uint16_t uint16;
typedef uint32_t uint32;
typedef uint64_t uint64;
typedef int8_t int8;
typedef int16_t int16;
typedef int32_t int32;
typedef int64_t int64;
typedef unsigned __int128 uint128;
typedef __int128 int128;

#define todo
#define USED __attribute__((used))

#endif // INCLUDE_H
