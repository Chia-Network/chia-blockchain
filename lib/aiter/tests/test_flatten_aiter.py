import unittest


from aiter import flatten_aiter, map_aiter, push_aiter


from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_flatten_aiter(self):
        q = push_aiter()
        fi = flatten_aiter(q)
        r = []
        q.push([0, 1, 2, 3])
        r.extend(run(get_n(fi, 3)))
        q.push([4, 5, 6, 7])
        r.extend(run(get_n(fi, 5)))
        q.stop()
        r.extend(run(get_n(fi)))
        self.assertEqual(r, list(range(8)))

    def test_make_simple_pipeline(self):
        q = push_aiter()
        aiter = flatten_aiter(flatten_aiter(q))
        q.push([
            (0, 0, 1, 0),
            (1, 1, 1, 1),
            (2, 0, 0, 1),
            (3, 1, 2, 0),
            (0, 0, 0, 7),
        ])
        r = run(get_n(aiter, 11))
        self.assertEqual(r, [0, 0, 1, 0, 1, 1, 1, 1, 2, 0, 0])
        r.extend(run(get_n(aiter, 8)))
        q.stop()
        r.extend(run(get_n(aiter)))
        self.assertEqual(r, [0, 0, 1, 0, 1, 1, 1, 1, 2, 0, 0, 1, 3, 1, 2, 0, 0, 0, 0, 7])

    def test_filter_pipeline(self):
        async def filter(item_list_of_lists):
            r = []
            for l1 in item_list_of_lists:
                for item in l1:
                    if item != 0:
                        r.append(item)
            return r

        TEST_CASE = [
            (0, 0, 0, 7),
            (5, 0, 0, 0),
            (0, 0, 1, 0),
            (1, 1, 1, 1),
            (2, 0, 0, 1),
            (3, 1, 2, 0),
        ]

        q = push_aiter()
        aiter = flatten_aiter(map_aiter(filter, q))
        q.push(TEST_CASE)
        q.stop()
        r = run(get_n(aiter, 12))
        r1 = [7, 5, 1, 1, 1, 1, 1, 2, 1, 3, 1, 2]
        self.assertEqual(r, r1)
