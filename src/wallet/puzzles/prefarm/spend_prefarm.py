import asyncio

from clvm_tools import binutils

from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.types.blockchain_format.program import Program
from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle
from src.util.config import load_config
from src.util.default_root import DEFAULT_ROOT_PATH


async def main():
    rpc_port = 8555
    self_hostname = "localhost"
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    client = await FullNodeRpcClient.create(self_hostname, rpc_port, DEFAULT_ROOT_PATH, config)
    try:
        farmer_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[1]
        pool_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[0]

        ph1 = ""
        ph2 = ""

        p = Program.to(binutils.assemble(f"((q (51 {ph1} 0x7f808e9291e6c000) (51 {ph2} 0x7f808e9291e6c000)) ())"))

        # sb_pool = SpendBundle([CoinSolution(pool_prefarm, p)], None)
        sb_farmer = SpendBundle([CoinSolution(farmer_prefarm, p)], None)

        res = await client.send_transaction(sb_farmer)
        print(res)
        up = await client.get_unspent_coins(farmer_prefarm.puzzle_hash)
        uf = await client.get_unspent_coins(pool_prefarm.puzzle_hash)
        print(up)
        print(uf)
    finally:
        client.close()


asyncio.run(main())
