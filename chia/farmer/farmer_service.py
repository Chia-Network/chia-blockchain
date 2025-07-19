from __future__ import annotations

from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.farmer.farmer_rpc_api import FarmerRpcApi
from chia.server.start_service import Service

FarmerService = Service[Farmer, FarmerAPI, FarmerRpcApi]
