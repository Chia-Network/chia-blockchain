from __future__ import annotations

import json
from typing import Optional

import click

from chia.rpc.full_node_rpc_client import FullNodeRpcClient


async def print_fee_info(node_client: FullNodeRpcClient, json_flag: bool) -> None:
    target_times = [60, 120, 300]
    target_times_names = ["1  minute", "2 minutes", "5 minutes"]
    res = await node_client.get_fee_estimate(target_times=target_times, cost=1)
    if json_flag:
        print(json.dumps(res))
        return

    print("\n")
    print(f"  Mempool max cost: {res['mempool_max_size']:>12} CLVM cost")
    print(f"      Mempool cost: {res['mempool_size']:>12} CLVM cost")
    print(f"     Mempool count: {res['num_spends']:>12} spends")
    print(f"   Fees in Mempool: {res['mempool_fees']:>12} mojos")
    print()

    print("Stats for last transaction block:")
    print(f"      Block height: {res['last_tx_block_height']:>12}")
    print(f"        Block fees: {res['fees_last_block']:>12} mojos")
    print(f"        Block cost: {res['last_block_cost']:>12} CLVM cost")
    print(f"          Fee rate: {res['fee_rate_last_block']:>12.5} mojos per CLVM cost")

    print("\nFee Rate Estimates:")
    max_name_len = max(len(name) for name in target_times_names)
    for (n, e) in zip(target_times_names, res["estimates"]):
        print(f"    {n:>{max_name_len}}: {e} mojo per CLVM cost")
    print("")


async def fees_cmd_async(ctx: click.Context, rpc_port: Optional[int], json: bool) -> None:

    from chia.cmds.cmds_util import get_any_service_client

    node_client: Optional[FullNodeRpcClient]
    async with get_any_service_client("full_node", rpc_port, ctx.obj["root_path"]) as node_config_fp:
        node_client, config, _ = node_config_fp
        if node_client is not None:
            await print_fee_info(node_client, json)


@click.command("fees", short_help="Show network fee estimates")
@click.option(
    "-p",
    "--rpc-port",
    help=(
        "Set the port where the Full Node is hosting the RPC interface. "
        "See the rpc_port under full_node in config.yaml"
    ),
    type=int,
    default=None,
)
@click.option(
    "-j",
    "--json",
    is_flag=True,
    type=bool,
    default=False,
    help="print json",
)
@click.pass_context
def fees_cmd(ctx: click.Context, rpc_port: Optional[int], json: bool) -> None:
    import asyncio

    asyncio.run(fees_cmd_async(ctx, rpc_port, json))
