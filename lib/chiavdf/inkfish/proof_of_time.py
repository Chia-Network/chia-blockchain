import hashlib
import math
from multiprocessing import Pipe, Process

from lib.chiavdf.inkfish.classgroup import ClassGroup
from lib.chiavdf.inkfish.iterate_squarings import iterate_squarings
from lib.chiavdf.inkfish import proof_pietrzak
from lib.chiavdf.inkfish import proof_wesolowski


def generate_r_value(x, y, sqrt_mu, int_size_bits):
    """creates an r value by hashing the inputs"""
    if isinstance(x, ClassGroup):
        s = serialize_proof([x, y, sqrt_mu])
    else:
        int_size = int_size_bits // 8
        s = (x.to_bytes(int_size, "big", signed=False) +
             y.to_bytes(int_size, "big", signed=False) +
             sqrt_mu.to_bytes(int_size, "big", signed=False))
    b = hashlib.sha256(s).digest()
    return int.from_bytes(b[:16], "big")


def serialize_proof(proof):
    return b''.join(el.serialize() for el in proof)


def deserialize_proof(proof_blob,  discriminant):
    int_size = (discriminant.bit_length() + 16) >> 4
    proof_arr = [proof_blob[_:_ + 2 * int_size]
                 for _ in range(0, len(proof_blob), 2*int_size)]
    return [ClassGroup.from_bytes(blob, discriminant) for blob in proof_arr]


def create_proof_of_time_wesolowski(discriminant, x, iterations, int_size_bits):
    L, k, _ = proof_wesolowski.approximate_parameters(iterations)

    powers_to_calculate = [i * k * L for i in range(0, math.ceil(iterations/(k*L)) + 1)]
    powers_to_calculate += [iterations]
    powers = iterate_squarings(x, powers_to_calculate)

    y = powers[iterations]
    identity = ClassGroup.identity_for_discriminant(discriminant)
    proof = proof_wesolowski.generate_proof(identity, x, y, iterations, k, L, powers)
    return y, serialize_proof([proof])


def create_proof_of_time_nwesolowski(discriminant, x, iterations,
                                     int_size_bits, depth_limit, depth=0):
    """
    Returns a serialized proof blob, using n_wesolowski
                     iterations_1                        iterations_2      proof_2
     [----------------------------------------------|---------------------][-----]
                                                    |---------------------]
                                                            proof_1
    """
    L, k, w = proof_wesolowski.approximate_parameters(iterations)

    iterations_1 = (iterations * w) // (w + 1)
    iterations_2 = iterations - iterations_1

    identity = ClassGroup.identity_for_discriminant(discriminant)

    powers_to_calculate = [i * k * L for i in range(0, math.ceil(iterations_1/(k*L)) + 1)]
    powers_to_calculate += [iterations_1]

    powers = iterate_squarings(x, powers_to_calculate)
    y_1 = powers[iterations_1]

    receive_con, send_con = Pipe(False)
    p = Process(target=proof_wesolowski.generate_proof,
                args=(identity, x, y_1, iterations_1, k, L, powers, send_con))
    p.start()

    if (depth < depth_limit - 1):
        y_2, proof_2 = create_proof_of_time_nwesolowski(discriminant, y_1, iterations_2, int_size_bits,
                                                        depth_limit, depth + 1)
    else:
        y_2, proof_2 = create_proof_of_time_wesolowski(discriminant, y_1, iterations_2, int_size_bits)

    proof = ClassGroup.from_bytes(receive_con.recv_bytes(), discriminant)
    p.join()

    return y_2, proof_2 + iterations_1.to_bytes(8, byteorder="big") + serialize_proof([y_1, proof])


def create_proof_of_time_pietrzak(discriminant, x, iterations, int_size_bits):
    """
    Returns a serialized proof blob.
    """
    delta = 8

    powers_to_calculate = proof_pietrzak.cache_indeces_for_count(iterations)
    powers = iterate_squarings(x, powers_to_calculate)
    y = powers[iterations]
    proof = proof_pietrzak.generate_proof(x, iterations, delta, y, powers,
                                          x.identity(), generate_r_value, int_size_bits)

    return y.serialize(), serialize_proof(proof)


