import asyncio
import unittest


from aiter import map_aiter, push_aiter


from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_asyncmap(self):

        def make_async_transformation_f(results):
            async def async_transformation_f(item):
                results.append(item)
                return item + 1
            return async_transformation_f

        results = []
        q = push_aiter()
        q.push(5, 4, 3)
        q.stop()
        r = list(q.available_iter())
        self.assertEqual(r, [5, 4, 3])
        aiter = map_aiter(make_async_transformation_f(results), q)
        r = run(get_n(aiter))
        self.assertEqual(r, [6, 5, 4])
        self.assertEqual(results, [5, 4, 3])

    def test_syncmap(self):

        def make_sync_transformation_f(results):
            def sync_transformation_f(item):
                results.append(item)
                return item + 1
            return sync_transformation_f

        results = []
        q = push_aiter()
        q.push(5, 4, 3)
        q.stop()
        r = list(q.available_iter())
        self.assertEqual(r, [5, 4, 3])
        aiter = map_aiter(make_sync_transformation_f(results), q)
        r = run(get_n(aiter))
        self.assertEqual(r, [6, 5, 4])
        self.assertEqual(results, [5, 4, 3])

    def test_make_pipe(self):
        async def map_f(x):
            await asyncio.sleep(x / 100.0)
            return x * x

        q = push_aiter()
        aiter = map_aiter(map_f, q)
        for _ in range(4):
            q.push(_)
        for _ in range(3, 9):
            q.push(_)
        r = run(get_n(aiter, 10))
        q.stop()
        r.extend(run(get_n(aiter)))
        r1 = sorted([_*_ for _ in range(4)] + [_ * _ for _ in range(3, 9)])
        self.assertEqual(r, r1)
