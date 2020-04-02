from chiavdf import verify_wesolowski


class ClassGroup(tuple):
    @classmethod
    def identity_for_discriminant(class_, d):
        return class_.from_ab_discriminant(1, 1, d)

    @classmethod
    def from_ab_discriminant(class_, a, b, discriminant):
        if discriminant >= 0:
            raise ValueError("Positive discriminant.")
        if discriminant % 4 != 1:
            raise ValueError("Invalid discriminant mod 4.")
        if a == 0:
            raise ValueError("a can't be 0.")
        c = (b * b - discriminant) // (4 * a)
        p = class_((a, b, c)).reduced()
        if p.discriminant() != discriminant:
            raise ValueError("No classgroup element given the discriminant.")
        return p

    @classmethod
    def from_bytes(class_, bytearray, discriminant):
        int_size = (discriminant.bit_length() + 16) >> 4
        a = int.from_bytes(bytearray[0:int_size], "big", signed=True)
        b = int.from_bytes(bytearray[int_size:], "big", signed=True)
        return class_.from_ab_discriminant(a, b, discriminant)

    def __new__(cls, t):
        a, b, c = t
        return tuple.__new__(cls, (a, b, c))

    def __init__(self, t):
        a, b, c = t
        super(ClassGroup, self).__init__()
        self._discriminant = None

    def identity(self):
        return self.identity_for_discriminant(self.discriminant())

    def discriminant(self):
        if self._discriminant is None:
            a, b, c = self
            self._discriminant = b * b - 4 * a * c
        return self._discriminant

    def reduced(self):
        a, b, c = self.normalized()
        while a > c or (a == c and b < 0):
            if c == 0:
                raise ValueError("Can't reduce the form.")
            s = (c + b) // (c + c)
            a, b, c = c, -b + 2 * s * c, c * s * s - b * s + a
        return self.__class__((a, b, c)).normalized()

    def normalized(self):
        a, b, c = self
        if -a < b <= a:
            return self
        r = (a - b) // (2 * a)
        b, c = b + 2 * r * a, a * r * r + b * r + c
        return self.__class__((a, b, c))

    def serialize(self):
        r = self.reduced()
        int_size_bits = int(self.discriminant().bit_length())
        int_size = (int_size_bits + 16) >> 4
        return b"".join(
            [x.to_bytes(int_size, "big", signed=True) for x in [r[0], r[1]]]
        )


def deserialize_proof(proof_blob, discriminant):
    int_size = (discriminant.bit_length() + 16) >> 4
    proof_arr = [
        proof_blob[_ : _ + 2 * int_size]
        for _ in range(0, len(proof_blob), 2 * int_size)
    ]
    return [ClassGroup.from_bytes(blob, discriminant) for blob in proof_arr]


def check_proof_of_time_nwesolowski(
    discriminant, x, proof_blob, iterations, int_size_bits, depth
):
    """
    Check the nested wesolowski proof. The proof blob
    includes the output of the VDF, along with the proof. The following
    table gives an example of the checks for a depth of 2.

    x   |  proof_blob
    ---------------------------------------------
    x   |  y3, proof3, y2, proof2, y1, proof1
    y1  |  y3, proof3, y2, proof2
    y2  |  y3, proof3
    """

    try:
        int_size = (int_size_bits + 16) >> 4
        if len(proof_blob) != 4 * int_size + depth * (8 + 4 * int_size):
            return False
        new_proof_blob = proof_blob[: 4 * int_size]
        iter_list = []
        for i in range(4 * int_size, len(proof_blob), 4 * int_size + 8):
            iter_list.append(int.from_bytes(proof_blob[i : (i + 8)], byteorder="big"))
            new_proof_blob = (
                new_proof_blob + proof_blob[(i + 8) : (i + 8 + 4 * int_size)]
            )
        proof_blob = new_proof_blob

        result_bytes = proof_blob[: (2 * int_size)]
        proof_bytes = proof_blob[(2 * int_size) :]
        y = ClassGroup.from_bytes(result_bytes, discriminant)

        proof = deserialize_proof(proof_bytes, discriminant)
        if depth * 2 + 1 != len(proof):
            return False

        for _ in range(depth):
            iterations_1 = iter_list[-1]
            if not verify_wesolowski(
                str(discriminant),
                str(x[0]),
                str(x[1]),
                str(proof[-2][0]),
                str(proof[-2][1]),
                str(proof[-1][0]),
                str(proof[-1][1]),
                iterations_1,
            ):
                return False
            x = proof[-2]
            iterations = iterations - iterations_1
            proof = proof[:-2]
            iter_list = iter_list[:-1]

        return verify_wesolowski(
            str(discriminant),
            str(x[0]),
            str(x[1]),
            str(y[0]),
            str(y[1]),
            str(proof[-1][0]),
            str(proof[-1][1]),
            iterations,
        )
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
