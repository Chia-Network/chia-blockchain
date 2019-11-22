import asyncio


async def join_aiters(aiter_of_aiters):
    """
    This wrapper takes an aiter of aiters and pipe the items coming out of all of them into a
    single aiter.

    :type aiter_of_aiters: async iterator
    :param aiter_of_aiters: an aiter that yields aiters

    :return: an aiter returning elements that come from any of the underlying aiters
    :rtype: async iterator
    """

    async def _aiter_to_next_job(aiter):
        """
        Return two lists: a list of items to yield, and a list of jobs to add to queue.
        """
        try:
            items = [await aiter.__anext__()]
            jobs = [asyncio.ensure_future(_aiter_to_next_job(aiter))]
        except StopAsyncIteration:
            items = jobs = []
        return items, jobs

    async def _main_aiter_to_next_job(aiter_of_aiters):
        """
        Return two lists: a list of items to yield, and a list of jobs to add to queue.
        """
        try:
            items = []
            new_aiter = await aiter_of_aiters.__anext__()
            jobs = [
                asyncio.ensure_future(_aiter_to_next_job(new_aiter.__aiter__())),
                asyncio.ensure_future(_main_aiter_to_next_job(aiter_of_aiters))]
        except StopAsyncIteration:
            jobs = []
        return items, jobs

    jobs = set([_main_aiter_to_next_job(aiter_of_aiters.__aiter__())])

    while jobs:
        done, jobs = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        for _ in done:
            new_items, new_jobs = await _
            for _ in new_items:
                yield _
            jobs.update(_ for _ in new_jobs)
