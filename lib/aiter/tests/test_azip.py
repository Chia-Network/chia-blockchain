import unittest


from aiter import azip, iter_to_aiter


from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_azip(self):
        i1 = ("abcdefgh")
        i2 = list(range(20))
        i3 = list(str(_) for _ in range(20))
        ai1 = iter_to_aiter(i1)
        ai2 = iter_to_aiter(i2)
        ai3 = iter_to_aiter(i3)
        ai = azip(ai1, ai2, ai3)
        r = run(get_n(ai))
        self.assertEqual(r, list(zip(i1, i2, i3)))
