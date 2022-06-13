import string

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


if __name__ == "__main__":
    main()
else:
    import pytest

    import pytest_asyncio


    @pytest_asyncio.fixture()
    async def port():
        print(" ==== running")
        app = aiohttp.web.Application()
        app.add_routes(
            [
                aiohttp.web.post('/', handle),
                *[
                    aiohttp.web.post(f"/{c}", handle)
                    for c in string.ascii_letters
                ],
            ],
        )

        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        try:
            host = "0.0.0.0"

            site = aiohttp.web.TCPSite(runner=runner, host=host, port=0)
            await site.start()
            [[interface, port]] = runner.addresses
            print(f" ==== listening on port {port}")
            await request_and_assert(port=port)
            try:
                yield port
            finally:
                await site.stop()
        finally:
            await runner.cleanup()


    @pytest_asyncio.fixture()
    async def another():
        print(" ==== running")
        app = aiohttp.web.Application()
        app.add_routes(
            [
                # aiohttp.web.post('/', handle),
                *[
                    aiohttp.web.post(f"/{c}", handle)
                    for c in string.ascii_letters
                ],
            ],
        )

        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        try:
            host = "0.0.0.0"

            site = aiohttp.web.TCPSite(runner=runner, host=host, port=0)
            await site.start()
            [[interface, port]] = runner.addresses
            print(f" ==== listening on port {port}")
            await request_and_assert(port=port, route="/a")
            try:
                yield port
            finally:
                await site.stop()
        finally:
            await runner.cleanup()


    async def request_and_assert(port, route="/"):
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            async with session.post(f"http://localhost:{port}{route}", json={}) as response:
                text = await response.text()
                assert text == "Heya", repr(text)

    @pytest.mark.parametrize(argnames="index", argvalues=range(11))
    @pytest.mark.asyncio()
    async def test_it(port, index, another):
        print(f" ==== running {port=} {another=}")
        await request_and_assert(port=port)
