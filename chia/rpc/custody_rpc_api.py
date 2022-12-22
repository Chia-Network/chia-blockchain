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
            # "/start_rekey": self.start_rekey,
            # "/clawback": self.clawback,
            # "/complete": self.complete,
            # "/increase": self.increase,
            "/show": self.show,
            # "/audit": self.audit,
            # "/examine": self.examine,
            # "/which_pubkeys": self.which_pubkeys,
            "/hsmgen": self.hsmgen,
            "/hsmpk": self.hsmpk,
            "/hsms": self.hsms,
            "/hsmmerge": self.hsmmerge,
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


    async def launch(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        configuration = request.get("configuration")
        db_path = request.get("db_path")
        wallet_rpc_port = request.get("wallet_rpc_port")
        fingerprint = request.get("fingerprint")
        node_rpc_port = request.get("node_rpc_port")
        fee = request.get("fee")
                    
        wjb = await self.service.launch_cmd(configuration,
            db_path,
            wallet_rpc_port,
            uint64(fingerprint),
            node_rpc_port,
            uint64(fee))
        return {"wjb": wjb}

    async def update(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        configuration = request.get("configuration")
        db_path = request.get("db_path")
                    
        wjb = await self.service.update_cmd(configuration,
            db_path)
        return {"wjb": wjb}
        
    async def export(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        filename = request.get("filename")
        db_path = request.get("db_path")
        public = request.get("public")
                      
        wjb = await self.service.export_cmd(filename,
            db_path,
            public)
        return {"wjb": wjb}
        
        

    async def sync(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        configuration = request.get("configuration")
        db_path = request.get("db_path")
        node_rpc_port = request.get("node_rpc_port")
        show = request.get("show")
                    
        wjb = await self.service.sync_cmd(configuration,
            db_path,
            node_rpc_port,
            show)
        return {"wjb": wjb}

    async def show(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        db_path = request.get("db_path")
        config = request.get("config")
        derivation = request.get("derivation")
                    
        wjb = await self.service.show_cmd(db_path,
            config,
            derivation)
        return {"info": wjb}

    async def address(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        db_path = request.get("db_path")
        prefix = request.get("prefix")
                     
        wjb = await self.service.address_cmd(db_path,
            prefix)
        return {"address": wjb}

    async def push(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        spend_bundle = request.get("spend_bundle")
        wallet_rpc_port = request.get("wallet_rpc_port")
        fingerprint = request.get("fingerprint")
        node_rpc_port = request.get("node_rpc_port")
        fee = request.get("fee")

        wjb = await self.service.push_cmd(spend_bundle,
            wallet_rpc_port,
            fingerprint,
            node_rpc_port,
            fee)
        return {"wjb": wjb}

    async def payments(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        db_path = request.get("db_path")
        pubkeys = request.get("pubkeys")
        amount = request.get("amount")
        recipient_address = request.get("recipient_address")
        absorb_available_payments = request.get("absorb_available_payments")
        maximum_extra_cost = request.get("maximum_extra_cost")
        amount_threshold = request.get("amount_threshold")
        filename = request.get("filename")
              
        wjb = await self.service.payments_cmd(db_path,
            pubkeys,
            amount,
            recipient_address,
            absorb_available_payments,
            maximum_extra_cost,
            amount_threshold,
            filename)
        return {"wjb": wjb}



    async def hsmgen(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
            
        secretkey = await self.service.hsmgen_cmd()
        return {"secretkey": secretkey}

    async def hsmpk(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
            
        secretkey = request.get("secretkey")
        publickey = await self.service.hsmpk_cmd(secretkey)
        return {"publickey": publickey}

    async def hsms(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
            
        message = request.get("message")
        secretkey = request.get("secretkey")
        bundle = await self.service.hsms_cmd(message, secretkey)
        return {"signature": bundle}

    async def hsmmerge(self, request: Dict[str, Any]) -> EndpointResult:
        if self.service is None:
            raise Exception("Data layer not created")
        
        bundle = request.get("bundle")
        sigs = request.get("sigs")
        bundle = await self.service.hsmmerge_cmd(bundle, sigs)
        return {"signedbundle": bundle}

