import asyncio
from lib.aiter.aiter.push_aiter import push_aiter
from lib.aiter.aiter.aiter_forker import aiter_forker
from lib.aiter.aiter.server import start_server_aiter
from lib.aiter.aiter.join_aiters import join_aiters
from lib.aiter.aiter.map_aiter import map_aiter
from lib.aiter.aiter.iter_to_aiter import iter_to_aiter


async def cancel():
    await asyncio.sleep(1)
    pending = asyncio.Task.all_tasks()
    for t in pending:
        print("CANCELLING")
        t.cancel()


async def test_aiter_cancel():
    q, aiter = await start_server_aiter(8002)
    forker = aiter_forker(aiter)
    fork_1 = forker.fork(is_active=True)
    fork_2 = forker.fork(is_active=True)

    responses_aiter = join_aiters(iter_to_aiter([fork_1, fork_2]))

    asyncio.create_task(cancel())
    async for x in responses_aiter:
        print(x)


asyncio.run(test_aiter_cancel())