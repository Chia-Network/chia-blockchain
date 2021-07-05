import asyncio

from blspy import G2Element
from clvm_tools import binutils

from chives.consensus.block_rewards import calculate_base_community_reward, calculate_base_farmer_reward, calculate_pool_reward
from chives.rpc.full_node_rpc_client import FullNodeRpcClient
from chives.types.blockchain_format.program import Program
from chives.types.coin_solution import CoinSolution
from chives.types.spend_bundle import SpendBundle
from chives.util.bech32m import decode_puzzle_hash
from chives.util.config import load_config
from chives.util.default_root import DEFAULT_ROOT_PATH
from chives.util.ints import uint32, uint16


async def main() -> None:
    rpc_port: uint16 = uint16(9755)
    self_hostname = "localhost"
    path = DEFAULT_ROOT_PATH
    config = load_config(path, "config.yaml")
    client = await FullNodeRpcClient.create(self_hostname, rpc_port, path, config)
    try:
        community_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[2]
        farmer_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[1]
        pool_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[0]

        pool_amounts = int(calculate_pool_reward(uint32(0)) / 2)
        farmer_amounts = int(calculate_base_farmer_reward(uint32(0)) / 2)
        community_amounts = int(calculate_base_community_reward(uint32(0)) / 2)
        print(farmer_prefarm.amount, farmer_amounts)
        assert farmer_amounts == farmer_prefarm.amount // 2
        assert pool_amounts == pool_prefarm.amount // 2
        assert community_amounts == community_prefarm.amount // 2
        address1 = "xcc1rdatypul5c642jkeh4yp933zu3hw8vv8tfup8ta6zfampnyhjnusxdgns6"  # Key 1
        address2 = "xcc1duvy5ur5eyj7lp5geetfg84cj2d7xgpxt7pya3lr2y6ke3696w9qvda66e"  # Key 2
        address3 = "xcc1duvy5ur5eyj7lp5geetfg84cj2d7xgpxt7pya3lr2y6ke3696w9qvda66e"  # Key 3

        ph1 = decode_puzzle_hash(address1)
        ph2 = decode_puzzle_hash(address2)
        ph3 = decode_puzzle_hash(address3)

        p_community_2 = Program.to(
            binutils.assemble(f"(q . ((51 0x{ph1.hex()} {community_amounts}) (51 0x{ph2.hex()} {community_amounts})))")
        )
        p_farmer_2 = Program.to(
            binutils.assemble(f"(q . ((51 0x{ph1.hex()} {farmer_amounts}) (51 0x{ph2.hex()} {farmer_amounts})))")
        )
        p_pool_2 = Program.to(
            binutils.assemble(f"(q . ((51 0x{ph1.hex()} {pool_amounts}) (51 0x{ph2.hex()} {pool_amounts})))")
        )

        p_solution = Program.to(binutils.assemble("()"))

        sb_community = SpendBundle([CoinSolution(community_prefarm, p_community_2, p_solution)], G2Element())
        sb_farmer = SpendBundle([CoinSolution(farmer_prefarm, p_farmer_2, p_solution)], G2Element())
        sb_pool = SpendBundle([CoinSolution(pool_prefarm, p_pool_2, p_solution)], G2Element())

        print(sb_pool, sb_farmer, sb_community)
        res = await client.push_tx(sb_farmer)
        # res = await client.push_tx(sb_pool)

        print(res)
        up = await client.get_coin_records_by_puzzle_hash(farmer_prefarm.puzzle_hash, True)
        uf = await client.get_coin_records_by_puzzle_hash(pool_prefarm.puzzle_hash, True)
        uc = await client.get_coin_records_by_puzzle_hash(pool_community.puzzle_hash, True)
        print(up)
        print(uf)
        print(uc)
    finally:
        client.close()


asyncio.run(main())
