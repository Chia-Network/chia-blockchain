#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from chia.wallet import wallet_rpc_client
from chia.wallet.wallet_request_types import Empty
from chia.wallet.wallet_rpc_metadata import WALLET_RPC_ENDPOINT_METADATA

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "chia" / "wallet" / "wallet_rpc_client.pyi"


def _type_name(cls: type) -> str:
    return cls.__name__


def _import_name(cls: type) -> str:
    return cls.__module__


def generate() -> str:

    methods: list[str] = []

    for meta in WALLET_RPC_ENDPOINT_METADATA:
        method_name = wallet_rpc_client.client_method_name(meta.endpoint_name)
        request_type = meta.request_type
        response_type = meta.response_type

        if response_type is Empty:
            response_ann = "None"
        elif _import_name(response_type) == "chia.wallet.wallet_request_types":
            response_ann = "wallet_request_types." + _type_name(response_type)
        else:
            response_ann = _type_name(response_type)

        if _import_name(request_type) == "chia.wallet.wallet_request_types":
            request_ann = "wallet_request_types." + _type_name(request_type)
        else:
            request_ann = _type_name(request_type)

        if meta.tx_endpoint:
            methods.append(
                f"    async def {method_name}(\n"
                f"        self,\n"
                f"        request: {request_ann},\n"
                f"        tx_config: TXConfig,\n"
                f"        extra_conditions: tuple[Condition, ...] = ...,\n"
                f"        timelock_info: ConditionValidTimes = ...,\n"
                f"    ) -> {response_ann}: ..."
            )
        elif request_type is Empty:
            methods.append(f"    async def {method_name}(self) -> {response_ann}: ...")
        else:
            methods.append(
                f"    async def {method_name}(\n"
                "        self,\n"
                f"        request: {request_ann},\n"
                f"    ) -> {response_ann}: ..."
            )

    body = "\n".join(
        [
            "from chia.data_layer.data_layer_util import DLProof, VerifyProofResponse",
            "from chia.rpc.rpc_client import RpcClient",
            "from chia.wallet import wallet_request_types",
            "from chia.wallet.conditions import Condition, ConditionValidTimes",
            "from chia.wallet.puzzles.clawback.metadata import AutoClaimSettings",
            "from chia.wallet.util.tx_config import TXConfig",
            "",
            "def client_method_name(endpoint_name: str) -> str: ...",
            "",
            "class WalletRpcClient(RpcClient):",
            *methods,
            "",
        ]
    )
    return body


def main() -> None:
    OUTPUT_PATH.write_text(generate(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
