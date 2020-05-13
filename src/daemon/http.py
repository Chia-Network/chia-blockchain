import asyncio

from aiohttp import web


# GET http://127.0.0.1:PORT/daemon/service/SERVICE_NAME?m=start => start service
# GET http://127.0.0.1:PORT/daemon/service/SERVICE_NAME?m=stop => stop service
# GET http://127.0.0.1:PORT/daemon/service/ => list services


def create_server_for_daemon(daemon, host="127.0.0.1"):
    routes = web.RouteTableDef()

    @routes.get('/daemon/ping/')
    async def ping(request):
        async for r in daemon.ping():
            pass
        return web.Response(text=str(r))

    @routes.get('/daemon/exit/')
    async def exit(request):
        async for r in daemon.exit():
            pass
        return web.Response(text=str(r))

    @routes.get('/daemon/service/start/')
    async def start_service(request):
        service_name = request.query.get("service")
        async for r in daemon.start_service(service_name):
            pass
        return web.Response(text=str(r))

    @routes.get('/daemon/service/stop/')
    async def stop_service(request):
        service_name = request.query.get("service")
        async for r in daemon.stop_service(service_name):
            pass
        return web.Response(text=str(r))

    @routes.get('/daemon/service/is_running/')
    async def is_running(request):
        service_name = request.query.get("service")
        async for r in daemon.is_running(service_name):
            pass
        return web.Response(text=str(r))

    app = web.Application()
    app.add_routes(routes)
    task = web._run_app(app)
    return asyncio.ensure_future(task)
