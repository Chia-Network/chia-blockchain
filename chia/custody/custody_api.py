from __future__ import annotations

import logging

from chia.custody.custody import Custody
from chia.server.server import ChiaServer


class CustodyAPI:
    custody: Custody

    def __init__(self, custody: Custody) -> None:
        self.custody = custody

    # def _set_state_changed_callback(self, callback: Callable):
    #     self.full_node.state_changed_callback = callback

    @property
    def server(self) -> ChiaServer:
        return self.custody.server

    @property
    def log(self) -> logging.Logger:
        return self.custody.log

    @property
    def api_ready(self) -> bool:
        return self.custody.initialized
