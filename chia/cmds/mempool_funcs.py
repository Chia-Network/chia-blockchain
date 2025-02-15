from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.spend_bundle import SpendBundle


async def import_mempool_async(
    rpc_port: Optional[int],
    root_path: Path,
    content: dict[str, Any],
) -> None:
    from chia.cmds.cmds_util import get_any_service_client

    async with get_any_service_client(FullNodeRpcClient, root_path, rpc_port) as (node_client, _):
        success = 0
        failed = 0

        for _, item in content["mempool_items"].items():
            try:
                await node_client.push_tx(SpendBundle.from_json_dict(item["spend_bundle"]))
                success += 1
            except Exception:
                failed += 1

        print(f"Successfully imported {success} mempool items, but failed to import {failed}")


async def export_mempool_async(
    rpc_port: Optional[int],
    root_path: Path,
    path: str,
) -> None:
    from chia.cmds.cmds_util import get_any_service_client

    async with get_any_service_client(FullNodeRpcClient, root_path, rpc_port) as (node_client, _):
        items = await node_client.get_all_mempool_items()
        content = {"mempool_items": {tx_id.hex(): item for tx_id, item in items.items()}}

        with open(path, "w") as f:
            json.dump(content, f)

        print(f"Successfully exported {len(content['mempool_items'])} mempool items to {path}")


async def create_block_async(
    rpc_port: Optional[int],
    root_path: Path,
) -> None:
    from chia.cmds.cmds_util import get_any_service_client

    async with get_any_service_client(FullNodeRpcClient, root_path, rpc_port) as (node_client, _):
        start = time.time()
        bundle = await node_client.create_block_bundle_from_mempool()
        end = time.time()
        spends = len(bundle["mempool_bundle"]["coin_spends"])
        print(f"Successfully created block bundle in {end - start} seconds with {spends} coin spends")
