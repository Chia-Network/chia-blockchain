from unittest import TestCase

from chia.types.blockchain_format.program import Program
from clvm.EvalError import EvalError


class TestProgram(TestCase):
    def test_at(self):
        p = Program.to([10, 20, 30, [15, 17], 40, 50])

        self.assertEqual(p.first(), p.at("f"))
        self.assertEqual(Program.to(10), p.at("f"))

        self.assertEqual(p.rest(), p.at("r"))
        self.assertEqual(Program.to([20, 30, [15, 17], 40, 50]), p.at("r"))

        self.assertEqual(p.rest().rest().rest().first().rest().first(), p.at("rrrfrf"))
        self.assertEqual(Program.to(17), p.at("rrrfrf"))

        self.assertRaises(ValueError, lambda: p.at("q"))
        self.assertRaises(EvalError, lambda: p.at("ff"))
