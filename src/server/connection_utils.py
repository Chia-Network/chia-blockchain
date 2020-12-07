import asyncio
from asyncio import FIRST_COMPLETED
from typing import List, Any, Tuple, Optional

from src.server.ws_connection import WSChiaConnection


async def send_all_first_reply(func, arg, peers: List[WSChiaConnection]) -> Optional[Tuple[Any, WSChiaConnection]]:
    """performs an API request to peers and returns the result of the first response and the peer that sent it."""

    async def do_func(peer, func, arg):
        method_to_call = getattr(peer, func)
        result = await method_to_call(arg)
        if result is not None:
            return result, peer
        else:
            await asyncio.sleep(15)
            return None

    tasks = []
    for peer in peers:
        tasks.append(do_func(peer, func, arg))

    done, pending = await asyncio.wait(tasks, return_when=FIRST_COMPLETED)

    if len(done) > 0:
        d = done.pop()
        result = d.result()
        if result is None:
            return None

        response, peer = result
        return response, peer
    else:
        return None
