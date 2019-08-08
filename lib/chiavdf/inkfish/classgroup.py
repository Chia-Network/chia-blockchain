from . import mod


class ClassGroup(tuple):
    @classmethod
    def identity_for_discriminant(class_, d):
        return class_.from_ab_discriminant(1, 1, d)

    @classmethod
    def from_ab_discriminant(class_, a, b, discriminant):
        assert discriminant < 0
        assert discriminant % 4 == 1
        c = (b * b - discriminant) // (4 * a)
        p = class_(a, b, c).reduced()
        assert p.discriminant() == discriminant
        return p

    @classmethod
    def from_bytes(class_, bytearray, discriminant):
        int_size = (discriminant.bit_length() + 16) >> 4
        a = int.from_bytes(bytearray[0:int_size], "big", signed=True)
        b = int.from_bytes(bytearray[int_size:], "big", signed=True)
        return ClassGroup(a, b, (b**2 - discriminant)//(4*a))

    def __new__(self, a, b, c):
        return tuple.__new__(self, (a, b, c))

    def __init__(self, a, b, c):
        super(ClassGroup, self).__init__()
        self._discriminant = None

    def __mul__(self, other):
        return self.multiply(other)

    def __hash__(self):
        a, b, c = self.reduced()
        return hash((a, b, c))

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
            s = (c + b) // (c + c)
            a, b, c = c, -b + 2 * s * c, c * s * s - b * s + a
        return self.__class__(a, b, c).normalized()

    def normalized(self):
        a, b, c = self
        if -a < b <= a:
            return self
        r = (a - b) // (2 * a)
        b, c = b + 2 * r * a, a * r * r + b * r + c
        return self.__class__(a, b, c)

    def serialize(self):
        r = self.reduced()
        int_size_bits = int(self.discriminant().bit_length())
        int_size = (int_size_bits + 16) >> 4
        return b''.join([x.to_bytes(int_size, "big", signed=True)
                         for x in [r[0], r[1]]])

    def __eq__(self, other):
        return tuple(self.reduced()) == tuple(ClassGroup(*other).reduced())

    def __ne__(self, other):
        return not self.__eq__(other)

    def __pow__(self, n):
        x = self
        items_prod = self.identity()
        while n > 0:
            if n & 1:
                items_prod *= x
            x = x.square()
            n >>= 1
        return items_prod

    def inverse(self):
        a, b, c = self
        return self.__class__(a, -b, c)

    def multiply(self, other):
        """
        An implementation of form composition as documented by "Explaining composition".
        """
        a1, b1, c1 = self.reduced()
        a2, b2, c2 = other.reduced()

        g = (b2 + b1) // 2
        h = (b2 - b1) // 2

        w = mod.gcd(a1, a2, g)

        j = w
        r = 0
        s = a1 // w
        t = a2 // w
        u = g // w

        # solve these equations for k, l, m
        """
        k * t - l * s = h
        k * u - m * s = c2
        l * u - m * t = c1
        """

        """
        solve
        (tu)k - (hu + sc) = 0 mod st
        k = (- hu - sc) * (tu)^-1
        """

        k_temp, constant_factor = mod.solve_mod(t * u, h * u + s * c1, s * t)
        n, constant_factor_2 = mod.solve_mod(t * constant_factor, h - t * k_temp, s)
        k = k_temp + constant_factor * n
        l = (t * k - h) // s
        m = (t * u * k - h * u - s * c1) // (s * t)
        #assert m * s * t == t * u * k - h * u - s * c1
        #assert u * l == t * m + c1
        #assert (t * u * k - h * u - s * c1) % (s * t) == 0

        a3 = s * t - r * u
        b3 = (j * u + m * r) - (k * t + l * s)
        c3 = k * l - j * m
        return self.__class__(a3, b3, c3).reduced()

    def square(self):
        """
        A rewrite of multiply for squaring.
        """
        a1, b1, c1 = self.reduced()

        g = b1
        h = 0

        w = mod.gcd(a1, g)

        j = w
        r = 0
        s = a1 // w
        t = s
        u = g // w

        # solve these equations for k, l, m
        """
        k * t - l * s = h
        k * u - m * s = c2
        l * u - m * t = c1
        """

        """
        solve
        (tu)k - (hu + sc) = 0 mod st
        k = (- hu - sc) * (tu)^-1
        """

        k_temp, constant_factor = mod.solve_mod(t * u, h * u + s * c1, s * t)
        n, constant_factor_2 = mod.solve_mod(t * constant_factor, h - t * k_temp, s)
        k = k_temp + constant_factor * n
        m = (t * u * k - h * u - s * c1) // (s * t)
        # assert m * s * t == t * u * k - h * u - s * c1
        l = (t * m + c1) // u
        # assert u * l == t * m + c1
        # assert (t * u * k - h * u - s * c1) % (s * t) == 0

        a3 = s * t - r * u
        b3 = (j * u + m * r) - (k * t + l * s)
        c3 = k * l - j * m
        return self.__class__(a3, b3, c3).reduced()


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
