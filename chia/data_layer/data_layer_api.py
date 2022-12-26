from __future__ import annotations

import logging
from typing import ClassVar

from chia.data_layer.data_layer import DataLayer
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.util.api_decorators import ApiNodeMetadata


class DataLayerAPI:
    metadata: ClassVar[ApiNodeMetadata] = ApiNodeMetadata(type=NodeType.DATA_LAYER)
    data_layer: DataLayer

    def __init__(self, data_layer: DataLayer) -> None:
        self.data_layer = data_layer

    # def _set_state_changed_callback(self, callback: Callable):
    #     self.full_node.state_changed_callback = callback

    @property
    def server(self) -> ChiaServer:
        return self.data_layer.server

    @property
    def log(self) -> logging.Logger:
        return self.data_layer.log

    @property
    def api_ready(self) -> bool:
        return self.data_layer.initialized
