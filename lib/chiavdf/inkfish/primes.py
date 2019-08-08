try:
    from gmpy2 import is_strong_prp
except ImportError:
    is_strong_prp = None


def odd_primes_below_n(n):
    """ Returns a list of odd primes less than n. """
    sieve = [True] * (n // 2)
    for i in range(3, int(n ** 0.5) + 1, 2):
        if sieve[i // 2]:
            sieve[i * i // 2::i] = [False] * ((n-i*i-1)//(2*i)+1)
    return [2 * i + 1 for i in range(1, n//2) if sieve[i]]


POTENTIAL_WITNESSES = odd_primes_below_n(500)


def run_test_for_potential_nonprime_witness(a, d, n, r):
    if a % n == 0:
        return False
    x = pow(a, d, n)
    if x in (1, n-1):
        return False
    for _ in range(r - 1):
        x = pow(x, 2, n)
        if x == n - 1:
            return False
    return True


def miller_rabin_test(n, count=2):
    # see https://en.wikipedia.org/wiki/Miller%E2%80%93Rabin_primality_test#Computational_complexity
    if n == 2:
        return True

    if n & 1 == 0:
        return False

    r = 0
    d = n - 1
    while d & 1 == 0:
        r += 1
        d >>= 1

    assert d & 1 == 1
    assert (2 ** r) * d + 1 == n

    for _, a in zip(range(count), POTENTIAL_WITNESSES):
        if run_test_for_potential_nonprime_witness(a, d, n, r):
            return False
    return True


if is_strong_prp:
    def is_probable_prime(p):
        return is_strong_prp(p, 2)
else:
    def is_probable_prime(p):
        return miller_rabin_test(p)


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
