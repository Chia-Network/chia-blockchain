import asyncio
import signal
import sys

from src.web.prompt_web import start_ssh_server
from src.util.logging import initialize_logging
from setproctitle import setproctitle

initialize_logging("UI %(name)-29s")
setproctitle("chia_full_node_web")


async def main():
    rpc_index = sys.argv.index("-r")
    rpc_port = int(sys.argv[rpc_index + 1])

    webfilename = sys.argv[1]

    await_all_closed, ui_close_cb = await start_ssh_server(
        webfilename, rpc_port
    )

    asyncio.get_running_loop().add_signal_handler(
        signal.SIGINT, lambda: ui_close_cb(False)
    )
    asyncio.get_running_loop().add_signal_handler(
        signal.SIGTERM, lambda: ui_close_cb(False)
    )

    await await_all_closed()

asyncio.run(main())
