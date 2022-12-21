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

    async def derive(
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

