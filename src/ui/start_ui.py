import asyncio
import signal

from src.ui.prompt_ui import start_ssh_server
from src.util.logging import initialize_logging
from src.util.config import load_config_cli
from setproctitle import setproctitle


async def main():
    config = load_config_cli("config.yaml", "ui")
    initialize_logging("UI %(name)-29s", config["logging"])
    setproctitle("chia_full_node_ui")

    await_all_closed, ui_close_cb = await start_ssh_server(
        config["port"], config["ssh_filename"], config["rpc_port"]
    )

    asyncio.get_running_loop().add_signal_handler(
        signal.SIGINT, lambda: ui_close_cb(False)
    )
    asyncio.get_running_loop().add_signal_handler(
        signal.SIGTERM, lambda: ui_close_cb(False)
    )

    await await_all_closed()


asyncio.run(main())
