/**
Copyright (C) 2019 Markku Pulkkinen

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

#ifndef REDUCER_H
#define REDUCER_H

#include <algorithm>
#include <array>
#include <cmath>

#include "ClassGroup.h"

/** constants utilized in reduction algorithm */
namespace {
const int_fast64_t THRESH{1ul << 31};
const int_fast64_t EXP_THRESH{31};
} 

/**
 * @brief The Reducer class that does custom reduce operation for VDF 
 * repeated squaring algorithm. The implementation is based on
 * Akashnil VDF competition entry and further optimized for speed.
 */
class alignas(64) Reducer {
public:
  /**
   * @brief Reducer - constructs by using reference into cg context.
   */  
  Reducer(ClassGroupContext &ctx_) : ctx(ctx_) {}

  ~Reducer() {}

  /**
   * @brief run - runs reduction algorithm for cg context params
   */  
  inline void run() {
    while (!isReduced()) {
      int_fast64_t a, b, c;
      {
        int_fast64_t a_exp, b_exp, c_exp;
        mpz_get_si_2exp(a, a_exp, ctx.a);
        mpz_get_si_2exp(b, b_exp, ctx.b);
        mpz_get_si_2exp(c, c_exp, ctx.c);
        auto mm = std::minmax({a_exp, b_exp, c_exp});
        if (mm.second - mm.first > EXP_THRESH) {
          reducer();
          continue;
        }
        // Ensure a, b, c are shifted so that a : b : c ratios are same as
        // f.a : f.b : f.c. a, b, c will be used as approximations to f.a,
        // f.b, f.c
        int_fast64_t max_exp(++mm.second); // for safety vs overflow
        a >>= (max_exp - a_exp);
        b >>= (max_exp - b_exp);
        c >>= (max_exp - c_exp);
      }
      {
        int_fast64_t u, v, w, x;
        calc_uvwx(u, v, w, x, a, b, c);

        mpz_mul_si(ctx.faa, ctx.a, u * u);
        mpz_mul_si(ctx.fab, ctx.b, u * w);
        mpz_mul_si(ctx.fac, ctx.c, w * w);

        mpz_mul_si(ctx.fba, ctx.a, u * v << 1);
        mpz_mul_si(ctx.fbb, ctx.b, u * x + v * w);
        mpz_mul_si(ctx.fbc, ctx.c, w * x << 1);

        mpz_mul_si(ctx.fca, ctx.a, v * v);
        mpz_mul_si(ctx.fcb, ctx.b, v * x);
        mpz_mul_si(ctx.fcc, ctx.c, x * x);

        mpz_add(ctx.a, ctx.faa, ctx.fab);
        mpz_add(ctx.a, ctx.a, ctx.fac);

        mpz_add(ctx.b, ctx.fba, ctx.fbb);
        mpz_add(ctx.b, ctx.b, ctx.fbc);

        mpz_add(ctx.c, ctx.fca, ctx.fcb);
        mpz_add(ctx.c, ctx.c, ctx.fcc);
      }
    }
  }

private:

  inline void signed_shift(uint64_t op, int64_t shift, int_fast64_t &r) {
    if (shift > 0)
      r = static_cast<int64_t>(op << shift);
    else if (shift <= -64)
      r = 0;
    else
      r = static_cast<int64_t>(op >> (-shift));
  }

  inline void mpz_get_si_2exp(int_fast64_t &r, int_fast64_t &exp,
                              const mpz_t op) {
    // Return an approximation x of the large mpz_t op by an int64_t and the
    // exponent e adjustment. We must have (x * 2^e) / op = constant
    // approximately.
    int_fast64_t size(static_cast<long>(mpz_size(op)));
    uint_fast64_t last(mpz_getlimbn(op, (size - 1)));
    int_fast64_t lg2 = exp = ((63 - __builtin_clzll(last)) + 1);
    signed_shift(last, (63 - exp), r);
    if (size > 1) {
      exp += (size - 1) * 64;
      uint_fast64_t prev(mpz_getlimbn(op, (size - 2)));
      int_fast64_t t;
      signed_shift(prev, -1 - lg2, t);
      r += t;
    }
    if (mpz_sgn(op) < 0)
      r = -r;
  }

  inline bool isReduced() {
    int a_b(mpz_cmpabs(ctx.a, ctx.b));
    int c_b(mpz_cmpabs(ctx.c, ctx.b));
    if (a_b < 0 || c_b < 0)
      return false;

    int a_c(mpz_cmp(ctx.a, ctx.c));
    if (a_c > 0) {
      mpz_swap(ctx.a, ctx.c);
      mpz_neg(ctx.b, ctx.b);
    } else if (a_c == 0 && mpz_sgn(ctx.b) < 0) {
      mpz_neg(ctx.b, ctx.b);
    }
    return true;
  }

  inline void reducer() {
    // (c + b)/2c == (1 + (b/c))/2 -> s
    mpz_mdiv(ctx.r, ctx.b, ctx.c);
    mpz_add_ui(ctx.r, ctx.r, 1);
    mpz_div_2exp(ctx.s, ctx.r, 1);
    // cs -> m
    mpz_mul(ctx.m, ctx.c, ctx.s);
    // 2cs -> r
    mpz_mul_2exp(ctx.r, ctx.m, 1);
    // (cs - b) -> m
    mpz_sub(ctx.m, ctx.m, ctx.b);

    // new b = -b + 2cs
    mpz_sub(ctx.b, ctx.r, ctx.b);
    // new a = c, c = a
    mpz_swap(ctx.a, ctx.c);
    // new c = c + cs^2 - bs ( == c + (s * ( cs - b)))
    mpz_addmul(ctx.c, ctx.s, ctx.m);
  }

  inline void calc_uvwx(int_fast64_t &u, int_fast64_t &v, int_fast64_t &w,
                        int_fast64_t &x, int_fast64_t &a, int_fast64_t &b,
                        int_fast64_t &c) {
    // We must be very careful about overflow in the following steps
    int below_threshold;
    int_fast64_t u_{1}, v_{0}, w_{0}, x_{1};
    int_fast64_t a_, b_, s;
    do {
      u = u_;
      v = v_;
      w = w_;
      x = x_;

      s = b >= 0 ? (b+c) / (c<<1) : - (-b+c) / (c<<1);

      a_ = a;
      b_ = b;
      // cs = c * s;

      // a = c
      a = c;
      // b = -b + 2cs
      b = -b + (c * s << 1);
      // c = a + cs^2 - bs
      c = a_ - s * (b_ - c * s);

      u_ = v;
      v_ = -u + s * v;
      w_ = x;
      x_ = -w + s * x;

      // The condition (abs(v_) | abs(x_)) <= THRESH protects against
      // overflow
      below_threshold = (abs(v_) | abs(x_)) <= THRESH ? 1 : 0;
    } while (below_threshold && a > c && c > 0);

    if (below_threshold) {
      u = u_;
      v = v_;
      w = w_;
      x = x_;
    }
  }

  ClassGroupContext &ctx;
};

#endif // REDUCER_H
