from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

from chia.rpc.rpc_server import Endpoint
from chia.timelord.timelord import Timelord
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class TimelordRpcApi:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcApiProtocol

        _protocol_check: ClassVar[RpcApiProtocol] = cast("TimelordRpcApi", None)

    def __init__(self, timelord: Timelord):
        self.service = timelord
        self.service_name = "chia_timelord"

    def get_routes(self) -> dict[str, Endpoint]:
        return {}

    async def _state_changed(self, change: str, change_data: Optional[dict[str, Any]] = None) -> list[WsRpcMessage]:
        payloads = []

        if change_data is None:
            change_data = {}

        if change in {"finished_pot", "new_compact_proof", "skipping_peak", "new_peak"}:
            payloads.append(create_payload_dict(change, change_data, self.service_name, "metrics"))

        return payloads
