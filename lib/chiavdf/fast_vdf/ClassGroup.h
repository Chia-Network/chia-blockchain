/**
Copyright (C) 2018 Markku Pulkkinen

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
**/

#ifndef CLASSGROUP_H
#define CLASSGROUP_H

#include <cstdint>
#include "gmp.h"

/**
 * @brief The ClassGroup data struct for VDF variables a, b, c and discriminant.
 * Optimal size because it fits into single entry of 64 byte wide cache line.
 */
struct alignas(64) ClassGroup {
  mpz_t a;
  mpz_t b;
  mpz_t c;
  mpz_t d;
};

/**
 * @brief ClassGroupContext struct - placeholder for variables
 * in classgroup arithmetic operations. Uses four cache
 * line entries, 256 bytes.
 */
struct alignas(64) ClassGroupContext {
  mpz_t a;
  mpz_t b;
  mpz_t c;
  mpz_t mu;

  mpz_t m;
  mpz_t r;
  mpz_t s;
  mpz_t faa;

  mpz_t fab;
  mpz_t fac;
  mpz_t fba;
  mpz_t fbb;

  mpz_t fbc;
  mpz_t fca;
  mpz_t fcb;
  mpz_t fcc;

  ClassGroupContext(uint32_t numBits = 4096) {
    mpz_init2(a, numBits);
    mpz_init2(b, numBits);
    mpz_init2(c, numBits);
    mpz_init2(mu, numBits);
    mpz_init2(m, numBits);
    mpz_init2(r, numBits);
    mpz_init2(s, numBits);
    mpz_init2(faa, numBits);
    mpz_init2(fab, numBits);
    mpz_init2(fac, numBits);
    mpz_init2(fba, numBits);
    mpz_init2(fbb, numBits);
    mpz_init2(fbc, numBits);
    mpz_init2(fca, numBits);
    mpz_init2(fcb, numBits);
    mpz_init2(fcc, numBits);
  }

  ~ClassGroupContext() {
    mpz_clears(a, b, c, mu, m, r, s, faa, fab, fac, fba, fbb, fbc, fca, fcb,
               fcc, NULL);
  }
};

#endif // CLASSGROUP_H
