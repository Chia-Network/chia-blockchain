import asyncio
from blspy import G2Element
from clvm_tools import binutils

from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from src.types.blockchain_format.program import Program
from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle
from src.util.bech32m import decode_puzzle_hash

from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.config import load_config
from src.rpc.full_node_rpc_client import FullNodeRpcClient
from src.util.ints import uint32


async def main():
    rpc_port = 8555
    self_hostname = "localhost"
    path = DEFAULT_ROOT_PATH
    config = load_config(path, "config.yaml")
    client = await FullNodeRpcClient.create(self_hostname, rpc_port, path, config)
    try:
        farmer_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[1]
        pool_prefarm = (await client.get_block_record_by_height(1)).reward_claims_incorporated[0]

        pool_amounts = int(calculate_pool_reward(uint32(0)) / 2)
        farmer_amounts = int(calculate_base_farmer_reward(uint32(0)) / 2)
        print(farmer_prefarm.amount, farmer_amounts)
        assert farmer_amounts == farmer_prefarm.amount // 2
        assert pool_amounts == pool_prefarm.amount // 2

        address1 = "txch1k50glwkdffp2mrqq64rsgjtxj4waphuf72stqayz4qqk6mj9hd4qp7lrek"  # Gene wallet (m/12381/8444/2/51):
        address2 = "txch1430mtj60hvzyuyz4t45dyxwjdjsvphhl2fgreyry362reca4zpkszhjd3e"  # farmer1 key (m/12381/8444/2/51)

        ph1 = decode_puzzle_hash(address1)
        ph2 = decode_puzzle_hash(address2)

        p_farmer_2 = Program.to(
            binutils.assemble(f"(q . ((51 0x{ph1.hex()} {farmer_amounts}) (51 0x{ph2.hex()} {farmer_amounts})))")
        )
        p_pool_2 = Program.to(
            binutils.assemble(f"(q . ((51 0x{ph1.hex()} {pool_amounts}) (51 0x{ph2.hex()} {pool_amounts})))")
        )

        p_solution = Program.to(binutils.assemble("()"))

        sb_farmer = SpendBundle([CoinSolution(farmer_prefarm, p_farmer_2, p_solution)], G2Element())
        sb_pool = SpendBundle([CoinSolution(pool_prefarm, p_pool_2, p_solution)], G2Element())

        print(sb_pool, sb_farmer)
        # res = await client.push_tx(sb_farmer)
        # res = await client.push_tx(sb_pool)

        # print(res)
        up = await client.get_coin_records_by_puzzle_hash(farmer_prefarm.puzzle_hash, True)
        uf = await client.get_coin_records_by_puzzle_hash(pool_prefarm.puzzle_hash, True)
        print(up)
        print(uf)
    finally:
        client.close()


asyncio.run(main())
