import unittest


from aiter import preload_aiter, push_aiter

from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_preload_aiter(self):
        q = push_aiter()
        q.push(*list(range(1000)))
        q.stop()

        self.assertEqual(len(q), 1000)
        aiter = preload_aiter(50, q)

        self.assertEqual(len(q), 1000)

        r = run(get_n(aiter, 1))
        self.assertEqual(len(q), 949)
        self.assertEqual(r, [0])

        r = run(get_n(aiter, 10))
        self.assertEqual(r, list(range(1, 11)))
        self.assertEqual(len(q), 939)

        r = run(get_n(aiter))
        self.assertEqual(r, list(range(11, 1000)))
        self.assertEqual(len(q), 0)
