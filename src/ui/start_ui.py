import asyncio
import signal
import sys
import yaml
import os

from src.ui.prompt_ui import start_ssh_server
from definitions import ROOT_DIR
from src.util.logging import initialize_logging
from setproctitle import setproctitle

initialize_logging("UI %(name)-29s")
setproctitle("chia_full_node_ui")


async def main():
    config_filename = os.path.join(ROOT_DIR, "config", "config.yaml")
    config = yaml.safe_load(open(config_filename, "r"))["full_node"]

    rpc_index = sys.argv.index("-r")
    rpc_port = int(sys.argv[rpc_index + 1])

    port = int(sys.argv[1])
    await_all_closed, ui_close_cb = await start_ssh_server(
        port, config["ssh_filename"], rpc_port
    )

    asyncio.get_running_loop().add_signal_handler(
        signal.SIGINT, lambda: ui_close_cb(False)
    )
    asyncio.get_running_loop().add_signal_handler(
        signal.SIGTERM, lambda: ui_close_cb(False)
    )

    await await_all_closed()


asyncio.run(main())
