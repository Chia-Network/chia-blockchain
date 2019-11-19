import unittest


from aiter import iter_to_aiter, gated_aiter

from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_gated_aiter(self):
        ai = iter_to_aiter(range(3000000000))
        aiter = gated_aiter(ai)
        aiter.push(9)
        r = run(get_n(aiter, 3))
        r.extend(run(get_n(aiter, 4)))
        aiter.push(11)
        aiter.stop()
        r.extend(run(get_n(aiter)))
        self.assertEqual(r, list(range(20)))
