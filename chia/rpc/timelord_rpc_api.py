from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Callable, Optional

from chia.rpc.rpc_server import Endpoint, ServiceManagementMessage
from chia.timelord.timelord import Timelord
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class TimelordRpcApi:
    def __init__(
        self,
        timelord: Timelord,
        management_request: Optional[Callable[[ServiceManagementMessage], Awaitable[None]]] = None,
    ):
        self.service = timelord
        self.service_name = "chia_timelord"

    def get_routes(self) -> dict[str, Endpoint]:
        return {}

    async def _state_changed(self, change: str, change_data: Optional[dict[str, Any]] = None) -> list[WsRpcMessage]:
        payloads = []

        if change_data is None:
            change_data = {}

        if change in ("finished_pot", "new_compact_proof", "skipping_peak", "new_peak"):
            payloads.append(create_payload_dict(change, change_data, self.service_name, "metrics"))

        return payloads
