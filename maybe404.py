import asyncio
import aiohttp
import aiohttp.web


async def handle(request):
    return aiohttp.web.Response(text="Heya")


async def async_main():
    print(" ==== running")
    app = aiohttp.web.Application()
    app.add_routes([aiohttp.web.post('/', handle)])

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    try:
        host = "0.0.0.0"

        site = aiohttp.web.TCPSite(runner=runner, host=host, port=0)
        await site.start()
        [[interface, port]] = runner.addresses
        print(f" ==== listening on port {port}")
        try:
            async with aiohttp.ClientSession(raise_for_status=True) as session:
                # async with session.get(f"http://localhost:{port}/") as response:
                async with session.post(f"http://localhost:{port}/", json={}) as response:
                    text = await response.text()
                    assert text == "Heya", repr(text)
        finally:
            await site.stop()
    finally:
        await runner.cleanup()


def main():
    while True:
        asyncio.run(async_main())


main()
