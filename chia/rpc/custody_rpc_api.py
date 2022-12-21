from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes

# todo input assertions for all rpc's
from chia.util.ints import uint64
from chia.util.streamable import recurse_jsonify
from chia.util.ws_message import WsRpcMessage
from chia.wallet.trading.offer import Offer as TradingOffer

if TYPE_CHECKING:
    from chia.custody.custody import Custody


def process_change(change: Dict[str, Any]) -> Dict[str, Any]:
    # TODO: A full class would likely be nice for this so downstream doesn't
    #       have to deal with maybe-present attributes or Dict[str, Any] hints.
    reference_node_hash = change.get("reference_node_hash")
    if reference_node_hash is not None:
        reference_node_hash = bytes32(hexstr_to_bytes(reference_node_hash))

    side = change.get("side")
    if side is not None:
        side = Side(side)

    value = change.get("value")
    if value is not None:
        value = hexstr_to_bytes(value)

    return {
        **change,
        "key": hexstr_to_bytes(change["key"]),
        "value": value,
        "reference_node_hash": reference_node_hash,
        "side": side,
    }


def get_fee(config: Dict[str, Any], request: Dict[str, Any]) -> uint64:
    fee = request.get("fee")
    if fee is None:
        config_fee = config.get("fee", 0)
        return uint64(config_fee)
    return uint64(fee)


class CustodyRpcApi:
    # TODO: other RPC APIs do not accept a wallet and the service start does not expect to provide one
    def __init__(self, custody: Custody):  # , wallet: CustodyWallet):
        self.service: Custody = custody
        self.service_name = "chia_custody"

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            "/init": self.init,
            "/derive": self.derive,
            "/launch": self.launch,
            "/update": self.update,
            "/export": self.export,
            "/sync": self.sync,
            "/address": self.address,
            "/push": self.push,
            "/payments": self.payments,
            "/start_rekey": self.start_rekey,
            "/clawback": self.clawback,
            "/complete": self.complete,
            "/increase": self.increase,
            "/show": self.show,
            "/audit": self.audit,
            "/examine": self.examine,
            "/which_pubkeys": self.which_pubkeys,
            "/hsmgen": self.hsmgen,
        }

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]]) -> List[WsRpcMessage]:
        return []

    async def init(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        directory = request.get("directory")
        withdrawal_timelock = request.get("withdrawal_timelock")
        payment_clawback = request.get("payment_clawback")
        rekey_cancel = request.get("rekey_cancel")
        rekey_timelock = request.get("rekey_timelock")
        slow_penalty = request.get("slow_penalty")
                        
        await self.service.init_cmd(directory,
            uint64(withdrawal_timelock),
            uint64(payment_clawback),
            uint64(rekey_cancel),
            uint64(rekey_timelock),
            uint64(slow_penalty))
        return {"success": "true"}

    async def derive(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        configuration = request.get("configuration")
        db_path = request.get("db_path")
        pubkeys = request.get("pubkeys")
        initial_lock_level = request.get("initial_lock_level")
        minimum_pks = request.get("minimum_pks")
        validate_against = request.get("validate_against")
        maximum_lock_level = request.get("maximum_lock_level")
                    
        await self.service.derive_cmd(configuration,
            db_path,
            pubkeys,
            uint64(initial_lock_level),
            uint64(minimum_pks),
            validate_against,
            uint64(maximum_lock_level))
        return {"success": "true"}

    async def hsmgen(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
            
        secretkey = await self.service.hsmgen_cmd()
        return {"secretkey": secretkey}
        
    async def launch(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def update(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def export(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def sync(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def address(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def push(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def payments(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def start_rekey(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def clawback(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def complete(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def increase(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def show(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def audit(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}
        
    async def examine(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

    async def which_pubkeys(self, request: Dict[str, Any]) -> EndpointResult:
        return {"success": "true"}

  
