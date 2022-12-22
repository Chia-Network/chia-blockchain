from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


class CustodyRpcClient(RpcClient):

    async def init(self,
        directory: str,
        withdrawal_timelock: uint64,
        payment_clawback: uint64,
        rekey_cancel: uint64,
        rekey_timelock: uint64,
        slow_penalty: uint64) -> Dict[str, Any]:
        response = await self.fetch("init", {"directory": directory,
            "withdrawal_timelock": withdrawal_timelock,
            "payment_clawback": payment_clawback,
            "rekey_cancel": rekey_cancel,
            "rekey_timelock": rekey_timelock,
            "slow_penalty": slow_penalty})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def derive(self,
        configuration: str,
        db_path: str,
        pubkeys: str,
        initial_lock_level: int,
        minimum_pks: int,
        validate_against: str,
        maximum_lock_level: int) -> Dict[str, Any]:
        response = await self.fetch("derive", {"configuration": configuration,
            "db_path": db_path,
            "pubkeys": pubkeys,
            "initial_lock_level": initial_lock_level,
            "minimum_pks": minimum_pks,
            "validate_against": validate_against,
            "maximum_lock_level": maximum_lock_level})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def launch(self,
        configuration: str,
        db_path: str,
        wallet_rpc_port: int,
        fingerprint: int,
        node_rpc_port: int,
        fee: int) -> Dict[str, Any]:
        response = await self.fetch("launch", {"configuration": configuration,
            "db_path": db_path,
            "wallet_rpc_port": wallet_rpc_port,
            "fingerprint": fingerprint,
            "node_rpc_port": node_rpc_port,
            "fee": fee})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def sync(self,
        configuration: str,
        db_path: str,
        node_rpc_port: int,
        show: bool) -> Dict[str, Any]:
        response = await self.fetch("sync", {"configuration": configuration,
            "db_path": db_path,
            "node_rpc_port": node_rpc_port,
            "show": show})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def show(self,
        db_path: str,
        configopt: bool,
        derivationopt: bool) -> Dict[str, Any]:
        response = await self.fetch("show", {"db_path": db_path, "config": True, "derivation": True})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def address(self,
        db_path: str,
        prefix: str) -> Dict[str, Any]:
        response = await self.fetch("address", {"db_path": db_path, "prefix": prefix})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def push(self,
        spend_bundle: str,
        wallet_rpc_port: Optional[int],
        fingerprint: Optional[int],
        node_rpc_port: Optional[int],
        fee: int) -> Dict[str, Any]:
        response = await self.fetch("push", {"spend_bundle": spend_bundle, "wallet_rpc_port": wallet_rpc_port, "fingerprint": fingerprint, "node_rpc_port": node_rpc_port, "fee": fee})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def payments(self,
        db_path: str,
        pubkeys: str,
        amount: int,
        recipient_address: str,
        absorb_available_payments: bool,
        maximum_extra_cost: Optional[int],
        amount_threshold: int,
        filename: Optional[str]) -> Dict[str, Any]:
        response = await self.fetch("payments", {"db_path": db_path, "pubkeys": pubkeys, "amount": amount, "recipient_address": recipient_address, "absorb_available_payments": absorb_available_payments, "maximum_extra_cost": maximum_extra_cost, "amount_threshold": amount_threshold, "filename": filename})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

        
    async def hsmgen(self) -> Dict[str, Any]:
        response = await self.fetch("hsmgen",{})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def hsmpk(self,
        secretkey:str) -> Dict[str, Any]:
        response = await self.fetch("hsmpk",{"secretkey": secretkey})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def hsms(self,
        message:str,
        secretkey:str) -> Dict[str, Any]:
        response = await self.fetch("hsms",{"message": message, "secretkey":secretkey})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]


    async def hsmmerge(self,
        bundle:str,
        sigs:str) -> Dict[str, Any]:
        response = await self.fetch("hsmmerge",{"bundle": bundle, "sigs": sigs})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

