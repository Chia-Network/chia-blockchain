import asyncio

from .push_aiter import push_aiter


async def aiter_server(start_f, *args, **kwargs):
    aiter = push_aiter()
    server = await start_f(
        client_connected_cb=lambda r, w: aiter.push((r, w)), *args, **kwargs)
    aiter.task = asyncio.ensure_future(
        server.wait_closed()).add_done_callback(lambda f: aiter.stop())
    return server, aiter


async def start_server_aiter(port, *args, **kwargs):
    return await aiter_server(
        asyncio.start_server, port=port, *args, **kwargs)


async def start_unix_server_aiter(path, *args, **kwargs):
    return await aiter_server(
        asyncio.start_unix_server, path=path, *args, **kwargs)
