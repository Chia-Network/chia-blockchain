import itertools
import math


def gcd(*args):
    """
    Generalize math.gcd to take more than two inputs.
    """
    items = list(args)
    while len(items) > 1:
        items.append(math.gcd(items.pop(), items.pop()))
    return items[0]


def extended_gcd(a, b):
    """
    Return r, s, t such that gcd(a, b) = r = a * s + b * t
    """
    r0, r1 = a, b
    s0, s1, t0, t1 = 1, 0, 0, 1
    if r0 > r1:
        r0, r1, s0, s1, t0, t1 = r1, r0, t0, t1, s0, s1
    while r1 > 0:
        q, r = divmod(r0, r1)
        r0, r1, s0, s1, t0, t1 = r1, r, s1, s0 - q * s1, t1, t0 - q * t1
    return r0, s0, t0


def inverse(a, p):
    """
    Return the inverse of a mod p, ie. a value v such that (a * v) % p == 1
    """
    if a < 0:
        return -inverse(-a, p)
    r, s, _ = extended_gcd(a, p)
    if r == 1:
        return s


def reduce_equivalencies(a0, m0, a1, m1):
    """
    Reduce two equivalencies x % m0 == a0, x % m1 == a1 into one: x % m == a.
    Returns a, m.
    """
    r, s, t = extended_gcd(m0, m1)
    m = m0 * m1 // r
    return ((a0 * m1 * t + a1 * m0 * s) // r) % m, m, ((a0 - a1) % r == 0)


def crt(a_list, m_list):
    """
    Chinese Remainder Theorem.

    Solves for a simultaneous list of equations.
    Returns a value x that solves for
      x % m == a for (a, m) in zip(a_list, m_list)
    """
    a0, m0 = a_list[0], m_list[0]
    for a, m in zip(a_list[1:], m_list[1:]):
        a0, m0, worked = reduce_equivalencies(a0, m0, a, m)
        if not worked:
            return None
    return a0


def square_root_mod_p(a, p):
    """
    Iterator yielding values v s.t. v * v % p == a
    There will be 0 or 2 answers.
    """
    # see http://course1.winona.edu/eerrthum/13Spring/SquareRoots.pdf
    a %= p
    if p == 2:
        yield a & 1
        return
    if p == 4:
        a &= 3
        if a == 0:
            yield 0
        if a == 1:
            yield 1
            yield 3
        return
    if p & 3 == 3:
        s1 = pow(a, (p + 1) >> 2, p)
        if s1 * s1 % p == a:
            yield s1
            yield p - s1
        return
    if p & 7 == 5:
        k = (p - 5) >> 3
        v1 = pow(a, (p-1) >> 2, p)
        v2 = pow(a, k+1, p)
        if v1 == 1:
            yield v2
            yield p - v2
        elif v1 == p-1:
            r = (v2 * pow(2, 2*k+1, p)) % p
            yield r
            yield p - r
        return
    else:
        raise ValueError("not implemented for prime %d" % p)


def square_root_mod_p_list(a, prime_factors):
    """
    Iterator yielding values v s.t. v * v % N == a.
    There may be no solutions.
    """
    for a_list in itertools.product(*[square_root_mod_p(a, _)
                                      for _ in prime_factors]):
        yield crt(a_list, prime_factors)


def solve_mod(a, b, m):
    """
    Solve ax == b mod m for x.

    Return s, t where x = s + k * t for integer k yields all solutions.
    """
    g, d, e = extended_gcd(a, m)
    q, r = divmod(b, g)
    if r != 0:
        raise ValueError("no solution to %dx = %d mod %d" % (a, b, m))

    assert b == q * g
    return (q * d) % m, m // g


"""
Copyright 2018 Chia Network Inc

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
