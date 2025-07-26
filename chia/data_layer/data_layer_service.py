from __future__ import annotations

from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_api import DataLayerAPI
from chia.data_layer.data_layer_rpc_api import DataLayerRpcApi
from chia.server.start_service import Service

DataLayerService = Service[DataLayer, DataLayerAPI, DataLayerRpcApi]
