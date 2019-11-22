import unittest


from aiter import push_aiter


from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_push_aiter(self):
        q = push_aiter()
        self.assertEqual(len(q), 0)
        q.push(5, 4)
        self.assertEqual(len(q), 2)
        q.push(3)
        self.assertEqual(len(q), 3)
        q.stop()
        self.assertRaises(ValueError, lambda: q.push(2))
        results = list(q.available_iter())
        self.assertEqual(results, [5, 4, 3])
        results = run(get_n(q))
        self.assertEqual(results, [5, 4, 3])
