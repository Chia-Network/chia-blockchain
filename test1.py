import asyncio


def cb(r, w):
    print("Connected", w.get_extra_info("peername"))


async def main():
    server = await asyncio.start_server(cb, "127.0.0.1", 8000)
    server2 = await asyncio.start_server(cb, "127.0.0.1", 8001)

    _, _ = await asyncio.open_connection("127.0.0.1", 8001)
    _, _ = await asyncio.open_connection("127.0.0.1", 8001)
    _, _ = await asyncio.open_connection("127.0.0.1", 8001)
    await asyncio.sleep(2)
    server2_socket = server2.sockets[0]
    print("Socket", server2.sockets)

    r, w = await asyncio.open_connection(sock=server2_socket)
    print("Opened connection", w.get_extra_info("peername"), w.transport)
    await server.serve_forever()



asyncio.run(main())