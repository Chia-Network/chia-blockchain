import asyncio
import unittest


from aiter import map_aiter, push_aiter


from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_make_delayed_pipeline(self):
        def make_wait_index(idx):

            async def wait(item):
                await asyncio.sleep(item[idx] / 10.)
                return item

            return wait

        TEST_CASE = [
            (0, 0, 0, 7),
            (5, 0, 0, 0),
            (0, 0, 1, 0),
            (1, 1, 1, 1),
            (2, 0, 0, 1),
            (3, 1, 2, 0),
        ]

        q = push_aiter()
        aiter = map_aiter(
            make_wait_index(0), map_aiter(
                make_wait_index(1), map_aiter(
                    make_wait_index(2), map_aiter(
                        make_wait_index(3), q, 10), 10), 10), 10)
        q.push(*TEST_CASE)
        q.stop()
        r = run(get_n(aiter))
        r1 = sorted(r, key=lambda x: sum(x))
        self.assertEqual(r, r1)
