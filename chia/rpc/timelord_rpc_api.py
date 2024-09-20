from __future__ import annotations

from typing import Any, Dict, List, Optional

from chia.rpc.rpc_server import Endpoint
from chia.timelord.timelord import Timelord
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class TimelordRpcApi:
    def __init__(self, timelord: Timelord):
        self.service = timelord
        self.service_name = "chia_timelord"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {}

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> List[WsRpcMessage]:
        payloads = []

        if change_data is None:
            change_data = {}

        if change in ("finished_pot", "new_compact_proof", "skipping_peak", "new_peak"):
            payloads.append(create_payload_dict(change, change_data, self.service_name, "metrics"))

        return payloads
