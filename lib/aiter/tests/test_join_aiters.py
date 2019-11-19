import unittest


from aiter import iter_to_aiter, join_aiters, push_aiter


from .helpers import run, get_n


class test_aitertools(unittest.TestCase):

    def test_join_aiters(self):
        int_vals = [1, 2, 3, 4]
        str_vals = "abcdefg"

        list_of_lists = [int_vals, str_vals]
        iter_of_aiters = [iter_to_aiter(_) for _ in list_of_lists]
        aiter_of_aiters = iter_to_aiter(iter_of_aiters)
        r = run(get_n(join_aiters(aiter_of_aiters)))

        r1 = [_ for _ in r if isinstance(_, int)]
        r2 = [_ for _ in r if isinstance(_, str)]
        self.assertEqual(r1, int_vals)
        self.assertEqual(r2, list(str_vals))

    def test_join_aiters_1(self):
        # make sure nothing's dropped
        # even if lots of events come in at once
        main_aiter = push_aiter()
        child_aiters = []
        aiter = join_aiters(main_aiter)

        child_aiters.append(push_aiter())
        child_aiters[0].push(100)
        main_aiter.push(child_aiters[0])

        t = run(get_n(aiter, 1))
        self.assertEqual(t, [100])

        child_aiters.append(push_aiter())
        child_aiters[0].push(101)
        child_aiters[1].push(200)
        child_aiters[1].push(201)
        main_aiter.push(child_aiters[1])

        t = run(get_n(aiter, 3))
        self.assertEqual(set(t), set([101, 200, 201]))

        for _ in range(3):
            child_aiters.append(push_aiter())
            main_aiter.push(child_aiters[-1])
        for _, ca in enumerate(child_aiters):
            ca.push((_+1) * 100)
            ca.push((_+1) * 100 + 1)

        t = run(get_n(aiter, len(child_aiters) * 2))
        self.assertEqual(set(t), set([100, 101, 200, 201, 300, 301, 400, 401, 500, 501]))

        child_aiters[-1].push(5000)
        main_aiter.stop()
        t = run(get_n(aiter, 1))
        self.assertEqual(t, [5000])

        for ca in child_aiters:
            ca.push(99)
            ca.stop()
        t = run(get_n(aiter))
        self.assertEqual(t, [99] * len(child_aiters))
