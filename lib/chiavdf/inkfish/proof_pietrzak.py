import math


def approximate_i(T):
    """Performs the approximation from the paper to select a resonable cache
     size"""
    x = (T / 16) * math.log(2)
    w = math.log(x) - math.log(math.log(x)) + 0.25
    return round(w / (2 * math.log(2)))


def sum_combinations(numbers):
    """Add all combinations of the given numbers, of at least one number"""
    combinations = [0]
    for element in numbers:
        new_combinations = list(combinations)
        for element2 in combinations:
            new_combinations.append(element + element2)
        combinations = new_combinations
    combinations.remove(0)  # Remove 0
    return combinations


def cache_indeces_for_count(T):
    i = approximate_i(T)

    # Since T might not be a power of 2, we have to divide and
    # add 1 if odd, to calculate all of the indeces that we will cache
    curr_T = T
    intermediate_Ts = []
    for _ in range(i):
        curr_T >>= 1
        intermediate_Ts.append(curr_T)
        if curr_T & 1 == 1:
            curr_T += 1
    cache_indeces = sorted([s for s in
                            sum_combinations(intermediate_Ts)])
    cache_indeces.append(T)
    return cache_indeces


def calculate_final_T(T, delta):
    # Based on the number of rounds to skip, calculates the target T that
    # we must look for, in order to stop the iteration of the loop
    curr_T = T
    Ts = []
    while curr_T != 2:
        Ts.append(curr_T)
        curr_T = curr_T >> 1
        if curr_T & 1 == 1:
            curr_T += 1
    Ts += [2, 1]       # Add 2, 1 for completion
    return Ts[-delta]  # return the correct T to look for


def generate_proof(x, T, delta, y, powers, identity,
                   generate_r_value, int_size_bits):
    """
    Generate the proof.
    Returns a list of elements derived by operations on x.
    """
    # Only even values work, since we need to do T/2
    if T % 2 != 0:
        raise ValueError("T must be even")
    i = approximate_i(T)
    mus = []
    rs = []    # random values generated using hash function
    x_p = [x]  # x prime in the paper
    y_p = [y]  # y prime in the paper

    curr_T = T
    Ts = []    # List of all of the Ts being used, T, then T/2, etc

    final_T = calculate_final_T(T, delta)

    round_index = 0
    while curr_T != final_T:
        assert(curr_T & 1 == 0)
        half_T = curr_T >> 1
        Ts.append(half_T)
        denominator = 1 << (round_index + 1)  # T/2 for initial round

        # use cache for first i rounds for fast computation
        if (round_index < i):
            mu = identity  # Compute product below

            # Get each of the cached terms, for round 3, denominator is 8.
            # The terms are T/8, 3T/8 5T/8 7T/8. If not a power of two, we
            # will not use exactly 3T/8
            for numerator in range(1, denominator, 2):
                # Number of bits in the denominator, for example 3
                # Don't include last r, since not computed yet
                num_bits = denominator.bit_length() - 2

                # Find out which rs to multiply for this term, based on bit
                # composition. For example, for 5T/8, 5 is 101 in bits, so
                # multiply r1 (but not r2)
                rs_to_mult = [
                        1 if numerator & (1 << (b + 1))
                        else rs[num_bits - b - 1]
                        for b in range(num_bits-1, -1, -1)]

                # Multiply rs together
                r_prod = 1
                for r in rs_to_mult:
                    r_prod *= r

                # Calculates the exact cached power T to use
                Ts_to_add = [
                    Ts[num_bits - b - 1] if numerator & (1 << (b + 1)) else 0
                    for b in range(num_bits)]

                T_sum = half_T
                for t in Ts_to_add:
                    T_sum += t

                mu_component = powers[T_sum]

                mu = mu * pow(mu_component, r_prod)
            mus.append(mu)
        else:
            # Compute for rounds i + 1 until the end, for low cache storage
            mu = x_p[-1]
            for _ in range(half_T):
                mu = pow(mu, 2)

            mus.append(mu)

        rs.append(generate_r_value(x, y, mus[-1], int_size_bits))
        x_p.append(pow(x_p[-1], rs[-1]) * mu)
        y_p.append(pow(mu, rs[-1]) * y_p[-1])

        # Compute the new T, and y. If T is odd, make it even, and adjust
        # the y_p accordingly, so that y_p = x_p ^ (2 ^ curr_T)
        curr_T = curr_T >> 1
        if curr_T & 1 == 1:
            curr_T += 1
            y_p[-1] = pow(y_p[-1], 2)
        round_index += 1

    assert(pow(y_p[-1], 1) == pow(x_p[-1], 1 << final_T))
    return mus


def verify_proof(x_initial, y_initial, proof, T, delta,
                 generate_r_value, int_size_bits):
    # Only even values work, since we need to do T/2
    if T % 2 != 0:
        raise ValueError("T must be even")
    mu = None
    x = x_initial
    y = y_initial

    final_T = calculate_final_T(T, delta)
    curr_T = T
    for mu in proof:
        assert(curr_T & 1 == 0)
        r = generate_r_value(x_initial, y_initial, mu, int_size_bits)
        x = pow(x, r) * mu
        y = pow(mu, r) * y

        # To guarantee even Ts, add 1 if necessary
        curr_T >>= 1
        if curr_T & 1 == 1:
            curr_T += 1
            y = pow(y, 2)

    return pow(x, 1 << final_T) == y


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
