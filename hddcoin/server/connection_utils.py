import asyncio
import random
from typing import Any, List, Optional, Tuple

from hddcoin.server.ws_connection import WSHDDcoinConnection


async def send_all_first_reply(
    func: str, arg: Any, peers: List[WSHDDcoinConnection], timeout=15
) -> Optional[Tuple[Any, WSHDDcoinConnection]]:
    """performs an API request to peers and returns the result of the first response and the peer that sent it."""

    async def do_func(peer_x: WSHDDcoinConnection, func_x: str, arg_x: Any):
        method_to_call = getattr(peer_x, func_x)
        result_x = await method_to_call(arg_x)
        if result_x is not None:
            return result_x, peer_x
        else:
            await asyncio.sleep(timeout)
            return None

    tasks = []
    for peer in peers:
        tasks.append(do_func(peer, func, arg))

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    if len(done) > 0:
        d = done.pop()
        result = d.result()
        if result is None:
            return None

        response, peer = result
        return response, peer
    else:
        return None


async def send_to_random(func: str, arg: Any, peers: List[WSHDDcoinConnection]) -> Optional[Tuple[Any, WSHDDcoinConnection]]:
    """performs an API request to peers and returns the result of the first response and the peer that sent it."""

    async def do_func(peer_x: WSHDDcoinConnection, func_x: str, arg_x: Any):
        method_to_call = getattr(peer_x, func_x)
        result_x = await method_to_call(arg_x)
        if result_x is not None:
            return result_x, peer_x
        else:
            await asyncio.sleep(15)
            return None

    tasks = []
    random_peer = random.choice(peers)
    tasks.append(do_func(random_peer, func, arg))
    done, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

    if len(done) > 0:
        d = done.pop()
        result = d.result()
        if result is None:
            return None

        response, peer = result
        return response, peer
    else:
        return None
