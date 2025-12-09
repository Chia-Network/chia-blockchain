from __future__ import annotations

from chia.server.start_service import Service
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.timelord.timelord_rpc_api import TimelordRpcApi

TimelordService = Service[Timelord, TimelordAPI, TimelordRpcApi]