def check_proof_of_time_wesolowski(discriminant, x, proof_blob,
                                   iterations, int_size_bits):
    # we add one bit for sign, then 15 bits to round up to the next word
    # BRAIN DAMAGE: can we round to a byte instead of a word?
    int_size = (int_size_bits + 16) >> 4
    result_bytes = proof_blob[: (2 * int_size)]
    proof_bytes = proof_blob[(2 * int_size):]

    proof = deserialize_proof(proof_bytes, discriminant)

    y = ClassGroup.from_bytes(result_bytes, discriminant)
    try:
        return proof_wesolowski.verify_proof(x, y, proof[0], iterations)
    except Exception:
        return False

def check_proof_of_time_nwesolowski(discriminant, x, proof_blob,
                                    iterations, int_size_bits, recursion):
    int_size = (int_size_bits + 16) >> 4
    new_proof_blob = proof_blob[:4 * int_size]
    iter_list = []
    for i in range(4 * int_size, len(proof_blob), 4 * int_size + 8):
        iter_list.append(int.from_bytes(proof_blob[i : (i + 8)], byteorder="big"))
        new_proof_blob = new_proof_blob + proof_blob[(i + 8): (i + 8 + 4 * int_size)]

    return check_proof_of_time_nwesolowski_inner(discriminant, x, new_proof_blob,
                                    iterations, int_size_bits, iter_list, recursion)
    

def check_proof_of_time_nwesolowski_inner(discriminant, x, proof_blob,
                                    iterations, int_size_bits, iter_list, recursion):
    """
    Recursive verification function for nested wesolowski. The proof blob
    includes the output of the VDF, along with the proof. The following
    table gives an example of the recursive calls for a depth of 3.

    x   |  proof_blob
    ---------------------------------------------
    x   |  y3, proof3, y2, proof2, y1, proof1
    y1  |  y3, proof3, y2, proof2
    y2  |  y3, proof3
    """
    int_size = (int_size_bits + 16) >> 4
    result_bytes = proof_blob[: (2 * int_size)]
    proof_bytes = proof_blob[(2 * int_size):]
    y = ClassGroup.from_bytes(result_bytes, discriminant)

    proof = deserialize_proof(proof_bytes, discriminant)
    if recursion * 2 + 1 != len(proof):
        raise ValueError("Invalid n-wesolowski proof length.")

    try:
        if len(proof) == 1:
            return proof_wesolowski.verify_proof(x, y, proof[-1], iterations)
        else:
            assert(len(proof) % 2 == 1 and len(proof) > 2)
            _, _, w = proof_wesolowski.approximate_parameters(iterations)

            iterations_1 = iter_list[-1]
            iterations_2 = iterations - iterations_1

            ver_outer = proof_wesolowski.verify_proof(x, proof[-2],
                                                      proof[-1], iterations_1)
            return ver_outer and check_proof_of_time_nwesolowski_inner(discriminant, proof[-2],
                                                                 serialize_proof([y] + proof[:-2]),
                                                                 iterations_2, int_size_bits, iter_list[:-1], recursion-1)

    except Exception:
        return False


def check_proof_of_time_pietrzak(discriminant, x, proof_blob, iterations, int_size_bits):
    int_size = (int_size_bits + 16) >> 4
    result_bytes = proof_blob[: (2 * int_size)]
    proof_bytes = proof_blob[(2 * int_size):]

    proof = deserialize_proof(proof_bytes, discriminant)

    y = ClassGroup.from_bytes(result_bytes, discriminant)
    try:
        return proof_pietrzak.verify_proof(x, y, proof, iterations, 8,
                                           generate_r_value, int_size_bits)
    except Exception:
        return False


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