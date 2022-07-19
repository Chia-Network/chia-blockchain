from unittest import TestCase

from chia.types.blockchain_format.program import Program
from clvm.EvalError import EvalError
from clvm_tools.curry import uncurry
from clvm.operators import KEYWORD_TO_ATOM
from clvm_tools.binutils import assemble, disassemble


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

    def test_replace(self):
        p1 = Program.to([100, 200, 300])
        self.assertEqual(p1.replace(f=105), Program.to([105, 200, 300]))
        self.assertEqual(p1.replace(rrf=[301, 302]), Program.to([100, 200, [301, 302]]))
        self.assertEqual(p1.replace(f=105, rrf=[301, 302]), Program.to([105, 200, [301, 302]]))
        self.assertEqual(p1.replace(f=100, r=200), Program.to((100, 200)))

    def test_replace_conflicts(self):
        p1 = Program.to([100, 200, 300])
        self.assertRaises(ValueError, lambda: p1.replace(rr=105, rrf=200))

    def test_replace_conflicting_paths(self):
        p1 = Program.to([100, 200, 300])
        self.assertRaises(ValueError, lambda: p1.replace(ff=105))

    def test_replace_bad_path(self):
        p1 = Program.to([100, 200, 300])
        self.assertRaises(ValueError, lambda: p1.replace(q=105))
        self.assertRaises(ValueError, lambda: p1.replace(rq=105))


def check_idempotency(f, *args):
    prg = Program.to(f)
    curried = prg.curry(*args)

    r = disassemble(curried)
    f_0, args_0 = uncurry(curried)

    assert disassemble(f_0) == disassemble(f)
    assert disassemble(args_0) == disassemble(Program.to(list(args)))
    return r


def test_curry_uncurry():
    PLUS = KEYWORD_TO_ATOM["+"][0]
    f = assemble("(+ 2 5)")
    actual_disassembly = check_idempotency(f, 200, 30)
    assert actual_disassembly == f"(a (q {PLUS} 2 5) (c (q . 200) (c (q . 30) 1)))"

    f = assemble("(+ 2 5)")
    args = assemble("(+ (q . 50) (q . 60))")
    # passing "args" here wraps the arguments in a list
    actual_disassembly = check_idempotency(f, args)
    assert actual_disassembly == f"(a (q {PLUS} 2 5) (c (q {PLUS} (q . 50) (q . 60)) 1))"
