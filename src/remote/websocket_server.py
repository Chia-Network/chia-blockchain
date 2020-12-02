import asyncio
import logging

from aiohttp import web

from .json_packaging import rpc_stream_for_websocket_aiohttp

log = logging.getLogger(__name__)


def create_server_for_ws_callback(ws_callback):
    routes = web.RouteTableDef()

    @routes.get("/ws/")
    async def ws_request(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws_callback(ws)
        return ws

    app = web.Application()
    app.add_routes(routes)
    return app


async def create_unix_site(runner, path):
    site = web.UnixSite(runner, path)
    await site.start()
    return site


async def create_tcp_site(runner, path, start_port, end_port=65536, host="127.0.0.1"):
    port = start_port
    while port < end_port:
        site = web.TCPSite(runner, port=port, host=host)
        try:
            await site.start()
            return site, port
        except IOError:
            port += 1
    raise IOError("couldn't find a port to listen on")


def ws_callback_for_api(api_list):
    async def ws_callback(ws):
        rpc_stream = rpc_stream_for_websocket_aiohttp(ws)
        for api in api_list:
            _ = rpc_stream.register_local_obj(api)
        rpc_stream.start()
        await rpc_stream.await_closed()

    return ws_callback


async def connect_runner_and_apis(site_for_runner_f, *api_list):
    ws_callback = ws_callback_for_api(api_list)

    app = create_server_for_ws_callback(ws_callback)
    runner = web.AppRunner(app)
    await runner.setup()

    site = await site_for_runner_f(runner)

    app["site"] = site
    task = asyncio.create_task(site._server.wait_closed())
    return site, task


async def simple_server(port, api, host="0.0.0.0"):
    """
    This simple example will attach an API to a given port. The URL for the client to
    connect to will be ws://127.0.0.1:port/ws/
    """

    async def site_for_runner(runner):
        site = web.TCPSite(runner, port=port, host=host)
        await site.start()
        return site

    site, task = await connect_runner_and_apis(site_for_runner, api)
    await task
