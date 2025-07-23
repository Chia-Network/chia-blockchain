from __future__ import annotations

from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.harvester.harvester_rpc_api import HarvesterRpcApi
from chia.server.start_service import Service

HarvesterService = Service[Harvester, HarvesterAPI, HarvesterRpcApi]
